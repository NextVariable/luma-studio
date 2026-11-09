"""Read a short-drama project as data. Never executes source scripts or calls models."""
import copy
import json
from pathlib import Path
import production
import creative

FORMAT = 'luma-short-drama-v1'


def read_bundle(directory):
    root = Path(directory).resolve()
    files = {}
    paths = [root / n for n in ('project.json', 'characters.json', 'assets.json', 'outfits.json', 'episode-state.json', 'visual-bible.md')]
    paths += sorted((root / 'scripts').glob('*.script.json')) + sorted((root / 'storyboards').glob('*.storyboard.json'))
    for path in paths:
        if path.exists():
            if not path.resolve().is_relative_to(root): raise ValueError('来源文件不能越出项目目录')
            raw = path.read_bytes()
            if len(raw) > 2_000_000: raise ValueError('来源文件过大')
            text = raw.decode('utf-8')
            files[path.relative_to(root).as_posix()] = text if path.suffix == '.md' else json.loads(text)
    return {'format': FORMAT, 'files': files}


def convert(bundle):
    if not isinstance(bundle, dict) or bundle.get('format') != FORMAT or not isinstance(bundle.get('files'), dict):
        raise ValueError('请选择流幕短剧导入包')
    if len(json.dumps(bundle, ensure_ascii=False, allow_nan=False)) > 1_800_000: raise ValueError('导入包过大')
    files = copy.deepcopy(bundle['files'])
    for key in ('project.json', 'characters.json', 'assets.json', 'outfits.json', 'episode-state.json'):
        if not isinstance(files.get(key), dict): raise ValueError('缺少来源文件：' + key)
    bible = files['project.json']; chars = files['characters.json']['characters']; other = files['assets.json']['assets']
    outfits = files['outfits.json']; state = files['episode-state.json']['episodes']
    digest = production.digest(bundle)
    pid = 'drama-' + digest[:24]
    p = {'id': pid, 'title': bible['title'], 'script': '', 'revision': 0, 'mode': 'director', 'assets': [], 'shots': [], 'episodes': [],
         'creative_brief': {'format': '9:16' if bible.get('format') == 'vertical' else '16:9', 'method': 'video', 'style': bible.get('visualStyle', '')},
         'creative_context': {'schema_version': 1, 'project_bible': bible, 'visual_bible': files.get('visual-bible.md', ''),
                              'source_digest': digest, 'source_type': 'short-drama', 'rule_version': creative.RULE_VERSION}}
    ids = [c['id'] for c in chars] + [a['assetId'] for a in other]
    if len(ids) != len(set(ids)): raise ValueError('来源资产编号重复')
    outfit_ids = [o['outfitId'] for o in outfits['outfits']]
    if len(outfit_ids) != len(set(outfit_ids)): raise ValueError('来源造型编号重复')
    if any(o['characterId'] not in {c['id'] for c in chars} for o in outfits['outfits']): raise ValueError('造型引用了不存在的角色')
    for c in chars:
        versions = []
        for o in outfits['outfits']:
            if o['characterId'] == c['id']:
                versions.append({'id': o['outfitId'], 'name': c['name'], 'description': c.get('appearance', ''), 'outfit': o['name'],
                                 'creative_spec': {'character': c, 'outfit': o}, 'file': None, 'created': 0})
        if not versions: raise ValueError('角色缺少明确造型：' + c['id'])
        options = [v for v in versions if v['creative_spec']['outfit']['context'] in (outfits.get('defaultContext', 'any'), 'any')]
        if len(options) != 1: raise ValueError('角色造型缺失或有歧义：' + c['id'])
        p['assets'].append({'id': c['id'], 'name': c['name'], 'description': c.get('appearance', ''), 'kind': 'character',
                            'versions': versions, 'selected_version': options[0]['id'], 'version': len(versions)})
    kinds = {'location': 'scene', 'prop': 'prop', 'style': 'style', 'voice': 'voice'}
    for a in other:
        if a['type'] not in kinds: raise ValueError('未支持的来源资产类型：' + a['type'])
        desc = a.get('function') or a.get('description') or a['name']
        vid = a['assetId'] + '-source-v1'
        p['assets'].append({'id': a['assetId'], 'name': a['name'], 'description': desc, 'kind': kinds[a['type']], 'version': 1, 'selected_version': vid,
                            'versions': [{'id': vid, 'name': a['name'], 'description': desc, 'creative_spec': a, 'file': None, 'created': 0}]})
    assets = {a['id']: a for a in p['assets']}; warnings = []; seen = set(); ep_seen = set(); segments_seen=set()
    used_files={'project.json','characters.json','assets.json','outfits.json','episode-state.json','visual-bible.md'}
    for name, sb in sorted(files.items()):
        if not name.startswith('storyboards/') or not name.endswith('.storyboard.json'): continue
        number = sb['ep']; eid = 'EP' + str(number).zfill(3)
        if eid in ep_seen: raise ValueError('来源剧集编号重复')
        ep_seen.add(eid)
        script = files.get('scripts/' + eid + '.script.json')
        if not script or script.get('ep') != number: raise ValueError('缺少对应剧本：' + eid)
        used_files.update((name,'scripts/'+eid+'.script.json'))
        scenes = {s['id']: s for s in script['scenes']}
        if len(scenes) != len(script['scenes']): raise ValueError('来源场景编号重复')
        ep_state = [s for s in state if s['ep'] == number]
        if len(ep_state) != 1: raise ValueError('缺少唯一分集状态：' + eid)
        entry = next((s for s in state if s['ep'] == number - 1), None)
        text = '\n\n'.join(s['id'] + ' · ' + s.get('time', '') + '\n' + '\n'.join((assets.get(b.get('who'), {}).get('name', '') + '：' if b.get('who') else '') + b['text'] for b in s['beats']) for s in script['scenes'])
        ep = {'id': eid, 'title': script.get('title') or '第 ' + str(number) + ' 集', 'script': text,
              'creative_spec': {'schema_version': 1, 'screenplay': script, 'entry_state': entry, 'planned_end_state': ep_state[0],
                                'source_storyboard': name, 'segments': [{k: v for k, v in g.items() if k != 'shots'} for g in sb['segments']]}}
        p['episodes'].append(ep)
        for segment in sb['segments']:
            if segment['segmentId'] in segments_seen: raise ValueError('来源分段编号重复')
            segments_seen.add(segment['segmentId'])
            for original in segment['shots']:
                spec = copy.deepcopy(original); sid = spec['shotId']
                if sid in seen: raise ValueError('来源镜头编号重复：' + sid)
                seen.add(sid)
                if spec['episodeId'] != number or spec['sceneId'] != segment['sceneId'] or spec['sceneId'] not in scenes:
                    raise ValueError('镜头的剧集或场景引用不一致：' + sid)
                if scenes[spec['sceneId']].get('location') != spec['locationId']:
                    warnings.append({'shot_id': sid, 'severity': 'warning', 'rule': 'source-location-conflict', 'message': '剧本场景地点与分镜不同；保留双方原文，需人工复核'})
                refs = [spec['visualSubject'], spec['locationId'], *spec.get('propIds', [])]
                line = spec.get('dialogue')
                if line:
                    if line.get('who') not in assets or assets[line['who']]['kind'] != 'character': raise ValueError('对白说话人未登记：' + sid)
                    refs.append(line['who'])
                refs = list(dict.fromkeys(refs))
                if any(aid not in assets for aid in refs): raise ValueError('来源镜头引用不存在的资产：' + sid)
                spec.update(schema_version=1, segmentId=segment['segmentId'])
                shot = {'id': sid, 'episode_id': eid, 'description': spec['action'], 'duration': spec['durationSec'], 'framing': spec['shotSize'],
                        'camera': spec.get('cameraMovement', ''), 'asset_ids': refs, 'asset_bindings': {aid: assets[aid]['selected_version'] for aid in refs},
                        'creative_spec': spec, 'approved': False, 'needs_review': True, 'locked': False, 'dialogue': ''}
                if line: shot['lines'] = [{'id': sid + '-line-1', 'speaker_asset_id': line['who'], 'text': line['text']}]
                p['shots'].append(shot)
    if not p['episodes'] or not p['shots']: raise ValueError('导入包没有可制作的分镜')
    p['script'] = p['episodes'][0]['script']
    production.normalize(p); creative.validate(p)
    warnings += [i for i in creative.issues(p) if i['severity'] != 'error']
    for shot in p['shots']:
        shot['source_warnings']=[copy.deepcopy(i) for i in warnings if i['shot_id']==shot['id']]
    missing_refs = [a['id'] for a in p['assets'] if not any(v.get('file') or v.get('views') for v in a['versions'])]
    return {'digest': digest, 'project': p, 'warnings': warnings, 'summary': {'title': p['title'], 'episodes': len(p['episodes']), 'shots': len(p['shots']),
             'assets': len(p['assets']), 'seconds': sum(s['duration'] for s in p['shots']), 'missing_reference_assets': missing_refs,
             'source': 'short-drama', 'media_generated': False, 'source_files': sorted(files), 'unmapped_files': sorted(set(files)-used_files)}}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('directory'); parser.add_argument('--bundle-out')
    args = parser.parse_args(); bundle = read_bundle(args.directory); preview = convert(bundle)
    if args.bundle_out: Path(args.bundle_out).write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in preview.items() if k != 'project'}, ensure_ascii=False, indent=2))
