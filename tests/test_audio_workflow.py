import importlib.util
import io
import json
from pathlib import Path
import unittest

from luma.providers import Dify

spec = importlib.util.spec_from_file_location('build_audio', Path(__file__).parents[1]/'workflows/build_audio.py')
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


class AudioWorkflowTests(unittest.TestCase):
    def intake(self, shot):
        namespace = {}
        exec(audio.INTAKE, namespace)
        return namespace['main'](json.dumps({'revision': 3, 'target_shot_id': 's', 'shots': [shot]}))

    def test_speaks_line_text_without_character_names(self):
        result = self.intake({'id': 's', 'dialogue': '小明：别走', 'lines': [
            {'speaker_asset_id': 'a', 'text': '别走'}, {'speaker_asset_id': 'a', 'text': '等等我'}]})
        self.assertEqual(result['text'], '别走\n等等我')
        self.assertEqual(result['source_revision'], 3)

    def test_multi_speaker_and_silent_shots_stop_before_tts(self):
        for shot in [{'id': 's', 'dialogue': ''}, {'id': 's', 'lines': [
                {'speaker_asset_id': 'a', 'text': '你好'}, {'speaker_asset_id': 'b', 'text': '再见'}]}]:
            with self.assertRaises(ValueError): self.intake(shot)

    def finish(self, files, **metadata):
        event = {'event': 'workflow_finished', 'data': {'status': 'succeeded', 'outputs': {'result': files, **metadata}}}
        return Dify().consume(io.BytesIO(('data: '+json.dumps(event)+'\n\n').encode()),
                              'audio', {'revision': 3, 'target_shot_id': 's'})

    def test_native_file_is_bound_to_snapshot(self):
        result = self.finish([{'type': 'audio', 'url': 'https://files.example/signed.wav'}], source_revision=3, target_shot_id='s')
        self.assertEqual(result['result']['url'], 'https://files.example/signed.wav')

    def test_mismatched_or_ambiguous_audio_is_rejected(self):
        file = {'type': 'audio', 'url': 'https://files.example/signed.wav'}
        cases = [([file], {}), ([file], {'source_revision': 4, 'target_shot_id': 's'}),
                 ([file], {'source_revision': 3, 'target_shot_id': 'other'}),
                 ([file, file], {'source_revision': 3, 'target_shot_id': 's'}),
                 ([{'type': 'audio', 'url': '/private/file.wav'}], {'source_revision': 3, 'target_shot_id': 's'})]
        for files, metadata in cases:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError): self.finish(files, **metadata)

    def test_committed_graph_matches_builder_and_never_retries(self):
        self.assertEqual(json.loads((audio.ROOT/'production/audio-production.yml').read_text()), audio.build())
        graph = audio.build()['workflow']['graph']
        self.assertEqual([n['data']['type'] for n in graph['nodes']], ['start', 'code', 'tool', 'end'])
        self.assertFalse(graph['nodes'][2]['data']['retry_config']['retry_enabled'])


if __name__ == '__main__': unittest.main()
