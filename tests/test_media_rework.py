"""返工后沿用旧画面必须明确确认；独立数据目录使用自己的 Dify 配置。"""
import os
import unittest
from unittest.mock import patch

from luma import production
from luma import studio
import test_studio


class MediaReworkTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def frame(self, name):
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:size=64x36', '-frames:v', '1', str(studio.MEDIA / name)])
        return name

    def act(self, action, **kw):
        body = {'project_id': self.p['id'], 'revision': self.p['revision'], 'action': action, 'shot_id': 's1'}
        body.update(kw)
        self.p = studio.edit_production(body)
        return self.p['shots'][0]

    def import_and_select(self, name):
        shot = self.act('add_take', kind='image', file=self.frame(name))
        return self.act('select_take', take_id=shot['takes'][-1]['id'])

    def approve(self):
        self.p['shots'][0].update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])

    def rework(self, text='旅人停在站台边'):
        self.p['shots'][0]['description'] = text
        self.p = studio.save(self.p, self.p['revision'])

    def readiness(self):
        return production.readiness(self.p, self.p['episodes'][0]['id'])

    def test_fresh_import_needs_no_extra_confirmation(self):
        self.add_shot()
        self.import_and_select('a.png')
        self.approve()
        self.assertTrue(self.readiness()['can_export'])

    def test_rework_keeps_old_frame_but_blocks_approval_until_confirmed(self):
        self.add_shot()
        self.import_and_select('a.png')
        self.approve()
        self.rework()
        self.assertEqual(self.p['shots'][0]['image'], 'a.png')
        self.assertIn('修改前', self.readiness()['shots'][0]['reason'])
        self.assertTrue(self.readiness()['shots'][0]['stale_media'])
        with self.assertRaisesRegex(ValueError, '修改前'):
            self.approve()
        self.act('confirm_media')
        self.approve()
        self.assertTrue(self.readiness()['can_export'])

    def test_new_import_after_rework_is_current(self):
        self.add_shot()
        self.import_and_select('a.png')
        self.rework()
        self.import_and_select('b.png')
        self.approve()
        self.assertIsNone(self.readiness()['shots'][0]['reason'])

    def test_reselecting_an_older_import_after_rework_is_stale(self):
        self.add_shot()
        self.import_and_select('a.png')
        old = self.p['shots'][0]['selected_takes']['image']
        self.rework()
        self.import_and_select('b.png')
        self.act('select_take', take_id=old)
        self.assertIn('修改前', self.readiness()['shots'][0]['reason'])

    def test_media_basis_cannot_be_written_directly(self):
        self.add_shot()
        self.import_and_select('a.png')
        self.rework()
        self.p["shots"][0]["media_basis"] = production.content_basis(self.p['shots'][0])
        with self.assertRaisesRegex(ValueError, '确认'):
            studio.save(self.p, self.p['revision'])

    def test_confirm_requires_selected_visual(self):
        self.add_shot()
        with self.assertRaisesRegex(ValueError, '画面'):
            self.act('confirm_media')

    def test_legacy_shot_without_media_basis_is_judged_by_its_previous_version(self):
        self.add_shot()
        self.import_and_select('a.png')
        with studio.connect() as c:
            p = studio.project(self.p['id'])
            p['shots'][0].pop('media_basis', None)
            c.execute('UPDATE projects SET body=? WHERE id=?', (studio.json.dumps(p, ensure_ascii=False), p['id']))
        self.p = studio.project(self.p['id'])
        self.rework()
        self.assertIn('修改前', self.readiness()['shots'][0]['reason'])

    def test_revision_preview_mentions_stale_frame(self):
        self.add_shot()
        self.import_and_select('a.png')
        p = studio.project(self.p['id'])
        snapshot = production.scope(p, p['episodes'][0]['id'], 's1', '改一下')
        preview = studio.revision_comparison(p, snapshot, {'shots': [{'id': 's1', 'description': '全新的镜头'}]})
        self.assertTrue(any('确认沿用' in e for e in preview['effects']))


    def test_dialogue_change_does_not_stale_the_picture(self):
        self.add_shot()
        self.import_and_select('a.png')
        self.p['shots'][0]['dialogue'] = '末班车来了'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertFalse(self.readiness()['shots'][0]['stale_media'])

    def test_framing_change_stales_the_picture(self):
        self.add_shot()
        self.import_and_select('a.png')
        self.p['shots'][0]['framing'] = '特写'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertTrue(self.readiness()['shots'][0]['stale_media'])


class IsolatedEnvTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown

    def source_root(self, text):
        root = studio.DATA / 'source'
        root.mkdir()
        (root / '.env').write_text(text)
        return root

    def test_isolated_data_dir_keeps_its_own_dify_settings(self):
        root = self.source_root('DIFY_PRODUCTION_KEY=app-from-source\n')
        with patch.object(studio, 'ROOT', root), patch.object(studio, 'DATA_ISOLATED', True), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DIFY_PRODUCTION_KEY', None)
            studio.load_env()
            self.assertNotIn('DIFY_PRODUCTION_KEY', os.environ)
            studio.configure_dify('https://api.dify.ai/v1', 'app-isolated')
            self.assertIn('app-isolated', (studio.DATA / '.env').read_text())
            self.assertEqual((root / '.env').read_text(), 'DIFY_PRODUCTION_KEY=app-from-source\n')

    def test_default_install_still_reads_source_env(self):
        root = self.source_root('DIFY_REVISION_KEY=app-default\n')
        with patch.object(studio, 'ROOT', root), patch.object(studio, 'DATA_ISOLATED', False), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DIFY_REVISION_KEY', None)
            studio.load_env()
            self.assertEqual(os.environ['DIFY_REVISION_KEY'], 'app-default')


if __name__ == '__main__':
    unittest.main()
