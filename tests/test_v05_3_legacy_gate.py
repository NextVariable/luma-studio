import hashlib
import os
import unittest
from unittest.mock import patch

import test_studio
from preparation_fixture import PNG_1PX
from luma import preparation, studio

MODEL = 'wan2.6-i2v-flash'


class LegacyPreparationGateTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def legacy(self):
        """A pre-approval work: asset image exists, visual_bible.references was never created."""
        self.add_shot()
        (studio.MEDIA / 'legacy.png').write_bytes(PNG_1PX)
        p = studio.edit_production({'project_id': self.p['id'], 'revision': self.p['revision'],
                                    'action': 'character_look', 'asset_id': 'hero',
                                    'outfit': '蓝外套', 'voice_id': 'alloy'})
        p = studio.edit_production({'project_id': p['id'], 'revision': p['revision'],
                                    'action': 'asset_version', 'asset_id': 'hero', 'file': 'legacy.png'})
        p = studio.edit_production({'project_id': p['id'], 'revision': p['revision'],
                                    'action': 'bind_current', 'shot_id': 's1'})
        p['creative_brief'].pop('visual_bible', None)
        self.p = studio.save(p, p['revision'])
        return self.p

    def approve(self, view='primary', file='legacy.png', source='测试批准'):
        asset = next(a for a in self.p['assets'] if a['id'] == 'hero')
        version = next(v for v in asset['versions'] if v['id'] == asset['selected_version'])
        refs = self.p['creative_brief'].setdefault('visual_bible', {}).setdefault('references', [])
        refs[:] = [r for r in refs if not (r.get('asset_id') == 'hero' and r.get('version_id') == version['id']
                                           and (r.get('view') or 'primary') == view)]
        refs.append(dict(role='character', asset_id='hero', version_id=version['id'], file=file, view=view,
                         source=source, sha256=hashlib.sha256(studio.media_path(file).read_bytes()).hexdigest()))
        self.p = studio.save(self.p, self.p['revision'])

    def bind_plan(self, file='legacy.png'):
        opened = studio.open_preparation(self.p['id'], 's1', 'video')
        chosen = next(r for r in opened['references'] if r['file'] == file)
        plan = opened['plan']
        seg = plan['segments'][0]
        seg.update(model=MODEL, mode='image_to_video',
                   parameters={**seg['parameters'], 'resolution': '720P'},
                   references=[{'reference_id': chosen['reference_id'], 'role': 'first_frame'}])
        self.p = studio.save_preparation(self.p['id'], 's1', self.p['revision'], plan, opened['basis'])['project']
        return seg['id']

    def report(self, allow=False):
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'offline'}):
            return preparation.report(self.p, 's1', studio.media_path, lambda kind: True, allow_unapproved=allow)

    def freeze(self, segment, allow=False):
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'offline'}):
            return preparation.freeze(self.p, 's1', 'video', segment, studio.media_path, lambda kind: True,
                                      allow_unapproved=allow)

    def quote(self, allow):
        payload = {'shot_id': 's1'}
        if allow:
            payload['allow_unapproved'] = True
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'offline'}):
            return studio.preview_job_quote(self.p['id'], 'video', payload)

    def test_legacy_work_is_previewable_but_cannot_freeze_unapproved_assets(self):
        self.legacy()
        segment = self.bind_plan()
        opened = studio.open_preparation(self.p['id'], 's1', 'video')
        item = next(r for r in opened['references'] if r['source'] == 'asset' and r['file'] == 'legacy.png')
        self.assertFalse(item['approved'])
        self.assertEqual(item['approval_status'], 'unapproved')
        self.assertFalse(opened['status']['ready'])
        self.assertIn('尚未批准', '；'.join(i['message'] for i in opened['status']['issues']))
        with self.assertRaisesRegex(ValueError, '尚未批准'):
            self.freeze(segment)

    def test_explicit_opt_in_keeps_quote_and_request_aligned(self):
        self.legacy()
        segment = self.bind_plan()
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'offline'}):
            with self.assertRaisesRegex(ValueError, '制作准备未就绪'):
                self.quote(False)
        blocked = self.report()
        self.assertFalse(blocked['ready'])
        self.assertTrue(blocked['segments'][0]['approval']['requires_confirmation'])
        allowed = self.report(allow=True)
        self.assertTrue(allowed['ready'])
        self.assertTrue(allowed['segments'][0]['approval']['allow_unapproved'])
        self.assertIn('未批准', allowed['segments'][0]['approval']['notice'])
        packet = self.freeze(segment, allow=True)
        self.assertTrue(packet['approval']['allow_unapproved'])
        self.assertEqual(packet['references'][0]['approval_status'], 'unapproved')
        self.assertTrue(packet['references'][0]['sha256'])
        quote = self.quote(True)
        self.assertTrue(quote['approval']['allow_unapproved'])
        self.assertEqual(quote['approval']['unapproved'][0]['file'], 'legacy.png')
        before = studio.spending()
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'offline'}):
            job=studio.enqueue(self.p['id'], 'video', {'shot_id': 's1', 'allow_unapproved': True,
                                                       'quote_digest': quote['digest']}, 'legacy-once')
        self.assertTrue(job)
        self.assertEqual(studio.spending(), before)
        with studio.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='video'").fetchone()[0], 1)

    def test_changed_reference_and_expired_quote_are_refused(self):
        self.legacy()
        self.bind_plan()
        quote = self.quote(True)
        studio.media_path('legacy.png').write_bytes(PNG_1PX + b'changed')
        before = studio.spending()
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'offline'}):
            with self.assertRaisesRegex(ValueError, '生成参数或报价已变化'):
                studio.enqueue(self.p['id'], 'video', {'shot_id': 's1', 'allow_unapproved': True,
                                                       'quote_digest': quote['digest']}, 'changed')
        self.assertEqual(studio.spending(), before)
        studio.media_path('legacy.png').write_bytes(PNG_1PX)
        fresh = self.quote(True)
        with studio.connect() as c:
            c.execute('UPDATE quotes SET created=created-4000 WHERE digest=?', (fresh['digest'],))
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'offline'}):
            with self.assertRaisesRegex(ValueError, '报价已过期'):
                studio.enqueue(self.p['id'], 'video', {'shot_id': 's1', 'allow_unapproved': True,
                                                       'quote_digest': fresh['digest']}, 'expired')
        self.assertEqual(studio.spending(), before)
        with studio.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)

    def test_version_switch_keeps_bindings_and_does_not_inherit_approval(self):
        self.legacy()
        self.approve()
        bound = self.p['shots'][0]['asset_bindings']['hero']
        asset = next(a for a in self.p['assets'] if a['id'] == 'hero')
        version = next(v for v in asset['versions'] if v['id'] == bound)
        self.p = studio.edit_production({'project_id': self.p['id'], 'revision': self.p['revision'],
                                         'action': 'asset_view', 'asset_id': 'hero', 'view': 'side',
                                         'file': 'legacy.png'})
        shot = self.p['shots'][0]
        asset = next(a for a in self.p['assets'] if a['id'] == 'hero')
        current = next(v for v in asset['versions'] if v['id'] == asset['selected_version'])
        self.assertNotEqual(current['id'], bound)
        self.assertEqual(shot['asset_bindings']['hero'], bound)
        self.assertEqual(version['views'], {})
        refs = self.p['creative_brief']['visual_bible']['references']
        self.assertTrue(any(r['version_id'] == bound and r['view'] == 'primary' for r in refs))
        self.assertFalse(any(r['version_id'] == current['id'] for r in refs))

    def test_approved_view_keeps_generation_ready_without_override(self):
        self.legacy()
        self.approve()
        segment = self.bind_plan()
        ready = self.report()
        self.assertTrue(ready['ready'])
        packet = self.freeze(segment)
        self.assertFalse(packet['approval']['allow_unapproved'])
        self.assertTrue(packet['approval']['used'][0]['approval_status'] == 'approved')
        self.assertEqual(packet['references'][0]['sha256'],
                         hashlib.sha256(PNG_1PX).hexdigest())

    def test_unselected_unapproved_view_is_reported_but_not_requested(self):
        self.legacy()
        self.approve(file='legacy.png', view='primary')
        (studio.MEDIA / 'side.png').write_bytes(PNG_1PX)
        self.p = studio.edit_production({'project_id': self.p['id'], 'revision': self.p['revision'],
                                         'action': 'character_look', 'asset_id': 'hero', 'outfit': '蓝外套',
                                         'voice_id': 'alloy', 'views': {'side': 'side.png'}})
        self.p = studio.edit_production({'project_id': self.p['id'], 'revision': self.p['revision'],
                                         'action': 'bind_current', 'shot_id': 's1'})
        # New version inherits nothing; approve only the primary of the new version.
        self.approve(file='legacy.png', view='primary')
        segment = self.bind_plan(file='legacy.png')
        self.assertTrue(self.report()['ready'])
        packet = self.freeze(segment)
        self.assertEqual([r['file'] for r in packet['references']], ['legacy.png'])
        opened = studio.open_preparation(self.p['id'], 's1', 'video')
        side = next(r for r in opened['references'] if r['file'] == 'side.png')
        self.assertEqual(side['approval_status'], 'unapproved')

    def test_local_media_preview_and_editing_still_work(self):
        self.legacy()
        opened = studio.open_preparation(self.p['id'], 's1', 'video')
        item = next(r for r in opened['references'] if r['source'] == 'asset')
        self.assertEqual(item['file'], 'legacy.png')
        self.assertTrue(studio.media_path(item['file']).is_file())
        self.p['shots'][0]['description'] = '旅人停下看信'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertEqual(studio.project(self.p['id'])['shots'][0]['description'], '旅人停下看信')
        self.assertTrue(studio.media_path('legacy.png').is_file())


if __name__ == '__main__':
    unittest.main()
