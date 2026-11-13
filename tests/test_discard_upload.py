"""被拒绝的上传文件可以清理，但绝不删除作品正在引用的素材。"""
import json
import unittest

from luma import studio
import test_studio


class DiscardUploadTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def test_unreferenced_upload_is_removed(self):
        (studio.MEDIA / 'stray.png').write_bytes(b'x')
        self.assertEqual(studio.discard_upload('stray.png'), {'discarded': 'stray.png'})
        self.assertFalse((studio.MEDIA / 'stray.png').exists())

    def test_media_used_by_a_shot_is_kept(self):
        self.add_shot()
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:size=32x32', '-frames:v', '1', str(studio.MEDIA / 'used.png')])
        body = {'project_id': self.p['id'], 'revision': self.p['revision'], 'action': 'add_take', 'shot_id': 's1', 'kind': 'image', 'file': 'used.png'}
        self.p = studio.edit_production(body)
        with self.assertRaisesRegex(ValueError, '已被作品使用'):
            studio.discard_upload('used.png')
        self.assertTrue((studio.MEDIA / 'used.png').exists())

    def test_path_traversal_is_refused(self):
        with self.assertRaises(ValueError):
            studio.discard_upload('../studio.sqlite')
        self.assertTrue(studio.DB.exists())

    def test_filename_substring_does_not_block_unrelated_discard(self):
        # A job result that mentions "final-a.mp4" must not block discarding the
        # unrelated "a.mp4" (a raw substring match used to do exactly that).
        with studio.connect() as c:
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('j1', self.p['id'], 'video', 'succeeded', '{}',
                       json.dumps({'candidate_file': 'final-a.mp4'}),
                       None, 0, 0, 'once'))
        (studio.MEDIA / 'a.mp4').write_bytes(b'x')
        self.assertEqual(studio.discard_upload('a.mp4'), {'discarded': 'a.mp4'})
        self.assertFalse((studio.MEDIA / 'a.mp4').exists())


if __name__ == '__main__':
    unittest.main()
