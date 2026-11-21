import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import domestic_media, fal_media, sample_scene, studio


class StoryboardImageTests(TestCase):
    def test_quote_and_queue_exact_two_inputs_without_external_requests(self):
        with TemporaryDirectory() as tmp, patch.multiple(
                studio,DATA=Path(tmp),MEDIA=Path(tmp)/'media',DB=Path(tmp)/'studio.sqlite'
        ), patch.dict(os.environ, FAL_KEY=''), patch.object(fal_media.Fal,'request') as network:
            studio.init()
            p=sample_scene.create(studio.MEDIA,studio.save)
            shot=p['shots'][1]
            selected=shot['image']
            p=studio.shot_camera(dict(project_id=p['id'],revision=p['revision'],shot_id=shot['id'],
                                      camera=dict(view='left',angle=29,distance=2.4)),apply=True)
            shot=p['shots'][1]
            self.assertEqual(shot['image'],selected)
            request=dict(shot_id=shot['id'],episode_id=shot['episode_id'],storyboard=True)
            quote=studio.preview_job_quote(p['id'],'image',request)
            self.assertEqual(quote['estimated_usd'],'0.0398')
            self.assertFalse(quote['configured'])
            self.assertEqual([r['role'] for r in quote['references']],['character','composition'])
            with self.assertRaises(ValueError):
                studio.enqueue(p['id'],'image',{**request,'quote_digest':quote['digest']},'blocked')
            network.assert_not_called()
            self.assertEqual(studio.spending()['used'],0)

            portrait=p['assets'][0]['versions'][0]['file']
            plate=shot['composition_reference']['file']
            bodies=[]
            def mock_queue(path, body=None):
                if body:
                    self.assertEqual(path,'/'+fal_media.STORYBOARD)
                    bodies.append(body)
                    return {'request_id':'fixture'}
                if path.endswith('/status'):return {'status':'COMPLETED'}
                return {'images':[{'url':'https://example.invalid/local-test'}]}

            with patch.dict(os.environ,FAL_KEY='offline-fixture'), patch('luma.media_bridge.receive',return_value=portrait):
                network.side_effect=mock_queue
                quote=studio.preview_job_quote(p['id'],'image',request)
                studio.set_spending(1)
                studio.shot_camera(dict(project_id=p['id'],revision=p['revision'],shot_id=shot['id'],
                                        camera=dict(view='left',angle=30,distance=2.4)),apply=True)
                with self.assertRaisesRegex(ValueError,'报价已变化'):
                    studio.enqueue(p['id'],'image',{**request,'quote_digest':quote['digest']},'outdated')
                quote=studio.preview_job_quote(p['id'],'image',request)
                plate=studio.project(p['id'])['shots'][1]['composition_reference']['file']
                job=studio.enqueue(p['id'],'image',{**request,'quote_digest':quote['digest']},'offline')
                studio.work_once()
                with studio.connect() as db:
                    row=db.execute('SELECT state,error FROM jobs WHERE id=?',(job,)).fetchone()
                self.assertEqual(row['state'],'succeeded',row['error'])
                self.assertEqual(len(bodies),1)
                body=bodies[0]
                self.assertEqual(body['num_images'],1)
                self.assertTrue(body['limit_generations'])
                self.assertEqual([base64.b64decode(url.split(',')[1]) for url in body['image_urls']],
                                 [studio.media_path(f).read_bytes() for f in (portrait,plate)])
                result=studio.project(p['id'])['shots'][1]
                self.assertEqual(result['selected_takes'],shot['selected_takes'])
                self.assertTrue(any(t.get('job_id')==job for t in result['takes']))

    def test_three_camera_quotes_follow_bound_scene_and_visible_cast(self):
        with TemporaryDirectory() as tmp, patch.multiple(
                studio, DATA=Path(tmp), MEDIA=Path(tmp)/'media', DB=Path(tmp)/'studio.sqlite'
        ), patch('socket.socket.connect', side_effect=AssertionError('unexpected network')):
            studio.init()
            p = sample_scene.create(studio.MEDIA, studio.save)
            for location in ('夜晚站台', '室内书房'):
                scene = next(a for a in p['assets'] if a['kind'] == 'scene')
                if location == '室内书房':
                    scene.update(name=location, description='窗前并排的书桌')
                    for shot in p['shots']:
                        shot['description'] = '两个人在房间里交谈'
                    p = studio.save(p, p['revision'])
                    for shot in p['shots']:
                        shot['asset_bindings'][scene['id']] = p['assets'][-1]['selected_version']
                    p = studio.save(p, p['revision'])
                for shot, names in zip(p['shots'], [('阿远', '青禾'), ('阿远',), ('青禾',)]):
                    for model in (domestic_media.FLASH, fal_media.STORYBOARD):
                        packet = studio.storyboard_packet(p, shot['id'], model)
                        q = studio.preview_job_quote(p['id'], 'image', dict(
                            shot_id=shot['id'], episode_id=shot['episode_id'], storyboard=True, model=model))
                        self.assertIn(location, packet['instruction'])
                        if location == '室内书房':
                            self.assertNotIn('站台', packet['instruction'])
                        self.assertEqual([r['label'] for r in q['references']],
                                         [name + ' · 角色参考' for name in names] + ['机位构图'])
                        self.assertEqual(q['references'][-1]['file'], shot['composition_reference']['file'])
            self.assertEqual(studio.spending()['used'], 0)
