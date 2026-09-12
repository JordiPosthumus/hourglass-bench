import contextlib
import json
import tempfile
import threading
import time
import unittest
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import run_warmup
import web


class WarmupTests(unittest.TestCase):
    def test_real_serializer_uses_selected_profile_and_only_one_neutral_request(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((body,self.headers.get('x-dsg-model'),self.headers.get('Authorization')))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                chunk={'id':'warm','object':'chat.completion.chunk','model':'fixture','choices':[{'index':0,'delta':{'role':'assistant','content':'1 2 3'},'finish_reason':'length'}],'usage':{'prompt_tokens':300,'completion_tokens':128,'total_tokens':428}}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n').encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        cfg={'name':'fixture','model':'fixture','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-key',
             'sampling_era':'pi-native-v1','output_budget':'pi','max_tokens':262144,'context_window':262144,'pi_thinking_level':'max',
             'pi_model':{'thinkingLevelMap':{'max':'max'},'samplingParams':{'temperature':.8}},
             'inference_profile':{'mapping_version':'pi-native-v1','backend':'llamacpp','backend_version':'fixture','route':{'kind':'dsg','name':'worker'}}}
        before=json.dumps(cfg,sort_keys=True)
        result=run_warmup.run(cfg,{},threading.Condition())
        self.assertEqual(result['status'],'completed');self.assertEqual(result['output_tokens'],128)
        self.assertEqual(json.dumps(cfg,sort_keys=True),before)
        self.assertEqual(len(requests),1)
        body,route,auth=requests[0]
        self.assertEqual(body['max_tokens'],128);self.assertEqual(body['temperature'],.8)
        self.assertEqual(body['chat_template_kwargs']['reasoning_effort'],'max')
        self.assertEqual(route,'worker');self.assertEqual(auth,'Bearer fixture-key')
        self.assertNotIn('tools',body);self.assertEqual(len(body['messages']),1)
        self.assertIn('unscored server warm-up',body['messages'][0]['content'])
        self.assertNotIn('answer_question',json.dumps(body))

    def exercise_worker(self, previous=False, failure=False, cancelled=False):
        with tempfile.TemporaryDirectory() as directory,contextlib.ExitStack() as stack:
            root=Path(directory);config_path=root/'config.json';config_path.write_text(json.dumps({'models':[{'model':'fixture'}]}))
            job={'id':'warmfixture','tasks':['first'],'model':'fixture','state':'pending','elapsed_s':0,
                 'warmup_policy':run_warmup.POLICY,'question_timeout_s':900}
            if previous:job.update(warmup={'status':'completed'},warmups=[{'status':'completed','duration_s':1}],resume_count=1)
            manifest={'id':job['id'],'expected':[{'task':'first','repeat':1}]};rows=[];observed=[]
            def warmup(config,current,condition):
                self.assertIsNone(current.get('active_started'));self.assertNotIn('_hour_deadline_monotonic',current)
                self.assertNotIn('question_deadline_at',current);self.assertEqual(current['active_intervals'],[])
                time.sleep(.15)
                observed.append(time.time())
                if failure:raise ValueError('warm-up failed')
                if cancelled:current['stop_requested']=True;raise InterruptedError('cancelled')
                return {'status':'completed','duration_s':.15}
            class Proc:
                def __init__(self,cmd,**kwargs):
                    self_at=time.time();observed.append(self_at)
                    assert job['active_started']>=observed[0]
                    assert job['question_deadline_at']-self_at>899
                    rows.append({'evaluation_id':job['id'],'task':'first','run':1,'status':'completed','solved':True})
            def persist(*args):
                if job['state'] in ('completed','error','stopped'):web.worker_stop=True
            stack.enter_context(patch.multiple(web,ROOT=root,LOGS=root/'logs',queue=deque([job]),running=[],done=deque(),condition=threading.Condition(),worker_stop=False))
            for obj,name,kwargs in [(web,'saved_manifest',{'return_value':manifest}),(web,'model_document',{'return_value':{'models':[]}}),
                (web,'result_rows',{'side_effect':lambda:rows}),(web.evaluation_store,'frozen_config_path',{'return_value':config_path}),
                (web.evaluation_store,'update_evaluation',{'side_effect':persist}),(web.run_warmup,'run',{'side_effect':warmup}),
                (web.live_tps,'collect',{}),(web.hour_deadline,'watch_job',{}),(web.hour_deadline,'finish_sound',{}),
                (web.question_deadline,'wait',{'return_value':(0,False)}),(web.subprocess,'Popen',{'side_effect':Proc})]:stack.enter_context(patch.object(obj,name,**kwargs))
            web.worker()
            if failure or cancelled:
                self.assertEqual(job['state'],'stopped' if cancelled else 'error')
                self.assertEqual(job['elapsed_s'],0);self.assertEqual(rows,[]);self.assertEqual(job['active_intervals'],[])
            else:
                self.assertEqual(job['state'],'completed',job)
                self.assertLess(job['elapsed_s'],.1,'Warm-up must not consume the scoring hour')
                self.assertEqual(len(job['warmups']),2 if previous else 1)
                self.assertEqual(len(rows),1,'Warm-up must not create a scored attempt')
    def test_new_run_clock_starts_after_warmup(self):self.exercise_worker()
    def test_every_resume_warms_even_after_previous_success(self):self.exercise_worker(previous=True)
    def test_failure_never_starts_scoring(self):self.exercise_worker(failure=True)
    def test_cancellation_never_starts_scoring(self):self.exercise_worker(cancelled=True)
