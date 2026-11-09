import copy, json, os, unittest
from unittest.mock import patch
import studio
import test_studio


class EpisodeTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown

    def two_episodes(self):
        first = self.p['episodes'][0]['id']
        self.p['episodes'].append({'id': 'ep2', 'title': '第二集', 'script': '第二集剧情'})
        self.p['assets'] = [{'id': 'hero', 'name': '旅人', 'kind': 'character'}]
        self.p['shots'] = [dict(id=sid, episode_id=eid, description='站台', duration=2,
                                asset_ids=['hero'], approved=True, needs_review=False)
                           for sid, eid in [('s1', first), ('s2', 'ep2')]]
        self.p = studio.save(self.p, self.p['revision'])
        for s in self.p['shots']:
            s.update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])
        return first

    def test_new_project_has_first_episode(self):
        self.assertEqual(self.p.get('episodes', [{}])[0].get('script'), self.p['script'])

    def test_legacy_project_keeps_shots_and_media(self):
        legacy = copy.deepcopy(self.p)
        legacy.pop('episodes', None)
        legacy['shots'] = [{'id': 'old', 'description': '旧镜头', 'duration': 2, 'asset_ids': []}]
        with studio.connect() as c:
            c.execute('UPDATE projects SET body=? WHERE id=?', (json.dumps(legacy), legacy['id']))
        restored = studio.project(legacy['id'])
        self.assertEqual(restored['shots'][0].get('episode_id'), restored.get('episodes', [{}])[0].get('id'))
        self.assertTrue(restored['shots'][0].get('episode_id'))
        self.assertEqual(restored['revision'], legacy['revision'])

    def test_edit_one_episode_does_not_invalidate_other(self):
        self.two_episodes()
        self.p['episodes'][0]['script'] = '第一集新剧情'
        saved = studio.save(self.p, self.p['revision'])
        self.assertFalse(saved['shots'][0]['approved'])
        self.assertTrue(saved['shots'][1]['approved'])

    def test_shared_asset_new_version_reaches_only_episodes_that_rebind(self):
        self.two_episodes()
        self.p['assets'][0]['name'] = '新人物设定'
        saved = studio.save(self.p, self.p['revision'])
        self.assertTrue(all(s['approved'] for s in saved['shots']))
        saved['shots'][0]['asset_bindings'] = {'hero': saved['assets'][0]['selected_version']}
        saved = studio.save(saved, saved['revision'])
        self.assertFalse(saved['shots'][0]['approved'])
        self.assertTrue(saved['shots'][1]['approved'])

    def test_snapshot_uses_only_target_episode_and_shared_assets(self):
        self.two_episodes()
        with patch.dict(os.environ, {'DIFY_SHOTS_KEY': 'test-not-a-real-key'}):
            jid = studio.enqueue(self.p['id'], 'shots', {'episode_id': 'ep2'}, 'snapshot')
        with studio.connect() as c:
            snapshot = json.loads(c.execute('SELECT payload FROM jobs WHERE id=?', (jid,)).fetchone()[0])['snapshot']
        self.assertEqual([s['id'] for s in snapshot['shots']], ['s2'])
        self.assertEqual(snapshot['script'], '第二集剧情')
        self.assertEqual(snapshot['assets'][0]['id'], 'hero')
        self.assertEqual(snapshot['episode_id'], 'ep2')

    def test_unknown_episode_is_rejected_before_enqueue(self):
        with patch.dict(os.environ, {'DIFY_SHOTS_KEY': 'test-not-a-real-key'}):
            with self.assertRaisesRegex(ValueError, '剧集'):
                studio.enqueue(self.p['id'], 'shots', {'episode_id': 'absent'}, 'bad')

    def test_duplicate_episode_rejected(self):
        self.two_episodes()
        self.p['episodes'].append(copy.deepcopy(self.p['episodes'][0]))
        with self.assertRaises(ValueError):
            studio.save(self.p, self.p['revision'])

    def test_orphan_shot_rejected(self):
        self.two_episodes()
        self.p['shots'][0]['episode_id'] = 'absent'
        with self.assertRaises(ValueError):
            studio.save(self.p, self.p['revision'])

    def test_adopted_shots_go_to_source_episode(self):
        self.two_episodes()
        with patch.dict(os.environ, {'DIFY_SHOTS_KEY': 'test-not-a-real-key'}):
            jid = studio.enqueue(self.p['id'], 'shots', {'episode_id': 'ep2'}, 'adopt')
        studio.update_job(jid, 'succeeded', {'result': {'shots': [{'description': '新镜头', 'duration': 3}]}})
        saved = studio.apply_job(self.p['id'], jid, self.p['revision'])
        self.assertEqual(saved['shots'][-1]['episode_id'], 'ep2')
        self.assertEqual(len([s for s in saved['shots'] if s['episode_id'] == self.p['episodes'][0]['id']]), 1)

    def test_export_selected_episode_ignores_other_unready_episode(self):
        first = self.two_episodes()
        studio.ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24', '-t', '1',
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(studio.MEDIA/'fixture.mp4')])
        self.p['shots'][0]['video'] = 'fixture.mp4'
        self.p = studio.save(self.p, self.p['revision'])
        self.p['shots'][0].update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])
        jid = studio.enqueue(self.p['id'], 'export', {'episode_id': first}, 'export-one')
        studio.work_once()
        with studio.connect() as c:
            job = c.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        self.assertEqual(job['state'], 'succeeded', job['error'])
        self.assertEqual(json.loads(job['result'])['duration'], 2)
