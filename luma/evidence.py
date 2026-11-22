"""Read-only production ledger separating local imports, provider records and human reviews."""
import json
import time
from decimal import Decimal, InvalidOperation

from . import continuity

DISCLAIMER = ('“供应商记录”只表示任务保存了请求号或运行号，不代表费用已核对，实际扣费以供应商控制台为准。'
              '离线模拟运行也会保存同类记录，不能作为真实 API 验收证据。')


def classify(take, receipt):
    """Local imports are certain; provider records are only as good as their request id."""
    if take.get('source') in ('import', 'local', 'local-assembly', 'assembly', 'blocking'):
        return 'local'
    if receipt.get('provider_request_id') or receipt.get('run_id'):
        return 'provider'
    return 'provider_unrecorded'


def _money(value):
    if value in (None, ''):
        return None
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def build(db, project):
    jobs = {row['id']: row for row in db.execute(
        'SELECT id, kind, state, payload, result, created, updated FROM jobs WHERE project_id=?',
        (project['id'],))}
    reviews = {}
    for row in db.execute('SELECT take_id, body FROM candidate_reviews WHERE project_id=? ORDER BY rowid',
                          (project['id'],)):
        reviews.setdefault(row['take_id'], []).append(json.loads(row['body']))
    summary = dict(episodes=len(project.get('episodes') or []), shots=0, shots_with_visual=0,
                   shots_reviewed=0, images=0, videos=0, local=0, provider=0,
                   provider_unrecorded=0, reviewed_takes=0, actual_cny='0.00')
    receipts = {jid: json.loads(job['result'] or '{}') for jid, job in jobs.items()
                if json.loads(job['payload'] or '{}').get('provider')}
    amounts = [_money(receipt.get('actual_cny')) for receipt in receipts.values()]
    actual = sum((amount for amount in amounts if amount is not None), Decimal('0'))
    items = []
    for episode in project.get('episodes') or []:
        shots = [x for x in project.get('shots') or [] if x.get('episode_id') == episode['id']]
        for number, shot in enumerate(shots, 1):
            summary['shots'] += 1
            if shot.get('image') or shot.get('video'):
                summary['shots_with_visual'] += 1
            shot_reviewed = False
            for take in shot.get('takes') or []:
                if take.get('kind') not in ('image', 'video'):
                    continue
                summary[take['kind'] + 's'] = summary.get(take['kind'] + 's', 0) + 1
                job = jobs.get(take.get('job_id'))
                payload = json.loads(job['payload'] or '{}') if job else {}
                receipt = json.loads(job['result'] or '{}') if job else {}
                quote = payload.get('quote') or {}
                source = classify(take, receipt)
                summary[source] = summary.get(source, 0) + 1
                history = reviews.get(take['id']) or []
                latest = history[-1] if history else None
                if latest:
                    shot_reviewed = True
                    summary['reviewed_takes'] += 1
                items.append(dict(
                    episode_id=episode['id'], episode_title=episode.get('title'), shot_id=shot['id'],
                    shot_number=number, shot_title=(shot.get('description') or '')[:80],
                    take_id=take['id'], kind=take['kind'], file=take['file'],
                    selected=shot.get('selected_takes', {}).get(take['kind']) == take['id'],
                    label=take.get('label'), evidence_class=source,
                    provider=payload.get('provider'), model=take.get('model') or quote.get('model'),
                    request_id=receipt.get('provider_request_id') or receipt.get('run_id'),
                    job_state=job['state'] if job else None,
                    estimated_cny=quote.get('estimated_cny'), actual_cny=receipt.get('actual_cny'),
                    billing_status=receipt.get('billing_status'),
                    reviewed=bool(latest), review_count=len(history),
                    review_scores=(latest or {}).get('scores'),
                    review_created=(latest or {}).get('created'),
                    review_matches_shot=bool(latest) and latest.get('shot_basis') == continuity.visual_basis(project, shot)))
            if shot_reviewed:
                summary['shots_reviewed'] += 1
    summary['actual_cny'] = format(actual, '.2f')
    approved = {}
    for reference in (project.get('creative_brief', {}).get('visual_bible') or {}).get('references') or []:
        approved.setdefault(reference.get('asset_id'), []).append(reference)
    assets = []
    for asset in project.get('assets') or []:
        bindings = [(s.get('asset_bindings') or {}).get(asset['id']) for s in project.get('shots') or []]
        assets.append(dict(id=asset['id'], name=asset['name'], kind=asset['kind'],
                           versions=len(asset.get('versions') or []),
                           selected_version=asset.get('selected_version'),
                           approved_references=len(approved.get(asset['id'], [])),
                           bound_shots=sum(1 for value in bindings if value)))
    return dict(project_id=project['id'], title=project.get('title'), generated_at=time.time(),
                disclaimer=DISCLAIMER, summary=summary, assets=assets, items=items)
