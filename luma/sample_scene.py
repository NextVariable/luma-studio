"""Editable, locally illustrated three-shot scene with bundled dialogue."""
import hashlib
import shutil
import uuid
import wave
from pathlib import Path

from . import blocking, production
from .episodes import normalize_project

FRAMES = (
    ('站台全景，两人隔着一束灯光站定。', '全景', '青禾', '末班车已经走了。'),
    ('阿远看向青禾，停了一拍。', '中景', '阿远', '我等的不是车。'),
    ('青禾回头，朝站台出口示意。', '近景', '青禾', '那就一起走吧。'),
)


def create(media, save):
    pid = uuid.uuid4().hex
    assets = [{'id': name, 'name': name, 'kind': 'character', 'description': look}
              for name, look in [('阿远', '蓝色外套，站在左侧'), ('青禾', '赭色外套，站在右侧')]]
    assets.append(dict(id='platform', name='夜晚站台', kind='scene', description='末班车驶离后的站台，灯光落在两人之间。'))
    script = '\n'.join(f'{description}\n{speaker}：{line}' for description, _, speaker, line in FRAMES)
    project = {'id': pid, 'title': '末班车之后', 'script': script, 'mode': 'director',
               'assets': assets, 'revision': 0, 'shots': []}
    for i, (description, framing, speaker, line) in enumerate(FRAMES, 1):
        project['shots'].append({'id': f'{pid}-{i}', 'description': description, 'duration': 5,
                                 'framing': framing, 'camera': '固定机位', 'asset_ids': ['阿远', '青禾', 'platform'],
                                 'approved': False, 'needs_review': True, 'locked': False,
                                 'lines': [{'id': f'line-{i}', 'speaker_asset_id': speaker, 'text': line}]})
    production.normalize(normalize_project(project))
    folder = Path(__file__).parent / 'samples' / 'platform'
    copied = []

    def install(name):
        dest = media / (pid + '-' + name)
        copied.append(dest)
        shutil.copyfile(folder / name, dest)
        return dest

    try:
        for asset in project['assets'][:2]:
            asset['versions'][0]['outfit'] = asset['description'].split('，')[0]
        project['assets'][0]['versions'][0]['file'] = install('ayuan.jpg').name
        for i, shot in enumerate(project['shots'], 1):
            frame = install(f'frame-{i}.jpg')
            if i == 3:
                project['assets'][1]['versions'][0]['file'] = frame.name
            selected = production.add_take(shot, 'image', frame.name, shot['framing'])
            production.select_take(shot, selected['id'])
            actors = blocking.layout(project, shot)
            camera = blocking.preset(('wide','left','right')[i-1])
            plate = media / (pid + f'-platform-{i}.png')
            copied.append(plate)
            plate.write_bytes(blocking.render(camera, actors, framing=shot['framing']))
            shot['composition_reference'] = dict(actors=actors, camera=camera, file=plate.name,
                                                 spec=blocking.composition_spec(camera['view'], shot['framing'], False))
            if i == 2:
                production.add_take(shot, 'image', install('frame-4.jpg').name, '备选 · 阿远近景')
            audio = install(f'line-{"abc"[i-1]}.wav')
            voice = production.add_take(shot, 'audio', audio.name, '示例对白')
            with wave.open(str(audio), 'rb') as wav:
                duration = wav.getnframes() / wav.getframerate()
            shot['lines'][0].update(audio_take_id=voice['id'], audio_duration=duration, audio_start=0.6)
            shot.update(approved=True, needs_review=False)
        # The bundled sample is a ready-made work; its own stills are approved so the
        # documented storyboard flow works without a manual approval round.
        bible = project['creative_brief'].setdefault('visual_bible', {})
        bible['references'] = [
            dict(role=asset['kind'], asset_id=asset['id'], version_id=version['id'],
                 file=version['file'], source='示例素材', view='primary',
                 sha256=hashlib.sha256((media / version['file']).read_bytes()).hexdigest())
            for asset in project['assets'] for version in asset['versions'] if version.get('file')
        ]
        return save(project, 0)
    except Exception:
        for path in copied:
            path.unlink(missing_ok=True)
        raise
