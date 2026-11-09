import json, os, sqlite3, subprocess, unittest
from pathlib import Path
from unittest.mock import patch
import studio, production, test_studio
from providers import Dify


class FullAuditTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    add_shot=test_studio.StudioTests.add_shot

    def test_empty_structured_dialogue_clears_old_subtitle(self):
        self.add_shot()
        self.p['shots'][0]['lines']=[{'id':'l','speaker_asset_id':None,'text':'应当被删除'}]
        self.p=studio.save(self.p,self.p['revision'])
        self.p['shots'][0]['lines']=[]
        self.p=studio.save(self.p,self.p['revision'])
        self.assertEqual(self.p['shots'][0]['dialogue'],'')
        self.assertFalse(production.readiness(self.p,self.p['episodes'][0]['id'])['shots'][0]['dialogue_without_audio'])

    def test_delete_last_line_stays_empty_in_editor(self):
        source=Path('web/editor-ui.js').read_text()
        script='''const vm=require('node:vm');const hidden={value:'old'};const del={dataset:{lineDel:'0'}};
let focused=false;const add={focus(){focused=true}};
const ctx={window:{addEventListener(){}},document:{querySelectorAll(s){return s==='[data-line-del]'?[del]:[]}},
 $:s=>s==='#line-add'?add:hidden,requestAnimationFrame(fn){fn()},bind(){},readLines(){return [{id:'l',text:'旧句'}]},rememberDraft(){},render(){}};
vm.createContext(ctx);vm.runInContext(SOURCE,ctx);ctx.readLines=()=>[{id:'l',text:'旧句'}];ctx.bindLines({});del.onclick();
if(hidden.value!=='[]')throw Error('删除最后一句后返回了 '+hidden.value+'，应保留空逐句模式');
if(!focused)throw Error('删除最后一句后应聚焦添加对白');'''
        result=subprocess.run(['node','-e',script.replace('SOURCE',json.dumps(source))],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_invalid_audio_is_refused_before_queue_or_allowance(self):
        self.add_shot()
        cases=[{}, {'dialogue':' '*5}, {'dialogue':'字'*4001}, {'lines':[
            {'id':'a','speaker_asset_id':'hero','text':'你好'}, {'id':'b','speaker_asset_id':None,'text':'旁白'}]}]
        with patch.dict(os.environ,{'DIFY_AUDIO_KEY':'local-test'}):
            for fields in cases:
                self.p=studio.project(self.p['id']);self.p['shots'][0].update(fields)
                self.p=studio.save(self.p,self.p['revision'])
                with self.subTest(fields=list(fields)), self.assertRaises(ValueError):
                    studio.enqueue(self.p['id'],'audio',{'shot_id':'s1'},studio.uid())
        self.assertEqual(studio.spending()['used'],0)
        with studio.connect() as c:self.assertEqual(c.execute('select count(*) from jobs').fetchone()[0],0)

    def test_audio_does_not_upload_visual_or_voice_reference_files(self):
        self.add_shot();s=self.p['shots'][0];s['dialogue']='你好'
        (studio.MEDIA/'hero.png').write_bytes(b'fixture')
        self.p['assets'][0]['versions'][0]['file']='hero.png'
        refs=production.reference_plan(self.p,'s1','audio')
        self.assertEqual(refs['items'],[])
        self.assertTrue(refs['omitted'])

    def test_database_context_closes_connection_after_commit(self):
        with studio.connect() as c:c.execute('select 1').fetchone()
        with self.assertRaises(sqlite3.ProgrammingError):c.execute('select 1')

    def test_removed_key_does_not_consume_authorization(self):
        self.add_shot()
        with patch.dict(os.environ,{'DIFY_AUDIO_KEY':'local-test'}):
            self.p['shots'][0]['dialogue']='你好'
            self.p=studio.save(self.p,self.p['revision'])
            jid=studio.enqueue(self.p['id'],'audio',{'shot_id':'s1'},'removed-key')
        with patch.dict(os.environ,{'DIFY_AUDIO_KEY':''}), patch.object(Dify,'run') as run:
            studio.work_once();run.assert_not_called()
        self.assertEqual(studio.spending()['used'],0)

    def test_voice_asset_is_never_sent_as_image_reference(self):
        self.add_shot()
        (studio.MEDIA/'voice.wav').write_bytes(b'fixture')
        self.p['assets'].append({'id':'voice','name':'声音','kind':'voice','versions':[
            {'id':'voice-v1','name':'声音','file':'voice.wav','description':''}],'selected_version':'voice-v1'})
        self.p['shots'][0]['asset_ids'].append('voice')
        self.p['shots'][0]['asset_bindings']['voice']='voice-v1'
        refs=production.reference_plan(self.p,'s1','video')
        self.assertFalse(any(r.get('asset_id')=='voice' for r in refs['items']))
        self.assertTrue(any(r.get('asset_id')=='voice' for r in refs['omitted']))
