import copy, json, unittest
import test_studio
import studio

class AuditRegressions(unittest.TestCase):
 setUp=test_studio.StudioTests.setUp
 tearDown=test_studio.StudioTests.tearDown
 add_shot=test_studio.StudioTests.add_shot
 def test_script_change_invalidates_locked_approval(self):
  self.add_shot(); self.p['shots'][0].update(approved=True,locked=True)
  self.p=studio.save(self.p,2); self.p['script']='故事已改变'
  saved=studio.save(self.p,3)
  self.assertFalse(saved['shots'][0]['approved'])
  self.assertTrue(saved['shots'][0]['needs_review'])
  self.assertTrue(saved['shots'][0]['locked'])
 def test_reorder_invalidates_continuity_review(self):
  self.add_shot(); self.p['shots'].append({**self.p['shots'][0],'id':'s2'})
  self.p=studio.save(self.p,2)
  for s in self.p['shots']:s.update(approved=True,needs_review=False)
  self.p=studio.save(self.p,3);self.p['shots'].reverse()
  saved=studio.save(self.p,4)
  self.assertTrue(all(s['needs_review'] and not s['approved'] for s in saved['shots']))
 def test_project_rejects_invalid_asset_type(self):
  self.p['assets']=[{'id':'x','name':'x','kind':'arbitrary','version':1}]
  with self.assertRaises(ValueError):studio.save(self.p,1)
 def test_failed_suggestion_cannot_be_applied(self):
  self.make_job(state='failed')
  with self.assertRaises(ValueError):studio.apply_job(self.p['id'],'j',1)
 def make_job(self,state='succeeded',revision=None):
  snapshot=copy.deepcopy(self.p)
  if revision is not None:snapshot['revision']=revision
  with studio.connect() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('j',self.p['id'],'script',state,json.dumps({'snapshot':snapshot}),json.dumps({'result':{'characters':[{'name':'旅人'}],'scenes':[]}}),None,0,0,'j'))
 def test_stale_suggestion_rejected(self):
  self.make_job();self.p['script']='新剧情';self.p=studio.save(self.p,1)
  with self.assertRaises(ValueError):studio.apply_job(self.p['id'],'j',2)
 def test_suggestion_is_applied_once_on_server(self):
  self.make_job();saved=studio.apply_job(self.p['id'],'j',1)
  self.assertEqual(len(saved['assets']),1)
  with self.assertRaises(ValueError):studio.apply_job(saved['id'],'j',saved['revision'])
  self.assertEqual(len(studio.project(saved['id'])['assets']),1)

if __name__=='__main__':unittest.main()
