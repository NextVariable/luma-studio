import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from luma import production, sample_scene, studio


class RehearsalTest(unittest.TestCase):
    def test_sample_recut_and_export_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.multiple(
                studio, DATA=Path(tmp), MEDIA=Path(tmp)/'media', DB=Path(tmp)/'library.sqlite'):
            studio.init()
            project = sample_scene.create(studio.MEDIA, studio.save)
            ep = project['episodes'][0]['id']
            shots = production.rehearsal(project, ep)
            self.assertEqual(sum(s['duration'] for s in shots), 15)
            self.assertEqual(len(shots), 3)
            for shot in shots:
                self.assertEqual(shot['audio'][0]['start'], 0.6)
                self.assertEqual(shot['captions'][0]['start'], 0.6)

            def export(label):
                job = studio.enqueue(project['id'], 'export', {'episode_id':ep}, label)
                studio.work_once()
                with studio.connect() as db:
                    row = db.execute('SELECT state,result,error FROM jobs WHERE id=?', (job,)).fetchone()
                self.assertEqual(row['state'], 'succeeded', row['error'])
                filename = json.loads(row['result'])['file']
                info = studio.probe_media(filename)
                self.assertAlmostEqual(float(info['format']['duration']),15,delta=.1)
                self.assertEqual({s['codec_type'] for s in info['streams']},{'audio','video','subtitle'})
                return filename

            first = export('first')
            middle = project['shots'][1]
            alternative = next(t for t in middle['takes'] if '备选' in t['label'])
            project = studio.edit_production(dict(project_id=project['id'],revision=project['revision'],
                shot_id=middle['id'], action='select_take',take_id=alternative['id']))
            revised = production.rehearsal(project,ep)
            self.assertEqual(revised[1]['clip']['file'],alternative['file'])
            self.assertEqual(shots[1]['audio'],revised[1]['audio'])
            self.assertEqual(shots[::2],revised[::2])
            project['shots'][1].update(approved=True,needs_review=False)
            project=studio.save(project, project['revision'])
            self.assertNotEqual(first,export('second'))
            self.assertTrue(studio.media_path(first).is_file())
            self.assertEqual(studio.spending()['used'],0)


    def test_camera_changes_one_view_of_same_stage(self):
        with tempfile.TemporaryDirectory() as tmp, patch.multiple(
                studio, DATA=Path(tmp), MEDIA=Path(tmp)/'media', DB=Path(tmp)/'library.sqlite'):
            studio.init()
            p=sample_scene.create(studio.MEDIA,studio.save)
            ep=p['episodes'][0]['id']
            before=production.rehearsal(p,ep)
            body=dict(project_id=p['id'],shot_id=p['shots'][1]['id'],revision=p['revision'])
            initial=studio.shot_camera(body)
            camera=dict(view='left',angle=29,distance=2.4)
            preview=studio.shot_camera(dict(body,camera=camera))
            self.assertEqual(initial['actors'],preview['actors'])
            self.assertNotEqual(initial['image'],preview['image'])
            self.assertEqual(p,studio.project(p['id']))
            saved=studio.shot_camera(dict(body,camera=camera),apply=True)
            after=production.rehearsal(saved,ep)
            self.assertEqual(before[::2],after[::2])
            self.assertEqual(before[1]['audio'],after[1]['audio'])
            self.assertTrue(studio.media_path(before[1]['clip']['file']).is_file())
            self.assertEqual(before,after)
            self.assertTrue(saved['shots'][1]['approved'])
            persisted=studio.shot_camera(dict(body,revision=saved['revision']))
            self.assertEqual(camera,persisted['camera'])
            self.assertEqual(preview['image'],persisted['image'])
            with self.assertRaises(ValueError):
                studio.shot_camera(dict(body,camera=camera),apply=True)
            self.assertEqual(studio.spending()['used'],0)
