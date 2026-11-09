import copy,json,subprocess,unittest
from unittest.mock import patch
import studio,production,preparation,test_studio

class AssemblyTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot

    def setup_parts(self):
        self.add_shot();p=self.p;s=p['shots'][0];plan=preparation.seed(p,'s1');one=plan['segments'][0];two=copy.deepcopy(one);one.update(end=1,instruction='A');two.update(id='part2',start=1,instruction='B');plan['segments']=[one,two]
        self.p=studio.save_preparation(p['id'],'s1',p['revision'],plan,preparation.basis(s))['project'];self.ids=[x['id'] for x in plan['segments']]
        for i,color in enumerate(('red','blue')):
            f=f'part{i}.mp4';studio.ffmpeg(['-f','lavfi','-i',f'color=c={color}:size=160x90:rate=24','-f','lavfi','-i',f'sine=frequency={440+i*440}:sample_rate=48000','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(studio.MEDIA/f)])
            self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'add_take','shot_id':'s1','kind':'video','file':f,'label':color})
        ts=self.p['shots'][0]['takes'];self.choices={sid:{'take_id':t['id'],'trim_start':0} for sid,t in zip(self.ids,ts)}
        self.bind(self.choices)

    def bind(self,sources):
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_segment_sources','shot_id':'s1','sources':sources})

    def queue(self,nonce='local'):
        return studio.enqueue(self.p['id'],'assemble',{'shot_id':'s1'},nonce)

    def job(self,jid):
        with studio.connect() as c:return dict(c.execute('select * from jobs where id=?',(jid,)).fetchone())

    def test_real_local_parts_to_selected_shot_to_export_without_provider_or_credit(self):
        self.setup_parts();studio.set_spending(0)
        with patch.object(studio.Dify,'run',side_effect=AssertionError('no provider')):
            jid=self.queue();self.assertEqual(jid,self.queue());studio.work_once();job=self.job(jid);self.assertEqual(job['state'],'succeeded',job['error']);r=json.loads(job['result'])
            p=studio.project(self.p['id']);s=p['shots'][0];self.assertFalse(s.get('video'));t=next(t for t in s['takes'] if t['id']==r['take_id']);self.assertEqual(len(t['assembly']['sources']),2)
            self.p=studio.edit_production({'project_id':p['id'],'revision':p['revision'],'action':'select_take','shot_id':'s1','take_id':t['id']})
            self.assertFalse(production.readiness(self.p,self.p['episodes'][0]['id'])['can_export'])
            self.p['shots'][0].update(dialogue='本地拼接测试');self.p=studio.save(self.p,self.p['revision'])
            opened=studio.open_preparation(self.p['id'],'s1');self.p=studio.save_preparation(self.p['id'],'s1',self.p['revision'],opened['plan'],opened['basis'])['project']
            self.p['shots'][0].update(approved=True,needs_review=False);self.p=studio.save(self.p,self.p['revision'])
            ex=studio.enqueue(self.p['id'],'export',{},'delivery');studio.work_once();job=self.job(ex);self.assertEqual(job['state'],'succeeded',job['error']);result=json.loads(job['result']);info=studio.probe_media(result['file'])
            self.assertEqual({s['codec_type'] for s in info['streams']},{'video','audio','subtitle'});self.assertAlmostEqual(float(info['format']['duration']),2,delta=.2)
            # Decode both halves: prove temporal order, not just a successful command.
            raw=subprocess.check_output(['ffmpeg','-v','error','-ss','0.25','-i',str(studio.media_path(result['file'])),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
            self.assertGreater(raw[0],raw[2])
            raw=subprocess.check_output(['ffmpeg','-v','error','-ss','1.25','-i',str(studio.media_path(result['file'])),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
            self.assertGreater(raw[2],raw[0]);self.assertEqual(studio.spending(),{'remaining':0,'used':0})

    def test_missing_source_blocks_queue(self):
        self.setup_parts();self.bind({})
        with self.assertRaisesRegex(ValueError,'选择素材'):self.queue()

    def test_short_video_is_not_silently_held(self):
        self.setup_parts();self.choices[self.ids[0]]['trim_start']=.5;self.bind(self.choices)
        with self.assertRaisesRegex(ValueError,'长度不足'):self.queue()

    def test_wrong_kind_or_other_shot_candidate_refused(self):
        self.setup_parts();bad=copy.deepcopy(self.choices);bad[self.ids[0]]['take_id']='foreign'
        with self.assertRaises(ValueError):self.bind(bad)

    def test_queue_freezes_files_and_source_selection(self):
        self.setup_parts();jid=self.queue();self.bind({})
        studio.work_once();self.assertEqual(self.job(jid)['state'],'failed')

    def test_changed_file_after_queue_refused(self):
        self.setup_parts();jid=self.queue();studio.ffmpeg(['-f','lavfi','-i','color=c=green:size=160x90:rate=24','-t','1','-c:v','libx264',str(studio.MEDIA/'part0.mp4')]);studio.work_once()
        self.assertEqual(self.job(jid)['state'],'failed')

    def test_locked_or_stale_plan_refused(self):
        self.setup_parts();self.p['shots'][0]['description']='新动作';self.p=studio.save(self.p,self.p['revision'])
        with self.assertRaisesRegex(ValueError,'过期'):self.queue()

    def test_partial_generation_candidates_can_be_assembled_but_not_selected(self):
        self.setup_parts()
        # Set metadata before insertion into a fresh history; existing history is immutable.
        p=self.p;s=p['shots'][0]
        for seg,t in zip(s['preparation']['segments'],s['takes']):
            candidate=production.add_take(s,'video',t['file'],'partial','dify');candidate['generation_segment']={k:seg[k] for k in ('id','start','end')};candidate['generation_segment']['shot_id']=s['id']
            self.choices[seg['id']]['take_id']=candidate['id']
            with self.assertRaisesRegex(ValueError,'局部'):production.select_take(s,candidate['id'])
        self.p=studio.save(p,p['revision']);self.bind(self.choices);jid=self.queue();studio.work_once();self.assertEqual(self.job(jid)['state'],'succeeded',self.job(jid)['error'])

    def test_cancel_during_render_keeps_output_without_adopting_candidate(self):
        self.setup_parts();jid=self.queue();real=studio.export
        def cancelling(snapshot,job):
            result=real(snapshot,job)
            with studio.connect() as c:c.execute("update jobs set state='cancelled' where id=?",(job,))
            return result
        with patch.object(studio,'export',side_effect=cancelling):studio.work_once()
        self.assertEqual(self.job(jid)['state'],'cancelled');self.assertFalse(any(t.get('source')=='assembly' for t in studio.project(self.p['id'])['shots'][0]['takes']))

    def test_selection_changed_during_render_retains_result_but_does_not_attach(self):
        self.setup_parts();jid=self.queue();real=studio.export
        def changed(snapshot,job):
            result=real(snapshot,job);self.bind({});return result
        with patch.object(studio,'export',side_effect=changed):studio.work_once()
        job=self.job(jid);self.assertEqual(job['state'],'failed');self.assertTrue(json.loads(job['result'])['file']);self.assertFalse(any(t.get('source')=='assembly' for t in studio.project(self.p['id'])['shots'][0]['takes']))

if __name__=='__main__':unittest.main()
