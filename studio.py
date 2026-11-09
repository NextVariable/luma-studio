"""Local-only studio: transactional project state, durable jobs and FFmpeg export."""
import argparse, copy, json, os, shutil, sqlite3, sys, tempfile, uuid, time, threading, subprocess, mimetypes, hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
from providers import Dify, PROVIDERS, encode_context, key_for, key_env_for, provider_identity, UncertainRun
from contracts import validate
from episodes import normalize_project, validate_episodes, changed_episodes, production_snapshot
import production
import creative
import preparation
import assembly
import continuity
import local_storage

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('AUTEUR_DATA', ROOT/'data'))
MEDIA = DATA/'media'
DB = DATA/'studio.sqlite'
LOCK = threading.RLock()

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
        INSERT OR IGNORE INTO spending VALUES(1,0,0);
        ''')
        c.execute("UPDATE jobs SET state='interrupted',error='服务重启；外部调用结果待核实，避免重复收费',updated=? WHERE state IN ('running','submitting')",(time.time(),))

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

def save(p, expected, candidate_only=False, state_confirmation=None, source_confirmation=False):
    submitted={s['id']:copy.deepcopy(s) for s in p['shots']}
    production.normalize(normalize_project(p))
    validate_project(p)
    with LOCK, connect() as c:
        old=c.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()
        if old:
            old=production.normalize(normalize_project(json.loads(old['body'])))
            if old['revision'] != expected: raise ValueError('作品已更新，请刷新后再编辑')
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
            if before and (s.get('preparation') or s.get('creative_spec') or s.get('continuity_from')) and continuity.basis(old,before)!=continuity.basis(p,s):s.update(approved=False,needs_review=True)
        for s in p['shots']:
            if creative.continuity_status(p,s['episode_id'])['requires_confirmation']:
                if submitted[s['id']].get('approved') and not submitted[s['id']].get('needs_review'):
                    prior=next((x for x in (old or {}).get('shots',[]) if x['id']==s['id']),{})
                    if not prior.get('approved') or prior.get('needs_review'):raise ValueError('跨集状态待确认，不能审核此镜头')
                s.update(approved=False,needs_review=True)
        for s in p['shots']:
            prior=next((x for x in (old or {}).get('shots',[]) if x['id']==s['id']),{})
            if submitted[s['id']].get('approved') and not submitted[s['id']].get('needs_review') and (not prior.get('approved') or prior.get('needs_review')):
                issue=preparation.current_issue(p,s)
                if issue:raise ValueError(issue)
        validate_project(p)
        production.validate(p,media_path)
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
            'references':preparation.catalog(p,s),'models':copy.deepcopy(preparation.MODELS),
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
    from drama_import import convert
    preview=convert(bundle)
    validate_project(preview['project']);production.validate(preview['project'],media_path)
    token=uid();digest=production.digest(preview)
    # Keep source and converted facts together; the confirmation never rereads mutable desktop files.
    with connect() as c:c.execute('INSERT INTO import_previews VALUES(?,?,?,?,NULL)',(token,digest,json.dumps({'preview':preview,'bundle':bundle},ensure_ascii=False),time.time()))
    return {'id':token,'digest':digest,'summary':preview['summary'],'warnings':preview['warnings'],
            'mapping':{'action':'画面描述','shotSize':'景别','cameraMovement':'运镜','dialogue':'逐句对白',
                       'narrativePurpose/composition/continuityIn/continuityOut/sound':'保留于镜头创作规格','characters/outfits/assets':'共享资产及固定造型版本'},
            'sample':preview['project']['shots'][0]}

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
    production.normalize(candidate);validate_project(candidate);production.validate(candidate,media_path);creative.validate(candidate)
    changes=[{'field':k,'before':target.get(k),'after':after.get(k)} for k in production.PLAN_TEXT_FIELDS if target.get(k)!=after.get(k)]
    effects=[]
    if preparation.current_issue(candidate,after):effects.append('制作准备需按新镜头重新确认')
    if target.get('segment_sources'):effects.append('原片段素材保留，继续拼接前需重新确认选用')
    if target.get('audio') and not after.get('audio'):effects.append('对白已改变，原整镜音轨保留为候选，不再自动选用')
    if any(target.get(k) and not after.get(k) for k in ('image','video')):effects.append('原画面范围不适用于新时长，保留候选并取消整镜选用')
    if changes:effects.append('本镜需要重新审核；已有成片保留为历史版本')
    return {'effects':effects,'target_shot_id':target_id,'number':1+[s['id'] for s in p['shots'] if s['episode_id']==target['episode_id']].index(target_id),
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

def edit_production(body):
    with LOCK:
        p=project(body['project_id'])
        if p['revision']!=body['revision']:raise ValueError('作品已更新，请刷新')
        action=body['action']
        if action in ('asset_version','asset_select','character_look'):
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
                else:s['lines']=[{'id':l.get('id') or uid(),'speaker_asset_id':l.get('speaker_asset_id') or None,'text':l.get('text','')} for l in lines] if isinstance(lines,list) else lines
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
            else:raise ValueError('未知制作操作')
        return save(p,p['revision'],source_confirmation=action in ('bind_segment_source','bind_segment_sources'))

def media_path(name):
    if not isinstance(name,str) or Path(name).name != name or not name: raise ValueError('非法媒体路径')
    path=(MEDIA/name).resolve()
    if path.parent != MEDIA.resolve() or not path.is_file(): raise ValueError('素材不存在')
    return path

def enqueue(pid,kind,payload,nonce):
    if kind not in ('script','assets','shots','revision','image','video','audio','plan','qc','export','assemble'): raise ValueError('未知任务类型')
    p=project(pid)
    if kind=='assemble':return enqueue_assembly(p,payload,nonce)
    episode_id=payload.get('episode_id') or (p['episodes'][0]['id'] if len(p['episodes'])==1 else None)
    if episode_id:creative.require_current_state(p,episode_id)
    snapshot=production_snapshot(p,payload.get('episode_id')) if kind=='export' else production.scope(p,payload.get('episode_id'),payload.get('shot_id'),payload.get('instruction',''))
    if kind in ('revision','image','video','audio') and not snapshot.get('target_shot_id'):raise ValueError('请指定目标镜头')
    if kind=='audio':snapshot['speech']=production.speech_request(snapshot,payload.get('line_id'))
    if kind=='audio' and (snapshot['speech']['line_id'] or snapshot['speech']['voice_id']!='alloy') and os.environ.get('DIFY_AUDIO_PROFILE')!='character-lines-v1':
        raise ValueError('角色逐句配音工作流尚未发布接入；可以先导入逐句音轨')
    packet=None
    if kind in ('image','video'):
        packet=preparation.freeze(p,snapshot['target_shot_id'],kind,payload.get('segment_id'),media_path,lambda k:bool(key_for(k)))
        refs=packet['references'];selected={(r['reference_id'],r['role']) for r in refs}
        plan={'items':refs,'mode':'first_frame' if packet['mode']=='image_to_video' else 'first_last_frame' if packet['mode']=='start_end_frames' else 'references',
              'omitted':[{**r,'reason':'未选入本片段'} for r in preparation.catalog(p,preparation.shot_of(p,snapshot['target_shot_id'])) if not any(x[0]==r['reference_id'] for x in selected)]}
        snapshot['generation_segment']=packet
    if kind=='audio':plan=production.reference_plan(p,snapshot['target_shot_id'],kind)
    if kind in ('image','video','audio'):
        if len(plan['items'])>10:raise ValueError('单次生成最多使用 10 个参考素材，请减少本镜头绑定的视图或资产')
        snapshot.update(reference_media=plan['items'],reference_mode=plan['mode'],reference_omitted=plan['omitted'])
    if kind=='revision' and (not isinstance(payload.get('instruction'),str) or not 1<=len(payload['instruction'].strip())<=2000):raise ValueError('请填写不超过 2000 字的单镜修改要求')
    if kind=='export' and not production.readiness(p,snapshot['episode_id'])['can_export']:
        raise ValueError('导出前每个镜头都需有图片或视频、通过审核且无待复核修改')
    if kind!='export':
        encode_context(snapshot)
        if not key_for(kind):raise ValueError('尚未连接该 Dify 工作流；请先配置已发布应用的 API Key')
        if spending()['remaining']==0:raise ValueError('付费调用已暂停，请先明确授权本批次数')
    dedupe=f'{pid}:{snapshot["episode_id"]}:{kind}:{nonce}'
    now=time.time()
    with connect() as c:
        existing=c.execute('SELECT id FROM jobs WHERE dedupe=?',(dedupe,)).fetchone()
        if existing:return existing['id']
        jid=uid()
        body={'snapshot':snapshot}
        if kind=='revision':body['revision_preview_required']=True
        if kind!='export':body['provider']=provider_identity(kind)  # frozen now; compared again before any remote call
        if kind in ('image','video','audio'):
            body['generation_unit']={'id':uid(),'shot_ids':[snapshot['target_shot_id']], 'kind':kind,
                'line_id':snapshot.get('speech',{}).get('line_id'),'input_digest':production.digest(snapshot),
                'parameters':copy.deepcopy(snapshot.get('speech') or {'mode':snapshot.get('reference_mode'),'duration':next(s['duration'] for s in snapshot['shots'] if s['id']==snapshot['target_shot_id'])}),
                'provider':body['provider'],'references':[{'file':r['file'],'sha256':hashlib.sha256(media_path(r['file']).read_bytes()).hexdigest()} for r in snapshot.get('reference_media',[])],
                'adapter_profile':os.environ.get('DIFY_AUDIO_PROFILE','alloy-v1') if kind=='audio' else 'external-workflow', 'created':now}
            if packet:body['generation_unit'].update(segment=packet,parameters={**packet['parameters'],**({'duration':packet['duration']} if kind=='video' else {})},
                                                     basis=production.take_basis(preparation.shot_of(p,snapshot['target_shot_id'])))
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,pid,kind,'queued',json.dumps(body),None,None,now,now,dedupe))
    return jid

def check_provider(payload, kind=None):
    """Refuse to continue a job against a different Dify app than the one it was queued with.
    Jobs queued before identities were recorded have none and are accepted as before."""
    frozen=payload.get('provider')
    if not frozen:return
    kind=kind or next((k for k in ('script','assets','shots','revision','image','video','audio','plan','qc') if key_env_for(k)==frozen['key_env']),None)
    if kind and not key_for(kind):return  # no key now: the adapter reports 'not configured' itself, nothing can be sent
    now=provider_identity(kind) if kind else None
    if not now or now['host']!=frozen['host'] or (frozen.get('endpoint_fingerprint') and now['endpoint_fingerprint']!=frozen['endpoint_fingerprint']):raise ValueError('Dify 地址已变更，此任务是用另一个地址提交的；不自动继续，请在原应用核对或重新发起')
    if now['key_fingerprint']!=frozen['key_fingerprint']:raise ValueError('Dify 应用 Key 已更换，此任务属于原应用；不自动继续，请换回原 Key 核实，或重新发起')

def update_job(jid,state,result=None,error=None):
    with connect() as c:
        c.execute('UPDATE jobs SET state=?,result=?,error=?,updated=? WHERE id=? AND state!=?',(state,json.dumps(result,ensure_ascii=False) if result is not None else None,error,time.time(),jid,'cancelled'))

def public_job(row):
    job={k:row[k] for k in ('id','project_id','kind','state','result','error','created','updated')}
    snapshot=json.loads(row['payload']).get('snapshot',{})
    job.update(episode_id=snapshot.get('episode_id'),episode_title=snapshot.get('episode_title'),source_revision=snapshot.get('revision'))
    try:job['fresh']=production.fresh(project(row['project_id']),snapshot)
    except ValueError:job['fresh']=False
    job['target_shot_id']=snapshot.get('target_shot_id');job['scope']=snapshot.get('scope');job['provider']=json.loads(row['payload']).get('provider')
    job['generation_unit']=json.loads(row['payload']).get('generation_unit')
    if job['result']:
        result=json.loads(job['result']);result.pop('form_token',None)
        if isinstance(result.get('form'),dict):
            result['form']={k:result['form'][k] for k in ('form_content','inputs','user_actions','resolved_default_values','expiration_time') if k in result['form']}
        job['result']=json.dumps(result,ensure_ascii=False)
    return job

def configure_dify(base,key,kind='shots'):
    if kind not in ('shots','revision','image','video','audio','script','assets','plan','qc'):raise ValueError('工作流类型无效')
    if not isinstance(base,str) or not isinstance(key,str): raise ValueError('配置格式无效')
    base=base.strip().rstrip('/');key=key.strip();parsed=urlparse(base)
    if (len(base)>2048 or any(c.isspace() for c in base) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not (parsed.scheme=='https' or (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')))):
        raise ValueError('Dify 地址必须是 HTTPS 或本机服务')
    if not key.startswith('app-') or any(c.isspace() for c in key) or len(key)>512:
        raise ValueError('请使用已发布应用的 app- API Key，不使用账号会话凭据')
    with LOCK:
        path=ROOT/'.env';values={'DIFY_BASE_URL':base,('DIFY_PRODUCTION_KEY' if kind=='shots' else 'DIFY_'+kind.upper()+'_KEY'):key}
        lines=path.read_text().splitlines() if path.exists() else []
        lines=[line for line in lines if line.split('=',1)[0].strip() not in values]
        text='\n'.join([*lines,*[k+'='+v for k,v in values.items()]])+'\n'
        tmp=ROOT/('.env-'+uid()+'.tmp')
        try:
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(text)
            os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
        os.environ.update(values)
    return {'configured':True,'verified':False,'base_url':base}

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

def reconcile_job(pid,jid):
    with LOCK, connect() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['project_id']!=pid or row['kind']=='export' or row['state'] not in ('interrupted','waiting_review','failed'): raise ValueError('此任务不能核实远程状态')
        result=json.loads(row['result'] or '{}')
        if not result.get('run_id') and not (row['kind'] in ('image','video','audio') and result.get('result',{}).get('url')): raise ValueError('未取得远程运行编号，请到 Dify 日志核对，不自动重发')
        payload=json.loads(row['payload'])
        if not (row['kind'] in ('image','video','audio') and result.get('result',{}).get('url')):check_provider(payload,row['kind'])
        payload['operation']='receive' if row['kind'] in ('image','video','audio') and result.get('result',{}).get('url') else 'listen'
        c.execute("UPDATE jobs SET state='queued',payload=?,error=NULL,updated=? WHERE id=?",(json.dumps(payload),time.time(),jid))

def ffmpeg(args):
    subprocess.run(['ffmpeg','-nostdin','-y','-loglevel','error',*args],check=True,capture_output=True,timeout=240)

def probe_media(file):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media_path(file))],timeout=30))

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
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(audio_path)]))
            if float(info['format']['duration'])>s['duration']+.15:raise ValueError('对白音轨超过镜头时长，请先延长镜头或调整配音，避免截断台词')
            args+=['-i',str(audio_path)]; audio='1:a:0'
        else:
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(src)]))
            if any(x['codec_type']=='audio' for x in probe['streams']): audio='0:a:0'
            else: args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']; audio='1:a:0'
        args+=['-map','0:v:0','-map',audio,'-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,tpad=stop_mode=clone:stop_duration=60',*(['-af','apad'] if not schedule else []),'-t',str(s['duration']),'-c:v','libx264','-preset','fast','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',str(out)]
        ffmpeg(args); files.append(out)
        if s.get('lines'):
            # One cue per line, timed by text length inside the shot (an estimate, not speech alignment).
            texts=[production.dialogue_text(snapshot,[l]) for l in s['lines']]
            times=[(x['start'],x['end']) for x in schedule] if schedule else production.line_timings(s['lines'],s['duration'])
            for (a,b),text in zip(times,texts):
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
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(dest)]))
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
            result=Dify().listen(row['kind'],payload['snapshot'],json.loads(row['result'] or '{}'),checkpoint);state=result['state']
        else:
            check_provider(payload,row['kind'])  # before spend(): a refused job costs no call
            if not key_for(row['kind']):raise ValueError('该 Dify 工作流已断开连接；未提交生成，未扣授权次数')
            encode_context(payload['snapshot'])
            if len(payload['snapshot'].get('reference_media',[]))>10:raise ValueError('单次生成最多使用 10 个参考素材，未扣授权次数')
            if row['kind']=='audio':
                profile=payload.get('generation_unit',{}).get('adapter_profile')
                if profile and profile!=os.environ.get('DIFY_AUDIO_PROFILE','alloy-v1'):raise ValueError('配音工作流配置已变化，请重新确认请求')
                speech=production.speech_request(payload['snapshot'],payload.get('generation_unit',{}).get('line_id'))
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
                if row['kind'] in ('image','video'):
                    frozen=payload.get('generation_unit',{}).get('segment')
                    if not frozen:raise ValueError('旧媒体任务没有片段制作准备，拒绝直接提交')
                    current_packet=preparation.freeze(current,frozen['shot_id'],row['kind'],frozen['id'],media_path,lambda k:bool(key_for(k)))
                    if current_packet!=frozen:raise ValueError('制作准备或模型能力已变化，请重新确认片段')
                if not production.fresh(current,payload['snapshot']):raise ValueError('来源镜头或承接状态已变化，未提交生成，请重新准备')
                spend()
            adapter=Dify()
            if row['kind'] in ('image','video','audio'):
                result=adapter.run(row['kind'],payload['snapshot'],checkpoint,media_path=media_path)
            else:result=adapter.run(row['kind'],payload['snapshot'],checkpoint)
            state=result['state']
        if state=='succeeded' and row['kind'] in ('image','video','audio'):
            update_job(row['id'],'running',result)
            from media_bridge import receive
            file=result.get('candidate_file')
            if not file:
                file=receive(result['result']['url'],row['kind'],MEDIA)
                result['candidate_file']=file
                update_job(row['id'],'running',result)
            else:media_path(file)
            with LOCK:
                p=project(row['project_id']);s=next((s for s in p['shots'] if s['id']==payload['snapshot']['target_shot_id']),None)
                if not s:raise ValueError('生成结果已保存，但来源镜头已删除')
                # Finished paid output is retained even if the user has since locked the shot.
                was_locked=s.get('locked');s['locked']=False
                t=production.add_take(s,row['kind'],file,'Dify 生成候选','dify',basis=payload.get('generation_unit',{}).get('basis') or production.take_basis(next(x for x in payload['snapshot']['shots'] if x['id']==s['id'])),job_id=row['id'])
                if t and payload.get('generation_unit',{}).get('segment'):t['generation_segment']={k:payload['generation_unit']['segment'][k] for k in ('id','start','end','shot_id')}
                if t and payload['snapshot'].get('speech',{}).get('line_id'):t['line_id']=payload['snapshot']['speech']['line_id']
                s['locked']=was_locked
                save(p,p['revision'],candidate_only=True);result['candidate_file']=file
        update_job(row['id'],state,result)
    except UncertainRun as e:
        with connect() as c: current=c.execute('SELECT result FROM jobs WHERE id=?',(row['id'],)).fetchone()
        update_job(row['id'],'interrupted',json.loads(current['result'] or '{}'),str(e))
    except Exception as e:
        message=str(e) if isinstance(e,ValueError) else f'{type(e).__name__}：执行失败，请检查服务与媒体格式'
        with connect() as c: current=c.execute('SELECT result FROM jobs WHERE id=?',(row['id'],)).fetchone()
        update_job(row['id'],'failed',json.loads(current['result']) if current['result'] else None,error=message)
    return True

def worker():
    while True:
        if not work_once():time.sleep(.5)

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
                return self.respond({'projects':ps,'jobs':js,'readiness':readiness,'spending':spending(),'providers':PROVIDERS,'dify_base_url':os.environ.get('DIFY_BASE_URL','https://api.dify.ai/v1'),'dify':{k:bool(key_for(k)) for k in ('script','assets','shots','revision','image','video','audio','plan','qc')}})
            if path.startswith('/api/versions/'):
                with connect() as c: rows=c.execute('SELECT id,body,created FROM versions WHERE project_id=? ORDER BY created DESC LIMIT 30',(path.split('/')[-1],)).fetchall()
                return self.respond([{'id':r['id'],'project':normalize_project(json.loads(r['body'])),'created':r['created']} for r in rows])
            if path.startswith('/media/'):file=media_path(unquote(path[7:]))
            else:
                file=(ROOT/'web'/('index.html' if path=='/' else unquote(path.lstrip('/')))).resolve()
                if not file.is_relative_to(ROOT/'web') or not file.is_file():return self.respond({'error':'不存在'},404)
            size=file.stat().st_size; start=0; end=size-1; status=200
            range_header=self.headers.get('Range')
            if range_header and range_header.startswith('bytes='):
                part=range_header[6:].split('-'); start=int(part[0] or 0); end=min(int(part[1]) if part[1] else end,end); status=206
                if start>end:return self.respond({'error':'无效媒体范围'},416)
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
        except Exception as e:self.respond({'error':str(e)},400)
    def do_POST(self):
        try:
            if self.headers.get('Host','').split(':')[0] not in ('127.0.0.1','localhost'):return self.respond({'error':'仅允许本机访问'},403)
            # Browser same-origin and custom header prevent cross-site local writes.
            if self.headers.get('X-Auteur')!='studio':return self.respond({'error':'拒绝跨站写入'},403)
            origin=self.headers.get('Origin')
            if origin and origin!=f'http://{self.headers.get("Host")}':return self.respond({'error':'来源无效'},403)
            path=urlparse(self.path).path; length=int(self.headers.get('Content-Length','0'))
            if length>200*1024*1024:raise ValueError('单次上传限 200 MB')
            if path.startswith('/api/upload/'):
                ext=path.rsplit('/',1)[1]
                if ext not in ('mp4','mov','wav','mp3','m4a','png','jpg','jpeg','webp'):raise ValueError('不支持该媒体格式')
                name=uid()+'.'+ext; dest=MEDIA/name; dest.write_bytes(self.rfile.read(length))
                try:
                    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(dest)],timeout=30))
                    if not info.get('streams'):raise ValueError('媒体无有效轨道')
                except Exception:
                    dest.unlink(missing_ok=True); raise ValueError('媒体格式验证失败')
                return self.respond({'file':name,'streams':[s['codec_type'] for s in info['streams']]})
            if length>2*1024*1024:raise ValueError('请求过大')
            body=json.loads(self.rfile.read(length) or '{}')
            if path=='/api/preparation/initialize':return self.respond(initialize_preparation(body['project_id'],body['revision'],body.get('episode_id')))
            if path=='/api/preparation/open':return self.respond(open_preparation(body['project_id'],body['shot_id'],body.get('kind','video')))
            if path=='/api/preparation/save':return self.respond(save_preparation(body['project_id'],body['shot_id'],body['revision'],body['plan'],body['basis']))
            if path=='/api/continuity/preview':return self.respond(continuity_preview(body['project_id'],body['episode_id']))
            if path=='/api/continuity/confirm':return self.respond(confirm_continuity(body['project_id'],body['episode_id'],body['revision'],body['digest'],body['resolution'],body.get('reason','')))
            if path=='/api/import/drama/preview':return self.respond(preview_drama_import(body.get('bundle')))
            if path=='/api/import/drama/apply':return self.respond(apply_drama_import(body.get('id'),body.get('digest')))
            if path=='/api/projects':return self.respond(create(body['title'],body.get('script','')))
            if path=='/api/shots':return self.respond(add_shot(body['project_id'],body['episode_id'],body['revision'],body.get('fields',{})))
            if path=='/api/apply':return self.respond(apply_job(body['project_id'],body['job_id'],body['revision'],body.get('mode'),body.get('preview_digest')))
            if path=='/api/revision-preview':return self.respond(revision_preview(body['project_id'],body['job_id'],body['revision']))
            if path=='/api/apply-preview':return self.respond(adoption_preview(body['project_id'],body['job_id'],body['revision'],body.get('mode','append')))
            if path=='/api/save':return self.respond(save(body['project'],body['revision']))
            if path=='/api/production':return self.respond(edit_production(body))
            if path=='/api/settings/spending':return self.respond(set_spending(body.get('remaining')))
            if path=='/api/jobs':return self.respond({'id':enqueue(body['project_id'],body['kind'],body,body['nonce'])})
            if path=='/api/review':
                review_job(body['project_id'],body['job_id'],body['revision'],body['review_id'],body['action'],body.get('notes',''))
                return self.respond({'ok':True})
            if path=='/api/reconcile':
                reconcile_job(body['project_id'],body['job_id']);return self.respond({'ok':True})
            if path=='/api/settings/dify':return self.respond(configure_dify(body.get('base_url',''),body.get('api_key',''),body.get('kind','shots')))
            if path=='/api/settings/dify/check':return self.respond(Dify().inspect_connection(body.get('kind')))
            if path=='/api/cancel':
                with connect() as c:c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=? AND state IN ('queued','running','waiting_review')",(time.time(),body['id']))
                return self.respond({'ok':True})
            return self.respond({'error':'接口不存在'},404)
        except Exception as e:self.respond({'error':str(e)},400)

def load_env():
    p=ROOT/'.env'
    if p.exists():
        for line in p.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))

def main():
    parser=argparse.ArgumentParser(description='流幕本机工作室')
    commands=parser.add_subparsers(dest='command')
    commands.add_parser('check',help='检查本机运行依赖')
    commands.add_parser('backup',help='将作品和素材备份到新目录').add_argument('destination',type=Path)
    commands.add_parser('restore',help='从备份恢复到 AUTEUR_DATA 指定的新目录').add_argument('source',type=Path)
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

if __name__=='__main__':
    main()
