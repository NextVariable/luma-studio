"""Application-level validation; Dify is not the source of business state."""
import json

KINDS = ('script', 'assets', 'shots', 'revision', 'image', 'video', 'audio', 'plan', 'qc')

def validate(kind, data):
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError('工作流必须返回 JSON 对象')
    if kind in ('image','video','audio'):
        if not isinstance(data.get('url'),str) or not data['url'].startswith('https://'):raise ValueError('媒体工作流必须返回 HTTPS url')
        return data
    if kind=='revision':kind='shots'
    fields = {'script': ('scenes', 'characters'), 'assets': ('assets',), 'shots': ('shots',), 'plan': ('tasks',), 'qc': ('issues',)}[kind]
    for key in fields:
        if not isinstance(data.get(key), list):
            raise ValueError(f'缺少数组 {key}')
        if len(data[key]) > 200:
            raise ValueError('输出超出 200 条限制')
        for item in data[key]:
            if not isinstance(item, dict):
                raise ValueError(f'{key} 元素必须是对象')
    if kind == 'script':
        for item in data['characters'] + data['scenes']:
            if not isinstance(item.get('name'), str) or not item['name'].strip():
                raise ValueError('角色和场景必须包含 name')
    if kind == 'assets':
        for a in data['assets']:
            if a.get('kind') not in ('character','scene','style','prop','voice') or not isinstance(a.get('name'),str):
                raise ValueError('资产 kind 或 name 无效')
    if kind == 'shots':
        for s in data['shots']:
            if 'creative_spec' in s and not isinstance(s['creative_spec'],dict):
                raise ValueError('镜头创作规格必须是对象')
            if not isinstance(s.get('description'),str) or not s['description'].strip():
                raise ValueError('镜头缺少 description')
            if type(s.get('duration')) not in (int,float) or not 1 <= s['duration'] <= 60:
                raise ValueError('镜头时长须为 1–60 秒')
            if not isinstance(s.get('asset_ids',[]),list):
                raise ValueError('asset_ids 必须是数组')
    if kind == 'plan':
        for t in data['tasks']:
            if not all(isinstance(t.get(k),str) and t[k] for k in ('shot_id','capability','provider')):
                raise ValueError('任务缺少 shot_id / capability / provider')
    if kind == 'qc':
        for i in data['issues']:
            if i.get('severity') not in ('info','warning','error') or not isinstance(i.get('message'),str):
                raise ValueError('质检建议格式无效')
    return data
