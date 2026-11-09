import copy, io, json, os, unittest
from unittest.mock import patch
import studio, production, test_studio


class ReferenceModeTests(unittest.TestCase):
    """Roles sent to a Dify media app are explicit; nothing is promoted to a first frame by accident."""
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def image(self, name='blue.png', color='blue'):
        studio.ffmpeg(['-f', 'lavfi', '-i', f'color=c={color}:size=160x90', '-frames:v', '1', str(studio.MEDIA / name)])
        return name

    def select_image(self, shot, name):
        production.select_take(shot, production.add_take(shot, 'image', name)['id'])

    def setup_pair(self, previous_media='image'):
        """hero has a reference file; s1 -> s2 continuity; the chosen media of s1 depends on the test."""
        self.add_shot()
        ref = self.image('hero.png', 'red')
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'], action='asset_version',
                                             asset_id='hero', description='蓝色外套', file=ref))
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'], action='bind_current', shot_id='s1'))
        s1 = self.p['shots'][0]
        s2 = {**copy.deepcopy(s1), 'id': 's2', 'continuity_from': 's1', 'takes': [], 'selected_takes': {}}
        for k in ('image', 'video', 'audio'):
            s2.pop(k, None)
        self.p['shots'].append(s2)
        if previous_media == 'image':
            self.select_image(s1, self.image('prev.png', 'green'))
        elif previous_media == 'video':
            s1['video'] = 'prev.mp4'
            s1['takes'].append({'id': 'v1', 'kind': 'video', 'file': 'prev.mp4', 'label': 'x', 'source': 'import', 'created': 0})
            s1['selected_takes']['video'] = 'v1'
            (studio.MEDIA / 'prev.mp4').write_bytes(b'x')
        self.p = studio.save(self.p, self.p['revision'])
        return ref

    def set_mode(self, shot_id, mode):
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
                                             action='set_frame_mode', shot_id=shot_id, frame_mode=mode))

    def test_own_selected_image_is_not_promoted_to_first_frame_by_default(self):
        self.add_shot()
        self.select_image(self.p['shots'][0], self.image())
        self.p = studio.save(self.p, self.p['revision'])
        plan = production.reference_plan(self.p, 's1', 'video')
        self.assertNotIn('first_frame', [i['role'] for i in plan['items']])
        self.assertEqual(plan['mode'], 'references')

    def test_asset_files_are_reference_images_with_exact_version(self):
        ref = self.setup_pair()
        item = production.reference_plan(self.p, 's1', 'video')['items'][0]
        self.assertEqual((item['file'], item['role'], item['source']), (ref, 'reference_image', 'asset'))
        self.assertEqual(item['version_id'], self.p['shots'][0]['asset_bindings']['hero'])

    def test_strict_own_image_becomes_first_frame_and_lists_dropped_references(self):
        ref = self.setup_pair()
        self.set_mode('s1', 'start_own')
        plan = production.reference_plan(self.p, 's1', 'video')
        self.assertEqual(plan['mode'], 'first_frame')
        self.assertEqual([(i['role'], i['source']) for i in plan['items']], [('first_frame', 'shot_image')])
        self.assertEqual(plan['omitted'][0]['asset_id'], 'hero')
        self.assertIn('首帧', plan['omitted'][0]['reason'])

    def test_strict_own_image_without_selection_is_refused(self):
        self.setup_pair(previous_media=None)
        self.set_mode('s1', 'start_own')
        with self.assertRaisesRegex(ValueError, '首帧'):
            production.reference_plan(self.p, 's1', 'video')

    def test_strict_continuity_uses_previous_image_as_first_frame(self):
        self.setup_pair()
        self.set_mode('s2', 'start_continuity')
        plan = production.reference_plan(self.p, 's2', 'video')
        self.assertEqual(plan['mode'], 'first_frame')
        item = plan['items'][0]
        self.assertEqual((item['role'], item['source'], item['shot_id']), ('first_frame', 'continuity', 's1'))
        self.assertEqual(item['file'], self.p['shots'][0]['image'])

    def test_strict_continuity_refuses_when_previous_shot_has_no_image(self):
        self.setup_pair(previous_media='video')
        self.set_mode('s2', 'start_continuity')
        with self.assertRaisesRegex(ValueError, '承接'):
            production.reference_plan(self.p, 's2', 'video')

    def test_strict_continuity_refuses_without_continuity_shot(self):
        self.setup_pair()
        self.set_mode('s1', 'start_continuity')
        with self.assertRaisesRegex(ValueError, '承接'):
            production.reference_plan(self.p, 's1', 'video')

    def test_reference_mode_sends_previous_image_as_reference_not_frame(self):
        self.setup_pair()
        plan = production.reference_plan(self.p, 's2', 'video')
        prev = [i for i in plan['items'] if i.get('shot_id') == 's1'][0]
        self.assertEqual((prev['role'], prev['source']), ('reference_image', 'continuity'))
        self.assertEqual(plan['mode'], 'references')

    def test_reference_mode_lists_previous_shot_without_image_as_omitted(self):
        self.setup_pair(previous_media='video')
        plan = production.reference_plan(self.p, 's2', 'video')
        self.assertEqual(plan['omitted'][0]['shot_id'], 's1')
        self.assertIn('尾帧', plan['omitted'][0]['reason'])

    def test_image_generation_never_receives_frame_roles(self):
        self.setup_pair()
        self.set_mode('s2', 'start_continuity')
        plan = production.reference_plan(self.p, 's2', 'image')
        self.assertEqual({i['role'] for i in plan['items']}, {'reference_image'})
        self.assertEqual(plan['mode'], 'references')

    def test_media_references_keeps_returning_items(self):
        ref = self.setup_pair()
        self.assertEqual(production.media_references(self.p, 's1')[0]['file'], ref)

    def test_invalid_frame_mode_is_rejected(self):
        self.add_shot()
        self.p['shots'][0]['frame_mode'] = 'anything'
        with self.assertRaisesRegex(ValueError, '承接方式'):
            studio.save(self.p, self.p['revision'])

    def test_changing_frame_mode_does_not_unapprove_or_stale_text_plan(self):
        self.setup_pair()
        for s in self.p['shots']:
            s.update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])
        snap = production.scope(self.p, self.p['episodes'][0]['id'])
        self.set_mode('s2', 'start_continuity')
        self.assertEqual(self.p['shots'][1]['frame_mode'], 'start_continuity')
        self.assertTrue(self.p['shots'][1]['approved'])
        self.assertTrue(production.fresh(self.p, snap))

    def test_job_snapshot_freezes_mode_roles_and_omissions(self):
        self.setup_pair()
        self.set_mode('s1', 'start_own')
        from preparation_fixture import prepare
        prepare(self,'video')
        with patch.dict(os.environ, {'DIFY_VIDEO_KEY': 'mock'}):
            jid = studio.enqueue(self.p['id'], 'video', {'episode_id': self.p['episodes'][0]['id'], 'shot_id': 's1'}, 'n')
        with studio.connect() as c:
            snap = json.loads(c.execute('SELECT payload FROM jobs WHERE id=?', (jid,)).fetchone()[0])['snapshot']
        self.assertEqual(snap['reference_mode'], 'first_frame')
        self.assertEqual([r['role'] for r in snap['reference_media']], ['first_frame'])
        self.assertEqual(snap['reference_omitted'][0]['asset_id'], 'hero')

    def test_enqueue_refuses_strict_start_without_source_image(self):
        self.setup_pair(previous_media=None)
        self.set_mode('s1', 'start_own')
        from preparation_fixture import prepare
        prepare(self,'video')
        with patch.dict(os.environ, {'DIFY_VIDEO_KEY': 'mock'}):
            with self.assertRaisesRegex(ValueError, '首帧'):
                studio.enqueue(self.p['id'], 'video', {'episode_id': self.p['episodes'][0]['id'], 'shot_id': 's1'}, 'n')

    def test_dify_context_carries_mode_roles_and_omissions(self):
        from providers import Dify
        self.setup_pair()
        self.set_mode('s1', 'start_own')
        plan = production.reference_plan(self.p, 's1', 'video')
        snap = production.scope(self.p, self.p['episodes'][0]['id'], 's1')
        snap.update(reference_media=plan['items'], reference_mode=plan['mode'], reference_omitted=plan['omitted'])
        calls = []
        def request(kind, path, body=None, content_type=None):
            calls.append(body)
            return io.BytesIO(b'{"id":"uploaded"}')
        d = Dify()
        with patch.object(d, 'request', side_effect=request), patch.object(d, 'consume', return_value={'state': 'succeeded'}):
            d.run('video', snap, media_path=studio.media_path)
        ctx = json.loads(calls[1]['inputs']['context'])
        self.assertEqual(ctx['reference_mode'], 'first_frame')
        self.assertEqual(ctx['reference_media'][0]['role'], 'first_frame')
        self.assertEqual(ctx['reference_omitted'][0]['asset_id'], 'hero')
        self.assertEqual(len(calls[1]['inputs']['reference_files']), 1)


if __name__ == '__main__':
    unittest.main()
