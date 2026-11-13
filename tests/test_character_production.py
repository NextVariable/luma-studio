import copy, json, os, unittest, wave
from unittest.mock import patch
import studio, production, test_studio
from providers import Dify


class CharacterProductionTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot

    def test_character_look_is_versioned_and_old_shots_keep_their_look(self):
        self.add_shot();old=self.p['shots'][0]['asset_bindings']['hero']
        for name in ('front.png','side.png'):(studio.MEDIA/name).write_bytes(b'fixture')
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
            'action':'character_look','asset_id':'hero','outfit':'雨衣','views':{'front':'front.png','side':'side.png'},'voice_id':'nova'})
        a=self.p['assets'][0];v=a['versions'][-1]
        self.assertEqual(v['outfit'],'雨衣');self.assertEqual(v['voice_id'],'nova')
        self.assertEqual(self.p['shots'][0]['asset_bindings']['hero'],old)
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
            'action':'bind_asset_version','shot_id':'s1','asset_id':'hero','version_id':v['id']})
        refs=production.reference_plan(self.p,'s1','image')['items']
        self.assertEqual({r['file'] for r in refs},{'front.png','side.png'})
        snap=production.scope(self.p,self.p['episodes'][0]['id'],'s1')
        self.assertEqual(snap['assets'][0]['versions'][0]['voice_id'],'nova')

    def test_character_edits_reject_invalid_view_or_voice(self):
        self.add_shot()
        for fields in ({'views':{'unknown':'no.png'}},{'voice_id':'unregistered'}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
                    'action':'character_look','asset_id':'hero',**fields})

    def test_new_outfit_does_not_reuse_images_of_previous_clothing(self):
        self.add_shot();(studio.MEDIA/'coat.png').write_bytes(b'fixture')
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
            'action':'character_look','asset_id':'hero','outfit':'雨衣','views':{'front':'coat.png'}})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
            'action':'character_look','asset_id':'hero','outfit':'西装'})
        self.assertEqual(self.p['assets'][0]['versions'][-1]['views'],{})
        self.assertEqual(self.p['assets'][0]['versions'][-2]['views']['front'],'coat.png')

    def test_general_reference_upload_retains_character_voice_and_outfit(self):
        self.add_shot();(studio.MEDIA/'new.png').write_bytes(b'fixture')
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
            'action':'character_look','asset_id':'hero','outfit':'雨衣','voice_id':'nova'})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
            'action':'asset_version','asset_id':'hero','file':'new.png'})
        v=self.p['assets'][0]['versions'][-1]
        self.assertEqual((v['voice_id'],v['outfit'],v['file']),('nova','雨衣','new.png'))

    def test_generation_unit_freezes_input_and_reference_bytes(self):
        self.add_shot();(studio.MEDIA/'front.png').write_bytes(b'first')
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
            'action':'asset_version','asset_id':'hero','file':'front.png'})
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_current','shot_id':'s1'})
        from preparation_fixture import prepare
        prepare(self,'image')
        with patch.dict(os.environ,{'DIFY_IMAGE_KEY':'test'}):
            jid=studio.enqueue(self.p['id'],'image',{'shot_id':'s1'},'unit')
        with studio.connect() as c:payload=json.loads(c.execute('select payload from jobs where id=?',(jid,)).fetchone()[0])
        unit=payload['generation_unit']
        self.assertEqual(unit['shot_ids'],['s1']);self.assertTrue(unit['references'][0]['sha256'])
        (studio.MEDIA/'front.png').write_bytes(b'changed')
        with patch.dict(os.environ,{'DIFY_IMAGE_KEY':'test'}),patch('studio.Dify.run') as run:
            studio.work_once();run.assert_not_called()
        self.assertEqual(studio.spending()['used'],0)

    def test_audio_line_can_be_generated_without_other_speakers(self):
        self.add_shot();self.p['shots'][0]['lines']=[{'id':'a','text':'你好','speaker_asset_id':'hero'},
            {'id':'b','text':'旁白','speaker_asset_id':None}]
        self.p=studio.save(self.p,self.p['revision'])
        with patch.dict(os.environ,{'OPENAI_API_KEY':'sk-offline'}):
            jid=studio.enqueue(self.p['id'],'audio',{'shot_id':'s1','line_id':'a'},'line')
        with studio.connect() as c:payload=json.loads(c.execute('select payload from jobs where id=?',(jid,)).fetchone()[0])
        self.assertEqual(payload['snapshot']['speech']['line_id'],'a')
        self.assertEqual(payload['snapshot']['speech']['text'],'你好')

    def test_excess_character_references_are_refused_before_queueing(self):
        self.add_shot()
        with patch('production.reference_plan',return_value={'items':[{'file':'view.png'}]*11,'mode':'references','omitted':[]}),patch.dict(os.environ,{'DIFY_IMAGE_KEY':'test'}):
            with self.assertRaisesRegex(ValueError,'制作准备'):studio.enqueue(self.p['id'],'image',{'shot_id':'s1'},'too-many-views')
        with studio.connect() as c:self.assertEqual(c.execute('select count(*) from jobs').fetchone()[0],0)
        self.assertEqual(studio.spending()['used'],0)

    def test_line_audio_is_scheduled_using_measured_length(self):
        self.add_shot();s=self.p['shots'][0]
        s['lines']=[{'id':'a','text':'第一句','speaker_asset_id':'hero'},{'id':'b','text':'第二句','speaker_asset_id':None}]
        for name in ('a.wav','b.wav'):
            with wave.open(str(studio.MEDIA/name),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\0\0'*8000)
            production.add_take(s,'audio',name)
        self.p=studio.save(self.p,self.p['revision'])
        for line,take in zip(('a','b'),self.p['shots'][0]['takes']):
            self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],
                'action':'bind_line_audio','shot_id':'s1','line_id':line,'take_id':take['id']})
        schedule=production.audio_schedule(self.p['shots'][0])
        self.assertEqual([(x['start'],x['end']) for x in schedule],[(0,1),(1,2)])
        studio.ffmpeg(['-f','lavfi','-i','color=c=blue:size=160x90','-frames:v','1',str(studio.MEDIA/'frame.png')])
        s=self.p['shots'][0];production.select_take(s,production.add_take(s,'image','frame.png')['id'])
        self.p=studio.save(self.p,self.p['revision']);self.p['shots'][0].update(approved=True,needs_review=False)
        self.p=studio.save(self.p,self.p['revision'])
        jid=studio.enqueue(self.p['id'],'export',{},'spoken-export');studio.work_once()
        with studio.connect() as c:r=c.execute('select state,error,result from jobs where id=?',(jid,)).fetchone()
        self.assertEqual(r['state'],'succeeded',r['error'])
        import subprocess
        subtitles=subprocess.check_output(['ffmpeg','-v','error','-i',str(studio.MEDIA/json.loads(r['result'])['file']),'-map','0:s:0','-f','srt','-']).decode()
        self.assertIn('00:00:00,000 --> 00:00:01,000',subtitles)
        self.assertIn('00:00:01,000 --> 00:00:02,000',subtitles)
        self.p['shots'][0]['duration']=1
        self.p=studio.save(self.p,self.p['revision'])
        with self.assertRaisesRegex(ValueError,'时长'):production.audio_schedule(self.p['shots'][0])
        self.assertFalse(production.readiness(self.p,self.p['episodes'][0]['id'])['can_export'])

    def test_changed_line_releases_audio_without_deleting_candidate(self):
        self.add_shot();s=self.p['shots'][0]
        (studio.MEDIA/'a.wav').write_bytes(b'fixture');t=production.add_take(s,'audio','a.wav')
        s['lines']=[{'id':'a','text':'旧句','speaker_asset_id':None,'audio_take_id':t['id'],'audio_duration':1}]
        self.p=studio.save(self.p,self.p['revision']);self.p['shots'][0]['lines'][0]['text']='新句'
        self.p=studio.save(self.p,self.p['revision'])
        self.assertNotIn('audio_take_id',self.p['shots'][0]['lines'][0])
        self.assertEqual(len(self.p['shots'][0]['takes']),1)

    def test_saving_lines_allocates_ids_and_preserves_unedited_audio(self):
        self.add_shot()
        pid=self.p['id']
        def edit(**fields):
            self.p=studio.edit_production({'project_id':pid,'revision':self.p['revision'],
                                           'shot_id':'s1',**fields})
        edit(action='set_lines',lines=[{'text':'第一句。'},{'text':'第二句。'}])
        first,second=self.p['shots'][0]['lines']
        self.assertNotEqual(first['id'],second['id'])
        studio.ffmpeg(['-f','lavfi','-i','sine=frequency=440','-t','0.25',str(studio.MEDIA/'retained.wav')])
        edit(action='add_take',kind='audio',file='retained.wav',line_id=first['id'])
        take=self.p['shots'][0]['takes'][-1]
        edit(action='bind_line_audio',line_id=first['id'],take_id=take['id'])
        edit(action='set_lines',lines=[first,{**second,'text':'只改第二句。'}])
        self.assertEqual(self.p['shots'][0]['lines'][0]['audio_take_id'],take['id'])
        self.assertEqual(self.p['shots'][0]['lines'][1]['text'],'只改第二句。')
        edit(action='set_lines',lines=[{**first,'text':'现在改第一句。'},second])
        self.assertNotIn('audio_take_id',self.p['shots'][0]['lines'][0])
        self.assertIn(take,self.p['shots'][0]['takes'])

    def test_cloud_audio_intake_uses_only_requested_line_and_bound_voice(self):
        from test_audio_workflow import audio
        self.add_shot();s=self.p['shots'][0]
        s['lines']=[{'id':'a','text':'你好','speaker_asset_id':'hero'},{'id':'b','text':'旁白','speaker_asset_id':None}]
        v=self.p['assets'][0]['versions'][0];v['voice_id']='nova'
        snap=production.scope(self.p,self.p['episodes'][0]['id'],'s1');snap['speech']=production.speech_request(snap,'a')
        ns={};exec(audio.INTAKE,ns);result=ns['main'](json.dumps(snap))
        self.assertEqual(result['text'],'你好');self.assertEqual(result['voice_id'],'nova');self.assertEqual(result['line_id'],'a')


    def test_invalid_audio_timing_keeps_the_saved_line_and_revision(self):
        self.add_shot();s=self.p['shots'][0]
        s['lines']=[{'id':'a','text':'一句话','speaker_asset_id':None}]
        with wave.open(str(studio.MEDIA/'timing.wav'),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\0\0'*8000)
        take=production.add_take(s,'audio','timing.wav');self.p=studio.save(self.p,self.p['revision'])
        self.p=studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_line_audio','shot_id':'s1','line_id':'a','take_id':take['id'],'start':0})
        saved=copy.deepcopy(self.p)
        for start in (-1,2,'bad',float('nan')):
            with self.subTest(start=start),self.assertRaises(ValueError):
                studio.edit_production({'project_id':self.p['id'],'revision':self.p['revision'],'action':'bind_line_audio','shot_id':'s1','line_id':'a','take_id':take['id'],'start':start})
            self.assertEqual(studio.project(self.p['id']),saved)
