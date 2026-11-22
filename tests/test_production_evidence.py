"""V0.5 acceptance ledger and asset approval selection, with provider responses simulated."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from luma import domestic_media as media, evidence, sample_scene, studio


class ProductionEvidenceTests(TestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory())
        data = Path(tmp)
        self.enterContext(patch.multiple(studio, DATA=data, MEDIA=data/'media', DB=data/'studio.sqlite'))
        self.enterContext(patch.dict('os.environ', ARK_API_KEY='mock-only'))
        self.enterContext(patch('socket.socket.connect', side_effect=AssertionError('network disabled')))
        studio.init()
        self.project = sample_scene.create(studio.MEDIA, studio.save)
        self.episode = self.project['episodes'][0]['id']
        self.image = 'local-frame.png'
        studio.ffmpeg(['-f','lavfi','-i','color=blue:size=640x360','-frames:v','1',str(studio.MEDIA/self.image)])
        studio.set_spending(4)

    def submit(self, kind, payload, nonce):
        quote = studio.preview_job_quote(self.project['id'], kind, payload)
        job = studio.enqueue(self.project['id'], kind, dict(payload, quote_digest=quote['digest']), nonce)
        return job, quote

    def run_simulated(self, response):
        with patch.object(media, 'request', return_value=response), \
                patch('luma.media_bridge.receive', return_value=self.image):
            self.assertTrue(studio.work_once())

    def test_missing_provider_id_is_not_called_a_real_record(self):
        self.assertEqual(evidence.classify({'source':'import'},{}),'local')
        self.assertEqual(evidence.classify({'source':'fal'},{}),'provider_unrecorded')
        self.assertEqual(evidence.classify({'source':'fal'},{'run_id':'task-1'}),'provider')

    def test_shot_and_asset_candidates_expose_cost_time_and_review_evidence(self):
        shot = self.project['shots'][0]
        job, quote = self.submit('image', dict(shot_id=shot['id'],episode_id=self.episode,kind='image',
                                              model=media.FLASH,storyboard=True,storyboard_reference_mode='text'),'evidence-shot')
        self.assertEqual(quote['estimated_cny'],'0.12')
        self.run_simulated({'provider_request_id':'req-shot','data':[{'url':'https://art.invalid/frame'}]})

        asset = self.project['assets'][0]
        version = next(v for v in asset['versions'] if v['id']==asset['selected_version'])
        asset_job, _ = self.submit('asset_image', dict(asset_id=asset['id'],version_id=version['id'],
                                                       episode_id=self.episode,kind='asset_image',
                                                       instruction='四分之三角度，服装清晰。'),'evidence-asset')
        self.run_simulated({'provider_request_id':'req-asset','data':[{'url':'https://art.invalid/look'}]})

        candidates = studio.asset_image_candidates({'project_id':self.project['id'],'asset_id':asset['id']})
        self.assertEqual(len(candidates),1)
        candidate = candidates[0]
        self.assertEqual(candidate['id'],asset_job)
        self.assertEqual(candidate['model'],media.FLASH)
        self.assertEqual(candidate['estimated_cny'],'0.12')
        self.assertTrue(candidate['created'])
        self.assertEqual(candidate['request_id'],'req-asset')
        self.assertFalse(candidate['approved'])

        report = studio.production_evidence({'project_id':self.project['id']})
        self.assertEqual(report['summary']['local'],4)
        self.assertGreaterEqual(report['summary']['provider'],1)
        recorded = next(item for item in report['items'] if item['request_id']=='req-shot')
        self.assertEqual(recorded['evidence_class'],'provider')
        self.assertEqual(recorded['job_state'],'succeeded')
        self.assertFalse(recorded['reviewed'])
        self.assertEqual(recorded['estimated_cny'],'0.12')
        self.assertRegex(report['disclaimer'],'不能作为真实 API 验收证据')

        before = studio.project(self.project['id'])
        saved = studio.approve_asset_image({'project_id':self.project['id'],'asset_id':asset['id'],
                                            'job_id':asset_job,'revision':before['revision'],'select':True})
        approved = next(a for a in saved['assets'] if a['id']==asset['id'])
        self.assertNotEqual(approved['selected_version'],version['id'])
        new_version = next(v for v in approved['versions'] if v.get('source_job_id')==asset_job)
        self.assertEqual(approved['selected_version'],new_version['id'])
        self.assertTrue(any(r['version_id']==new_version['id']
                            for r in saved['creative_brief']['visual_bible']['references']))
        self.assertEqual(studio.production_evidence({'project_id':self.project['id']})['assets'][0]['versions'],
                         len(approved['versions']))

        again = studio.approve_asset_image({'project_id':self.project['id'],'asset_id':asset['id'],
                                            'job_id':asset_job,'revision':saved['revision'],'select':True})
        self.assertEqual(len(again['assets'][0]['versions']),len(approved['versions']))
