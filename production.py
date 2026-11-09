"""Versioned production objects. No model calls and no destructive migration."""
import copy
import hashlib
import json
import time
import uuid
import creative

LEGACY_SHOT_FIELDS = ('description', 'duration', 'framing', 'camera', 'dialogue', 'lines', 'asset_ids', 'asset_bindings', 'continuity_from')
SHOT_FIELDS = LEGACY_SHOT_FIELDS + ('creative_spec',)
FRAME_MODES = ('references', 'start_own', 'start_continuity')  # how a video starts; not part of the text plan basis
BRIEF_DEFAULTS ={'format':'16:9', 'method':'mixed', 'style':''}
CHARACTER_VIEWS=('front','side','back','three_quarter')
VOICE_IDS=('alloy','ash','ballad','coral','echo','fable','onyx','nova','sage','shimmer','verse','marin','cedar')

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def normalize(p):
    p.setdefault('creative_brief', copy.deepcopy(BRIEF_DEFAULTS))
    for a in p['assets']:
        a.setdefault('version', 1)
        a.setdefault('versions', [{'id': a['id']+'-v1', 'description': a.get('description',''), 'name': a['name'], 'file': None, 'created': 0}])
        a.setdefault('selected_version', a['versions'][-1]['id'])
    for s in p['shots']:
        s.setdefault('takes', [])
        s.setdefault('selected_takes', {})
        s.setdefault('asset_bindings', {a['id']:a['selected_version'] for a in p['assets'] if a['id'] in s.get('asset_ids',[])})
        for kind in ('video','audio','image'):
            if s.get(kind) and not any(t['kind']==kind and t['file']==s[kind] for t in s['takes']):
                tid=s['id']+'-'+kind+'-'+digest(s[kind])[:12]
                s['takes'].append({'id':tid,'kind':kind,'file':s[kind],'label':'原有素材','source':'import','created':0})
                s['selected_takes'][kind]=tid
        s.setdefault('trim_start',0)
        s.setdefault('frame_mode','references')
        if s.get('clip'):
            sync_clip_selection(s)
        if isinstance(s.get('lines'),list):s['dialogue']=dialogue_text(p,s['lines'])
    return p

def preserve_history(old, p):
    """General edits cannot delete or rewrite prior paid/imported candidates."""
    for field, history in (('assets','versions'),('shots','takes')):
        originals={x['id']:x for x in old[field]}
        for item in p[field]:
            prev=originals.get(item['id'])
            if not prev:continue
            prior={v['id']:v for v in prev.get(history,[])}
            for v in item.get(history,[]):
                if v['id'] in prior and v!=prior[v['id']]:raise ValueError('历史素材不可改写，请创建新版本')
            item[history]=copy.deepcopy(list(prior.values()))+[v for v in item.get(history,[]) if v['id'] not in prior]
            if field=='assets' and any(item.get(k)!=prev.get(k) for k in ('name','description')):
                chosen=next(v for v in item['versions'] if v['id']==item['selected_version'])
                if (chosen.get('description',''),chosen.get('name')) != (item.get('description',''),item['name']):
                    v={**chosen,'id':uuid.uuid4().hex,'name':item['name'],'description':item.get('description',''),'created':time.time()}
                    item['versions'].append(v);item['selected_version']=v['id']
                item['version']=len(item['versions'])
    for s in p['shots']:
        s['asset_bindings']={a['id']:s.get('asset_bindings',{}).get(a['id'],a['selected_version']) for a in p['assets'] if a['id'] in s.get('asset_ids',[])}

