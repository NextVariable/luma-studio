"""Work-level art direction and explicitly approved, versioned image references."""

import hashlib

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

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
STATUS_LABELS = {'approved': '已批准', 'legacy': '旧版批准', 'unapproved': '未批准'}


def image_mime(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise ValueError('参考图须为 PNG、JPEG 或 WebP 图片')


def read_image(path):
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError('参考图须为 PNG、JPEG 或 WebP 图片')
    with path.open('rb') as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError('参考图须不超过 8 MB')
    return data


def file_at_view(version, view):
    return version.get('file') if view == 'primary' else (version.get('views') or {}).get(view)


def view_of(version, file):
    """The view slot a file occupies in a version, or None when it is unrelated."""
    if file and version.get('file') == file:
        return 'primary'
    for view, other in (version.get('views') or {}).items():
        if other == file:
            return view
    return None


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
        if view is None and version is None:
            view = 'primary'
        if view not in order or (version is not None and file_at_view(version, view) != ref.get('file')):
            continue
        items.append((order.get(view, len(order)), view, ref))
    items.sort(key=lambda item: item[0])
    return [(view, ref) for _, view, ref in items]


def style_reference(references, assets):
    for _, ref in approved_refs(references, 'style'):
        asset = next((a for a in assets if a['id'] == ref.get('asset_id') and a['kind'] == 'style'), None)
        if asset:
            version = next((v for v in asset['versions'] if v['id'] == ref.get('version_id')), None)
            if version and file_at_view(version, 'primary') == ref['file']:
                return ref
    return None


def view_states(version, references, role, asset_id, version_id):
    """Every view actually present in a version, with its approval state.

    A view is `approved` only when an approval record for the same view and file
    exists and carries a file digest. Rows saved before digests were introduced
    stay usable as `legacy`; views without an approval record are always
    `unapproved` and must never enter production silently.
    """
    files = {}
    if version.get('file'):
        files['primary'] = version['file']
    files.update({view: file for view, file in (version.get('views') or {}).items() if file})
    approved = dict(approved_refs(references, role, asset_id, version_id, version))
    states = []
    for view in allowed_views(role):
        file = files.get(view)
        if not file:
            continue
        ref = approved.get(view)
        if ref and ref.get('file') == file:
            status = 'approved' if ref.get('sha256') else 'legacy'
        else:
            ref, status = None, 'unapproved'
        states.append(dict(view=view, file=file, label=VIEW_LABELS.get(view, view),
                           status=status, status_label=STATUS_LABELS[status], approval=ref))
    return states


def validate_bible(brief, assets, media_path, previous=()):
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
                or file_at_view(version, view) != ref['file']):
            if ref in previous:
                continue
            raise ValueError('视觉参考必须属于指定资产版本；同一版本可按视图分别批准，作品只能指定一张风格图')
        if ref not in previous:
            data = read_image(media_path(ref['file']))
            if ref.get('sha256') and hashlib.sha256(data).hexdigest()!=ref['sha256']:
                raise ValueError('已批准的参考图文件发生变化')
            image_mime(data)
        seen.add(key)
        if role == 'style':
            style_seen = True
