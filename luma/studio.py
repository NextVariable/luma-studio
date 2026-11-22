"""Local-only studio: transactional project state, durable jobs and FFmpeg export."""
import argparse, copy, json, os, re, shutil, sqlite3, sys, tempfile, uuid, time, threading, subprocess, mimetypes, hashlib
from pathlib import Path
from contextlib import nullcontext
from decimal import Decimal
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
from .providers import Dify, PROVIDERS, encode_context, key_for, key_env_for, provider_identity, RemoteTaskFailed, UncertainRun
from .contracts import validate
from .episodes import normalize_project, validate_episodes, changed_episodes, production_snapshot
from . import production
from . import creative
from . import preparation
from . import domestic_media, fal_media
from . import assembly
from . import continuity
from . import local_storage
from . import openai_direct
from . import blocking, visual, art, quality, comparison, evidence
from . import sample_scene
from . import generation_quote

ROOT = Path(__file__).resolve().parent.parent
# LUMA_DATA selects an independent library. AUTEUR_DATA is the legacy name and still works.
DATA_ENV = os.environ.get('LUMA_DATA') or os.environ.get('AUTEUR_DATA')
DATA = Path(DATA_ENV) if DATA_ENV else ROOT/'data'
MEDIA = DATA/'media'
DB = DATA/'studio.sqlite'
LOCK = threading.RLock()
# An explicit data directory is a separate library and keeps its own Dify settings.
DATA_ISOLATED = DATA_ENV is not None

def env_file():
    return DATA/'.env' if DATA_ISOLATED else ROOT/'.env'

def uid(): return uuid.uuid4().hex

