"""Offline production preparation. Model capabilities are server-owned, never LLM claims."""
import copy
import math
import hashlib
import uuid
import creative
import continuity
import fal_media

# Only provider models with a documented input/output contract belong here.
MODELS = fal_media.PROFILES.copy()
MODES = {'image': ('text_to_image','reference_to_image'),
         'video': ('text_to_video','reference_to_video','image_to_video','start_end_frames')}
ROLES = ('reference_image','first_frame','last_frame')


def shot_of(p, sid):
    s=next((s for s in p['shots'] if s['id']==sid),None)
    if not s:raise ValueError('镜头不存在')
    return s


def basis(s):
    from production import semantic_shot
    return creative.digest(semantic_shot(s))


def character_versions(p,s):
    return {aid:vid for aid,vid in s['asset_bindings'].items() if any(a['id']==aid and a['kind']=='character' for a in p['assets'])}


def catalog(p,s):
    items=[]
    for aid,vid in s['asset_bindings'].items():
        a=next(a for a in p['assets'] if a['id']==aid)
        if a['kind']=='voice':continue
        v=next(v for v in a['versions'] if v['id']==vid)
        for view,file in {**({'primary':v['file']} if v.get('file') else {}),**v.get('views',{})}.items():
            items.append({'source':'asset','asset_id':aid,'version_id':vid,'view':view,'file':file,'label':a['name']+' · '+{'primary':'设定图','front':'正面','side':'侧面','back':'背面','three_quarter':'四分之三侧面'}.get(view,view)})
    # A video can replace the selected image without invalidating its pinned first frame.
    from production import content_basis
    frames = {}
    if s.get('image'):
        frames[s['image']] = '本镜已选图'
    current = content_basis(s)
    for take in s.get('takes', []):
        if take['kind'] == 'image' and take.get('shot_basis') == current:
            frames.setdefault(take['file'], take['label'])
    for file, label in frames.items():
        items.append({'source':'shot_image','shot_id':s['id'],'file':file,'label':label})
    previous = next((x for x in p['shots'] if x['id'] == s.get('continuity_from')), None)
    if previous and previous.get('image'):
        items.append({'source':'continuity','shot_id':previous['id'],'file':previous['image'],'label':'承接镜头已选图'})
    for item in items:item['reference_id']=creative.digest({k:v for k,v in item.items() if k!='label'})[:24]
    return items


def seed(p,sid,kind='video'):
    if kind not in MODES:raise ValueError('制作类型无效')
    s=shot_of(p,sid)
    return {'schema_version':1,'shot_id':sid,'basis':basis(s),'character_versions':character_versions(p,s),'dependency_basis':continuity.basis(p,s),
            'segments':[{'id':uuid.uuid4().hex,'start':0,'end':s['duration'],'kind':kind,'model':None,'mode':None,
                         'instruction':s['description'],'start_state':s.get('creative_spec',{}).get('continuityIn') or '',
                         'end_state':s.get('creative_spec',{}).get('continuityOut') or '',
                         'parameters':{'aspect_ratio':p['creative_brief']['format'],'resolution':None},'references':[]}]}


