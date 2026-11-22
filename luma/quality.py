"""Evidence and human reviews scoped to one immutable media candidate."""
import hashlib
import json
import time

from . import continuity

STRUCTURE = {
    'cast': '人数与身份', 'wardrobe': '服装', 'gaze': '视线与站位',
    'framing': '景别与构图', 'continuity': '场景与镜头承接',
}
CRAFT = {'style': '画风', 'detail': '美术细节', 'expression': '表情与情绪', 'lighting': '光影'}
MOTION = {'motion': '动作自然度', 'stability': '视频稳定性'}


def candidates(db, project, shot):
    jobs = {row['id']: row for row in db.execute(
        'SELECT id, payload, result, created, updated FROM jobs WHERE project_id=?', (project['id'],))}
    reviews = {}
    for row in db.execute('SELECT take_id, body FROM candidate_reviews WHERE project_id=? AND shot_id=? ORDER BY rowid',
                          (project['id'], shot['id'])):
        reviews.setdefault(row['take_id'], []).append(json.loads(row['body']))
    rows = []
    basis = continuity.visual_basis(project,shot)
    for take in shot['takes']:
        kind = take['kind']
        if kind not in ('image', 'video'):
            continue
        job = jobs.get(take.get('job_id'))
        quote, receipt = {}, {}
        elapsed = None
        if job:
            quote = json.loads(job['payload']).get('quote', {})
            receipt = json.loads(job['result'] or '{}')
            elapsed = max(0, round(job['updated'] - job['created']))
        rows.append(dict(id=take['id'], file=take['file'], label=take['label'], kind=kind,
                         model=take.get('model') or quote.get('model'), provider=take['source'],
                         selected=shot.get('selected_takes', {}).get(kind)==take['id'],
                         estimated_cny=quote.get('estimated_cny'), estimated_usd=quote.get('estimated_usd'),
                         actual_cny=receipt.get('actual_cny'), billing_status=receipt.get('billing_status'),
                         request_id=receipt.get('provider_request_id') or receipt.get('run_id'),
                         queue_to_result_seconds=elapsed, reviews=[dict(r, matches_shot=r.get('shot_basis')==basis)
                         for r in reviews.get(take['id'], [])]))
    return rows


def inspect(take, media_path, probe):
    path = media_path(take['file'])
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    info = probe(take['file'])
    stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    return dict(sha256=sha, bytes=path.stat().st_size, width=stream.get('width'), height=stream.get('height'),
                duration=info.get('format', {}).get('duration') if take['kind']=='video' else None,
                video_track=bool(stream), audio_track=any(s.get('codec_type')=='audio' for s in info.get('streams', [])))


def record(db, project, shot, take, data, evidence, shot_basis):
    craft = dict(CRAFT, **(MOTION if take['kind']=='video' else {}))
    structure, scores, notes = data.get('structure'), data.get('scores'), data.get('notes')
    if (not isinstance(structure, dict) or set(structure)!=set(STRUCTURE)
            or any(v not in ('pass','fail','uncertain') for v in structure.values())):
        raise ValueError('请逐项确认结构检查')
    if (not isinstance(scores, dict) or set(scores)!=set(craft)
            or any(type(v) is not int or not 1<=v<=5 for v in scores.values())):
        raise ValueError('请逐项填写 1 至 5 分的美术评分')
    if not isinstance(notes,str) or not 1<=len(notes.strip())<=3000:
        raise ValueError('请填写复核依据，最多 3000 字')
    review = dict(structure=structure, scores=scores, notes=notes.strip(), evidence=evidence,
                  basis=data['basis'], shot_basis=shot_basis, project_revision=project['revision'], source='human', created=time.time())
    db.execute('INSERT INTO candidate_reviews(project_id,shot_id,take_id,body) VALUES(?,?,?,?)',
               (project['id'],shot['id'],take['id'],json.dumps(review,ensure_ascii=False)))
    return review
