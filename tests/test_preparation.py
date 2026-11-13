import copy
import io
import json
import os
import unittest
from unittest.mock import patch
from luma import studio
from luma import production
from luma import preparation
import test_studio
from preparation_fixture import prepare
from luma.providers import Dify


class PreparationTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot

    def configured(self,kind='video'):
        self.add_shot();(studio.MEDIA/'front.png').write_bytes(b'isolated-reference')
        self.model=prepare(self,kind);self.p=studio.project(self.p['id']);return self.p['shots'][0]['preparation']

    def report(self):return preparation.report(self.p,'s1',studio.media_path,lambda k:True)

    def save_plan(self,plan):
        result=studio.save_preparation(self.p['id'],'s1',self.p['revision'],plan,preparation.basis(self.p['shots'][0]));self.p=result['project'];return result

    def test_unknown_model_is_saved_as_plan_never_claimed_verified(self):
        self.add_shot();opened=studio.open_preparation(self.p['id'],'s1');plan=opened['plan'];plan['segments'][0]['model']='unknown-real-service'
        before=studio.spending();result=self.save_plan(plan)
        self.assertFalse(result['status']['ready']);self.assertTrue(any('尚未核实' in i['message'] for i in result['status']['issues']))
        with patch.dict(os.environ,{'DIFY_VIDEO_KEY':'test-only'}),self.assertRaisesRegex(ValueError,'制作准备'):studio.enqueue(self.p['id'],'video',{'shot_id':'s1'},'unknown')
        self.assertEqual(studio.spending(),before)
        with studio.connect() as c:self.assertEqual(c.execute('select count(*) from jobs').fetchone()[0],0)

    def test_no_implicit_auto_collection_without_preparation(self):
        self.add_shot()
        with patch.dict(os.environ,{'DIFY_IMAGE_KEY':'test-only'}),self.assertRaisesRegex(ValueError,'尚未保存制作准备'):studio.enqueue(self.p['id'],'image',{'shot_id':'s1'},'bypass')

    def test_bound_outfit_and_single_selected_view_are_explicit(self):
        self.configured();s=self.p['shots'][0];plan=copy.deepcopy(s['preparation'])
        self.assertEqual(plan['character_versions'],s['asset_bindings']);self.assertEqual(len(plan['segments'][0]['references']),1)
        self.assertTrue(self.report()['ready'])

    def test_split_preserves_parent_identity_duration_and_facts(self):
        plan=copy.deepcopy(self.configured());before=copy.deepcopy(self.p['shots'][0]);one=plan['segments'][0];two=copy.deepcopy(one)
        one.update(end=1,instruction='抬手',start_state='手放下',end_state='手抬起');two.update(id='part-two',start=1,instruction='收信',start_state='手抬起',end_state='信收好')
        plan['segments']=[one,two];self.save_plan(plan)
        s=self.p['shots'][0]
        for k in ('id','duration','description','dialogue','asset_bindings'):self.assertEqual(s.get(k),before.get(k))
        self.assertTrue(self.report()['ready'])
        with self.assertRaisesRegex(ValueError,'指定'):preparation.freeze(self.p,'s1','video',None,studio.media_path,lambda k:True)

    def test_gaps_overlap_duplicate_ids_and_wrong_total_are_rejected(self):
        source=copy.deepcopy(self.configured())
        for change in ('gap','overlap','duplicate','total','nan'):
            plan=copy.deepcopy(source);a=plan['segments'][0];b=copy.deepcopy(a);a['end']=1;b.update(id='two',start=1)
            if change=='gap':b['start']=1.2
            elif change=='overlap':b['start']=.8
            elif change=='duplicate':b['id']=a['id']
            elif change=='total':b['end']=3
            else:a['end']=float('nan')
            plan['segments']=[a,b]
            with self.subTest(change=change),self.assertRaises(ValueError):self.save_plan(plan)

    def test_unaligned_segment_states_save_but_block_submission(self):
        plan=copy.deepcopy(self.configured());a=plan['segments'][0];b=copy.deepcopy(a);a.update(end=1,start_state='A',end_state='B');b.update(id='two',start=1,start_state='C',end_state='D');plan['segments']=[a,b]
        result=self.save_plan(plan);self.assertFalse(result['status']['ready']);self.assertIn('衔接', ''.join(i['message'] for i in result['status']['issues']).replace('相邻片段的末态与起始状态尚未对齐','衔接'))

    def test_wrong_pinned_version_and_ghost_reference_are_refused(self):
        original=copy.deepcopy(self.configured())
        plan=copy.deepcopy(original);plan['character_versions']['hero']='wrong'
        with self.assertRaisesRegex(ValueError,'造型版本'):self.save_plan(plan)
        plan=copy.deepcopy(original);plan['segments'][0]['references']=[{'reference_id':'ghost','role':'reference_image'}]
        with self.assertRaisesRegex(ValueError,'参考图'):self.save_plan(plan)

    def test_duplicate_reference_and_fake_file_fields_are_refused(self):
        original=copy.deepcopy(self.configured())
        for mode in ('duplicate','filename'):
            plan=copy.deepcopy(original);ref=plan['segments'][0]['references'][0]
            if mode=='duplicate':plan['segments'][0]['references'].append(copy.deepcopy(ref))
            else:ref['file']='other.png'
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.save_plan(plan)

    def test_mode_role_mismatch_blocks_before_external_submission(self):
        source=copy.deepcopy(self.configured())
        for mode in ('text_to_video','image_to_video','start_end_frames'):
            plan=copy.deepcopy(source);plan['segments'][0]['mode']=mode;result=self.save_plan(plan);self.assertFalse(result['status']['ready'])

    def test_exact_model_limits_resolution_duration_role_count_and_combination(self):
        self.configured();profile=preparation.MODELS[self.model]
        for field,value in [('max_images',0),('resolutions',['invalid']),('modes',[]),('duration',{'min':3,'max':4}),('role_limits',{}),('parameter_sets',[{'aspect_ratio':'9:16','resolution':'720p'}])]:
            with self.subTest(field=field),patch.dict(profile,{field:value}):self.assertFalse(self.report()['ready'])

    def test_unknown_parameters_and_changed_aspect_ratio_are_rejected(self):
        source=copy.deepcopy(self.configured())
        for key,value in [('magic',True),('aspect_ratio','9:16'),('fps',float('inf')),('seed',True)]:
            plan=copy.deepcopy(source);plan['segments'][0]['parameters'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.save_plan(plan)

    def test_unsupported_parameter_is_not_silently_dropped(self):
        plan=copy.deepcopy(self.configured());plan['segments'][0]['parameters']['fps']=60;result=self.save_plan(plan)
        self.assertFalse(result['status']['ready']);self.assertEqual(self.p['shots'][0]['preparation']['segments'][0]['parameters']['fps'],60)

    def test_disconnected_service_blocks_even_with_verified_fixture(self):
        self.configured();self.assertFalse(preparation.report(self.p,'s1',studio.media_path,lambda k:False)['ready'])

    def test_identity_and_outfit_missing_are_reported_without_fake_fallback(self):
        plan=copy.deepcopy(self.configured());plan['segments'][0].update(mode='text_to_video',references=[]);result=self.save_plan(plan)
        self.assertFalse(result['status']['ready']);self.assertTrue(any('用于生成的参考图' in i['message'] for i in result['status']['issues']))

    def test_plan_is_stale_after_narrative_change_but_is_not_deleted(self):
        self.configured();self.p['shots'][0]['description']='新的叙事动作';self.p=studio.save(self.p,self.p['revision'])
        self.assertIn('preparation',self.p['shots'][0]);self.assertFalse(self.report()['ready'])

    def test_rebinding_invalidates_exact_reference_instead_of_auto_switching(self):
        self.configured();original=copy.deepcopy(self.p['shots'][0]['preparation']);(studio.MEDIA/'other.png').write_bytes(b'other')
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'asset_version','asset_id':'hero','file':'other.png'})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_current','shot_id':'s1'})
        self.assertEqual(self.p['shots'][0]['preparation'],original);self.assertFalse(self.report()['ready'])

    def test_parameter_changes_revoke_review_and_keep_candidates(self):
        self.configured();s=self.p['shots'][0];production.add_take(s,'image','front.png');s.update(approved=True,needs_review=False);self.p=studio.save(self.p,self.p['revision']);before=copy.deepcopy(self.p['shots'][0]['takes'])
        plan=copy.deepcopy(s['preparation']);plan['segments'][0]['parameters']['seed']=8;self.save_plan(plan)
        self.assertFalse(self.p['shots'][0]['approved']);self.assertEqual(self.p['shots'][0]['takes'],before)

    def test_queue_freezes_selected_segment_model_parameters_and_bytes(self):
        self.configured()
        with patch.dict(os.environ,{'DIFY_VIDEO_KEY':'test-only'}):jid=studio.enqueue(self.p['id'],'video',{'shot_id':'s1'},'freeze')
        with studio.connect() as c:payload=json.loads(c.execute('select payload from jobs where id=?',(jid,)).fetchone()[0])
        packet=payload['snapshot']['generation_segment'];self.assertEqual(packet['model'],self.model);self.assertEqual(packet['duration'],2)
        self.assertEqual(len(packet['references']),1);self.assertTrue(payload['generation_unit']['references'][0]['sha256']);self.assertEqual(payload['generation_unit']['parameters']['resolution'],'720p')

    def test_actual_adapter_request_contains_packet_and_only_selected_files(self):
        self.configured();packet=preparation.freeze(self.p,'s1','video',None,studio.media_path,lambda k:True)
        snap=production.scope(self.p,self.p['episodes'][0]['id'],'s1');snap.update(generation_segment=packet,reference_media=packet['references'],reference_mode='references')
        event={'event':'workflow_finished','data':{'status':'succeeded','outputs':{'result':{'url':'https://example.invalid/result.mp4'}}}}
        with patch.object(Dify,'upload_reference',return_value={'type':'image','transfer_method':'local_file','upload_file_id':'test'}) as upload,patch.object(Dify,'request',return_value=io.BytesIO(('data: '+json.dumps(event)+'\n\n').encode())) as request:
            Dify().run('video',snap,media_path=studio.media_path)
        context=json.loads(request.call_args.args[2]['inputs']['context']);self.assertEqual(context['generation_segment']['parameters']['resolution'],'720p');self.assertEqual(upload.call_count,1)

    def test_changed_model_or_plan_blocks_queued_job_without_spending(self):
        self.configured()
        with patch.dict(os.environ,{'DIFY_VIDEO_KEY':'test-only'}):
            jid=studio.enqueue(self.p['id'],'video',{'shot_id':'s1'},'change')
            with patch.dict(preparation.MODELS[self.model],{'max_images':0}),patch.object(Dify,'run') as run:
                before=studio.spending();studio.work_once();run.assert_not_called();self.assertEqual(studio.spending(),before)
        with studio.connect() as c:self.assertEqual(c.execute('select state from jobs where id=?',(jid,)).fetchone()[0],'failed')

    def test_partial_generation_take_cannot_masquerade_as_whole_shot(self):
        self.configured();s=self.p['shots'][0];t=production.add_take(s,'video','piece.mp4');t['generation_segment']={'id':'one','start':0,'end':1,'shot_id':s['id']}
        with self.assertRaisesRegex(ValueError,'局部生成片段'):production.select_take(s,t['id'])
        with self.assertRaisesRegex(ValueError,'局部生成片段'):production.set_clip(s,t['id'])

    def test_initialization_is_no_cost_idempotent_and_does_not_overwrite_plan(self):
        self.add_shot();before=copy.deepcopy(self.p['shots'][0]);result=studio.initialize_preparation(self.p['id'],self.p['revision']);p=result['project']
        self.assertEqual(result['initialized'],1);self.assertEqual(result['ready_count'],0)
        second=studio.initialize_preparation(p['id'],p['revision']);self.assertEqual(second['initialized'],0);self.assertEqual(second['project']['revision'],p['revision'])
        for key,value in before.items():self.assertEqual(p['shots'][0][key],value)

    def test_stale_revision_and_locked_shot_cannot_replace_preparation(self):
        plan=copy.deepcopy(self.configured());self.p['shots'][0]['locked']=True;self.p=studio.save(self.p,self.p['revision'])
        with self.assertRaises(ValueError):self.save_plan(plan)

    def test_only_explicit_view_is_uploaded_and_other_views_are_omitted(self):
        self.configured();(studio.MEDIA/'side.png').write_bytes(b'side')
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'character_look','asset_id':'hero','outfit':'测试服装','voice_id':'alloy','views':{'side':'side.png'}})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_current','shot_id':'s1'})
        opened=studio.open_preparation(self.p['id'],'s1');plan=opened['plan'];plan['character_versions']=preparation.character_versions(self.p,self.p['shots'][0])
        chosen=next(r for r in opened['references'] if r['file']=='side.png');plan['segments'][0]['references']=[{'reference_id':chosen['reference_id'],'role':'reference_image'}];self.save_plan(plan)
        with patch.dict(os.environ,{'DIFY_VIDEO_KEY':'test-only'}):jid=studio.enqueue(self.p['id'],'video',{'shot_id':'s1'},'selected-view')
        with studio.connect() as c:snap=json.loads(c.execute('select payload from jobs where id=?',(jid,)).fetchone()[0])['snapshot']
        self.assertEqual([r['file'] for r in snap['reference_media']],['side.png']);self.assertTrue(snap['reference_omitted'])

    def test_even_supported_profile_revision_change_blocks_old_queued_request(self):
        self.configured()
        with patch.dict(os.environ,{'DIFY_VIDEO_KEY':'test-only'}):
            studio.enqueue(self.p['id'],'video',{'shot_id':'s1'},'profile-revision');before=studio.spending()
            with patch.dict(preparation.MODELS[self.model],{'evidence':'isolated-fixture-revision-2'}),patch.object(Dify,'run') as run:studio.work_once();run.assert_not_called()
        self.assertEqual(studio.spending(),before)

    def test_plan_edit_blocks_old_queued_request_without_using_allowance(self):
        self.configured()
        with patch.dict(os.environ,{'DIFY_VIDEO_KEY':'test-only'}):
            studio.enqueue(self.p['id'],'video',{'shot_id':'s1'},'plan-revision');plan=copy.deepcopy(self.p['shots'][0]['preparation']);plan['segments'][0]['parameters']['seed']=7;self.save_plan(plan);before=studio.spending()
            with patch.object(Dify,'run') as run:studio.work_once();run.assert_not_called()
        self.assertEqual(studio.spending(),before)


if __name__=='__main__':unittest.main()
