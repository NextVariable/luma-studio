"""Verified capabilities ONLY for isolated protocol tests, never application configuration."""
import hashlib
from unittest.mock import patch
from luma import studio
from luma import preparation

# Smallest valid PNG header payload; approval and preview validate real image types.
PNG_1PX=(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
         b'\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
         b'\x00\x00\x00\x00IEND\xaeB`\x82')

def prepare(case,kind,mode=None):
    profile={'verified':True,'contract':'luma-prepared-media-v1','provider':'isolated-fixture','evidence':'unit-test-only',
             'kind':kind,'modes':list(preparation.MODES[kind]),'duration':{'min':1,'max':60,'step':1},
             'resolutions':['720p'],'aspect_ratios':['16:9','9:16'],'parameters':['aspect_ratio','resolution','fps','seed'],
             'fps':[24],'max_images':10,'role_limits':{'reference_image':10,'first_frame':1,'last_frame':1}}
    model='fixture-'+kind;patcher=patch.dict(preparation.MODELS,{model:profile});patcher.start();case.addCleanup(patcher.stop)
    case.p=studio.project(case.p['id']);s=next(s for s in case.p['shots'] if s['id']=='s1')
    for aid in list(preparation.character_versions(case.p,s)):
        a=next(a for a in case.p['assets'] if a['id']==aid);v=next(v for v in a['versions'] if v['id']==s['asset_bindings'][aid])
        if not v.get('outfit'):case.p=studio.edit_production({'project_id':case.p['id'],'revision':case.p['revision'],'action':'character_look','asset_id':aid,'outfit':'测试服装','voice_id':'alloy'})
        current=next(a for a in case.p['assets'] if a['id']==aid);v=next(v for v in current['versions'] if v['id']==current['selected_version'])
        if not v.get('file') and not v.get('views'):
            files=list(studio.MEDIA.glob('*.png'))
            if not files:
                studio.ffmpeg(['-f','lavfi','-i','color=c=blue:size=32x32','-frames:v','1',str(studio.MEDIA/'prep-fixture.png')]);files=[studio.MEDIA/'prep-fixture.png']
            case.p=studio.edit_production({'project_id':case.p['id'],'revision':case.p['revision'],'action':'asset_version','asset_id':aid,'file':files[0].name})
    if preparation.character_versions(case.p,s):case.p=studio.edit_production({'project_id':case.p['id'],'revision':case.p['revision'],'action':'bind_current','shot_id':'s1'})
    for a in list(case.p['assets']):
        if a['kind'] not in ('character','scene'):continue
        version=next((v for v in a['versions'] if v['id']==a['selected_version']),None)
        if not version or not version.get('file'):continue
        refs=(case.p['creative_brief'].get('visual_bible') or {}).get('references') or []
        if any(r.get('asset_id')==a['id'] and r.get('version_id')==version['id'] and (r.get('view') or 'primary')=='primary' for r in refs):continue
        media=studio.media_path(version['file'])
        with media.open('rb') as stream:data=stream.read()
        if not data.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff',b'RIFF')):
            media.write_bytes(PNG_1PX)
        sha=hashlib.sha256(media.read_bytes()).hexdigest()
        bible=case.p['creative_brief'].setdefault('visual_bible',{});refs=bible.setdefault('references',[])
        refs.append(dict(role=a['kind'],asset_id=a['id'],version_id=version['id'],file=version['file'],
                         view='primary',source='测试批准',sha256=sha))
        case.p=studio.save(case.p,case.p['revision'])
    s=next(s for s in case.p['shots'] if s['id']=='s1')
    opened=studio.open_preparation(case.p['id'],'s1',kind);plan=opened['plan'];seg=plan['segments'][0];choices=opened['references']
    mode=mode or ('image_to_video' if s.get('frame_mode')=='start_own' else 'reference_to_'+kind if choices else 'text_to_'+kind)
    seg.update(model=model,mode=mode);seg['parameters']['resolution']='720p'
    refs=[r for r in choices if r['source']=='shot_image'] if mode=='image_to_video' else choices if mode.startswith('reference_') else []
    seg['references']=[{'reference_id':r['reference_id'],'role':'first_frame' if mode=='image_to_video' else 'reference_image'} for r in refs]
    case.p=studio.save_preparation(case.p['id'],'s1',case.p['revision'],plan,opened['basis'])['project']
    return model
