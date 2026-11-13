"""Exercise direct generation through the real studio queue with offline API fixtures."""
import base64
import io
import json
import os
import unittest
import wave
from unittest.mock import patch

import openai_direct
import studio
import test_studio


class Response(io.BytesIO):
    headers = {'x-request-id': 'local-test'}


def reply(value):
    return Response(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}],
                               'usage': {'total_tokens': 7}}).encode())


class RealtimeSocket:
    def __init__(self, pcm=bytes(4800), status='completed'):
        self.sent = []
        self.closed = False
        self.events = iter([
            {'type': 'session.created'}, {'type': 'session.updated'},
            {'type': 'response.output_audio.delta', 'delta': base64.b64encode(pcm).decode()},
            {'type': 'response.done', 'response': {'id': 'resp_test', 'status': status, 'usage': {'total_tokens': 20}}},
        ])

    def send(self, event):
        self.sent.append(json.loads(event))

    def recv(self):
        return json.dumps(next(self.events))

    def close(self):
        self.closed = True


class DirectTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def setup_shots(self):
        self.add_shot()
        self.p = studio.edit_production({'project_id': self.p['id'], 'revision': self.p['revision'],
                                         'action': 'character_look', 'asset_id': 'hero',
                                         'outfit': '蓝外套', 'voice_id': 'coral'})
        self.p['shots'][0]['asset_bindings']['hero'] = self.p['assets'][0]['selected_version']
        self.p['shots'][0]['lines'] = [{'id': 'line1', 'text': '明天见。', 'speaker_asset_id': 'hero'}]
        self.p['shots'].append({'id': 's2', 'description': '旅人离开站台', 'duration': 2, 'asset_ids': ['hero']})
        self.p = studio.save(self.p, self.p['revision'])

    def run_job(self, kind, **options):
        jid = studio.enqueue(self.p['id'], kind, {'shot_id': 's1', **options}, kind)
        self.assertTrue(studio.work_once())
        with studio.connect() as conn:
            return studio.public_job(conn.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone())

    def test_audio_keeps_voice_line_and_local_candidate(self):
        self.setup_shots()
        socket = RealtimeSocket()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-offline'}), patch.object(
                openai_direct, 'open_realtime', return_value=socket):
            job = self.run_job('audio', line_id='line1')
        self.assertEqual(job['state'], 'succeeded', job['error'])
        settings, request = socket.sent
        self.assertEqual(settings['session']['audio']['output']['voice'], 'coral')
        self.assertEqual(request['response']['input'][0]['content'][0]['text'], '明天见。')
        self.assertTrue(socket.closed)
        shot = studio.project(self.p['id'])['shots'][0]
        take, = shot['takes']
        self.assertEqual((take['line_id'], take['source']), ('line1', 'openai'))
        with wave.open(str(studio.media_path(take['file'])), 'rb') as audio:
            self.assertEqual((audio.getframerate(),audio.getnframes()),(24000,2400))
        self.assertEqual(studio.spending()['used'], 1)

    def edit_audio(self, action, **fields):
        current = studio.project(self.p['id'])
        return studio.edit_production({'project_id':current['id'],'revision':current['revision'],
                                       'action':action,'shot_id':'s1',**fields})

    def test_late_audio_cannot_bind_to_edited_line_or_another_line(self):
        self.setup_shots()
        socket = RealtimeSocket()
        original_recv = socket.recv
        def recv():
            event = original_recv()
            if json.loads(event)['type']=='response.output_audio.delta':
                self.edit_audio('set_lines',lines=[
                    {'id':'line1','text':'已经改过。','speaker_asset_id':'hero'},
                    {'id':'line2','text':'另一句。','speaker_asset_id':'hero'}])
            return event
        with patch.dict(os.environ, {'OPENAI_API_KEY':'sk-offline'}), patch.object(
                openai_direct,'open_realtime',return_value=socket), patch.object(socket,'recv',side_effect=recv):
            job = self.run_job('audio',line_id='line1')
        self.assertEqual(job['state'],'succeeded')
        self.assertFalse(job['fresh'])
        take = studio.project(self.p['id'])['shots'][0]['takes'][0]
        for line_id,message in [('line1','旧版对白'),('line2','其他对白')]:
            with self.subTest(line_id=line_id), self.assertRaisesRegex(ValueError,message):
                self.edit_audio('bind_line_audio',line_id=line_id,take_id=take['id'])
        with self.assertRaisesRegex(ValueError,'其他对白'):
            self.edit_audio('select_take',take_id=take['id'])
        current = studio.project(self.p['id'])
        current['shots'][0]['lines'][1].update(audio_take_id=take['id'],audio_duration=0.1)
        with self.assertRaisesRegex(ValueError,'其他对白'):
            studio.save(current,current['revision'])

    def test_bound_audio_is_released_when_character_voice_version_changes(self):
        self.setup_shots()
        with patch.dict(os.environ, {'OPENAI_API_KEY':'sk-offline'}), patch.object(
                openai_direct,'open_realtime',return_value=RealtimeSocket()):
            job=self.run_job('audio',line_id='line1')
        self.assertEqual(job['state'],'succeeded')
        pid=self.p['id']
        take=studio.project(pid)['shots'][0]['takes'][0]
        current=self.edit_audio('bind_line_audio',line_id='line1',take_id=take['id'])
        current=studio.edit_production({'project_id':pid,'revision':current['revision'],
                                        'action':'character_look','asset_id':'hero','outfit':'蓝外套','voice_id':'sage'})
        self.assertEqual(current['shots'][0]['lines'][0]['audio_take_id'],take['id'])
        changed=self.edit_audio('bind_asset_version',asset_id='hero',version_id=current['assets'][0]['selected_version'])
        self.assertNotIn('audio_take_id',changed['shots'][0]['lines'][0])
        self.assertEqual(changed['shots'][0]['takes'][0]['id'],take['id'])

    def test_restart_recovers_finished_wav_without_generating_again(self):
        self.setup_shots()
        pid=self.p['id']
        with patch.dict(os.environ, {'OPENAI_API_KEY':'sk-offline'}), patch.object(
                openai_direct,'open_realtime',return_value=RealtimeSocket()) as connect:
            jid=studio.enqueue(pid,'audio',{'shot_id':'s1','line_id':'line1'},'restart')
            update=studio.update_job
            def crash(job_id,state,result=None,error=None):
                if state=='running' and result and result.get('candidate_file'):
                    raise SystemExit()
                return update(job_id,state,result,error)
            with patch.object(studio,'update_job',side_effect=crash), self.assertRaises(SystemExit):
                studio.work_once()
            self.assertTrue((studio.MEDIA/(jid+'.wav')).is_file())
            studio.init()
            with studio.connect() as c:
                job=studio.public_job(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
            self.assertEqual(job['state'],'interrupted')
            self.assertEqual(json.loads(job['result'])['candidate_file'],jid+'.wav')
            studio.reconcile_job(pid,jid)
            self.assertTrue(studio.work_once())
        connect.assert_called_once()
        self.assertEqual(studio.spending()['used'],1)
        take,=studio.project(pid)['shots'][0]['takes']
        self.assertEqual(take['file'],jid+'.wav')

    def test_legacy_voice_is_rejected_before_call_or_allowance(self):
        self.setup_shots()
        current=studio.project(self.p['id'])
        current=studio.edit_production({'project_id':current['id'],'revision':current['revision'],
                                        'action':'character_look','asset_id':'hero','outfit':'蓝外套','voice_id':'nova'})
        self.edit_audio('bind_asset_version',asset_id='hero',version_id=current['assets'][0]['selected_version'])
        with patch.dict(os.environ, {'OPENAI_API_KEY':'sk-offline'}), patch.object(openai_direct,'open_realtime') as connect:
            with self.assertRaisesRegex(ValueError,'不支持当前角色音色'):
                studio.enqueue(self.p['id'],'audio',{'shot_id':'s1','line_id':'line1'},'old-voice')
        connect.assert_not_called()
        self.assertEqual(studio.spending()['used'],0)

    def test_incomplete_realtime_audio_is_not_saved(self):
        self.setup_shots()
        with patch.dict(os.environ, {'OPENAI_API_KEY':'sk-offline'}), patch.object(
                openai_direct,'open_realtime',return_value=RealtimeSocket(status='incomplete')):
            job=self.run_job('audio',line_id='line1')
        self.assertEqual(job['state'],'failed')
        self.assertFalse((studio.MEDIA/(job['id']+'.wav')).exists())

    def test_framing_preserves_neighbours_and_requires_confirmation(self):
        self.setup_shots()
        before = studio.project(self.p['id'])
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-offline'}), patch.object(
                openai_direct, 'open_request', return_value=reply({'id': 's1', 'changes': {'framing': '近景'}})) as send:
            job = self.run_job('revision', instruction='改成近景，人物和对白保持不变')
        send.assert_called_once()
        self.assertEqual(job['state'], 'succeeded', job['error'])
        self.assertEqual(studio.project(self.p['id']), before)
        preview = studio.revision_preview(self.p['id'], job['id'], before['revision'])
        after = studio.apply_job(self.p['id'], job['id'], before['revision'], preview_digest=preview['digest'])
        self.assertEqual(after['shots'][0]['framing'], '近景')
        self.assertEqual(after['shots'][0]['lines'], before['shots'][0]['lines'])
        self.assertEqual(after['shots'][0]['asset_bindings'], before['shots'][0]['asset_bindings'])
        self.assertEqual(after['shots'][1]['description'], before['shots'][1]['description'])

    def test_simple_edit_cannot_smuggle_dialogue_change(self):
        self.setup_shots()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-offline'}), patch.object(
                openai_direct, 'open_request', return_value=reply(
                    {'id': 's1', 'changes': {'framing': '近景', 'dialogue': '另一句。'}})) as send:
            job = self.run_job('revision', instruction='改成近景，人物和对白保持不变')
        self.assertEqual(job['state'], 'failed')
        self.assertIn('保留对白', job['error'])
        send.assert_called_once()

    def test_story_edit_can_be_blocked_by_review(self):
        self.setup_shots()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-offline'}), patch.object(
                openai_direct, 'open_request', side_effect=[
                    reply({'id': 's1', 'changes': {'description': '旅人在站台提前打开信封'}}),
                    reply({'passed': False, 'issues': ['后续镜头与提前拆信冲突']})]) as send:
            job = self.run_job('revision', instruction='让旅人提前拆信')
        self.assertEqual(job['state'], 'blocked', job['error'])
        self.assertEqual(json.loads(job['result'])['result']['issues'], ['后续镜头与提前拆信冲突'])
        self.assertEqual(send.call_count, 2)
        self.assertEqual(studio.spending()['used'], 2)

    def test_second_call_cannot_exceed_authorization(self):
        self.setup_shots()
        studio.set_spending(1)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-offline'}), patch.object(
                openai_direct, 'open_request', return_value=reply(
                    {'id': 's1', 'changes': {'description': '旅人在站台提前打开信封'}})) as send:
            job = self.run_job('revision', instruction='让旅人提前拆信')
        self.assertEqual(job['state'], 'failed')
        self.assertIn('授权已用尽', job['error'])
        send.assert_called_once()
        self.assertEqual(studio.spending(), {'remaining': 0, 'used': 1})
