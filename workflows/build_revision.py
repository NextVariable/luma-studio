"""Independent single-shot Dify workflow. Generate locally; never publish or run."""
import json
from build_production import Graph

g=Graph()
g.node('start','start','单镜修订快照',0,200,{'variables':[{'variable':'context','label':'镜头上下文 JSON','type':'paragraph','required':True,'max_length':100000}]})
g.code('intake','校验修改范围',300,200,{'context':['start','context']},{'project':'object','ok':'number','result':'object'},'''
import json
def main(context):
    try:
        p=json.loads(context)
        assert p.get('scope')=='shot' and isinstance(p.get('instruction'),str) and p['instruction'].strip()
        assert len([s for s in p['shots'] if s['id']==p['target_shot_id']])==1
        return {'project':p,'ok':1,'result':{'status':'requires_review'}}
    except Exception:
        return {'project':{},'ok':0,'result':{'status':'blocked','issues':['单镜范围或修改要求无效']}}
''')
g.gate('input_gate','范围有效',600,200,['intake','ok'])
g.end('input_end','退回输入问题',900,600,['intake','result'])
g.llm('director','仅修订目标镜头',900,200,'只修改 target_shot_id 指定的一镜，shots 必须且只能有一个元素。其他镜头仅作连续性上下文。按 instruction 修改，未要求的剧情、人物、对白保持不变。asset_ids 只能引用已有资产。返回 shots 和 missing_assets。每镜包含 description、duration（1–60秒）、framing、camera、dialogue、asset_ids。不开始任何媒体生成。','项目 {{#intake.project#}}')
g.llm('continuity','独立审核单镜变更',1200,200,'核查目标镜头是否按 instruction 修改、是否擅改其他剧情事实、是否与相邻镜头冲突。只审文本，不能宣称画面一致性已通过。返回 passed 和 issues 字符串数组。','项目 {{#intake.project#}}\n修订 {{#director.text#}}')
check='''
import json
def main(text,review,project):
    issues=[];shots=[]
    try:
        d=json.loads(text);r=json.loads(review);shots=d['shots']
        assert len(shots)==1,'只能返回一个目标镜头'
        s=shots[0]
        assert isinstance(s.get('description'),str) and s['description'].strip(),'缺少画面描述'
        assert type(s.get('duration')) in (int,float) and 1<=s['duration']<=60,'时长应为1–60秒'
        assert set(s.get('asset_ids',[])) <= {a['id'] for a in project['assets']},'资产引用越界'
        if r.get('passed') is not True:issues+=r.get('issues') or ['连续性审核未通过']
        if d.get('missing_assets'):issues+=d['missing_assets']
    except Exception as e:issues.append(str(e))
    result={'status':'blocked' if issues else 'requires_review','shots':shots,'issues':issues,'source_revision':project.get('revision'),'target_shot_id':project.get('target_shot_id'),'media_generation_started':False}
    return {'ok':int(not issues),'result':result,'review_text':json.dumps(result,ensure_ascii=False)}
'''
out={'ok':'number','result':'object','review_text':'string'}
g.code('check','结构与引用硬校验',1500,200,{'text':['director','text'],'review':['continuity','text'],'project':['intake','project']},out,check)
g.gate('quality_gate','是否需要一次返工',1800,200,['check','ok'])
g.llm('repair','局部返工一次',2100,500,'只解决明确问题，仍只返回目标镜头一个元素。返回 shots 和 missing_assets。保留无问题字段，不能修改其他镜头。','项目 {{#intake.project#}}\n方案 {{#director.text#}}\n问题 {{#check.result#}}')
g.llm('recheck','独立复审',2400,500,'核查返工是否解决问题，返回 passed 和 issues；不得因已经返工而放行。','项目 {{#intake.project#}}\n原问题 {{#check.result#}}\n返工 {{#repair.text#}}')
g.code('repair_check','返工硬校验',2700,500,{'text':['repair','text'],'review':['recheck','text'],'project':['intake','project']},out,check)
g.gate('repair_gate','返工是否通过',3000,500,['repair_check','ok'])
g.end('blocked_end','保留问题不自动重试',3300,800,['repair_check','result'])
g.node('merge','variable-aggregator','合并候选',3300,200,{'variables':[['check','result'],['repair_check','result']],'output_type':'object'})
# Return a proposal; the studio's before/after confirmation is the sole human acceptance step.
g.code('proposal','返回待确认修改',3600,200,{'result':['merge','output']},{'result':'object'},"def main(result):\n    result.update(status='revision_proposed',media_generation_started=False)\n    return {'result':result}")
g.end('proposal_end','交工作室比较前后差异',3900,200,['proposal','result'])
g.nodes[-1]['data']['outputs'][0]['variable']='result'
for a,b in [('start','intake'),('intake','input_gate'),('director','continuity'),('continuity','check'),('check','quality_gate'),('repair','recheck'),('recheck','repair_check'),('repair_check','repair_gate'),('merge','proposal'),('proposal','proposal_end')]:g.edge(a,b)
for a,b,h in [('input_gate','director','true'),('input_gate','input_end','false'),('quality_gate','merge','true'),('quality_gate','repair','false'),('repair_gate','merge','true'),('repair_gate','blocked_end','false')]:g.edge(a,b,h)
for n in g.nodes:
    if n['data']['type']=='llm':n['data']['retry_config']={'retry_enabled':False,'max_retries':0,'retry_interval':1000}
g.write('shot-revision.yml','Luma · 单镜修改')
path=__import__('pathlib').Path(__file__).parent/'production/shot-revision.yml'
data=json.loads(path.read_text());data['version']='0.7.0';data['app']['description']='仅修订指定镜头，独立文字复审、一次返工。返回修改建议，由流幕展示前后差异后确认应用，不生成图片或视频。'
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print('Single-shot revision:',len(g.nodes),'nodes; cloud publication pending')
