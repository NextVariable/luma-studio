from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import preparation, sample_scene, studio


class ReferenceApprovalTests(TestCase):
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

    def unapproved_version(self):
        char = self.character()
        front = self.copy_image('front.png')
        p = studio.edit_production(dict(project_id=self.p['id'], revision=self.p['revision'], action='asset_view',
                                        asset_id=char['id'], view='front', file=front))
        char = self.character(p)
        version = next(v for v in char['versions'] if v['id'] == char['selected_version'])
        return p, char, version, front

    def test_unapproved_views_are_excluded_and_reported(self):
        p, char, version, front = self.unapproved_version()
        p = studio.approve_imported_reference(dict(
            project_id=p['id'], asset_id=char['id'], version_id=version['id'], file=version['file'],
            view='primary', source='只批准主图', revision=p['revision']))
        packet = studio.asset_image_packet(p, dict(asset_id=char['id'], version_id=version['id'],
                                                   instruction='雨夜站台'))
        self.assertEqual([ref['view'] for ref in packet['references']], ['primary'])
        self.assertEqual(packet['approval']['used'][0]['status'], 'approved')
        self.assertEqual([item['view'] for item in packet['approval']['excluded']], ['front'])
        self.assertIn('未批准', packet['approval']['excluded'][0]['reason'])
        self.assertTrue(packet['approval']['requires_confirmation'])

    def test_version_without_approved_view_blocks_until_explicit_opt_in(self):
        p, char, version, front = self.unapproved_version()
        with self.assertRaisesRegex(ValueError, '未批准'):
            studio.asset_image_packet(p, dict(asset_id=char['id'], version_id=version['id'],
                                              instruction='雨夜站台'))
        packet = studio.asset_image_packet(p, dict(asset_id=char['id'], version_id=version['id'],
                                                   instruction='雨夜站台', allow_unapproved=True))
        self.assertEqual({ref['status'] for ref in packet['references']}, {'unapproved'})
        self.assertIn(front, {ref['file'] for ref in packet['references']})
        self.assertIn('尚未批准的视图', packet['instruction'])
        self.assertTrue(packet['approval']['allow_unapproved'])
        self.assertFalse(packet['approval']['requires_confirmation'])

    def test_legacy_approval_without_digest_is_labelled(self):
        p, char, version, front = self.unapproved_version()
        p = studio.approve_imported_reference(dict(
            project_id=p['id'], asset_id=char['id'], version_id=version['id'], file=version['file'],
            view='primary', source='旧版数据', revision=p['revision']))
        stripped = deepcopy(p)
        for ref in stripped['creative_brief']['visual_bible']['references']:
            if ref['asset_id'] == char['id']:
                ref.pop('sha256', None)
        packet = studio.asset_image_packet(stripped, dict(asset_id=char['id'], version_id=version['id'],
                                                          instruction='旧项目'))
        self.assertEqual(packet['references'][0]['status'], 'legacy')

    def test_quote_exposes_exclusions_and_confirmation(self):
        p, char, version, front = self.unapproved_version()
        p = studio.approve_imported_reference(dict(
            project_id=p['id'], asset_id=char['id'], version_id=version['id'], file=version['file'],
            view='primary', source='只批准主图', revision=p['revision']))
        quote = studio.preview_job_quote(p['id'], 'asset_image', dict(asset_id=char['id'],
                                                                      version_id=version['id'], instruction='保持光线'))
        self.assertTrue(quote['requires_approval'])
        self.assertIn('未批准', quote['approval_notice'])
        self.assertEqual([item['view'] for item in quote['excluded_references']], ['front'])
        self.assertEqual([ref['status'] for ref in quote['references']], ['approved'])

    def test_catalog_marks_unapproved_views(self):
        p, char, version, front = self.unapproved_version()
        for shot in p['shots']:
            shot['asset_bindings'][char['id']] = version['id']
        shot = p['shots'][1]
        items = [item for item in preparation.catalog(p, shot) if item.get('asset_id') == char['id']]
        self.assertEqual({(item['view'], item['approved']) for item in items},
                         {('primary', False), ('front', False)})
        self.assertTrue(all(item['approval_status'] == 'unapproved' for item in items))
