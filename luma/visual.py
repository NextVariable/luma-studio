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
# A version's `file` is its primary image; extra views live in `views`.
# Characters and scenes may each have several approved views of the same version.
VIEWS = {
    'character': ('primary', 'front', 'three_quarter', 'side', 'back'),
    'scene': ('primary', 'wide', 'detail', 'reverse'),
}
VIEW_LABELS = {'primary': '设定图', 'front': '正面', 'three_quarter': '四分之三',
               'side': '侧面', 'back': '背面', 'wide': '全景', 'detail': '细节', 'reverse': '反打'}


def view_of(version, file):
    """The view slot a file occupies in a version, or None when it is unrelated."""
    for view, other in (version.get('views') or {}).items():
        if other == file:
            return view
    return 'primary' if version.get('file') == file else None


def allowed_views(role):
    return VIEWS.get(role, ('primary',))


def approved_refs(references, role, asset_id=None, version_id=None, version=None):
    """Approved references in display order; legacy rows without `view` are derived from the version."""
    order = {view: index for index, view in enumerate(allowed_views(role))}
    items = []
    for ref in references:
        if ref.get('role') != role:
            continue
        if asset_id is not None and ref.get('asset_id') != asset_id:
            continue
        if version_id is not None and ref.get('version_id') != version_id:
            continue
        view = ref.get('view') or (view_of(version, ref.get('file')) if version else None)
        if view is None:
            view = 'primary'
        items.append((order.get(view, len(order)), view, ref))
    items.sort(key=lambda item: item[0])
    return [(view, ref) for _, view, ref in items]


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
    style_seen = False
    for ref in references:
        fields = {'role', 'asset_id', 'version_id', 'file', 'source'}
        if not isinstance(ref, dict) or not fields<=set(ref) or set(ref)-fields-{'sha256', 'view', 'label'} or any(
            not isinstance(value, str) or not value.strip() for value in ref.values()
        ) or len(ref['source']) > 500:
            raise ValueError('视觉参考需要用途、资产版本、文件及来源')
        asset = assets.get(ref['asset_id'], {})
        role = ref['role']
        version = next((v for v in asset.get('versions', []) if v['id'] == ref['version_id']), {})
        view = ref.get('view') or view_of(version, ref['file'])
        key = (role, ref['asset_id'], ref['version_id'], view)
        if (role not in ROLES or asset.get('kind') != role or view not in allowed_views(role)
                or key in seen or (role == 'style' and (style_seen or view != 'primary'))
                or ref['file'] not in [version.get('file'), *version.get('views', {}).values()]):
            raise ValueError('视觉参考必须属于指定资产版本；同一版本可按视图分别批准，作品只能指定一张风格图')
        path = media_path(ref['file'])
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp') or path.stat().st_size > 8*1024*1024:
            raise ValueError('视觉参考必须是 8 MB 以内的图片')
        if ref.get('sha256'):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:
                raise ValueError('已批准的参考图文件发生变化')
        seen.add(key)
        if role == 'style':
            style_seen = True
