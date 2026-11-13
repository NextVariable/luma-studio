import io,json,unittest
from pathlib import Path
from luma.providers import Dify

class RevisionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.graph=json.loads(Path('workflows/production/shot-revision.yml').read_text())['workflow']['graph']
        self.nodes={n['id']:n for n in self.graph['nodes']}
    def run_code(self,node,**args):
        ns={};exec(self.nodes[node]['data']['code'],ns);return ns['main'](**args)
    def test_graph_compiles_and_human_acceptance_stays_in_studio(self):
        self.assertNotIn('human-input',{n['data']['type'] for n in self.nodes.values()})
        for e in self.graph['edges']:
            self.assertIn(e['source'],self.nodes);self.assertIn(e['target'],self.nodes)
        reachable={'start'}
        while True:
            expanded=reachable|{e['target'] for e in self.graph['edges'] if e['source'] in reachable}
            if expanded==reachable:break
            reachable=expanded
        self.assertEqual(reachable,set(self.nodes), 'Every node must be reachable from start')
        for n in self.nodes.values():
            if n['data']['type']=='code':compile(n['data']['code'],n['id'],'exec')
            if n['data']['type']=='llm':self.assertFalse(n['data']['retry_config']['retry_enabled'])
        self.assertEqual(self.nodes['proposal_end']['data']['outputs'][0]['variable'],'result')
    def test_proposal_can_be_decoded_without_human_approval_event(self):
        proposal=self.run_code('proposal',result={'shots':[{'description':'近景','duration':5,'asset_ids':[]}],'source_revision':2,'target_shot_id':'s1'})['result']
        event={'event':'workflow_finished','data':{'status':'succeeded','outputs':{'result':proposal}}}
        result=Dify().consume(io.BytesIO(('data: '+json.dumps(event)+'\n\n').encode()),'revision',{'revision':2,'target_shot_id':'s1'})
        self.assertEqual(result['state'],'succeeded');self.assertEqual(result['result']['status'],'revision_proposed')
        self.assertFalse(result['result']['media_generation_started'])
    def test_multiple_shots_and_unapproved_text_review_are_blocked(self):
        shot={'description':'近景','duration':5,'asset_ids':[]}
        for shots,review in (([shot,shot],True),([shot],'yes')):
            result=self.run_code('check',text=json.dumps({'shots':shots}),review=json.dumps({'passed':review}),project={'assets':[],'revision':2,'target_shot_id':'s1'})
            self.assertEqual(result['ok'],0)

    def test_null_creative_spec_from_a_plain_project_is_accepted(self):
        # The published schema asks for creative_spec on every shot and uses null for plain projects.
        from luma.contracts import validate
        shot={'description':'近景','duration':5,'asset_ids':[],'creative_spec':None}
        self.assertEqual(validate('revision',{'shots':[shot]})['shots'][0]['creative_spec'],None)
        with self.assertRaises(ValueError):
            validate('revision',{'shots':[{**shot,'creative_spec':'text'}]})
