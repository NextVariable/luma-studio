"""End-to-end local pipelines with provider responses explicitly simulated."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import domestic_media as media, production, sample_scene, studio


class AgenticStudioTests(TestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory())
        data = Path(tmp)
        self.enterContext(patch.multiple(studio, DATA=data, MEDIA=data/'media', DB=data/'studio.sqlite'))
        self.enterContext(patch.dict('os.environ', ARK_API_KEY='mock-only', MINIMAX_API_KEY='mock-only',
                                     DIFY_SCRIPT_KEY='app-draft', DIFY_SHOTS_KEY='app-shots'))
        self.enterContext(patch('socket.socket.connect', side_effect=AssertionError('network disabled')))
        studio.init()
        self.image = 'local-frame.png'
        studio.ffmpeg(['-f','lavfi','-i','color=blue:size=640x360','-frames:v','1',str(studio.MEDIA/self.image)])

    def row(self, jid):
        with studio.connect() as db:
            return db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()

    def run_job(self, project, payload, nonce, quote=False):
        if quote:
            cost = studio.preview_job_quote(project['id'],payload['kind'],payload)
            payload = dict(payload,quote_digest=cost['digest'])
        jid = studio.enqueue(project['id'],payload['kind'],payload,nonce)
        self.assertTrue(studio.work_once())
        row = self.row(jid)
        self.assertEqual(row['state'],'succeeded',row['error'])
        return jid

    def test_station_batch_pause_isolates_failed_shot_and_keeps_old_takes(self):
        p = sample_scene.create(studio.MEDIA,studio.save)
        eid = p['episodes'][0]['id']
        requests = [dict(shot_id=s['id'],episode_id=eid,kind='image',model=media.FLASH,
                         storyboard=True,storyboard_reference_mode='text') for s in p['shots']]
        batch = dict(project_id=p['id'],requests=requests,nonce='station')
        quote = studio.production_batch(batch)
        self.assertEqual(quote['estimated_cny'],'0.36')
        batch['digest'] = quote['digest']
        studio.set_spending(2)
        with self.assertRaisesRegex(ValueError,'授权不足'):
            studio.production_batch(batch,True)
        self.assertFalse(studio.work_once())
        studio.set_spending(3)
        result = studio.production_batch(batch,True)
        self.assertEqual(studio.production_batch(batch,True),result)
        scope = dict(project_id=p['id'],batch_id=result['batch_id'])
        self.assertEqual(studio.batch_state(dict(scope,action='pause'))['updated'],3)
        self.assertFalse(studio.work_once())
        studio.set_spending(2)
        with self.assertRaisesRegex(ValueError,'保持暂停'):
            studio.batch_state(dict(scope,action='resume'))
        studio.set_spending(3)
        self.assertEqual(studio.batch_state(dict(scope,action='resume'))['updated'],3)
        ok = {'data':[{'url':'https://art.invalid/frame'}]}
        with patch.object(media,'request',side_effect=[ok,ValueError('fixture rejection'),ok]) as remote,              patch('luma.media_bridge.receive',return_value=self.image):
            for _ in requests:
                studio.work_once()
            self.assertEqual(remote.call_count,3)
        self.assertEqual([self.row(j)['state'] for j in result['jobs']],['succeeded','failed','succeeded'])
        self.assertEqual(studio.spending(),{'remaining':0,'used':3})
        updated = studio.project(p['id'])
        for before,after in zip(p['shots'],updated['shots'],strict=True):
            self.assertEqual(before['selected_takes'],after['selected_takes'])
            self.assertTrue(all(t in after['takes'] for t in before['takes']))
        self.run_job(updated,dict(kind='export',episode_id=eid),'station-export')

    def test_new_story_assets_single_camera_video_recovery_review_and_export(self):
        p = studio.create('清晨的钥匙','修表学徒把钥匙放回工作台，听见钟被敲响。')
        eid = p['episodes'][0]['id']
        studio.set_spending(6)
        beats = dict(characters=[dict(name='学徒',description='亚麻围裙')],
                     scenes=[dict(name='钟表店', description='靠窗工作台，墙上挂钟')])
        with patch.object(studio.Dify,'run',return_value=dict(state='succeeded',result=beats)):
            analysis = self.run_job(p,dict(kind='script',episode_id=eid),'analysis')
        p = studio.apply_job(p['id'],analysis,p['revision'])
        character,scene = p['assets']
        studio.edit_production(dict(project_id=p['id'],revision=p['revision'],action='character_look',
                                    asset_id=character['id'],outfit='亚麻围裙'))
        for aid in (character['id'],scene['id']):
            p = studio.project(p['id'])
            asset = next(a for a in p['assets'] if a['id']==aid)
            req = dict(kind='asset_image',episode_id=eid,asset_id=aid,version_id=asset['selected_version'],
                       instruction='明确造型或地标，保留柔和晨光')
            with patch.object(media,'request',return_value={'data':[{'url':'https://art.invalid/ref'}]}),                  patch('luma.media_bridge.receive',return_value=self.image):
                jid = self.run_job(p,req,'asset-'+aid,quote=True)
            unchanged = studio.project(p['id'])
            self.assertEqual(p,unchanged)
            ctx = dict(project_id=p['id'],revision=p['revision'],job_id=jid)
            p = studio.approve_asset_image(ctx)
            saved = next(a for a in p['assets'] if a['id']==aid)
            self.assertEqual(saved['selected_version'],asset['selected_version'])
            studio.edit_production(dict(project_id=p['id'],revision=p['revision'],action='asset_select',
                                        asset_id=aid,version_id=saved['versions'][-1]['id']))
        p = studio.project(p['id'])
        shots = dict(shots=[dict(description='学徒看着工作台上的钥匙',framing='中景',camera='固定机位',duration=6,
                                 dialogue='',asset_ids=[character['id'],scene['id']])])
        with patch.object(studio.Dify,'run',return_value=dict(state='succeeded',result=shots)):
            plan = self.run_job(p,dict(kind='shots',episode_id=eid),'plan')
        p = studio.apply_job(p['id'],plan,p['revision'])
        shot = p['shots'][0]
        scope = dict(project_id=p['id'],shot_id=shot['id'])
        p = studio.shot_camera(dict(scope,revision=p['revision']),apply=True)
        request = dict(kind='image',episode_id=eid,shot_id=shot['id'],storyboard=True,model=media.FLASH,
                       storyboard_reference_mode='text')
        quote = studio.preview_job_quote(p['id'],'image',request)
        self.assertEqual([r['role'] for r in quote['references']],['character','scene'])
        with patch.object(media,'request',return_value={'data':[{'url':'https://art.invalid/still'}]}), \
             patch('luma.media_bridge.receive',return_value=self.image):
            self.run_job(p,request,'still',quote=True)
        p = studio.project(p['id'])
        pic = p['shots'][0]['takes'][-1]
        p = studio.edit_production(dict(scope,revision=p['revision'],action='select_take',take_id=pic['id']))
        prep = studio.open_preparation(p['id'],shot['id'])
        ref = next(r for r in prep['references'] if r['source']=='shot_image')
        seg = prep['plan']['segments'][0]
        seg.update(model=media.HAILUO, mode='image_to_video', references=[dict(role='first_frame',reference_id=ref['reference_id'])])
        seg['parameters']['resolution']='768P'
        studio.save_preparation(p['id'],shot['id'],prep['revision'],prep['plan'],prep['basis'])
        video = dict(kind='video',shot_id=shot['id'],episode_id=eid,segment_id=seg['id'])
        quote = studio.preview_job_quote(p['id'],'video',video)
        self.assertEqual(quote['estimated_cny'],'1.35')
        jid = studio.enqueue(p['id'],'video',dict(video,quote_digest=quote['digest']),'video')
        ok = dict(base_resp=dict(status_code=0))
        with patch.object(media,'request',side_effect=[dict(ok,task_id='toy-1'),media.UncertainRun('offline interruption')]):
            studio.work_once()
        self.assertEqual(self.row(jid)['state'],'interrupted',self.row(jid)['error'])
        self.assertEqual(json.loads(self.row(jid)['result'])['run_id'],'toy-1')
        studio.ffmpeg(['-f','lavfi','-i','color=purple:size=640x360','-t','6','-pix_fmt','yuv420p',str(studio.MEDIA/'clip.mp4')])
        studio.reconcile_job(p['id'],jid)
        with patch.object(media,'request',side_effect=[dict(ok,task_id='toy-1',status='Success',file_id='toy-file'),
                                                       dict(ok,file=dict(file_id='toy-file',download_url='https://art.invalid/clip'))]) as remote,              patch('luma.media_bridge.receive',return_value='clip.mp4'):
            studio.work_once()
            self.assertEqual([c.args for c in remote.call_args_list], [
                ('minimax','/v1/query/video_generation?task_id=toy-1',None),
                ('minimax','/v1/files/retrieve?file_id=toy-file',None)])
        self.assertEqual(self.row(jid)['state'],'succeeded',self.row(jid)['error'])
        p = studio.project(p['id'])
        take = next(t for t in p['shots'][0]['takes'] if t['kind']=='video')
        review = studio.candidate_review(dict(scope,take_id=take['id']))
        studio.candidate_review(dict(scope,take_id=take['id'],basis=review['basis'],
            structure={key:'pass' for key in review['structure']},scores={key:3 for key in review['scores']},
            notes='模拟测试只验证复核记录入库。'),True)
        choices = studio.candidate_review(scope)['candidates']
        self.assertEqual(choices[-1]['estimated_cny'],'1.35')
        self.assertIsNone(choices[-1]['actual_cny'])
        self.assertEqual(choices[-1]['reviews'][0]['source'],'human')
        self.assertTrue(choices[-1]['reviews'][0]['matches_shot'])
        p = studio.edit_production(dict(scope,revision=p['revision'],action='select_take',take_id=take['id']))
        p['shots'][0].update(approved=True,needs_review=False)
        p = studio.save(p,p['revision'])
        self.assertTrue(production.readiness(p,eid)['can_export'])
        export = self.run_job(p,dict(kind='export',episode_id=eid),'new-story-export')
        final = json.loads(self.row(export)['result'])['file']
        self.assertAlmostEqual(float(studio.probe_media(final)['format']['duration']),6,delta=.1)
        self.assertEqual(studio.spending(),{'remaining':0,'used':6})

    def test_minimax_contract_rejects_unsupported_duration_resolution_and_image(self):
        segment = dict(model=media.HAILUO, instruction='自然转头', duration=6,
                       parameters=dict(resolution='768P'),
                       references=[dict(role='first_frame',file=self.image)])
        body = media.arguments('video',{'generation_segment':segment},studio.media_path)
        self.assertEqual((body['duration'],body['resolution'],body['prompt_optimizer']),(6,'768P',False))
        self.assertTrue(body['first_frame_image'].startswith('data:image/png;base64,'))
        for seconds,resolution in ((5,'768P'),(10,'1080P'),(6,'720P')):
            invalid = dict(segment,duration=seconds,parameters=dict(resolution=resolution))
            with self.assertRaisesRegex(ValueError,'组合无效'):
                media.arguments('video',{'generation_segment':invalid},studio.media_path)
        studio.ffmpeg(['-f','lavfi','-i','color=blue:size=320x180','-frames:v','1',str(studio.MEDIA/'tiny.png')])
        segment['references'][0]['file']='tiny.png'
        with self.assertRaisesRegex(ValueError,'短边'):
            media.arguments('video',{'generation_segment':segment},studio.media_path)

    def test_over_shoulder_preserves_asset_references_and_uses_foreground(self):
        p = sample_scene.create(studio.MEDIA,studio.save)
        shot = p['shots'][1]
        scope = dict(project_id=p['id'],shot_id=shot['id'],revision=p['revision'])
        camera = dict(view='over_left',distance=3.5,angle=20,height=.2,offset=.15,
                      positions={'阿远':dict(x=-.8,z=.2)},gaze={'阿远':'right'})
        preview = studio.shot_camera(dict(scope,camera=camera))
        self.assertNotEqual(preview['image'],studio.shot_camera(scope)['image'])
        p = studio.shot_camera(dict(scope,camera=camera),apply=True)
        packet=studio.storyboard_packet(p,shot['id'],media.FLASH)
        self.assertEqual(packet['staging']['visible_ids'],['阿远','青禾'])
        self.assertEqual([r['role'] for r in packet['references']],['character','character','composition'])
        self.assertIn('前景肩背',packet['instruction'])
        self.assertEqual(p['shots'][1]['selected_takes'],shot['selected_takes'])
