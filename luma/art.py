"""Style-aware art direction for generated references, storyboards and video.

The work-level style decides which craft constraints belong in a prompt.  A
cel-shaded animation must never be asked for photoreal skin, and a live-action
film must not be flattened into cartoon lines.  User-defined styles keep the
author's own wording and only receive the shared identity/structure rules.
"""

import re

STYLES = {
    'anime': dict(
        label='精致二维动画 / 赛璐璐',
        keywords=('二维动画', '2d animation', '动漫', '赛璐璐', '二次元', '番剧', 'anime', 'cel'),
        specific=('线稿干净闭合，赛璐璐分层上色，阴影边缘明确；按动画比例绘制完整五官，'
                  '材质以平涂和少量高光表现；禁止照片级皮肤纹理和三维写实质感。'),
    ),
    'comic': dict(
        label='国漫 / 插画',
        keywords=('国漫', '插画', '漫画', '条漫', '绘本', 'comic', 'illustration'),
        specific=('国漫插画线条有轻重变化，色彩层次分明，画面达到封面级完整度；'
                  '面部与服装保持插画化处理；禁止照片写实皮肤和三维渲染感。'),
    ),
    'cinematic': dict(
        label='电影写实',
        keywords=('写实', '实拍', 'live action', 'photoreal', 'photorealistic'),
        specific=('电影级实拍光影，皮肤与布料有可信的材质和细节，镜头质感接近实拍；'
                  '避免卡通化线条和夸张变形。'),
    ),
    'custom': dict(
        label='自定义风格',
        keywords=(),
        specific='',
    ),
}
DEFAULT = 'custom'

GENERAL = ('同一角色的脸型、五官、发型、发色、肤色和服装必须与已批准参考保持一致；'
           '画面内五官完整、肢体结构正确、手指数目正常，服装连续；'
           '背景干净，只出现被描述的角色和物件，不添加多余人物；'
           '不添加未要求的文字或水印。')

SUBJECTS = {
    'character': '角色定妆参考：单人，四分之三角度，面部与服装清晰，简洁背景，柔和主光。',
    'scene': '场景参考：展示地点布局、主要地标、建筑材质与主光方向，画内无人。',
    'storyboard': '完成的漫剧分镜。',
}


def resolve(brief):
    """The active style for a work: explicit choice, keyword inference, or custom."""
    brief = brief if isinstance(brief, dict) else {}
    explicit = brief.get('art_style')
    if explicit in STYLES:
        return dict(key=explicit, **STYLES[explicit])
    text = str(brief.get('style') or '').strip()
    lowered = text.lower()
    # A craft preset is safe only when the writer clearly describes one style.
    if re.search(r'非写实|不写实|避免写实|不要写实|定格|黏土|粘土|水墨|低多边形|\b(?:3d|not|non)[ -]', lowered):
        return dict(key=DEFAULT, **STYLES[DEFAULT])
    matches = []
    for key, spec in STYLES.items():
        if any((re.search(r'(?<![a-z])' + re.escape(word) + r'(?![a-z])', lowered)
                if word.isascii() else word in lowered) for word in spec['keywords']):
            matches.append(key)
    key = matches[0] if len(matches) == 1 else DEFAULT
    return dict(key=key, **STYLES[key])


def constraints(brief, subject=None):
    """Craft constraints for one prompt type, without contradicting the chosen style."""
    style = resolve(brief)
    parts = [SUBJECTS.get(subject, '') if subject else '', GENERAL]
    if style['specific']:
        parts.append(style['specific'] + '禁止低多边形，避免无意的塑料质感。')
    description = style_description(brief)
    if description:
        parts.append('遵循用户风格描述：' + description + '。')
    return ''.join(part for part in parts if part)


def style_description(brief):
    text = str(brief.get('style') or '').strip()
    explicit = brief.get('art_style')
    inferred = resolve({'style': text})['key']
    if explicit in STYLES and explicit != 'custom' and inferred not in (explicit, 'custom'):
        raise ValueError('美术风格选项与画风描述冲突，请修改描述或选择自定义风格')
    return text


def video_clause(brief):
    """A short clause appended to image-to-video prompts to keep the style stable."""
    style = resolve(brief)
    description = '，'.join(filter(None, (style['label'] if style['key'] != 'custom' else '', style_description(brief))))
    prefix = f'画风：{description}。' if description else ''
    return prefix + '保持首帧的人物身份、服装、场景结构和既定画风不变，不新增人物，不改变镜头语言。'
