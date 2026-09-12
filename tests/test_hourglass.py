import contextlib,importlib.util,io,json,tempfile,unittest,types,shutil,os
from pathlib import Path
from unittest.mock import patch
import hourglass,web,option_layout,task_identity

class LegacyHarnessAndScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch.object(hourglass,'run_agent',hourglass.legacy_run_agent),patch.object(hourglass,'ROOT',self.root),patch.object(hourglass,'TASKS',self.root/'tasks'),patch.object(hourglass,'RESULTS',self.root/'results'),patch.object(hourglass,'SANDBOX',self.root/'sandboxes')]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)]);self.addCleanup(self.tmp.cleanup)
        self.cfg=self.root/'models.json';self.cfg.write_text(json.dumps({'models':[{'name':'test model','base_url':'http://example.invalid/v1','model':'fixture','max_tokens':1024,'extra':{'custom':True}}]}))
    def task(self,tid='unit-mcq'):
        task={'id':tid,'kind':'mcq','prompt':'Choose the correct option','mode':'option_id','options':[{'id':'001','text':'no'},{'id':'002','text':'yes'}],'answer':'002','files':{'evidence.txt':'42'},'assets':[],'max_turns':4,'timeout_s':60,'repeat':1}
        p=hourglass.TASKS/tid;p.mkdir(parents=True);(p/'task.json').write_text(json.dumps(task));return task
    def answer(self,name='answer_question',args=None):
        return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'call1','type':'function','function':{'name':name,'arguments':json.dumps(args or {'option':'002'})}}]}}], 'usage':{'prompt_tokens':20,'completion_tokens':5}}
    def args(self,tid='unit-mcq'):
        return types.SimpleNamespace(task=tid,model='test model',repeat=1,config=str(self.cfg),no_sandbox=True)
    def run_mock(self,responses):
        t=json.loads((hourglass.TASKS/'unit-mcq/task.json').read_text())
        _,layout=option_layout.prepare(t,1,task_identity.identity(hourglass.TASKS/'unit-mcq'),'fixture-seed')
        if layout:
            inverse={v:k for k,v in layout['display_to_original'].items()}
            for response in responses:
                if not isinstance(response,dict):continue
                for call in response['choices'][0]['message'].get('tool_calls',[]):
                    fn=call['function'];args=json.loads(fn['arguments'])
                    if fn['name']=='answer_question' and args.get('option') in inverse:
                        args['option']=inverse[args['option']];fn['arguments']=json.dumps(args)
        with patch.object(hourglass.uuid,'uuid4',return_value=types.SimpleNamespace(hex='fixture-seed')),patch.object(hourglass,'chat',side_effect=responses),patch.object(hourglass,'get_provenance',return_value={'node':'test','pi_version':'fixture'}),contextlib.redirect_stdout(io.StringIO()):hourglass.cmd_run(self.args())
    def test_full_mcq_reads_file_and_grades(self):
        self.task();self.run_mock([self.answer('read_file',{'path':'evidence.txt'}),self.answer()]);rows=hourglass._rows();self.assertTrue(rows[0]['solved']);self.assertEqual(rows[0]['tool_calls'],2);self.assertEqual(rows[0]['opt_n'],2)
        tr=json.loads((self.root/rows[0]['artifact_dir']/'trace.json').read_text());self.assertTrue(any(t.get('result')=='42' for t in tr))
    def test_nonvision_zero_without_model_or_workspace(self):
        t=self.task();t['assets']=['chart.png'];(hourglass.TASKS/t['id']/'task.json').write_text(json.dumps(t))
        cfg=json.loads(self.cfg.read_text());cfg['models'][0]['supports_vision']=False;self.cfg.write_text(json.dumps(cfg))
        with patch.object(hourglass,'build',side_effect=AssertionError('must not build')),patch.object(hourglass,'chat',side_effect=AssertionError('must not send')),patch.object(hourglass,'get_provenance',return_value={}),contextlib.redirect_stdout(io.StringIO()):hourglass.cmd_run(self.args())
        r=hourglass._rows()[0];self.assertEqual(r['status'],'completed');self.assertFalse(r['solved']);self.assertEqual(r['score_reason'],'unsupported_vision');self.assertEqual(r['benchmark_version'],hourglass.BENCHMARK_VERSION);self.assertEqual(r['completion_tokens'],0)
        self.assertIn(f'| {hourglass.BENCHMARK_VERSION} | unit-mcq |',(self.root/'leaderboard.md').read_text())
    def test_auto_vision_rejection_is_zero(self):
        t=self.task();t['assets']=['chart.png'];(hourglass.TASKS/t['id']/'task.json').write_text(json.dumps(t));(hourglass.TASKS/t['id']/'chart.png').write_bytes(b'fixture')
        self.run_mock([hourglass.UnsupportedVision('model does not support images')])
        r=hourglass._rows()[0];self.assertFalse(r['solved']);self.assertEqual(r['status'],'completed');self.assertEqual(r['vision_detection'],'endpoint_rejection');self.assertNotIn('error',r)
    def test_vision_error_classifier(self):
        for msg in ['This model does not support images', 'image input is not supported', 'Missing mmproj file']:
            self.assertTrue(hourglass.vision_rejection(msg))
        for msg in ['connection refused', 'invalid image format', 'context length exceeded', 'tools not supported', 'model not found']:
            self.assertFalse(hourglass.vision_rejection(msg))
    def test_early_stop_records_zero_without_workspace_or_request(self):
        self.task()
        with patch.dict(os.environ,{'HOURGLASS_SKIP_REASON':'five_wrong_in_row'}),patch.object(hourglass,'build',side_effect=AssertionError('must not build')):
            self.run_mock([AssertionError('must not call model')])
        r=hourglass._rows()[0];self.assertEqual(r['score_reason'],'five_wrong_in_row');self.assertFalse(r['solved']);self.assertEqual(r['duration_s'],0)
    def test_runner_rejects_multiple_attempts(self):
        self.task();args=self.args();args.repeat=3;args.repeat_indices='2'
        with patch.object(hourglass,'chat') as call,self.assertRaisesRegex(ValueError,'runs once'):hourglass.cmd_run(args)
        call.assert_not_called()

    def test_task_metadata_cannot_enable_multiple_attempts(self):
        task=self.task();task['repeat']=3
        (hourglass.TASKS/task['id']/'task.json').write_text(json.dumps(task))
        args=self.args();del args.repeat
        with patch.object(hourglass,'chat',return_value=self.answer()) as call,patch.object(hourglass,'get_provenance',return_value={}),contextlib.redirect_stdout(io.StringIO()):hourglass.cmd_run(args)
        self.assertEqual(call.call_count,1);self.assertEqual(len(hourglass._rows()),1)
    def test_chat_has_no_timeout_and_preserves_generation_settings(self):
        response=io.BytesIO(json.dumps(self.answer()).encode())
        with patch.object(hourglass.urllib.request,'urlopen',return_value=response) as call:
            hourglass.chat('http://localhost/v1','model',[],{'timeout_s':.001,'max_tokens':262144,'temperature':1})
        self.assertIsNone(call.call_args.kwargs['timeout']);body=json.loads(call.call_args.args[0].data);self.assertEqual(body['max_tokens'],262144);self.assertNotIn('temperature',body)
    def test_task_time_limit_is_ignored(self):
        t=self.task();t['timeout_s']=-1;wd=hourglass.build(t)
        with patch.object(hourglass,'chat',return_value=self.answer()),contextlib.redirect_stdout(io.StringIO()):
            result=hourglass.run_mcq(t,{'model':'x','base_url':'unused'},wd,False)
        self.assertEqual(result[2],{'option':'002'});self.assertEqual(result[1]['termination'],'answered')
    def test_tool_command_has_no_timeout(self):
        with patch.object(hourglass.subprocess,'run',return_value=types.SimpleNamespace(stdout='ok',stderr='',returncode=0)) as call:
            hourglass.run_bash('anything',self.root,sandboxed=False)
        self.assertNotIn('timeout',call.call_args.kwargs)
    def test_nonvision_still_runs_text_questions(self):
        self.task();cfg=json.loads(self.cfg.read_text());cfg['models'][0]['supports_vision']=False;self.cfg.write_text(json.dumps(cfg));self.run_mock([self.answer()]);self.assertTrue(hourglass._rows()[0]['solved'])
    def test_versions_do_not_merge_in_leaderboard(self):
        self.task();self.run_mock([self.answer()]);r=hourglass._rows()[0];r.pop('benchmark_version')
        with (hourglass.RESULTS/'results.jsonl').open('a') as f:f.write(json.dumps(r)+'\n')
        with contextlib.redirect_stdout(io.StringIO()):hourglass.cmd_leaderboard(None)
        doc=(self.root/'leaderboard.md').read_text();self.assertIn('| unversioned | unit-mcq |',doc);self.assertIn(f'| {hourglass.BENCHMARK_VERSION} | unit-mcq |',doc)
    def test_vision_capability_requires_boolean(self):
        cfg=json.loads(self.cfg.read_text());cfg['models'][0]['supports_vision']='false';self.assertTrue(hourglass.validate_models(cfg))
    def test_both_image_task_formats_require_vision(self):
        for t in [{'kind':'chart-vqa'},{'assets':['chart.png']},{'image':'chart.png'}]:self.assertTrue(hourglass.requires_vision(t))
        self.assertFalse(hourglass.requires_vision({'kind':'mcq','assets':[]}))
    def test_relaunch_keeps_both_artifacts(self):
        self.task();self.run_mock([self.answer()]);self.run_mock([self.answer()]);rows=hourglass._rows();self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['artifact_dir'],rows[1]['artifact_dir']);self.assertTrue(all((self.root/r['artifact_dir']/'metrics.json').exists() for r in rows))
    def test_endpoint_failure_is_error_not_wrong_answer(self):
        self.task()
        with self.assertRaises(SystemExit):self.run_mock([OSError('endpoint unavailable')])
        row=hourglass._rows()[0];self.assertEqual(row['status'],'error');self.assertFalse(row['solved']);self.assertIn('endpoint unavailable',row['error']);self.assertNotIn('| unit-mcq |',(self.root/'leaderboard.md').read_text())
    def test_partial_trace_and_usage_survive_endpoint_failure(self):
        self.task()
        with self.assertRaises(SystemExit):self.run_mock([self.answer('read_file',{'path':'evidence.txt'}),OSError('offline')])
        row=hourglass._rows()[0];self.assertEqual(row['completion_tokens'],5);tr=json.loads((self.root/row['artifact_dir']/'trace.json').read_text());self.assertTrue(any(t.get('result')=='42' for t in tr))
    def test_wrong_answer_is_scored_attempt_not_execution_error(self):
        self.task();self.run_mock([self.answer(args={'option':'001'})]);r=hourglass._rows()[0];self.assertEqual(r['status'],'completed');self.assertFalse(r['solved'])
    def test_no_answer_budget_does_not_crash(self):
        t=self.task();t['max_turns']=0;wd=hourglass.build(t)
        result=hourglass.run_mcq(t,{'base_url':'unused','model':'unused'},wd,False)
        self.assertEqual(result[1]['termination'],'turn_limit');self.assertEqual(result[2],{})
    def test_fix_lane_initialization_and_submit(self):
        t={'id':'fix','kind':'fix','prompt':'Fix it','max_turns':2,'files':{}}
        wd=hourglass.build(t)
        with patch.object(hourglass,'chat',return_value=self.answer('submit',{'summary':'done'})),contextlib.redirect_stdout(io.StringIO()):trace,*_=hourglass.run_agent(t,{'base_url':'unused','model':'unused'},wd,False)
        self.assertTrue(any('submit'in x for x in trace))
    def test_all_native_file_tools_confined(self):
        wd=self.root/'work';wd.mkdir();outside=self.root/'secret';outside.write_text('private')
        (wd/'escape').symlink_to(self.root,target_is_directory=True)
        for name,args in [('read_file',{'path':'../secret'}),('read_file',{'path':'escape/secret'}),('write_file',{'path':'../secret','content':'changed'}),('edit_file',{'path':'escape/secret','oldText':'private','newText':'changed'})]:
            self.assertIn('outside workspace',hourglass.exec_tool(name,args,wd,False))
        self.assertEqual(outside.read_text(),'private')
    def test_sibling_prefix_is_not_inside_workspace(self):
        wd=self.root/'work';wd.mkdir();other=self.root/'work-secret';other.mkdir();(other/'key').write_text('private')
        self.assertIn('outside workspace',hourglass.exec_tool('read_file',{'path':'../work-secret/key'},wd,False))
    def test_build_confines_embedded_files(self):
        with self.assertRaises(ValueError):hourglass.build({'id':'bad','files':{'../leak':'x'}})
    def test_true_shuffle_preserves_mapping(self):
        t=self.task();t['options']=[{'id':f'{i:03d}','text':str(i)} for i in range(1,65)];t['shuffle']=True
        text=hourglass.mcq_display(t);self.assertNotEqual(text.splitlines()[1:],[f'{x["id"]} — {x["text"]}' for x in t['options']]);self.assertEqual(text,hourglass.mcq_display(t));self.assertTrue(hourglass.score_mcq(t,{'option':'2'})[0])
    def test_legacy_chart_shuffle_mapping(self):
        t={'id':'legacy','choices':['a','b','c','d'],'shuffle':True};display,mapping=hourglass.shuffle_choices(t)
        for line in display.splitlines()[1:]:letter,text=line.split('. ');self.assertEqual(t['choices']['ABCD'.index(mapping[letter])],text)
    def test_numeric_nonfinite_rejected(self):
        t={'mode':'numeric','target':10,'tolerance_abs':.5}
        for x in [float('nan'),float('inf'),'not a number']:self.assertFalse(hourglass.score_mcq(t,{'value':x})[0])
        self.assertTrue(hourglass.score_mcq(t,{'value':10.5})[0]);self.assertFalse(hourglass.score_mcq(t,{'value':10.50001})[0])
    def test_mcq_cert_uses_contract_not_empty_fix_verifier(self):
        self.task()
        with patch.object(hourglass,'build',side_effect=AssertionError('should not build')),contextlib.redirect_stdout(io.StringIO()):hourglass.cert('unit-mcq')
    def test_model_fields_not_downgraded(self):
        d={'models':[{'name':'a','base_url':'http://localhost/v1','model':'a','max_tokens':65536,'reasoning':{'effort':'high'},'extra':{'temperature':.7,'top_p':.95}}]};self.assertEqual(hourglass.validate_models(d),[]);self.cfg.write_text(json.dumps(d));self.assertEqual(hourglass.load_models(self.cfg)['a'],d['models'][0])

