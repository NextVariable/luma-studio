import copy
import io
import json
import unittest
from unittest.mock import patch
from luma import creative
from luma import drama_import
from luma import production
from luma import studio
import test_studio
from luma.providers import Dify


def bundle():
    files = {'project.json': {'projectId': 'fixture', 'title': '导入测试', 'format': 'vertical', 'visualStyle': '冷光'},
             'characters.json': {'characters': [{'id': 'hero', 'name': '旅人', 'appearance': '短发', 'immutableVisualAnchors': ['左腕手表']}]},
             'assets.json': {'assets': [{'assetId': 'station', 'name': '站台', 'type': 'location'}, {'assetId': 'letter', 'name': '信', 'type': 'prop'}]},
             'outfits.json': {'defaultContext': 'night', 'outfits': [{'outfitId': 'coat', 'characterId': 'hero', 'name': '蓝外套', 'context': 'night'}]},
             'episode-state.json': {'episodes': [{'ep': 1, 'knownBy': {'hero': ['第一集线索']}, 'possessions': ['信']}, {'ep': 2, 'knownBy': {'hero': ['第二集才揭晓']}}]},
             'visual-bible.md': '蓝外套与左腕手表不可漂移。'}
    for ep in (1, 2):
        eid = f'EP{ep:03}'
        scene = eid + '-SC1'
        files[f'scripts/{eid}.script.json'] = {'ep': ep, 'title': '第' + str(ep) + '集', 'targetSec': 2,
            'scenes': [{'id': scene, 'location': 'station', 'beats': [{'kind': 'line', 'who': 'hero', 'text': '明天见'}]}]}
        files[f'storyboards/{eid}.storyboard.json'] = {'ep': ep, 'segments': [{'segmentId': eid + '-SEG1', 'sceneId': scene, 'shots': [
            {'shotId': eid + '-S1', 'sceneId': scene, 'episodeId': ep, 'durationSec': 2, 'narrativePurpose': '告别', 'visualSubject': 'hero',
             'action': '旅人收好信', 'locationId': 'station', 'propIds': ['letter'], 'shotSize': '中景', 'cameraMovement': '固定',
             'composition': '人物靠左', 'lighting': '冷光', 'sound': '列车声', 'continuityIn': '信在右手', 'continuityOut': '信在口袋',
             'dialogue': {'who': 'hero', 'text': '明天见'}, 'riskFlags': ['fine-handwork']}]}]}
    return {'format': drama_import.FORMAT, 'files': files}


class DramaImportTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown

    def imported(self):
        preview = studio.preview_drama_import(bundle())
        return studio.apply_drama_import(preview['id'], preview['digest'])

    def test_preview_cancel_has_no_project_job_or_spending_side_effect(self):
        before = studio.project(self.p['id']); allowance = studio.spending()
        preview = studio.preview_drama_import(bundle())
        self.assertEqual(preview['summary']['shots'], 2)
        self.assertEqual(preview['summary']['assets'], 3)
        self.assertEqual(studio.project(self.p['id']), before)
        self.assertEqual(studio.spending(), allowance)
        with studio.connect() as c:
            self.assertEqual(c.execute('select count(*) from projects').fetchone()[0], 1)
            self.assertEqual(c.execute('select count(*) from jobs').fetchone()[0], 0)

    def test_import_preserves_ids_facts_dialogue_and_explicit_outfit(self):
        p = self.imported(); s = p['shots'][0]
        self.assertEqual((len(p['episodes']), s['id'], s['asset_bindings']['hero']), (2, 'EP001-S1', 'coat'))
        self.assertEqual(s['lines'][0]['speaker_asset_id'], 'hero')
        self.assertEqual(s['dialogue'], '旅人：明天见')
        self.assertEqual(s['creative_spec']['continuityOut'], '信在口袋')
        self.assertEqual(s['creative_spec']['composition'], '人物靠左')
        self.assertFalse(s['approved']); self.assertTrue(s['needs_review']); self.assertFalse(s['takes'])

    def test_repeated_confirmation_and_duplicate_package_never_overwrite_edits(self):
        preview = studio.preview_drama_import(bundle()); p = studio.apply_drama_import(preview['id'], preview['digest'])
        p['title'] = '用户已改名'; p = studio.save(p, p['revision'])
        again = studio.apply_drama_import(preview['id'], preview['digest'])
        other = studio.preview_drama_import(bundle()); third = studio.apply_drama_import(other['id'], other['digest'])
        self.assertEqual(again['revision'], p['revision']); self.assertEqual(third['title'], '用户已改名')
        with studio.connect() as c:self.assertEqual(c.execute('select count(*) from projects').fetchone()[0], 2)

    def test_modified_confirmation_digest_is_refused(self):
        preview = studio.preview_drama_import(bundle())
        with self.assertRaises(ValueError): studio.apply_drama_import(preview['id'], 'wrong')

    def test_preview_freezes_input_instead_of_rereading_mutable_source(self):
        b = bundle(); preview = studio.preview_drama_import(b); b['files']['project.json']['title'] = '后来改了'
        p = studio.apply_drama_import(preview['id'], preview['digest']); self.assertEqual(p['title'], '导入测试')

    def test_duplicate_shot_ghost_asset_missing_purpose_and_ambiguous_outfit_block(self):
        for change in ('duplicate', 'ghost', 'purpose', 'outfit'):
            b = bundle(); shots = b['files']['storyboards/EP001.storyboard.json']['segments'][0]['shots']
            if change == 'duplicate': shots.append(copy.deepcopy(shots[0]))
            if change == 'ghost': shots[0]['propIds'] = ['ghost']
            if change == 'purpose': shots[0]['narrativePurpose'] = ''
            if change == 'outfit': b['files']['outfits.json']['outfits'].append({'outfitId':'other', 'characterId':'hero', 'name':'红外套', 'context':'night'})
            with self.subTest(change=change), self.assertRaises(ValueError): studio.preview_drama_import(b)

    def test_missing_scene_and_wrong_episode_block(self):
        for field, value in (('sceneId','missing'),('episodeId',99)):
            b = bundle(); b['files']['storyboards/EP001.storyboard.json']['segments'][0]['shots'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): studio.preview_drama_import(b)

    def test_source_location_conflicts_are_preserved_as_warnings(self):
        b = bundle(); b['files']['scripts/EP001.script.json']['scenes'][0]['location'] = 'other-place'
        preview = studio.preview_drama_import(b); self.assertIn('source-location-conflict', [i['rule'] for i in preview['warnings']])
        p = studio.apply_drama_import(preview['id'], preview['digest'])
        self.assertEqual(p['shots'][0]['creative_spec']['locationId'], 'station')
        self.assertEqual(p['episodes'][0]['creative_spec']['screenplay']['scenes'][0]['location'], 'other-place')
        self.assertTrue(p['shots'][0]['source_warnings'])

    def test_rich_facts_reach_real_adapter_request_without_later_episode_state(self):
        p = self.imported(); snap = production.scope(p, 'EP001', 'EP001-S1', '改成近景')
        result = {'status':'revision_proposed','source_revision':p['revision'],'target_shot_id':'EP001-S1','shots':[{'description':'旅人收好信','duration':2}]}
        event = {'event':'workflow_finished','data':{'status':'succeeded','outputs':{'result':result}}}
        with patch.object(Dify,'request',return_value=io.BytesIO(('data: '+json.dumps(event)+'\n\n').encode())) as request:
            Dify().run('revision',snap)
        body = request.call_args.args[2]; context = json.loads(body['inputs']['context'])
        self.assertEqual(context['shots'][0]['creative_spec']['narrativePurpose'], '告别')
        self.assertEqual(context['assets'][0]['versions'][0]['creative_spec']['character']['immutableVisualAnchors'], ['左腕手表'])
        self.assertEqual(context['creative_context']['rules']['version'], creative.RULE_VERSION)
        self.assertNotIn('第二集才揭晓', body['inputs']['context'])
        self.assertFalse(context['creative_context']['rules']['visual_quality_verified'])

    def test_old_snapshot_and_take_basis_are_unchanged_without_rich_fields(self):
        from test_studio import StudioTests
        StudioTests.add_shot(self); s = self.p['shots'][0]
        self.assertEqual(production.take_basis(s), production.digest({k:s.get(k) for k in production.LEGACY_SHOT_FIELDS}))
        snap = production.scope(self.p, self.p['episodes'][0]['id'])
        self.assertNotIn('creative_context', snap); self.assertNotIn('creative_spec', snap['shots'][0]); self.assertTrue(production.fresh(self.p,snap))

    def test_edit_projection_updates_spec_and_stales_plan(self):
        p = self.imported(); snap = production.scope(p, 'EP001', 'EP001-S1', '近景')
        p['shots'][0]['framing'] = '近景'; p = studio.save(p,p['revision'])
        self.assertEqual(p['shots'][0]['creative_spec']['shotSize'],'近景'); self.assertFalse(production.fresh(p,snap))

    def test_rich_composition_change_stales_plan_and_revokes_approval(self):
        p = self.imported(); p['shots'][0].update(approved=True,needs_review=False); p=studio.save(p,p['revision'])
        snap = production.scope(p,'EP001','EP001-S1','近景'); p['shots'][0]['creative_spec']['composition']='人物靠右';p=studio.save(p,p['revision'])
        self.assertFalse(p['shots'][0]['approved']); self.assertFalse(production.fresh(p,snap))

    def test_rich_duration_cannot_bypass_normal_duration_gate(self):
        p=self.imported();p['shots'][0]['creative_spec']['durationSec']=999
        with self.assertRaises(ValueError):studio.save(p,p['revision'])

    def test_spec_removal_and_identity_rewrite_are_refused(self):
        p=self.imported()
        for change in ('remove','identity'):
            x=copy.deepcopy(p)
            if change=='remove':x['shots'][0].pop('creative_spec')
            else:x['shots'][0]['creative_spec']['shotId']='other'
            with self.subTest(change=change),self.assertRaises(ValueError):studio.save(x,x['revision'])

    def test_local_revision_proposal_preserves_facts_media_and_neighbour(self):
        p=self.imported(); s=p['shots'][0]; (studio.MEDIA/'reference.png').write_bytes(b'fixture')
        production.add_take(s,'image','reference.png');p=studio.save(p,p['revision']);before=copy.deepcopy(p)
        snap=production.scope(p,'EP001',s['id'],'改成近景，人物和对白保持不变')
        result={'status':'revision_proposed','source_revision':p['revision'],'target_shot_id':s['id'],
                'shots':[{'description':s['description'],'duration':2,'framing':'近景'}]}
        with studio.connect() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('revision',p['id'],'revision','succeeded',json.dumps({'snapshot':snap,'revision_preview_required':True}),json.dumps({'result':result}),None,0,0,'revision'))
        preview=studio.revision_preview(p['id'],'revision',p['revision'])
        updated=studio.apply_job(p['id'],'revision',p['revision'],preview_digest=preview['digest'])
        target=updated['shots'][0]
        self.assertEqual(target['creative_spec']['shotSize'],'近景')
        for key in ('composition','continuityIn','continuityOut','sound','narrativePurpose'):
            self.assertEqual(target['creative_spec'][key],before['shots'][0]['creative_spec'][key])
        self.assertEqual(target['takes'],before['shots'][0]['takes']);self.assertEqual(target['lines'],before['shots'][0]['lines'])
        self.assertEqual(updated['shots'][1],before['shots'][1]);self.assertTrue(target['needs_review'])

    def test_partial_rich_revision_merges_without_losing_unmentioned_facts(self):
        p=self.imported(); target=p['shots'][0];original=copy.deepcopy(target)
        production.apply_plan_text(target,{'creative_spec':{'composition':'居中'}},production.PLAN_TEXT_FIELDS)
        self.assertEqual(target['creative_spec']['composition'],'居中')
        self.assertEqual(target['creative_spec']['continuityIn'],original['creative_spec']['continuityIn'])
        self.assertEqual(target['id'],original['id'])

    def test_deleted_last_dialogue_never_returns_from_imported_spec(self):
        p=self.imported();p['shots'][0]['lines']=[];p=studio.save(p,p['revision'])
        self.assertEqual(p['shots'][0]['dialogue'],'');self.assertIsNone(p['shots'][0]['creative_spec']['dialogue'])

    def test_contradictory_plain_and_rich_edits_are_refused(self):
        p=self.imported();p['shots'][0]['framing']='近景';p['shots'][0]['creative_spec']['shotSize']='全景'
        with self.assertRaisesRegex(ValueError,'冲突'):studio.save(p,p['revision'])

    def test_rich_dialogue_cannot_silently_override_structured_lines(self):
        p=self.imported();p['shots'][0]['creative_spec']['dialogue']={'who':'hero','text':'擅改台词'}
        with self.assertRaisesRegex(ValueError,'对白冲突'):studio.save(p,p['revision'])

    def test_duration_policy_is_advisory_and_never_rewrites_narrative_shots(self):
        b=bundle();b['files']['scripts/EP001.script.json']['targetSec']=120
        preview=studio.preview_drama_import(b)
        self.assertIn('source-duration-policy',[w['rule'] for w in preview['warnings']])
        p=studio.apply_drama_import(preview['id'],preview['digest']);self.assertEqual(p['shots'][0]['duration'],2)
        context=production.scope(p,'EP001')['creative_context']
        self.assertTrue(context['rules']['planned_end_state_is_not_current_knowledge'])
        self.assertIn('动作应可观察，优先用行为呈现情绪',context['rules']['creative_preferences'])


if __name__ == '__main__':unittest.main()