def validate(p, media_path):
    brief=p['creative_brief']
    if not isinstance(brief,dict) or brief.get('format') not in ('16:9','9:16') or brief.get('method') not in ('mixed','illustrated','video'):
        raise ValueError('请选择有效的画幅和制作方式')
    if not isinstance(brief.get('style'),str) or len(brief['style'])>2000:raise ValueError('视觉风格最多 2000 字')
    assets={a['id']:a for a in p['assets']}
    for a in p['assets']:
        ids=[v['id'] for v in a['versions']]
        if len(ids)!=len(set(ids)) or a['selected_version'] not in ids:raise ValueError('资产版本无效')
        for v in a['versions']:
            if v.get('file'):media_path(v['file'])
            views=v.get('views',{})
            if not isinstance(views,dict) or not set(views)<=set(CHARACTER_VIEWS):raise ValueError('角色视角无效')
            for file in views.values():media_path(file)
            if not isinstance(v.get('outfit',''),str) or len(v.get('outfit',''))>200:raise ValueError('服装名称最多 200 字')
            if v.get('voice_id','alloy') not in VOICE_IDS:raise ValueError('角色音色无效')
    for s in p['shots']:
        ids=[t['id'] for t in s['takes']]
        if len(ids)!=len(set(ids)):raise ValueError('素材候选 ID 重复')
        for t in s['takes']:
            if t.get('kind') not in ('image','video','audio'):raise ValueError('候选素材类型无效')
            media_path(t['file'])
        sources=s.get('segment_sources',{})
        if not isinstance(sources,dict):raise ValueError('片段素材选择无效')
        for segment_id,choice in sources.items():
            if not isinstance(segment_id,str) or not isinstance(choice,dict) or set(choice)-{'take_id','trim_start','basis'} or not {'take_id','trim_start'}<=set(choice):raise ValueError('片段素材选择无效')
            if choice['take_id'] not in ids or type(choice['trim_start']) not in (int,float) or not 0<=choice['trim_start']<=86400:raise ValueError('片段素材或起点无效')
        chosen={t['id']:t for t in s['takes']}
        for kind,tid in s['selected_takes'].items():
            t=chosen.get(tid)
            if not t or t['kind']!=kind or s.get(kind)!=t['file']:raise ValueError('选用素材与候选版本不一致')
            if kind in ('image','video'):check_full_take(s,t)
        for t in s['takes']:
            if t['kind'] in ('image','video') and s.get(t['kind'])==t['file']:check_full_take(s,t)
        for aid,vid in s['asset_bindings'].items():
            if aid not in assets or vid not in {v['id'] for v in assets[aid]['versions']}:raise ValueError('镜头资产版本不存在')
        check_lines(p,s)
        if s.get('frame_mode') not in FRAME_MODES:raise ValueError('画面承接方式无效')
        if s.get('clip'):checked_clip(s,s['clip'])
        if type(s.get('trim_start',0)) not in (int,float) or not 0<=s.get('trim_start',0)<=86400:raise ValueError('素材裁剪起点无效')
        if s.get('continuity_from') and s['continuity_from'] not in {x['id'] for x in p['shots'] if x['episode_id']==s['episode_id'] and x['id']!=s['id']}:raise ValueError('承接镜头必须属于本集')

    parents={s['id']:s.get('continuity_from') for s in p['shots']}
    for sid in parents:
        seen=set();current=sid
        while current:
            if current in seen:raise ValueError('镜头承接不能形成循环')
            seen.add(current);current=parents.get(current)

MAX_LINES=50
LINE_TEXT_MAX=2000

def dialogue_text(p, lines):
    """What older readers see in s['dialogue']: 'name: text' for a character, bare text for narration."""
    names={a['id']:a['name'] for a in p['assets']}
    return '\n'.join((names.get(l.get('speaker_asset_id'),'')+'：' if l.get('speaker_asset_id') in names else '')+str(l.get('text','')) for l in lines)

def check_lines(p, s):
    lines=s.get('lines')
    if lines is None:return
    chars={a['id'] for a in p['assets'] if a['kind']=='character'}
    if not isinstance(lines,list) or len(lines)>MAX_LINES:raise ValueError(f'对白最多 {MAX_LINES} 句')
    ids=[]
    for l in lines:
        if not isinstance(l,dict) or not isinstance(l.get('id'),str) or not l['id'] or not isinstance(l.get('text'),str) or not l['text'].strip():raise ValueError('每句对白都需要编号和文字')
        if len(l['text'])>LINE_TEXT_MAX:raise ValueError(f'每句对白最多 {LINE_TEXT_MAX} 字')
        sp=l.get('speaker_asset_id')
        if sp is not None and sp not in chars:raise ValueError('说话人必须是作品里的角色资产，旁白请留空')
        ids.append(l['id'])
        if l.get('audio_take_id'):
            if not any(t['id']==l['audio_take_id'] and t['kind']=='audio' for t in s.get('takes',[])):raise ValueError('逐句音轨必须来自本镜音频候选')
            if type(l.get('audio_duration')) not in (int,float) or not 0<l['audio_duration']<=3600:raise ValueError('逐句音轨缺少有效实测时长')
    if len(ids)!=len(set(ids)):raise ValueError('对白编号重复')

