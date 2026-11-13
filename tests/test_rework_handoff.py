import copy,json,unittest
from unittest.mock import patch
from luma import studio, production, preparation, assembly
import test_studio, test_assembly

class ReworkHandoffTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot
    setup_parts=test_assembly.AssemblyTests.setup_parts
    bind=test_assembly.AssemblyTests.bind
    queue=test_assembly.AssemblyTests.queue
    job=test_assembly.AssemblyTests.job

    def revise(self,**fields):
        s=self.p['shots'][0];snap=production.scope(self.p,s['episode_id'],'s1','本地模拟修改结果，不运行模型')
        incoming={'description':s['description'],'duration':s['duration'],'asset_ids':s['asset_ids'],**fields}
        jid=studio.uid();result={'status':'revision_proposed','target_shot_id':'s1','source_revision':self.p['revision'],'shots':[incoming]}
        with studio.connect() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,self.p['id'],'revision','succeeded',json.dumps({'snapshot':snap,'revision_preview_required':True}),json.dumps({'result':result}),None,0,0,jid))
        before=studio.project(self.p['id']);preview=studio.revision_preview(self.p['id'],jid,self.p['revision']);self.assertEqual(before,studio.project(self.p['id']))
        self.p=studio.apply_job(self.p['id'],jid,self.p['revision'],preview_digest=preview['digest']);return preview

    def reconfirm(self):
        o=studio.open_preparation(self.p['id'],'s1');self.p=studio.save_preparation(self.p['id'],'s1',self.p['revision'],o['plan'],o['basis'])['project']

    def approve(self):
        self.p['shots'][0].update(approved=True,needs_review=False);self.p=studio.save(self.p,self.p['revision'])

    def assemble_select(self,nonce):
        jid=self.queue(nonce);studio.work_once();j=self.job(jid);self.assertEqual(j['state'],'succeeded',j['error']);self.p=studio.project(self.p['id']);tid=json.loads(j['result'])['take_id'];self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'select_take','shot_id':'s1','take_id':tid});return jid

    def export(self,nonce):
        jid=studio.enqueue(self.p['id'],'export',{},nonce);studio.work_once();j=self.job(jid);self.assertEqual(j['state'],'succeeded',j['error']);return json.loads(j['result'])

    def test_real_rework_reconfirm_reuse_reassemble_review_and_export_chain(self):
        self.setup_parts();studio.set_spending(0)
        with patch.object(studio.Dify,'run',side_effect=AssertionError('no model')):
            self.assemble_select('before');self.approve();old=self.export('before');old_bytes=studio.media_path(old['file']).read_bytes();takes=copy.deepcopy(self.p['shots'][0]['takes']);old_render=old['delivery_basis']
            preview=self.revise(framing='近景')
            self.assertTrue(preview['effects']);self.assertEqual(takes,self.p['shots'][0]['takes']);self.assertFalse(self.p['shots'][0]['approved'])
            f=production.readiness(self.p,self.p['episodes'][0]['id']);self.assertFalse(f['can_export']);self.assertEqual(f['delivery_basis'],old_render);self.assertNotEqual(f['review_basis'],old['review_basis'])
            with self.assertRaisesRegex(ValueError,'制作准备'):self.approve()
            self.p=studio.project(self.p['id']);self.reconfirm()
            with self.assertRaisesRegex(ValueError,'片段选用'):self.queue('must-block')
            with self.assertRaisesRegex(ValueError,'明确确认'):self.bind(self.choices)
            self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_segment_sources','shot_id':'s1','sources':self.choices,'acknowledge_stale':True})
            self.assemble_select('after');self.approve();new=self.export('after');current=production.readiness(self.p,self.p['episodes'][0]['id'])
            self.assertEqual(new['review_basis'],current['review_basis']);self.assertNotEqual(old['review_basis'],new['review_basis']);self.assertEqual(studio.media_path(old['file']).read_bytes(),old_bytes);self.assertEqual(studio.spending(),{'remaining':0,'used':0})

    def test_plain_dialogue_revision_unselects_old_full_audio_without_deleting_it(self):
        self.setup_parts();s=self.p['shots'][0];s['dialogue']='旧台词';a=production.add_take(s,'audio','part0.mp4');production.select_take(s,a['id']);self.p=studio.save(self.p,self.p['revision']);takes=copy.deepcopy(self.p['shots'][0]['takes'])
        preview=self.revise(dialogue='新台词');s=self.p['shots'][0];self.assertNotIn('audio',s);self.assertNotIn('audio',s['selected_takes']);self.assertEqual(takes,s['takes']);self.assertTrue(any('音轨' in x for x in preview['effects']))

    def test_framing_only_revision_does_not_remove_unchanged_audio(self):
        self.setup_parts();s=self.p['shots'][0];a=production.add_take(s,'audio','part0.mp4');production.select_take(s,a['id']);self.p=studio.save(self.p,self.p['revision']);self.revise(framing='近景');self.assertEqual(self.p['shots'][0]['audio'],'part0.mp4')

    def test_generated_partial_reuse_requires_explicit_ack_after_rework(self):
        self.setup_parts();s=self.p['shots'][0];seg=s['preparation']['segments'][0];t=production.add_take(s,'video','part0.mp4','generated','dify');t['generation_segment']={'shot_id':'s1',**{k:seg[k] for k in ('id','start','end')}};self.p=studio.save(self.p,self.p['revision']);self.choices[seg['id']]['take_id']=t['id'];self.bind(self.choices)
        self.revise(framing='近景');self.reconfirm()
        with self.assertRaisesRegex(ValueError,'明确确认'):self.bind(self.choices)
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_segment_sources','shot_id':'s1','sources':self.choices,'acknowledge_stale':True})
        self.assertEqual(len(assembly.source_plan(self.p,'s1',studio.media_path,studio.probe_media)['sources']),2)

    def test_duration_revision_can_apply_without_losing_historical_full_take(self):
        self.setup_parts();s=self.p['shots'][0];t=production.add_take(s,'video','part0.mp4','old complete','dify');t['generation_segment']={'id':'whole','shot_id':'s1','start':0,'end':2};production.select_take(s,t['id']);self.p=studio.save(self.p,self.p['revision'])
        self.revise(duration=3);s=self.p['shots'][0];self.assertEqual(s['duration'],3);self.assertNotIn('video',s);self.assertTrue(any(x['id']==t['id'] for x in s['takes']));o=studio.open_preparation(self.p['id'],'s1');self.assertEqual(o['narrative_duration'],3)

    def test_outfit_reconfirmation_drops_only_invalid_references_in_draft(self):
        self.setup_parts();studio.ffmpeg(['-f','lavfi','-i','color=c=white:size=160x90','-frames:v','1',str(studio.MEDIA/'old-look.png')])
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'character_look','asset_id':'hero','outfit':'旧服装','views':{'front':'old-look.png'}})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_current','shot_id':'s1'})
        o=studio.open_preparation(self.p['id'],'s1');plan=o['plan'];ref=next(r for r in o['references'] if r['file']=='old-look.png')
        for segment in plan['segments']:segment['references']=[{'reference_id':ref['reference_id'],'role':'reference_image'}]
        self.p=studio.save_preparation(self.p['id'],'s1',self.p['revision'],plan,o['basis'])['project']
        # New outfit must not silently acquire old outfit images.
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'character_look','asset_id':'hero','outfit':'新服装'})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_current','shot_id':'s1'});stored=copy.deepcopy(self.p['shots'][0]['preparation']);o=studio.open_preparation(self.p['id'],'s1')
        self.assertTrue(o['requires_reconfirmation']);self.assertTrue(stored['segments'][0]['references']);self.assertFalse(o['plan']['segments'][0]['references']);self.assertNotEqual(stored['character_versions'],o['plan']['character_versions']);self.assertEqual(studio.project(self.p['id'])['shots'][0]['preparation'],stored)
        self.p=studio.save_preparation(self.p['id'],'s1',self.p['revision'],o['plan'],o['basis'])['project'];self.assertIsNone(preparation.current_issue(self.p,self.p['shots'][0]))

    def test_pending_assembly_is_blocked_after_revision_without_spend(self):
        self.setup_parts();studio.set_spending(0);jid=self.queue('pending');self.revise(framing='近景');studio.work_once();self.assertEqual(self.job(jid)['state'],'failed');self.assertEqual(studio.spending()['used'],0)

    def test_pending_export_finishes_as_historical_not_current_after_revision(self):
        self.setup_parts();self.assemble_select('before');self.approve();jid=studio.enqueue(self.p['id'],'export',{},'pending');self.revise(framing='近景');studio.work_once();j=self.job(jid);self.assertEqual(j['state'],'succeeded',j['error']);self.assertNotEqual(json.loads(j['result'])['review_basis'],production.readiness(self.p,self.p['episodes'][0]['id'])['review_basis'])

    def test_binding_audio_to_unchanged_lines_does_not_stale_visual_preparation(self):
        self.setup_parts();self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'set_lines','shot_id':'s1','lines':[{'id':'l1','text':'原台词'}]});self.reconfirm()
        before=preparation.basis(self.p['shots'][0]);snap=production.scope(self.p,self.p['episodes'][0]['id'],'s1');media_basis=production.take_basis(self.p['shots'][0])
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'add_take','shot_id':'s1','kind':'audio','file':'part0.mp4'})
        take=self.p['shots'][0]['takes'][-1];self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_line_audio','shot_id':'s1','line_id':'l1','take_id':take['id'],'start':.2})
        self.assertEqual(preparation.basis(self.p['shots'][0]),before);self.assertEqual(production.take_basis(self.p['shots'][0]),media_basis);self.assertTrue(production.fresh(self.p,snap));self.assertIsNone(preparation.current_issue(self.p,self.p['shots'][0]))

    def test_generic_save_cannot_remove_preparation_to_bypass_rework_review(self):
        self.setup_parts();self.revise(framing='近景');self.p['shots'][0].pop('preparation');self.p['shots'][0].update(approved=True,needs_review=False)
        with self.assertRaisesRegex(ValueError,'不能直接移除'):studio.save(self.p,self.p['revision'])

    def test_generic_save_cannot_forge_segment_reconfirmation(self):
        self.setup_parts();self.revise(framing='近景');self.reconfirm()
        for choice in self.p['shots'][0]['segment_sources'].values():choice['basis']=production.take_basis(self.p['shots'][0])
        with self.assertRaisesRegex(ValueError,'不能直接改写'):studio.save(self.p,self.p['revision'])

if __name__=='__main__':unittest.main()
