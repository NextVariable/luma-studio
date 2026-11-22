"""Direct Beijing-region adapters for storyboard stills and silent first-frame video."""
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from .fal_media import image_url
from .providers import UncertainRun, open_request

SEEDREAM = 'doubao-seedream-4-5-251128'
FLASH = 'doubao-seedream-5-0-flash-260915'
STILL_MODELS = {FLASH: ('Seedream 5.0 Flash', '0.12'), SEEDREAM: ('Seedream 4.5', '0.25')}
WAN = 'wan2.6-i2v-flash'
HAILUO = 'MiniMax-Hailuo-2.3-Fast'
HAILUO_PRICES = {(6, '768P'): '1.35', (10, '768P'): '2.25', (6, '1080P'): '2.31'}
KEYS = {'ark': 'ARK_API_KEY', 'dashscope': 'DASHSCOPE_API_KEY', 'minimax': 'MINIMAX_API_KEY'}
PROVIDER = {FLASH: 'ark', SEEDREAM: 'ark', WAN: 'dashscope', HAILUO: 'minimax'}
WAN_PROFILE = dict(verified=True, contract='luma-prepared-media-v1', provider='dashscope',
                   label='Wan 2.6 Flash · 无声', kind='video', modes=['image_to_video'],
                   evidence='https://help.aliyun.com/zh/model-studio/wan2-6-i2v-flash',
                   duration=dict(min=2, max=15, step=1), resolutions=['720P'],
                   aspect_ratios=['16:9', '9:16'], parameters=['aspect_ratio', 'resolution'],
                   max_images=1, role_limits={'first_frame': 1})


HAILUO_PROFILE = dict(WAN_PROFILE, provider='minimax', label='MiniMax 海螺 2.3 Fast',
                      evidence='https://platform.minimax.cn/docs/api-reference/video-generation-i2v',
                      duration=dict(min=6, max=10, step=4), resolutions=['768P', '1080P'],
                      duration_resolution=[[seconds, resolution] for seconds, resolution in HAILUO_PRICES],
                      audio=False, supports_remote_cancel=False)


def key(provider):
    return os.environ.get(KEYS[provider], '').strip()


def host(provider):
    if provider == 'ark':
        return 'ark.cn-beijing.volces.com'
    if provider == 'minimax':
        return 'api.minimax.cn'
    workspace = os.environ.get('DASHSCOPE_WORKSPACE_ID', '').strip()
    if not workspace:
        return 'dashscope.aliyuncs.com'
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', workspace):
        raise ValueError('百炼北京工作空间 ID 无效')
    return workspace + '.cn-beijing.maas.aliyuncs.com'


def identity(model):
    provider = PROVIDER[model]
    return dict(provider=provider, model=model, host=host(provider), key_env=KEYS[provider],
                key_fingerprint=hashlib.sha256(key(provider).encode()).hexdigest()[:12])


def arguments(kind, context, media_path):
    seg = context['generation_segment']
    refs = seg['references']
    roles = [ref['role'] for ref in refs]
    if seg['model'] in STILL_MODELS and kind == 'image':
        if seg.get('mode')=='asset':
            if roles not in ([], ['character'], ['scene']):
                raise ValueError('角色或场景生成最多使用一张原版设定图')
            size = '1440x2560' if seg['parameters']['aspect_ratio']=='9:16' else '2560x1440'
            body = dict(model=FLASH,prompt=seg['instruction'],size=size,response_format='url')
            if refs:
                body['image']=[image_url(media_path(refs[0]['file']))]
            return body
        count = roles.count('character')
        extras = roles[count:]
        composition = ['composition'] if seg.get('reference_mode', 'image') == 'image' else []
        expected = ['character'] * count + (['scene'] if 'scene' in extras else []) + composition + (['style'] if 'style' in extras else [])
        if count not in (1, 2) or roles != expected:
            raise ValueError('分镜参考图的用途或顺序无效')
        size = {'16:9': '2560x1440', '9:16': '1440x2560'}[seg['parameters']['aspect_ratio']]
        body = dict(model=seg['model'], prompt=seg['instruction'], size=size, response_format='url',
                    image=[image_url(media_path(r['file'])) for r in refs])
        if seg['model'] == SEEDREAM:
            body['sequential_image_generation'] = 'disabled'
        return body
    if seg['model'] == HAILUO and kind == 'video' and roles == ['first_frame']:
        seconds, resolution = seg['duration'], seg['parameters']['resolution']
        prompt = seg['instruction']
        if (seconds, resolution) not in HAILUO_PRICES or len(prompt) > 2000:
            raise ValueError('海螺时长、分辨率组合无效，或动作描述超过 2000 字')
        path = media_path(refs[0]['file'])
        image = image_url(path)
        try:
            probe = subprocess.check_output(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(path)],
                timeout=10, stderr=subprocess.DEVNULL)
            width, height = map(int, probe.strip().split(b','))
        except (OSError, subprocess.SubprocessError, ValueError):
            raise ValueError('无法读取海螺首帧尺寸') from None
        if min(width, height) <= 300 or not 0.4 <= width / height <= 2.5:
            raise ValueError('海螺首帧短边须大于 300 像素，宽高比须在 2:5 至 5:2 之间')
        return dict(model=HAILUO, prompt=prompt, first_frame_image=image, duration=int(seconds),
                    resolution=resolution, prompt_optimizer=False)
    if seg['model'] == WAN and kind == 'video' and roles == ['first_frame']:
        seconds = int(seg['duration'])
        if seconds != seg['duration'] or not 2 <= seconds <= 15 or seg['parameters']['resolution'] != '720P':
            raise ValueError('Wan 需要 720P 和 2 至 15 整秒的视频时长')
        return dict(model=WAN, input=dict(prompt=seg['instruction'], img_url=image_url(media_path(refs[0]['file']))),
                    parameters=dict(duration=seconds, resolution='720P', audio=False, shot_type='single'))
    raise ValueError('模型与参考素材用途不匹配')


