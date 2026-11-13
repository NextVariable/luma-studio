"""Acceptance gates for every write path; no network or model calls."""
import copy
import json
import unittest
from unittest.mock import patch
from luma import studio
from luma import production
from luma import creative
import test_studio
from test_drama_import import bundle


class CreativeAcceptanceTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def imported(self):
        preview=studio.preview_drama_import(bundle())
        self.p=studio.apply_drama_import(preview['id'],preview['digest'])
        return self.p

    def proposal(self, shots):
        snap=production.scope(self.p,'EP001')
        result={'status':'creative_approved','source_revision':self.p['revision'],'shots':shots}
        with studio.connect() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('plan',self.p['id'],'shots','succeeded',json.dumps({'snapshot':snap}),json.dumps({'result':result}),None,0,0,'plan'))
        return 'plan'

    def incoming(self, sid='new-rich'):
        s=copy.deepcopy(self.p['shots'][0]);s['id']=sid;s['creative_spec']['shotId']=sid
        return s

    def change_end(self):
        self.p['episodes'][0]['creative_spec']['planned_end_state']['knownBy']['hero'].append('新的线索')
        self.p=studio.save(self.p,self.p['revision'])

    def test_new_shot_cannot_bypass_creative_spec(self):
        self.imported();p=copy.deepcopy(self.p)
        p['shots'].append({'id':'plain','episode_id':'EP001','description':'新增镜头','duration':2,'asset_ids':[]})
        with self.assertRaisesRegex(ValueError,'创作规格'):studio.save(p,p['revision'])
        self.assertEqual(studio.project(p['id']),self.p)

    def test_add_shot_creates_complete_spec_and_keeps_existing_work(self):
        self.imported()
        before=copy.deepcopy(self.p['shots'])
        result=studio.add_shot(self.p['id'],'EP001',self.p['revision'],{
            'scene_id':'EP001-SC1','subject_id':'hero','version_id':'coat',
            'purpose':'表现犹豫','description':'旅人停下脚步','duration':3})
        p=result['project'];s=next(s for s in p['shots'] if s['id']==result['shot_id'])
        self.assertEqual(s['creative_spec']['action'],'旅人停下脚步')
        self.assertEqual(s['creative_spec']['shotId'],s['id'])
        self.assertEqual(s['asset_bindings']['hero'],'coat')
        self.assertEqual(s['creative_spec']['sceneId'],'EP001-SC1')
        self.assertFalse(s['approved']);self.assertTrue(s['needs_review'])
        self.assertEqual(s['takes'],[]);self.assertEqual(s['dialogue'],'')
        self.assertEqual([s for s in p['shots'] if s['id']!=result['shot_id']],before)
        self.assertIn(result['shot_id'],[sid for g in p['episodes'][0]['creative_spec']['segments'] for sid in g['shot_ids']])
        with self.assertRaisesRegex(ValueError,'作品已更新'):
            studio.add_shot(p['id'],'EP001',self.p['revision'],{})

    def test_add_shot_refuses_missing_or_foreign_creative_fields_atomically(self):
        self.imported()
        fields={'scene_id':'EP001-SC1','subject_id':'hero','version_id':'coat',
                'purpose':'告别','description':'旅人挥手','duration':3}
        for patch_fields in ({'scene_id':'EP002-SC1'},{'version_id':'fake'},{'purpose':''},{'subject_id':'fake'}):
            with self.subTest(fields=patch_fields),self.assertRaises(ValueError):
                studio.add_shot(self.p['id'],'EP001',self.p['revision'],{**fields,**patch_fields})
            self.assertEqual(studio.project(self.p['id']),self.p)

    def test_creative_context_cannot_be_removed_to_bypass_rules(self):
        self.imported();p=copy.deepcopy(self.p);p.pop('creative_context')
        with self.assertRaises(ValueError):studio.save(p,p['revision'])

    def test_valid_new_shot_is_editable_and_stays_unapproved(self):
        self.imported();self.p['shots'].append(self.incoming());p=studio.save(self.p,self.p['revision'])
        self.assertEqual(p['shots'][-1]['creative_spec']['shotId'],'new-rich')
        self.assertFalse(p['shots'][-1]['approved'])

    def test_append_and_replace_refuse_plain_model_shots_in_preview_and_apply(self):
        self.imported();jid=self.proposal([{'description':'普通模型方案','duration':2,'asset_ids':[]}])
        for mode in ('append','replace'):
            preview=studio.adoption_preview(self.p['id'],jid,self.p['revision'],mode)
            self.assertTrue(preview['blocked'],mode)
            with self.assertRaises(ValueError):studio.apply_job(self.p['id'],jid,self.p['revision'],mode)
        self.assertEqual(studio.project(self.p['id']),self.p)

    def test_merge_updates_existing_text_without_dropping_rich_fields(self):
        self.imported();before=copy.deepcopy(self.p['shots'][0]);jid=self.proposal([{'description':'旅人把信收入口袋','duration':2,'framing':'近景','asset_ids':before['asset_ids']}])
        self.assertFalse(studio.adoption_preview(self.p['id'],jid,self.p['revision'],'merge')['blocked'])
        p=studio.apply_job(self.p['id'],jid,self.p['revision'],'merge');s=p['shots'][0]
        self.assertEqual(s['creative_spec']['shotSize'],'近景');self.assertEqual(s['creative_spec']['sound'],before['creative_spec']['sound'])
        self.assertEqual(s['asset_bindings'],before['asset_bindings'])

    def test_merge_cannot_add_plain_extra_shot(self):
        self.imported();plain={'description':'普通方案','duration':2,'asset_ids':self.p['shots'][0]['asset_ids']};jid=self.proposal([plain,plain])
        self.assertTrue(studio.adoption_preview(self.p['id'],jid,self.p['revision'],'merge')['blocked'])
        with self.assertRaises(ValueError):studio.apply_job(self.p['id'],jid,self.p['revision'],'merge')

    def test_replace_with_complete_spec_preserves_ids_and_rebuilds_plan_links(self):
        self.imported();shot=self.incoming('EP001-NEW');shot['creative_spec']['segmentId']='new-segment';jid=self.proposal([shot])
        self.assertFalse(studio.adoption_preview(self.p['id'],jid,self.p['revision'],'replace')['blocked'])
        p=studio.apply_job(self.p['id'],jid,self.p['revision'],'replace');s=next(s for s in p['shots'] if s['episode_id']=='EP001')
        self.assertEqual(s['id'],'EP001-NEW');self.assertEqual(s['creative_spec']['shotId'],s['id'])
        spec=p['episodes'][0]['creative_spec']
        self.assertEqual(spec['storyboard_source_status'],'historical')
        self.assertEqual(spec['segments'][0]['shot_ids'],['EP001-NEW'])
        self.assertEqual(p['shots'][-1]['id'],'EP002-S1')

    def test_bad_or_duplicate_rich_plan_is_blocked_at_preview(self):
        self.imported();s=self.incoming();s['creative_spec']['propIds']=['missing'];jid=self.proposal([s])
        self.assertTrue(studio.adoption_preview(self.p['id'],jid,self.p['revision'],'replace')['blocked'])

    def test_duplicate_rich_ids_block_append_and_replace(self):
        self.imported();s=self.incoming();jid=self.proposal([s,copy.deepcopy(s)])
        for mode in ('append','replace'):
            self.assertTrue(studio.adoption_preview(self.p['id'],jid,self.p['revision'],mode)['blocked'])

    def test_replacement_cannot_silently_change_an_existing_sources_scene(self):
        self.imported();self.p['episodes'][0]['creative_spec']['screenplay']['scenes'].append({'id':'new-scene','location':'station','beats':[]})
        self.p=studio.save(self.p,self.p['revision']);s=copy.deepcopy(self.p['shots'][0]);s['creative_spec']['sceneId']='new-scene';jid=self.proposal([s])
        self.assertTrue(studio.adoption_preview(self.p['id'],jid,self.p['revision'],'replace')['blocked'])

    def test_queued_generation_is_rechecked_before_any_spend(self):
        self.imported()
        with patch.dict('os.environ',{'DIFY_REVISION_KEY':'test-only'}):
            jid=studio.enqueue(self.p['id'],'revision',{'episode_id':'EP002','shot_id':'EP002-S1','instruction':'近景'},'queued')
            self.change_end();before=studio.spending()
            with patch.object(studio.Dify,'run') as run:studio.work_once();run.assert_not_called()
        self.assertEqual(studio.spending(),before)
        with studio.connect() as c:row=c.execute('select state,error from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(row['state'],'failed');self.assertIn('跨集状态',row['error'])

    def add_third_episode(self):
        ep=copy.deepcopy(self.p['episodes'][1]);ep=json.loads(json.dumps(ep).replace('EP002','EP003'));ep['creative_spec']['screenplay']['ep']=3
        ep['creative_spec'].pop('state_link',None);ep['creative_spec']['entry_state']=copy.deepcopy(self.p['episodes'][1]['creative_spec']['planned_end_state'])
        ep['creative_spec']['planned_end_state']={'knownBy':{'hero':['第三集状态']}}
        shot=json.loads(json.dumps(self.p['shots'][1]).replace('EP002','EP003'));shot['creative_spec']['episodeId']=3
        self.p['episodes'].append(ep);self.p['shots'].append(shot);self.p=studio.save(self.p,self.p['revision'])

    def test_state_change_propagates_through_three_episodes_and_confirms_in_order(self):
        self.imported();self.add_third_episode();self.change_end()
        self.assertTrue(creative.continuity_status(self.p,'EP002')['requires_confirmation'])
        self.assertTrue(creative.continuity_status(self.p,'EP003')['requires_confirmation'])
        preview=studio.continuity_preview(self.p['id'],'EP003')
        with self.assertRaisesRegex(ValueError,'上游'):studio.confirm_continuity(self.p['id'],'EP003',self.p['revision'],preview['digest'],'inherit','')
        preview=studio.continuity_preview(self.p['id'],'EP002')
        self.p=studio.confirm_continuity(self.p['id'],'EP002',self.p['revision'],preview['digest'],'inherit','')
        self.assertTrue(creative.continuity_status(self.p,'EP003')['requires_confirmation'])
        preview=studio.continuity_preview(self.p['id'],'EP003')
        self.p=studio.confirm_continuity(self.p['id'],'EP003',self.p['revision'],preview['digest'],'inherit','')
        self.assertFalse(creative.continuity_status(self.p,'EP003')['requires_confirmation'])

    def test_confirmation_race_requires_new_preview_and_does_not_overwrite(self):
        self.imported();self.change_end();preview=studio.continuity_preview(self.p['id'],'EP002');self.change_end()
        with self.assertRaises(ValueError):studio.confirm_continuity(self.p['id'],'EP002',self.p['revision'],preview['digest'],'inherit','')

    def test_existing_import_with_mismatched_entry_is_not_automatically_certified(self):
        b=bundle();b['files']['episode-state.json']['episodes'][0]['knownBy']['hero'].append('新版本')
        # Build a pre-upgrade stored project with an entry copied from an older state.
        from luma import drama_import
        p=drama_import.convert(b)['project'];p['episodes'][1]['creative_spec']['entry_state']={'knownBy':{'hero':['旧版本']}}
        p=studio.save(p,0)
        self.assertTrue(creative.continuity_status(p,'EP002')['requires_confirmation'])

    def test_locked_and_media_shots_still_block_whole_episode_replacement(self):
        self.imported();self.p['shots'][0]['locked']=True;self.p=studio.save(self.p,self.p['revision']);jid=self.proposal([self.incoming()])
        self.assertIn('锁定',studio.adoption_preview(self.p['id'],jid,self.p['revision'],'replace')['blocked'])

    def test_legacy_project_still_accepts_plain_new_shots(self):
        self.p['shots'].append({'id':'plain','episode_id':self.p['episodes'][0]['id'],'description':'普通镜头','duration':2,'asset_ids':[]})
        self.p=studio.save(self.p,self.p['revision']);self.assertEqual(len(self.p['shots']),1)

    def test_replace_existing_id_keeps_its_pinned_outfit_not_current_asset_version(self):
        self.imported();asset=self.p['assets'][0];v=copy.deepcopy(asset['versions'][0]);v.update(id='coat-new',outfit='红外套')
        asset['versions'].append(v);asset['selected_version']=v['id'];self.p=studio.save(self.p,self.p['revision'])
        incoming=copy.deepcopy(self.p['shots'][0]);jid=self.proposal([incoming])
        self.assertFalse(studio.adoption_preview(self.p['id'],jid,self.p['revision'],'replace')['blocked'])
        p=studio.apply_job(self.p['id'],jid,self.p['revision'],'replace')
        s=next(s for s in p['shots'] if s['episode_id']=='EP001')
        self.assertEqual(s['asset_bindings']['hero'],'coat')

    def test_omitting_server_link_cannot_clear_a_pending_state(self):
        self.imported();self.change_end();p=copy.deepcopy(self.p);p['episodes'][1]['creative_spec'].pop('state_link')
        p=studio.save(p,p['revision']);self.assertTrue(creative.continuity_status(p,'EP002')['requires_confirmation'])

    def test_legacy_bare_queued_snapshot_cannot_bypass_an_upgraded_project(self):
        self.imported()
        with patch.dict('os.environ',{'DIFY_REVISION_KEY':'test-only'}):
            jid=studio.enqueue(self.p['id'],'revision',{'episode_id':'EP001','shot_id':'EP001-S1','instruction':'近景'},'old-shape')
            with studio.connect() as c:
                payload=json.loads(c.execute('select payload from jobs where id=?',(jid,)).fetchone()[0]);snap=payload['snapshot'];snap.pop('creative_context',None)
                for ep in snap['episodes']:ep.pop('creative_spec',None)
                for shot in snap['shots']:shot.pop('creative_spec',None)
                c.execute('update jobs set payload=? where id=?',(json.dumps(payload),jid))
            before=studio.spending()
            with patch.object(studio.Dify,'run') as run:studio.work_once();run.assert_not_called()
        self.assertEqual(studio.spending(),before)
        with studio.connect() as c:row=c.execute('select state,error from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(row['state'],'failed');self.assertIn('创作规格',row['error'])

    def test_empty_model_plan_cannot_wipe_an_episode(self):
        self.imported();jid=self.proposal([])
        for mode in ('append','merge','replace'):
            self.assertTrue(studio.adoption_preview(self.p['id'],jid,self.p['revision'],mode)['blocked'])
            with self.assertRaises(ValueError):studio.apply_job(self.p['id'],jid,self.p['revision'],mode)
        self.assertEqual(studio.project(self.p['id']),self.p)

    def test_upstream_edit_marks_later_state_pending_without_overwriting_story(self):
        self.imported();before=copy.deepcopy(self.p['episodes'][1]['creative_spec']['entry_state']);self.change_end()
        status=creative.continuity_status(self.p,'EP002')
        self.assertTrue(status['requires_confirmation'])
        self.assertEqual(self.p['episodes'][1]['creative_spec']['entry_state'],before)
        self.assertFalse(production.readiness(self.p,'EP002')['can_export'])

    def test_pending_state_blocks_all_generation_before_queue_or_spend(self):
        self.imported();self.change_end();allowance=studio.spending()
        for kind in ('shots','revision','image','video','audio','export'):
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'跨集状态'):
                studio.enqueue(self.p['id'],kind,{'episode_id':'EP002','shot_id':'EP002-S1','instruction':'近景'},kind)
        self.assertEqual(studio.spending(),allowance)
        with studio.connect() as c:self.assertEqual(c.execute('select count(*) from jobs').fetchone()[0],0)

    def test_state_confirmation_requires_current_digest(self):
        self.imported();self.change_end();preview=studio.continuity_preview(self.p['id'],'EP002')
        with self.assertRaises(ValueError):studio.confirm_continuity(self.p['id'],'EP002',self.p['revision'],'wrong','inherit','')
        self.assertEqual(studio.project(self.p['id']),self.p)
        p=studio.confirm_continuity(self.p['id'],'EP002',self.p['revision'],preview['digest'],'inherit','')
        self.assertFalse(creative.continuity_status(p,'EP002')['requires_confirmation'])
        self.assertEqual(p['episodes'][1]['creative_spec']['entry_state'],p['episodes'][0]['creative_spec']['planned_end_state'])

    def test_keep_state_needs_explicit_reason_and_does_not_clear_future_changes(self):
        self.imported();self.change_end();preview=studio.continuity_preview(self.p['id'],'EP002')
        with self.assertRaises(ValueError):studio.confirm_continuity(self.p['id'],'EP002',self.p['revision'],preview['digest'],'keep','')
        self.p=studio.confirm_continuity(self.p['id'],'EP002',self.p['revision'],preview['digest'],'keep','本集保持原设定，由后续剧情处理')
        self.assertFalse(creative.continuity_status(self.p,'EP002')['requires_confirmation'])
        self.change_end();self.assertTrue(creative.continuity_status(self.p,'EP002')['requires_confirmation'])

    def test_client_cannot_forge_dependency_confirmation(self):
        self.imported();self.change_end();p=copy.deepcopy(self.p)
        p['episodes'][1]['creative_spec']['state_link']={'upstream_digest':'fake'}
        with self.assertRaises(ValueError):studio.save(p,p['revision'])

    def test_pending_episode_cannot_be_approved(self):
        self.imported();self.change_end();self.p['shots'][1].update(approved=True,needs_review=False)
        with self.assertRaisesRegex(ValueError,'跨集状态'):studio.save(self.p,self.p['revision'])


if __name__=='__main__':unittest.main()
