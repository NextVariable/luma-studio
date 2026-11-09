"""Receive media artifacts from dedicated Dify media workflows; never run a model."""
import ipaddress
import json
import socket
import ssl
import http.client
import subprocess
import uuid
from urllib.parse import urlparse

def receive(url, kind, folder):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('生成素材必须是公网 HTTPS 地址')
    addresses={x[4][0] for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise ValueError('拒绝下载内网或本机地址')
    # Pin validated address; preserve TLS hostname validation and reject redirects.
    conn=http.client.HTTPSConnection(p.hostname,timeout=60,context=ssl.create_default_context())
    raw=socket.create_connection((sorted(addresses)[0],443),timeout=60)
    try:conn.sock=conn._context.wrap_socket(raw,server_hostname=p.hostname)
    except Exception:
        raw.close();raise
    ext={'image':'.png','video':'.mp4','audio':'.wav'}[kind]
    dest=folder/(uuid.uuid4().hex+ext)
    normalized=None;complete=False
    try:
        conn.request('GET',(p.path or '/')+('?' + p.query if p.query else ''))
        r=conn.getresponse()
        if r.status!=200:raise ValueError('素材下载失败；保留远程结果，不重新生成')
        size=0
        with dest.open('wb') as f:
            while chunk:=r.read(65536):
                size+=len(chunk)
                if size>200*1024*1024:raise ValueError('素材超过 200 MB')
                f.write(chunk)
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_streams','-of','json',str(dest)],timeout=30))
        required='audio' if kind=='audio' else 'video'
        if not any(s['codec_type']==required for s in info.get('streams',[])):raise ValueError('生成素材没有所需媒体轨道')
        # Normalize containers so the file extension always describes the saved bytes.
        normalized=folder/(uuid.uuid4().hex+ext)
        args=['ffmpeg','-nostdin','-y','-v','error','-protocol_whitelist','file,pipe','-i',str(dest)]
        args+=['-frames:v','1'] if kind=='image' else ['-vn','-c:a','pcm_s16le'] if kind=='audio' else ['-c:v','libx264','-c:a','aac']
        subprocess.run([*args,str(normalized)],check=True,capture_output=True,timeout=240)
        complete=True
        return normalized.name
    finally:
        conn.close();dest.unlink(missing_ok=True)
        if normalized and not complete:normalized.unlink(missing_ok=True)
