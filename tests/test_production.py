import copy,json,os,unittest
from unittest.mock import patch
from luma import studio, production
import test_studio

class ProductionTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot

    def fixture(self):
        studio.ffmpeg(['-f','lavfi','-i','color=c=blue:size=160x90','-frames:v','1',str(studio.MEDIA/'blue.png')])
        return 'blue.png'

    def test_pause_blocks_enqueuing_and_existing_queue(self):
        with patch.dict(os.environ,{'DIFY_SHOTS_KEY':'mock'}):
            jid=studio.enqueue(self.p['id'],'shots',{},'queued')
            studio.set_spending(0)
            with self.assertRaisesRegex(ValueError,'暂停'):studio.enqueue(self.p['id'],'shots',{},'second')
            with patch('luma.studio.Dify.run') as run:
                studio.work_once();run.assert_not_called()
        with studio.connect() as c:self.assertEqual(c.execute('select state from jobs where id=?',(jid,)).fetchone()[0],'failed')

    def test_budget_counts_unknown_attempt_without_refund(self):
        studio.set_spending(1)
        with patch.dict(os.environ,{'DIFY_SHOTS_KEY':'mock'}):studio.enqueue(self.p['id'],'shots',{},'one')
        with patch.dict(os.environ,{'DIFY_SHOTS_KEY':'mock'}),patch('luma.studio.Dify.run',side_effect=studio.UncertainRun('未知')):studio.work_once()
        self.assertEqual(studio.spending(),{'remaining':0,'used':1})

    def test_asset_edit_retains_old_version_and_binding(self):
        self.add_shot();binding=self.p['shots'][0]['asset_bindings']['hero']
        self.p['assets'][0]['description']='红色大衣';p=studio.save(self.p,self.p['revision'])
        self.assertEqual(len(p['assets'][0]['versions']),2)
        self.assertEqual(p['shots'][0]['asset_bindings']['hero'],binding)
        self.assertNotEqual(p['assets'][0]['selected_version'],binding)

    def test_old_version_is_immutable(self):
        self.add_shot();self.p['assets'][0]['versions'][0]['description']='覆盖历史'
        with self.assertRaisesRegex(ValueError,'历史'):studio.save(self.p,self.p['revision'])

    def test_candidates_are_not_automatically_selected(self):
        self.add_shot();f=self.fixture()
        p=studio.edit_production(dict(project_id=self.p['id'],revision=self.p['revision'],action='add_take',shot_id='s1',kind='image',file=f))
        self.assertNotIn('image',p['shots'][0]);self.assertEqual(len(p['shots'][0]['takes']),1)
        p=studio.edit_production(dict(project_id=p['id'],revision=p['revision'],action='select_take',shot_id='s1',take_id=p['shots'][0]['takes'][0]['id']))
        self.assertEqual(p['shots'][0]['image'],f)

    def test_other_episode_does_not_stale_plan(self):
        self.add_shot();snap=production.scope(self.p,self.p['episodes'][0]['id'])
        self.p['episodes'].append(dict(id='second',title='第二集',script='不同故事'))
        self.p=studio.save(self.p,self.p['revision'])
        self.assertTrue(production.fresh(self.p,snap))
        self.p['episodes'][0]['script']='本集故事改变'
        self.assertFalse(production.fresh(self.p,snap))

    def test_revision_replaces_only_target_keeps_candidates(self):
        self.add_shot();f=self.fixture();production.add_take(self.p['shots'][0],'image',f)
        self.p['shots'].append({**copy.deepcopy(self.p['shots'][0]),'id':'s2','description':'第二镜','takes':[]})
        self.p=studio.save(self.p,self.p['revision']);original=copy.deepcopy(self.p['shots'][1])
        with patch.dict(os.environ,{'DIFY_REVISION_KEY':'mock'}):
            jid=studio.enqueue(self.p['id'],'revision',{'episode_id':self.p['episodes'][0]['id'],'shot_id':'s1','instruction':'改为近景'},'revision')
        studio.update_job(jid,'succeeded',{'result':{'shots':[{'description':'旅人近景','duration':2,'asset_ids':['hero']}]}})
        preview=studio.revision_preview(self.p['id'],jid,self.p['revision'])
        p=studio.apply_job(self.p['id'],jid,self.p['revision'],preview_digest=preview['digest'])
        self.assertEqual(len(p['shots']),2);self.assertEqual(len(p['shots'][0]['takes']),1)
        self.assertEqual(p['shots'][1],original)

    def test_new_candidate_does_not_stale_text_plan(self):
        self.add_shot();snap=production.scope(self.p,self.p['episodes'][0]['id'],'s1','近景')
        production.add_take(self.p['shots'][0],'image',self.fixture())
        self.assertTrue(production.fresh(self.p,snap))

    def test_continuity_marks_dependent_only(self):
        self.add_shot();base=self.p['shots'][0]
        self.p['shots'] += [{**copy.deepcopy(base),'id':'s2','continuity_from':'s1'}, {**copy.deepcopy(base),'id':'s3'}]
        self.p=studio.save(self.p,self.p['revision'])
        for s in self.p['shots']:s.update(approved=True,needs_review=False)
        self.p=studio.save(self.p,self.p['revision']);self.p['shots'][0]['description']='新画面'
        self.p=studio.save(self.p,self.p['revision'])
        self.assertTrue(self.p['shots'][1]['needs_review']);self.assertTrue(self.p['shots'][2]['approved'])

    def test_image_export_has_manifest_and_real_video(self):
        self.add_shot();s=self.p['shots'][0];s['image']=self.fixture()
        self.p=studio.save(self.p,self.p['revision']);self.p['shots'][0].update(approved=True,needs_review=False)
        self.p=studio.save(self.p,self.p['revision']);studio.set_spending(0)
        jid=studio.enqueue(self.p['id'],'export',{},'image-export');studio.work_once()
        with studio.connect() as c:r=c.execute('select * from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(r['state'],'succeeded',r['error']);result=json.loads(r['result'])
        proof=json.loads(studio.media_path(result['manifest']).read_text())
        self.assertEqual(proof['shots'][0]['image'],'blue.png');self.assertTrue(studio.media_path(result['file']).exists())

    def test_revision_workflow_hard_gate_rejects_multiple_shots(self):
        from pathlib import Path
        graph=json.loads((Path(studio.ROOT)/'workflows/production/shot-revision.yml').read_text())['workflow']['graph']
        code=next(n['data']['code'] for n in graph['nodes'] if n['id']=='check');env={};exec(code,env)
        r=env['main'](json.dumps({'shots':[{},{}]}),json.dumps({'passed':True}),{'assets':[],'revision':1})
        self.assertEqual(r['ok'],0);self.assertEqual(r['result']['status'],'blocked')

    def test_download_rejects_local_url(self):
        from luma.media_bridge import receive
        with self.assertRaises(ValueError):receive('http://127.0.0.1/secret','image',studio.MEDIA)

    def test_continuity_cycle_rejected(self):
        self.add_shot();a=self.p['shots'][0]
        self.p['shots'].append({**copy.deepcopy(a),'id':'s2','continuity_from':'s1'})
        a['continuity_from']='s2'
        with self.assertRaisesRegex(ValueError,'循环'):studio.save(self.p,self.p['revision'])

    def test_selected_candidate_cannot_point_to_other_kind(self):
        self.add_shot();s=self.p['shots'][0]
        t=production.add_take(s,'image',self.fixture())
        s['selected_takes']['video']=t['id']
        with self.assertRaisesRegex(ValueError,'不一致'):studio.save(self.p,self.p['revision'])

    def test_media_uses_bound_asset_version_not_latest(self):
        self.add_shot();f=self.fixture();a=self.p['assets'][0]
        a['versions'][0]['file']=f
        a['versions'].append({**a['versions'][0],'id':'new','file':None})
        a['selected_version']='new'
        refs=production.media_references(self.p,'s1')
        self.assertEqual(refs[0]['file'],f)
        self.assertEqual(refs[0]['version_id'],self.p['shots'][0]['asset_bindings']['hero'])

    def test_dify_upload_and_run_share_user_and_file_binding(self):
        import io
        from luma.providers import Dify
        self.add_shot();f=self.fixture();snap=production.scope(self.p,self.p['episodes'][0]['id'],'s1')
        snap['reference_media']=[{'file':f,'role':'start_frame'}]
        calls=[]
        def request(kind,path,body=None,content_type=None):
            calls.append((kind,path,body,content_type))
            return io.BytesIO(b'{"id":"uploaded"}')
        d=Dify()
        with patch.object(d,'request',side_effect=request),patch.object(d,'consume',return_value={'state':'succeeded'}):
            d.run('video',snap,media_path=studio.media_path)
        self.assertIn(('auteur-'+self.p['id']).encode(),calls[0][2])
        body=calls[1][2]
        self.assertEqual(body['user'],'auteur-'+self.p['id'])
        self.assertEqual(body['inputs']['reference_files'],[{'type':'image','transfer_method':'local_file','upload_file_id':'uploaded'}])
        self.assertEqual(json.loads(body['inputs']['context'])['reference_media'][0]['role'],'start_frame')

    def test_late_media_is_retained_without_unlocking_or_selecting(self):
        self.add_shot();f=self.fixture()
        from preparation_fixture import prepare
        prepare(self,'image')
        with patch.dict(os.environ,{'DIFY_IMAGE_KEY':'mock'}):
            jid=studio.enqueue(self.p['id'],'image',{'shot_id':'s1'},'media')
        result={'state':'succeeded','result':{'url':'https://example.com/frame.png'}}
        def finished(*args,**kwargs):
            p=studio.project(self.p['id']);p['shots'][0]['locked']=True;studio.save(p,p['revision']);return result
        with patch.dict(os.environ,{'DIFY_IMAGE_KEY':'mock'}),patch('luma.studio.Dify.run',side_effect=finished),patch('luma.media_bridge.receive',return_value=f):studio.work_once()
        p=studio.project(self.p['id']);s=p['shots'][0]
        self.assertTrue(s['locked']);self.assertNotIn('image',s);self.assertEqual(s['takes'][0]['file'],f)
        with studio.connect() as c:r=c.execute('select * from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(r['state'],'succeeded',r['error'])

    def test_deleted_source_retains_downloaded_file_in_task(self):
        self.add_shot();f=self.fixture()
        from preparation_fixture import prepare
        prepare(self,'image')
        with patch.dict(os.environ,{'DIFY_IMAGE_KEY':'mock'}):jid=studio.enqueue(self.p['id'],'image',{'shot_id':'s1'},'deleted')
        def finished(*args,**kwargs):
            p=studio.project(self.p['id']);p['shots']=[];studio.save(p,p['revision']);return {'state':'succeeded','result':{'url':'https://example.com/frame.png'}}
        with patch.dict(os.environ,{'DIFY_IMAGE_KEY':'mock'}),patch('luma.studio.Dify.run',side_effect=finished),patch('luma.media_bridge.receive',return_value=f):studio.work_once()
        with studio.connect() as c:r=c.execute('select * from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(r['state'],'failed');self.assertEqual(json.loads(r['result'])['candidate_file'],f)

    def test_readiness_reports_selected_media_and_review_separately(self):
        self.add_shot();ep=self.p['episodes'][0]['id'];s=self.p['shots'][0]
        production.add_take(s,'image',self.fixture())
        self.assertEqual(production.readiness(self.p,ep)['shots'][0]['reason'],'尚未选用画面')
        production.select_take(s,s['takes'][0]['id'])
        self.assertEqual(production.readiness(self.p,ep)['shots'][0]['reason'],'需要复核')
        s.update(approved=True,needs_review=False)
        self.assertTrue(production.readiness(self.p,ep)['can_export'])

    def test_delivery_identity_changes_only_with_assembly_inputs(self):
        self.add_shot();snap=production.scope(self.p,self.p['episodes'][0]['id'])
        first=production.delivery_basis(snap)
        snap['shots'][0]['description']='编辑描述，不改变选用素材或剪辑'
        snap['shots'][0]['takes']=[{'file':'unused.mp4'}]
        self.assertEqual(first,production.delivery_basis(snap))
        snap['creative_brief']['format']='9:16'
        self.assertNotEqual(first,production.delivery_basis(snap))

    def test_portrait_format_is_rendered_and_recorded(self):
        import subprocess
        self.add_shot();self.p['creative_brief']['format']='9:16';self.p['shots'][0]['image']=self.fixture()
        self.p=studio.save(self.p,self.p['revision']);self.p['shots'][0].update(approved=True,needs_review=False)
        self.p=studio.save(self.p,self.p['revision']);studio.set_spending(0)
        jid=studio.enqueue(self.p['id'],'export',{},'portrait');studio.work_once()
        with studio.connect() as c:r=c.execute('select * from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(r['state'],'succeeded',r['error']);result=json.loads(r['result'])
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(studio.media_path(result['file']))]))
        video=next(x for x in info['streams'] if x['codec_type']=='video')
        self.assertEqual((video['width'],video['height']),(720,1280))
        self.assertEqual(result['format'],'9:16');self.assertIn('delivery_basis',result)
        self.assertEqual(studio.spending()['used'],0)
