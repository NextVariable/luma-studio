"""Offline acceptance of the fal queue and three-shot delivery using local fixtures."""
import copy
import json
import os
import unittest
from unittest.mock import patch

from luma import fal_media
from luma import studio
from luma.providers import UncertainRun
from test_openai_direct import RealtimeSocket, reply
import test_studio


class FalMediaTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown

    def configure(self):
        self.pid = self.p['id']
        self.eid = self.p['episodes'][0]['id']
        self.p['assets'] = [{'id': 'hero', 'name': '守夜人', 'kind': 'character', 'description': '蓝外套，短发', 'version': 1}]
        self.p = studio.save(self.p, self.p['revision'])
        self.edit('character_look', asset_id='hero', outfit='蓝外套', voice_id='alloy')
        self.edit('asset_version', asset_id='hero', file='anchor.png')
        self.p['shots'] = [
            {'id': f's{i}', 'description': action, 'duration': 5, 'asset_ids': ['hero'],
             'lines': [{'id': f'l{i}', 'speaker_asset_id': 'hero', 'text': line}]}
            for i, (action, line) in enumerate((
                ('守夜人走近信箱', '灯还亮着。'), ('守夜人停下看信', '原来是你。'), ('守夜人抬头望向窗口', '我回来了。')), 1)
        ]
        self.p = studio.save(self.p, self.p['revision'])

    def edit(self, action, **fields):
        self.p = studio.edit_production({
            'project_id': self.pid, 'revision': self.p['revision'], 'action': action, **fields,
        })

    def prepare(self, sid, kind):
        opened = studio.open_preparation(self.pid, sid, kind)
        plan = opened['plan']
        shot = studio.preparation.shot_of(self.p, sid)
        seg = plan['segments'][0]
        is_image = kind == 'image'
        ref = next(r for r in opened['references'] if r['source'] == ('asset' if is_image else 'shot_image'))
        seg.update(kind=kind, model=fal_media.IMAGE if is_image else fal_media.VIDEO,
                   mode='reference_to_image' if is_image else 'image_to_video',
                   instruction=shot['description'], references=[
                       {'reference_id': ref['reference_id'], 'role': 'reference_image' if is_image else 'first_frame'}])
        seg['parameters']['resolution'] = 'auto'
        result = studio.save_preparation(self.pid, sid, self.p['revision'], plan, opened['basis'])
        self.p = result['project']
        self.assertTrue(result['status']['ready'], result['status'])
        return seg['id']

    def run_job(self, kind, nonce, **fields):
        payload={'episode_id':self.eid, **fields}
        if kind!='export':
            before=studio.spending()
            quote=studio.preview_job_quote(self.pid,kind,payload)
            self.assertEqual(studio.spending(),before)
            if kind in ('image','video'):
                self.assertEqual(quote['estimated_usd'], '0.04' if kind=='image' else '0.35')
                with self.assertRaisesRegex(ValueError,'报价已变化'):
                    studio.enqueue(self.pid,kind,{**payload,'quote_digest':'stale'},nonce)
            payload['quote_digest']=quote['digest']
        jid = studio.enqueue(self.pid, kind, payload, nonce)
        self.assertTrue(studio.work_once())
        with studio.connect() as c:
            row = c.execute('SELECT state,error,result FROM jobs WHERE id=?', (jid,)).fetchone()
        self.assertEqual(row['state'], 'succeeded', row['error'])
        self.p = studio.project(self.pid)
        return jid, json.loads(row['result'])

    def select_generated(self, sid, kind, nonce):
        seg = self.prepare(sid, kind)
        job, _ = self.run_job(kind, nonce, shot_id=sid, segment_id=seg)
        shot = studio.preparation.shot_of(self.p, sid)
        take = next(t for t in shot['takes'] if t.get('job_id') == job)
        self.assertEqual(take['source'], 'fal')
        self.edit('select_take', shot_id=sid, take_id=take['id'])

    def approve(self):
        for shot in self.p['shots']:
            shot.update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])

    def test_three_shots_audio_export_revision_and_second_export(self):
        for name, source, args in (
            ('anchor.png', 'color=blue:size=320x180', ['-frames:v', '1']),
            ('fixture.png', 'color=green:size=320x180', ['-frames:v', '1']),
            ('fixture.mp4', 'testsrc2=size=320x180:rate=24', ['-t', '5', '-c:v', 'libx264']),
        ):
            studio.ffmpeg(['-f', 'lavfi', '-i', source, *args, str(studio.MEDIA/name)])
        self.configure()
        paid_posts = []

        def request(path, body=None):
            if body is not None:
                paid_posts.append((path, body))
                return {'request_id': str(len(paid_posts))}
            if path.endswith('/status'):
                return {'status': 'COMPLETED'}
            if 'kling-video' in path:
                return {'video': {'url': 'https://example.invalid/video'}}
            return {'images': [{'url': 'https://example.invalid/image'}]}

        env = {'FAL_KEY': 'test-only', 'OPENAI_API_KEY': 'sk-offline'}
        files = {'image': 'fixture.png', 'video': 'fixture.mp4'}
        with patch.dict(os.environ, env), patch.object(fal_media.Fal, 'request', side_effect=request), \
                patch('luma.media_bridge.receive', side_effect=lambda url, kind, folder: files[kind]), \
                patch('luma.openai_direct.open_realtime', side_effect=lambda key: RealtimeSocket()), \
                patch('luma.openai_direct.open_request', side_effect=[
                    reply({'id':'s2','changes':{'framing':'近景','description':'近景：守夜人停下看信'}}),
                    reply({'passed':True,'issues':[]})]):
            for i in range(1, 4):
                sid = f's{i}'
                self.select_generated(sid, 'image', f'image{i}')
                self.select_generated(sid, 'video', f'video{i}')
                self.assertTrue(studio.open_preparation(self.pid, sid)['status']['ready'])
                line = f'l{i}'
                job, _ = self.run_job('audio', f'audio{i}', shot_id=sid, line_id=line)
                take = next(t for t in self.p['shots'][i-1]['takes'] if t.get('job_id') == job)
                self.edit('bind_line_audio', shot_id=sid, line_id=line, take_id=take['id'])
            self.approve()
            _, first = self.run_job('export', 'first')
            old_shots = copy.deepcopy(self.p['shots'])
            jid, _ = self.run_job('revision', 'revision', shot_id='s2', instruction='改成近景，并调整画面描述，保留角色和对白')
            preview = studio.revision_preview(self.pid, jid, self.p['revision'])
            impact={row['label']:row for row in preview['media_impact']}
            self.assertEqual(impact['第 1 句音轨']['status'],'keep')
            self.assertEqual(impact['整镜视频']['status'],'review')
            self.assertEqual(impact['整镜视频']['replacement']['estimated_usd'],'0.35')
            before_apply=studio.spending()
            self.p = studio.apply_job(self.pid, jid, self.p['revision'], preview_digest=preview['digest'])
            self.assertEqual(studio.spending(),before_apply)
            with self.assertRaisesRegex(ValueError, '导出前'):
                studio.enqueue(self.pid, 'export', {'episode_id': self.eid}, 'premature')
            self.assertEqual(self.p['shots'][1]['lines'], old_shots[1]['lines'])
            self.assertTrue(all(t in self.p['shots'][1]['takes'] for t in old_shots[1]['takes']))
            self.select_generated('s2', 'image', 'image2-rework')
            self.select_generated('s2', 'video', 'video2-rework')
            # The next shot must reconfirm its changed narrative input without spending or replacing media.
            self.assertTrue(studio.open_preparation(self.pid, 's3')['requires_reconfirmation'])
            self.prepare('s3', 'video')
            self.assertEqual([self.p['shots'][i]['selected_takes'] for i in (0, 2)],
                             [old_shots[i]['selected_takes'] for i in (0, 2)])
            self.approve()
            _, second = self.run_job('export', 'second')

        images = [body for path, body in paid_posts if path == '/' + fal_media.IMAGE]
        videos = [body for path, body in paid_posts if path == '/' + fal_media.VIDEO]
        self.assertEqual(len(images), 4)
        self.assertEqual(len({body['image_url'] for body in images}), 1)
        self.assertEqual([body['duration'] for body in videos], ['5'] * 4)
        self.assertNotEqual(first['file'], second['file'])
        for result in (first, second):
            probe = studio.probe_media(result['file'])
            self.assertAlmostEqual(float(probe['format']['duration']), 15, delta=.15)
            self.assertEqual({s['codec_type'] for s in probe['streams']}, {'video', 'audio', 'subtitle'})
        self.assertEqual(studio.spending()['used'], 13)

    def test_workbench_config_and_confirmed_plan_guard(self):
        (studio.MEDIA/'anchor.png').write_bytes(b'isolated-reference')
        self.configure()
        config=studio.DATA/'.env'
        config.write_text('DIFY_BASE_URL=https://api.dify.ai/v1\n')
        with patch.dict(os.environ), patch.object(studio,'env_file',return_value=config):
            os.environ.pop('FAL_KEY',None)
            before=studio.open_preparation(self.pid,'s1')
            self.assertFalse(before['fal_configured'])
            self.assertFalse(before['models'][fal_media.IMAGE]['connected'])
            with self.assertRaises(ValueError):
                studio.configure_fal('invalid\nkey')
            result=studio.configure_fal('fixture-id:fixture-secret')
            self.assertEqual(result,{'configured':True,'verified':False})
            self.assertEqual(config.stat().st_mode & 0o777,0o600)
            self.assertIn('DIFY_BASE_URL=',config.read_text())
            seg=self.prepare('s1','image')
            opened=studio.open_preparation(self.pid,'s1')
            self.assertTrue(opened['models'][fal_media.IMAGE]['connected'])
            self.assertNotIn('fixture-secret',json.dumps(opened))
            fields={'episode_id':self.eid,'shot_id':'s1','segment_id':seg}
            with self.assertRaisesRegex(ValueError,'制作准备已变更'):
                studio.enqueue(self.pid,'image',{**fields,'preparation_digest':'old-plan'},'stale')
            fields['preparation_digest']=opened['status']['plan_digest']
            job=studio.enqueue(self.pid,'image',fields,'once')
            self.assertEqual(studio.enqueue(self.pid,'image',fields,'once'),job)
            with self.assertRaisesRegex(ValueError,'已有生成任务'):
                studio.enqueue(self.pid,'image',fields,'second-click')
            self.assertEqual(studio.spending()['used'],0)

    def test_queue_reconcile_never_submits_twice(self):
        context = {'generation_segment': {'model': fal_media.VIDEO}}
        checkpoint = []
        with patch.object(fal_media.Fal, 'request', side_effect=[{'request_id': 'r1'}, UncertainRun('interrupted')]):
            with self.assertRaises(UncertainRun):
                fal_media.Fal().submit('video', context, {'duration': '5'}, checkpoint.append)
        self.assertEqual(checkpoint[0]['run_id'], 'r1')
        with patch.object(fal_media.Fal, 'request', side_effect=[
            {'status': 'COMPLETED'}, {'video': {'url': 'https://example.invalid/video'}},
        ]) as request:
            result = fal_media.Fal().listen('video', context, checkpoint[0], checkpoint.append)
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual([c.args for c in request.call_args_list],
                         [('/fal-ai/kling-video/requests/r1/status',), ('/fal-ai/kling-video/requests/r1',)])