class WebTests(unittest.TestCase):
    def setUp(self):
        sound=patch.object(web.hour_deadline,'chime');sound.start();self.addCleanup(sound.stop)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch.object(web,'ROOT',self.root),patch.object(web,'TASKS',self.root/'tasks'),patch.object(web,'RESULTS',self.root/'results'),patch.object(web,'LOGS',self.root/'logs')]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)]);self.addCleanup(self.tmp.cleanup)
        self.model='name with spaces; echo should-not-run';(self.root/'models.json').write_text(json.dumps({'models':[{'name':self.model,'model':'x','base_url':'http://localhost/v1','hardware':'Fixture hardware','server_name':'Fixture server','quantization':'FP16'}]}))
        p=web.TASKS/'G001';p.mkdir(parents=True);(p/'task.json').write_text(json.dumps({'id':'G001','kind':'mcq','section':'games','prompt':'q','options':[{'id':'001','text':'a'},{'id':'002','text':'b'}],'answer':'001','files':{}}))
        with web.condition:web.queue.clear();web.running.clear();web.done.clear()
    def test_state_does_not_expose_answers(self):
        s=web.state();self.assertNotIn('answer',s['tasks'][0]);self.assertNotIn('prompt',s['tasks'][0])
    def test_enqueue_retains_model_name_as_data(self):
        j=web.enqueue({'model':self.model,'tasks':['G001','G001'],'repeat':1});self.assertEqual(j['model'],self.model);self.assertNotIn('cmd',j);self.assertEqual(j['tasks'],['G001'])
    def test_unique_ids_and_repeat_validation(self):
        a=web.enqueue({'model':self.model,'tasks':['G001'],'repeat':1});b=web.enqueue({'model':self.model,'tasks':['G001'],'repeat':1});self.assertNotEqual(a['id'],b['id'])
        for r in [0,-1,True,1.1,'1']:
            with self.assertRaises(ValueError):web.enqueue({'model':self.model,'tasks':['G001'],'repeat':r})
    def test_reject_unknown_task_and_model(self):
        for body in [{'model':'missing','tasks':['G001']},{'model':self.model,'tasks':['../x']},{'model':self.model,'tasks':[]}]:
            with self.assertRaises(ValueError):web.enqueue(body)
    def test_model_list_check_makes_no_generation_request(self):
        response=io.BytesIO(json.dumps({'data':[{'id':'x'}]}).encode())
        with patch.object(web.urllib.request,'urlopen',return_value=response) as call:
            r=web.check_model(self.model)
        self.assertTrue(r['listed']);self.assertTrue(call.call_args.args[0].full_url.endswith('/models'))
    def test_reject_duplicate_model_aliases(self):
        m={'name':'x','base_url':'http://localhost/v1','model':'x'};self.assertTrue(hourglass.validate_models({'models':[m,m]}))
    def test_difficulty_order_and_section_interleaving(self):
        tasks=[{'id':'C2','tier':2,'section':'chart'},{'id':'C1','tier':1,'section':'chart'},
               {'id':'C0','tier':1,'section':'chart'},{'id':'M1','tier':1,'section':'math'},
               {'id':'G1','tier':1,'section':'games'},{'id':'U1','tier':None,'section':'math'}]
        order=web.ordered_tasks(tasks,[t['id'] for t in tasks])
        self.assertEqual(order,['C0','G1','M1','C1','C2','U1'])
    def test_math_levels_are_estimated_and_interleaved(self):
        tasks=[{'id':'C1','tier':1,'section':'chart'}, {'id':'G1','tier':1,'section':'games'},
               {'id':'M1','tier':None,'level':'advanced_high_school','section':'math'},
               {'id':'M2','tier':None,'level':'advanced_undergraduate','section':'math'},
               {'id':'M3','tier':None,'level':'graduate','section':'math'}, {'id':'C9','tier':9,'section':'chart'}]
        self.assertEqual(web.ordered_tasks(tasks,[t['id'] for t in tasks]),['C1','M2','C9','G1','M3','M1'])
        self.assertEqual([web.run_tracking.difficulty_tier(t) for t in tasks],[1,1,1,5,9,9])
    def test_twenty_wrong_stop_and_correct_answer_reset(self):
        for correct_at in [None,19]:
            with web.condition:web.queue.clear();web.running.clear();web.done.clear();web.worker_stop=False
            tasks=[]
            for i in range(42):
                tid=f'T{i:02d}';tasks.append(tid);p=web.TASKS/tid;p.mkdir(exist_ok=True)
                (p/'task.json').write_text(json.dumps({'id':tid,'kind':'mcq','prompt':'fixture','options':[{'id':'001','text':'a'},{'id':'002','text':'b'}],'answer':'001'}))
            job=web.enqueue({'model':self.model,'tasks':tasks,'repeat':1});rows=[];calls=[]
            class Proc:
                def __init__(self,cmd,**kwargs):
                    tid=cmd[cmd.index('run')+1];skip=kwargs['env']['HOURGLASS_SKIP_REASON'];calls.append(skip)
                    rows.append({'evaluation_id':job['id'],'task':tid,'status':'completed','solved':len(calls)-1==correct_at})
                def wait(self, timeout=None):
                    if len(calls)==42:web.worker_stop=True
                    return 0
            with patch.object(web.subprocess,'Popen',Proc),patch.object(web,'result_rows',side_effect=lambda:rows):web.worker()
            expected=20 if correct_at is None else 40
            self.assertEqual(calls[:expected],['']*expected);self.assertEqual(calls[expected:],['wrong_streak_limit']*(42-expected));self.assertEqual(web.done[-1]['stopped_after'],tasks[expected-1])
        self.addCleanup(lambda:setattr(web,'worker_stop',False))
    def test_worker_uses_argv_and_preserves_single_stream(self):
        calls=[]
        class Proc:
            def __init__(self,cmd,**kwargs):calls.append(cmd)
            def wait(self, timeout=None):
                with web.condition:web.worker_stop=True
                return 0
        web.enqueue({'model':self.model,'tasks':['G001'],'repeat':1})
        jid=web.queue[0]['id']
        with patch.object(web.subprocess,'Popen',Proc),patch.object(web,'result_rows',side_effect=lambda:[{'evaluation_id':jid,'task':'G001','status':'completed','solved':True}] if calls else []):web.worker()
        self.addCleanup(lambda:setattr(web,'worker_stop',False));self.assertEqual(len(calls),1);self.assertEqual(calls[0][calls[0].index('--model')+1],self.model);self.assertNotIn('bash',calls[0]);self.assertEqual(web.done[-1]['state'],'completed')

if __name__=='__main__':unittest.main()
