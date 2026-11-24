"""Frozen, comparable video requests for one reviewed still."""
import hashlib
import json

from . import continuity, domestic_media, production, quality

RESOLUTIONS = {domestic_media.WAN: '720P', domestic_media.HAILUO: '768P'}


def packet(db, project, shot, choices, media_path):
    model = choices.get('model')
    seconds = choices.get('seconds', 6)
    if model not in RESOLUTIONS or type(seconds) is not int or seconds not in (6, 10):
        raise ValueError('双模型对照支持 6 或 10 秒')
    instruction = choices.get('instruction')
    if not isinstance(instruction,str) or not 1<=len(instruction.strip())<=2000:
        raise ValueError('请填写两家共同使用的动作，最多 2000 字')
    take_id = shot.get('selected_takes', {}).get('image')
    take = next((t for t in shot['takes'] if t['id']==take_id and t['kind']=='image'), None)
    if not take or production.media_issue(shot):
        raise ValueError('请先选用与当前镜头设定一致的分镜图')
    review_row = db.execute('''SELECT body FROM candidate_reviews
        WHERE project_id=? AND shot_id=? AND take_id=? ORDER BY rowid DESC LIMIT 1''',
        (project['id'],shot['id'],take_id)).fetchone()
    review = json.loads(review_row['body']) if review_row else {}
    with media_path(take['file']).open('rb') as stream:
        sha = hashlib.file_digest(stream,'sha256').hexdigest()
    if (review.get('shot_basis')!=continuity.visual_basis(project,shot)
            or review.get('evidence',{}).get('sha256')!=sha
            or not all(review.get('structure',{}).get(key)=='pass' for key in quality.STRUCTURE)
            or not all(review.get('scores',{}).get(key,0)>=3 for key in quality.CRAFT)):
        raise ValueError('首帧需通过当前镜头的人工复核：结构项通过，美术项均至少 3 分')
    aspect = project['creative_brief']['format']
    cohort = production.digest([shot['id'], take_id, sha, instruction.strip(), seconds, aspect])
    result = dict(id='compare-'+cohort[:20]+'-'+domestic_media.PROVIDER[model], comparison_id=cohort,
                  shot_id=shot['id'], start=0, end=seconds, duration=seconds, model=model,
                  provider=domestic_media.PROVIDER[model], mode='image_to_video', kind='video',
                  instruction=instruction.strip(), parameters={'resolution':RESOLUTIONS[model],'aspect_ratio':aspect},
                  references=[dict(role='first_frame',file=take['file'],reference_id=sha,label='已复核分镜首帧')])
    result['plan_digest']=production.digest(result)
    return result
