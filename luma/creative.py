"""Versioned creative facts. Deterministic gates only; never claims visual quality."""
import copy
import json
import hashlib

SCHEMA_VERSION = 1
RULE_VERSION = 'short-drama-facts-v1'
PREFERENCES = ['动作应可观察，优先用行为呈现情绪', '对白应推进冲突或新信息，避免重复解释',
               '开场与集尾钩子属于短剧创作偏好，不以固定秒数强迫所有作品',
               '保留已批准的人物身份、服装、地点、道具与知识状态，不静默化解上游矛盾',
               '模型适配只翻译，不反向改写叙事事实；画面一致性须基于真实素材另验']
PROJECTIONS = {'description': 'action', 'duration': 'durationSec', 'framing': 'shotSize', 'camera': 'cameraMovement'}
IDENTITY = ('shotId', 'sceneId', 'episodeId')


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def requires_spec(project):
    return bool(project.get('creative_context') or any(e.get('creative_spec') for e in project['episodes'])
                or any(s.get('creative_spec') for s in project['shots']))


def state_outputs(project):
    """Narrative dependencies, not camera tweaks, approval flags or selected media."""
    outputs={};upstream=None
    for ep in project['episodes']:
        spec=ep.get('creative_spec')
        if not spec:continue
        facts=[]
        for s in project['shots']:
            if s['episode_id']!=ep['id']:continue
            facts.append({'id':s['id'],'description':s.get('description'),'dialogue':s.get('dialogue'),
                          'lines':[{'who':l.get('speaker_asset_id'),'text':l['text']} for l in s.get('lines') or []],
                          'facts':{k:s.get('creative_spec',{}).get(k) for k in ('action','visualSubject','locationId','propIds','continuityIn','continuityOut')}})
        outputs[ep['id']]=digest({'id':ep['id'],'script':ep['script'],'entry':spec.get('entry_state'),
                                 'end':spec.get('planned_end_state'),'shots':facts,'upstream':upstream})
        upstream=outputs[ep['id']]
    return outputs


def continuity_status(project, episode_id):
    outputs=state_outputs(project);previous=None;upstream_pending=False;looks=[]
    for ep in project['episodes']:
        spec=ep.get('creative_spec')
        if not spec:continue
        expected_id=previous['id'] if previous else None
        expected_digest=outputs[expected_id] if previous else None
        carry_digest=digest(looks)
        entry_digest=digest(spec.get('entry_state'))
        link=spec.get('state_link')
        if link:
            changed=(link.get('resolution')=='unconfirmed' or link.get('upstream_episode_id')!=expected_id or link.get('upstream_digest')!=expected_digest
                     or link.get('entry_digest')!=entry_digest or ('carry_digest' in link and link['carry_digest']!=carry_digest))
        else:
            # Read pre-upgrade projects without rewriting them. First write freezes this baseline.
            changed=bool(previous and spec.get('entry_state')!=previous['creative_spec'].get('planned_end_state'))
        pending=bool(changed or upstream_pending)
        status={'requires_confirmation':pending,'upstream_episode_id':expected_id,'upstream_digest':expected_digest,
                'entry_digest':entry_digest,'carry_digest':carry_digest,'carry_inputs':copy.deepcopy(looks),'upstream_pending':upstream_pending,
                'reason':'跨集状态的上游尚未确认' if upstream_pending else '跨集状态已变化，请比较后确认' if changed else None}
        if ep['id']==episode_id:return status
        character_ids={a['id'] for a in project['assets'] if a['kind']=='character'}
        looks.append({'episode_id':ep['id'],'shots':[{'id':s['id'],'subject_state':s.get('creative_spec',{}).get('subjectState'),'looks':{aid:vid for aid,vid in s.get('asset_bindings',{}).items() if aid in character_ids}} for s in project['shots'] if s['episode_id']==ep['id']]})
        previous=ep;upstream_pending=pending
    return {'requires_confirmation':False,'upstream_episode_id':None,'upstream_digest':None,'entry_digest':None,'carry_digest':None,'carry_inputs':[],'upstream_pending':False,'reason':None}


