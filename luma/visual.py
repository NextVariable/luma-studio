"""Work-level art direction and explicitly approved, versioned image references."""

import hashlib

DIRECTION = {
    'palette': '色彩与光线',
    'wardrobe': '服装连续性',
    'camera': '摄影与景别',
    'quality': '美术质量要求',
    'continuity': '跨镜头一致性',
    'landmarks': '场景地标与主光',
}
ROLES = ('character', 'scene', 'style')


def validate_bible(brief, assets, media_path):
    bible = brief.get('visual_bible', {})
    if not isinstance(bible, dict) or set(bible) - {*DIRECTION, 'references'}:
        raise ValueError('视觉设定格式无效')
    for key in DIRECTION:
        value = bible.get(key, '')
        if not isinstance(value, str) or len(value) > 1000:
            raise ValueError(f'{DIRECTION[key]}最多 1000 字')
    references = bible.get('references', [])
    if not isinstance(references, list) or len(references) > 200:
        raise ValueError('视觉参考最多 200 项')
    seen = set()
    for ref in references:
        fields = {'role', 'asset_id', 'version_id', 'file', 'source'}
        if not isinstance(ref, dict) or not fields<=set(ref) or set(ref)-fields-{'sha256'} or any(
            not isinstance(value, str) or not value.strip() for value in ref.values()
        ) or len(ref['source']) > 500:
            raise ValueError('视觉参考需要用途、资产版本、文件及来源')
        asset = assets.get(ref['asset_id'], {})
        role = ref['role']
        version = next((v for v in asset.get('versions', []) if v['id'] == ref['version_id']), {})
        key = (role, ref['asset_id'], ref['version_id'])
        if (role not in ROLES or asset.get('kind') != role or key in seen
                or (role == 'style' and any(item[0] == 'style' for item in seen))
                or ref['file'] not in [version.get('file'), *version.get('views', {}).values()]):
            raise ValueError('视觉参考必须属于指定资产版本，每个版本只能批准一张参考图，作品只能指定一张风格图')
        path = media_path(ref['file'])
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp') or path.stat().st_size > 8*1024*1024:
            raise ValueError('视觉参考必须是 8 MB 以内的图片')
        if ref.get('sha256'):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:
                raise ValueError('已批准的参考图文件发生变化')
        seen.add(key)
