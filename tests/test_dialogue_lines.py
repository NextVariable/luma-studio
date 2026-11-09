import json, subprocess, unittest
import studio, production, test_studio


class DialogueLineTests(unittest.TestCase):
    """Per-line dialogue with a speaker. `dialogue` stays as the text every older reader already uses."""
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def two_lines(self):
        return [{'id': 'l1', 'speaker_asset_id': 'hero', 'text': '你来晚了。'},
                {'id': 'l2', 'speaker_asset_id': None, 'text': '雨还没有停。'}]

    def with_lines(self, lines=None, **fields):
        self.add_shot()
        self.p['shots'][0].update(lines=lines if lines is not None else self.two_lines(), **fields)
        self.p = studio.save(self.p, self.p['revision'])
        return self.p['shots'][0]

    def approve(self):
        self.p['shots'][0].update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])

    # --- derivation ---------------------------------------------------------------
    def test_dialogue_is_built_from_lines_with_speaker_names(self):
        s = self.with_lines()
        self.assertEqual(s['dialogue'], '旅人：你来晚了。\n雨还没有停。')

    def test_narration_line_has_no_speaker_prefix(self):
        s = self.with_lines([{'id': 'n', 'speaker_asset_id': None, 'text': '很久以前。'}])
        self.assertEqual(s['dialogue'], '很久以前。')

    def test_shot_without_lines_keeps_its_plain_dialogue_untouched(self):
        self.add_shot()
        self.p['shots'][0]['dialogue'] = '旧对白'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertEqual(self.p['shots'][0]['dialogue'], '旧对白')
        self.assertNotIn('lines', self.p['shots'][0])

    def test_clearing_lines_keeps_the_last_dialogue_text(self):
        s = self.with_lines()
        self.p['shots'][0].pop('lines')
        self.p = studio.save(self.p, self.p['revision'])
        self.assertEqual(self.p['shots'][0]['dialogue'], s['dialogue'])

    def test_renamed_speaker_updates_dialogue_text(self):
        self.with_lines()
        self.p['assets'][0]['name'] = '新旅人'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertEqual(self.p['shots'][0]['dialogue'], '新旅人：你来晚了。\n雨还没有停。')

    # --- validation ---------------------------------------------------------------
    def test_unknown_speaker_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '说话人'):
            self.with_lines([{'id': 'l1', 'speaker_asset_id': 'ghost', 'text': 'x'}])

    def test_speaker_must_be_a_character(self):
        self.add_shot()
        self.p['assets'].append({'id': 'room', 'name': '候车室', 'kind': 'scene', 'version': 1})
        self.p['shots'][0]['lines'] = [{'id': 'l1', 'speaker_asset_id': 'room', 'text': 'x'}]
        with self.assertRaisesRegex(ValueError, '说话人'):
            studio.save(self.p, self.p['revision'])

    def test_empty_text_duplicate_ids_and_overlong_lines_are_rejected(self):
        for bad in ([{'id': 'a', 'speaker_asset_id': None, 'text': '  '}],
                    [{'id': 'a', 'speaker_asset_id': None, 'text': 'x'}, {'id': 'a', 'speaker_asset_id': None, 'text': 'y'}],
                    [{'id': 'a', 'speaker_asset_id': None, 'text': 'x' * 2001}],
                    [{'id': 'a', 'speaker_asset_id': None, 'text': 'x'}] * 51,
                    'not a list'):
            with self.assertRaisesRegex(ValueError, '对白'):
                self.with_lines(bad)
                self.p = studio.project(self.p['id'])
            self.p = studio.project(self.p['id'])

    # --- review and plan freshness --------------------------------------------------
    def test_changing_a_line_requires_review(self):
        self.with_lines();self.approve()
        self.p['shots'][0]['lines'][0]['text'] = '你终于来了。'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertTrue(self.p['shots'][0]['needs_review'] and not self.p['shots'][0]['approved'])

    def test_changing_a_speaker_requires_review(self):
        self.with_lines();self.approve()
        self.p['shots'][0]['lines'][0]['speaker_asset_id'] = None
        self.p = studio.save(self.p, self.p['revision'])
        self.assertTrue(self.p['shots'][0]['needs_review'])

    def test_lines_are_part_of_the_text_plan(self):
        self.with_lines()
        snap = production.scope(self.p, self.p['episodes'][0]['id'], 's1', '近景')
        self.p['shots'][0]['lines'][1]['text'] = '雨停了。'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertFalse(production.fresh(self.p, snap))

    # --- subtitle timing ------------------------------------------------------------
    def test_timings_split_the_shot_by_text_length_and_fill_it_exactly(self):
        lines = [{'id': 'a', 'speaker_asset_id': None, 'text': '一二三'}, {'id': 'b', 'speaker_asset_id': None, 'text': '一二三四五六七八九'}]
        t = production.line_timings(lines, 4)
        self.assertEqual(t[0][0], 0)
        self.assertAlmostEqual(t[0][1], 1.0, places=3)
        self.assertAlmostEqual(t[1][0], 1.0, places=3)
        self.assertAlmostEqual(t[1][1], 4.0, places=3)

    def test_single_line_takes_the_whole_shot(self):
        self.assertEqual(production.line_timings([{'id': 'a', 'text': '你好', 'speaker_asset_id': None}], 3), [(0, 3)])

    # --- export ---------------------------------------------------------------------
    def export(self):
        studio.ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24', '-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(studio.MEDIA / 'v.mp4')])
        s = self.p['shots'][0]
        production.select_take(s, production.add_take(s, 'video', 'v.mp4')['id'])
        self.p = studio.save(self.p, self.p['revision'])
        self.approve()
        jid = studio.enqueue(self.p['id'], 'export', {}, 'e')
        studio.work_once()
        with studio.connect() as c:
            row = c.execute('select * from jobs where id=?', (jid,)).fetchone()
        self.assertEqual(row['state'], 'succeeded', row['error'])
        return studio.media_path(json.loads(row['result'])['file'])

    def subtitles(self, path):
        return subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:s:0', '-f', 'srt', '-'], capture_output=True, text=True).stdout

    def test_export_writes_one_subtitle_cue_per_line(self):
        self.with_lines(duration=4)
        srt = self.subtitles(self.export())
        self.assertIn('旅人：你来晚了。', srt)
        self.assertIn('雨还没有停。', srt)
        self.assertEqual(srt.count('-->'), 2)

    def test_export_of_plain_dialogue_is_still_one_cue(self):
        self.add_shot()
        self.p['shots'][0].update(dialogue='单句字幕', duration=4)
        self.p = studio.save(self.p, self.p['revision'])
        srt = self.subtitles(self.export())
        self.assertEqual(srt.count('-->'), 1)
        self.assertIn('单句字幕', srt)

    def test_manifest_records_the_lines(self):
        self.with_lines(duration=4)
        path = self.export()
        with studio.connect() as c:
            row = c.execute("select result from jobs where kind='export'").fetchone()
        proof = json.loads(studio.media_path(json.loads(row[0])['manifest']).read_text())
        self.assertEqual([l['text'] for l in proof['shots'][0]['lines']], ['你来晚了。', '雨还没有停。'])

    # --- adoption keeps speakers ----------------------------------------------------
    def test_merge_adoption_keeps_lines_when_plan_has_no_dialogue_change(self):
        self.with_lines()
        self.assertIn('lines', self.p['shots'][0])
        self.assertIn('lines', production.PLAN_TEXT_FIELDS)


if __name__ == '__main__':
    unittest.main()