def track_dependencies(old, project, confirmation=None):
    """Clients cannot certify their own state. Only the confirmation endpoint may change a link."""
    if old and requires_spec(old) and not project.get('creative_context') and old.get('creative_context'):
        raise ValueError('不能移除已有作品的创作规则')
    old_episodes={e['id']:e for e in (old or project)['episodes']}
    baseline=old or project;outputs=state_outputs(baseline)
    previous=None;links={}
    for ep in baseline['episodes']:
        spec=ep.get('creative_spec')
        if not spec:continue
        links[ep['id']]=copy.deepcopy(spec.get('state_link') or {
            'upstream_episode_id':previous['id'] if previous else None,
            'upstream_digest':outputs[previous['id']] if previous else None,
            'entry_digest':digest(spec.get('entry_state')),
            'resolution':'unconfirmed' if continuity_status(baseline,ep['id'])['requires_confirmation'] else 'source'})
        prior_status=continuity_status(baseline,ep['id'])
        links[ep['id']].setdefault('carry_digest',prior_status.get('carry_digest'))
        links[ep['id']].setdefault('carry_inputs',prior_status.get('carry_inputs',[]))
        previous=ep
    for ep in project['episodes']:
        spec=ep.get('creative_spec');prior=old_episodes.get(ep['id'],{}).get('creative_spec')
        if prior and not spec:raise ValueError('不能移除已有剧集的创作规格')
        if not spec:continue
        if confirmation and ep['id']==confirmation:
            continue  # This link was verified against a current preview in the backend.
        if old and spec.get('state_link') is not None and spec.get('state_link')!=((prior or {}).get('state_link')):
            raise ValueError('跨集状态必须经独立比较确认，不能直接改写确认记录')
        if ep['id'] in links:spec['state_link']=links[ep['id']]
        else:
            status=continuity_status(project,ep['id'])
            spec['state_link']={k:status[k] for k in ('upstream_episode_id','upstream_digest','entry_digest','carry_digest','carry_inputs')}
            spec['state_link']['resolution']='unconfirmed' if status['requires_confirmation'] else 'source'


def require_current_state(project, episode_id):
    status=continuity_status(project,episode_id)
    if status['requires_confirmation']:raise ValueError(status['reason'])


def synchronize(shot, previous=None):
    """Keep the ordinary editor and rich facts in one record; conflicting edits fail."""
    spec = shot.get('creative_spec')
    old = (previous or {}).get('creative_spec')
    if old and not spec:
        raise ValueError('不能丢弃已有镜头创作规格')
    if not spec:
        return
    if not isinstance(spec, dict):
        raise ValueError('镜头创作规格必须是对象')
    for key, field in PROJECTIONS.items():
        if old:
            changed = shot.get(key) != previous.get(key)
            rich_changed = spec.get(field) != old.get(field)
            if changed and rich_changed and shot.get(key) != spec.get(field):
                raise ValueError('镜头文字与创作规格冲突：' + key)
            if changed:
                spec[field] = copy.deepcopy(shot.get(key))
            elif rich_changed:
                shot[key] = copy.deepcopy(spec.get(field))
        elif key not in shot:
            shot[key] = copy.deepcopy(spec.get(field))
    # The editable dialogue is authoritative. Never restore a deleted line from imported text.
    if 'lines' in shot:
        lines = [{'who': l.get('speaker_asset_id'), 'text': l['text']} for l in shot['lines']]
        dialogue = lines[0] if len(lines) == 1 else lines or None
        if old and spec.get('dialogue') != old.get('dialogue') and spec.get('dialogue') != dialogue:
            raise ValueError('创作对白与逐句对白冲突，请明确修改逐句内容')
        spec['dialogue'] = dialogue
    elif previous and shot.get('dialogue') != previous.get('dialogue'):
        spec['dialogue'] = {'who': None, 'text': shot.get('dialogue', '')} if shot.get('dialogue') else None
    if old and any(spec.get(k) != old.get(k) for k in IDENTITY):
        raise ValueError('不能修改导入镜头的来源编号或所属场景')


def merge_spec(target, patch):
    if not isinstance(patch, dict):
        raise ValueError('镜头创作规格必须是对象')
    old = target.get('creative_spec', {})
    if old and any(k in patch and patch[k] != old.get(k) for k in IDENTITY):
        raise ValueError('修订不能替换来源镜头或场景')
    return {**copy.deepcopy(old), **copy.deepcopy(patch)}


RISK_LABELS = {'fine-handwork':'手部精细动作','crowd':'多人群像','fast-motion':'快速运动','text-on-screen':'画面中的文字',
    'water':'水与液体','fire':'火焰与烟雾','animal':'动物','vehicle':'交通工具','night':'夜景低光','reflection':'镜面与反射'}


def risk_text(flag):
    return '源剧本标记的制作风险：' + RISK_LABELS.get(flag, flag)