def line_timings(lines, duration):
    """Start/end seconds per line inside a shot, split by text length. An estimate for subtitles, not speech alignment."""
    weights=[max(1,len(l['text'].strip())) for l in lines]
    total=sum(weights);cursor=0;out=[]
    for i,w in enumerate(weights):
        end=duration if i==len(weights)-1 else cursor+duration*w/total
        out.append((cursor,end));cursor=end
    return out

def reference_plan(p, shot_id, kind='video'):
    """Explicit roles for a Dify media app. Frames are never inferred from what happens to exist:
    'references' sends only reference_image; 'first_frame' sends exactly one frame and nothing else
    (same rule as waoowaoo: reference and frame modes are not mixed). Dropped inputs are listed, not hidden."""
    s=next(s for s in p['shots'] if s['id']==shot_id)
    if kind=='audio':
        # The connected TTS app uses a fixed voice. Do not upload pictures or imply voice cloning.
        omitted=[{'asset_id':aid,'version_id':vid,'reason':'当前单人配音只读取对白，不使用参考素材或克隆音色'}
                 for aid,vid in s['asset_bindings'].items()]
        return {'mode':'text_only','items':[],'omitted':omitted}
    previous=next((x for x in p['shots'] if x['id']==s.get('continuity_from')),None)
    assets=[];ignored=[]
    for aid,vid in s['asset_bindings'].items():
        a=next(a for a in p['assets'] if a['id']==aid)
        v=next(v for v in a['versions'] if v['id']==vid)
        if v.get('file') or v.get('views'):
            if a['kind']=='voice':ignored.append({'asset_id':aid,'version_id':vid,'reason':'声音样本不是参考图片，当前画面与视频工作流不接收声音样本'})
            else:
                files=list(dict.fromkeys(v.get('views',{}).values() or ([v['file']] if v.get('file') else [])))
                for file in files:assets.append({'file':file,'role':'reference_image','source':'asset','asset_id':aid,'version_id':vid})
    mode=s.get('frame_mode','references') if kind=='video' else 'references'
    if mode!='references':
        if mode=='start_own':
            if not s.get('image'):raise ValueError('「从本镜已选图开始」需要先选用一张本镜画面作为首帧')
            frame={'file':s['image'],'role':'first_frame','source':'shot_image','shot_id':s['id']}
        else:
            if not previous or not previous.get('image'):raise ValueError('「从承接镜头开始」需要承接镜头已选用画面')
            frame={'file':previous['image'],'role':'first_frame','source':'continuity','shot_id':previous['id']}
        dropped=ignored+[{k:r[k] for k in ('asset_id','version_id')}|{'reason':'首帧模式不与参考图混用，该参考图未发送'} for r in assets]
        if mode=='start_own' and previous and previous.get('image'):
            dropped.append({'shot_id':previous['id'],'reason':'首帧模式不与参考图混用，承接镜头画面未发送'})
        return {'mode':'first_frame','items':[frame],'omitted':dropped}
    items=list(assets);omitted=list(ignored)
    if s.get('image'):items.append({'file':s['image'],'role':'reference_image','source':'shot_image','shot_id':s['id']})
    if previous:
        if previous.get('image'):items.append({'file':previous['image'],'role':'reference_image','source':'continuity','shot_id':previous['id']})
        else:omitted.append({'shot_id':previous['id'],'reason':'承接镜头没有已选用画面（视频的尾帧暂未提取），无法作为参考'})
    return {'mode':'references','items':items,'omitted':omitted}