def validate(p,s,plan,media_path):
    """Structural validity permits incomplete plans, but never stale/fabricated references."""
    if not isinstance(plan,dict) or plan.get('schema_version')!=1 or plan.get('shot_id')!=s['id']:
        raise ValueError('制作准备的版本或所属镜头无效')
    if not isinstance(plan.get('basis'),str) or not isinstance(plan.get('character_versions'),dict):raise ValueError('制作准备缺少来源依据或角色版本')
    segments=plan.get('segments')
    if not isinstance(segments,list) or not 1<=len(segments)<=50:raise ValueError('每镜须有1–50个生成片段')
    ids=[];cursor=0;available={r['reference_id']:r for r in catalog(p,s)}
    for seg in segments:
        if not isinstance(seg,dict) or not isinstance(seg.get('id'),str) or not seg['id']:raise ValueError('生成片段缺少编号')
        ids.append(seg['id'])
        a,b=seg.get('start'),seg.get('end')
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in (a,b)) or a<0 or b<=a or abs(a-cursor)>.001:
            raise ValueError('生成片段须按时间顺序连续排列，不能重叠或留空')
        cursor=b
        if seg.get('kind') not in MODES or seg.get('mode') not in (None,*MODES[seg['kind']]):raise ValueError('生成方式与媒体类型不符')
        if seg.get('model') is not None and (not isinstance(seg['model'],str) or len(seg['model'])>200):raise ValueError('模型标识无效')
        for key in ('instruction','start_state','end_state'):
            if not isinstance(seg.get(key),str) or len(seg[key])>10000:raise ValueError('片段动作与起止状态须为文字')
        params=seg.get('parameters')
        if not isinstance(params,dict) or set(params)-{'aspect_ratio','resolution','fps','seed'}:raise ValueError('生成参数包含未支持的字段')
        if params.get('aspect_ratio')!=p['creative_brief']['format']:raise ValueError('生成画幅必须与作品一致')
        if params.get('resolution') is not None and not isinstance(params['resolution'],str):raise ValueError('分辨率须为文字')
        if 'fps' in params and (type(params['fps']) not in (int,float) or not math.isfinite(params['fps']) or params['fps']<=0):raise ValueError('帧率无效')
        if 'seed' in params and (type(params['seed']) is not int or params['seed']<0):raise ValueError('随机种子无效')
        refs=seg.get('references')
        if not isinstance(refs,list) or len(refs)>20:raise ValueError('参考图选择无效')
        keys=[];files=[]
        for ref in refs:
            if not isinstance(ref,dict) or set(ref)!={'reference_id','role'} or ref.get('reference_id') not in available or ref.get('role') not in ROLES:
                raise ValueError('参考图不存在、版本已改变或用途无效，请重新选择')
            keys.append((ref['reference_id'],ref['role']));file=available[ref['reference_id']]['file']
            files.append((file,ref['role']))
            if file.rsplit('.',1)[-1].lower() not in ('png','jpg','jpeg','webp'):raise ValueError('画面参考必须是图片，不能使用声音或视频文件')
            media_path(file)
        if len(keys)!=len(set(keys)):raise ValueError('同一用途的参考图不能重复选择')
        if len(files)!=len(set(files)):raise ValueError('同一图片不能以不同名称重复充当同一用途的参考')
    if len(ids)!=len(set(ids)):raise ValueError('生成片段编号重复')
    if abs(cursor-s['duration'])>.001:raise ValueError('片段总时长必须等于叙事镜头时长；不能反向改写镜头')


def current_issue(p,s):
    plan=s.get('preparation')
    if plan and (plan.get('basis')!=basis(s) or plan.get('character_versions')!=character_versions(p,s)):
        return '制作准备已过期，请按返工后的镜头重新确认'
    if plan and plan.get('dependency_basis')!=continuity.basis(p,s):
        return '承接镜头或跨集输入已变化，请重新确认制作准备'
    if plan and creative.continuity_status(p,s['episode_id'])['requires_confirmation']:
        return '跨集状态待确认，请先处理剧集承接'
    if plan and continuity.visual_issue(p,s):return continuity.visual_issue(p,s)
    return None