def issues(project):
    """Structural errors block; imported production risks remain advisory."""
    out = []
    assets = {a['id']: a for a in project['assets']}
    episodes = {e['id']:e for e in project['episodes']}
    for shot in project['shots']:
        spec = shot.get('creative_spec')
        if spec is None:
            if requires_spec(project):
                out.append({'shot_id':shot['id'],'severity':'error','rule':'missing-creative-spec','message':'此作品新增镜头必须包含完整创作规格'})
            continue
        sid = shot['id']
        screenplay=episodes[shot['episode_id']].get('creative_spec',{}).get('screenplay',{})
        scenes={s['id'] for s in screenplay.get('scenes',[])}
        def add(message, severity='error', rule='structure', sid=sid):
            out.append({'shot_id': sid, 'severity': severity, 'rule': rule, 'message': message})
        if not isinstance(spec, dict) or spec.get('schema_version') != SCHEMA_VERSION:
            add('不支持的创作规格版本'); continue
        if len(json.dumps(spec, ensure_ascii=False, allow_nan=False)) > 30000:
            add('单镜创作规格过大'); continue
        for key in ('shotId', 'sceneId', 'narrativePurpose', 'action', 'visualSubject', 'locationId'):
            if not isinstance(spec.get(key), str) or not spec[key].strip():
                add('缺少创作字段：' + key)
        if scenes and spec.get('sceneId') not in scenes:
            add('镜头引用了不存在的场景')
        if screenplay and spec.get('episodeId')!=screenplay.get('ep'):
            add('创作规格的剧集编号不一致')
        if spec.get('shotId') != sid:
            add('创作规格与镜头编号不一致')
        for key, field in PROJECTIONS.items():
            if shot.get(key) != spec.get(field): add('编辑字段与创作规格不一致：' + key)
        for key in ('continuityIn', 'continuityOut'):
            if spec.get(key) is not None and not isinstance(spec[key], str): add('连续性状态必须是文字或空值')
        for key in ('composition', 'cameraAngle', 'cameraPosition', 'lighting', 'emotion', 'subjectState', 'sound'):
            if spec.get(key) is not None and not isinstance(spec[key], str): add('创作字段类型无效：' + key)
        props = spec.get('propIds', [])
        if not isinstance(props, list) or not all(isinstance(x, str) for x in props):
            add('道具引用必须是编号数组'); props = []
        references = [spec.get('visualSubject'), spec.get('locationId'), *props]
        for aid in references:
            if aid not in assets: add('创作引用不存在：' + str(aid))
            elif aid not in shot.get('asset_ids', []): add('创作实体未绑定到本镜：' + aid)
        if spec.get('locationId') in assets and assets[spec['locationId']]['kind'] != 'scene': add('地点必须绑定场景资产')
        for aid in props:
            if aid in assets and assets[aid]['kind'] != 'prop': add('道具编号类型错误：' + aid)
        flags = spec.get('riskFlags', [])
        if not isinstance(flags, list) or not all(isinstance(x, str) for x in flags):
            add('制作风险必须是文字数组')
        else:
            for flag in flags: add(risk_text(flag), 'warning', 'source-production-risk')
        for aid, vid in shot.get('asset_bindings', {}).items():
            asset = assets.get(aid)
            if asset and asset['kind'] == 'character':
                version = next((v for v in asset['versions'] if v['id'] == vid), {})
                if not version.get('outfit'):
                    add('角色未明确选择造型：' + aid)
    for episode in project['episodes']:
        target=episode.get('creative_spec',{}).get('screenplay',{}).get('targetSec')
        seconds=sum(s['duration'] for s in project['shots'] if s['episode_id']==episode['id'])
        if type(target) in (int,float) and target>0 and not target*.85<=seconds<=target*1.15:
            out.append({'episode_id':episode['id'],'shot_id':None,'severity':'warning','rule':'source-duration-policy',
                        'message':'当前分镜总时长偏离来源目标超过15%，请审阅节奏；不自动缩短镜头'})
    return out


def validate(project):
    context = project.get('creative_context')
    if context is not None and (not isinstance(context, dict) or context.get('schema_version') != SCHEMA_VERSION):
        raise ValueError('不支持的作品创作规格版本')
    errors = [i for i in issues(project) if i['severity'] == 'error']
    if errors:
        raise ValueError(errors[0]['shot_id'] + '：' + errors[0]['message'])


def scoped_context(project, episode_id):
    if not requires_spec(project):
        return None
    context = copy.deepcopy(project.get('creative_context') or {'schema_version': SCHEMA_VERSION})
    ep = next(e for e in project['episodes'] if e['id'] == episode_id)
    # Never send later episodes' scripts/knowledge to this episode's creative run.
    context['episode'] = copy.deepcopy(ep.get('creative_spec', {}))
    context['rules'] = {'version': RULE_VERSION, 'hard': ['stable-ids', 'registered-references', 'explicit-outfit', 'preserve-unmodified-facts'],
                        'advisory': ['source-production-risk', 'source-duration-policy'], 'creative_preferences':PREFERENCES,
                        'planned_end_state_is_not_current_knowledge':True, 'reviewer_may_diagnose_but_not_silently_rewrite':True,
                        'visual_quality_verified': False}
    return context
