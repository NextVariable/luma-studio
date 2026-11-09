import itertools, json, os, unittest
from unittest.mock import patch
import studio, test_studio
from providers import Dify

SECRET = 'app-SECRET-VALUE-0123456789'
BASE = 'https://api.dify.ai/v1'
NONCE = itertools.count()  # id(object()) can repeat, and the dedupe key would then merge two jobs


class ProviderIdentityTests(unittest.TestCase):
    """A job remembers which Dify app it was queued against; it never stores the key itself."""
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def env(self, key=SECRET, base=BASE):
        return patch.dict(os.environ, {'DIFY_SHOTS_KEY': key, 'DIFY_BASE_URL': base})

    def queue(self, kind='shots', **env):
        with self.env(**env):
            jid = studio.enqueue(self.p['id'], kind, {'episode_id': self.p['episodes'][0]['id']}, 'n%d' % next(NONCE))
        return jid

    def payload(self, jid):
        with studio.connect() as c:
            return json.loads(c.execute('select payload from jobs where id=?', (jid,)).fetchone()[0])

    def test_job_freezes_host_key_name_and_fingerprint(self):
        ident = self.payload(self.queue())['provider']
        self.assertEqual(ident['provider'], 'dify')
        self.assertEqual(ident['host'], 'api.dify.ai')
        self.assertEqual(ident['key_env'], 'DIFY_SHOTS_KEY')
        self.assertRegex(ident['key_fingerprint'], r'^[0-9a-f]{12}$')

    def test_secret_and_full_base_url_are_never_stored(self):
        with self.env(base='https://api.dify.ai/v1'):
            jid = studio.enqueue(self.p['id'], 'shots', {'episode_id': self.p['episodes'][0]['id']}, 'z')
        with studio.connect() as c:
            raw = c.execute('select payload from jobs where id=?', (jid,)).fetchone()[0]
        self.assertNotIn(SECRET, raw)
        self.assertNotIn('SECRET', raw)
        self.assertNotIn('/v1', raw.split('"provider"')[1])

    def test_same_key_has_stable_fingerprint_and_other_key_differs(self):
        a = self.payload(self.queue())['provider']['key_fingerprint']
        b = self.payload(self.queue())['provider']['key_fingerprint']
        c = self.payload(self.queue(key='app-another-key-000000'))['provider']['key_fingerprint']
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_production_key_identity_is_recorded_for_shots(self):
        with patch.dict(os.environ, {'DIFY_PRODUCTION_KEY': 'app-production-key-1', 'DIFY_BASE_URL': BASE}):
            jid = studio.enqueue(self.p['id'], 'shots', {'episode_id': self.p['episodes'][0]['id']}, 'p')
        self.assertEqual(self.payload(jid)['provider']['key_env'], 'DIFY_PRODUCTION_KEY')

    def test_export_has_no_provider_identity(self):
        self.add_shot()
        studio.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:size=160x90', '-frames:v', '1', str(studio.MEDIA / 'b.png')])
        s = self.p['shots'][0]
        import production
        production.select_take(s, production.add_take(s, 'image', 'b.png')['id'])
        self.p = studio.save(self.p, self.p['revision'])
        self.p['shots'][0].update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])
        jid = studio.enqueue(self.p['id'], 'export', {}, 'e')
        self.assertNotIn('provider', self.payload(jid))

    def test_matches_when_configuration_is_unchanged(self):
        jid = self.queue()
        with self.env():
            studio.check_provider(self.payload(jid))

    def test_refuses_when_key_changed(self):
        jid = self.queue()
        with self.env(key='app-rotated-key-999999'):
            with self.assertRaisesRegex(ValueError, '应用 Key'):
                studio.check_provider(self.payload(jid))

    def test_refuses_when_host_changed(self):
        jid = self.queue()
        with self.env(base='https://dify.example.com/v1'):
            with self.assertRaisesRegex(ValueError, '地址'):
                studio.check_provider(self.payload(jid))

    def test_legacy_payload_without_identity_is_accepted(self):
        with self.env():
            studio.check_provider({'snapshot': {}})

    def test_check_does_not_leak_the_key_in_its_message(self):
        jid = self.queue()
        with self.env(key='app-rotated-key-999999'):
            try:
                studio.check_provider(self.payload(jid))
            except ValueError as e:
                self.assertNotIn('rotated', str(e))
                self.assertNotIn(SECRET, str(e))

    def test_changed_key_blocks_reconcile_without_calling_dify(self):
        jid = self.queue()
        payload = self.payload(jid)
        with studio.connect() as c:
            c.execute("update jobs set state='interrupted', result=? where id=?", (json.dumps({'run_id': 'remote-run'}), jid))
        with self.env(key='app-rotated-key-999999'), patch.object(Dify, 'listen') as listen, patch.object(Dify, 'run') as run:
            with self.assertRaisesRegex(ValueError, '应用 Key'):
                studio.reconcile_job(self.p['id'], jid)
            studio.work_once()
        listen.assert_not_called()
        run.assert_not_called()

    def test_changed_key_makes_queued_job_fail_instead_of_running_against_another_app(self):
        jid = self.queue()
        with self.env(key='app-rotated-key-999999'), patch.object(Dify, 'run') as run:
            studio.work_once()
        run.assert_not_called()
        with studio.connect() as c:
            row = c.execute('select state, error from jobs where id=?', (jid,)).fetchone()
        self.assertEqual(row['state'], 'failed')
        self.assertIn('应用 Key', row['error'])
        self.assertEqual(studio.spending()['used'], 0)

    def test_public_job_exposes_identity_without_the_fingerprint_secrecy_issue(self):
        jid = self.queue()
        with studio.connect() as c:
            job = studio.public_job(c.execute('select * from jobs where id=?', (jid,)).fetchone())
        self.assertEqual(job['provider']['host'], 'api.dify.ai')
        self.assertNotIn('SECRET', json.dumps(job))


if __name__ == '__main__':
    unittest.main()
