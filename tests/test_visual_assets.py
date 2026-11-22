from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import domestic_media, production, sample_scene, studio


class VisualAssetTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.files = patch.multiple(studio, DATA=Path(self.tmp.name),
                                    MEDIA=Path(self.tmp.name)/'media', DB=Path(self.tmp.name)/'studio.sqlite')
        self.files.start()
        self.network = patch('socket.socket.connect', side_effect=AssertionError('unexpected network'))
        self.network.start()
        studio.init()
        self.p = sample_scene.create(studio.MEDIA, studio.save)

    def tearDown(self):
        self.network.stop()
        self.files.stop()
        self.tmp.cleanup()

    def character(self, p=None):
        return next(a for a in (p or self.p)['assets'] if a['kind'] == 'character')

    def copy_image(self, name):
        dest = studio.MEDIA/name
        dest.write_bytes(studio.media_path(self.p['shots'][0]['image']).read_bytes())
        return dest.name

    def view(self, p, asset, view, file):
        return studio.edit_production(dict(project_id=p['id'], revision=p['revision'], action='asset_view',
                                           asset_id=asset['id'], view=view, file=file))

    def approve(self, p, asset, file, view, source='本地测试素材', replace=False):
        return studio.approve_imported_reference(dict(
            project_id=p['id'], asset_id=asset['id'], version_id=asset['selected_version'], file=file,
            view=view, source=source, replace=replace, revision=p['revision']))

    def test_views_of_one_version_are_approved_separately_and_stay_pinned(self):
        char = self.character()
        bound = {s['id']: s['asset_bindings'][char['id']] for s in self.p['shots'] if char['id'] in s['asset_bindings']}
        front = self.copy_image('front.png')
        p = self.view(self.p, char, 'front', front)
        char = self.character(p)
        version = next(v for v in char['versions'] if v['id'] == char['selected_version'])
        self.assertEqual(version['file'], char['versions'][0]['file'])
        self.assertEqual(version['views']['front'], front)
        self.assertEqual({s['id']: s['asset_bindings'][char['id']] for s in p['shots'] if char['id'] in s['asset_bindings']}, bound)
        p = self.approve(p, char, version['file'], 'primary')
        p = self.approve(p, char, front, 'front')
        refs = [r for r in p['creative_brief']['visual_bible']['references']
                if r['asset_id'] == char['id'] and r['version_id'] == version['id']]
        self.assertEqual({(r['view'], r['file']) for r in refs}, {('primary', version['file']), ('front', front)})
        with self.assertRaisesRegex(ValueError, '确认替换'):
            self.approve(p, char, front, 'front')
        p = self.approve(p, char, front, 'front', source='替换后的来源', replace=True)
        refs = [r for r in p['creative_brief']['visual_bible']['references']
                if r['asset_id'] == char['id'] and r['version_id'] == version['id']]
        self.assertEqual(len(refs), 2)

    def test_asset_generation_uses_existing_views_and_injects_work_style(self):
        char = self.character()
        p = self.view(self.p, char, 'front', self.copy_image('front.png'))
        char = self.character(p)
        p = self.view(p, char, 'three_quarter', self.copy_image('three-quarter.png'))
        style_file = self.copy_image('style.png')
        p['assets'].append(dict(id='style', kind='style', name='暖色胶片', description='低饱和暖色'))
        production.normalize(p)
        style = next(a for a in p['assets'] if a['kind'] == 'style')
        style['versions'][0]['file'] = style_file
        p = studio.save(p, p['revision'])
        p = self.approve(p, style, style_file, 'primary', source='画风测试')
        char = self.character(p)
        version = next(v for v in char['versions'] if v['id'] == char['selected_version'])
        for view in ('primary', 'front', 'three_quarter'):
            file = version['file'] if view == 'primary' else version['views'][view]
            p = self.approve(p, char, file, view)
        packet = studio.asset_image_packet(p, dict(asset_id=char['id'], version_id=char['selected_version'],
                                                   instruction='保持雨夜氛围'))
        self.assertEqual([r['role'] for r in packet['references']],
                         ['character', 'character', 'character', 'style'])
        self.assertEqual([r['view'] for r in packet['references'][:3]], ['primary', 'front', 'three_quarter'])
        self.assertTrue(all(r['status'] == 'approved' for r in packet['references']))
        self.assertEqual(packet['art_label'], '电影写实')
        self.assertIn('禁止低多边形', packet['instruction'])
        self.assertIn('最后一张参考图', packet['instruction'])
        body = domestic_media.arguments('image', {'generation_segment': packet}, studio.media_path)
        self.assertEqual(len(body['image']), 4)
        awkward = deepcopy(packet)
        awkward['references'] = [packet['references'][-1], *packet['references'][:-1]]
        with self.assertRaises(ValueError):
            domestic_media.arguments('image', {'generation_segment': awkward}, studio.media_path)

    def test_storyboard_prefers_the_approved_view_and_scene_reference(self):
        char = self.character()
        front = self.copy_image('front.png')
        p = self.view(self.p, char, 'front', front)
        char = self.character(p)
        p = self.approve(p, char, front, 'front')
        scene = next(a for a in p['assets'] if a['kind'] == 'scene')
        scene_file = self.copy_image('scene-wide.png')
        p = studio.edit_production(dict(project_id=p['id'], revision=p['revision'], action='asset_version',
                                        asset_id=scene['id'], file=scene_file, label='场景主参考'))
        scene = next(a for a in p['assets'] if a['kind'] == 'scene')
        p = self.approve(p, scene, scene_file, 'primary')
        for shot in p['shots']:
            shot['asset_bindings'][scene['id']] = scene['selected_version']
            shot['asset_bindings'][char['id']] = char['selected_version']
        p = studio.save(p, p['revision'])
        shot = next(s for s in p['shots'] if any(a['name'] == char['name'] for a in p['assets']
                                                 if a['id'] in s['asset_ids'] and a['id'] == char['id']))
        packet = studio.storyboard_packet(p, shot['id'], domestic_media.FLASH)
        roles = [r['role'] for r in packet['references']]
        self.assertIn('scene', roles)
        character = next(r for r in packet['references'] if r.get('asset_id') == char['id'])
        self.assertEqual((character['view'], character['status'], character['file']), ('front', 'approved', front))
        self.assertEqual(next(r for r in packet['references'] if r['role'] == 'scene')['status'], 'approved')

    def test_legacy_reference_without_view_is_still_accepted(self):
        char = self.character()
        version = next(v for v in char['versions'] if v['id'] == char['selected_version'])
        p = deepcopy(self.p)
        p['creative_brief']['visual_bible'] = dict(references=[dict(
            role='character', asset_id=char['id'], version_id=version['id'], file=version['file'],
            source='旧版数据')])
        p = studio.save(p, p['revision'])
        packet = studio.storyboard_packet(p, p['shots'][1]['id'], domestic_media.FLASH)
        reference = next(r for r in packet['references'] if r['role'] == 'character')
        self.assertEqual((reference['status'], reference['view']), ('legacy', 'primary'))

    def test_changed_approved_file_is_rejected_before_generation(self):
        char = self.character()
        front = self.copy_image('front.png')
        p = self.view(self.p, char, 'front', front)
        char = self.character(p)
        p = self.approve(p, char, front, 'front')
        for shot in p['shots']:
            shot['asset_bindings'][char['id']] = char['selected_version']
        p = studio.save(p, p['revision'])
        (studio.MEDIA/front).write_bytes(b'changed after approval')
        with self.assertRaisesRegex(ValueError, '文件发生变化'):
            studio.storyboard_packet(p, p['shots'][1]['id'], domestic_media.FLASH)
        with self.assertRaisesRegex(ValueError, '文件发生变化'):
            studio.asset_image_packet(p, dict(asset_id=char['id'], version_id=char['selected_version'],
                                              instruction='测试'))