def media_references(p, shot_id, kind='video'):
    return reference_plan(p,shot_id,kind)['items']

def audio_text(s):
    """Preflight the currently connected single-speaker TTS before any external operation."""
    lines=s.get('lines')
    if isinstance(lines,list):
        if len({l.get('speaker_asset_id') for l in lines})>1:
            raise ValueError('当前配音仅支持单一说话人，多角色音色尚未配置；未提交生成')
        text='\n'.join(l.get('text','').strip() for l in lines)
    else:text=(s.get('dialogue') or '').strip()
    if not 1<=len(text)<=4000:
        raise ValueError('配音对白须为 1–4000 字；未提交生成')
    return text

def speech_request(snapshot,line_id=None):
    s=next(s for s in snapshot['shots'] if s['id']==snapshot['target_shot_id'])
    if line_id:
        line=next((l for l in s.get('lines') or [] if l['id']==line_id),None)
        if not line:raise ValueError('对白句子不存在')
        text=audio_text({'lines':[line]});speaker=line.get('speaker_asset_id')
    else:
        text=audio_text(s);speaker=next(iter({l.get('speaker_asset_id') for l in s.get('lines') or []}),None)
    a=next((a for a in snapshot['assets'] if a['id']==speaker),None)
    version=next((v for v in a['versions'] if v['id']==s.get('asset_bindings',{}).get(speaker)),None) if a else None
    return {'line_id':line_id,'speaker_asset_id':speaker,'text':text,'voice_id':(version or {}).get('voice_id','alloy'),
            'model':'gpt-4o-mini-tts-2025-12-15'}

def audio_schedule(s,duration_lookup=None):
    lines=s.get('lines') or []
    if not any(l.get('audio_take_id') for l in lines):return []
    takes={t['id']:t for t in s.get('takes',[])};cursor=0;items=[]
    for l in lines:
        t=takes.get(l.get('audio_take_id'))
        if not t or t['kind']!='audio':raise ValueError('逐句配音尚未齐备，请为每句选择音轨或改用整镜音轨')
        duration=duration_lookup(t['file']) if duration_lookup else l['audio_duration']
        start=l.get('audio_start',cursor)
        if type(start) not in (int,float) or start<cursor:raise ValueError('逐句音轨起点不能重叠或为负数')
        end=start+duration
        if end>s['duration']+.05:raise ValueError('逐句配音超过镜头时长，请延长镜头或调整音轨')
        items.append({'line_id':l['id'],'text':l['text'],'speaker_asset_id':l.get('speaker_asset_id'),'file':t['file'],'start':start,'end':end})
        cursor=end
    return items

SNAPSHOT_V=2  # v2: shot plans depend on the exact asset version a shot is bound to

def snapshot_basis(snapshot):
    keys=['episode_id','script','assets','shots','scope','target_shot_id','instruction','creative_brief']
    if snapshot.get('basis_v'):keys.append('basis_v')  # legacy snapshots keep their original digest
    if 'creative_context' in snapshot:keys.append('creative_context')
    if 'continuity_dependencies' in snapshot:keys.append('continuity_dependencies')
    return digest({k:snapshot.get(k) for k in keys})

def effective_version(a, shots, target_id=None):
    """Version a plan sees: the target shot's pin, else a neighbour's pin, else the asset's current choice."""
    for s in sorted(shots,key=lambda s:s['id']!=target_id):
        v=next((v for v in a['versions'] if v['id']==s.get('asset_bindings',{}).get(a['id'])),None)
        if v:return v
    return next(v for v in a['versions'] if v['id']==a['selected_version'])

def delivery_basis(snapshot):
    # Match what is actually rendered; task history and unused candidates cannot stale a film.
    return digest({'format':snapshot.get('creative_brief',BRIEF_DEFAULTS)['format'],
                   'shots':[{**{k:s.get(k) for k in ('id','duration','video','image','audio','trim_start','dialogue')},
                             # Only an explicit cut joins the digest, so shots without one keep their existing basis.
                             **({'clip':clip_of(s)} if s.get('clip') else {}),
                             **({'lines':s['lines']} if s.get('lines') else {})} for s in snapshot['shots']]})

