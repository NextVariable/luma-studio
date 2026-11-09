import unittest,json,uuid
from pathlib import Path
import production
from drama_import import convert
from test_drama_import import bundle

class WorkflowTests(unittest.TestCase):
 def setUp(self):
  d=json.loads(Path('workflows/production/director-production.yml').read_text())
  self.graph=d['workflow']['graph'];self.nodes={n['id']:n for n in self.graph['nodes']}
 def run_code(self,id,**kwargs):
  ns={};exec(self.nodes[id]['data']['code'],ns);return ns['main'](**kwargs)
 def test_graph_edges_and_parents_resolve(self):
  for e in self.graph['edges']:
   self.assertIn(e['source'],self.nodes);self.assertIn(e['target'],self.nodes)
  for n in self.nodes.values():
   if 'parentId' in n:self.assertEqual(self.nodes[n['parentId']]['data']['type'],'iteration')
 def test_end_output_names_are_globally_unique(self):
  names=[o['variable'] for n in self.nodes.values() if n['data']['type']=='end' for o in n['data']['outputs']]
  self.assertEqual(len(names),len(set(names)))
 def test_all_embedded_code_compiles(self):
  for n in self.nodes.values():
   if n['data']['type']=='code':compile(n['data']['code'],n['id'],'exec')
 def test_intake_blocks_bad_input_without_llm(self):
  self.assertEqual(self.run_code('intake',context='not json')['ok'],0)
  self.assertEqual(self.run_code('intake',context=json.dumps({'script':'a','target_seconds':90}))['ok'],0)
 def test_scene_evidence_must_be_from_source(self):
  r=self.run_code('scene_check',text=json.dumps({'scenes':[{'name':'码头','source_quote':'伪造原文','characters':[]}]}),project={'script':'雨夜码头'})
  self.assertEqual(r['ok'],0)
 def test_unknown_asset_forces_repair(self):
  s={'description':'站在雨中','duration':5,'asset_ids':['fake'],'framing':'近景','camera':'固定','dialogue':''}
  r=self.run_code('shot_check',plan=json.dumps({'shots':[s]}),review='{"passed":true,"issues":[]}',project={'assets':[]})
  self.assertEqual(r['ok'],0)
 def test_overlong_shot_reports_actionable_repair_reason(self):
  shot={'description':'走向渡轮','duration':16,'asset_ids':[],'framing':'远景','camera':'固定','dialogue':''}
  for node in ('shot_check','repair_check'):
   r=self.run_code(node,plan=json.dumps({'shots':[shot]}),review='{"passed":true,"issues":[]}',project={})
   self.assertEqual(r['ok'],0)
   self.assertIn('镜头 1',r['issues'][0])
   self.assertIn('1–15',r['issues'][0])
 def test_failed_repair_cannot_approve(self):
  r=self.run_code('assembly',results=[{'scene':{'scene_key':'s1'},'passed':False,'shots':[{'duration':40}],'issues':['衣服不符']}],project={'revision':7})
  self.assertEqual(r['ok'],0);self.assertEqual(r['result']['status'],'blocked');self.assertFalse(r['result']['media_generation_started'])
 def test_valid_plan_waits_for_director(self):
  r=self.run_code('assembly',results=[{'scene':{'scene_key':'s1'},'passed':True,'shots':[{'duration':40}],'issues':[]}],project={'revision':7})
  self.assertEqual(r['result']['status'],'requires_review');self.assertEqual(r['result']['source_revision'],7)
 def test_missing_assets_cannot_pass_readiness(self):
  shot={'description':'站在雨中','duration':10,'asset_ids':[],'framing':'近景','camera':'固定','dialogue':''}
  r=self.run_code('shot_check',plan=json.dumps({'shots':[shot],'missing_assets':['主角参考资产']}),review='{"passed":true,"issues":[]}',project={'assets':[]})
  self.assertEqual(r['ok'],0)
  self.assertEqual(r['candidate']['missing_assets'],['主角参考资产'])
 def test_malformed_shot_is_blocked_without_crashing_assembly(self):
  r=self.run_code('shot_check',plan='{"shots":[{"duration":"bad"}]}',review='{"passed":true,"issues":[]}',project={'assets':[]})
  final=self.run_code('assembly',results=[{'scene':{'scene_key':'s'},**r['candidate']}],project={})
  self.assertEqual(final['ok'],0)
 def test_invalid_asset_list_blocks_before_model_call(self):
  r=self.run_code('intake',context=json.dumps({'script':'剧本','assets':[{'name':'无ID'}]}))
  self.assertEqual(r['ok'],0)
 def test_human_approval_has_reject_and_timeout_routes(self):
  self.assertEqual({e['sourceHandle'] for e in self.graph['edges'] if e['source']=='director_approval'},{'approve','revise','timeout'})
 def test_llms_enforce_structured_schema_at_provider(self):
  for n in self.nodes.values():
   if n['data']['type']=='llm':
    params=n['data']['model']['completion_params']
    self.assertEqual(params.get('response_format'),'json_schema')
    schema=json.loads(params['json_schema'])
    self.assertTrue(schema['strict'])
    self.assertFalse(schema['schema']['additionalProperties'])
 def test_bad_review_json_reports_decode_failure(self):
  r=self.run_code('shot_check',plan='{"shots":[]}',review='{"passed":false,"issues":["bad "quote""]}',project={})
  self.assertIn('JSONDecodeError',r['issues'][0])
 def test_scene_budget_is_set_by_code(self):
  scenes=[{'name':'码头','source_quote':'雨夜码头','characters':[]},{'name':'船','source_quote':'登船','characters':[]}]
  r=self.run_code('scene_check',text=json.dumps({'scenes':scenes}),project={'script':'雨夜码头，登船','target_seconds':40})
  self.assertEqual([x['target_seconds'] for x in r['scenes']],[20,20])
 def test_per_scene_budget_violation_is_not_accepted(self):
  shot={'description':'雨夜','duration':10,'asset_ids':[],'framing':'中景','camera':'固定','dialogue':''}
  r=self.run_code('shot_check',plan=json.dumps({'shots':[shot]*4,'missing_assets':[]}),review='{"passed":true,"issues":[]}',project={},scene={'target_seconds':20})
  self.assertEqual(r['ok'],0)
 def test_existing_asset_id_is_not_reported_missing(self):
  shot={'description':'雨夜','duration':10,'asset_ids':['hero'],'framing':'中景','camera':'固定','dialogue':''}
  r=self.run_code('shot_check',plan=json.dumps({'shots':[shot],'missing_assets':['hero']}),review='{"passed":true,"issues":[]}',project={'assets':[{'id':'hero'}]})
  self.assertEqual(r['ok'],1)
 def test_imported_director_output_is_adoptable_at_source_duration(self):
  p=production.normalize(convert(bundle())['project'])
  p['revision']=1
  p['episodes'][0]['creative_spec']['screenplay']['targetSec']=120
  project=production.scope(p,'EP001')
  intake=self.run_code('intake',context=json.dumps(project))
  self.assertEqual(intake['ok'],1,intake['issues'])
  project=intake['project']
  scene={'name':'站台','source_quote':'明天见','characters':['旅人'],'sceneId':'EP001-SC1'}
  checked=self.run_code('scene_check',text=json.dumps({'scenes':[scene]}),project=project)
  self.assertEqual(checked['ok'],1,checked['issues'])
  scene=checked['scenes'][0]
  shot={'description':'旅人收好信','duration':15,'asset_ids':['hero','station','letter'],
        'framing':'近景','camera':'固定','dialogue':'明天见'}
  spec={'shotId':None,'narrativePurpose':'告别','visualSubject':'hero','locationId':'station','propIds':['letter'],
        'dialogue':[{'who':'hero','text':'明天见'}]}
  proposal={'shots':[shot]*8}
  review='{"passed":true,"issues":[]}'
  for node in ('shot_check','repair_check'):
   plain=self.run_code(node,plan=json.dumps(proposal),review=review,project=project,scene=scene)
   self.assertEqual(plain['ok'],0)
   self.assertIn('缺少创作规格',plain['issues'][0])
   rich=self.run_code(node,plan=json.dumps({'shots':[{**shot,'creative_spec':spec}]*8}),review=review,project=project,scene=scene)
   self.assertEqual(rich['ok'],1,rich['issues'])
   result=self.run_code('assembly',results=[{'scene':scene,**rich['candidate']}],project=project)
   self.assertEqual(result['ok'],1,result['result']['issues'])
   proposed=result['result']['shots']
   self.assertEqual(result['result']['seconds'],120)
   self.assertIsNone(production.plan_adoption(p,'EP001',proposed,'replace')['blocked'])
   self.assertEqual(proposed[0]['lines'][0]['speaker_asset_id'],'hero')
   self.assertEqual(proposed[0]['creative_spec']['action'],shot['description'])
   self.assertEqual(len({s['creative_spec']['shotId'] for s in proposed}),8)
 def test_known_scene_cannot_be_omitted_or_renamed(self):
  p=production.normalize(convert(bundle())['project'])
  project=production.scope(p,'EP001')
  scene={'name':'站台','source_quote':'明天见','characters':[],'sceneId':'invented'}
  self.assertEqual(self.run_code('scene_check',text=json.dumps({'scenes':[scene]}),project=project)['ok'],0)
 def test_human_delivery_ids_are_runtime_valid_uuids(self):
  for method in self.nodes['director_approval']['data']['delivery_methods']:
   self.assertEqual(str(uuid.UUID(method['id'])),method['id'])
 def test_iteration_concurrency_is_bounded(self):
  self.assertEqual(self.nodes['scene_iteration']['data']['parallel_nums'],2)
 def test_repair_has_no_unbounded_cycle(self):
  adj={n:[] for n in self.nodes}
  for e in self.graph['edges']:adj[e['source']].append(e['target'])
  def visit(n,path):
   self.assertNotIn(n,path)
   for nxt in adj[n]:visit(nxt,path+[n])
  visit('start',[]);visit('scene_start',[])

if __name__=='__main__':unittest.main()
