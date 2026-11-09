import copy, itertools, os, unittest
from unittest.mock import patch
import studio, test_studio

NONCE = itertools.count()


class AdoptionModeTests(unittest.TestCase):
    """Adopting a whole-episode plan is an explicit append, replace or merge, previewed before it changes anything."""
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def episode(self):
        return self.p['episodes'][0]['id']

    def fixture(self):
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:size=160x90', '-frames:v', '1', str(studio.MEDIA / 'blue.png')])
        return 'blue.png'

    def edit(self, **body):
        self.p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'], **body))

    def plan_job(self, shots, episode_id=None):
        with patch.dict(os.environ, {'DIFY_SHOTS_KEY': 'mock'}):
            jid = studio.enqueue(self.p['id'], 'shots', {'episode_id': episode_id or self.episode()}, 'n%d' % next(NONCE))
        studio.update_job(jid, 'succeeded', {'result': {'shots': shots}})
        return jid

    def apply(self, jid, mode=None):
        self.p = studio.apply_job(self.p['id'], jid, self.p['revision'], mode)
        return self.p

    def episode_shots(self, eid=None):
        return [s for s in self.p['shots'] if s['episode_id'] == (eid or self.episode())]

    PLAN = [{'description': '新方案一', 'duration': 3, 'camera': '推近', 'asset_ids': ['hero']},
            {'description': '新方案二', 'duration': 4, 'asset_ids': ['hero']}]

    def test_default_mode_still_appends(self):
        self.add_shot()
        self.apply(self.plan_job(self.PLAN))
        self.assertEqual([s['description'] for s in self.episode_shots()], ['旅人走向站台', '新方案一', '新方案二'])

    def test_replace_swaps_untouched_episode_shots_and_marks_review(self):
        self.add_shot()
        self.apply(self.plan_job(self.PLAN), 'replace')
        shots = self.episode_shots()
        self.assertEqual([s['description'] for s in shots], ['新方案一', '新方案二'])
        self.assertNotIn('s1', [s['id'] for s in shots])
        self.assertTrue(all(s['needs_review'] and not s['approved'] for s in shots))

    def test_replace_keeps_other_episodes_untouched(self):
        self.add_shot()
        self.p['episodes'].append({'id': 'ep2', 'title': '第二集', 'script': '另一集'})
        self.p['shots'].append({**copy.deepcopy(self.p['shots'][0]), 'id': 'other', 'episode_id': 'ep2', 'takes': []})
        self.p = studio.save(self.p, self.p['revision'])
        self.apply(self.plan_job(self.PLAN), 'replace')
        self.assertEqual([s['id'] for s in self.episode_shots('ep2')], ['other'])

    def test_replace_is_recoverable_from_project_history(self):
        self.add_shot()
        self.apply(self.plan_job(self.PLAN), 'replace')
        with studio.connect() as c:
            bodies = [r[0] for r in c.execute('select body from versions where project_id=?', (self.p['id'],))]
        self.assertTrue(any('旅人走向站台' in b for b in bodies))

    def test_replace_refused_when_a_shot_has_candidates(self):
        self.add_shot()
        self.edit(action='add_take', shot_id='s1', kind='image', file=self.fixture())
        jid = self.plan_job(self.PLAN)
        before = copy.deepcopy(self.p)
        with self.assertRaisesRegex(ValueError, '候选'):
            self.apply(jid, 'replace')
        self.assertEqual(studio.project(before['id'])['revision'], before['revision'])
        self.assertEqual(studio.project(before['id']).get('applied', []), [])

    def test_replace_refused_when_a_shot_is_locked(self):
        self.add_shot()
        self.p['shots'][0]['locked'] = True
        self.p = studio.save(self.p, self.p['revision'])
        with self.assertRaisesRegex(ValueError, '锁定'):
            self.apply(self.plan_job(self.PLAN), 'replace')

    def test_merge_updates_text_but_keeps_identity_media_and_pins(self):
        self.add_shot()
        pinned = self.p['shots'][0]['asset_bindings']['hero']
        self.edit(action='add_take', shot_id='s1', kind='image', file=self.fixture())
        self.edit(action='select_take', shot_id='s1', take_id=self.p['shots'][0]['takes'][0]['id'])
        self.edit(action='set_frame_mode', shot_id='s1', frame_mode='start_own')
        self.p['shots'][0].update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])
        self.apply(self.plan_job(self.PLAN), 'merge')
        first, second = self.episode_shots()
        self.assertEqual(first['id'], 's1')
        self.assertEqual((first['description'], first['duration'], first['camera']), ('新方案一', 3, '推近'))
        self.assertEqual(len(first['takes']), 1)
        self.assertEqual(first['image'], 'blue.png')
        self.assertEqual(first['asset_bindings']['hero'], pinned)
        self.assertEqual(first['frame_mode'], 'start_own')
        self.assertTrue(first['needs_review'] and not first['approved'])
        self.assertNotEqual(second['id'], 's1')
        self.assertEqual(second['description'], '新方案二')

    def test_merge_skips_locked_shot_and_still_adds_the_rest(self):
        self.add_shot()
        self.p['shots'][0]['locked'] = True
        self.p = studio.save(self.p, self.p['revision'])
        self.apply(self.plan_job(self.PLAN), 'merge')
        shots = self.episode_shots()
        self.assertEqual(shots[0]['description'], '旅人走向站台')
        self.assertTrue(shots[0]['locked'])
        self.assertEqual([s['description'] for s in shots[1:]], ['新方案二'])

    def test_merge_keeps_old_shots_beyond_the_plan(self):
        self.add_shot()
        self.p['shots'].append({**copy.deepcopy(self.p['shots'][0]), 'id': 's2', 'description': '多出来的旧镜头', 'takes': []})
        self.p = studio.save(self.p, self.p['revision'])
        self.apply(self.plan_job(self.PLAN[:1]), 'merge')
        self.assertEqual([s['description'] for s in self.episode_shots()], ['新方案一', '多出来的旧镜头'])

    def test_preview_reports_each_shot_and_changes_nothing(self):
        self.add_shot()
        self.p['shots'].append({**copy.deepcopy(self.p['shots'][0]), 'id': 's2', 'description': '旧二', 'takes': []})
        self.p = studio.save(self.p, self.p['revision'])
        jid = self.plan_job(self.PLAN[:1] + self.PLAN[1:] + [{'description': '新方案三', 'duration': 2}])
        before = studio.project(self.p['id'])
        report = studio.adoption_preview(self.p['id'], jid, self.p['revision'], 'merge')
        self.assertEqual([r['action'] for r in report['items']], ['update', 'update', 'new'])
        self.assertEqual(report['items'][0]['old_id'], 's1')
        self.assertEqual(report['counts'], {'new': 1, 'update': 2, 'keep': 0, 'skip_locked': 0, 'remove': 0})
        self.assertEqual(studio.project(self.p['id']), before)

    def test_preview_of_replace_lists_removals_or_the_blocker(self):
        self.add_shot()
        jid = self.plan_job(self.PLAN)
        ok = studio.adoption_preview(self.p['id'], jid, self.p['revision'], 'replace')
        self.assertEqual(ok['counts']['remove'], 1)
        self.assertIsNone(ok['blocked'])
        self.edit(action='add_take', shot_id='s1', kind='image', file=self.fixture())
        blocked = studio.adoption_preview(self.p['id'], jid, self.p['revision'], 'replace')
        self.assertIn('候选', blocked['blocked'])

    def test_unknown_mode_is_rejected(self):
        self.add_shot()
        with self.assertRaisesRegex(ValueError, '采纳方式'):
            self.apply(self.plan_job(self.PLAN), 'overwrite')

    def test_mode_is_only_for_whole_episode_plans(self):
        import test_audit_regressions as t
        t.AuditRegressions.make_job(self)
        with self.assertRaisesRegex(ValueError, '整集分镜'):
            studio.apply_job(self.p['id'], 'j', 1, 'replace')


if __name__ == '__main__':
    unittest.main()
