import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import quality, sample_scene, studio


class V051RegressionTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.files = patch.multiple(studio, DATA=Path(self.tmp.name),
                                    MEDIA=Path(self.tmp.name) / 'media', DB=Path(self.tmp.name) / 'studio.sqlite')
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
        dest = studio.MEDIA / name
        dest.write_bytes(studio.media_path(self.p['shots'][0]['image']).read_bytes())
        return dest.name

    def test_new_version_does_not_inherit_approvals_or_move_bindings(self):
        char = self.character()
        old_version = char['selected_version']
        old_refs = [r for r in self.p['creative_brief']['visual_bible']['references']
                    if r['asset_id'] == char['id'] and r['version_id'] == old_version]
        self.assertTrue(old_refs)
        bindings = {s['id']: s['asset_bindings'].get(char['id']) for s in self.p['shots']}
        changed = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
                                              action='asset_view', asset_id=char['id'], view='front',
                                              file=self.copy_image('front.png')))
        char = self.character(changed)
        new_version = char['selected_version']
        self.assertNotEqual(new_version, old_version)
        refs = [r for r in changed['creative_brief']['visual_bible']['references']
                if r['asset_id'] == char['id'] and r['version_id'] == new_version]
        self.assertEqual(refs, [])
        self.assertTrue(any(r['asset_id'] == char['id'] and r['version_id'] == old_version
                            for r in changed['creative_brief']['visual_bible']['references']))
        self.assertEqual({s['id']: s['asset_bindings'].get(char['id']) for s in changed['shots']}, bindings)

    def test_selecting_an_old_version_never_rewrites_shot_bindings(self):
        char = self.character()
        old_version = char['selected_version']
        changed = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'],
                                              action='asset_view', asset_id=char['id'], view='front',
                                              file=self.copy_image('front.png')))
        char = self.character(changed)
        self.assertGreater(len(char['versions']), 1)
        bindings = {s['id']: deepcopy(s['asset_bindings']) for s in changed['shots']}
        changed = studio.edit_production(dict(project_id=changed['id'], revision=changed['revision'],
                                              action='asset_select', asset_id=char['id'], version_id=old_version))
        self.assertEqual({s['id']: s['asset_bindings'] for s in changed['shots']}, bindings)

    def test_single_shot_rework_leaves_other_shots_untouched(self):
        p = studio.project(self.p['id'])
        before = {s['id']: deepcopy(s) for s in p['shots']}
        target = p['shots'][0]
        other = p['shots'][1]
        target['takes'].append(dict(id='rework-take', kind='image', file=self.p['shots'][0]['image'],
                                    label='单镜返工', source='import', created=1))
        target['selected_takes'] = {**(target.get('selected_takes') or {}), 'image': 'rework-take'}
        target['image'] = self.p['shots'][0]['image']
        saved = studio.save(p, p['revision'])
        after = studio.project(saved['id'])
        new_target = next(s for s in after['shots'] if s['id'] == target['id'])
        new_other = next(s for s in after['shots'] if s['id'] == other['id'])
        self.assertEqual(new_target['selected_takes']['image'], 'rework-take')
        self.assertEqual(new_target['image'], self.p['shots'][0]['image'])
        for key in ('takes', 'selected_takes', 'image', 'video', 'asset_bindings', 'approved', 'needs_review'):
            self.assertEqual(new_other.get(key), before[other['id']].get(key))

    def test_candidates_label_missing_provider_records(self):
        p = studio.project(self.p['id'])
        shot = p['shots'][0]
        media = self.p['shots'][0]['image']
        shot['takes'] = [
            dict(id='local', kind='image', file=media, label='本机', source='import', created=0),
            dict(id='recorded', kind='image', file=media, label='有记录', source='seedream', job_id='job-recorded', created=0),
            dict(id='missing', kind='image', file=media, label='缺记录', source='seedream', job_id='job-gone', created=0),
        ]
        with studio.connect() as c:
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('job-recorded', p['id'], 'image', 'succeeded',
                       json.dumps(dict(provider=dict(provider='ark'), quote=dict(model='doubao-seedream-5-0-flash-260915'))),
                       json.dumps(dict(provider_request_id='req-123', billing_status='unreconciled')),
                       None, 1, 2, None))
            rows = {row['id']: row for row in quality.candidates(c, p, shot)}
        self.assertEqual(rows['local']['evidence_class'], 'local')
        self.assertEqual(rows['recorded']['evidence_class'], 'provider')
        self.assertEqual(rows['recorded']['provider'], 'ark')
        self.assertEqual(rows['recorded']['request_id'], 'req-123')
        self.assertEqual(rows['missing']['evidence_class'], 'provider_unrecorded')
        self.assertFalse(rows['recorded']['verified'])
