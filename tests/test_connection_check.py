import io
import json
import unittest
from unittest.mock import patch
from providers import Dify


class ConnectionCheckTests(unittest.TestCase):
    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def test_reads_only_metadata_and_does_not_claim_generation(self):
        d = Dify()
        with patch.object(d, 'request', side_effect=[
                self.response({'name': '配音', 'mode': 'workflow', 'private': 'must-not-return'}),
                self.response({'user_input_form': [{'paragraph': {'variable': 'context'}},
                                                  {'file-list': {'variable': 'reference_files'}}]})]) as request:
            result = d.inspect_connection('audio')
        self.assertEqual([c.args for c in request.call_args_list], [('audio', '/info'), ('audio', '/parameters')])
        self.assertTrue(result['connected'])
        self.assertFalse(result['generation_verified'])
        self.assertNotIn('private', result)

    def test_wrong_app_or_incompatible_form_is_rejected(self):
        for mode, form, kind in [('chat', [{'paragraph': {'variable': 'context'}}], 'shots'),
                                 ('workflow', [{'paragraph': {'variable': 'question'}}], 'shots'),
                                 ('workflow', [{'paragraph': {'variable': 'context'}}], 'audio')]:
            d = Dify()
            with self.subTest(mode=mode, kind=kind), patch.object(d, 'request', side_effect=[
                    self.response({'mode': mode}), self.response({'user_input_form': form})]):
                with self.assertRaises(ValueError): d.inspect_connection(kind)

    def test_unknown_kind_never_makes_request(self):
        d = Dify()
        with patch.object(d, 'request') as request, self.assertRaises(ValueError):
            d.inspect_connection('anything')
        request.assert_not_called()
