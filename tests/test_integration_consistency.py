import copy,json,os,unittest
from unittest.mock import patch
import studio,production,providers,test_studio,test_adoption

class ConsistencyTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot
    plan_job=test_adoption.AdoptionModeTests.plan_job
    episode=test_adoption.AdoptionModeTests.episode

    def with_lines(self):
        self.add_shot()
        self.p['shots'][0]['lines']=[{'id':'line1','speaker_asset_id':'hero','text':'旧对白'}]
        self.p=studio.save(self.p,self.p['revision'])

    def test_merge_new_plain_dialogue_is_not_overwritten_by_old_lines(self):
        self.with_lines()
        jid=self.plan_job([{'description':'新画面','duration':2,'asset_ids':['hero'],'dialogue':'新对白'}])
        result=studio.apply_job(self.p['id'],jid,self.p['revision'],'merge')['shots'][0]
        self.assertEqual(result['dialogue'],'新对白')
        self.assertNotIn('lines',result)

    def test_revision_new_plain_dialogue_switches_to_text(self):
        self.with_lines();snap=production.scope(self.p,self.episode(),'s1','修改对白')
        with studio.connect() as c:
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('rev',self.p['id'],'revision','succeeded',json.dumps({'snapshot':snap}),json.dumps({'result':{'shots':[{'description':'修订画面','duration':2,'asset_ids':['hero'],'dialogue':'修订对白'}]}}),None,0,0,'revision'))
        result=studio.apply_job(self.p['id'],'rev',self.p['revision'])['shots'][0]
        self.assertEqual(result['dialogue'],'修订对白');self.assertNotIn('lines',result)

    def test_unchanged_plain_dialogue_preserves_speaker_structure(self):
        self.with_lines();before=copy.deepcopy(self.p['shots'][0])
        production.apply_plan_text(before,{'dialogue':before['dialogue']},production.PLAN_TEXT_FIELDS)
        self.assertEqual(before['lines'][0]['speaker_asset_id'],'hero')

    def test_plain_write_cannot_silently_disappear_when_lines_unchanged(self):
        self.with_lines();self.p['shots'][0]['dialogue']='新的纯文本'
        with self.assertRaisesRegex(ValueError,'逐句'):studio.save(self.p,self.p['revision'])

    def test_old_mismatched_clip_normalizes_selected_visual(self):
        self.add_shot();s=self.p['shots'][0]
        for n in ('a.jpg','b.jpg'):(studio.MEDIA/n).write_bytes(b'fixture')
        a=production.add_take(s,'image','a.jpg');b=production.add_take(s,'image','b.jpg');production.select_take(s,a['id'])
        s['clip']={'source_take_id':b['id'],'trim_start':0,'trim_end':None}
        production.normalize(self.p)
        self.assertEqual(s['image'],production.clip_of(s)['file'])
        self.assertEqual(s['selected_takes']['image'],b['id'])

    def test_cut_from_candidate_is_enough_to_review_and_deliver(self):
        self.add_shot();s=self.p['shots'][0];(studio.MEDIA/'b.jpg').write_bytes(b'fixture')
        b=production.add_take(s,'image','b.jpg');production.set_clip(s,b['id'])
        s.update(approved=True,needs_review=False)
        self.assertTrue(production.readiness(self.p,self.episode())['can_export'])

    def test_cut_range_change_requires_review_even_in_general_save(self):
        self.add_shot();s=self.p['shots'][0];(studio.MEDIA/'b.jpg').write_bytes(b'fixture')
        b=production.add_take(s,'image','b.jpg');production.set_clip(s,b['id'])
        self.p=studio.save(self.p,self.p['revision']);self.p['shots'][0].update(approved=True,needs_review=False)
        self.p=studio.save(self.p,self.p['revision']);self.p['shots'][0]['clip']['trim_end']=1
        self.p=studio.save(self.p,self.p['revision']);self.assertFalse(self.p['shots'][0]['approved'])

    def test_endpoint_identity_covers_scheme_port_path_and_query(self):
        with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'dummy-audit','DIFY_BASE_URL':'https://example.test:443/a/v1'}):
            ident=providers.provider_identity('shots')
            for base in ('http://example.test:443/a/v1','https://example.test:8443/a/v1','https://example.test:443/b/v1','https://example.test:443/a/v1?tenant=other'):
                os.environ['DIFY_BASE_URL']=base
                with self.assertRaisesRegex(ValueError,'地址'):studio.check_provider({'provider':ident},'shots')
            os.environ['DIFY_BASE_URL']='https://example.test:443/a/v1/'
            studio.check_provider({'provider':ident},'shots')

    def test_subtitle_structure_changes_delivery_identity_even_with_identical_plain_text(self):
        self.with_lines();s=self.p['shots'][0]
        s['lines']=[{'id':'a','speaker_asset_id':None,'text':'第一句\n第二句'}]
        production.normalize(self.p);before=production.delivery_basis(self.p)
        s['lines']=[{'id':'a','speaker_asset_id':None,'text':'第一句'},{'id':'b','speaker_asset_id':None,'text':'第二句'}]
        production.normalize(self.p)
        self.assertNotEqual(before,production.delivery_basis(self.p))