def request(provider, path, body=None):
    secret = key(provider)
    if not secret:
        raise ValueError('缺少本机 ' + KEYS[provider])
    headers = {'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'}
    if provider == 'dashscope' and body is not None:
        headers['X-DashScope-Async'] = 'enable'
    req = urllib.request.Request('https://' + host(provider) + path,
                                 data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with open_request(req, timeout=180) as response:
            request_id = response.headers.get('X-Request-Id') or response.headers.get('X-Tt-Logid')
            result = json.loads(response.read(2_000_001))
        if not isinstance(result, dict):
            raise ValueError()
        if provider == 'ark' and request_id:
            result['provider_request_id'] = request_id
        return result
    except urllib.error.HTTPError as error:
        if error.code < 500 and error.code != 429:
            raise ValueError(f'生成服务拒绝请求（HTTP {error.code}），请核对凭据与模型权限') from None
        raise UncertainRun('生成服务暂不可用，请核实原请求') from None
    except (OSError, ValueError):
        raise UncertainRun('生成服务响应中断，不自动重发') from None


def completed(url, run=None):
    if not isinstance(url, str) or not url.startswith('https://'):
        raise UncertainRun('未取得可下载的素材，请核实原请求')
    return dict(state='succeeded', run_id=run, result={'url': url})


class DomesticMedia:
    def submit(self, kind, context, body, on_progress):
        if kind == 'image':
            result = request('ark', '/api/v3/images/generations', body)
            images = result.get('data')
            if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
                raise UncertainRun('未取得预期的一张分镜，请检查方舟生成记录')
            output = completed(images[0].get('url'))
            output.update(provider_request_id=result.get('provider_request_id') or result.get('request_id'),
                          model=result.get('model') or body['model'], usage=result.get('usage'),
                          billing_status='unreconciled')
            on_progress(output)
            return output
        if body['model'] == HAILUO:
            response = minimax_request('/v1/video_generation', body)
            run = response.get('task_id')
            if not valid_run(run):
                raise UncertainRun('海螺未返回可查询的任务编号，请核对原请求')
            previous = dict(run_id=run, state='running', billing_status='unreconciled')
            on_progress(previous)
            return self.listen(kind, context, previous, on_progress)
        result = request('dashscope', '/api/v1/services/aigc/video-generation/video-synthesis', body)
        run = result.get('output', {}).get('task_id')
        if not valid_run(run):
            raise UncertainRun('百炼未返回可查询的任务编号，请核对原请求')
        previous = dict(run_id=run, state='running')
        on_progress(previous)
        return self.listen(kind, context, previous, on_progress)

    def listen(self, kind, context, previous, on_progress):
        run = previous.get('run_id')
        if kind != 'video' or not valid_run(run):
            raise ValueError('缺少可查询的视频任务')
        if context.get('generation_segment', {}).get('model') == HAILUO:
            return listen_minimax(run, previous, on_progress)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            result = request('dashscope', '/api/v1/tasks/' + run).get('output', {})
            state = result.get('task_status')
            if state == 'SUCCEEDED':
                return completed(result.get('video_url'), run)
            if state in ('FAILED', 'CANCELED'):
                raise ValueError('百炼视频任务失败或已取消')
            if state not in ('PENDING', 'RUNNING'):
                raise UncertainRun('百炼任务状态待核实')
            on_progress(previous)
            time.sleep(3)
        raise UncertainRun('视频仍在生成，可继续查询原任务')


def valid_run(value):
    return isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', value)


def minimax_request(path, body=None):
    response = request('minimax', path, body)
    base = response.get('base_resp')
    if not isinstance(base, dict) or type(base.get('status_code')) is not int:
        raise UncertainRun('海螺响应缺少业务状态，请核对远程任务')
    code = base['status_code']
    if code in (1004, 1008, 2013):
        raise ValueError(f'海螺拒绝请求（错误 {code}）')
    if code:
        raise UncertainRun(f'海螺请求状态待核对（错误 {code}）')
    return response


def listen_minimax(run, previous, on_progress):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        result = minimax_request('/v1/query/video_generation?task_id=' + run)
        if result.get('task_id') != run:
            raise UncertainRun('海螺返回的任务号不一致')
        state = result.get('status')
        if state == 'Success':
            file_id = result.get('file_id')
            if not valid_run(file_id):
                raise UncertainRun('海螺未返回文件编号')
            file = minimax_request('/v1/files/retrieve?file_id=' + file_id).get('file')
            if not isinstance(file, dict) or file.get('file_id') != file_id:
                raise UncertainRun('海螺返回的文件号不一致')
            return dict(completed(file.get('download_url'), run), file_id=file_id, billing_status='unreconciled')
        if state == 'Fail':
            raise ValueError('海螺视频任务失败')
        if state not in ('Preparing', 'Queueing', 'Processing'):
            raise UncertainRun('海螺任务状态待核实')
        on_progress(previous)
        time.sleep(3)
    raise UncertainRun('视频仍在生成，可继续查询原任务')
