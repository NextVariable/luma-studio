"""Local assembly of explicitly chosen segment candidates. No provider calls."""
import copy
import math
import hashlib
from . import preparation
from . import production


def source_plan(p,sid,media_path,probe):
    s=preparation.shot_of(p,sid);plan=s.get('preparation')
    if s.get('locked'):raise ValueError('请先解除镜头锁定')
    if not plan:raise ValueError('请先保存制作准备')
    preparation.validate(p,s,plan,media_path)
    issue=preparation.current_issue(p,s)
    if issue:raise ValueError(issue)
    sources=s.get('segment_sources',{});rows=[]
    for seg in plan['segments']:
        choice=sources.get(seg['id'],{});t=next((t for t in s['takes'] if t['id']==choice.get('take_id')),None)
        if not t:raise ValueError('片段尚未选择素材')
        if t['kind']!=seg['kind']:raise ValueError('片段素材类型与制作准备不一致')
        old=t.get('generation_segment')
        if old and (old.get('shot_id')!=sid or old.get('id')!=seg['id'] or abs(old.get('start',-1)-seg['start'])>.001 or abs(old.get('end',-1)-seg['end'])>.001):raise ValueError('生成素材不属于当前片段范围')
        if choice.get('basis')!=production.take_basis(s):raise ValueError('片段选用尚未按当前设定确认，请重新保存片段选用')
        start=choice.get('trim_start',0);duration=seg['end']-seg['start']
        if type(start) not in (int,float) or not math.isfinite(start) or start<0:raise ValueError('片段素材起点无效')
        info=probe(t['file']);streams=info.get('streams',[])
        if not any(x.get('codec_type')=='video' for x in streams):raise ValueError('片段素材没有有效画面')
        if t['kind']=='image' and start:raise ValueError('静态图片不需要裁剪起点')
        if t['kind']=='video':
            length=float(info.get('format',{}).get('duration',0))
            if not math.isfinite(length) or start+duration>length+.05:raise ValueError('片段视频长度不足，不能自动定格补齐')
        rows.append({'segment_id':seg['id'],'start':seg['start'],'end':seg['end'],'duration':duration,'take_id':t['id'],
                     'kind':t['kind'],'file':t['file'],'trim_start':start,'sha256':hashlib.sha256(media_path(t['file']).read_bytes()).hexdigest()})
    return {'shot_id':sid,'basis':production.take_basis(s),'plan_digest':production.digest(plan),'sources':copy.deepcopy(rows)}
