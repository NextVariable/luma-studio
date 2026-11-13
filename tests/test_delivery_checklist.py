"""The delivery checklist reflects local edits and the real export gate."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import production
import studio
import test_studio


class DeliveryChecklistTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    add_shot = test_studio.StudioTests.add_shot

    def test_local_revision_reuses_audio_and_reexports_without_allowance(self):
        self.add_shot()
        pid = self.p['id']
        eid = self.p['episodes'][0]['id']
        self.p['shots'][0]['lines'] = [{'id':'line','speaker_asset_id':'hero','text':'明天见。'}]
        self.p = studio.save(self.p,self.p['revision'])
        studio.set_spending(0)

        def edit(action, **fields):
            self.p = studio.edit_production(dict(project_id=pid,revision=self.p['revision'],
                                                 shot_id='s1',action=action,**fields))

        def checklist():
            return production.readiness(self.p,eid)['shots'][0]

        def approve():
            self.p['shots'][0].update(approved=True,needs_review=False)
            self.p=studio.save(self.p,self.p['revision'])

        def export(nonce):
            jid=studio.enqueue(pid,'export',{'episode_id':eid},nonce)
            self.assertTrue(studio.work_once())
            with studio.connect() as c:
                job=c.execute('SELECT state,result,error FROM jobs WHERE id=?',(jid,)).fetchone()
            self.assertEqual(job['state'],'succeeded',job['error'])
            return json.loads(job['result'])['file']

        with patch('studio.spend',side_effect=AssertionError('external call')):
            initial=checklist()
            self.assertFalse(initial['ready'])
            self.assertIn({'status':'blocked','label':'尚未选用画面','action':'media'},initial['checks'])
            self.assertTrue(any(c['status']=='optional' and c['action']=='dialogue' for c in initial['checks']))
            studio.ffmpeg(['-f','lavfi','-i','color=blue:size=160x90','-frames:v','1',str(studio.MEDIA/'frame.png')])
            studio.ffmpeg(['-f','lavfi','-i','sine=frequency=440','-t','0.5',str(studio.MEDIA/'line.wav')])
            edit('add_take',kind='image',file='frame.png')
            edit('select_take',take_id=self.p['shots'][0]['takes'][-1]['id'])
            edit('add_take',kind='audio',file='line.wav',line_id='line')
            audio_id=self.p['shots'][0]['takes'][-1]['id']
            edit('bind_line_audio',line_id='line',take_id=audio_id)
            approve()
            first=export('first')

            self.p['shots'][0]['framing']='近景'
            self.p=studio.save(self.p,self.p['revision'])
            changed=checklist()
            self.assertIn({'status':'blocked','label':production.MEDIA_STALE,'action':'media'},changed['checks'])
            self.assertIn({'status':'reuse','label':'第 1 句音轨可沿用','action':'dialogue'},changed['checks'])
            self.assertIn({'status':'blocked','label':'需要复核','action':'shot'},changed['checks'])
            with self.assertRaisesRegex(ValueError,'导出前'):
                studio.enqueue(pid,'export',{'episode_id':eid},'blocked')
            edit('confirm_media')
            self.assertFalse(checklist()['ready'])
            approve()
            self.assertTrue(checklist()['ready'])
            second=export('second')

        self.assertNotEqual(first,second)
        for name in (first,second):
            self.assertTrue(Path(studio.media_path(name)).is_file())
            self.assertEqual({s['codec_type'] for s in studio.probe_media(name)['streams']},{'audio','video','subtitle'})
        self.assertEqual(self.p['shots'][0]['lines'][0]['audio_take_id'],audio_id)
        self.assertEqual(studio.spending(),{'remaining':0,'used':0})