def report(p,sid,media_path,connected=None,profiles=None):
    s=shot_of(p,sid);plan=s.get('preparation');errors=[];rows=[]
    def error(message,segment_id=None):errors.append({'segment_id':segment_id,'message':message})
    if not plan:return {'ready':False,'issues':[{'segment_id':None,'message':'尚未保存制作准备'}],'segments':[]}
    try:validate(p,s,plan,media_path)
    except ValueError as e:error(str(e));return {'ready':False,'issues':errors,'segments':[]}
    issue=current_issue(p,s)
    if issue:error(issue)
    if plan['basis']!=basis(s):error('镜头设定或造型引用已变化，请重新确认制作准备')
    if plan['character_versions']!=character_versions(p,s):error('制作准备中的角色造型与本镜绑定不一致')
    for aid,vid in character_versions(p,s).items():
        a=next(a for a in p['assets'] if a['id']==aid);v=next(v for v in a['versions'] if v['id']==vid)
        if not v.get('outfit'):error('角色尚未明确造型：'+a['name'])
    state=creative.continuity_status(p,s['episode_id'])
    if state['requires_confirmation']:error(state['reason'])
    if s.get('locked'):error('镜头已锁定')
    available={r['reference_id']:r for r in catalog(p,s)};profiles=MODELS if profiles is None else profiles
    previous=None
    for seg in plan['segments']:
        sid2=seg['id'];duration=seg['end']-seg['start'];refs=[{**available[r['reference_id']],'role':r['role']} for r in seg['references']]
        counts={role:sum(r['role']==role for r in refs) for role in ROLES};mode=seg['mode'];profile=profiles.get(seg['model'])
        if len(refs)>10:error('当前工作流最多接收10个参考文件，不能静默截断',sid2)
        if not seg['instruction'].strip():error('请明确这一片段的动作要求',sid2)
        if len(plan['segments'])>1:
            if not seg['start_state'].strip() or not seg['end_state'].strip():error('分段制作须明确每段起止状态',sid2)
            if previous and previous['end_state']!=seg['start_state']:error('相邻片段的末态与起始状态尚未对齐',sid2)
        previous=seg
        if not mode:error('请选择生成方式',sid2)
        elif mode in ('text_to_image','text_to_video') and refs:error('纯文字生成方式不能携带参考图',sid2)
        elif mode in ('reference_to_image','reference_to_video') and (not refs or counts['first_frame'] or counts['last_frame']):error('参考图方式须选择普通参考，不能混入首尾帧',sid2)
        elif mode=='image_to_video' and (counts['first_frame']!=1 or len(refs)!=1):error('图生视频须明确选择一张首帧',sid2)
        elif mode=='start_end_frames' and (counts['first_frame']!=1 or counts['last_frame']!=1 or len(refs)!=2):error('首尾帧方式须各选一张首帧和尾帧',sid2)
        # Character consistency cannot be claimed from text-only identity bindings.
        for aid in plan['character_versions']:
            if not any(r.get('asset_id')==aid for r in refs) and not any(r['role']=='first_frame' for r in refs):error('角色尚未选择用于生成的参考图：'+next(a['name'] for a in p['assets'] if a['id']==aid),sid2)
        if not profile or profile.get('verified') is not True or profile.get('contract')!='luma-prepared-media-v1':
            error('模型支持的生成方式和参数尚未核实，暂不能生成',sid2)
        else:
            params=seg['parameters']
            if seg['kind']!=profile.get('kind') or mode not in profile.get('modes',[]):error('模型不支持所选生成方式',sid2)
            if not profile.get('provider') or not profile.get('evidence'):error('模型能力缺少核实来源',sid2)
            if profile.get('provider') == 'fal' and any(r['source'] == 'shot_image' and r['file'] == s.get('image') for r in refs):
                from production import media_issue
                if media_issue(s):error('本镜首帧来自修改前，请生成新图或确认沿用',sid2)
            limits=profile.get('duration',{})
            if seg['kind']=='video' and (not limits or not limits.get('min',0)<=duration<=limits.get('max',0)):error('片段时长超出模型范围',sid2)
            step=limits.get('step')
            if seg['kind']=='video' and step and abs((duration-limits.get('min',0))/step-round((duration-limits.get('min',0))/step))>.001:error('片段时长不符合模型步长',sid2)
            if params.get('resolution') not in profile.get('resolutions',[]):error('分辨率未获模型支持或尚未填写',sid2)
            if params.get('aspect_ratio') not in profile.get('aspect_ratios',[]):error('模型不支持作品画幅',sid2)
            if set(params)-set(profile.get('parameters',[])):error('模型不支持部分生成参数',sid2)
            if 'fps' in params and params['fps'] not in profile.get('fps',[]):error('模型不支持所选帧率',sid2)
            if len(refs)>profile.get('max_images',0):error('参考图数量超过模型上限',sid2)
            if any(counts[role]>profile.get('role_limits',{}).get(role,0) for role in ROLES):error('参考图用途或数量超出模型能力',sid2)
            if profile.get('parameter_sets') and not any(all(params.get(k)==v for k,v in combo.items()) for combo in profile['parameter_sets']):error('分辨率、画幅与帧率组合不受支持',sid2)
        if connected is not None:
            service_ready = bool(fal_media.key()) if profile and profile.get('provider') == 'fal' else connected(seg['kind'])
            if not service_ready:error('对应生成服务尚未连接',sid2)
        rows.append({'id':sid2,'start':seg['start'],'end':seg['end'],'duration':duration,'kind':seg['kind'],'model':seg['model'],'mode':mode,'parameters':copy.deepcopy(seg['parameters']),'references':refs})
    return {'ready':not errors,'issues':errors,'segments':rows,'plan_digest':creative.digest(plan),'operation_count':len(rows)}


def freeze(p,sid,kind,segment_id,media_path,connected):
    result=report(p,sid,media_path,connected)
    if not result['ready']:raise ValueError('制作准备未就绪：'+'；'.join(dict.fromkeys(i['message'] for i in result['issues'])))
    s=shot_of(p,sid);segments=s['preparation']['segments']
    if not segment_id and len(segments)!=1:raise ValueError('请指定本次生成片段，不能将多片段当作整镜提交')
    seg=next((x for x in segments if x['id']==(segment_id or segments[0]['id'])),None)
    if not seg or seg['kind']!=kind:raise ValueError('生成片段不存在或类型不一致')
    profile=MODELS[seg['model']];row=next(x for x in result['segments'] if x['id']==seg['id'])
    return {**copy.deepcopy(row),'shot_id':sid,'plan_digest':result['plan_digest'],'model_profile_digest':creative.digest(profile),
            'provider':profile['provider'],'contract':profile['contract'],'instruction':seg['instruction'],
            'start_state':seg['start_state'],'end_state':seg['end_state'],'character_versions':copy.deepcopy(s['preparation']['character_versions'])}
