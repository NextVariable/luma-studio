"""Station shot 2 production rehearsal with local artifacts and no outbound requests."""
import base64
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import domestic_media as media
from luma import sample_scene, studio


class StationMediaTests(TestCase):
    model = media.SEEDREAM
    price = '0.25'

    def test_two_refs_to_selected_frame_to_silent_five_second_clip(self):
        with TemporaryDirectory() as tmp, patch.multiple(
            studio, DATA=Path(tmp), MEDIA=Path(tmp)/'media', DB=Path(tmp)/'studio.sqlite'
        ), patch.dict(os.environ, ARK_API_KEY='', DASHSCOPE_API_KEY='', DASHSCOPE_WORKSPACE_ID=''), \
                patch('socket.socket.connect', side_effect=AssertionError('unexpected network connection')):
            studio.init()
            project = sample_scene.create(studio.MEDIA, studio.save)
            shot = project['shots'][1]
            base = dict(shot_id=shot['id'], episode_id=shot['episode_id'])
            pid = project['id']
            still = dict(**base, storyboard=True, model=self.model)
            first_quote = studio.preview_job_quote(pid, 'image', still)
            self.assertFalse(first_quote['configured'])
            self.assertEqual(first_quote['estimated_cny'], self.price)
            with self.assertRaises(ValueError):
                studio.enqueue(pid, 'image', dict(**still, quote_digest=first_quote['digest']), 'blocked')

            # A local illustrated take stands in for Seedream's returned image.
            frame = studio.MEDIA / 'offline-storyboard.jpg'
            frame.write_bytes(next(studio.MEDIA.glob('*-frame-4.jpg')).read_bytes())
            clip = studio.MEDIA / 'offline-video.mp4'
            requests = []
            def transport(provider, path, body=None):
                requests.append((provider, path, body))
                if provider == 'ark':
                    return dict(data=[dict(url='https://fixture.invalid/image')])
                if body:
                    return dict(output=dict(task_id='station-2'))
                return dict(output=dict(task_status='SUCCEEDED', video_url='https://fixture.invalid/video'))

            def receive(url, kind, folder):
                if kind == 'image':
                    return frame.name
                subprocess.run(['ffmpeg','-loglevel','error','-loop','1','-i',str(frame),
                                '-vf','scale=1280:720','-t','5','-an','-pix_fmt','yuv420p',
                                '-c:v','libx264','-preset','ultrafast',str(clip)], check=True)
                return clip.name

            def run(kind, request, price):
                quote = studio.preview_job_quote(pid, kind, request)
                self.assertEqual(quote['estimated_cny'], price)
                with self.assertRaisesRegex(ValueError,'报价'):
                    studio.enqueue(pid, kind, request, 'unquoted')
                job = studio.enqueue(pid, kind, dict(**request,quote_digest=quote['digest']), kind)
                self.assertTrue(studio.work_once())
                with studio.connect() as db:
                    row = db.execute('SELECT state,error FROM jobs WHERE id=?',(job,)).fetchone()
                self.assertEqual(row['state'],'succeeded',row['error'])
                current = studio.project(pid)
                take = next(t for t in current['shots'][1]['takes'] if t.get('job_id')==job)
                return current, take

            with patch.dict(os.environ, ARK_API_KEY='offline', DASHSCOPE_API_KEY='offline'), \
                    patch.object(media,'request',side_effect=transport), patch('luma.media_bridge.receive',side_effect=receive):
                studio.set_spending(2)
                current, take = run('image',still,self.price)
                self.assertEqual(take['model'], self.model)
                self.assertEqual(current['shots'][1]['image'],shot['image'])
                self.assertEqual(current['shots'][1]['composition_reference'],shot['composition_reference'])
                body = requests[0][2]
                inputs = [base64.b64decode(url.split(',')[1]) for url in body['image']]
                self.assertEqual(inputs,[studio.media_path(r['file']).read_bytes() for r in first_quote['references']])
                self.assertEqual(body['model'], self.model)
                if self.model == media.FLASH:
                    self.assertNotIn('sequential_image_generation', body)
                else:
                    self.assertEqual(body['sequential_image_generation'],'disabled')
                studio.edit_production(dict(project_id=pid, revision=current['revision'], shot_id=shot['id'],
                                            action='select_take', take_id=take['id']))
                prep = studio.open_preparation(pid,shot['id'])
                ref = next(r for r in prep['references'] if r['file']==frame.name)
                seg = prep['plan']['segments'][0]
                seg.update(model=media.WAN, mode='image_to_video', references=[dict(role='first_frame',reference_id=ref['reference_id'])])
                seg['parameters']['resolution']='720P'
                saved=studio.save_preparation(pid,shot['id'],prep['revision'],prep['plan'],prep['basis'])
                self.assertTrue(saved['status']['ready'],saved['status']['issues'])
                current, take = run('video',dict(**base, segment_id=seg['id']),'0.75')
                self.assertEqual(take['file'],clip.name)
                self.assertEqual(current['shots'][1]['image'],frame.name)
                self.assertEqual(current['shots'][1]['lines'],shot['lines'])
                video=requests[1][2]
                self.assertEqual(video['parameters'],dict(duration=5,resolution='720P',audio=False,shot_type='single'))
                self.assertEqual(base64.b64decode(video['input']['img_url'].split(',')[1]),frame.read_bytes())
                self.assertEqual(requests[2][1],'/api/v1/tasks/station-2')
                self.assertEqual(studio.spending()['used'],2)
                info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
                    'stream=codec_type,width,height:format=duration','-of','json',str(clip)]))
                self.assertEqual(info['streams'],[dict(codec_type='video',width=1280,height=720)])
                self.assertEqual(float(info['format']['duration']),5)


class FlashStationMediaTests(StationMediaTests):
    model = media.FLASH
    price = '0.12'
