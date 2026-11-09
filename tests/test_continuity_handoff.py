import copy,json,unittest
from unittest.mock import patch
import studio,production,preparation,creative,continuity,assembly,test_studio
import test_creative_acceptance as acceptance

class ContinuityHandoffTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    imported=acceptance.CreativeAcceptanceTests.imported
    add_third_episode=acceptance.CreativeAcceptanceTests.add_third_episode

    def fixture(self):
        self.imported();self.add_third_episode();root=self.p['shots'][0]
        a=copy.deepcopy(root);a['id']='EP001-S2';a['creative_spec']['shotId']=a['id'];a['continuity_from']=root['id']
        b=copy.deepcopy(root);b['id']='EP001-S3';b['creative_spec']['shotId']=b['id'];b['continuity_from']=a['id']
        self.p['shots'][1:1]=[a,b];self.p=studio.save(self.p,self.p['revision'])
        for eid in ('EP002','EP003'):
            if creative.continuity_status(self.p,eid)['requires_confirmation']:self.confirm(eid)
        studio.ffmpeg(['-f','lavfi','-i','color=c=blue:size=160x90','-frames:v','1',str(studio.MEDIA/'blue.png')])
        studio.ffmpeg(['-f','lavfi','-i','color=c=red:size=160x90','-frames:v','1',str(studio.MEDIA/'red.png')])
        for s in self.p['shots']:production.select_take(s,production.add_take(s,'image','blue.png')['id'])
        self.p=studio.save(self.p,self.p['revision'])
        for s in self.p['shots']:s['preparation']=preparation.seed(self.p,s['id'],'image')
        self.p=studio.save(self.p,self.p['revision'])
        for s in self.p['shots']:s.update(approved=True,needs_review=False)
        self.p=studio.save(self.p,self.p['revision'])

    def shot(self,sid):return next(s for s in self.p['shots'] if s['id']==sid)

    def save(self):self.p=studio.save(self.p,self.p['revision'])

    def confirm(self,eid,resolution='keep'):
        o=studio.continuity_preview(self.p['id'],eid);self.p=studio.confirm_continuity(self.p['id'],eid,self.p['revision'],o['digest'],resolution,'已检查本集设定，保留原状态')

    def reprepare(self,sid):
        o=studio.open_preparation(self.p['id'],sid);self.p=studio.save_preparation(self.p['id'],sid,self.p['revision'],o['plan'],o['basis'])['project']

    def test_visual_replacement_invalidates_transitive_preparation_not_just_direct_child(self):
        self.fixture();old=[copy.deepcopy(self.shot(s)['preparation']) for s in ('EP001-S2','EP001-S3')]
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'add_take','shot_id':'EP001-S1','kind':'image','file':'red.png'})
        tid=self.shot('EP001-S1')['takes'][-1]['id'];self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'select_take','shot_id':'EP001-S1','take_id':tid})
        for sid,plan in zip(('EP001-S2','EP001-S3'),old):
            s=self.shot(sid);self.assertEqual(s['preparation'],plan);self.assertTrue(s['needs_review']);self.assertIsNotNone(preparation.current_issue(self.p,s));self.assertEqual(s['image'],'blue.png')
        self.assertFalse(creative.continuity_status(self.p,'EP002')['requires_confirmation'])

    def test_story_change_invalidates_later_preparations_even_without_visual_link(self):
        self.fixture();self.shot('EP001-S3').pop('continuity_from');self.save();self.reprepare('EP001-S3');self.shot('EP001-S1')['description']='旅人把信交给陌生人';self.save()
        self.assertIsNotNone(preparation.current_issue(self.p,self.shot('EP001-S3')));self.assertTrue(creative.continuity_status(self.p,'EP002')['requires_confirmation']);self.assertTrue(creative.continuity_status(self.p,'EP003')['requires_confirmation'])

    def test_outfit_rebind_propagates_but_never_auto_replaces_downstream_pins(self):
        self.fixture();before=self.shot('EP002-S1')['asset_bindings']['hero']
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'character_look','asset_id':'hero','outfit':'白色外套'})
        self.assertFalse(creative.continuity_status(self.p,'EP002')['requires_confirmation'])
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_asset_version','shot_id':'EP001-S1','asset_id':'hero','version_id':self.p['assets'][0]['selected_version']})
        self.assertTrue(creative.continuity_status(self.p,'EP002')['requires_confirmation']);self.assertTrue(creative.continuity_status(self.p,'EP003')['requires_confirmation']);self.assertEqual(self.shot('EP002-S1')['asset_bindings']['hero'],before)
        o=studio.continuity_preview(self.p['id'],'EP002');self.assertNotEqual(o['before_carry'],o['after_carry'])

    def test_subject_state_change_is_seen_across_episodes(self):
        self.fixture();self.shot('EP001-S1')['creative_spec']['subjectState']='右手受伤';self.save();self.assertTrue(creative.continuity_status(self.p,'EP002')['requires_confirmation'])

    def test_confirming_episode_does_not_silently_refresh_preparations_or_sources(self):
        self.fixture();sid='EP002-S1';s=self.shot(sid);seg=s['preparation']['segments'][0]['id'];take=s['takes'][0]['id']
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_segment_sources','shot_id':sid,'sources':{seg:{'take_id':take,'trim_start':0}}});before=copy.deepcopy(self.shot(sid)['segment_sources'])
        self.shot('EP001-S1')['creative_spec']['subjectState']='受伤';self.save()
        with self.assertRaisesRegex(ValueError,'跨集状态'):self.reprepare(sid)
        self.confirm('EP002');self.confirm('EP003');self.assertIsNotNone(preparation.current_issue(self.p,self.shot(sid)));self.assertEqual(self.shot(sid)['segment_sources'],before)
        self.reprepare(sid)
        with self.assertRaisesRegex(ValueError,'片段选用'):assembly.source_plan(self.p,sid,studio.media_path,studio.probe_media)
        with self.assertRaisesRegex(ValueError,'明确确认'):studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_segment_sources','shot_id':sid,'sources':{seg:{'take_id':take,'trim_start':0}}})

    def test_cannot_approve_stale_dependent_even_if_locked_was_previously_approved(self):
        self.fixture();self.shot('EP001-S3')['locked']=True;self.save();self.shot('EP001-S1')['description']='信已交出';self.save();s=self.shot('EP001-S3');self.assertTrue(s['needs_review']);self.assertTrue(s['locked']);s.update(approved=True,needs_review=False)
        with self.assertRaises(ValueError):self.save()

    def test_reordering_changes_predecessor_basis(self):
        self.fixture();sid='EP001-S2';before=continuity.basis(self.p,self.shot(sid));self.p['shots'][0],self.p['shots'][2]=self.p['shots'][2],self.p['shots'][0];self.save();self.assertNotEqual(before,continuity.basis(self.p,self.shot(sid)));self.assertIsNotNone(preparation.current_issue(self.p,self.shot(sid)))

    def test_unused_candidate_or_asset_current_version_does_not_invalidate_pinned_preparations(self):
        self.fixture();before=copy.deepcopy(self.shot('EP001-S3')['preparation']);basis=continuity.basis(self.p,self.shot('EP001-S3'))
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'add_take','shot_id':'EP001-S1','kind':'image','file':'red.png'})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'character_look','asset_id':'hero','outfit':'未绑定新造型'})
        self.assertEqual(continuity.basis(self.p,self.shot('EP001-S3')),basis);self.assertIsNone(preparation.current_issue(self.p,self.shot('EP001-S3')));self.assertEqual(self.shot('EP001-S3')['preparation'],before)

    def test_pure_framing_change_only_affects_explicit_visual_chain_not_cross_episode_story(self):
        self.fixture();self.shot('EP001-S1')['framing']='近景';self.save();self.assertIsNotNone(preparation.current_issue(self.p,self.shot('EP001-S3')));self.assertFalse(creative.continuity_status(self.p,'EP002')['requires_confirmation']);self.assertIsNone(preparation.current_issue(self.p,self.shot('EP002-S1')))

    def test_generic_state_link_forgery_is_rejected(self):
        self.fixture();self.shot('EP001-S1')['creative_spec']['subjectState']='受伤';self.save();self.p['episodes'][1]['creative_spec']['state_link']['carry_digest']=creative.continuity_status(self.p,'EP002')['carry_digest']
        with self.assertRaises(ValueError):self.save()

    def test_queued_assembly_rechecks_transitive_source_and_costs_nothing(self):
        self.fixture();sid='EP001-S3';s=self.shot(sid);seg=s['preparation']['segments'][0]['id'];self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_segment_sources','shot_id':sid,'sources':{seg:{'take_id':s['takes'][0]['id'],'trim_start':0}}});studio.set_spending(0)
        jid=studio.enqueue(self.p['id'],'assemble',{'shot_id':sid},'chain');self.shot('EP001-S1')['description']='信已不在';self.save()
        with patch.object(studio.Dify,'run',side_effect=AssertionError('no model')):studio.work_once()
        with studio.connect() as c:j=c.execute('select state from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(j['state'],'failed');self.assertEqual(studio.spending()['used'],0)

    def test_reconfirming_child_cannot_skip_unreviewed_visual_parent(self):
        self.fixture();self.shot('EP001-S1')['framing']='近景';self.save();self.reprepare('EP001-S2');self.reprepare('EP001-S3')
        self.assertIn('先复核',preparation.current_issue(self.p,self.shot('EP001-S3')))
        s=self.shot('EP001-S3');s.update(approved=True,needs_review=False)
        with self.assertRaises(ValueError):self.save()

    def test_audio_arrangement_does_not_invalidate_downstream_visual_preparation(self):
        self.fixture();before=continuity.basis(self.p,self.shot('EP001-S3'));studio.ffmpeg(['-f','lavfi','-i','sine=frequency=440','-t','0.5',str(studio.MEDIA/'line.wav')])
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'add_take','shot_id':'EP001-S1','kind':'audio','file':'line.wav'})
        source=self.shot('EP001-S1');self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_line_audio','shot_id':source['id'],'line_id':source['lines'][0]['id'],'take_id':source['takes'][-1]['id'],'start':.2})
        self.assertTrue(self.shot('EP001-S1')['needs_review']);self.assertEqual(before,continuity.basis(self.p,self.shot('EP001-S3')));self.assertIsNone(preparation.current_issue(self.p,self.shot('EP001-S3')))

    def test_queued_revision_rechecks_visual_ancestry_before_spending(self):
        self.fixture();studio.set_spending(1)
        with patch.dict('os.environ',{'DIFY_REVISION_KEY':'isolated-test-only'}):
            jid=studio.enqueue(self.p['id'],'revision',{'episode_id':'EP001','shot_id':'EP001-S3','instruction':'近景'},'queued-revision')
            self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'add_take','shot_id':'EP001-S1','kind':'image','file':'red.png'})
            self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'select_take','shot_id':'EP001-S1','take_id':self.shot('EP001-S1')['takes'][-1]['id']})
            with patch.object(studio.Dify,'run') as run:studio.work_once();run.assert_not_called()
        with studio.connect() as c:j=c.execute('select state from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(j['state'],'failed');self.assertEqual(studio.spending()['used'],0)

    def test_legacy_episode_links_upgrade_without_false_pending_but_still_catch_next_rebind(self):
        self.fixture()
        for ep in self.p['episodes']:
            link=ep['creative_spec']['state_link'];link.pop('carry_digest',None);link.pop('carry_inputs',None)
        with studio.connect() as c:c.execute('update projects set body=? where id=?',(json.dumps(self.p),self.p['id']))
        self.p=studio.project(self.p['id']);self.assertFalse(creative.continuity_status(self.p,'EP002')['requires_confirmation'])
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'character_look','asset_id':'hero','outfit':'新造型'})
        self.assertFalse(creative.continuity_status(self.p,'EP002')['requires_confirmation'])
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_asset_version','shot_id':'EP001-S1','asset_id':'hero','version_id':self.p['assets'][0]['selected_version']})
        self.assertTrue(creative.continuity_status(self.p,'EP002')['requires_confirmation'])

if __name__=='__main__':unittest.main()
