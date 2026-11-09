import io, json, os, unittest
from unittest.mock import patch
import test_studio
import studio
from providers import Dify
import providers


def stream(*events):
    return io.BytesIO(('event: ping\n\n' + ''.join('data: '+json.dumps(e,ensure_ascii=False)+'\n\n' for e in events)).encode())


class DifyBridgeTests(unittest.TestCase):
    def test_tls_verification_failure_is_not_an_unknown_remote_execution(self):
        import ssl, urllib.error
        failure=urllib.error.URLError(ssl.SSLCertVerificationError('unknown CA'))
        with patch.dict(os.environ, {'DIFY_PRODUCTION_KEY':'not-real'}), patch('providers.open_request',side_effect=failure):
            with self.assertRaisesRegex(ValueError,'证书验证失败.*请求未提交') as error:
                Dify().run('shots',{'id':'p','script':'剧情','revision':1})
            self.assertNotIsInstance(error.exception,providers.UncertainRun)

    def test_finished_snapshot_clears_stale_running_node(self):
        with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'not-real'}):
            result=Dify().consume(stream({'event':'workflow_finished','data':{'status':'succeeded','outputs':{
                'approved_end_result':{'status':'creative_approved','shots':[{'description':'码头','duration':5}]}}}}),
                'shots',{'id':'p','revision':1},previous={'current_node':{'title':'导演审批','status':'running'}})
        self.assertEqual(result['current_node']['status'],'finished')

    def test_redirect_cannot_forward_application_key(self):
        import urllib.request
        request=urllib.request.Request('https://api.dify.ai/v1/workflows/run',headers={'Authorization':'Bearer secret'})
        self.assertIsNone(providers.NoRedirect().redirect_request(request,None,302,'redirect',{},'https://other.example/'))

    def run_stream(self, *events):
        with patch.dict(os.environ, {'DIFY_PRODUCTION_KEY':'not-real'}), patch('providers.open_request', return_value=stream(*events)) as request:
            result = Dify().run('shots', {'id':'p','script':'剧情','revision':1})
            body = json.loads(request.call_args.args[0].data)
            self.assertEqual(body['response_mode'], 'streaming')
            self.assertEqual(body['user'], 'auteur-p')
            return result

    def test_production_approved_output_is_decoded(self):
        result=self.run_stream({'event':'workflow_finished','workflow_run_id':'run1','data':{
            'status':'succeeded','total_tokens':42,'outputs':{'approved_end_result':{
                'status':'creative_approved','shots':[{'description':'雨夜','duration':5}], 'source_revision':1}}}})
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(result['run_id'], 'run1')
        self.assertEqual(result['result']['shots'][0]['description'], '雨夜')

    def test_business_block_is_not_a_successful_shot_plan(self):
        result=self.run_stream({'event':'workflow_finished','data':{'status':'succeeded','outputs':{
            'blocked_end_result':{'status':'blocked','issues':['遗漏折信动作'],'shots':[]}}}})
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(result['result']['issues'], ['遗漏折信动作'])

    def test_timeout_does_not_turn_requires_review_into_approval(self):
        result=self.run_stream({'event':'workflow_finished','data':{'status':'succeeded','outputs':{
            'timeout_end_result':{'status':'requires_review','shots':[{'description':'雨夜','duration':5}]}}}})
        self.assertEqual(result['state'], 'blocked')

    def test_conflicting_end_results_are_rejected(self):
        with self.assertRaises(ValueError):
            self.run_stream({'event':'workflow_finished','data':{'status':'succeeded','outputs':{
                'approved_end_result':{'status':'creative_approved','shots':[]},
                'blocked_end_result':{'status':'blocked','shots':[]}}}})

    def test_stream_disconnect_is_not_silent_success(self):
        with self.assertRaisesRegex(ValueError, '断开|结束|核实'):
            self.run_stream({'event':'workflow_started','workflow_run_id':'run1','data':{}})

    def test_paused_form_is_loaded_and_keeps_run_identity(self):
        form={'form_content':'审核分镜','inputs':[{'type':'paragraph','output_variable_name':'notes'}],
              'user_actions':[{'id':'approve','title':'通过'},{'id':'revise','title':'修改'}]}
        with patch.dict(os.environ, {'DIFY_PRODUCTION_KEY':'not-real'}), patch('providers.open_request', side_effect=[
            stream({'event':'human_input_required','workflow_run_id':'r','task_id':'t','data':{'form_token':'private-token'}}),
            io.BytesIO(json.dumps(form).encode())]):
            result=Dify().run('shots',{'id':'p'})
        self.assertEqual(result['state'],'waiting_review')
        self.assertEqual(result['form']['user_actions'][1]['id'],'revise')
        self.assertEqual(result['run_id'],'r')

    def test_source_revision_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'版本'):
            self.run_stream({'event':'workflow_finished','data':{'status':'succeeded','outputs':{
                'approved_end_result':{'status':'creative_approved','source_revision':9,'shots':[]}}}})

    def test_reconnect_uses_get_and_original_user(self):
        finished={'event':'workflow_finished','workflow_run_id':'remote-run','data':{'status':'succeeded','outputs':{
            'approved_end_result':{'status':'creative_approved','shots':[{'description':'镜头','duration':5}]}}}}
        with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'not-real'}),patch('providers.open_request',return_value=stream(finished)) as request:
            Dify().listen('shots',{'id':'project1','revision':1},{'run_id':'remote-run'})
        req=request.call_args.args[0]
        self.assertEqual(req.get_method(),'GET')
        self.assertIn('/workflow/remote-run/events?',req.full_url)
        self.assertIn('user=auteur-project1',req.full_url)

    def test_approval_submit_uses_original_form_and_identity(self):
        with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'not-real'}),patch('providers.open_request',return_value=io.BytesIO(b'{}')) as request:
            Dify().submit('shots',{'id':'project1'},{'form_token':'private-form'},'revise',{'notes':'改第三镜'})
        req=request.call_args.args[0]
        self.assertTrue(req.full_url.endswith('/form/human_input/private-form'))
        self.assertEqual(json.loads(req.data),{'action':'revise','inputs':{'notes':'改第三镜'},'user':'auteur-project1'})

    def test_accepted_empty_submit_response_does_not_reopen_form(self):
        with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'not-real'}),patch('providers.open_request',return_value=io.BytesIO(b'')):
            Dify().submit('shots',{'id':'p'},{'form_token':'private-form'},'approve',{})

    def test_reconnect_does_not_reuse_previous_approval_token(self):
        previous={'run_id':'r','form_token':'old-form','review_id':'old-review','form':{'user_actions':[{'id':'approve'}]}}
        with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'not-real'}),patch('providers.open_request',return_value=stream({'event':'workflow_paused','data':{}})):
            result=Dify().listen('shots',{'id':'p'},previous)
        self.assertFalse(result.get('review_id'))
        self.assertNotIn('form_token',result)

    def test_context_excludes_other_episode_scripts(self):
        done={'event':'workflow_finished','data':{'status':'succeeded','outputs':{'result':{'shots':[]}}}}
        with patch.dict(os.environ,{'DIFY_PRODUCTION_KEY':'','DIFY_SHOTS_KEY':'not-real'}),patch('providers.open_request',return_value=stream(done)) as request:
            Dify().run('shots',{'id':'p','script':'本集','episodes':[{'script':'另一集不应发送'}],'assets':[],'revision':1})
        sent=json.loads(json.loads(request.call_args.args[0].data)['inputs']['context'])
        self.assertNotIn('episodes',sent)
        self.assertEqual(sent['script'],'本集')


class ReviewJobTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def waiting_job(self):
        result={'state':'waiting_review','run_id':'remote-run','form_token':'private-token','review_id':'review1',
                'form':{'form_content':'请审核','inputs':[{'type':'paragraph','output_variable_name':'notes'}],
                        'user_actions':[{'id':'approve','title':'通过'},{'id':'revise','title':'修改'}]}}
        with studio.connect() as c:
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('j',self.p['id'],'shots','waiting_review',
                json.dumps({'snapshot':self.p}),json.dumps(result),None,0,0,'review'))

    def test_public_job_never_returns_form_token(self):
        self.waiting_job()
        with studio.connect() as c: row=c.execute('SELECT * FROM jobs WHERE id=?',('j',)).fetchone()
        result=studio.public_job(row)
        self.assertNotIn('private-token',json.dumps(result))
        self.assertEqual(json.loads(result['result'])['review_id'],'review1')

    def test_outdated_project_cannot_submit_remote_approval(self):
        self.waiting_job();self.p['title']='改名';self.p=studio.save(self.p,1)
        with patch.object(Dify,'submit') as submit:
            with self.assertRaises(ValueError):studio.review_job(self.p['id'],'j',2,'review1','approve','')
            submit.assert_not_called()

    def test_successful_review_queues_listen_not_a_new_run(self):
        self.waiting_job()
        with patch.object(Dify,'submit',return_value=None):
            studio.review_job(self.p['id'],'j',1,'review1','revise','第三镜改近景')
        with studio.connect() as c: row=c.execute('SELECT * FROM jobs WHERE id=?',('j',)).fetchone()
        self.assertEqual(row['state'],'queued')
        self.assertEqual(json.loads(row['payload'])['operation'],'listen')
        self.assertEqual(json.loads(row['result'])['run_id'],'remote-run')

    def test_repeated_or_wrong_action_rejected_locally(self):
        self.waiting_job()
        with patch.object(Dify,'submit',return_value=None) as submit:
            with self.assertRaises(ValueError):studio.review_job(self.p['id'],'j',1,'review1','invented','')
            studio.review_job(self.p['id'],'j',1,'review1','approve','')
            with self.assertRaises(ValueError):studio.review_job(self.p['id'],'j',1,'review1','approve','')
            self.assertEqual(submit.call_count,1)

    def test_blocked_result_cannot_be_adopted(self):
        self.waiting_job();studio.update_job('j','blocked',{'result':{'status':'blocked','shots':[]}})
        with self.assertRaises(ValueError):studio.apply_job(self.p['id'],'j',1)

    def test_worker_retains_paused_instead_of_success(self):
        self.waiting_job()
        with studio.connect() as c:c.execute("UPDATE jobs SET state='queued' WHERE id='j'")
        with patch.dict(os.environ,{'DIFY_SHOTS_KEY':'mock'}),patch.object(Dify,'run',return_value={'state':'waiting_review','run_id':'r','form_token':'secret'}):
            studio.work_once()
        with studio.connect() as c: state=c.execute("SELECT state FROM jobs WHERE id='j'").fetchone()[0]
        self.assertEqual(state,'waiting_review')

    def test_reconcile_only_listens_to_existing_run(self):
        self.waiting_job();studio.reconcile_job(self.p['id'],'j')
        with patch.object(Dify,'listen',return_value={'state':'blocked','result':{'status':'revision_requested'}}) as listen, patch.object(Dify,'run') as run:
            studio.work_once()
        self.assertEqual(listen.call_count,1)
        run.assert_not_called()

    def test_configuration_is_server_only_and_private(self):
        with patch.object(studio,'ROOT',studio.DATA),patch.dict(os.environ,{},clear=False):
            result=studio.configure_dify('https://api.dify.ai/v1','app-test-secret')
            self.assertNotIn('app-test-secret',json.dumps(result))
            self.assertEqual((studio.DATA/'.env').stat().st_mode & 0o777,0o600)
            self.assertEqual(os.environ['DIFY_PRODUCTION_KEY'],'app-test-secret')

    def test_invalid_endpoint_cannot_save_credentials(self):
        with patch.object(studio,'ROOT',studio.DATA):
            with self.assertRaises(ValueError):studio.configure_dify('http://localhost.attacker.test/v1','app-test-secret')
            self.assertFalse((studio.DATA/'.env').exists())

    def test_config_rejects_newline_in_url(self):
        with patch.object(studio,'ROOT',studio.DATA):
            with self.assertRaises(ValueError):studio.configure_dify('https://api.dify.ai/v1\nPORT=1','app-test-secret')
            self.assertFalse((studio.DATA/'.env').exists())
