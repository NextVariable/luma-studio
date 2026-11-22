import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import art, domestic_media, preparation, sample_scene, studio, visual


class IndependentAuditTests(TestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.multiple(studio, MEDIA=Path(tmp) / 'media', DB=Path(tmp) / 'test.sqlite'))
        self.enterContext(patch('socket.socket.connect', side_effect=AssertionError('unexpected network')))
        self.enterContext(patch.dict(os.environ, {'ARK_API_KEY': 'offline-test-only', 'DASHSCOPE_API_KEY': 'offline-test-only'}))
        studio.init()
        self.p = sample_scene.create(studio.MEDIA, studio.save)

    def asset(self, role):
        asset = next(a for a in self.p['assets'] if a['kind'] == role)
        version = next(v for v in asset['versions'] if v['id'] == asset['selected_version'])
        return asset, version

    def test_scene_view_upload_can_create_version_and_approve_slot(self):
        scene, original = self.asset('scene')
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
            action='asset_view', asset_id=scene['id'], file=self.p['shots'][0]['image'], view='wide'))
        scene, current = self.asset('scene')
        self.assertNotEqual(original['id'], current['id'])
        self.assertEqual(current['views']['wide'], self.p['shots'][0]['image'])
        self.assertTrue(all(s['asset_bindings'][scene['id']] == original['id'] for s in self.p['shots']))
        self.p = studio.approve_imported_reference(dict(project_id=self.p['id'], revision=self.p['revision'],
            asset_id=scene['id'], version_id=current['id'], file=current['views']['wide'], view='wide', source='实验'))
        states = visual.view_states(current, self.p['creative_brief']['visual_bible']['references'],
                                   'scene', scene['id'], current['id'])
        self.assertEqual(next(row for row in states if row['view'] == 'wide')['status'], 'approved')

    def test_forged_view_is_neither_approved_nor_sent(self):
        actor, version = self.asset('character')
        ref = dict(role='character', asset_id=actor['id'], version_id=version['id'],
                   file=version['file'], source='实验', view='front')
        self.assertEqual(visual.approved_refs([ref], 'character', actor['id'], version['id'], version), [])
        with self.assertRaisesRegex(ValueError, '资产版本'):
            visual.validate_bible({'visual_bible': {'references': [ref]}}, {actor['id']: actor}, studio.media_path)

    def prepared_video(self):
        shot = self.p['shots'][0]
        frame = studio.MEDIA / 'frame.jpg'
        frame.write_bytes(studio.media_path(shot['image']).read_bytes())
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
            action='add_take', shot_id=shot['id'], file=frame.name, kind='image'))
        shot = self.p['shots'][0]
        plan = preparation.seed(self.p, shot['id'])
        first = next(r for r in preparation.catalog(self.p, shot) if r['file'] == frame.name)
        plan['segments'][0].update(model=domestic_media.WAN, mode='image_to_video',
                                   references=[dict(role='first_frame', reference_id=first['reference_id'])])
        plan['segments'][0]['parameters']['resolution'] = '720P'
        self.p = studio.save_preparation(self.p['id'], shot['id'], self.p['revision'], plan, plan['basis'])['project']
        return dict(shot_id=shot['id']), frame

    def test_quote_digest_tracks_video_first_frame_bytes(self):
        body, frame = self.prepared_video()
        quote = studio.preview_job_quote(self.p['id'], 'video', body)
        frame.write_bytes(studio.media_path(self.p['shots'][1]['image']).read_bytes())
        studio.set_spending(1)
        with self.assertRaisesRegex(ValueError, '报价已变化'):
            studio.enqueue(self.p['id'], 'video', dict(body, quote_digest=quote['digest']), 'old-price')
        self.assertEqual(studio.spending(), {'remaining': 1, 'used': 0})

    def test_local_storyboard_uses_only_the_quoted_bytes(self):
        shot = self.p['shots'][1]
        context = {'generation_segment': studio.storyboard_packet(
            self.p, shot['id'], domestic_media.FLASH, reference_mode='text')}
        ref = context['generation_segment']['references'][0]
        body = domestic_media.arguments('image', context, studio.media_path)
        self.assertEqual(hashlib.sha256(base64.b64decode(body['image'][0].split(',', 1)[1])).hexdigest(),
                         ref['reference_id'])
        studio.media_path(ref['file']).write_bytes(studio.media_path(shot['image']).read_bytes())
        with self.assertRaisesRegex(ValueError, '文件内容已变化'):
            domestic_media.arguments('image', context, studio.media_path)

    def test_custom_work_is_not_forced_into_photoreal_or_cel(self):
        for style in ('电影感定格黏土', '非写实水墨', 'porcelain doll', '3D 动画'):
            self.assertEqual(art.resolve({'style': style})['key'], 'custom', style)
        self.assertNotIn('电影写实', art.video_clause({}))
        self.assertIn('水墨留白', art.video_clause({'art_style': 'custom', 'style': '水墨留白'}))

    def asset_job(self, *, unapproved=False):
        asset, version = self.asset('character')
        if unapproved:
            self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
                action='asset_view', asset_id=asset['id'], file=self.p['shots'][0]['image'], view='front'))
            asset, version = self.asset('character')
        body = dict(asset_id=asset['id'], version_id=version['id'], instruction='同一服装', allow_unapproved=unapproved)
        quote = studio.preview_job_quote(self.p['id'], 'asset_image', body)
        studio.set_spending(2)
        jid = studio.enqueue(self.p['id'], 'asset_image', dict(body, quote_digest=quote['digest']), 'asset')
        return jid, dict(body, quote_digest=quote['digest'])

    def job(self, jid):
        with studio.connect() as db:
            return db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()

    def test_explicit_unapproved_opt_in_survives_worker_recheck(self):
        jid, body = self.asset_job(unapproved=True)
        candidate = self.p['shots'][0]['image']
        with patch.object(domestic_media, 'request', return_value={'request_id': 'fake-1',
            'data': [{'url': 'https://example.invalid/out'}]}) as request, \
                patch('luma.media_bridge.receive', return_value=candidate):
            studio.work_once()
        self.assertEqual(self.job(jid)['state'], 'succeeded')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(request.call_args.args[2]['image']), 2)
        self.assertTrue(body['allow_unapproved'])

    def test_failed_download_is_recovered_without_another_paid_submission(self):
        jid, body = self.asset_job()
        candidate = self.p['shots'][0]['image']
        with patch.object(domestic_media, 'request', return_value={'request_id': 'fake-2',
            'data': [{'url': 'https://example.invalid/out'}]}) as request, \
                patch('luma.media_bridge.receive', side_effect=[OSError('download failed'), candidate]):
            studio.work_once()
            self.assertEqual(self.job(jid)['state'], 'interrupted')
            self.assertEqual(studio.enqueue(self.p['id'], 'asset_image', body, 'asset'), jid)
            with self.assertRaisesRegex(ValueError, '已有生成任务'):
                studio.enqueue(self.p['id'], 'asset_image', body, 'different-nonce')
            studio.reconcile_job(self.p['id'], jid)
            studio.work_once()
        self.assertEqual(self.job(jid)['state'], 'succeeded')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(studio.spending(), {'remaining': 1, 'used': 1})

    def test_bill_includes_asset_job_without_a_shot_candidate(self):
        jid, _ = self.asset_job()
        studio.update_job(jid, 'failed', {'provider_request_id': 'fake-3'})
        studio.record_job_bill(dict(project_id=self.p['id'], job_id=jid, actual_cny='0.12', evidence='模拟账单'))
        report = studio.production_evidence({'project_id': self.p['id']})
        self.assertEqual(report['summary']['actual_cny'], '0.12')

    def test_candidate_bytes_cannot_change_after_generation(self):
        jid, _ = self.asset_job()
        file = studio.MEDIA / 'candidate.jpg'
        file.write_bytes(studio.media_path(self.p['shots'][0]['image']).read_bytes())
        output_sha = hashlib.sha256(file.read_bytes()).hexdigest()
        studio.update_job(jid, 'succeeded', {'candidate_file': file.name, 'output_sha256': output_sha})
        file.write_bytes(studio.media_path(self.p['shots'][1]['image']).read_bytes())
        with self.assertRaisesRegex(ValueError, '文件内容已变化'):
            studio.approve_asset_image(dict(project_id=self.p['id'], revision=self.p['revision'], job_id=jid))
        self.assertEqual(studio.project(self.p['id'])['revision'], self.p['revision'])

    def test_malformed_provider_success_keeps_request_id(self):
        jid, _ = self.asset_job()
        with patch.object(domestic_media, 'request', return_value={'request_id': 'fake-4', 'data': []}):
            studio.work_once()
        row = self.job(jid)
        self.assertEqual(row['state'], 'interrupted')
        self.assertEqual(json.loads(row['result'])['provider_request_id'], 'fake-4')

    def test_preparation_rejects_unapproved_asset_used_as_first_frame(self):
        actor, _ = self.asset('character')
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
            action='asset_view', asset_id=actor['id'], file=self.p['shots'][0]['image'], view='front'))
        actor, version = self.asset('character')
        shot = self.p['shots'][1]
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
            action='bind_asset_version', asset_id=actor['id'], shot_id=shot['id'], version_id=version['id']))
        shot = self.p['shots'][1]
        plan = preparation.seed(self.p, shot['id'])
        ref = next(r for r in preparation.catalog(self.p, shot) if r.get('asset_id') == actor['id'] and r['view'] == 'front')
        plan['segments'][0].update(model=domestic_media.WAN, mode='image_to_video',
                                   references=[dict(role='first_frame', reference_id=ref['reference_id'])])
        plan['segments'][0]['parameters']['resolution'] = '720P'
        self.p = studio.save_preparation(self.p['id'], shot['id'], self.p['revision'], plan, plan['basis'])['project']
        with self.assertRaisesRegex(ValueError, '未批准'):
            studio.preview_job_quote(self.p['id'], 'video', dict(shot_id=shot['id']))

    def test_rejected_view_upload_leaves_original_asset_versions_untouched(self):
        scene, _ = self.asset('scene')
        audio = self.p['shots'][0]['takes'][1]['file']
        self.assertTrue(audio.endswith('.wav'))
        with self.assertRaisesRegex(ValueError, 'PNG'):
            studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
                action='asset_view', asset_id=scene['id'], file=audio, view='wide'))
        self.assertEqual(studio.project(self.p['id']), self.p)

    def test_discard_keeps_file_used_only_by_paid_task(self):
        file = studio.MEDIA / '旧输入.jpg'
        file.touch()
        with studio.connect() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('sample', self.p['id'], 'asset_image', 'interrupted',
                 json.dumps({'snapshot': {'reference_media': [{'file': file.name}]}}, ensure_ascii=False),
                 '{}', None, 0, 0, 'once'))
        with self.assertRaisesRegex(ValueError, '已被作品使用'):
            studio.discard_upload(file.name)
        self.assertTrue(file.is_file())

    def test_general_edit_cannot_downgrade_approval_but_can_save_during_file_corruption(self):
        original_refs = self.p['creative_brief']['visual_bible']['references']
        submitted = studio.project(self.p['id'])
        submitted['creative_brief']['visual_bible']['references'][0].pop('sha256')
        with self.assertRaisesRegex(ValueError, '批准或替换'):
            studio.save(submitted, submitted['revision'], reference_actions_only=True)
        self.assertEqual(studio.project(self.p['id'])['creative_brief']['visual_bible']['references'], original_refs)
        file = studio.media_path(original_refs[0]['file'])
        file.write_bytes(studio.media_path(self.p['shots'][1]['image']).read_bytes())
        submitted = studio.project(self.p['id'])
        submitted['title'] = '继续编辑原工程'
        saved = studio.save(submitted, submitted['revision'], reference_actions_only=True)
        with self.assertRaisesRegex(ValueError, '文件发生变化'):
            studio.storyboard_packet(saved, saved['shots'][1]['id'], domestic_media.FLASH)
        self.assertEqual(saved['title'], '继续编辑原工程')

    def test_conflicting_recognized_preset_does_not_build_dual_style_prompt(self):
        brief = dict(art_style='anime', style='电影写实')
        with self.assertRaisesRegex(ValueError, '风格.*冲突'):
            art.constraints(brief, 'storyboard')
        with self.assertRaisesRegex(ValueError, '风格.*冲突'):
            art.video_clause(brief)

    def test_failed_query_keeps_original_task_until_provider_confirms_terminal(self):
        body, _ = self.prepared_video()
        quote = studio.preview_job_quote(self.p['id'], 'video', body)
        studio.set_spending(2)
        body['quote_digest'] = quote['digest']
        jid = studio.enqueue(self.p['id'], 'video', body, 'video')
        with patch.object(domestic_media, 'request', side_effect=[
            {'output': {'task_id': 'video-1'}},
            ValueError('模拟查询凭据错误'),
            {'output': {'task_status': 'FAILED'}},
        ]) as request:
            studio.work_once()
            self.assertEqual(self.job(jid)['state'], 'interrupted')
            self.assertEqual(json.loads(self.job(jid)['result'])['run_id'], 'video-1')
            with self.assertRaisesRegex(ValueError, '已有生成任务'):
                studio.enqueue(self.p['id'], 'video', body, 'new-video')
            studio.reconcile_job(self.p['id'], jid)
            studio.work_once()
        self.assertEqual(self.job(jid)['state'], 'failed')
        self.assertEqual(studio.spending()['used'], 1)
        self.assertEqual([call.args[1] for call in request.call_args_list][1:], ['/api/v1/tasks/video-1'] * 2)

    def test_external_job_endpoint_requires_quote_for_dify_as_well(self):
        self.p = studio.create('新作品', '人物在站台等候。')
        studio.set_spending(1)
        with patch.dict(os.environ, {'DIFY_PRODUCTION_KEY': 'fake-director'}):
            with self.assertRaisesRegex(ValueError, '先确认.*报价'):
                studio.enqueue(self.p['id'], 'shots', {}, 'first', require_quote=True)
        self.assertEqual(studio.spending()['used'], 0)
