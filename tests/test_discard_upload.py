"""被拒绝的上传文件可以清理，但绝不删除作品正在引用的素材。"""
import unittest

import studio
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


if __name__ == '__main__':
    unittest.main()
