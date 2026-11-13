"""fal image and video queue adapter for explicitly prepared generation segments."""
import base64
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request

from providers import UncertainRun, open_request

BASE = 'https://queue.fal.run'
IMAGE = 'fal-ai/flux-pro/kontext'
TEXT_IMAGE = IMAGE + '/text-to-image'
VIDEO = 'fal-ai/kling-video/v2.5-turbo/pro/image-to-video'

PROFILES = {
    model: {
        'verified': True,
        'contract': 'luma-prepared-media-v1',
        'provider': 'fal',
        'label': 'Kling 2.5 Turbo Pro' if kind == 'video' else 'FLUX.1 Kontext Pro',
        'evidence': f'https://fal.ai/models/{model}/api',
        'kind': kind,
        'modes': [mode],
        'duration': {'min': 5, 'max': 10, 'step': 5} if kind == 'video' else {},
        'resolutions': ['auto'],
        'aspect_ratios': ['16:9', '9:16'],
        'parameters': ['aspect_ratio', 'resolution'] + (['seed'] if kind == 'image' else []),
        'max_images': int(role is not None),
        'role_limits': {role: 1} if role else {},
    }
    for model, kind, mode, role in (
        (TEXT_IMAGE, 'image', 'text_to_image', None),
        (IMAGE, 'image', 'reference_to_image', 'reference_image'),
        (VIDEO, 'video', 'image_to_video', 'first_frame'),
    )
}


def key():
    return os.environ.get('FAL_KEY', '').strip()


def identity(model):
    return {
        'provider': 'fal',
        'host': 'queue.fal.run',
        'endpoint_fingerprint': hashlib.sha256(f'{BASE}/{model}'.encode()).hexdigest(),
        'key_env': 'FAL_KEY',
        'key_fingerprint': hashlib.sha256(('luma-key:' + key()).encode()).hexdigest()[:12],
        'model': model,
    }


def arguments(kind, context, media_path):
    segment = context['generation_segment']
    model = segment['model']
    profile = PROFILES.get(model)
    if not profile or profile['kind'] != kind or segment['mode'] not in profile['modes']:
        raise ValueError('fal 模型与已确认的制作方式不一致')
    params = segment['parameters']
    body = {'prompt': segment['instruction']}
    if kind == 'image':
        body.update(aspect_ratio=params['aspect_ratio'], num_images=1, output_format='png')
        if 'seed' in params:
            body['seed'] = params['seed']
    else:
        if segment['duration'] not in (5, 10):
            raise ValueError('Kling 片段仅支持 5 秒或 10 秒')
        body['duration'] = str(int(segment['duration']))
    refs = segment['references']
    if len(refs) != profile['max_images']:
        raise ValueError('fal 参考图数量与已确认的制作方式不一致')
    if refs:
        file = media_path(refs[0]['file'])
        mime = mimetypes.guess_type(file.name)[0]
        if mime not in ('image/png', 'image/jpeg', 'image/webp') or file.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('fal 参考图须为不超过 8 MB 的 PNG、JPEG 或 WebP')
        body['image_url'] = f'data:{mime};base64,' + base64.b64encode(file.read_bytes()).decode('ascii')
    return body


class Fal:
    def request(self, path, body=None):
        secret = key()
        if not secret:
            raise ValueError('fal 尚未配置本机 FAL_KEY')
        req = urllib.request.Request(
            BASE + path, data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Key ' + secret, 'Content-Type': 'application/json'},
        )
        try:
            with open_request(req, timeout=45) as response:
                result = json.loads(response.read(2_000_001))
            if not isinstance(result, dict):
                raise ValueError('invalid queue response')
            return result
        except urllib.error.HTTPError as error:
            if error.code >= 500 or error.code == 429:
                raise UncertainRun(f'fal 暂不可用（HTTP {error.code}），保留任务，不自动重发') from None
            raise ValueError(f'fal 请求未成功（HTTP {error.code}），请核对授权、余额或请求状态') from None
        except (OSError, ValueError):
            raise UncertainRun('fal 返回中断或无效，远程结果待核实，不自动重发') from None

    def submit(self, kind, context, body, on_progress):
        model = context['generation_segment']['model']
        accepted = self.request('/' + model, body)
        run = accepted.get('request_id')
        if not isinstance(run, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', run):
            raise UncertainRun('fal 未返回可核实的任务编号，不自动重发')
        previous = {'run_id': run, 'state': 'running'}
        on_progress(previous)
        return self.listen(kind, context, previous, on_progress)

    def listen(self, kind, context, previous, on_progress):
        model = context['generation_segment']['model']
        run = previous.get('run_id')
        if model not in PROFILES or not isinstance(run, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', run):
            raise ValueError('fal 任务缺少可核实的模型或运行编号')
        # Queue lookups are scoped to the owner and app, excluding the endpoint subpath.
        app = '/'.join(model.split('/')[:2])
        path = f'/{app}/requests/{run}'
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            status = self.request(path + '/status').get('status')
            if status == 'COMPLETED':
                result = self.request(path)
                images = result.get('images')
                artifact = (images[0] if isinstance(images, list) and images else None) if kind == 'image' else result.get('video')
                url = artifact.get('url') if isinstance(artifact, dict) else None
                if not isinstance(url, str) or not url.startswith('https://'):
                    raise ValueError('fal 完成但未返回可下载的素材')
                return {'run_id': run, 'state': 'succeeded', 'result': {'url': url}}
            if status not in ('IN_QUEUE', 'IN_PROGRESS'):
                raise UncertainRun('fal 返回未知任务状态，可稍后核实原任务')
            on_progress(previous)
            time.sleep(3)
        raise UncertainRun('fal 仍在生成，可稍后核实原任务，无需重新提交')
