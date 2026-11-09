"""Build the audio app from a tool node exported from the current Dify workspace.

No model invocation. Supports per-character preset voices and one line per request.
"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).parent
INTAKE = '''import json
def main(context):
    p = json.loads(context)
    if not isinstance(p, dict) or type(p.get('revision')) is not int:
        raise ValueError('缺少项目版本')
    target = p.get('target_shot_id')
    shots = [s for s in p.get('shots', []) if s.get('id') == target]
    if not target or len(shots) != 1:
        raise ValueError('须指定唯一目标镜头')
    shot = shots[0]
    speech = p.get('speech') or {}
    lines = shot.get('lines')
    line_id = speech.get('line_id')
    if line_id:
        lines = [line for line in lines or [] if line.get('id') == line_id]
        if len(lines) != 1: raise ValueError('目标对白不存在')
    if lines:
        if any(not isinstance(line.get('text'), str) or not line['text'].strip() for line in lines):
            raise ValueError('对白内容无效')
        speakers = {line.get('speaker_asset_id') for line in lines}
        if len(speakers) > 1:
            raise ValueError('当前配音连接只支持单一说话人；多角色音色尚未配置，未调用模型')
        text = '\\n'.join(line['text'].strip() for line in lines)
    else:
        text = shot.get('dialogue', '').strip()
    if not 1 <= len(text) <= 4000:
        raise ValueError('配音对白须为1到4000字，未调用模型')
    if speech and speech.get('text') != text: raise ValueError('对白快照不一致')
    voice = speech.get('voice_id', 'alloy')
    if voice not in ('alloy','ash','ballad','coral','echo','fable','onyx','nova','sage','shimmer','verse','marin','cedar'):
        raise ValueError('音色无效')
    return {'text': text, 'voice_id':voice, 'line_id':line_id or '', 'source_revision': p['revision'], 'target_shot_id': target}
'''


def build():
    sample = json.loads((ROOT / 'smoke/script.yml').read_text())
    sample['version'] = '0.7.0'
    sample['dependencies'] = []
    sample['app'].update(name='Luma · 流幕配音', description='逐句角色配音：按工作室冻结的对白与预设音色生成，一次只合成一句或一个说话人，不自动重试。')
    def node(id, type, title, x, data):
        return {'id': id, 'type': 'custom', 'position': {'x': x, 'y': 180},
                'width': 242, 'height': 100, 'sourcePosition': 'right', 'targetPosition': 'left',
                'data': {'type': type, 'title': title, 'selected': False, **data}}
    start = node('start', 'start', '工作室镜头快照', 0, {'variables': [
        {'variable': 'context', 'label': '镜头上下文 JSON', 'type': 'paragraph', 'required': True, 'max_length': 100000},
        {'variable': 'reference_files', 'label': '参考文件（此单人配音不使用视觉参考）', 'type': 'file-list', 'required': False,
         'allowed_file_types': ['image', 'audio', 'video'], 'allowed_file_upload_methods': ['local_file', 'remote_url']}]})
    intake = node('intake', 'code', '校验目标镜头、对白与说话人', 310, {
        'code_language': 'python3', 'code': INTAKE,
        'variables': [{'variable': 'context', 'value_selector': ['start', 'context']}],
        'outputs': {k: {'type': t, 'children': None} for k, t in
                    [('text', 'string'), ('voice_id','string'), ('line_id','string'), ('source_revision', 'number'), ('target_shot_id', 'string')]}})
    tool = copy.deepcopy(json.loads((ROOT / 'fixtures/audio-tool.json').read_text()))
    tool.update(id='tts', position={'x': 620, 'y': 180})
    tool.pop('positionAbsolute', None)
    tool['data']['title'] = '角色预设音色配音'
    tool['data']['tool_configurations']['voice#langgenius/openai/openai#gpt-4o-mini-tts-2025-12-15']={'type':'variable','value':['intake','voice_id']}
    tool['data']['tool_parameters']['text'] = {'type': 'mixed', 'value': '{{#intake.text#}}'}
    tool['data']['retry_config'] = {'retry_enabled': False, 'max_retries': 0, 'retry_interval': 1000}
    end = node('end', 'end', '返回音频与来源版本', 930, {'outputs': [
        {'variable': 'result', 'value_selector': ['tts', 'files'], 'value_type': 'array[file]'},
        {'variable': 'source_revision', 'value_selector': ['intake', 'source_revision'], 'value_type': 'number'},
        {'variable': 'target_shot_id', 'value_selector': ['intake', 'target_shot_id'], 'value_type': 'string'},
        {'variable':'voice_id','value_selector':['intake','voice_id'],'value_type':'string'},
        {'variable':'line_id','value_selector':['intake','line_id'],'value_type':'string'}]})
    nodes = [start, intake, tool, end]
    edges = [{'id': a['id']+'-'+b['id'], 'source': a['id'], 'target': b['id'],
              'sourceHandle': 'source', 'targetHandle': 'target', 'type': 'custom', 'zIndex': 0,
              'data': {'sourceType': a['data']['type'], 'targetType': b['data']['type'], 'isInIteration': False, 'isInLoop': False}}
             for a,b in zip(nodes, nodes[1:])]
    sample['workflow']['graph'] = {'nodes': nodes, 'edges': edges, 'viewport': {'x': 0, 'y': 0, 'zoom': .65}}
    return sample


if __name__ == '__main__':
    (ROOT / 'production/audio-production.yml').write_text(json.dumps(build(), ensure_ascii=False, indent=2)+'\n')
