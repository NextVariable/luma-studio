import copy,json,unittest
import production,studio,test_studio

class RevisionPreviewTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot

    def revision_job(self,incoming=None,**meta):
        self.add_shot()
        self.p['shots'][0].update(approved=True,needs_review=False)
        self.p['shots'].append({**copy.deepcopy(self.p['shots'][0]),'id':'s2','description':'相邻镜头'})
        self.p=studio.save(self.p,self.p['revision'])
        snap=production.scope(self.p,self.p['episodes'][0]['id'],'s1','改成近景，人物和对白保持不变')
        result={'status':'creative_approved','source_revision':self.p['revision'],'target_shot_id':'s1','shots':[incoming or {'description':'旅人面部近景','duration':2,'framing':'近景','asset_ids':['hero']}],**meta}
        with studio.connect() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('rev',self.p['id'],'revision','succeeded',json.dumps({'snapshot':snap,'revision_preview_required':True}),json.dumps({'result':result}),None,0,0,'rev'))
        return 'rev'

    def test_preview_is_read_only_and_shows_effective_before_after(self):
        jid=self.revision_job();before=studio.project(self.p['id'])
        preview=studio.revision_preview(self.p['id'],jid,self.p['revision'])
        self.assertEqual(preview['target_shot_id'],'s1')
        change=next(x for x in preview['changes'] if x['field']=='description')
        self.assertEqual((change['before'],change['after']),('旅人走向站台','旅人面部近景'))
        self.assertEqual(studio.project(self.p['id']),before)
        p=studio.apply_job(self.p['id'],jid,self.p['revision'],preview_digest=preview['digest'])
        self.assertEqual(p['shots'][1],before['shots'][1])
        self.assertTrue(p['shots'][0]['needs_review']);self.assertFalse(p['shots'][0]['approved'])
        self.assertEqual(p['shots'][0]['asset_bindings'],before['shots'][0]['asset_bindings'])

    def test_new_revision_cannot_be_applied_without_matching_preview(self):
        jid=self.revision_job()
        for token in (None,'wrong'):
            with self.subTest(token=token),self.assertRaisesRegex(ValueError,'预览'):studio.apply_job(self.p['id'],jid,self.p['revision'],preview_digest=token)

    def test_wrong_target_and_unapproved_result_are_refused(self):
        self.revision_job()
        for meta in ({'target_shot_id':'s2'},{'status':'blocked'},{'source_revision':0}):
            with self.subTest(meta=meta):
                result={'status':'creative_approved','source_revision':self.p['revision'],'target_shot_id':'s1','shots':[{'description':'近景','duration':2}],**meta}
                studio.update_job('rev','succeeded',{'result':result})
                with self.assertRaises(ValueError):studio.revision_preview(self.p['id'],'rev',self.p['revision'])

    def test_locked_or_changed_target_cannot_be_previewed(self):
        jid=self.revision_job();self.p['shots'][0]['locked']=True
        self.p=studio.save(self.p,self.p['revision'])
        with self.assertRaises(ValueError):studio.revision_preview(self.p['id'],jid,self.p['revision'])