def init():
    MEDIA.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, project_id TEXT, body TEXT NOT NULL, created REAL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, state TEXT, payload TEXT, result TEXT, error TEXT, created REAL, updated REAL, dedupe TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS spending(id INTEGER PRIMARY KEY CHECK(id=1), remaining INTEGER NOT NULL, used INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS import_previews(id TEXT PRIMARY KEY, digest TEXT NOT NULL, body TEXT NOT NULL, created REAL, applied_project_id TEXT);
        CREATE TABLE IF NOT EXISTS candidate_reviews(project_id TEXT NOT NULL, shot_id TEXT NOT NULL, take_id TEXT NOT NULL, body TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS candidate_reviews_shot ON candidate_reviews(project_id,shot_id);
        INSERT OR IGNORE INTO spending VALUES(1,0,0);
        ''')
        c.execute("UPDATE jobs SET state='interrupted',error='服务重启；外部调用结果待核实，避免重复收费',updated=? WHERE state IN ('running','submitting')",(time.time(),))
        for row in c.execute("SELECT * FROM jobs WHERE kind='audio' AND state='interrupted'").fetchall():
            result=json.loads(row['result'] or '{}')
            if not result.get('candidate_file') and recover_direct_audio(row,json.loads(row['payload']),result):
                c.execute("UPDATE jobs SET result=?,error=NULL WHERE id=?",(json.dumps(result),row['id']))

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

def connect():
    c=sqlite3.connect(DB,timeout=30,factory=ClosingConnection)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    return c

def project(pid):
    with connect() as c: r=c.execute('SELECT body FROM projects WHERE id=?',(pid,)).fetchone()
    if not r: raise ValueError('作品不存在')
    return production.normalize(normalize_project(json.loads(r['body'])))

def spending():
    with connect() as c:return dict(c.execute('SELECT remaining,used FROM spending WHERE id=1').fetchone())

def set_spending(limit):
    if type(limit) is not int or not 0<=limit<=20:raise ValueError('每批授权 0–20 次外部工作流操作；0 表示暂停')
    with LOCK,connect() as c:c.execute('UPDATE spending SET remaining=? WHERE id=1',(limit,))
    return spending()

def spend():
    # Claim immediately before external submission; unknown results never refund automatically.
    with LOCK,connect() as c:
        if c.execute('UPDATE spending SET remaining=remaining-1,used=used+1 WHERE id=1 AND remaining>0').rowcount!=1:
            raise ValueError('付费调用已暂停或本批授权已用尽；请在设置中明确授权次数')

def validate_project(p):
    if not isinstance(p.get('title'),str) or not 1 <= len(p['title'].strip()) <= 200: raise ValueError('作品名称不能为空，最多 200 字')
    if not isinstance(p.get('script'),str) or len(p['script']) > 100000: raise ValueError('剧本最多 10 万字')
    if len(p.get('shots',[])) > 200: raise ValueError('本地版最多 200 个镜头')
    if not isinstance(p.get('assets'),list) or not isinstance(p.get('shots'),list): raise ValueError('资产与镜头必须是数组')
    validate_episodes(p)
    for a in p['assets']:
        if not isinstance(a,dict) or not isinstance(a.get('id'),str) or not a['id'] or a.get('kind') not in ('character','scene','style','prop','voice') or not isinstance(a.get('name'),str) or not a['name'].strip(): raise ValueError('资产 ID、名称或类型无效')
    ids=[a['id'] for a in p['assets']]
    if len(ids)!=len(set(ids)): raise ValueError('资产 ID 重复')
    shot_ids=[s['id'] for s in p['shots']]
    if len(shot_ids)!=len(set(shot_ids)): raise ValueError('镜头 ID 重复')
    for s in p['shots']:
        if type(s.get('duration')) not in (float,int) or not 1 <= s['duration'] <= 60: raise ValueError('镜头时长为 1–60 秒')
        if not set(s.get('asset_ids',[])).issubset(set(ids)): raise ValueError('镜头引用了不存在的资产')
        for field in ('video','audio'):
            if s.get(field): media_path(s[field])

def save(p, expected, candidate_only=False, state_confirmation=None, source_confirmation=False, media_confirmation=None,
         reference_actions_only=False):
    submitted={s['id']:copy.deepcopy(s) for s in p['shots']}
    production.normalize(normalize_project(p))
    validate_project(p)
    with LOCK, connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()
        previous_refs=[]
        if old:
            old=production.normalize(normalize_project(json.loads(old['body'])))
            if old['revision'] != expected: raise ValueError('作品已更新，请刷新后再编辑')
            previous_refs=(old['creative_brief'].get('visual_bible') or {}).get('references',[])
            if reference_actions_only:
                bible=p['creative_brief'].get('visual_bible')
                incoming_refs=bible.get('references',[]) if isinstance(bible,dict) else []
                if incoming_refs!=previous_refs:
                    raise ValueError('请在素材中使用批准或替换参考图操作')
            oldshots={s['id']:s for s in old['shots']}
            for s in p['shots']:creative.synchronize(s,oldshots.get(s['id']))
            production.preserve_history(old,p)
            if any(s.get('locked') and s['id'] not in {x['id'] for x in p['shots']} for s in old['shots']): raise ValueError('不能删除锁定镜头')
            # Shots are pinned to immutable asset versions; only a change of what the asset is (its kind) reaches them unasked.
            oldkinds={a['id']:a['kind'] for a in old['assets']}
            changed={a['id'] for a in p['assets'] if a['id'] in oldkinds and a['kind']!=oldkinds[a['id']]}
            context_changed=p['script'] != old['script'] or p.get('creative_context')!=old.get('creative_context') or any(p['creative_brief'].get(k)!=old['creative_brief'].get(k) for k in ('style','method'))
            affected_episodes=changed_episodes(old,p)
            for s in p['shots']:
                production.check_lines(p,s)
                prev=oldshots.get(s['id'])
                raw=submitted[s['id']]
                if s.get('visual_review_basis')!=(prev or {}).get('visual_review_basis'):raise ValueError('不能直接改写画面复核记录')
                if s.get('media_basis')!=(prev or {}).get('media_basis') and media_confirmation!=s['id']:raise ValueError('请通过「确认沿用画面」操作确认，不能直接改写画面确认记录')
                if prev and prev.get('preparation') and not s.get('preparation'):raise ValueError('已有制作准备不能直接移除，请按当前镜头重新确认')
                if s.get('segment_sources',{})!=(prev or {}).get('segment_sources',{}) and not source_confirmation:raise ValueError('请通过片段选用操作确认素材，不能直接改写确认记录')
                prior_lines={l['id']:l for l in (prev or {}).get('lines') or []}
                for line in s.get('lines') or []:
                    before=prior_lines.get(line['id'])
                    if before and any(line.get(k)!=before.get(k) for k in ('text','speaker_asset_id')):
                        for k in ('audio_take_id','audio_duration','audio_start'):line.pop(k,None)
                if prev:production.clear_stale_audio(s,prev)
                if prev and prev.get('lines') and raw.get('lines')==prev['lines'] and raw.get('dialogue')!=prev.get('dialogue'):
                    raise ValueError('逐句对白已启用，请编辑逐句内容或明确切回文本对白')
                if prev and prev.get('locked') and s != prev:
                    # Unlock is a separate explicit action before editing.
                    test=dict(s); test['locked']=True
                    if candidate_only:test['takes']=prev['takes']
                    if test != prev: raise ValueError('请先解除镜头锁定')
                if context_changed or s['episode_id'] in affected_episodes or set(s.get('asset_ids',[])) & changed:
                    s['needs_review']=True; s['approved']=False
                if prev and any(s.get(k)!=prev.get(k) for k in ('episode_id','description','duration','camera','dialogue','asset_ids','asset_bindings','framing','video','image','audio','trim_start','clip','lines','creative_spec')):
                    s['approved']=False; s['needs_review']=True
            changed_shots={s['id'] for s in p['shots'] if s['id'] in oldshots and any(s.get(k)!=oldshots[s['id']].get(k) for k in (*production.SHOT_FIELDS,'video','image'))}
            for s in p['shots']:
                if s.get('continuity_from') in changed_shots:s.update(approved=False,needs_review=True)
            c.execute('INSERT INTO versions VALUES(?,?,?,?)',(uid(),p['id'],json.dumps(old,ensure_ascii=False),time.time()))
        creative.track_dependencies(old,p,state_confirmation)
        for s in p['shots']:
            before=next((x for x in (old or {}).get('shots',[]) if x['id']==s['id']),None)
            production.update_audio_selection(p,s,before)
            if before and (s.get('preparation') or s.get('creative_spec') or s.get('continuity_from')) and continuity.basis(old,before)!=continuity.basis(p,s):s.update(approved=False,needs_review=True)
        for s in p['shots']:
            if creative.continuity_status(p,s['episode_id'])['requires_confirmation']:
                if submitted[s['id']].get('approved') and not submitted[s['id']].get('needs_review'):
                    prior=next((x for x in (old or {}).get('shots',[]) if x['id']==s['id']),{})
                    if not prior.get('approved') or prior.get('needs_review'):raise ValueError('跨集状态待确认，不能审核此镜头')
                s.update(approved=False,needs_review=True)
        production.stamp_media({x['id']:x for x in (old or {}).get('shots',[])},p,media_confirmation)
        for s in p['shots']:
            prior=next((x for x in (old or {}).get('shots',[]) if x['id']==s['id']),{})
            if submitted[s['id']].get('approved') and not submitted[s['id']].get('needs_review') and (not prior.get('approved') or prior.get('needs_review')):
                issue=preparation.current_issue(p,s) or production.media_issue(s)
                if issue:raise ValueError(issue)
        validate_project(p)
        production.validate(p,media_path,previous_refs)
        creative.validate(p)
        originals={s['id']:s for s in (old or {}).get('shots',[])}
        for s in p['shots']:
            before=originals.get(s['id'],{})
            if s.get('preparation') is not None and s.get('preparation')!=before.get('preparation'):
                preparation.validate(p,s,s['preparation'],media_path)
                s.update(approved=False,needs_review=True)
        for s in p['shots']:
            if s.get('approved') and not s.get('needs_review'):s['visual_review_basis']=continuity.visual_basis(p,s)
        p['revision']=(old['revision'] if old else 0)+1
        p['updated']=time.time()
        c.execute('INSERT OR REPLACE INTO projects VALUES(?,?)',(p['id'],json.dumps(p,ensure_ascii=False)))
    return p

def create(title,script):
    return save({'id':uid(),'title':title,'script':script,'assets':[],'shots':[],'mode':'director','revision':0},0)

def add_shot(pid, episode_id, expected, fields):
    with LOCK:
        p=project(pid)
        if p['revision']!=expected:raise ValueError('作品已更新，请刷新后再添加镜头')
        ep=next((e for e in p['episodes'] if e['id']==episode_id),None)
        if not ep:raise ValueError('剧集不存在')
        s={'id':uid(),'episode_id':episode_id,'description':fields.get('description','写下这一镜要发生的事。'),
           'duration':fields.get('duration',5),'framing':fields.get('framing','中景'),'camera':fields.get('camera','固定机位'),
           'dialogue':'','asset_ids':[],'approved':False,'needs_review':True,'locked':False}
        if creative.requires_spec(p):
            screenplay=ep.get('creative_spec',{}).get('screenplay',{})
            scene=next((x for x in screenplay.get('scenes',[]) if x['id']==fields.get('scene_id')),None)
            if screenplay.get('scenes') and not scene:raise ValueError('请选择本集的场景')
            location=scene.get('location') if scene else fields.get('location_id')
            subject=fields.get('subject_id')
            s['asset_ids']=list(dict.fromkeys([subject,location]))
            assets={a['id']:a for a in p['assets']}
            if subject not in assets or location not in assets:raise ValueError('请选择已建立的主体和地点')
            s['asset_bindings']={aid:assets[aid]['selected_version'] for aid in s['asset_ids']}
            if assets[subject]['kind']=='character':
                version=next((v for v in assets[subject]['versions'] if v['id']==fields.get('version_id')),None)
                if not version or not version.get('outfit'):raise ValueError('请选择角色的明确造型')
                s['asset_bindings'][subject]=version['id']
            s['creative_spec']={'schema_version':creative.SCHEMA_VERSION,'shotId':s['id'],
                'episodeId':screenplay.get('ep',episode_id),'sceneId':scene['id'] if scene else fields.get('scene_id'),
                'segmentId':s['id'],'narrativePurpose':fields.get('purpose'),'visualSubject':subject,
                'locationId':location,'propIds':[],'dialogue':None,'riskFlags':[],
                **{field:s[key] for key,field in creative.PROJECTIONS.items()}}
        index=max((i for i,shot in enumerate(p['shots']) if shot['episode_id']==episode_id),default=len(p['shots'])-1)+1
        p['shots'].insert(index,s)
        production.update_plan_links(p,episode_id)
        return {'project':save(p,expected),'shot_id':s['id']}

def open_preparation(pid,sid,kind='video'):
    p=project(pid);s=preparation.shot_of(p,sid)
    draft=copy.deepcopy(s.get('preparation') or preparation.seed(p,sid,kind))
    needs_confirmation=bool(preparation.current_issue(p,s))
    if needs_confirmation:
        draft['character_versions']=preparation.character_versions(p,s)
        available={r['reference_id'] for r in preparation.catalog(p,s)}
        for segment in draft['segments']:
            segment['references']=[r for r in segment['references'] if r['reference_id'] in available]
    return {'revision':p['revision'],'basis':preparation.basis(s),'plan':draft,
            'requires_reconfirmation':needs_confirmation,'narrative_description':s['description'],'narrative_duration':s['duration'],
            'characters':[{'asset_id':a['id'],'version_id':s['asset_bindings'][a['id']],'name':a['name'],
                           'outfit':next(v for v in a['versions'] if v['id']==s['asset_bindings'][a['id']]).get('outfit','未设定')}
                          for a in p['assets'] if a['kind']=='character' and a['id'] in s['asset_bindings']],
            'references':preparation.catalog(p,s),'fal_configured':bool(fal_media.key()),
            'domestic_configured':{name:bool(domestic_media.key(name)) for name in domestic_media.KEYS},
            'models':{name:{**copy.deepcopy(model),'connected':bool(fal_media.key() if model.get('provider')=='fal' else domestic_media.key(model['provider']) if model.get('provider') in domestic_media.KEYS else key_for(model['kind']))}
                      for name,model in preparation.MODELS.items()},
            'status':preparation.report(p,sid,media_path,lambda kind:bool(key_for(kind)))}

def save_preparation(pid,sid,expected,plan,source_basis):
    with LOCK:
        p=project(pid);s=preparation.shot_of(p,sid)
        if p['revision']!=expected or source_basis!=preparation.basis(s):raise ValueError('镜头已变化，请重新打开制作准备')
        if s.get('locked'):raise ValueError('请先解除镜头锁定')
        plan=copy.deepcopy(plan)
        if plan.get('character_versions')!=preparation.character_versions(p,s):raise ValueError('造型版本已变化，请重新确认本镜绑定')
        creative.require_current_state(p,s['episode_id'])
        plan['dependency_basis']=continuity.basis(p,s)
        plan['basis']=source_basis;preparation.validate(p,s,plan,media_path)
        s['preparation']=plan;p=save(p,expected)
        return {'project':p,'status':preparation.report(p,sid,media_path,lambda kind:bool(key_for(kind)))}

def initialize_preparation(pid,expected,episode_id=None):
    with LOCK:
        p=project(pid)
        if p['revision']!=expected:raise ValueError('作品已更新，请重新读取')
        if episode_id and episode_id not in {e['id'] for e in p['episodes']}:raise ValueError('剧集不存在')
        count=0
        for s in p['shots']:
            if episode_id and s['episode_id']!=episode_id:continue
            if s.get('preparation') or s.get('locked'):continue
            s['preparation']=preparation.seed(p,s['id']);count+=1
        if count:p=save(p,expected)
        return {'project':p,'initialized':count,'ready_count':sum(preparation.report(p,s['id'],media_path,lambda k:bool(key_for(k)))['ready'] for s in p['shots'])}

def continuity_preview(pid,episode_id):
    p=project(pid);ep=next((e for e in p['episodes'] if e['id']==episode_id),None)
    if not ep or not ep.get('creative_spec'):raise ValueError('剧集没有跨集创作状态')
    status=creative.continuity_status(p,episode_id)
    upstream=next((e for e in p['episodes'] if e['id']==status['upstream_episode_id']),None)
    preview={'project_id':pid,'episode_id':episode_id,'revision':p['revision'],'status':status,
             'before_carry':copy.deepcopy(ep['creative_spec'].get('state_link',{}).get('carry_inputs')),'after_carry':copy.deepcopy(status.get('carry_inputs',[])),
             'before':copy.deepcopy(ep['creative_spec'].get('entry_state')),
             'after':copy.deepcopy(upstream['creative_spec'].get('planned_end_state')) if upstream else None}
    preview['digest']=production.digest(preview)
    return preview

def confirm_continuity(pid,episode_id,expected,preview_digest,resolution,reason):
    with LOCK:
        preview=continuity_preview(pid,episode_id)
        if preview['revision']!=expected or preview['digest']!=preview_digest:raise ValueError('跨集状态预览已变化，请重新比较')
        if preview['status']['upstream_pending']:raise ValueError('请先确认上游跨集状态')
        if resolution not in ('inherit','keep'):raise ValueError('请选择继承新状态或保留原状态')
        if resolution=='keep' and (not isinstance(reason,str) or not 1<=len(reason.strip())<=2000):raise ValueError('保留原跨集状态须说明理由')
        p=project(pid);ep=next(e for e in p['episodes'] if e['id']==episode_id)
        if resolution=='inherit':ep['creative_spec']['entry_state']=preview['after']
        ep['creative_spec']['state_link']={k:preview['status'][k] for k in ('upstream_episode_id','upstream_digest','carry_digest','carry_inputs')}
        ep['creative_spec']['state_link'].update(entry_digest=creative.digest(ep['creative_spec'].get('entry_state')),resolution=resolution,
                                                reason=reason.strip() if isinstance(reason,str) else '',confirmed_revision=expected)
        return save(p,expected,state_confirmation=episode_id)

def preview_drama_import(bundle):
    from .drama_import import convert
    try:
        preview=convert(bundle)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('短剧包字段缺失或格式不正确，请检查来源文件后重新导入') from exc
    validate_project(preview['project']);production.validate(preview['project'],media_path)
    token=uid();digest=production.digest(preview)
    # Keep source and converted facts together; the confirmation never rereads mutable desktop files.
    with connect() as c:c.execute('INSERT INTO import_previews VALUES(?,?,?,?,NULL)',(token,digest,json.dumps({'preview':preview,'bundle':bundle},ensure_ascii=False),time.time()))
    return {'id':token,'digest':digest,'summary':preview['summary'],'warnings':preview['warnings'],
            'mapping':{'action':'画面描述','shotSize':'景别','cameraMovement':'运镜','dialogue':'逐句对白',
                       'narrativePurpose/composition/continuityIn/continuityOut/sound':'保留于镜头创作规格','characters/outfits/assets':'共享资产及固定造型版本'},
            'sample':preview['project']['shots'][0],'shot_ids':[s['id'] for s in preview['project']['shots']],'asset_names':{a['id']:a['name'] for a in preview['project']['assets']}}

def apply_drama_import(token,digest):
    with LOCK:
        with connect() as c:row=c.execute('SELECT * FROM import_previews WHERE id=?',(token,)).fetchone()
        if not row or row['digest']!=digest:raise ValueError('导入预览已失效，请重新检查')
        data=json.loads(row['body']);preview=data['preview'];p=preview['project']
        if row['applied_project_id']:return project(row['applied_project_id'])
        if production.digest(preview)!=digest:raise ValueError('导入预览内容已变化')
        with connect() as c:existing=c.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()
        if existing:
            p=json.loads(existing['body'])
            if p.get('creative_context',{}).get('source_digest')!=preview['digest']:raise ValueError('导入作品编号冲突')
        else:p=save(p,0)
        with connect() as c:c.execute('UPDATE import_previews SET applied_project_id=? WHERE id=?',(p['id'],token))
        return p

def adoptable_plan(pid, jid, expected, mode):
    """Shared by preview and apply: the same checks, so a preview never promises what apply would refuse."""
    p=project(pid)
    if p['revision'] != expected: raise ValueError('作品已更新，请刷新后再采纳')
    with connect() as c: row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
    if not row or row['project_id'] != pid or row['state'] != 'succeeded' or row['kind'] not in ('script','assets','shots','revision'): raise ValueError('没有可采纳的成功任务')
    if jid in p.get('applied',[]): raise ValueError('这条结果已采纳')
    snapshot=json.loads(row['payload'])['snapshot']
    if not production.fresh(p,snapshot): raise ValueError('工作流基于旧版本，请以当前作品重新运行')
    if mode is not None and (row['kind']!='shots' or snapshot.get('scope')!='episode'):raise ValueError('采纳方式只适用于整集分镜方案')
    return p,row,snapshot,validate(row['kind'],json.loads(row['result'])['result'])

def adoption_preview(pid, jid, expected, mode='append'):
    with LOCK:
        p,row,snapshot,result=adoptable_plan(pid,jid,expected,mode)
        episode_id=snapshot.get('episode_id') or p['episodes'][0]['id']
        return production.plan_adoption(p,episode_id,result['shots'],mode)

def revision_media_impact(p,before,after):
    rows=[]
    visual_changed=production.content_basis(before)!=production.content_basis(after)
    current_segments={seg['id']:(index,seg) for index,seg in enumerate((after.get('preparation') or {}).get('segments',[]),1)}
    takes={t['id']:t for t in before.get('takes',[])}
    def visual_quote(kind,segment=None):
        if segment:
            model=segment['model']
            provider=preparation.MODELS.get(model,{}).get('provider')
            if not provider:return None
            duration=segment['end']-segment['start'] if kind=='video' else None
        else:
            selected=takes.get(before.get('selected_takes',{}).get(kind),{})
            source=selected.get('source')
            if source == 'minimax':
                return generation_quote.estimate(kind, source, domestic_media.HAILUO, after['duration'])
            if source in domestic_media.KEYS:
                model=selected.get('model',domestic_media.SEEDREAM) if kind=='image' else domestic_media.WAN
                duration=after['duration'] if kind=='video' else None
                if duration is not None and (int(duration)!=duration or not 2<=duration<=15):return None
                return generation_quote.estimate(kind,source,model,duration)
            model=fal_media.IMAGE if kind=='image' else fal_media.VIDEO
            provider='fal'
            duration=after['duration'] if kind=='video' else None
            if kind=='video' and duration not in (5,10):return None
        return generation_quote.estimate(kind,provider,model,duration)

    for kind,label in (('image','整镜图片'),('video','整镜视频')):
        if before.get(kind):
            status='removed' if not after.get(kind) else 'review' if visual_changed or production.media_issue(after) else 'keep'
            rows.append({'label':label,'status':status,'replacement':visual_quote(kind) if status!='keep' else None})
    old_segments={seg['id']:index for index,seg in enumerate((before.get('preparation') or {}).get('segments',[]),1)}
    for sid,source in before.get('segment_sources',{}).items():
        index,segment=current_segments.get(sid,(old_segments.get(sid),None))
        kind=takes.get(source['take_id'],{}).get('kind')
        status='review' if source.get('basis')!=production.take_basis(after) or preparation.current_issue(p,after) else 'keep'
        if not segment:status='removed'
        label=f'片段 {index}' if index is not None else '原片段'
        rows.append({'label':label+' · '+('视频' if kind=='video' else '图片'),
                     'status':status,'replacement':visual_quote(segment['kind'],segment) if segment and status!='keep' else None})
    selected_after={line_id:take['id'] for line_id,take in production.selected_audio(after)}
    before_lines={line['id']:i for i,line in enumerate(before.get('lines') or [],1)}
    after_lines={line['id'] for line in after.get('lines') or []}
    for line_id,take in production.selected_audio(before):
        kept=selected_after.get(line_id)==take['id']
        try:
            can_regenerate=not kept and (line_id is None or line_id in after_lines) and bool(production.audio_text(
                after if line_id is None else {'lines':[line for line in after['lines'] if line['id']==line_id]}))
        except ValueError:
            can_regenerate=False
        rows.append({'label':f'第 {before_lines[line_id]} 句音轨' if line_id is not None else '整镜音轨',
                     'status':'keep' if kept else 'removed',
                     'replacement':generation_quote.estimate('audio','openai',openai_direct.MODELS['audio'])
                     if can_regenerate else None,
                     'replacement_needed':bool(can_regenerate)})
    return rows


def revision_comparison(p, snapshot, result):
    target_id=snapshot.get('target_shot_id')
    if result.get('target_shot_id',target_id)!=target_id:raise ValueError('修改结果不属于目标镜头')
    if result.get('source_revision',snapshot['revision'])!=snapshot['revision']:raise ValueError('修改结果来源版本不一致')
    if result.get('status','creative_approved') not in ('creative_approved','revision_proposed'):raise ValueError('修改方案尚未通过审核')
    if len(result['shots'])!=1:raise ValueError('单镜修订必须只返回一个镜头')
    incoming=result['shots'][0]
    if incoming.get('id',target_id)!=target_id:raise ValueError('修改方案不能替换其他镜头')
    target=next((s for s in p['shots'] if s['id']==target_id),None)
    if not target or target.get('locked'):raise ValueError('目标镜头不存在或已锁定，请先检查')
    after=copy.deepcopy(target)
    production.apply_plan_text(after,incoming,production.PLAN_TEXT_FIELDS)
    after['asset_bindings']={a['id']:target['asset_bindings'].get(a['id'],a['selected_version']) for a in p['assets'] if a['id'] in after['asset_ids']}
    candidate=copy.deepcopy(p);candidate['shots']=[after if s['id']==target_id else s for s in candidate['shots']]
    production.normalize(candidate);production.update_audio_selection(candidate,after,target)
    validate_project(candidate);production.validate(candidate,media_path);creative.validate(candidate)
    changes=[{'field':k,'before':target.get(k),'after':after.get(k)} for k in production.PLAN_TEXT_FIELDS if target.get(k)!=after.get(k)]
    effects=[]
    if preparation.current_issue(candidate,after):effects.append('制作准备需按新镜头重新确认')
    if target.get('audio') and not after.get('audio'):effects.append('原整镜音轨保留为候选，已取消选用')
    if any(target.get(k) and not after.get(k) for k in ('image','video')):effects.append('原画面范围不适用于新时长，保留候选并取消整镜选用')
    if production.content_basis(target)!=production.content_basis(after) and (after.get('image') or after.get('video')):effects.append('当前画面会保留，重新审核前需确认沿用或更换')
    if changes:effects.append('本镜需要重新审核；已有成片保留为历史版本')
    return {'effects':effects,'media_impact':revision_media_impact(candidate,target,after),'target_shot_id':target_id,'number':1+[s['id'] for s in p['shots'] if s['episode_id']==target['episode_id']].index(target_id),
            'changes':changes,'digest':production.digest({'target':target,'after':after,'source':snapshot.get('basis')}),
            'kept_takes':len(target.get('takes',[])),'instruction':snapshot.get('instruction','')}

def revision_preview(pid,jid,expected):
    with LOCK:
        p,row,snapshot,result=adoptable_plan(pid,jid,expected,None)
        if row['kind']!='revision':raise ValueError('只有单镜修改可以查看此预览')
        return revision_comparison(p,snapshot,result)

def apply_job(pid, jid, expected, mode=None, preview_digest=None):
    """Adopt only the validated result of this project's successful source revision.
    mode (whole-episode shot plans only): append (default), replace or merge; see production.plan_adoption."""
    with LOCK:
        p,row,snapshot,result=adoptable_plan(pid,jid,expected,mode)
        if row['kind']=='revision':
            preview=revision_comparison(p,snapshot,result)
            if (json.loads(row['payload']).get('revision_preview_required') or preview_digest is not None) and preview_digest!=preview['digest']:
                raise ValueError('请重新预览修改前后的差异，再确认应用')
            target=next(s for s in p['shots'] if s['id']==snapshot['target_shot_id'])
            if target.get('locked'):raise ValueError('请先解除镜头锁定')
            production.apply_plan_text(target,result['shots'][0],production.PLAN_TEXT_FIELDS)
            target.update(approved=False,needs_review=True)
        elif row['kind']=='shots':
            episode_id=snapshot.get('episode_id') or p['episodes'][0]['id']
            if episode_id not in {e['id'] for e in p['episodes']}: raise ValueError('来源剧集不存在')
            plan=production.plan_adoption(p,episode_id,result['shots'],mode or 'append')
            if plan['blocked']:raise ValueError(plan['blocked'])
            def fresh_shot(shot):
                previous=next((s for s in p['shots'] if s['id']==(shot.get('creative_spec') or {}).get('shotId')),None)
                return production.new_plan_shot(shot,episode_id,previous)
            if plan['mode']=='replace':
                # The previous revision is kept in the versions table by save(), so the old plan stays recoverable.
                first=next((i for i,s in enumerate(p['shots']) if s['episode_id']==episode_id),len(p['shots']))
                rest=[s for s in p['shots'] if s['episode_id']!=episode_id]
                p['shots']=rest[:first]+[fresh_shot(s) for s in result['shots']]+rest[first:]
            elif plan['mode']=='merge':
                current=[s for s in p['shots'] if s['episode_id']==episode_id]
                added=[]
                for x in plan['items']:
                    new=result['shots'][x['index']] if 'index' in x else None
                    if x['action']=='update':
                        target=next(s for s in current if s['id']==x['old_id'])
                        production.apply_plan_text(target,new,production.PLAN_TEXT_FIELDS);target.update(approved=False,needs_review=True)
                    elif x['action']=='new':added.append(fresh_shot(new))
                p['shots'].extend(added)
            else:
                p['shots'].extend(fresh_shot(s) for s in result['shots'])
            production.update_plan_links(p,episode_id)
        else:
            items=([{**a,'kind':'character'} for a in result['characters']]+[{**a,'kind':'scene'} for a in result['scenes']]) if row['kind']=='script' else result['assets']
            for a in items: p['assets'].append({**a,'id':uid(),'version':1})
        p['applied']=[*p.get('applied',[]),jid]
        return save(p,expected)

def shot_camera(body, apply=False):
    p=project(body['project_id'])
    if p['revision']!=body['revision']:raise ValueError('作品已更新，请刷新后再调整机位')
    shot=preparation.shot_of(p,body['shot_id'])
    actors=blocking.layout(p,shot)
    camera=body.get('camera',blocking.current_camera(shot,actors))
    portrait = p['creative_brief']['format'] == '9:16'
    framing = shot.get('framing') or '中景'
    image=blocking.render(camera, actors, portrait, framing)
    if not apply:
        return {'actors':actors,'camera':camera,'image':blocking.preview(image),
                'presets':{name:blocking.preset(name) for name in blocking.choices(actors)}}
    filename=uid()+'.png'
    if shot.get('locked'):raise ValueError('请先解除镜头锁定')
    shot['composition_reference']={'actors':actors,'camera':camera,'file':filename,
                                   'spec':blocking.composition_spec(camera['view'], framing, portrait)}
    path=MEDIA/filename
    try:
        path.write_bytes(image)
        return save(p,body['revision'])
    except Exception:
        path.unlink(missing_ok=True)
        raise


def edit_production(body):
    with LOCK:
        p=project(body['project_id'])
        if p['revision']!=body['revision']:raise ValueError('作品已更新，请刷新')
        action=body['action']
        if action in ('asset_version','asset_select','asset_view','character_look'):
            a=next((a for a in p['assets'] if a['id']==body.get('asset_id')),None)
            if not a:raise ValueError('资产不存在')
            if action=='character_look':
                if a['kind']!='character':raise ValueError('只有角色可以配置视图、服装和音色')
                current=next(v for v in a['versions'] if v['id']==a['selected_version'])
                v={**copy.deepcopy(current),'id':uid(),'created':time.time(),'label':body.get('label','角色造型')[:100]}
                if 'outfit' in body and body['outfit']!=current.get('outfit',''):v.update(views={},file=None)
                for k in ('views','outfit','voice_id'):
                    if k in body:v[k]=body[k]
                a['versions'].append(v)
            elif action=='asset_view':
                if a['kind'] not in ('character','scene'):raise ValueError('只有角色或场景可以添加视图')
                view=body.get('view')
                if view not in visual.allowed_views(a['kind']) or view=='primary':raise ValueError('视图类型无效')
                file=body.get('file')
                visual.image_mime(visual.read_image(media_path(file)))
                current=next(v for v in a['versions'] if v['id']==a['selected_version'])
                v={**copy.deepcopy(current),'id':uid(),'created':time.time(),'name':a['name'],
                   'description':body.get('description',a.get('description','')),
                   'label':body.get('label',view)[:100],
                   'views':{**(current.get('views') or {}),view:file}}
                if not v.get('file'):v['file']=None
                a['versions'].append(v)
            elif action=='asset_version':
                file=body.get('file')
                if file:media_path(file)
                current=next(v for v in a['versions'] if v['id']==a['selected_version'])
                v={**copy.deepcopy(current),'id':uid(),'name':a['name'],'description':body.get('description',a.get('description','')),'file':file,'created':time.time(),'label':body.get('label','新版本')[:100]}
                if file:v['views']={}  # a new general reference replaces the prior view set, but retains voice/outfit identity
                a['versions'].append(v)
            else:
                v=next((v for v in a['versions'] if v['id']==body.get('version_id')),None)
                if not v:raise ValueError('版本不存在')
            a.update(selected_version=v['id'],description=v['description'],name=v['name'],version=len(a['versions']))
        else:
            s=next((s for s in p['shots'] if s['id']==body.get('shot_id')),None)
            if not s:raise ValueError('镜头不存在')
            if s.get('locked'):raise ValueError('请先解除镜头锁定')
            if action=='add_take':
                file=body['file'];media_path(file)
                t=production.add_take(s,body['kind'],file,body.get('label','导入素材'))
                if body.get('line_id'):
                    if body['kind']!='audio' or body['line_id'] not in {l['id'] for l in s.get('lines') or []}:raise ValueError('逐句音轨目标无效')
                    t['line_id']=body['line_id']
            elif action in ('bind_segment_source','bind_segment_sources'):
                choices=body.get('sources') if action=='bind_segment_sources' else {body.get('segment_id'):{'take_id':body.get('take_id'),'trim_start':body.get('trim_start',0)}}
                if not isinstance(choices,dict):raise ValueError('片段素材选择无效')
                issue=preparation.current_issue(p,s)
                if issue:raise ValueError(issue)
                selected_sources={};current_basis=production.take_basis(s)
                for segid,choice in choices.items():
                    if not isinstance(choice,dict):raise ValueError('片段素材选择无效')
                    seg=next((x for x in s.get('preparation',{}).get('segments',[]) if x['id']==segid),None)
                    if not seg:raise ValueError('制作片段不存在')
                    t=next((t for t in s['takes'] if t['id']==choice.get('take_id')),None)
                    if not t or t['kind']!=seg['kind']:raise ValueError('请选择本镜中类型相符的素材')
                    start=choice.get('trim_start',0)
                    if type(start) not in (int,float) or not 0<=start<=86400:raise ValueError('片段素材起点无效')
                    previous=s.get('segment_sources',{}).get(segid)
                    stale=(previous is not None and previous.get('basis')!=current_basis) or (t.get('source')!='import' and t.get('basis')!=current_basis)
                    if stale and body.get('acknowledge_stale') is not True:raise ValueError('存在返工前的片段素材，请检查并明确确认继续使用')
                    selected_sources[segid]={'take_id':t['id'],'trim_start':start,'basis':current_basis}
                if action=='bind_segment_sources':s['segment_sources']=selected_sources
                else:s.setdefault('segment_sources',{}).update(selected_sources)
            elif action=='select_take':production.select_take(s,body['take_id'])
            elif action=='set_frame_mode':s['frame_mode']=body.get('frame_mode')
            elif action=='set_lines':
                lines=body.get('lines')
                if lines is None:s.pop('lines',None)  # back to plain text; the last derived dialogue text is kept
                elif not isinstance(lines,list) or any(not isinstance(line,dict) for line in lines):
                    raise ValueError('逐句对白格式无效')
                else:
                    incoming=[{'id':line.get('id') or uid(),'speaker_asset_id':line.get('speaker_asset_id') or None,
                               'text':line.get('text','')} for line in lines]
                    production.apply_plan_text(s,{'lines':incoming},('lines',))
            elif action=='set_clip':production.set_clip(s,body.get('source_take_id'),body.get('trim_start',0),body.get('trim_end'))
            elif action=='bind_current':
                s['asset_bindings']={a['id']:a['selected_version'] for a in p['assets'] if a['id'] in s.get('asset_ids',[])}
            elif action=='bind_asset_version':
                a=next((a for a in p['assets'] if a['id']==body.get('asset_id') and a['id'] in s['asset_ids']),None)
                if not a or body.get('version_id') not in {v['id'] for v in a['versions']}:raise ValueError('角色版本不属于本镜引用资产')
                s['asset_bindings'][a['id']]=body['version_id']
            elif action=='bind_line_audio':
                line=next((l for l in s.get('lines') or [] if l['id']==body.get('line_id')),None)
                if not line:raise ValueError('对白句子不存在')
                if not body.get('take_id'):
                    for k in ('audio_take_id','audio_duration','audio_start'):line.pop(k,None)
                else:
                    t=next((t for t in s['takes'] if t['id']==body['take_id'] and t['kind']=='audio'),None)
                    if not t:raise ValueError('音轨候选不存在')
                    issue=production.audio_take_issue(p,s,t,line['id'])
                    if issue:raise ValueError(issue)
                    line.update(audio_take_id=t['id'],audio_duration=audio_duration(t['file']))
                    start=body.get('start')
                    if start is not None:
                        if type(start) not in (int,float) or not 0<=start<=86400:raise ValueError('逐句音轨起点不能为负数或超出范围')
                        if start+line['audio_duration']>s['duration']+.05:raise ValueError('逐句配音超过镜头时长，请延长镜头或调整音轨')
                        line['audio_start']=start
                    else:line.pop('audio_start',None)
                    # Reject an impossible complete schedule before persisting it.
                    # Partial assignments remain editable while the other lines are prepared.
                    if all(l.get('audio_take_id') for l in s['lines']):production.audio_schedule(s)
                    s.pop('audio',None);s['selected_takes'].pop('audio',None)
            elif action=='confirm_media':
                if not (s.get('image') or s.get('video')):raise ValueError('这一镜还没有选用画面')
                s['media_basis']=production.content_basis(s)
            else:raise ValueError('未知制作操作')
        return save(p,p['revision'],source_confirmation=action in ('bind_segment_source','bind_segment_sources'),media_confirmation=body.get('shot_id') if action=='confirm_media' else None)

def media_path(name):
    if not isinstance(name,str) or Path(name).name != name or not name: raise ValueError('非法媒体路径')
    path=(MEDIA/name).resolve()
    if path.parent != MEDIA.resolve() or not path.is_file(): raise ValueError('素材不存在')
    return path

def discard_upload(name):
    """Remove a just-uploaded file the user rejected; never touches media any project or version refers to."""
    path=media_path(name)
    with LOCK,connect() as c:
        c.execute('BEGIN IMMEDIATE')
        bodies=[r[0] for r in c.execute('SELECT body FROM projects')]+[r[0] for r in c.execute('SELECT body FROM versions')]
        jobs=[value for row in c.execute('SELECT payload,result FROM jobs') for value in row if value]
        if any(token in body for body in bodies+jobs
               for token in {json.dumps(name),json.dumps(name,ensure_ascii=False)}):
            raise ValueError('这个文件已被作品使用，不能删除')
        path.unlink()
    return {'discarded':name}

def storyboard_packet(p,sid,model=fal_media.STORYBOARD, *, reference_mode='image'):
    if reference_mode not in ('image', 'text') or (reference_mode == 'text' and model not in domestic_media.STILL_MODELS):
        raise ValueError('仅 Seedream 分镜支持纯文字机位')
    if model != fal_media.STORYBOARD and model not in domestic_media.STILL_MODELS:
        raise ValueError('分镜模型无效')
    s=preparation.shot_of(p,sid)
    ref=s.get('composition_reference') or {}
    if not ref or ref.get('actors')!=blocking.layout(p,s):
        raise ValueError('请先为当前角色保存机位构图')
    view=ref['camera']['view']
    if view not in blocking.choices(ref['actors']):
        raise ValueError('机位无效，请重新保存构图')
    framing = s.get('framing') or '中景'
    if reference_mode == 'image' and view != 'wide' and ref.get('spec') != blocking.composition_spec(view, framing, p['creative_brief']['format'] == '9:16'):
        raise ValueError('请打开机位并重新保存单人构图，以匹配当前景别与画幅')
    slots = blocking.visible_slots(view,len(ref['actors']))
    actors = [ref['actors'][slot] for slot in slots]
    offscreen = [actor for slot, actor in enumerate(ref['actors']) if slot not in slots]
    assets = {a['id']: a for a in p['assets']}
    bindings = s['asset_bindings']
    versions = []
    refs = []
    instructions = ['绘制一张完成的漫剧分镜。']
    bible = p['creative_brief'].get('visual_bible', {})
    approvals = bible.get('references', [])
    ark = model in domestic_media.STILL_MODELS

    def bound_version(asset):
        version = next((v for v in asset['versions'] if v['id'] == bindings.get(asset['id'])), None)
        if not version:
            raise ValueError(f"请重新绑定{asset['name']}的版本")
        versions.append(version['id'])
        return version

    def add_reference(role, file, label):
        path = media_path(file)
        refs.append(dict(role=role, file=file, label=label,
                         reference_id=hashlib.sha256(visual.read_image(path)).hexdigest()))

    over = view.startswith('over_')
    if over:
        slot = blocking.focus_slot(view)
        instructions.append(f"越肩镜头：主体为{ref['actors'][slot]['name']}，对手仅以虚化的前景肩背入画，保持视轴。")
    elif view == 'wide' and len(actors) == 1:
        instructions.append('单人全景，画内恰好一人，完整展现人物和场景。')
    elif view == 'wide':
        instructions.append('双人全景，恰好两人同框，左右位置与视线按构图保持。')
    elif len(ref['actors']) == 1:
        instructions.append(f'单人{framing}，画内恰好一人，动作及视线以镜头描述为准。')
    else:
        direction = '右' if view == 'left' else '左'
        instructions.append(f"单人{framing}，画内恰好一人。主体面朝画{direction}，看向画{direction}外的对手。"
                            "仅拍主体，画面边缘、前景、背景及倒影均无第二人或其身体局部。")
    for index, actor in enumerate(actors, 1):
        version = bound_version(assets[actor['id']])
        views = version.get('views') or {}
        picks = visual.approved_refs(approvals, 'character', actor['id'], version['id'], version)
        pick_view, approval = picks[0] if picks else (None, None)
        portrait = approval['file'] if approval else None
        name = version.get('name') or actor['name']
        if not portrait:
            if version.get('file') or views:
                raise ValueError(f'请先在角色与素材中批准{name}要用于分镜的参考视图')
            raise ValueError(f'请为{name}当前绑定的造型添加角色参考图')
        add_reference('character', portrait, name + ' · ' + visual.VIEW_LABELS.get(pick_view, '角色参考'))
        if approval.get('sha256') and refs[-1]['reference_id']!=approval['sha256']:
            raise ValueError('已批准的角色参考图文件发生变化')
        refs[-1].update(asset_id=actor['id'], version_id=version['id'],
                        source=approval['source'],
                        view=pick_view, status='approved' if approval.get('sha256') else 'legacy')
        position = ('左侧' if index == 1 else '右侧') if view == 'wide' else '主体'
        instructions.append(f"图{index}用于{position}人物{name}的面貌与衣着。保持参考图的脸型、发型、发色和服装颜色。造型：{version.get('description','')}。服装：{version.get('outfit') or '以角色图为准'}。")

    location = (s.get('creative_spec') or {}).get('locationId')
    scenes = [assets[k] for k in s['asset_ids'] if assets[k]['kind'] == 'scene' and (not location or k == location)]
    if len(scenes) > 1 or (location and not scenes):
        raise ValueError('请为当前镜头明确绑定一个拍摄场景')
    if scenes:
        scene = bound_version(scenes[0])
        instructions.append(f"场景：{scene.get('name') or scenes[0]['name']}。{scene.get('description','')}。")
        picks = visual.approved_refs(approvals, 'scene', scenes[0]['id'], scene['id'], scene)
        if ark and not picks and (scene.get('file') or scene.get('views')):
            raise ValueError(f'请先在角色与素材中批准{scene.get("name") or scenes[0]["name"]}要用于分镜的参考视图')
        if ark and picks:
            pick_view, approval = picks[0]
            add_reference('scene', approval['file'], '场景参考 · ' + visual.VIEW_LABELS.get(pick_view, '设定图'))
            if approval.get('sha256') and refs[-1]['reference_id']!=approval['sha256']:
                raise ValueError('已批准的场景参考图文件发生变化')
            refs[-1].update({k: approval[k] for k in ('asset_id', 'version_id', 'source')},
                            view=pick_view, status='approved' if approval.get('sha256') else 'legacy')
            instructions.append(f'图{len(refs)}仅用于场景布局、建筑与环境灯光。')
    if reference_mode == 'image':
        add_reference('composition', ref['file'], '机位构图')
        refs[-1].update(source='本地机位预演', status='composition_only')
        instructions.append(f"图{len(refs)}仅用于站位、视线、景别与机位。"
                            "成图独立绘制，来自预演的人偶、色块、纹理和多边形轮廓无需保留。")
    else:
        instructions.append('依据文字构图，背景依照场景设定绘制。')
        if view != 'wide':
            side = '左' if blocking.focus_slot(view)==0 else '右'
            crop = {'中景': '腰部以上', '中近景': '胸口以上', '近景': '肩部以上',
                    '特写': '脸部为主', '大特写': '局部面部细节'}.get(framing, '依景别裁切')
            instructions.append(f'主体位于画{side}三分线附近，{crop}，朝视线方向留出空间。')
        elif len(actors)==1:
            instructions.append('完整呈现主体及其周围环境，保留头顶和脚下空间。')
        else:
            instructions.append('完整呈现两人及其间距，左侧人物看画右，右侧人物看画左。')
    style_ref = visual.style_reference(approvals,p['assets'])
    if ark and style_ref:
        add_reference('style', style_ref['file'], '画风参考')
        if style_ref.get('sha256') and refs[-1]['reference_id']!=style_ref['sha256']:
            raise ValueError('已批准的风格参考图文件发生变化')
        refs[-1].update({k: style_ref[k] for k in ('asset_id', 'version_id', 'source')},
                        view=style_ref.get('view') or 'primary', status='approved' if style_ref.get('sha256') else 'legacy')
        instructions.append(f'图{len(refs)}仅用于绘制技法、光影、色彩和细节层次。')
    instructions.append(f"镜头：{s['description']}。")
    instructions.append(art.constraints(p['creative_brief']))
    style = art.resolve(p['creative_brief'])
    for key, label in visual.DIRECTION.items():
        if bible.get(key):
            instructions.append(f'{label}：{bible[key]}。')
    for actor in actors:
        direction = ref['camera'].get('gaze', {}).get(actor['id'])
        if direction:
            side = '左' if direction=='left' else '右'
            instructions.append(f"以此明确视线为准：{actor['name']}看向画{side}。")
    if offscreen:
        instructions.append(f"动作描述中提到的{offscreen[0]['name']}始终在画外，不入镜。")
    instructions.append('保持本场既定空间、主光方向和人物相对位置；角色外观只取自角色参考图。')
    staging = dict(visible_ids=[actor['id'] for actor in actors],
                   offscreen_ids=[actor['id'] for actor in offscreen], view=view)
    prompt = ''.join(instructions)
    return dict(id='storyboard-'+sid,shot_id=sid,start=0,end=s['duration'],duration=s['duration'],
                kind='image',mode='storyboard',provider=domestic_media.PROVIDER.get(model, 'fal'),model=model,
                references=refs,parameters={'aspect_ratio':p['creative_brief']['format']},
                instruction=prompt,staging=staging,reference_mode=reference_mode,
                art_style=style['key'],art_label=style['label'],
                plan_digest=production.digest([refs,prompt,versions,ref['camera'],staging]))


def asset_image_packet(p, payload):
    asset = next((a for a in p['assets'] if a['id']==payload.get('asset_id') and a['kind'] in ('character','scene')), None)
    if not asset:
        raise ValueError('请选择角色或场景')
    version = next((v for v in asset['versions'] if v['id']==payload.get('version_id')), None)
    if not version:
        raise ValueError('素材版本已不存在')
    instruction = payload.get('instruction')
    if not isinstance(instruction,str) or not 1<=len(instruction.strip())<=2000:
        raise ValueError('请填写不超过 2000 字的生成要求')
    bible = p['creative_brief'].get('visual_bible', {})
    references = bible.get('references', [])
    states = visual.view_states(version, references, asset['kind'], asset['id'], version['id'])
    approved = [state for state in states if state['status']!='unapproved']
    unapproved = [state for state in states if state['status']=='unapproved']
    allow_unapproved = payload.get('allow_unapproved') is True
    if states and not approved and not allow_unapproved:
        raise ValueError('这个版本只有未批准的视图；请先在角色与素材中批准要用于生成的视图，或明确选择“使用未批准视图”')
    use = approved + (unapproved if allow_unapproved else [])
    refs, used = [], set()
    for state in use:
        if len(used) >= 3:
            break
        file = state['file']
        digest = hashlib.sha256(visual.read_image(media_path(file))).hexdigest()
        approval = state['approval']
        if approval and approval.get('sha256') and approval['sha256']!=digest:
            raise ValueError('已批准的参考图文件发生变化')
        refs.append(dict(file=file, role=asset['kind'], reference_id=digest,
                         label=version['name']+' · '+visual.VIEW_LABELS.get(state['view'],state['view']),
                         asset_id=asset['id'], version_id=version['id'], view=state['view'],
                         status=state['status'], source=(approval or {}).get('source')))
        used.add(state['view'])
    excluded = [dict(view=state['view'], status=state['status'], label=state['label'],
                     reason=('未批准，未进入本次请求' if state['status']=='unapproved' and not allow_unapproved
                             else '超出单次 3 张参考图上限'))
                for state in states if state['view'] not in used]
    style = visual.style_reference(references,p['assets'])
    style_status = None
    if style:
        path = media_path(style['file'])
        digest = hashlib.sha256(visual.read_image(path)).hexdigest()
        if style.get('sha256') and digest!=style['sha256']:
            raise ValueError('已批准的风格参考图文件发生变化')
        style_status = 'approved' if style.get('sha256') else 'legacy'
        refs.append(dict(file=style['file'], role='style', reference_id=digest,
                         label='作品统一画风', asset_id=style.get('asset_id'), version_id=style.get('version_id'),
                         source=style.get('source'), view=style.get('view') or 'primary', status=style_status))
    art_style = art.resolve(p['creative_brief'])
    prompt = f"生成一张{art_style['label']}风格的" + art.constraints(p['creative_brief'], asset['kind'])
    if style:
        prompt += '最后一张参考图仅用于统一绘制技法、色彩和光影，不改变人物或场景本身的结构。'
    prompt += f"素材：{version['name']}。{version.get('description','')}。"
    if version.get('outfit'):
        prompt += f"服装：{version['outfit']}。"
    prompt += ''.join(f'{label}：{bible[key]}。' for key,label in visual.DIRECTION.items() if bible.get(key))
    if allow_unapproved and any(ref['status']=='unapproved' for ref in refs):
        prompt += '注意：本次生成包含尚未批准的视图，仅用于本次请求，不会自动成为正式参考。'
    prompt += instruction.strip()
    packet = dict(id='asset-'+asset['id'], asset_id=asset['id'],version_id=version['id'],kind='image',mode='asset',
                  instruction=prompt,user_instruction=instruction,model=domestic_media.FLASH,provider='ark',
                  parameters={'aspect_ratio':'9:16' if asset['kind']=='character' else p['creative_brief']['format']},
                  references=refs,art_style=art_style['key'],art_label=art_style['label'],
                  approval=dict(used=[dict(view=ref['view'],status=ref['status'],label=visual.VIEW_LABELS.get(ref['view'],ref['view']))
                                      for ref in refs if ref['role']!='style'],
                                excluded=excluded,allow_unapproved=allow_unapproved,
                                requires_confirmation=bool(unapproved) and not allow_unapproved,
                                style_status=style_status))
    packet['plan_digest']=production.digest(packet)
    return packet


def job_request(pid,kind,payload,*,quoting=False):
    if kind not in ('script','assets','shots','revision','image','asset_image','video','audio','plan','qc','export','assemble'): raise ValueError('未知任务类型')
    p=project(pid)
    episode_id=payload.get('episode_id') or (p['episodes'][0]['id'] if len(p['episodes'])==1 else None)
    if episode_id:creative.require_current_state(p,episode_id)
    snapshot=production_snapshot(p,payload.get('episode_id')) if kind=='export' else production.scope(p,payload.get('episode_id'),payload.get('shot_id'),payload.get('instruction',''))
    if kind in ('revision','image','video','audio') and not snapshot.get('target_shot_id'):raise ValueError('请指定目标镜头')
    uses_openai = kind=='audio' or (kind=='revision' and bool(openai_direct.key()))
    if kind=='audio':
        snapshot['speech']=production.speech_request(snapshot,payload.get('line_id'))
        if not openai_direct.key():raise ValueError('请在设置中连接 OpenAI 配音服务，或先导入音轨')
        openai_direct.check_voice(snapshot['speech']['voice_id'])
        snapshot['speech']['model']=openai_direct.MODELS['audio']
    packet=None
    if kind=='asset_image':
        packet=asset_image_packet(p,payload)
        snapshot.update(generation_segment=packet,reference_media=packet['references'],reference_mode='asset')
    expected_plan=payload.get('preparation_digest')
    if kind in ('image','video'):
        if kind=='video' and payload.get('comparison') is True:
            with connect() as db:
                packet=comparison.packet(db,p,preparation.shot_of(p,snapshot['target_shot_id']),payload,media_path)
        elif kind=='image' and payload.get('storyboard') is True:
            packet=storyboard_packet(p,snapshot['target_shot_id'],payload.get('model',fal_media.STORYBOARD),
                                     reference_mode=payload.get('storyboard_reference_mode','image'))
        else:packet=preparation.freeze(p,snapshot['target_shot_id'],kind,payload.get('segment_id'),media_path,None if quoting else lambda k:bool(key_for(k)))
        if expected_plan is not None and expected_plan!=packet['plan_digest']:
            raise ValueError('制作准备已变更，请重新打开并确认后生成')
        refs=packet['references'];selected={(r['reference_id'],r['role']) for r in refs}
        plan={'items':refs,'mode':'first_frame' if packet['mode']=='image_to_video' else 'first_last_frame' if packet['mode']=='start_end_frames' else 'references',
              'omitted':[{**r,'reason':'未选入本片段'} for r in preparation.catalog(p,preparation.shot_of(p,snapshot['target_shot_id'])) if not any(x[0]==r['reference_id'] for x in selected)]}
        snapshot['generation_segment']=packet
    if kind=='audio':plan={'items':[],'mode':'speech','omitted':[]}
    if kind in ('image','video','audio'):
        if len(plan['items'])>10:raise ValueError('单次生成最多使用 10 个参考素材，请减少本镜头绑定的视图或资产')
        snapshot.update(reference_media=plan['items'],reference_mode=plan['mode'],reference_omitted=plan['omitted'])
    if kind=='revision' and (not isinstance(payload.get('instruction'),str) or not 1<=len(payload['instruction'].strip())<=2000):raise ValueError('请填写不超过 2000 字的单镜修改要求')
    if kind=='export' and not production.readiness(p,snapshot['episode_id'])['can_export']:
        raise ValueError('导出前每个镜头都需有图片或视频、通过审核且无待复核修改')
    provider=None
    if packet and packet['provider'] in domestic_media.KEYS:
        provider=domestic_media.identity(packet['model'])
    elif packet and packet['provider']=='fal':
        provider=fal_media.identity(packet['model'])
    elif kind!='export':
        encode_context(snapshot)
        if not uses_openai and not key_for(kind):raise ValueError('尚未连接该 Dify 工作流；请先配置已发布应用的 API Key')
        provider=openai_direct.identity(kind) if uses_openai else provider_identity(kind)
    return p,snapshot,packet,provider


def build_job_quote(kind,snapshot,packet,provider):
    name=provider['provider']
    model=packet['model'] if packet else provider.get('model')
    quote=generation_quote.estimate(kind,name,model,
                                   packet['duration'] if packet and kind=='video' else None,
                                   snapshot.get('instruction',''),
                                   resolution=packet['parameters'].get('resolution') if packet else None)
    if packet:quote['model_label']=domestic_media.STILL_MODELS[model][0] if model in domestic_media.STILL_MODELS else 'Nano Banana Edit' if model==fal_media.STORYBOARD else preparation.MODELS[model].get('label',model)
    quote['reference_count']=len(snapshot.get('reference_media',[]))
    quote['digest']=production.digest({'basis':snapshot.get('basis'),'speech':snapshot.get('speech'),
                                       'instruction':snapshot.get('instruction'),'packet':packet,
                                       'provider':provider,'quote':quote})
    return quote


def preview_job_quote(pid,kind,payload):
    if kind in ('export','assemble'):raise ValueError('本地任务不需要生成报价')
    _,snapshot,packet,provider=job_request(pid,kind,payload,quoting=True)
    quote=build_job_quote(kind,snapshot,packet,provider)
    if packet and packet['provider'] in domestic_media.KEYS:
        domestic_media.arguments('image' if kind=='asset_image' else kind,snapshot,media_path)
        quote.update(references=packet['references'],configured=bool(domestic_media.key(packet['provider'])))
        if packet.get('approval'):
            quote.update(approval=packet['approval'],
                         excluded_references=packet['approval']['excluded'],
                         requires_approval=packet['approval']['requires_confirmation'],
                         approval_notice=('这个版本还有未批准的视图，它们不会进入本次模型请求。'
                                          '如需使用，必须在报价中明确确认。'
                                          if packet['approval']['requires_confirmation'] else ''),
                         art_label=packet.get('art_label'))
    elif packet and packet['provider']=='fal':
        fal_media.arguments(kind,snapshot,media_path)
        quote.update(references=packet['references'],configured=bool(fal_media.key()),
                     art_label=packet.get('art_label'))
    if packet and packet.get('comparison_id'):
        quote.update(comparison_id=packet['comparison_id'], duration=packet['duration'],
                     resolution=packet['parameters']['resolution'])
    if kind=='asset_image':quote['prompt']=packet['instruction']
    return quote


def enqueue(pid,kind,payload,nonce,*,connection=None,batch=None,require_quote=False):
    if kind=='assemble':return enqueue_assembly(project(pid),payload,nonce)
    p,snapshot,packet,provider=job_request(pid,kind,payload)
    quote=build_job_quote(kind,snapshot,packet,provider) if provider else None
    if provider and require_quote and not payload.get('quote_digest'):
        raise ValueError('请先确认本次生成报价')
    if packet and packet['provider'] in domestic_media.KEYS:
        if not payload.get('quote_digest'):raise ValueError('请先确认本次生成报价')
        if not domestic_media.key(packet['provider']):raise ValueError('请先配置 ' + domestic_media.KEYS[packet['provider']])
    elif packet and packet['model']==fal_media.STORYBOARD:
        if not payload.get('quote_digest'):raise ValueError('请先确认分镜图的报价')
        if not fal_media.key():raise ValueError('请先配置 fal API Key')
    if 'quote_digest' in payload and (not quote or payload['quote_digest']!=quote['digest']):
        raise ValueError('生成参数或报价已变化，请重新确认')
    dedupe=f'{pid}:{snapshot["episode_id"]}:{kind}:{nonce}'
    now=time.time()
    with (nullcontext(connection) if connection is not None else connect()) as c:
        if connection is None:
            c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT id FROM jobs WHERE dedupe=?',(dedupe,)).fetchone()
        if existing:return existing['id']
        if provider:
            remaining=c.execute('SELECT remaining FROM spending WHERE id=1').fetchone()['remaining']
            if not remaining:raise ValueError('付费调用已暂停，请先明确授权本批次数')
            needed=quote['authorization_calls'] if 'quote_digest' in payload else 1
            if remaining<needed:raise ValueError(f'本次需要 {needed} 次本机授权，目前剩余 {remaining} 次')
        if packet:
            pending=c.execute("""SELECT id FROM jobs WHERE project_id=? AND kind=?
                AND state IN ('queued','paused','running','waiting_review','interrupted')
                AND json_extract(payload,'$.snapshot.target_shot_id') IS ?
                AND json_extract(payload,'$.generation_unit.segment.id')=? LIMIT 1""",
                (pid,kind,packet.get('shot_id'),packet['id'])).fetchone()
            if pending:raise ValueError('这一片段已有生成任务，请先查看生成记录')
        jid=uid()
        body={'snapshot':snapshot}
        if batch:body['batch_id']=batch
        if kind=='revision':body['revision_preview_required']=True
        if provider:body.update(provider=provider,quote=quote)
        frozen_refs=[]
        for ref in snapshot.get('reference_media',[]):
            file=ref['file']
            expected=ref.get('sha256') or ref['reference_id']
            with media_path(file).open('rb') as stream:
                actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=expected:
                raise ValueError('参考文件内容已变化，请重新确认生成请求')
            frozen_refs.append(dict(file=file,sha256=actual))
        if kind=='asset_image':
            body['generation_unit']={'segment':packet,'references':frozen_refs}
        if kind in ('image','video','audio'):
            body['generation_unit']={'id':uid(),'shot_ids':[snapshot['target_shot_id']], 'kind':kind,
                'line_id':snapshot.get('speech',{}).get('line_id'),'input_digest':production.digest(snapshot),
                'parameters':copy.deepcopy(snapshot.get('speech') or {'mode':snapshot.get('reference_mode'),'duration':next(s['duration'] for s in snapshot['shots'] if s['id']==snapshot['target_shot_id'])}),
                'provider':body['provider'],'references':frozen_refs,
                'adapter_profile':'openai-realtime' if kind=='audio' else 'external-workflow', 'created':now}
            if packet:body['generation_unit'].update(segment=packet,parameters={**packet['parameters'],**({'duration':packet['duration']} if kind=='video' else {})},
                                                     basis=production.take_basis(preparation.shot_of(p,snapshot['target_shot_id'])))
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,pid,kind,'queued',json.dumps(body),None,None,now,now,dedupe))
    return jid

def production_batch(body, submit=False):
    pid=body.get('project_id')
    project(pid)
    requests=body.get('requests')
    if not isinstance(requests,list) or not 1<=len(requests)<=20 or any(not isinstance(r,dict) for r in requests):
        raise ValueError('每批须选择 1–20 个生成片段')
    allowed={'kind','shot_id','episode_id','segment_id','storyboard','model','storyboard_reference_mode','comparison','instruction','seconds'}
    if any(set(r)-allowed or r.get('kind') not in ('image','video') or not r.get('shot_id') for r in requests):
        raise ValueError('批次只支持已准备的镜头画面')
    identifiers=[(r['kind'],r['shot_id'],r.get('segment_id'),r.get('model') if r.get('comparison') else None) for r in requests]
    if len(set(identifiers))!=len(requests):
        raise ValueError('同批不能重复提交同一片段')
    with LOCK:
        quotes=[preview_job_quote(pid,r['kind'],r) for r in requests]
        if any(q.get('estimated_cny') is None for q in quotes):
            raise ValueError('批次仅支持人民币价格明确的模型')
        digest=production.digest([pid,requests,[q['digest'] for q in quotes]])
        calls=sum(q['authorization_calls'] for q in quotes)
        total=sum(Decimal(q['estimated_cny']) for q in quotes)
        if not submit:
            return dict(digest=digest,quotes=quotes,calls=calls,estimated_cny=format(total,'.2f'))
        nonce=body.get('nonce')
        if not isinstance(nonce,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',nonce):
            raise ValueError('批次编号无效')
        if body.get('digest')!=digest:
            raise ValueError('批次报价已变化，请重新确认')
        batch=production.digest([pid,nonce])[:24]
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT id,payload FROM jobs WHERE project_id=? AND json_extract(payload,'$.batch_id')=? ORDER BY created",
                            (pid,batch)).fetchall()
            if rows:
                if [json.loads(r['payload'])['quote']['digest'] for r in rows]!=[q['digest'] for q in quotes]:
                    raise ValueError('批次编号已用于其他请求')
                return dict(batch_id=batch,jobs=[r['id'] for r in rows])
            remaining=db.execute('SELECT remaining FROM spending WHERE id=1').fetchone()[0]
            pending=db.execute("""SELECT COALESCE(SUM(COALESCE(json_extract(payload,'$.quote.authorization_calls'),1)),0)
                                  FROM jobs WHERE state='queued' AND json_type(payload,'$.provider')='object'
                                  AND json_extract(payload,'$.operation') IS NULL""").fetchone()[0]
            if remaining<pending+calls:
                raise ValueError('生成授权不足，请先确认整个批次的费用')
            jobs=[enqueue(pid,r['kind'],dict(r,quote_digest=q['digest']),f'{batch}-{i}',connection=db,batch=batch)
                  for i,(r,q) in enumerate(zip(requests,quotes,strict=True))]
    return dict(batch_id=batch,jobs=jobs)


def director_references(body):
    """Preview the same references an Ark storyboard would actually receive."""
    p=project(body['project_id'])
    shot=preparation.shot_of(p,body['shot_id'])
    modes={}
    for mode in ('image','text'):
        try:
            packet=storyboard_packet(p,shot['id'],domestic_media.FLASH,reference_mode=mode)
        except ValueError as exc:
            modes[mode]={'blocked':str(exc)}
            continue
        references=[]
        for ref in packet['references']:
            reason={'character':'当前镜头明确绑定的角色造型',
                    'scene':'当前镜头场景版本的已批准环境图',
                    'style':'作品当前批准的风格图',
                    'composition':'该镜预演的站位和机位'}[ref['role']]
            references.append(dict(ref,reason=reason))
        modes[mode]=dict(references=references,staging=packet['staging'])
    return modes


def video_comparison(body):
    scope={key:body[key] for key in ('shot_id','episode_id','instruction','seconds') if key in body}
    requests=[dict(scope,kind='video',comparison=True,model=model) for model in comparison.RESOLUTIONS]
    result=production_batch(dict(project_id=body['project_id'],requests=requests))
    result['requests']=requests
    return result


def batch_state(body):
    action=body.get('action')
    states={'pause':('paused','queued'),'resume':('queued','paused')}
    if action not in states:
        raise ValueError('批次操作无效')
    new,old=states[action]
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if action=='resume':
            remaining=db.execute('SELECT remaining FROM spending WHERE id=1').fetchone()[0]
            calls=db.execute("""SELECT COALESCE(SUM(COALESCE(json_extract(payload,'$.quote.authorization_calls'),1)),0)
                FROM jobs WHERE json_type(payload,'$.provider')='object' AND json_extract(payload,'$.operation') IS NULL
                AND (state='queued' OR (state='paused' AND project_id=? AND json_extract(payload,'$.batch_id')=?))""",
                (body['project_id'],body['batch_id'])).fetchone()[0]
            if remaining<calls:
                raise ValueError('当前生成授权不足，批次仍保持暂停')
        count=db.execute("""UPDATE jobs SET state=?,updated=? WHERE project_id=? AND state=?
                           AND json_extract(payload,'$.batch_id')=?""",
                         (new,time.time(),body['project_id'],old,body['batch_id'])).rowcount
    return {'updated':count}


def check_provider(payload, kind=None):
    """Refuse to continue a job against a different Dify app than the one it was queued with.
    Jobs queued before identities were recorded have none and are accepted as before."""
    frozen=payload.get('provider')
    if not frozen:return
    if frozen.get('provider') == 'openai':
        if kind not in openai_direct.MODELS or not openai_direct.key() or frozen!=openai_direct.identity(kind):
            raise ValueError('OpenAI 模型或 Key 已变更，请重新确认请求')
        return
    if frozen.get('provider') in domestic_media.KEYS:
        model=payload['snapshot']['generation_segment']['model']
        if not domestic_media.key(frozen['provider']) or model not in domestic_media.PROVIDER or frozen != domestic_media.identity(model):
            raise ValueError('生成模型、服务地址或凭据已变化，请核实原任务')
        return
    if frozen.get('provider') == 'fal':
        model = payload.get('snapshot', {}).get('generation_segment', {}).get('model')
        if model not in (*fal_media.PROFILES,fal_media.STORYBOARD) or frozen != fal_media.identity(model):
            raise ValueError('fal 模型或 Key 已变更，请恢复原配置核实此任务')
        return
    kind=kind or next((k for k in ('script','assets','shots','revision','image','video','audio','plan','qc') if key_env_for(k)==frozen['key_env']),None)
    if kind and not key_for(kind):return  # no key now: the adapter reports 'not configured' itself, nothing can be sent
    now=provider_identity(kind) if kind else None
    if not now or now['host']!=frozen['host'] or (frozen.get('endpoint_fingerprint') and now['endpoint_fingerprint']!=frozen['endpoint_fingerprint']):raise ValueError('Dify 地址已变更，此任务是用另一个地址提交的；不自动继续，请在原应用核对或重新发起')
    if now['key_fingerprint']!=frozen['key_fingerprint']:raise ValueError('Dify 应用 Key 已更换，此任务属于原应用；不自动继续，请换回原 Key 核实，或重新发起')

def update_job(jid,state,result=None,error=None):
    with connect() as c:
        if result is not None:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT result FROM jobs WHERE id=?',(jid,)).fetchone()
            previous=json.loads(row['result'] or '{}') if row else {}
            for key in ('submission_started_at','provider_request_id','output_sha256','actual_cny','billing_history'):
                if previous.get(key):
                    result.setdefault(key,previous[key])
            if previous.get('billing_history'):
                result['billing_status']=previous['billing_status']
            if state=='succeeded' and result.get('submission_started_at'):
                result.setdefault('completed_at',time.time())
        c.execute('UPDATE jobs SET state=?,result=?,error=?,updated=? WHERE id=? AND state!=?',(state,json.dumps(result,ensure_ascii=False) if result is not None else None,error,time.time(),jid,'cancelled'))


def public_job(row):
    job={k:row[k] for k in ('id','project_id','kind','state','result','error','created','updated')}
    snapshot=json.loads(row['payload']).get('snapshot',{})
    job.update(episode_id=snapshot.get('episode_id'),episode_title=snapshot.get('episode_title'),source_revision=snapshot.get('revision'))
    try:job['fresh']=production.fresh(project(row['project_id']),snapshot)
    except ValueError:job['fresh']=False
    job['target_shot_id']=snapshot.get('target_shot_id');job['scope']=snapshot.get('scope');job['provider']=json.loads(row['payload']).get('provider')
    job['generation_unit']=json.loads(row['payload']).get('generation_unit')
    job['batch_id']=json.loads(row['payload']).get('batch_id')
    if job['provider']:
        job['provider']={k:job['provider'][k] for k in ('provider','model','host') if k in job['provider']}
    if job['generation_unit'] and job['generation_unit'].get('provider'):
        job['generation_unit']['provider']=job['provider']

    if job['result']:
        result=json.loads(job['result']);result.pop('form_token',None)
        if isinstance(result.get('form'),dict):
            result['form']={k:result['form'][k] for k in ('form_content','inputs','user_actions','resolved_default_values','expiration_time') if k in result['form']}
        job['result']=json.dumps(result,ensure_ascii=False)
    return job

def record_job_bill(body):
    value=body.get('actual_cny')
    evidence=body.get('evidence')
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,7}(?:\.[0-9]{1,4})?',value):
        raise ValueError('请输入非负人民币金额，最多四位小数')
    if not isinstance(evidence,str) or not 1<=len(evidence.strip())<=300:
        raise ValueError('请填写可核对的账单条目或凭证说明')
    with LOCK, connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT payload,result FROM jobs WHERE id=? AND project_id=? AND state IN ('succeeded','failed','interrupted')",
                       (body['job_id'],body['project_id'])).fetchone()
        if not row or not json.loads(row['payload']).get('provider'):
            raise ValueError('只能对有供应商记录的已结束任务录入账单')
        result=json.loads(row['result'] or '{}')
        if not any(result.get(key) for key in ('provider_request_id','run_id','submission_started_at')):
            raise ValueError('该任务没有外部请求证据')
        entries=result.setdefault('billing_history',[])
        if entries and entries[-1]['cny']==value and entries[-1]['evidence']==evidence.strip():
            return entries[-1]
        entry=dict(cny=value,evidence=evidence.strip(),recorded_at=time.time(),source='manual')
        entries.append(entry)
        result.update(actual_cny=value,billing_status='manual_statement')
        db.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps(result,ensure_ascii=False),body['job_id']))
        return entry


def configure_dify(base,key,kind='shots'):
    if kind not in ('shots','revision','image','video','audio','script','assets','plan','qc'):raise ValueError('工作流类型无效')
    if not isinstance(base,str) or not isinstance(key,str): raise ValueError('配置格式无效')
    base=base.strip().rstrip('/');key=key.strip();parsed=urlparse(base)
    if (len(base)>2048 or any(c.isspace() for c in base) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not (parsed.scheme=='https' or (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')))):
        raise ValueError('Dify 地址必须是 HTTPS 或本机服务')
    if not key.startswith('app-') or any(c.isspace() for c in key) or len(key)>512:
        raise ValueError('请使用已发布应用的 app- API Key，不使用账号会话凭据')
    save_local_credentials({'DIFY_BASE_URL':base,('DIFY_PRODUCTION_KEY' if kind=='shots' else 'DIFY_'+kind.upper()+'_KEY'):key})
    return {'configured':True,'verified':False,'base_url':base}

def configure_media_key(provider,key):
    names={'fal':'FAL_KEY', **domestic_media.KEYS}
    if provider not in names:raise ValueError('未知媒体服务')
    if not isinstance(key,str):raise ValueError('请输入 API Key')
    key=key.strip()
    if not key or len(key)>512 or any(not c.isascii() or not c.isprintable() or c.isspace() or ord(c) in (34,39) for c in key):
        raise ValueError('请粘贴有效的 API Key')
    save_local_credentials({names[provider]:key})
    return {'configured':True,'verified':False}

def configure_fal(key):
    return configure_media_key('fal',key)

def configure_openai(key):
    if not isinstance(key,str):raise ValueError('请输入 OpenAI API Key')
    key=key.strip()
    if not key.startswith('sk-') or len(key)>512 or any(not c.isascii() or not (c.isalnum() or c in '-_') for c in key):
        raise ValueError('请使用 OpenAI 平台的 API Key')
    save_local_credentials({'OPENAI_API_KEY':key})
    return {'configured':True,'verified':False}

def save_local_credentials(values):
    with LOCK:
        path=env_file()
        lines=path.read_text().splitlines() if path.exists() else []
        lines=[line for line in lines if line.split('=',1)[0].strip() not in values]
        text='\n'.join([*lines,*[k+'='+v for k,v in values.items()]])+'\n'
        tmp=path.parent/('.env-'+uid()+'.tmp')
        try:
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(text)
            os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
        os.environ.update(values)

def review_job(pid,jid,revision,review_id,action,notes):
    with LOCK, connect() as c:
        p=project(pid)
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['project_id']!=pid or row['state']!='waiting_review': raise ValueError('任务当前不在等待审批')
        payload=json.loads(row['payload']);result=json.loads(row['result'])
        if p['revision']!=revision or not production.fresh(p,payload['snapshot']): raise ValueError('作品已更新，旧方案不能审批；请检查或重新规划')
        check_provider(payload,row['kind'])
        if not review_id or review_id!=result.get('review_id'): raise ValueError('审批表单已变化，请刷新')
        form=result.get('form') or {}
        if action not in {x.get('id') for x in form.get('user_actions',[])}: raise ValueError('审批动作无效')
        if not isinstance(notes,str) or len(notes)>10000: raise ValueError('修改意见最多 10000 字')
        fields=form.get('inputs',[])
        if len(fields)>1 or any(f.get('type')!='paragraph' or not f.get('output_variable_name') for f in fields): raise ValueError('当前工作室仅支持单个文字字段审批，请在 Dify 处理此表单')
        inputs={f['output_variable_name']:notes for f in fields}
        spend()
        c.execute("UPDATE jobs SET state='submitting',updated=? WHERE id=?",(time.time(),jid))
    try:
        Dify().submit(row['kind'],payload['snapshot'],result,action,inputs)
    except UncertainRun as e:
        update_job(jid,'interrupted',result,str(e));raise
    except ValueError as e:
        # A rejected form submission did not accept the action. Reconcile expired or consumed forms manually.
        update_job(jid,'waiting_review',result,str(e));raise
    except Exception:
        update_job(jid,'interrupted',result,'审批提交结果未知，请核实远程状态，不重复提交')
        raise ValueError('审批提交结果未知，请核实远程状态') from None
    with LOCK, connect() as c:
        payload['operation']='listen'
        result.update(submitted_action=action,submitted_notes=notes)
        c.execute("UPDATE jobs SET state='queued',payload=?,result=?,error=NULL,updated=? WHERE id=? AND state='submitting'",
                  (json.dumps(payload,ensure_ascii=False),json.dumps(result,ensure_ascii=False),time.time(),jid))

def recover_direct_audio(row,payload,result):
    if row['kind']!='audio' or payload.get('provider',{}).get('provider')!='openai':return False
    jid=row['id']
    if len(jid)!=32 or any(ch not in '0123456789abcdef' for ch in jid):return False
    path=MEDIA/(jid+'.wav')
    if not path.is_file():return False
    try:openai_direct.validate_wav(path)
    except (ValueError,OSError):return False
    result.update(state='succeeded',candidate_file=path.name,cost=None)
    return True

def reconcile_job(pid,jid):
    with LOCK, connect() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['project_id']!=pid or row['kind']=='export' or row['state'] not in ('interrupted','waiting_review','failed'): raise ValueError('此任务不能核实远程状态')
        result=json.loads(row['result'] or '{}')
        payload=json.loads(row['payload'])
        media_ready=row['kind'] in ('image','asset_image','video','audio') and (result.get('result',{}).get('url') or result.get('candidate_file'))
        if not media_ready:media_ready=recover_direct_audio(row,payload,result)
        if not result.get('run_id') and not media_ready:raise ValueError('未取得可恢复的结果，请到生成服务日志核对，不自动重发')
        renewal = (payload.get('provider', {}).get('provider')=='minimax' and
                   result.get('run_id') and not result.get('candidate_file'))
        if renewal or not media_ready:check_provider(payload,row['kind'])
        payload['operation']='listen' if renewal or not media_ready else 'receive'
        c.execute("UPDATE jobs SET state='queued',payload=?,result=?,error=NULL,updated=? WHERE id=?",(json.dumps(payload),json.dumps(result),time.time(),jid))

def ffmpeg(args):
    subprocess.run(['ffmpeg','-nostdin','-y','-loglevel','error',*args],check=True,capture_output=True,timeout=240)

def asset_image_candidates(body):
    p=project(body['project_id'])
    aid=body['asset_id']
    if not any(a['id']==aid and a['kind'] in ('character','scene') for a in p['assets']):
        raise ValueError('素材不存在')
    with connect() as db:
        rows=db.execute("""SELECT id, state, payload, result, error, created, updated FROM jobs
            WHERE project_id=? AND kind='asset_image'
            AND json_extract(payload,'$.snapshot.generation_segment.asset_id')=?
            ORDER BY created DESC LIMIT 100""",(p['id'],aid)).fetchall()
    adopted={v.get('source_job_id') for a in p['assets'] if a['id']==aid for v in a['versions']}
    items=[]
    for r in rows:
        payload=json.loads(r['payload'] or '{}')
        result=json.loads(r['result'] or '{}')
        quote=payload.get('quote') or {}
        items.append(dict(id=r['id'],state=r['state'],file=result.get('candidate_file'),
                          error=r['error'],approved=r['id'] in adopted,
                          created=r['created'],updated=r['updated'],
                          model=quote.get('model') or payload.get('snapshot',{}).get('model'),
                          estimated_cny=quote.get('estimated_cny'),
                          actual_cny=result.get('actual_cny'),
                          billing_status=result.get('billing_status'),
                          request_id=result.get('provider_request_id') or result.get('run_id')))
    return items


def production_evidence(body):
    p=project(body['project_id'])
    with connect() as db:
        return evidence.build(db,p)


def approve_asset_image(body):
    with LOCK:
        p=project(body['project_id'])
        if p['revision']!=body['revision']:
            raise ValueError('作品已变化，请刷新后确认')
        with connect() as db:
            row=db.execute("SELECT payload,result FROM jobs WHERE id=? AND project_id=? AND kind='asset_image' AND state='succeeded'",
                           (body['job_id'],p['id'])).fetchone()
        if not row:
            raise ValueError('素材候选不存在')
        packet=json.loads(row['payload'])['snapshot']['generation_segment']
        result=json.loads(row['result'] or '{}')
        if body.get('asset_id') and body['asset_id']!=packet['asset_id']:
            raise ValueError('候选不属于这个素材')
        asset=next((a for a in p['assets'] if a['id']==packet['asset_id'] and a['kind'] in ('character','scene')),None)
        source=next((v for v in asset['versions'] if v['id']==packet['version_id']),None) if asset else None
        if not source:
            raise ValueError('原素材版本已不存在')
        if any(v.get('source_job_id')==body['job_id'] for v in asset['versions']):
            return p
        file=result.get('candidate_file')
        if not file or not media_path(file).is_file():
            raise ValueError('候选图片不存在，可能已被清理')
        sha=hashlib.sha256(visual.read_image(media_path(file))).hexdigest()
        if result.get('output_sha256') and sha!=result['output_sha256']:
            raise ValueError('候选图片文件内容已变化，请核实生成记录')
        version=dict(source,id=uid(),created=time.time(),label='已批准的生成参考',file=file,views={},
                     source_job_id=body['job_id'])
        asset['versions'].append(version)
        asset['version']=len(asset['versions'])
        if body.get('select') is True:
            asset['selected_version']=version['id']
        bible=p['creative_brief'].setdefault('visual_bible',{})
        bible.setdefault('references',[]).append(dict(role=asset['kind'],asset_id=asset['id'],
            version_id=version['id'],file=file,view='primary',source='Seedream · '+body['job_id'],sha256=sha))
        return save(p,p['revision'])


def approve_imported_reference(body):
    with LOCK:
        p=project(body['project_id'])
        if p['revision']!=body['revision']:
            raise ValueError('作品已变化，请刷新后确认')
        asset=next((a for a in p['assets'] if a['id']==body.get('asset_id') and a['kind'] in visual.ROLES),None)
        version=next((v for v in asset['versions'] if v['id']==body.get('version_id')),None) if asset else None
        file=body.get('file')
        if not version or not file or file not in [version.get('file'),*version.get('views',{}).values()]:
            raise ValueError('图片不属于选定素材版本')
        view=body.get('view') or visual.view_of(version,file)
        if view not in visual.allowed_views(asset['kind']) or visual.file_at_view(version, view) != file:
            raise ValueError('视图用途无效')
        source=body.get('source')
        if not isinstance(source,str) or not 1<=len(source.strip())<=500:
            raise ValueError('请填写图片来源')
        bible=p['creative_brief'].setdefault('visual_bible',{})
        refs=bible.setdefault('references',[])
        matches=[r for r in refs if (asset['kind']=='style' and r['role']=='style') or
                 (r['asset_id']==asset['id'] and r['version_id']==version['id']
                  and (r.get('view') or visual.view_of(version,r['file']) or 'primary')==view)]
        valid_matches = dict(visual.approved_refs(refs,asset['kind'],asset['id'],version['id'],version))
        if (view in valid_matches or (asset['kind']=='style' and visual.style_reference(refs,p['assets']))) and body.get('replace') is not True:
            raise ValueError('这个视图已有已批准参考，请确认替换')
        with media_path(file).open('rb') as stream:
            sha=hashlib.file_digest(stream,'sha256').hexdigest()
        refs[:]=[r for r in refs if r not in matches]
        refs.append(dict(role=asset['kind'],asset_id=asset['id'],version_id=version['id'],
                         file=file,view=view,source=source.strip(),sha256=sha))
        return save(p,p['revision'])


def candidate_review(body, submit=False):
    p = project(body['project_id'])
    s = preparation.shot_of(p, body['shot_id'])
    if not body.get('take_id') and not submit:
        with connect() as db:
            return {'candidates':quality.candidates(db,p,s)}
    take = next((t for t in s['takes'] if t['id']==body.get('take_id') and t['kind'] in ('image','video')), None)
    if not take:
        raise ValueError('候选素材不属于当前镜头')
    evidence = quality.inspect(take,media_path,probe_media)
    context_basis = continuity.visual_basis(p,s)
    basis = production.digest([take['id'],evidence,context_basis])
    if not submit:
        scores = dict(quality.CRAFT, **(quality.MOTION if take['kind']=='video' else {}))
        return {'evidence':evidence,'basis':basis,'structure':quality.STRUCTURE,'scores':scores}
    with LOCK, connect() as db:
        if body.get('basis') != basis or project(p['id'])['revision'] != p['revision']:
            raise ValueError('素材或镜头已变化，请重新打开复核')
        return quality.record(db,p,s,take,body,evidence,context_basis)


def probe_media(file):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media_path(file))],timeout=30))

_thumb_lock = threading.Lock()

def thumbnail(name):
    """A small cached JPEG for lists and backdrops. Media names are unique and never rewritten, so the cache never goes stale."""
    src=media_path(name)
    folder=MEDIA/'.thumbs';folder.mkdir(exist_ok=True)
    out=folder/(name+'.jpg')
    if out.is_file():return out
    with _thumb_lock:
        if out.is_file():return out
        tmp=folder/('.'+uid()+'.jpg')
        try:
            for seek in (['-ss','0.3'],[]):
                try:ffmpeg([*seek,'-i',str(src),'-frames:v','1','-vf','scale=360:-2','-q:v','5',str(tmp)])
                except subprocess.CalledProcessError:continue
                if tmp.is_file() and tmp.stat().st_size:break
            else:raise ValueError('无法生成缩略图')
            tmp.replace(out)
        finally:tmp.unlink(missing_ok=True)
    return out

def enqueue_assembly(p,payload,nonce):
    with LOCK:
        p=project(p['id']);s=preparation.shot_of(p,payload.get('shot_id'))
        creative.require_current_state(p,s['episode_id'])
        frozen=assembly.source_plan(p,s['id'],media_path,probe_media)
        snapshot={'id':p['id'],'revision':p['revision'],'episode_id':s['episode_id'],'creative_brief':p['creative_brief'],
                  'assembly':frozen,'target_shot_id':s['id'],'episode_title':next(e['title'] for e in p['episodes'] if e['id']==s['episode_id']),'shots':[]}
        for r in frozen['sources']:
            snapshot['shots'].append({'id':r['segment_id'],'duration':r['duration'],r['kind']:r['file'],
                                     'trim_start':r['trim_start'],'description':'','dialogue':'','asset_ids':[],
                                     'takes':[],'selected_takes':{}})
        now=time.time();dedupe=f"{p['id']}:assemble:{nonce}"
        with connect() as c:
            row=c.execute('SELECT id FROM jobs WHERE dedupe=?',(dedupe,)).fetchone()
            if row:return row['id']
            jid=uid();c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,p['id'],'assemble','queued',json.dumps({'snapshot':snapshot},ensure_ascii=False),None,None,now,now,dedupe))
        return jid

def assemble_local(row,payload):
    snapshot=payload['snapshot'];frozen=snapshot['assembly']
    with LOCK:
        p=project(row['project_id']);s=preparation.shot_of(p,frozen['shot_id'])
        creative.require_current_state(p,s['episode_id'])
        if assembly.source_plan(p,s['id'],media_path,probe_media)!=frozen:raise ValueError('片段选择或制作准备已变化，请重新拼接')
    result=export(snapshot,row['id']);result.update(source='local-assembly',shot_id=s['id'])
    update_job(row['id'],'running',result)
    with LOCK:
        p=project(row['project_id']);s=preparation.shot_of(p,frozen['shot_id'])
        creative.require_current_state(p,s['episode_id'])
        if assembly.source_plan(p,s['id'],media_path,probe_media)!=frozen:raise ValueError('拼接文件已保留，但镜头或片段选择已变化，请重新拼接')
        with connect() as c:
            if c.execute('SELECT state FROM jobs WHERE id=?',(row['id'],)).fetchone()['state']=='cancelled':raise ValueError('本地拼接已取消，未加入素材候选')
        t=production.add_take(s,'video',result['file'],'本地片段拼接','assembly',basis=frozen['basis'],job_id=row['id'])
        t['assembly']=copy.deepcopy(frozen);save(p,p['revision'],candidate_only=True)
        result['take_id']=t['id']
    return result

def audio_duration(file):
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media_path(file))],timeout=30))
    if not any(s['codec_type']=='audio' for s in info.get('streams',[])):raise ValueError('音轨没有有效声音')
    duration=float(info['format']['duration'])
    if not 0<duration<=3600:raise ValueError('音轨时长无效')
    return duration

def export(snapshot,jid):
    with tempfile.TemporaryDirectory(prefix='render-',dir=MEDIA) as folder:
        return render_export(snapshot,jid,Path(folder))

def render_export(snapshot,jid,folder):
    files=[]; cursor=0; captions=[]; clips=[]
    width,height=(720,1280) if snapshot.get('creative_brief',{}).get('format')=='9:16' else (1280,720)
    def stamp(t):
        ms=round(t*1000); return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    for i,s in enumerate(snapshot['shots']):
        with connect() as c:
            if c.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()['state']=='cancelled': raise ValueError('任务已取消')
        clip=production.clip_of(s); src=media_path(clip['file']); out=folder/f'{i:04}.mp4'
        clips.append({'shot_id':s['id'],**clip})
        # Normalize all clips; optional dialogue track replaces original audio.
        # trim_end bounds the window read from the source; the shot's duration still sets the delivered length.
        window=['-t',str(clip['trim_end']-clip['trim_start'])] if clip['kind']=='video' and clip['trim_end'] else []
        args=(['-loop','1','-i',str(src)] if clip['kind']=='image' else ['-ss',str(clip['trim_start']),*window,'-i',str(src)])
        schedule=production.audio_schedule(s,audio_duration)
        if schedule:
            graph=[]
            for n,item in enumerate(schedule,1):
                args+=['-i',str(media_path(item['file']))]
                graph.append(f'[{n}:a]adelay={round(item["start"]*1000)}:all=1[a{n}]')
            graph.append(''.join(f'[a{n}]' for n in range(1,len(schedule)+1))+f'amix=inputs={len(schedule)}:normalize=0:duration=longest,apad[dialogue]')
            args+=['-filter_complex',';'.join(graph)];audio='[dialogue]'
        elif s.get('audio'):
            audio_path=media_path(s['audio'])
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(audio_path)],timeout=30))
            if float(info['format']['duration'])>s['duration']+.15:raise ValueError('对白音轨超过镜头时长，请先延长镜头或调整配音，避免截断台词')
            args+=['-i',str(audio_path)]; audio='1:a:0'
        else:
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(src)],timeout=30))
            if any(x['codec_type']=='audio' for x in probe['streams']): audio='0:a:0'
            else: args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']; audio='1:a:0'
        args+=['-map','0:v:0','-map',audio,'-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,tpad=stop_mode=clone:stop_duration=60',*(['-af','apad'] if not schedule else []),'-t',str(s['duration']),'-c:v','libx264','-preset','fast','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',str(out)]
        ffmpeg(args); files.append(out)
        if s.get('lines'):
            # One cue per line, timed by text length inside the shot (an estimate, not speech alignment).
            texts=[production.dialogue_text(snapshot,[l]) for l in s['lines']]
            times=[(x['start'],x['end']) for x in schedule] if schedule else production.line_timings(s['lines'],s['duration'])
            for (a,b),text in zip(times, texts, strict=True):
                captions.append(f'{len(captions)+1}\n{stamp(cursor+a)} --> {stamp(cursor+b)}\n{text}\n')
        elif s.get('dialogue'): captions.append(f'{len(captions)+1}\n{stamp(cursor)} --> {stamp(cursor+s["duration"])}\n{s["dialogue"]}\n')
        cursor+=s['duration']
    manifest=folder/'concat.txt'; manifest.write_text(''.join(f"file '{f.name}'\n" for f in files))
    merged=folder/'merged.mp4'; ffmpeg(['-f','concat','-safe','1','-i',str(manifest),'-c','copy',str(merged)])
    dest=folder/(jid+'.mp4'); args=['-i',str(merged)]
    if captions:
        srt=folder/'subtitles.srt'; srt.write_text('\n'.join(captions)); args+=['-i',str(srt),'-c:v','copy','-c:a','copy','-c:s','mov_text','-metadata:s:s:0','language=zho']
    else: args+=['-c','copy']
    ffmpeg(args+['-movflags','+faststart',str(dest)])
    proof={'project_id':snapshot['id'],'episode_id':snapshot.get('episode_id'),'revision':snapshot['revision'],'shots':snapshot['shots'],'clips':clips,'creative_brief':snapshot.get('creative_brief'),'duration':cursor,'output':dest.name,'delivery_basis':production.delivery_basis(snapshot),'review_basis':production.review_basis(snapshot),**({'assembly':snapshot['assembly']} if snapshot.get('assembly') else {})}
    proof_file=folder/(jid+'.json');proof_file.write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(dest)],timeout=30))
    if abs(float(probe['format']['duration'])-cursor)>.2:raise ValueError('成片时长验证失败')
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(dest),'-f','null','-'],check=True,capture_output=True,timeout=240)
    proof_file.replace(MEDIA/proof_file.name)
    dest.replace(MEDIA/dest.name)
    return {'manifest':proof_file.name,'file':dest.name,'duration':cursor,'revision':snapshot['revision'],'episode_id':snapshot.get('episode_id'),'episode_title':snapshot.get('episode_title'),'source':'selected-media','delivery_basis':proof['delivery_basis'],'review_basis':proof['review_basis'],'format':snapshot.get('creative_brief',{}).get('format','16:9')}

def work_once():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
        if not row:return False
        c.execute("UPDATE jobs SET state='running',updated=? WHERE id=?",(time.time(),row['id']))
    try:
        payload=json.loads(row['payload'])
        provider = payload.get('provider', {}).get('provider','dify')
        direct_media = domestic_media if provider in domestic_media.KEYS else fal_media if provider == 'fal' else None
        adapter = domestic_media.DomesticMedia() if provider in domestic_media.KEYS else fal_media.Fal() if provider == 'fal' else None
        uses_openai = provider == 'openai'
        asset_image = row['kind']=='asset_image'
        media_kind = 'image' if asset_image else row['kind']
        def checkpoint(result):
            with connect() as c:
                if c.execute('SELECT state FROM jobs WHERE id=?',(row['id'],)).fetchone()['state']=='cancelled': raise ValueError('本地任务已取消，远程调用可能仍在执行')
            update_job(row['id'],'running',result)
        if row['kind']=='assemble':
            result=assemble_local(row,payload);state='succeeded'
        elif row['kind']=='export':
            creative.require_current_state(project(row['project_id']),payload['snapshot']['episode_id'])
            result=export(payload['snapshot'],row['id']);state='succeeded'
        elif payload.get('operation')=='receive':
            result=json.loads(row['result']);state='succeeded'
        elif payload.get('operation')=='listen':
            check_provider(payload,row['kind'])
            adapter = adapter or Dify()
            result=adapter.listen(row['kind'],payload['snapshot'],json.loads(row['result'] or '{}'),checkpoint);state=result['state']
        else:
            check_provider(payload,row['kind'])  # before spend(): a refused job costs no call
            if not direct_media:
                if not uses_openai and not key_for(row['kind']):raise ValueError('该 Dify 工作流已断开连接；未提交生成，未扣授权次数')
                encode_context(payload['snapshot'])
            if len(payload['snapshot'].get('reference_media',[]))>10:raise ValueError('单次生成最多使用 10 个参考素材，未扣授权次数')
            if row['kind']=='audio':
                profile=payload.get('generation_unit',{}).get('adapter_profile')
                if not uses_openai and profile and profile!=os.environ.get('DIFY_AUDIO_PROFILE','alloy-v1'):raise ValueError('配音工作流配置已变化，请重新确认请求')
                speech=production.speech_request(payload['snapshot'],payload.get('generation_unit',{}).get('line_id'))
                if uses_openai:speech['model']=openai_direct.MODELS['audio']
                if payload['snapshot'].get('speech') and speech!=payload['snapshot']['speech']:raise ValueError('冻结的对白请求不一致，拒绝生成')
            for ref in payload.get('generation_unit',{}).get('references',[]):
                if hashlib.sha256(media_path(ref['file']).read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('参考文件内容已变化，请重新确认生成请求')
            with LOCK:
                current=project(row['project_id'])
                episode_id=payload['snapshot'].get('episode_id')
                if not episode_id:episode_id=production_snapshot(current)['episode_id']
                creative.require_current_state(current,episode_id)
                if creative.requires_spec(current):
                    if not creative.requires_spec(payload['snapshot']):raise ValueError('排队任务缺少当前作品的创作规格，请重新准备')
                    creative.validate(payload['snapshot'])
                if asset_image:
                    frozen=payload['snapshot']['generation_segment']
                    current_packet=asset_image_packet(current,dict(frozen,instruction=frozen['user_instruction'],
                                                                 allow_unapproved=frozen['approval']['allow_unapproved']))
                    if current_packet!=frozen:raise ValueError('来源素材或视觉设定已变化，请重新报价')
                if row['kind'] in ('image','video'):
                    frozen=payload.get('generation_unit',{}).get('segment')
                    if not frozen:raise ValueError('旧媒体任务没有片段制作准备，拒绝直接提交')
                    if frozen.get('comparison_id'):
                        with connect() as db:
                            current_packet=comparison.packet(db,current,preparation.shot_of(current,frozen['shot_id']),
                                dict(frozen,seconds=frozen['duration']),media_path)
                    elif frozen['mode']=='storyboard':
                        current_packet=storyboard_packet(current,frozen['shot_id'],frozen['model'],
                                                         reference_mode=frozen.get('reference_mode','image'))
                    else:current_packet=preparation.freeze(current,frozen['shot_id'],row['kind'],frozen['id'],media_path,lambda k:bool(key_for(k)))
                    if current_packet!=frozen:raise ValueError('制作准备或模型能力已变化，请重新确认片段')
                if not asset_image and not production.fresh(current,payload['snapshot']):raise ValueError('来源镜头或承接状态已变化，未提交生成，请重新准备')
                if direct_media:
                    arguments = direct_media.arguments(media_kind, payload['snapshot'], media_path)
                if not uses_openai:spend()
            if uses_openai:
                credential=openai_direct.key()
                def authorize():
                    with LOCK,connect() as c:
                        check_provider(payload,row['kind'])
                        if openai_direct.identity(row['kind'],credential)!=payload['provider']:
                            raise ValueError('OpenAI Key 已变更，未提交生成')
                        if c.execute('SELECT state FROM jobs WHERE id=?',(row['id'],)).fetchone()['state']!='running':
                            raise ValueError('任务已取消，未提交后续调用')
                        if not production.fresh(project(row['project_id']),payload['snapshot']):
                            raise ValueError('来源镜头已变化，未提交后续调用')
                        spend()
                if row['kind']=='audio':
                    result=openai_direct.speech(payload['snapshot'],credential,authorize,MEDIA/(row['id']+'.wav'))
                else:
                    result=openai_direct.revise(payload['snapshot'],credential,authorize)
                    if result['state']=='succeeded':
                        revision_comparison(project(row['project_id']),payload['snapshot'],result['result'])
            elif direct_media:
                checkpoint({'submission_started_at':time.time(),'billing_status':'unreconciled'})
                result=adapter.submit(media_kind, payload['snapshot'], arguments, checkpoint)
            elif row['kind'] in ('image','video','audio'):
                result=Dify().run(row['kind'],payload['snapshot'],checkpoint,media_path=media_path)
            else:result=Dify().run(row['kind'],payload['snapshot'],checkpoint)
            state=result['state']
        if state=='succeeded' and media_kind in ('image','video','audio'):
            update_job(row['id'],'running',result)
            from .media_bridge import receive
            file=result.get('candidate_file')
            if not file:
                try:
                    file=receive(result['result']['url'],media_kind,MEDIA)
                except (OSError, ValueError, subprocess.SubprocessError, KeyError):
                    raise UncertainRun('远程结果尚未入库，请恢复原任务，不重新生成') from None
                result['candidate_file']=file
                update_job(row['id'],'running',result)
            else:media_path(file)
            if direct_media:
                with media_path(file).open('rb') as stream:
                    output_sha=hashlib.file_digest(stream,'sha256').hexdigest()
                if result.get('output_sha256') and result['output_sha256']!=output_sha:
                    raise UncertainRun('候选文件内容已变化，已保留原任务记录')
                result['output_sha256']=output_sha
                result.setdefault('billing_status','unreconciled')
                result.setdefault('model',payload['provider'].get('model'))

            if asset_image:
                update_job(row['id'],state,result)
                return True
            with LOCK:
                p=project(row['project_id']);s=next((s for s in p['shots'] if s['id']==payload['snapshot']['target_shot_id']),None)
                if not s:
                    update_job(row['id'],'failed',result,'生成结果已保存，但来源镜头已删除')
                    return True
                # Finished paid output is retained even if the user has since locked the shot.
                was_locked=s.get('locked');s['locked']=False
                source=provider
                label={'ark':'Seedream 分镜候选','dashscope':'Wan 视频候选','minimax':'海螺视频候选','fal':'fal 生成候选','openai':'OpenAI 配音候选','dify':'Dify 生成候选'}[source]
                t=production.add_take(s,row['kind'],file,label,source,basis=payload.get('generation_unit',{}).get('basis') or production.take_basis(next(x for x in payload['snapshot']['shots'] if x['id']==s['id'])),job_id=row['id'],shot_basis=production.content_basis(next(x for x in payload['snapshot']['shots'] if x['id']==s['id'])))
                if t and source in domestic_media.KEYS:
                    t['model']=payload['provider']['model']
                if t and payload.get('generation_unit',{}).get('segment'):
                    segment=payload['generation_unit']['segment']
                    t['generation_segment']={k:segment[k] for k in ('id','start','end','shot_id')}
                    if segment.get('comparison_id'):
                        t['comparison_id']=segment['comparison_id']
                if t and row['kind']=='audio':
                    snapshot=payload['snapshot']
                    line_id=snapshot.get('speech',{}).get('line_id')
                    source_shot=next(x for x in snapshot['shots'] if x['id']==s['id'])
                    t['speech_basis']=production.speech_basis(snapshot,source_shot,line_id)
                    if line_id:t['line_id']=line_id
                s['locked']=was_locked
                save(p,p['revision'],candidate_only=True);result['candidate_file']=file
        update_job(row['id'],state,result)
    except UncertainRun as e:
        with connect() as c: current=c.execute('SELECT result FROM jobs WHERE id=?',(row['id'],)).fetchone()
        update_job(row['id'],'interrupted',json.loads(current['result'] or '{}'),str(e))
    except Exception as e:
        message=str(e) if isinstance(e,ValueError) else f'{type(e).__name__}：执行失败，请检查服务与媒体格式'
        with connect() as c: current=c.execute('SELECT result FROM jobs WHERE id=?',(row['id'],)).fetchone()
        receipt=json.loads(current['result']) if current['result'] else None
        if receipt and not isinstance(e,RemoteTaskFailed) and (
            receipt.get('run_id') or (row['kind'] in ('image','asset_image','video','audio') and receipt.get('state')=='succeeded')
        ):
            update_job(row['id'],'interrupted',receipt,error=message)
        else:
            update_job(row['id'],'failed',receipt,error=message)
    return True

def worker():
    while True:
        if not work_once():time.sleep(.5)

def byte_range(header, size):
    """Resolve a single-range Range header against a file of `size` bytes.

    Returns (start, end) inclusive, None to serve the whole file (no header, a form we do not
    parse, or several ranges), or raises ValueError when the range cannot be satisfied (416).
    """
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', (header or '').strip())
    if not match or not (match.group(1) or match.group(2)):
        return None
    first, last = match.groups()
    if not first:  # suffix form: the final N bytes
        count = int(last)
        if count == 0 or size == 0:
            raise ValueError('无效媒体范围')
        return max(size - count, 0), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise ValueError('无效媒体范围')
    return start, end


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def respond(self,data,status=200):
        content=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(content))); self.end_headers(); self.wfile.write(content)
    def do_GET(self):
        try:
            path=urlparse(self.path).path
            if self.headers.get('Host','').split(':')[0] not in ('127.0.0.1','localhost'):return self.respond({'error':'仅允许本机访问'},403)
            if path=='/api/state':
                with connect() as c:
                    ps=[production.normalize(normalize_project(json.loads(r['body']))) for r in c.execute('SELECT body FROM projects')]
                    js=[public_job(r) for r in c.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100')]
                readiness={p['id']:{e['id']:production.readiness(p,e['id']) for e in p['episodes']} for p in ps}
                return self.respond({'projects':ps,'jobs':js,'readiness':readiness,'spending':spending(),'providers':PROVIDERS,'dify_base_url':os.environ.get('DIFY_BASE_URL','https://api.dify.ai/v1'),'openai_direct':bool(openai_direct.key()),'dify':{k:bool(key_for(k)) for k in ('script','assets','shots','revision','image','video','audio','plan','qc')}})
            if path.startswith('/api/versions/'):
                with connect() as c: rows=c.execute('SELECT id,body,created FROM versions WHERE project_id=? ORDER BY created DESC LIMIT 30',(path.split('/')[-1],)).fetchall()
                return self.respond([{'id':r['id'],'project':normalize_project(json.loads(r['body'])),'created':r['created']} for r in rows])
            if path.startswith('/thumb/'):file=thumbnail(unquote(path[7:]))
            elif path.startswith('/media/'):file=media_path(unquote(path[7:]))
            else:
                file=(ROOT/'web'/('index.html' if path=='/' else unquote(path.lstrip('/')))).resolve()
                if not file.is_relative_to(ROOT/'web') or not file.is_file():return self.respond({'error':'不存在'},404)
            size=file.stat().st_size; start=0; end=size-1; status=200
            try:requested=byte_range(self.headers.get('Range'),size)
            except ValueError:return self.respond({'error':'无效媒体范围'},416)
            if requested:start,end=requested;status=206
            self.send_response(status); self.send_header('Content-Type',mimetypes.guess_type(file)[0] or 'application/octet-stream'); self.send_header('Content-Length',str(end-start+1)); self.send_header('Accept-Ranges','bytes'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Cache-Control','no-store')
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with file.open('rb') as f:
                f.seek(start); remaining=end-start+1
                while remaining:
                    chunk=f.read(min(65536,remaining))
                    if not chunk:break
                    self.wfile.write(chunk); remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):pass
        except FileNotFoundError:
            self.respond({'error':'文件不存在'},404)
        except ValueError as error:
            self.respond({'error':str(error)},400)
        except (OSError, sqlite3.Error, subprocess.SubprocessError):
            self.respond({'error':'暂时无法读取作品或媒体'},500)
    def do_POST(self):
        try:
            if self.headers.get('Host','').split(':')[0] not in ('127.0.0.1','localhost'):return self.respond({'error':'仅允许本机访问'},403)
            # Browser same-origin and custom header prevent cross-site local writes.
            if self.headers.get('X-Luma')!='studio':return self.respond({'error':'拒绝跨站写入'},403)
            origin=self.headers.get('Origin')
            if origin and origin!=f'http://{self.headers.get("Host")}':return self.respond({'error':'来源无效'},403)
            path=urlparse(self.path).path; length=int(self.headers.get('Content-Length','0'))
            if length < 0:raise ValueError('请求长度无效')
            if length>200*1024*1024:raise ValueError('单次上传限 200 MB')
            if path.startswith('/api/upload/') and path!='/api/upload/discard':
                ext=path.rsplit('/',1)[1]
                if ext not in ('mp4','mov','wav','mp3','m4a','png','jpg','jpeg','webp'):raise ValueError('不支持该媒体格式')
                name=uid()+'.'+ext; dest=MEDIA/name; dest.write_bytes(self.rfile.read(length))
                try:
                    formats={'mp4':'mov','mov':'mov','m4a':'mov','mp3':'mp3','wav':'wav',
                             'png':'png_pipe','jpg':'jpeg_pipe','jpeg':'jpeg_pipe','webp':'webp_pipe'}
                    is_image=dest.suffix in visual.IMAGE_EXTENSIONS
                    if is_image:
                        with dest.open('rb') as stream:
                            mime=visual.image_mime(stream.read(12))
                        if mime!=mimetypes.guess_type(dest.name)[0]:
                            raise ValueError('图片字节与扩展名不匹配')
                    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-protocol_whitelist','file,pipe',
                        '-f',formats[ext],'-show_streams','-of','json',str(dest)],timeout=30,stderr=subprocess.DEVNULL))
                    expected='audio' if ext in ('wav','mp3','m4a') else 'video'
                    matching=[stream for stream in info.get('streams',[]) if stream['codec_type']==expected]
                    if not matching or (is_image and not any(s.get('width',0)>0 and s.get('height',0)>0 for s in matching)):
                        raise ValueError('媒体类型与扩展名不匹配')
                except (OSError, ValueError, subprocess.SubprocessError) as err:
                    dest.unlink(missing_ok=True); raise ValueError('媒体格式验证失败') from err
                return self.respond({'file':name,'streams':[s['codec_type'] for s in info['streams']]})
            if length>2*1024*1024:raise ValueError('请求过大')
            body=json.loads(self.rfile.read(length) or '{}')
            if not isinstance(body, dict):raise ValueError('请求内容必须是 JSON 对象')
            if path=='/api/upload/discard':return self.respond(discard_upload(body.get('file')))
            if path=='/api/preparation/initialize':return self.respond(initialize_preparation(body['project_id'],body['revision'],body.get('episode_id')))
            if path=='/api/preparation/open':return self.respond(open_preparation(body['project_id'],body['shot_id'],body.get('kind','video')))
            if path=='/api/preparation/save':return self.respond(save_preparation(body['project_id'],body['shot_id'],body['revision'],body['plan'],body['basis']))
            if path=='/api/continuity/preview':return self.respond(continuity_preview(body['project_id'],body['episode_id']))
            if path=='/api/continuity/confirm':return self.respond(confirm_continuity(body['project_id'],body['episode_id'],body['revision'],body['digest'],body['resolution'],body.get('reason','')))
            if path=='/api/import/drama/preview':return self.respond(preview_drama_import(body.get('bundle')))
            if path=='/api/import/drama/apply':return self.respond(apply_drama_import(body.get('id'),body.get('digest')))
            if path in ('/api/camera/preview','/api/camera/apply'):return self.respond(shot_camera(body,path.endswith('/apply')))
            if path=='/api/projects/sample':return self.respond(sample_scene.create(MEDIA,save))
            if path=='/api/rehearsal':return self.respond(production.rehearsal(project(body['project_id']),body['episode_id']))
            if path=='/api/projects':return self.respond(create(body['title'],body.get('script','')))
            if path=='/api/shots':return self.respond(add_shot(body['project_id'],body['episode_id'],body['revision'],body.get('fields',{})))
            if path=='/api/apply':return self.respond(apply_job(body['project_id'],body['job_id'],body['revision'],body.get('mode'),body.get('preview_digest')))
            if path=='/api/revision-preview':return self.respond(revision_preview(body['project_id'],body['job_id'],body['revision']))
            if path=='/api/apply-preview':return self.respond(adoption_preview(body['project_id'],body['job_id'],body['revision'],body.get('mode','append')))
            if path=='/api/save':return self.respond(save(body['project'],body['revision'],reference_actions_only=True))
            if path=='/api/assets/image-candidates':return self.respond(asset_image_candidates(body))
            if path=='/api/assets/approve-reference':return self.respond(approve_imported_reference(body))
            if path=='/api/jobs/bill':return self.respond(record_job_bill(body))
            if path=='/api/assets/approve-image':return self.respond(approve_asset_image(body))
            if path in ('/api/quality/open','/api/quality/record'):
                return self.respond(candidate_review(body,path.endswith('/record')))
            if path=='/api/production':return self.respond(edit_production(body))
            if path=='/api/production/evidence':return self.respond(production_evidence(body))
            if path=='/api/settings/spending':return self.respond(set_spending(body.get('remaining')))
            if path=='/api/director/references':return self.respond(director_references(body))
            if path=='/api/jobs/video-comparison':return self.respond(video_comparison(body))
            if path in ('/api/jobs/batch/quote','/api/jobs/batch/submit'):
                return self.respond(production_batch(body,path.endswith('/submit')))
            if path=='/api/jobs/batch/state':return self.respond(batch_state(body))
            if path=='/api/jobs/quote':return self.respond(preview_job_quote(body['project_id'],body['kind'],body))
            if path=='/api/jobs':return self.respond({'id':enqueue(body['project_id'],body['kind'],body,body['nonce'],require_quote=True)})
            if path=='/api/review':
                review_job(body['project_id'],body['job_id'],body['revision'],body['review_id'],body['action'],body.get('notes',''))
                return self.respond({'ok':True})
            if path=='/api/reconcile':
                reconcile_job(body['project_id'],body['job_id']);return self.respond({'ok':True})
            if path=='/api/settings/dify':return self.respond(configure_dify(body.get('base_url',''),body.get('api_key',''),body.get('kind','shots')))
            if path=='/api/settings/dify/check':return self.respond(Dify().inspect_connection(body.get('kind')))
            if path=='/api/settings/openai':return self.respond(configure_openai(body.get('api_key')))
            if path=='/api/settings/media-key':return self.respond(configure_media_key(body.get('provider'),body.get('api_key')))
            if path=='/api/settings/fal':return self.respond(configure_fal(body.get('api_key')))
            if path=='/api/cancel':
                with connect() as c:
                    changed=c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state IN ('queued','paused','waiting_review')",(time.time(),body['id'])).rowcount
                    if not changed:raise ValueError('已提交的任务需要等待结果或在供应商处处理')
                return self.respond({'ok':True})
            return self.respond({'error':'接口不存在'},404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except KeyError:
            self.respond({'error':'请求缺少必要字段'},400)
        except ValueError as error:
            self.respond({'error':str(error)},400)
        except (OSError, sqlite3.Error, subprocess.SubprocessError):
            self.respond({'error':'暂时无法保存或处理请求'},500)

def load_env():
    p=env_file()
    if p.exists():
        for line in p.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))

def main():
    parser=argparse.ArgumentParser(description='流幕本机工作室')
    commands=parser.add_subparsers(dest='command')
    commands.add_parser('check',help='检查本机运行依赖')
    commands.add_parser('backup',help='将作品和素材备份到新目录').add_argument('destination',type=Path)
    commands.add_parser('restore',help='从备份恢复到 LUMA_DATA 指定的新目录').add_argument('source',type=Path)
    options=parser.parse_args()
    try:
        if options.command=='backup':
            local_storage.backup(DATA,options.destination)
            print(f'已备份作品与素材：{options.destination.resolve()}')
            return
        if options.command=='restore':
            local_storage.restore(options.source,DATA)
            print(f'已恢复作品与素材，生成额度保持暂停：{DATA.resolve()}')
            return
        if sys.version_info<(3,11):raise ValueError('流幕需要 Python 3.11 或更新版本')
        missing=[name for name in ('ffmpeg','ffprobe') if not shutil.which(name)]
        if missing:raise ValueError('缺少媒体工具：'+', '.join(missing)+'。安装 FFmpeg 后重试。')
        if options.command=='check':
            print('Python、FFmpeg 和 ffprobe 已就绪')
            return
        load_env()
        port=int(os.environ.get('PORT','7820'))
        if not 1<=port<=65535:raise ValueError('PORT 必须在 1 到 65535 之间')
        with local_storage.data_lock(DATA), ThreadingHTTPServer(('127.0.0.1',port),Handler) as server:
            init()
            threading.Thread(target=worker,daemon=True).start()
            print(f'Luma · 流幕 http://127.0.0.1:{port}',flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1,f'流幕：{error}\n')
