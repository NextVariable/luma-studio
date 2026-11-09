"""Dify Service API adapter. Credentials and form tokens stay on the server."""
import hashlib, json, os, ssl, urllib.request, urllib.error, uuid, mimetypes
from urllib.parse import urlparse, quote, urlencode
from contracts import validate


class UncertainRun(ValueError):
    """A request may have executed remotely; never automatically submit it again."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_request(request, timeout):
    return urllib.request.build_opener(NoRedirect()).open(request,timeout=timeout)


def key_for(kind):
    return os.environ.get('DIFY_PRODUCTION_KEY') if kind == 'shots' and os.environ.get('DIFY_PRODUCTION_KEY') else os.environ.get('DIFY_' + kind.upper() + '_KEY')


def key_env_for(kind):
    return 'DIFY_PRODUCTION_KEY' if kind == 'shots' and os.environ.get('DIFY_PRODUCTION_KEY') else 'DIFY_' + kind.upper() + '_KEY'


def provider_identity(kind):
    """Which Dify app a job was queued against. Host, key variable name and a short key fingerprint only:
    enough to tell two apps apart, never enough to use or recover the key."""
    key=key_for(kind) or ''
    endpoint=os.environ.get('DIFY_BASE_URL','https://api.dify.ai/v1').rstrip('/')
    host=urlparse(endpoint).hostname
    return {'provider':'dify','host':host,'endpoint_fingerprint':hashlib.sha256(endpoint.encode()).hexdigest(),'key_env':key_env_for(kind),'key_fingerprint':hashlib.sha256(('luma-key:'+key).encode()).hexdigest()[:12]}


def sse_events(response):
    lines=[]; size=0
    for raw in response:
        line=raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if lines:
                yield json.loads('\n'.join(lines))
            lines=[]; size=0
        elif line.startswith('data:'):
            part=line[5:].lstrip(' '); size+=len(part)
            if size > 2_000_000: raise ValueError('Dify 单条事件过大')
            lines.append(part)
    if lines: yield json.loads('\n'.join(lines))


def encode_context(context):
    fields=('id','title','episode_id','episode_title','revision','script','assets','shots','target_seconds','max_scenes','scope','target_shot_id','instruction','basis','reference_media','reference_mode','reference_omitted','creative_brief','creative_context','generation_segment','speech')
    encoded=json.dumps({k:context[k] for k in fields if k in context},ensure_ascii=False)
    if len(encoded)>100000:
        raise ValueError('本次创作输入超过工作流的 10 万字符限制，请缩短剧本或资产设定')
    return encoded


class Dify:
    def inspect_connection(self, kind):
        """Read app metadata only. Never starts a workflow or consumes an allowance."""
        if kind not in PROVIDERS[0]['capabilities']:
            raise ValueError('工作流类型无效')
        with self.request(kind,'/info') as response: info=json.load(response)
        with self.request(kind,'/parameters') as response: parameters=json.load(response)
        if not isinstance(info,dict) or info.get('mode')!='workflow':
            raise ValueError('此 Key 对应的应用不是工作流')
        if not isinstance(parameters,dict) or not isinstance(parameters.get('user_input_form'),list):
            raise ValueError('Dify 未返回有效的输入表单')
        fields={}
        for entry in parameters['user_input_form']:
            if isinstance(entry,dict):
                for type_name, field in entry.items():
                    if isinstance(field,dict) and isinstance(field.get('variable'),str):
                        fields[field['variable']]=type_name
        if fields.get('context') not in ('paragraph','text-input'):
            raise ValueError('工作流缺少 context 文本输入，请检查是否接错应用')
        if kind in ('image','video','audio') and fields.get('reference_files')!='file-list':
            raise ValueError('媒体工作流缺少 reference_files 文件列表输入')
        return {'connected':True,'generation_verified':False,'app_name':str(info.get('name',''))[:120],
                'message':'接口已连通，生成效果尚未验证'}

    def request(self, kind, path, body=None, content_type="application/json"):
        key=key_for(kind)
        if not key: raise ValueError(f'Dify {kind} 尚未配置应用 API Key')
        base=os.environ.get('DIFY_BASE_URL','https://api.dify.ai/v1').rstrip('/')
        parsed=urlparse(base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError('Dify 地址无效')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost','127.0.0.1')):
            raise ValueError('Dify 地址必须使用 HTTPS，本机服务除外')
        req=urllib.request.Request(base+path, None if body is None else body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode(),
            {'Authorization':'Bearer '+key,'Content-Type':content_type})
        try: return open_request(req,timeout=180)
        except urllib.error.HTTPError as e:
            if e.code >= 500: raise UncertainRun('Dify 服务异常，远程结果待核实，不自动重复提交') from None
            raise ValueError(f'Dify 请求失败 HTTP {e.code}，请检查发布状态、权限或表单有效期') from None
        except urllib.error.URLError as e:
            if isinstance(e.reason,ssl.SSLCertVerificationError):
                raise ValueError('Dify HTTPS 证书验证失败，请配置可信 CA 证书；请求未提交，不会消耗模型额度') from None
            raise UncertainRun('Dify 连接中断，远程结果待核实，不自动重复提交') from None
        except OSError:
            raise UncertainRun('Dify 连接中断，远程结果待核实，不自动重复提交') from None

    def upload_reference(self, kind, user, path):
        mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        category=mime.split('/')[0]
        if category not in ('image','audio','video'):raise ValueError('参考素材必须为图片、音频或视频')
        limit={'image':10,'audio':50,'video':100}[category]*1024*1024
        if path.stat().st_size>limit:raise ValueError('参考素材超过 Dify 默认上传限制')
        boundary='auteur'+uuid.uuid4().hex
        # Filename is deliberately generated; local names cannot inject MIME headers.
        filename='reference'+path.suffix.lower()
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="user"\r\n\r\n{user}\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n').encode()
        body+=path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        with self.request(kind,'/files/upload',body,'multipart/form-data; boundary='+boundary) as response:
            result=json.load(response)
        if not isinstance(result.get('id'),str):raise ValueError('Dify 未返回参考文件 ID')
        return {'type':category,'transfer_method':'local_file','upload_file_id':result['id']}

    def run(self, kind, context, on_progress=None, media_path=None):
        body={'inputs':{'context':encode_context(context)},'response_mode':'streaming','user':'auteur-'+context['id']}
        if kind in ('image','video','audio'):
            refs=context.get('reference_media',[])
            if len(refs)>10:raise ValueError('单次生成最多使用 10 个参考素材')
            if refs and media_path is None:raise ValueError('参考素材读取器未配置，拒绝丢失参考继续生成')
            body['inputs']['reference_files']=[self.upload_reference(kind,body['user'],media_path(r['file'])) for r in refs]
        with self.request(kind,'/workflows/run',body) as response:
            return self.consume(response,kind,context,on_progress)

    def listen(self, kind, context, previous, on_progress=None):
        run=previous.get('run_id')
        if not run: raise ValueError('没有远程运行编号，不能核实；请在 Dify 日志检查，不自动重发')
        query=urlencode({'user':'auteur-'+context['id'],'include_state_snapshot':'true'})
        previous={k:v for k,v in previous.items() if k not in ('form_token','form','review_id')}
        with self.request(kind,'/workflow/'+quote(run,safe='')+'/events?'+query) as response:
            return self.consume(response,kind,context,on_progress,previous)

    def submit(self, kind, context, previous, action, inputs):
        token=previous.get('form_token')
        if not token: raise ValueError('此审批没有可用表单，请在 Dify 内处理后核实状态')
        with self.request(kind,'/form/human_input/'+quote(token,safe=''),
                          {'action':action,'inputs':inputs,'user':'auteur-'+context['id']}):
            # HTTP success accepts this one-shot form; an empty body must not reopen it.
            pass

    def consume(self, response, kind, context, on_progress=None, previous=None):
        result={**(previous or {}),'state':'running','cost':None}
        try:
            for event in sse_events(response):
                name=event.get('event'); data=event.get('data') or {}
                result['run_id']=event.get('workflow_run_id') or result.get('run_id')
                result['task_id']=event.get('task_id') or result.get('task_id')
                if name in ('node_started','node_finished'):
                    result['current_node']={'title':data.get('title') or data.get('node_title') or data.get('node_id'),
                                            'status':data.get('status') or ('running' if name=='node_started' else 'finished')}
                if on_progress and name in ('workflow_started','node_started','node_finished','human_input_required'):
                    on_progress(result)
                if name=='error': raise ValueError('Dify 执行失败，请检查远程运行日志')
                if name=='human_input_required':
                    token=data.get('form_token'); result['form_token']=token
                    if token:
                        with self.request(kind,'/form/human_input/'+quote(token,safe='')+'?'+urlencode({'user':'auteur-'+context['id']})) as form_response:
                            result['form']=json.load(form_response)
                        result['review_id']=hashlib.sha256(token.encode()).hexdigest()
                    else:
                        result['form']={'form_content':data.get('form_content','请在 Dify 中处理审批'), 'inputs':[], 'user_actions':[]}
                        result['review_id']=None
                    result['state']='waiting_review'
                    if result.get('current_node'): result['current_node']['status']='waiting_review'
                    return result
                if name=='workflow_paused':
                    result.update(state='waiting_review',form=result.get('form') or {'form_content':'请在 Dify 中审批，之后核实状态','inputs':[],'user_actions':[]})
                    return result
                if name=='workflow_finished':
                    if data.get('status')!='succeeded': raise ValueError('Dify 未成功完成，请检查远程运行日志')
                    outputs=data.get('outputs') or {}
                    names=('result','input_end_result','scene_end_result','blocked_end_result','approved_end_result','rejected_end_result','timeout_end_result')
                    candidates=[outputs[n] for n in names if outputs.get(n) is not None]
                    if len(candidates)!=1: raise ValueError('Dify 返回多个或缺失结果，拒绝采纳')
                    output=candidates[0]
                    # Native TTS tools return files, not an LLM-authored JSON URL.
                    # Bind that file to the exact shot/version before receiving it.
                    if kind=='audio' and isinstance(output,list):
                        if len(output)!=1 or not isinstance(output[0],dict) or output[0].get('type')!='audio':
                            raise ValueError('配音工作流须返回唯一音频文件')
                        if type(outputs.get('source_revision')) is not int or outputs['source_revision']!=context.get('revision'):
                            raise ValueError('配音文件来源版本不一致')
                        if not context.get('target_shot_id') or outputs.get('target_shot_id')!=context['target_shot_id']:
                            raise ValueError('配音文件目标镜头不一致')
                        speech=context.get('speech') or {}
                        if speech and (outputs.get('voice_id')!=speech['voice_id'] or outputs.get('line_id')!=(speech.get('line_id') or '')):
                            raise ValueError('配音音色或对白句子与冻结请求不一致')
                        output={'url':output[0].get('url'), 'source_revision':outputs['source_revision'],
                                'target_shot_id':outputs['target_shot_id']}
                    if isinstance(output,str): output=json.loads(output)
                    if not isinstance(output,dict): raise ValueError('Dify 结果须为对象')
                    if output.get('source_revision',context.get('revision'))!=context.get('revision'):
                        raise ValueError('Dify 结果来源版本不一致')
                    status=output.get('status')
                    blocked=status in ('blocked','requires_review','revision_requested')
                    if (kind=='revision' or (kind=='shots' and os.environ.get('DIFY_PRODUCTION_KEY'))) and status not in (('creative_approved','revision_proposed','blocked','requires_review','revision_requested') if kind=='revision' else ('creative_approved','blocked','requires_review','revision_requested')):
                        raise ValueError('制作工作流未返回明确的创作审批状态')
                    if not blocked: validate(kind,output)
                    result.update(state='blocked' if blocked else 'succeeded',result=output,
                                  tokens=data.get('total_tokens'),elapsed=data.get('elapsed_time'))
                    if result.get('current_node'): result['current_node']['status']='finished'
                    for key in ('form_token','form','review_id'): result.pop(key,None)
                    return result
        except (OSError, urllib.error.URLError):
            raise UncertainRun('Dify 事件连接断开，结果待核实，不自动重复提交') from None
        raise UncertainRun('Dify 事件流未正常结束，结果待核实，不自动重复提交')


PROVIDERS=[
 {'id':'dify','capabilities':['script','assets','shots','revision','image','video','audio','plan','qc'],'async':True,'cost':'由 Dify 实际运行记录确定'},
 {'id':'local-media','capabilities':['import','export'],'async':True,'cost':'本机处理，无外部调用'},
]
