"""Native pinned-Pi requests against synthetic providers; no model inference."""
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import harness_runner
import inference_profiles
import profile_export
import hourglass


class NativeProfiles(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.raw = []
        self.headers = []
        self.fail_first = False
        self.reject_store = False
        self.reject_context = False
        self.successes = 0
        self.reported_prompt_tokens = 20
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                # Missing metadata must not invalidate explicit settings.
                self.send_response(404); self.end_headers()
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                request = json.loads(raw)
                owner.raw.append(raw); owner.requests.append(request); owner.headers.append(dict(self.headers))
                if owner.reject_store and 'store' in request:
                    self.send_response(400); self.end_headers()
                    self.wfile.write(b'{"error":{"message":"store: unsupported request field for this backend","type":"BadRequestError","param":"store"}}'); return
                if owner.reject_context:
                    self.send_response(400); self.end_headers()
                    # Bound a broken implementation's fixture loop as well.
                    message=("This model's maximum context length is 262144 tokens. However, you requested 262144 output tokens and your prompt contains 100 characters."
                             if len(owner.requests)<3 else 'Fixture stopped repeated failed requests.')
                    self.wfile.write(json.dumps({'error':{'message':message,'type':'BadRequestError'}}).encode()); return
                if owner.fail_first and len(owner.requests) == 1:
                    self.send_response(503); self.send_header('retry-after-ms', '1'); self.end_headers()
                    self.wfile.write(b'{"error":{"message":"synthetic retry","type":"server_error"}}'); return
                summary = not request.get('tools')
                if not summary: owner.successes += 1
                name = 'bash' if owner.successes == 1 else 'answer_question'
                args = {'command': 'printf fixture'} if name == 'bash' else {'option': '001'}
                message = {'role':'assistant','reasoning_content':'Synthetic reasoning.',
                           'tool_calls':[{'id':'fixture-call-'+str(owner.successes),'type':'function',
                                          'function':{'name':name,'arguments':json.dumps(args)}}]}
                if summary: message = {'role':'assistant','content':'The workspace tool succeeded. Continue and call answer_question with option 001.'}
                elif owner.reported_prompt_tokens>240000 and owner.successes==1:
                    message['reasoning_content']='Synthetic earlier reasoning. '*4000
                self.send_response(200)
                self.send_header('x-ds4-node','fixture-worker')
                self.send_header('Content-Type','text/event-stream' if request.get('stream') else 'application/json')
                self.end_headers()
                usage = owner.reported_prompt_tokens if not summary and owner.successes == 1 else 20
                envelope={'id':'fixture','created':1,'model':'fixture','usage':{'prompt_tokens':usage,'completion_tokens':10,'total_tokens':usage+10}}
                finish = 'stop' if summary else 'tool_calls'
                if request.get('stream'):
                    delta=copy.deepcopy(message)
                    for i,call in enumerate(delta.get('tool_calls',[])):call['index']=i
                    self.wfile.write(('data: '+json.dumps({**envelope,'object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n').encode())
                else:
                    self.wfile.write(json.dumps({**envelope,'object':'chat.completion','choices':[{'index':0,'message':message,'finish_reason':finish}]}).encode())

        self.server=HTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=pathlib.Path(self.temp.name)

    def cfg(self):
        return {'name':'fixture','model':'fixture','base_url':f'http://127.0.0.1:{self.server.server_port}/v1',
                'max_tokens':131072,'context_window':262144,'output_budget':'explicit',
                'sampling_era':'explicit-v1','inference_profile':{
                    'mapping_version':inference_profiles.MAPPING_VERSION,'backend':'omlx','backend_version':'fixture',
                    'lane':'thinking','route':{'kind':'dsg','name':'fixture-route'},
                    'values':{'temperature':0,'top_p':.95,'top_k':20,'min_p':0,'presence_penalty':0,
                              'repetition_penalty':1,'enable_thinking':True,'preserve_thinking':False,'reasoning_effort':'xhigh'}}}

    def run_profile(self,cfg):
        return harness_runner.run({'id':'T','kind':'mcq','prompt':'Choose 001.',
                                   'options':[{'id':'001','text':'one'},{'id':'002','text':'two'}]},cfg,self.work,False)

    def test_stream_continuation_and_serialized_evidence(self):
        cfg=self.cfg();_,metrics,answer,_=self.run_profile(cfg)
        self.assertEqual(answer,{'option':'001'});self.assertEqual(len(self.requests),2)
        expected=inference_profiles.request_settings(cfg)
        for request in self.requests:
            for key,value in expected.items():self.assertEqual(request[key],value)
            self.assertNotIn('max_completion_tokens',request)
        self.assertTrue(any(m['role']=='tool' for m in self.requests[1]['messages']))
        self.assertTrue(all(h.get('x-dsg-model')=='fixture-route' for h in self.headers))
        self.assertEqual(len(metrics['requested_settings']),2)
        self.assertTrue(all(r['source']=='serialized_request' and r['values']==expected for r in metrics['requested_settings']))

    def test_complete_response_and_deliberate_output_omission(self):
        cfg=self.cfg();cfg.update(response_mode='complete',output_budget='server')
        _,metrics,answer,_=self.run_profile(cfg)
        self.assertEqual(answer,{'option':'001'})
        for request in self.requests:
            self.assertFalse(request['stream']);self.assertNotIn('stream_options',request)
            self.assertNotIn('max_tokens',request);self.assertNotIn('max_completion_tokens',request)
        self.assertTrue(all('max_tokens' not in r['values'] and r['response_mode']=='complete' for r in metrics['requested_settings']))

    def test_sdk_retry_keeps_settings_and_route(self):
        self.fail_first=True;cfg=self.cfg()
        _,metrics,answer,_=self.run_profile(cfg)
        self.assertEqual(answer,{'option':'001'});self.assertGreaterEqual(len(self.raw),3)
        self.assertEqual(self.raw[0],self.raw[1],'SDK retry must retain the serialized request')
        self.assertTrue(all(h.get('x-dsg-model')=='fixture-route' for h in self.headers))
        self.assertEqual(len(metrics['requested_settings']),len(self.raw))

    def test_vllm_rejects_store_and_preserves_other_request_bytes(self):
        # Exercise real pinned-Pi serialization, both response modes and the
        # continuation after a tool call. The existing generic provider is the
        # baseline: only the unsupported field may differ for vLLM.
        for mode in ('stream','complete'):
            with self.subTest(mode=mode):
                self.requests.clear(); self.raw.clear(); self.headers.clear(); self.successes=0
                self.reject_store=False
                cfg=self.cfg(); cfg['response_mode']=mode
                self.run_profile(cfg)
                baseline=copy.deepcopy(self.requests)
                self.assertTrue(all(r.get('store') is False for r in baseline))
                self.requests.clear(); self.raw.clear(); self.headers.clear(); self.successes=0
                self.reject_store=True
                cfg['inference_profile']['backend']='vllm'
                _,metrics,answer,_=self.run_profile(cfg)
                self.assertEqual(answer,{'option':'001'})
                self.assertEqual(len(self.requests),2)
                for before,after in zip(baseline,self.requests):
                    before.pop('store')
                    self.assertEqual(after,before)
                self.assertTrue(all(h.get('x-dsg-model')=='fixture-route' for h in self.headers))
                self.assertEqual(metrics['context_window'],262144)
                self.assertTrue(all(r['values']==inference_profiles.request_settings(cfg) for r in metrics['requested_settings']))

    def test_context_error_removed_by_pi_still_stops_outer_loop(self):
        self.reject_context=True
        cfg=self.cfg(); cfg['inference_profile']['backend']='vllm'; cfg['max_tokens']=262144
        with self.assertRaises(hourglass.AgentRunError) as caught:
            self.run_profile(cfg)
        self.assertIn('maximum context length',str(caught.exception))
        self.assertEqual(len(self.requests),1,'Do not inject Continue after failed native context recovery.')
        self.assertEqual(self.requests[0]['max_tokens'],262144)

    def test_grandfathered_request_bytes_match_prechange_harness(self):
        cfg=self.cfg();cfg.pop('sampling_era');cfg.pop('inference_profile')
        cfg['temperature']=1;cfg['extra']={'temperature':2,'top_k':20,'chat_template_kwargs':{'enable_thinking':False}}
        with tempfile.TemporaryDirectory() as tmp:
            baseline=pathlib.Path(tmp);(baseline/'harness').mkdir()
            (baseline/'vendor').symlink_to(ROOT/'vendor',target_is_directory=True)
            for file in (ROOT/'harness').iterdir():
                if file.name!='pi.mjs':(baseline/'harness'/file.name).symlink_to(file)
            (baseline/'harness/pi.mjs').write_bytes((ROOT/'tests/fixtures/pi-before-explicit.mjs').read_bytes())
            popen=subprocess.Popen
            def old_popen(command,*args,**kwargs):
                if isinstance(command,list) and len(command)>1 and command[1]==str(ROOT/'harness/pi.mjs'):
                    command=[command[0],str(baseline/'harness/pi.mjs'),*command[2:]]
                return popen(command,*args,**kwargs)
            with patch.object(harness_runner.subprocess,'Popen',side_effect=old_popen):self.run_profile(cfg)
        before=list(self.raw);self.raw.clear();self.requests.clear();self.headers.clear();self.successes=0
        self.run_profile(cfg)
        self.assertEqual(self.raw,before)
        self.assertTrue(all('temperature' not in r for r in self.requests))

    def test_exported_extension_matches_native_serializer(self):
        cfg=self.cfg();expected=inference_profiles.request_settings(cfg)
        # Run the handoff extension through the same pinned native Pi serializer.
        # Its payload hook replaces the benchmark hook, not just a standalone dict.
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/'harness').mkdir()
            (root/'vendor').symlink_to(ROOT/'vendor',target_is_directory=True)
            for file in (ROOT/'harness').iterdir():
                if file.name!='pi.mjs':(root/'harness'/file.name).symlink_to(file)
            source=(ROOT/'harness/pi.mjs').read_text()
            source=source.replace("if(cfg.sampling_era==='explicit-v1')return applyExplicitSettings(p,input.requestSettings);",
                                  "if(cfg.sampling_era==='explicit-v1')return handoffHook(e);")
            extension=profile_export.extension_source(expected).replace('<MODEL_ID>','fixture')
            (root/'handoff.mjs').write_text(extension)
            source="import handoff from '../handoff.mjs';\nlet handoffHook; handoff({on:(_event,fn)=>handoffHook=fn});\n"+source
            (root/'harness/pi.mjs').write_text(source)
            popen=subprocess.Popen
            def handoff_popen(command,*args,**kwargs):
                if isinstance(command,list) and len(command)>1 and command[1]==str(ROOT/'harness/pi.mjs'):
                    command=[command[0],str(root/'harness/pi.mjs'),*command[2:]]
                return popen(command,*args,**kwargs)
            with patch.object(harness_runner.subprocess,'Popen',side_effect=handoff_popen):
                _,metrics,answer,_=self.run_profile(cfg)
        self.assertEqual(answer,{'option':'001'})
        self.assertTrue(all(record['values']==expected for record in metrics['requested_settings']))


if __name__=='__main__':unittest.main()
