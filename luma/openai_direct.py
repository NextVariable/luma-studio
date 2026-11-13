"""Direct speech and single-shot revision. The studio owns review and saved media."""
import base64
import binascii
import hashlib
import http.client
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
import wave
from contextlib import closing
from urllib.parse import urlencode

from .contracts import validate
from .providers import UncertainRun, encode_context, open_request

BASE = 'https://api.openai.com/v1'
MODELS = {'audio': 'gpt-realtime-2.1-mini', 'revision': 'gpt-5.4-mini'}
FIELDS = ('description', 'duration', 'framing', 'camera', 'dialogue', 'asset_ids')
CAMERA_ONLY = re.compile(
    r'(?:把(?:这|本)一?镜)?(?:改成|改为|换成|切到|使用)(?P<framing>大特写|特写|近景|中近景|中景|全景|远景|大远景)'
    r'(?:[，,、\s]*(?:(?:角色|人物|对白|台词|剧情|其他)(?:和|与|及|、)?)+(?:保持不变|不变))?[。！!\s]*'
)
KEEP_DIALOGUE = re.compile(r'(?:对白|台词)[^。；;，,]{0,16}(?:不变|别改|不要改|照旧)|(?:保留|保持|不要改|别改)[^。；;，,]{0,12}(?:对白|台词)')
KEEP_CAST = re.compile(r'(?:人物|角色|造型)[^。；;，,]{0,16}(?:不变|别改|不要改|照旧)|(?:保留|保持|不要改|别改)[^。；;，,]{0,12}(?:人物|角色|造型)')


def key():
    return os.environ.get('OPENAI_API_KEY', '').strip()


def identity(kind, credential=None):
    credential = key() if credential is None else credential
    return {'provider': 'openai', 'host': 'api.openai.com', 'model': MODELS[kind],
            'key_fingerprint': hashlib.sha256(('luma-key:'+credential).encode()).hexdigest()[:12]}


def request(path, body, credential, authorize, limit):
    req = urllib.request.Request(BASE+path, json.dumps(body, ensure_ascii=False).encode(),
                                 {'Authorization': 'Bearer '+credential, 'Content-Type': 'application/json'})
    authorize()
    try:
        with open_request(req, timeout=120) as response:
            content = response.read(limit+1)
            request_id = response.headers.get('x-request-id')
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            raise UncertainRun('OpenAI 服务异常，远程结果待核实，未自动重试') from None
        raise ValueError(f'OpenAI 请求失败 HTTP {exc.code}，请检查 API Key、模型权限或额度') from None
    except (OSError, http.client.HTTPException):
        raise UncertainRun('OpenAI 连接中断，远程结果待核实，未自动重试') from None
    if not content or len(content)>limit:
        raise ValueError('OpenAI 返回内容为空或超过大小限制')
    return content, request_id


REALTIME_VOICES = frozenset(('alloy','ash','ballad','coral','echo','sage','shimmer','verse','marin','cedar'))
PCM_RATE = 24000
MAX_AUDIO_BYTES = 50*1024*1024


def check_voice(voice):
    if voice not in REALTIME_VOICES:
        raise ValueError('OpenAI 直连不支持当前角色音色，请在角色设定中另建支持的音色版本并更新本镜绑定')


def open_realtime(credential):
    try:
        from websocket import create_connection, WebSocketException
    except ImportError:
        raise ValueError('OpenAI 直连配音需要安装 requirements-realtime.txt 中的 WebSocket 依赖') from None
    try:
        return create_connection('wss://api.openai.com/v1/realtime?'+urlencode({'model':MODELS['audio']}),
                                 header={'Authorization':'Bearer '+credential},
                                 timeout=120, redirect_limit=0,
                                 sslopt={'context':ssl.create_default_context()})
    except (WebSocketException,OSError):
        raise ValueError('无法连接 OpenAI 实时配音服务，未提交配音请求') from None


