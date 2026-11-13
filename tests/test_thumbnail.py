"""缩略图：视频和图片都生成一张小 JPG 并缓存；拒绝越界路径。"""
import json
import subprocess
import unittest

import studio
import test_studio


class ThumbnailTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown

    def size(self, path):
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)]))
        return info['streams'][0]['width'], info['streams'][0]['height']

    def test_video_thumbnail_is_small_jpeg_and_cached(self):
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=red:size=1280x720:rate=24', '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(studio.MEDIA / 'v.mp4')])
        out = studio.thumbnail('v.mp4')
        self.assertEqual(out.suffix, '.jpg')
        self.assertEqual(self.size(out), (360, 202))
        stamp = out.stat().st_mtime_ns
        self.assertEqual(studio.thumbnail('v.mp4').stat().st_mtime_ns, stamp)

    def test_image_thumbnail(self):
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:size=800x1200', '-frames:v', '1', str(studio.MEDIA / 'p.png')])
        self.assertEqual(self.size(studio.thumbnail('p.png'))[0], 360)

    def test_traversal_and_missing_are_refused(self):
        for bad in ('../studio.sqlite', '.thumbs', 'nope.mp4'):
            with self.assertRaises(ValueError):
                studio.thumbnail(bad)

    def test_backup_ignores_the_thumbnail_cache(self):
        import local_storage
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:size=64x64', '-frames:v', '1', str(studio.MEDIA / 'p.png')])
        studio.thumbnail('p.png')
        local_storage.backup(studio.DATA, studio.DATA.parent / (studio.DATA.name + '-bk'))
        copied = sorted(p.name for p in (studio.DATA.parent / (studio.DATA.name + '-bk') / 'media').iterdir())
        import shutil
        shutil.rmtree(studio.DATA.parent / (studio.DATA.name + '-bk'))
        self.assertEqual(copied, ['p.png'])


if __name__ == '__main__':
    unittest.main()
