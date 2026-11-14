"""HTTP byte-range handling for media and static files.

Browsers seek inside a video with Range requests, so the server has to follow RFC 7233 for
the single-range forms and answer anything it cannot serve with a clean 4xx.
"""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from luma import studio

BODY = b'0123456789ABCDEFGHIJ'


class RangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name).resolve()  # macOS temp dirs are symlinks; the server resolves paths
        cls.web = cls.root / 'web'
        cls.web.mkdir()
        (cls.web / 'probe.bin').write_bytes(BODY)
        (cls.web / 'index.html').write_text('<html></html>')
        cls.root_patch = patch.object(studio, 'ROOT', cls.root)
        cls.root_patch.start()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), studio.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.root_patch.stop()
        cls.tmp.cleanup()

    def get(self, range_header=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Range': range_header} if range_header is not None else {}
        conn.request('GET', '/probe.bin', headers=headers)
        response = conn.getresponse()
        body = response.read()
        result = (response.status, body, response.getheader('Content-Range'), response.getheader('Content-Length'))
        conn.close()
        return result

    def test_no_range_returns_the_whole_file(self):
        status, body, content_range, _ = self.get()
        self.assertEqual((status, body, content_range), (200, BODY, None))

    def test_closed_range(self):
        self.assertEqual(self.get('bytes=0-4')[:3], (206, b'01234', 'bytes 0-4/20'))

    def test_open_ended_range(self):
        self.assertEqual(self.get('bytes=15-')[:3], (206, b'FGHIJ', 'bytes 15-19/20'))

    def test_end_past_the_file_is_clamped(self):
        self.assertEqual(self.get('bytes=15-999')[:3], (206, b'FGHIJ', 'bytes 15-19/20'))

    def test_suffix_range_returns_the_last_bytes(self):
        self.assertEqual(self.get('bytes=-5')[:3], (206, b'FGHIJ', 'bytes 15-19/20'))

    def test_suffix_longer_than_the_file_returns_all_of_it(self):
        self.assertEqual(self.get('bytes=-100')[:3], (206, BODY, 'bytes 0-19/20'))

    def test_content_length_matches_the_body(self):
        status, body, _, length = self.get('bytes=-5')
        self.assertEqual(int(length), len(body))

    def test_unsatisfiable_ranges_get_416(self):
        for value in ('bytes=20-', 'bytes=25-30', 'bytes=5-2', 'bytes=-0'):
            with self.subTest(value=value):
                self.assertEqual(self.get(value)[0], 416)

    def test_malformed_ranges_are_ignored_and_serve_the_whole_file(self):
        for value in ('bytes=abc-', 'bytes=-', 'bytes=', 'bytes=1-2-3', 'items=0-4', 'bytes=0-x'):
            with self.subTest(value=value):
                status, body, content_range, _ = self.get(value)
                self.assertEqual((status, body, content_range), (200, BODY, None))

    def test_multiple_ranges_fall_back_to_the_whole_file(self):
        status, body, _, _ = self.get('bytes=0-0,5-9')
        self.assertEqual((status, body), (200, BODY))

    def test_errors_never_expose_python_exception_text(self):
        for value in ('bytes=abc-', 'bytes=', 'bytes=0-0,5-9'):
            _, body, _, _ = self.get(value)
            self.assertNotIn(b'invalid literal', body)
            self.assertNotIn(b'index out of range', body)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET', '/missing.bin')
        response = conn.getresponse()
        self.assertEqual(response.status, 404)
        self.assertEqual(json.loads(response.read()), {'error': '不存在'})
        conn.close()


if __name__ == '__main__':
    unittest.main()