def review_basis(snapshot):
    # Creative approval identity is separate from bytes/render identity.
    return digest({'shots':[{'id':s['id'],'basis':take_basis(s)} for s in snapshot['shots']],
                   'dependencies':snapshot.get('continuity_dependencies',{}),'script':snapshot.get('script',''),'brief':snapshot.get('creative_brief',BRIEF_DEFAULTS),
                   'context':creative.scoped_context(snapshot,snapshot['episode_id']) if snapshot.get('creative_context') else None})


def readiness(p, episode_id):
    from episodes import production_snapshot
    import preparation
    snap=production_snapshot(p,episode_id);items=[]
    state_status=creative.continuity_status(p,episode_id)
    for i,s in enumerate(snap['shots'],1):
        has_visual=bool(s.get('image') or s.get('video'))
        audio_issue=None
        try:line_audio=audio_schedule(s)
        except ValueError as e:audio_issue=str(e);line_audio=[]
        prep_issue=preparation.current_issue(p,s)
        ready=not prep_issue and has_visual and s.get('approved') and not s.get('needs_review') and not audio_issue and not state_status['requires_confirmation']
        items.append({'shot_id':s['id'],'number':i,'has_visual':has_visual,'ready':bool(ready),'basis':take_basis(s),
                      'reason':state_status['reason'] or prep_issue or audio_issue or ('尚未选用画面' if not has_visual else '需要复核' if s.get('needs_review') else '尚未审核' if not s.get('approved') else None),
                      'audio_schedule':line_audio,'dialogue_without_audio':bool(s.get('dialogue') and not s.get('audio') and not line_audio)})
    refs=[(a,v) for a in p['assets'] for v in a['versions'] if v['id']==a['selected_version'] and (v.get('file') or v.get('views'))]
    return {'episode_id':episode_id,'script_ready':bool(snap['script'].strip()),'asset_count':len(p['assets']),
            'reference_count':len(refs),'visual_reference_count':sum(a['kind']!='voice' for a,v in refs),'shots':items,'ready_count':sum(x['ready'] for x in items),
            'can_export':bool(items) and all(x['ready'] for x in items),'delivery_basis':delivery_basis(snap),'review_basis':review_basis(snap),'continuity':state_status}

def scope(p, episode_id, shot_id=None, instruction='', legacy=False):
    from episodes import production_snapshot
    snap=production_snapshot(p,episode_id)
    creative.require_current_state(p,snap['episode_id'])
    if shot_id:
        ss=snap['shots'];i=next((i for i,s in enumerate(ss) if s['id']==shot_id),None)
        if i is None:raise ValueError('目标镜头不在本集')
        if ss[i].get('locked'):raise ValueError('请先解除镜头锁定')
        snap['shots']=ss[max(0,i-1):i+2]
        snap.update(scope='shot',target_shot_id=shot_id,instruction=instruction)
        used={aid for s in snap['shots'] for aid in s.get('asset_ids',[])}
        snap['assets']=[a for a in snap['assets'] if a['id'] in used]
    else:snap['scope']='episode'
    # Only semantic inputs influence freshness, never approval flags, candidates or UI state.
    scoped=snap['shots']
    if 'continuity_dependencies' in snap:snap['continuity_dependencies']={s['id']:snap['continuity_dependencies'][s['id']] for s in scoped}
    snap['shots']=[{'id':s['id'],**semantic_shot(s)} for s in scoped]
    context=creative.scoped_context(p,episode_id or snap['episode_id'])
    if context is not None:snap['creative_context']=context
    if legacy:
        snap['assets']=[{k:copy.deepcopy(a.get(k)) for k in ('id','kind','name','description','selected_version','versions')} for a in snap['assets']]
    else:
        # Only the version a plan actually depends on is part of its basis; other history cannot stale it.
        target=shot_id if shot_id else None;assets=[]
        for a in snap['assets']:
            v=effective_version(a,scoped,target) if shot_id else next(v for v in a['versions'] if v['id']==a['selected_version'])
            assets.append({'id':a['id'],'kind':a['kind'],'name':v['name'],'description':v.get('description',''),'selected_version':v['id'],'versions':[copy.deepcopy(v)]})
        snap['assets']=assets;snap['basis_v']=SNAPSHOT_V
    snap['basis']=snapshot_basis(snap)
    return snap

