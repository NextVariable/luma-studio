import unittest,tempfile,copy,json,os,subprocess
from pathlib import Path
from unittest.mock import patch
from luma import studio
from luma.contracts import validate

class StudioTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();studio.DATA=Path(self.tmp.name);studio.MEDIA=studio.DATA/'media';studio.DB=studio.DATA/'studio.sqlite';studio.init();studio.set_spending(20)
  self.p=studio.create('测试作品','雨中的车站，一个人等待末班车。')
 def tearDown(self):self.tmp.cleanup()
 def add_shot(self):
  self.p['assets']=[{'id':'hero','name':'旅人','kind':'character','description':'蓝色外套','version':1}]
  self.p['shots']=[{'id':'s1','description':'旅人走向站台','duration':2,'asset_ids':['hero'],'locked':False,'approved':False}]
  self.p=studio.save(self.p,self.p['revision']);return self.p['shots'][0]
 def test_revision_conflict(self):
  stale=copy.deepcopy(self.p);self.p['script']='新剧本';studio.save(self.p,1)
  with self.assertRaises(ValueError):studio.save(stale,1)
 def test_versions_persist(self):
  self.p['script']='第二版';studio.save(self.p,1)
  with studio.connect() as c:self.assertEqual(c.execute('select count(*) from versions').fetchone()[0],1)
 def test_shared_mode(self):
  self.add_shot();self.p['mode']='wizard';p=studio.save(self.p,2);self.assertEqual(studio.project(p['id'])['shots'][0]['id'],'s1')
 def test_locked_shot(self):
  s=self.add_shot();s['locked']=True;self.p=studio.save(self.p,2);self.p['shots'][0]['description']='changed'
  with self.assertRaises(ValueError):studio.save(self.p,3)
 def test_asset_change_keeps_shot_on_pinned_version_until_rebound(self):
  self.add_shot();pinned=self.p['shots'][0]['asset_bindings']['hero'];self.p['assets'][0]['description']='红色外套';p=studio.save(self.p,2)
  self.assertEqual(p['shots'][0]['id'],'s1');self.assertEqual(p['shots'][0]['asset_bindings']['hero'],pinned);self.assertNotEqual(p['assets'][0]['selected_version'],pinned)
  p['shots'][0]['asset_bindings']['hero']=p['assets'][0]['selected_version'];p=studio.save(p,p['revision']);self.assertTrue(p['shots'][0]['needs_review'])
 def test_unknown_reference_rejected(self):
  s=self.add_shot();s['asset_ids']=['absent']
  with self.assertRaises(ValueError):studio.save(self.p,2)
 def test_export_blocks_unapproved(self):
  self.add_shot()
  with self.assertRaises(ValueError):studio.enqueue(self.p['id'],'export',{},'one')
 def test_schema_rejects_wrong_type(self):
  with self.assertRaises(ValueError):validate('shots',{'shots':[{'description':'a','duration':'5'}]})
 def test_path_traversal(self):
  with self.assertRaises(ValueError):studio.media_path('../studio.sqlite')
 def test_recovery_never_replays_unknown_paid_call(self):
  with studio.connect() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('j',self.p['id'],'script','running','{}',None,None,0,0,'once'))
  studio.init()
  with studio.connect() as c:self.assertEqual(c.execute('select state from jobs').fetchone()[0],'interrupted')
 def test_oversized_dify_input_is_rejected_before_queue_or_spend(self):
  p=studio.create('超长输入','字'*100000)
  episode_id=p['episodes'][0]['id']
  snapshot=studio.production.scope(p,episode_id)
  with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'app-test'}), patch.object(studio.Dify,'run') as run:
   with self.assertRaisesRegex(ValueError,'10 万字符'):
    studio.enqueue(p['id'],'shots',{'episode_id':episode_id},'new')
   with studio.connect() as c:
    self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
    c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('old',p['id'],'shots','queued',json.dumps({'snapshot':snapshot}),None,None,0,0,'old'))
   studio.work_once()
   run.assert_not_called()
  with studio.connect() as c:
   row=c.execute('SELECT state,error FROM jobs').fetchone()
   self.assertEqual(row['state'],'failed')
   self.assertIn('10 万字符',row['error'])
  self.assertEqual(studio.spending(),{'remaining':20,'used':0})
 def test_real_ffmpeg_export_and_idempotency(self):
  s=self.add_shot();clip=studio.MEDIA/'fixture.mp4'
  studio.ffmpeg(['-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(clip)])
  s.update(video=clip.name,approved=True,needs_review=False,dialogue='测试字幕，不是 AI 生成短片')
  self.p=studio.save(self.p,2)
  self.p['shots'][0].update(approved=True,needs_review=False);self.p=studio.save(self.p,3)
  jid=studio.enqueue(self.p['id'],'export',{},'same');self.assertEqual(jid,studio.enqueue(self.p['id'],'export',{},'same'))
  self.assertTrue(studio.work_once())
  with studio.connect() as c:j=c.execute('select * from jobs where id=?',(jid,)).fetchone()
  self.assertEqual(j['state'],'succeeded',j['error']);result=json.loads(j['result']);path=studio.media_path(result['file'])
  probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
  self.assertEqual({s['codec_type'] for s in probe['streams']},{'video','audio','subtitle'});self.assertAlmostEqual(float(probe['format']['duration']),2,delta=.15)

if __name__=='__main__':unittest.main()
