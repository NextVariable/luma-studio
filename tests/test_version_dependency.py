import unittest
import studio, production, test_studio


class VersionDependencyTests(unittest.TestCase):
    """A shot depends on the exact asset version it is bound to, not on the asset's later history."""
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def approve(self):
        for s in self.p['shots']:
            s.update(approved=True, needs_review=False)
        self.p = studio.save(self.p, self.p['revision'])

    def edit(self, **body):
        return studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'], **body))

    def new_version(self, text='红色外套'):
        return self.edit(action='asset_version', asset_id='hero', description=text)

    def test_new_version_leaves_pinned_shot_approved(self):
        self.add_shot();self.approve()
        pinned = self.p['shots'][0]['asset_bindings']['hero']
        self.p = self.new_version()
        s = self.p['shots'][0]
        self.assertEqual(s['asset_bindings']['hero'], pinned)
        self.assertEqual(len(self.p['assets'][0]['versions']), 2)
        self.assertTrue(s['approved'])
        self.assertFalse(s['needs_review'])

    def test_text_edit_of_asset_leaves_pinned_shot_approved(self):
        self.add_shot();self.approve()
        self.p['assets'][0]['description'] = '红色外套'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertTrue(self.p['shots'][0]['approved'])
        self.assertFalse(self.p['shots'][0]['needs_review'])

    def test_rebinding_to_new_version_requires_review(self):
        self.add_shot();self.approve();self.p = self.new_version()
        self.p = self.edit(action='bind_current', shot_id='s1')
        s = self.p['shots'][0]
        self.assertEqual(s['asset_bindings']['hero'], self.p['assets'][0]['selected_version'])
        self.assertFalse(s['approved'])
        self.assertTrue(s['needs_review'])

    def test_asset_kind_change_still_requires_review(self):
        self.add_shot();self.approve()
        self.p['assets'][0]['kind'] = 'scene'
        self.p = studio.save(self.p, self.p['revision'])
        self.assertFalse(self.p['shots'][0]['approved'])
        self.assertTrue(self.p['shots'][0]['needs_review'])

    def test_shot_plan_survives_new_version_of_pinned_asset(self):
        self.add_shot()
        snap = production.scope(self.p, self.p['episodes'][0]['id'], 's1', '近景')
        self.p = self.new_version()
        self.assertTrue(production.fresh(self.p, snap))

    def test_shot_plan_goes_stale_when_shot_is_rebound(self):
        self.add_shot()
        snap = production.scope(self.p, self.p['episodes'][0]['id'], 's1', '近景')
        self.p = self.new_version()
        self.p = self.edit(action='bind_current', shot_id='s1')
        self.assertFalse(production.fresh(self.p, snap))

    def test_episode_plan_follows_selected_version_and_recovers_when_reselected(self):
        self.add_shot()
        first = self.p['assets'][0]['selected_version']
        snap = production.scope(self.p, self.p['episodes'][0]['id'])
        self.p = self.new_version()
        self.assertFalse(production.fresh(self.p, snap))
        self.p = self.edit(action='asset_select', asset_id='hero', version_id=first)
        self.assertTrue(production.fresh(self.p, snap))

    def test_unselected_extra_version_does_not_stale_episode_plan(self):
        self.add_shot()
        snap = production.scope(self.p, self.p['episodes'][0]['id'])
        original = self.p['assets'][0]['selected_version']
        self.p = self.new_version()
        self.p = self.edit(action='asset_select', asset_id='hero', version_id=original)
        self.assertEqual(len(self.p['assets'][0]['versions']), 2)
        self.assertTrue(production.fresh(self.p, snap))

    def test_legacy_snapshot_without_basis_version_keeps_old_rule(self):
        self.add_shot()
        snap = production.scope(self.p, self.p['episodes'][0]['id'], 's1', '近景', legacy=True)
        self.assertNotIn('basis_v', snap)
        self.assertTrue(production.fresh(self.p, snap))
        self.p = self.new_version()
        self.assertFalse(production.fresh(self.p, snap))


if __name__ == '__main__':
    unittest.main()