def fresh(p, snapshot):
    if not snapshot.get('basis'):return p['revision']==snapshot['revision']
    legacy=snapshot.get('basis_v')!=SNAPSHOT_V
    try:return scope(p,snapshot['episode_id'],snapshot.get('target_shot_id'),snapshot.get('instruction',''),legacy)['basis']==snapshot['basis']
    except ValueError:return False

ADOPT_MODES = ('append', 'replace', 'merge')
PLAN_TEXT_FIELDS = ('description', 'duration', 'framing', 'camera', 'dialogue', 'lines', 'asset_ids', 'creative_spec')


def new_plan_shot(incoming, episode_id, previous=None):
    spec=incoming.get('creative_spec')
    sid=spec.get('shotId') if isinstance(spec,dict) else uuid.uuid4().hex
    return {**{k:copy.deepcopy(incoming[k]) for k in PLAN_TEXT_FIELDS if k in incoming},
            'id':sid,'episode_id':episode_id,'asset_ids':copy.deepcopy(incoming.get('asset_ids',[])),
            **({'asset_bindings':{aid:vid for aid,vid in previous.get('asset_bindings',{}).items() if aid in incoming.get('asset_ids',[])}} if previous else {}),
            'approved':False,'needs_review':True,'locked':False}


def update_plan_links(p, episode_id):
    ep=next(e for e in p['episodes'] if e['id']==episode_id);spec=ep.get('creative_spec')
    if not spec:return
    spec.setdefault('source_segments',copy.deepcopy(spec.get('segments',[])))
    groups={}
    for s in p['shots']:
        if s['episode_id']!=episode_id:continue
        shot_spec=s.get('creative_spec',{})
        key=(shot_spec.get('segmentId'),shot_spec.get('sceneId'))
        group=groups.setdefault(key,{'segmentId':key[0],'sceneId':key[1],'shot_ids':[]})
        group['shot_ids'].append(s['id'])
    spec['segments']=list(groups.values())
    spec['storyboard_source_status']='historical'


def validate_creative_plan(p, episode_id, plan_shots, mode):
    """Validate the effective plan, including retained fields of merges, before promising adoption."""
    if not creative.requires_spec(p):return
    if not plan_shots:raise ValueError('方案没有镜头，不能覆盖已有创作计划')
    candidate=copy.deepcopy(p);current=[s for s in candidate['shots'] if s['episode_id']==episode_id]
    originals={s['id']:s for s in p['shots']}
    def new_shot(s):return new_plan_shot(s,episode_id,originals.get((s.get('creative_spec') or {}).get('shotId')))
    if mode=='replace':
        candidate['shots']=[s for s in candidate['shots'] if s['episode_id']!=episode_id]+[new_shot(s) for s in plan_shots]
    elif mode=='append':candidate['shots'].extend(new_shot(s) for s in plan_shots)
    else:
        for i,incoming in enumerate(plan_shots):
            if i<len(current):
                target=current[i]
                if target.get('locked'):continue
                apply_plan_text(target,incoming,PLAN_TEXT_FIELDS)
            else:candidate['shots'].append(new_shot(incoming))
    ids=[s['id'] for s in candidate['shots']]
    if len(ids)!=len(set(ids)):raise ValueError('方案镜头编号重复，不能覆盖现有镜头')
    originals={s['id']:s for s in p['shots']}
    for s in candidate['shots']:creative.synchronize(s,originals.get(s['id']))
    normalize(candidate)
    validate(candidate,lambda _file:None)  # candidates contain only existing media; new plan media is not accepted
    creative.validate(candidate)

