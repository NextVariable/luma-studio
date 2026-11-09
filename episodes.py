"""Episode boundaries for shared project assets and isolated production inputs."""
import copy


def normalize_project(p):
    # Legacy projects remain readable without rewriting their stored revision.
    if 'episodes' not in p:
        p['episodes'] = [{'id': p['id'] + '-episode-1', 'title': '第 1 集', 'script': p['script']}]
    if isinstance(p['episodes'], list) and len(p['episodes']) == 1:
        for shot in p['shots']:
            shot.setdefault('episode_id', p['episodes'][0]['id'])
    return p


def validate_episodes(p):
    episodes = p.get('episodes')
    if not isinstance(episodes, list) or not 1 <= len(episodes) <= 100:
        raise ValueError('作品须包含 1–100 个剧集')
    for ep in episodes:
        if (not isinstance(ep, dict) or not isinstance(ep.get('id'), str) or not ep['id']
                or not isinstance(ep.get('title'), str) or not 1 <= len(ep['title'].strip()) <= 100
                or not isinstance(ep.get('script'), str) or len(ep['script']) > 100000):
            raise ValueError('剧集 ID、名称或剧本无效')
    ids = [e['id'] for e in episodes]
    if len(ids) != len(set(ids)):
        raise ValueError('剧集 ID 重复')
    if any(s.get('episode_id') not in ids for s in p['shots']):
        raise ValueError('镜头引用了不存在的剧集')


def changed_episodes(old, new):
    result = set()
    for ep in new['episodes']:
        prev = next((e for e in old['episodes'] if e['id'] == ep['id']), None)
        before = [s['id'] for s in old['shots'] if s['episode_id'] == ep['id']]
        after = [s['id'] for s in new['shots'] if s['episode_id'] == ep['id']]
        if prev is None or ep['script'] != prev['script'] or ep.get('creative_spec') != prev.get('creative_spec') or before != after:
            result.add(ep['id'])
    return result


def production_snapshot(p, episode_id=None):
    p = copy.deepcopy(normalize_project(p))
    # A multi-episode project must never silently export or generate the wrong episode.
    if episode_id is None and len(p['episodes']) > 1:
        raise ValueError('请先选择要制作的剧集')
    episode_id = episode_id or p['episodes'][0]['id']
    ep = next((e for e in p['episodes'] if e['id'] == episode_id), None)
    if ep is None:
        raise ValueError('剧集不存在')
    p.update(episode_id=ep['id'], episode_title=ep['title'], script=ep['script'])
    import continuity
    p['continuity_dependencies']={s['id']:continuity.basis(p,s) for s in p['shots'] if s['episode_id']==episode_id}
    p['shots'] = [s for s in p['shots'] if s['episode_id'] == episode_id]
    return p