def send_event(socket,event,paid=False):
    try:
        socket.send(json.dumps(event,ensure_ascii=False))
    except Exception:
        if paid:raise UncertainRun('配音提交结果待核实，未自动重试') from None
        raise ValueError('配音服务未能完成连接设置，未提交配音请求') from None


def realtime_events(socket,paid=False):
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        try:
            raw=socket.recv()
            if not raw:raise OSError('closed')
        except Exception:
            break
        try:
            event=json.loads(raw)
        except (ValueError,TypeError):
            break
        if not isinstance(event,dict):break
        if event.get('type')=='error':
            code=(event.get('error') or {}).get('code')
            label=f'（{code}）' if isinstance(code,str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,60}',code) else ''
            if paid:raise ValueError('OpenAI 配音执行失败'+label)
            raise ValueError('OpenAI 配音连接设置失败，未提交生成'+label)
        yield event
    if paid:raise UncertainRun('配音连接中断或超时，未自动重试') from None
    raise ValueError('OpenAI 配音连接未就绪，未提交生成')


def validate_wav(source):
    try:
        handle=source.open('rb')
        with handle,wave.open(handle) as audio:
            expected=audio.getnframes()*audio.getnchannels()*audio.getsampwidth()
            if not expected or expected>MAX_AUDIO_BYTES or len(audio.readframes(audio.getnframes()))!=expected:
                raise ValueError('配音返回了空音轨或不完整音轨')
    except (EOFError,wave.Error):
        raise ValueError('配音文件不是有效的 WAV 音轨') from None


def speech(snapshot,credential,authorize,destination):
    speech=snapshot['speech']
    check_voice(speech['voice_id'])
    pcm=bytearray()
    response=None
    with closing(open_realtime(credential)) as socket:
        send_event(socket,{'type':'session.update','session':{
            'type':'realtime','output_modalities':['audio'],
            'audio':{'input':{'turn_detection':None},'output':{
                'format':{'type':'audio/pcm','rate':PCM_RATE},'voice':speech['voice_id']}},
        }})
        for event in realtime_events(socket):
            if event.get('type')=='session.updated':break
        request={'type':'response.create','response':{
            'conversation':'none','output_modalities':['audio'],'max_output_tokens':4096,
            'instructions':'你为影视作品朗读台词。只逐字朗读给出的正文，保留原语言和内容。不要回应、改写、翻译、解释、加开场白或添加其他内容。',
            'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':speech['text']}]}],
        }}
        authorize()
        send_event(socket,request,paid=True)
        for event in realtime_events(socket,paid=True):
            kind=event.get('type')
            if kind=='response.output_audio.delta':
                try:pcm.extend(base64.b64decode(event['delta'],validate=True))
                except (KeyError,TypeError,binascii.Error):raise ValueError('OpenAI 返回了无效音频片段') from None
                if len(pcm)>MAX_AUDIO_BYTES:raise ValueError('配音文件超过大小限制')
            elif kind=='response.done':
                response=event.get('response') or {}
                break
    if not response or response.get('status')!='completed' or not pcm or len(pcm)%2:
        raise ValueError('OpenAI 未返回完整配音')
    tmp=destination.with_suffix('.tmp')
    try:
        with wave.open(str(tmp),'wb') as audio:
            audio.setparams((1,2,PCM_RATE,0,'NONE','not compressed'))
            audio.writeframes(pcm)
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)
    usage=response.get('usage') or {}
    return {'state':'succeeded','candidate_file':destination.name,'cost':None,
            'response_id':response.get('id'),'tokens':usage.get('total_tokens'),'usage':usage}