def plan_adoption(p, episode_id, plan_shots, mode='append'):
    """Pure description of what adopting a whole-episode plan would do. Preview and apply share this,
    so what the user sees is what happens. Never mutates p.
    append  - keep every current shot, add the plan's shots after them (the previous behaviour)
    replace - swap the episode's shots for the plan; refused if any shot has media or is locked
    merge   - plan shot i updates current shot i's text only (identity, media, pins stay); extras are added"""
    if mode not in ADOPT_MODES:raise ValueError('采纳方式无效')
    current=[s for s in p['shots'] if s['episode_id']==episode_id]
    items=[];blocked=None
    if mode=='append':
        items=[{'action':'new','index':i} for i in range(len(plan_shots))]
    elif mode=='replace':
        items=[{'action':'new','index':i} for i in range(len(plan_shots))]+[{'action':'remove','old_id':s['id']} for s in current]
        if any(s.get('locked') for s in current):blocked='有镜头已锁定，请先解除锁定再整版替换'
        elif any(s.get('takes') or s.get('image') or s.get('video') or s.get('audio') for s in current):
            blocked='有镜头已保存素材候选，整版替换会让它们脱离作品；请改用「按序合并」或先处理这些镜头'
    else:
        for i in range(len(plan_shots)):
            old=current[i] if i<len(current) else None
            items.append({'action':'skip_locked','old_id':old['id'],'index':i} if old and old.get('locked')
                         else {'action':'update','old_id':old['id'],'index':i} if old else {'action':'new','index':i})
        items+=[{'action':'keep','old_id':s['id']} for s in current[len(plan_shots):]]
    for x in items:
        if 'index' in x:x['description']=plan_shots[x['index']]['description']
        if x.get('old_id'):x['old_description']=next(s['description'] for s in current if s['id']==x['old_id'])
    if not blocked:
        try:validate_creative_plan(p,episode_id,plan_shots,mode)
        except (ValueError,TypeError,KeyError) as e:blocked='方案不能采纳：'+str(e)
    counts={k:sum(x['action']==k for x in items) for k in ('new','update','keep','skip_locked','remove')}
    return {'mode':mode,'items':items,'counts':counts,'blocked':blocked}

def clip_of(s):
    """The cut a shot delivers: which candidate and which window of it. An explicit s['clip'] wins;
    otherwise it is derived from the selected media and trim_start, so older shots deliver exactly as before."""
    explicit=s.get('clip')
    takes={t['id']:t for t in s.get('takes',[])}
    if explicit:
        t=takes[explicit['source_take_id']]
        return {'source_take_id':t['id'],'kind':t['kind'],'file':t['file'],'trim_start':explicit.get('trim_start',0),'trim_end':explicit.get('trim_end')}
    kind='video' if s.get('video') else 'image' if s.get('image') else None
    if not kind:return None
    for t in s.get('takes',[]):
        if t['kind']==kind and t['file']==s[kind]:check_full_take(s,t)
    return {'source_take_id':s.get('selected_takes',{}).get(kind),'kind':kind,'file':s[kind],
            'trim_start':s.get('trim_start',0) if kind=='video' else 0,'trim_end':None}

def sync_clip_selection(s):
    """A saved cut is the selected visual everywhere, including older mismatched records."""
    clip=checked_clip(s,s['clip'])
    t=next(t for t in s['takes'] if t['id']==clip['source_take_id'])
    other='image' if t['kind']=='video' else 'video'
    s['selected_takes'][t['kind']]=t['id'];s[t['kind']]=t['file']
    s.pop(other,None);s['selected_takes'].pop(other,None)
    s['trim_start']=clip['trim_start'] if t['kind']=='video' else 0


def apply_plan_text(target, incoming, fields):
    """Structured lines own dialogue; an explicitly changed plain dialogue switches back to text."""
    before=copy.deepcopy(target)
    if 'lines' not in incoming and 'dialogue' in incoming and incoming['dialogue']!=target.get('dialogue',''):
        target.pop('lines',None)
    target.update({k:copy.deepcopy(incoming[k]) for k in fields if k in incoming and k!='creative_spec'})
    if 'creative_spec' in incoming and 'creative_spec' in fields:target['creative_spec']=creative.merge_spec(before,incoming['creative_spec'])
    creative.synchronize(target,before)
    clear_stale_audio(target,before)
    if target.get('duration')!=before.get('duration'):
        chosen=target.get('selected_takes',{})
        for kind in ('image','video'):
            t=next((t for t in target.get('takes',[]) if t['id']==chosen.get(kind)),None)
            if t:
                try:check_full_take(target,t)
                except ValueError:
                    chosen.pop(kind,None);target.pop(kind,None);target.pop('clip',None)


