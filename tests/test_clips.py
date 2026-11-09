import json, subprocess, unittest
import studio, production, test_studio


class ClipTests(unittest.TestCase):
    """A clip says which candidate a shot cuts from and which part of it. Legacy shots derive one unchanged."""
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def video(self, name='six.mp4', seconds=6):
        studio.ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24', '-t', str(seconds),
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(studio.MEDIA / name)])
        return name

    def shot_with_video(self, **fields):
        self.add_shot()
        s = self.p['shots'][0]
        s.update(fields)
        production.select_take(s, production.add_take(s, 'video', self.video())['id'])
        self.p = studio.save(self.p, self.p['revision'])
        return self.p['shots'][0]

    def edit(self, **body):
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'], **body))
        return self.p['shots'][0]

    def approve(self):
        self.p['shots'][0].update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])

    def export(self):
        self.approve()
        jid = studio.enqueue(self.p['id'], 'export', {}, 'x%s' % id(object()))
        studio.work_once()
        with studio.connect() as c:
            row = c.execute('select * from jobs where id=?', (jid,)).fetchone()
        self.assertEqual(row['state'], 'succeeded', row['error'])
        result = json.loads(row['result'])
        return result, json.loads(studio.media_path(result['manifest']).read_text())

    def test_legacy_shot_derives_a_clip_from_its_selected_media(self):
        s = self.shot_with_video(duration=3, trim_start=1.5)
        c = production.clip_of(s)
        self.assertEqual(c['source_take_id'], s['selected_takes']['video'])
        self.assertEqual((c['kind'], c['file'], c['trim_start'], c['trim_end']), ('video', 'six.mp4', 1.5, None))

    def test_legacy_image_shot_derives_an_image_clip(self):
        self.add_shot()
        s = self.p['shots'][0]
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:size=160x90', '-frames:v', '1', str(studio.MEDIA / 'b.png')])
        production.select_take(s, production.add_take(s, 'image', 'b.png')['id'])
        c = production.clip_of(s)
        self.assertEqual((c['kind'], c['file']), ('image', 'b.png'))

    def test_shot_without_visual_has_no_clip(self):
        self.add_shot()
        self.assertIsNone(production.clip_of(self.p['shots'][0]))

    def test_set_clip_stores_trim_and_refers_to_a_candidate_by_id(self):
        s = self.shot_with_video(duration=2)
        take = s['selected_takes']['video']
        s = self.edit(action='set_clip', shot_id='s1', source_take_id=take, trim_start=1, trim_end=3)
        self.assertEqual(s['clip'], {'source_take_id': take, 'trim_start': 1, 'trim_end': 3})
        self.assertEqual(production.clip_of(s)['file'], 'six.mp4')

    def test_clip_selects_its_candidate_for_preview_and_export(self):
        s = self.shot_with_video(duration=2)
        selected = s['selected_takes']['video']
        self.video('other.mp4', 4)
        other = production.add_take(self.p['shots'][0], 'video', 'other.mp4')
        self.p = studio.save(self.p, self.p['revision'])
        s = self.edit(action='set_clip', shot_id='s1', source_take_id=other['id'], trim_start=0.5)
        self.assertEqual(s['selected_takes']['video'], other['id'])
        self.assertEqual(s['video'], 'other.mp4')
        self.assertEqual(s['trim_start'], 0.5)
        self.assertEqual(production.clip_of(s)['file'], 'other.mp4')

    def test_invalid_trim_is_rejected(self):
        s = self.shot_with_video(duration=2)
        take = s['selected_takes']['video']
        for bad in ({'trim_start': -1}, {'trim_start': 3, 'trim_end': 3}, {'trim_start': 4, 'trim_end': 2}, {'trim_start': 0, 'trim_end': 99999}):
            with self.assertRaisesRegex(ValueError, '裁剪'):
                self.edit(action='set_clip', shot_id='s1', source_take_id=take, **bad)

    def test_unknown_or_audio_candidate_is_rejected(self):
        s = self.shot_with_video(duration=2)
        with self.assertRaisesRegex(ValueError, '候选'):
            self.edit(action='set_clip', shot_id='s1', source_take_id='nope', trim_start=0)
        self.p['shots'][0]['takes'].append({'id': 'a1', 'kind': 'audio', 'file': self.video('a.mp4', 1), 'label': 'x', 'source': 'import', 'created': 0})
        self.p = studio.save(self.p, self.p['revision'])
        with self.assertRaisesRegex(ValueError, '候选'):
            self.edit(action='set_clip', shot_id='s1', source_take_id='a1', trim_start=0)

    def test_clip_pointing_at_a_missing_candidate_fails_validation(self):
        s = self.shot_with_video(duration=2)
        self.p['shots'][0]['clip'] = {'source_take_id': 'gone', 'trim_start': 0, 'trim_end': None}
        with self.assertRaisesRegex(ValueError, '候选'):
            studio.save(self.p, self.p['revision'])

    def test_changing_the_cut_requires_review_but_locked_shot_is_protected(self):
        s = self.shot_with_video(duration=2)
        take = s['selected_takes']['video']
        self.approve()
        s = self.edit(action='set_clip', shot_id='s1', source_take_id=take, trim_start=1)
        self.assertTrue(s['needs_review'] and not s['approved'])
        s['locked'] = True
        self.p = studio.save(self.p, self.p['revision'])
        with self.assertRaisesRegex(ValueError, '锁定'):
            self.edit(action='set_clip', shot_id='s1', source_take_id=take, trim_start=0)

    def test_changing_the_cut_does_not_stale_the_text_plan(self):
        import production as pr
        s = self.shot_with_video(duration=2)
        snap = pr.scope(self.p, self.p['episodes'][0]['id'], 's1', '近景')
        self.edit(action='set_clip', shot_id='s1', source_take_id=s['selected_takes']['video'], trim_start=1)
        self.assertTrue(pr.fresh(self.p, snap))

    def test_selecting_another_video_resets_a_clip_that_pointed_elsewhere(self):
        s = self.shot_with_video(duration=2)
        self.video('other.mp4', 4)
        other = production.add_take(self.p['shots'][0], 'video', 'other.mp4')
        self.p = studio.save(self.p, self.p['revision'])
        self.edit(action='set_clip', shot_id='s1', source_take_id=s['selected_takes']['video'], trim_start=1)
        s = self.edit(action='select_take', shot_id='s1', take_id=other['id'])
        self.assertEqual(production.clip_of(s)['file'], 'other.mp4')
        self.assertEqual(production.clip_of(s)['trim_start'], 0)

    def test_export_uses_trim_end_to_cut_the_requested_window(self):
        s = self.shot_with_video(duration=2)
        self.edit(action='set_clip', shot_id='s1', source_take_id=s['selected_takes']['video'], trim_start=1, trim_end=3)
        result, proof = self.export()
        self.assertAlmostEqual(result['duration'], 2, delta=0.2)
        self.assertEqual(proof['clips'][0]['trim_start'], 1)
        self.assertEqual(proof['clips'][0]['trim_end'], 3)

    def test_export_manifest_records_candidate_ids_not_only_file_names(self):
        s = self.shot_with_video(duration=2)
        take = s['selected_takes']['video']
        result, proof = self.export()
        clip = proof['clips'][0]
        self.assertEqual((clip['shot_id'], clip['source_take_id'], clip['file'], clip['kind']), ('s1', take, 'six.mp4', 'video'))
        self.assertEqual(proof['shots'][0]['video'], 'six.mp4')  # existing manifest keys stay for older readers

    def test_legacy_trim_start_still_cuts_when_no_clip_is_set(self):
        self.shot_with_video(duration=2, trim_start=2)
        result, proof = self.export()
        self.assertAlmostEqual(result['duration'], 2, delta=0.2)
        self.assertEqual(proof['clips'][0]['trim_start'], 2)

    def test_trim_end_shorter_than_shot_duration_is_extended_by_holding_last_frame(self):
        s = self.shot_with_video(duration=3)
        self.edit(action='set_clip', shot_id='s1', source_take_id=s['selected_takes']['video'], trim_start=0, trim_end=1)
        result, proof = self.export()
        self.assertAlmostEqual(result['duration'], 3, delta=0.2)

    def test_delivery_basis_changes_when_the_cut_changes(self):
        s = self.shot_with_video(duration=2)
        before = production.readiness(self.p, self.p['episodes'][0]['id'])['delivery_basis']
        self.edit(action='set_clip', shot_id='s1', source_take_id=s['selected_takes']['video'], trim_start=1, trim_end=3)
        after = production.readiness(self.p, self.p['episodes'][0]['id'])['delivery_basis']
        self.assertNotEqual(before, after)


if __name__ == '__main__':
    unittest.main()