def complete(instruction, context, credential, authorize):
    content, request_id = request('/chat/completions', {
        'model': MODELS['revision'], 'max_completion_tokens': 3000, 'response_format': {'type': 'json_object'},
        'messages': [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': context}],
    }, credential, authorize, 1_000_000)
    try:
        response = json.loads(content)
        choice = response['choices'][0]
        if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
            raise ValueError('模型未完整返回镜头修改')
        value = json.loads(choice['message']['content'])
        if not isinstance(value, dict):
            raise ValueError('模型须返回 JSON 对象')
        return value, response.get('usage', {}).get('total_tokens'), request_id
    except (IndexError, KeyError, TypeError):
        raise ValueError('OpenAI 返回的镜头修改格式无效') from None


def revise(snapshot, credential, authorize):
    target_id = snapshot['target_shot_id']
    target = next(s for s in snapshot['shots'] if s['id']==target_id)
    instruction = snapshot['instruction'].strip()
    framing_only = CAMERA_ONLY.fullmatch(instruction)
    context = encode_context(snapshot)
    proposal, tokens, request_id = complete(
        '你是流幕的单镜修订助手。用户输入是 JSON 项目快照。只按 instruction 修改 target_shot_id，'
        '参考相邻镜头，不执行媒体生成。返回 JSON {"id":"目标镜头ID","changes":{...}}，仅包含改动字段。'
        '可改字段为 description、duration、framing、camera、dialogue、asset_ids。'
        '镜头时长必须为 1–60 秒，只引用已有资产。除非明确要求，保留剧情事实、对白和人物。'
        + ('本次只允许修改 framing，取值须与用户要求的景别相同。' if framing_only else ''),
        context, credential, authorize)
    changes = proposal.get('changes')
    if proposal.get('id') != target_id or not isinstance(changes, dict) or set(changes)-set(FIELDS):
        raise ValueError('修改建议越出目标镜头或包含不支持的字段')
    if any(not isinstance(changes[k], str) for k in ('description','framing','camera','dialogue') if k in changes):
        raise ValueError('镜头修改的文字字段格式无效')
    changes = {k:v for k,v in changes.items() if v!=target.get(k)}
    if not changes:
        raise ValueError('没有可应用的镜头变化')
    if framing_only and changes != {'framing': framing_only['framing']}:
        raise ValueError('景别修改须保留对白、角色和剧情')
    if 'dialogue' in changes and KEEP_DIALOGUE.search(instruction):
        raise ValueError('修改建议改动了要求保留的对白')
    if 'asset_ids' in changes:
        assets = changes['asset_ids']
        if KEEP_CAST.search(instruction):
            raise ValueError('修改建议改动了要求保留的角色引用')
        if (not isinstance(assets, list) or any(not isinstance(a, str) for a in assets)
                or len(set(assets))!=len(assets) or set(assets)-{a['id'] for a in snapshot['assets']}):
            raise ValueError('修改建议引用了无效资产')
    shot = {'id': target_id, 'description': target['description'], 'duration': target['duration'], **changes}
    validate('revision', {'shots': [shot]})
    result = {'state':'succeeded', 'result': {'status':'revision_proposed', 'shots':[shot],
              'source_revision':snapshot['revision'], 'target_shot_id':target_id,
              'media_generation_started':False}, 'tokens':tokens, 'cost':None,
              'request_id':request_id, 'model_reviewed':not framing_only}
    if not framing_only:
        review, review_tokens, review_id = complete(
            '独立审查单镜修改。对照 instruction、相邻镜头、剧情承接、对白和资产引用。'
            '如果改了用户未要求的事实或破坏连续性就拒绝。只返回 JSON {"passed": true 或 false, "issues": ["问题"]}。',
            json.dumps({'project':json.loads(context), 'proposal':{'id':target_id, **changes}},ensure_ascii=False),
            credential, authorize)
        result['review_request_id'] = review_id
        if type(review_tokens) is int:
            result['tokens'] = (tokens or 0)+review_tokens
        if review.get('passed') is not True:
            issues = review.get('issues')
            issues = [s[:300] for s in issues[:10] if isinstance(s,str)] if isinstance(issues,list) else []
            result['state'] = 'blocked'
            result['result'].update(status='blocked', issues=issues or ['单镜修改未通过连续性复审'])
    return result