def clear_stale_audio(s,before):
    before_lines=[(l.get('id'),l.get('text'),l.get('speaker_asset_id')) for l in before.get('lines') or []]
    after_lines=[(l.get('id'),l.get('text'),l.get('speaker_asset_id')) for l in s.get('lines') or []]
    if (s.get('dialogue','')!=before.get('dialogue','') or before_lines!=after_lines) and before.get('audio') and s.get('audio')==before.get('audio'):
        s.pop('audio',None);s.get('selected_takes',{}).pop('audio',None)


def set_clip(s, source_take_id, trim_start=0, trim_end=None):
    if s.get('locked'):raise ValueError('请先解除镜头锁定')
    s['clip']=checked_clip(s,{'source_take_id':source_take_id,'trim_start':trim_start,'trim_end':trim_end})
    sync_clip_selection(s)
    s.update(approved=False,needs_review=True)

def checked_clip(s, c):
    t=next((t for t in s.get('takes',[]) if t['id']==c.get('source_take_id')),None)
    if not t or t['kind'] not in ('video','image'):raise ValueError('剪辑片段必须引用本镜的画面或视频候选')
    check_full_take(s,t)
    a,b=c.get('trim_start',0),c.get('trim_end')
    if type(a) not in (int,float) or not 0<=a<=86400 or (b is not None and (type(b) not in (int,float) or not a<b<=86400)):
        raise ValueError('裁剪起止无效：起点不能为负，终点须大于起点')
    return {'source_take_id':t['id'],'trim_start':a,'trim_end':b}

def semantic_shot(s):
    fields={k:copy.deepcopy(s.get(k)) for k in LEGACY_SHOT_FIELDS}
    if fields.get('lines') is not None:
        fields['lines']=[{k:v for k,v in l.items() if k not in ('audio_take_id','audio_duration','audio_start')} for l in fields['lines']]
    if 'creative_spec' in s:fields['creative_spec']=copy.deepcopy(s['creative_spec'])
    return fields

def take_basis(s):return digest({**semantic_shot(s),**({'preparation':s['preparation']} if 'preparation' in s else {})})

def add_take(s, kind, file, label='导入素材', source='import', basis=None, job_id=None):
    if s.get('locked'):raise ValueError('请先解除镜头锁定')
    if job_id and any(t.get('job_id')==job_id for t in s['takes']):return
    t={'id':uuid.uuid4().hex,'kind':kind,'file':file,'label':label[:100],'source':source,'created':time.time(),'basis':basis or take_basis(s),'job_id':job_id}
    s['takes'].append(t)
    return t

def select_take(s, tid):
    if s.get('locked'):raise ValueError('请先解除镜头锁定')
    t=next((t for t in s['takes'] if t['id']==tid),None)
    if not t:raise ValueError('素材候选不存在')
    check_full_take(s,t)
    s['selected_takes'][t['kind']]=tid;s[t['kind']]=t['file']
    if t['kind']=='audio':
        for l in s.get('lines') or []:
            for k in ('audio_take_id','audio_duration','audio_start'):l.pop(k,None)
    # A cut made on another candidate must not silently follow a new selection; the new one starts uncut.
    if t['kind'] in ('image','video') and s.get('clip') and s['clip']['source_take_id']!=tid:
        s.pop('clip');s['trim_start']=0
    if t['kind'] in ('image','video'):
        other='image' if t['kind']=='video' else 'video'
        s.pop(other,None);s['selected_takes'].pop(other,None)
    s.update(approved=False,needs_review=True)

def check_full_take(s,t):
    segment=t.get('generation_segment')
    if segment and (segment['start']!=0 or abs(segment['end']-s['duration'])>.001):raise ValueError('这是局部生成片段，需合成完整镜头后再选用，不能直接替代整镜')
