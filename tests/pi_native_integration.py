"""Real pinned-Pi serialization, native SDK parity, retry and compaction."""
import copy
import json
import pathlib
import subprocess
import unittest
from unittest.mock import patch
import pi_explicit_integration as fixtures
ROOT=fixtures.ROOT
import stock_pi
import harness_runner


class StockPi(unittest.TestCase):
    setUp = fixtures.NativeProfiles.setUp
    run_profile = fixtures.NativeProfiles.run_profile

    def cfg(self, backend='vllm'):
        cfg=fixtures.NativeProfiles.cfg(self)
        cfg['model']='qwen3.8-fixture'
        cfg['max_tokens']=262144
        cfg['inference_profile']['backend']=backend
        if backend=='mtplx':
            for key in ('min_p','repetition_penalty','preserve_thinking'):
                cfg['inference_profile']['values'].pop(key,None)
        return stock_pi.migrate(cfg)

    def test_stock_sdk_parity_and_native_context_sizing(self):
        cfg=self.cfg(); request_path=None; popen=subprocess.Popen
        def observe(command,*args,**kwargs):
            nonlocal request_path
            if isinstance(command,list) and len(command)>1 and command[1]==str(ROOT/'harness/pi.mjs'):
                request_path=command[2]
            return popen(command,*args,**kwargs)
        with patch.object(harness_runner.subprocess,'Popen',side_effect=observe):
            _,metrics,answer,_=self.run_profile(cfg)
        self.assertEqual(answer,{'option':'001'})
        actual=copy.deepcopy(self.requests); self.requests.clear(); self.successes=0
        ref=subprocess.run(['node',str(ROOT/'tests/pi-native-reference.mjs'),request_path,str(self.work/'reference-agent')],capture_output=True,text=True,timeout=30)
        self.assertEqual(ref.returncode,0,ref.stderr)
        self.assertEqual(json.loads(ref.stdout)['thinking'],'xhigh')
        self.assertEqual(self.requests,actual,'Full serialized bodies must match a plain pinned-Pi SDK session.')
        self.assertEqual(len(actual),2)
        for request in actual:
            self.assertLess(request['max_tokens'],262144)
            self.assertGreater(request['max_tokens'],60000)
            self.assertEqual(request['chat_template_kwargs']['reasoning_effort'],'xhigh')
            self.assertNotIn('store',request)
        self.assertNotEqual(actual[0]['max_tokens'],actual[1]['max_tokens'])
        session=metrics['pi_session']
        self.assertEqual(session['thinking_level'],'xhigh')
        self.assertEqual(session['http_idle_timeout_ms'],300000)
        self.assertEqual(session['compaction'],{'enabled':True,'reserveTokens':16384,'keepRecentTokens':20000})
        self.assertTrue(session['retry']['enabled'])
        self.assertEqual(session['retry']['maxRetries'],3)

    def test_native_mtplx_and_transient_retry(self):
        self.fail_first=True
        _,metrics,answer,_=self.run_profile(self.cfg('mtplx'))
        self.assertEqual(answer,{'option':'001'})
        self.assertEqual(self.raw[0],self.raw[1])
        for request in self.requests:
            self.assertTrue(request['enable_thinking'])
            self.assertEqual(request['reasoning_effort'],'xhigh')
            self.assertNotIn('chat_template_kwargs',request)
        self.assertEqual(len(metrics['requested_settings']),len(self.requests))

    def test_automatic_compaction_keeps_selected_thinking(self):
        self.reported_prompt_tokens=250000
        _,metrics,answer,_=self.run_profile(self.cfg())
        self.assertEqual(answer,{'option':'001'})
        summaries=[r for r in self.requests if not r.get('tools')]
        self.assertTrue(summaries,'Usage above the native threshold must trigger compaction.')
        for request in self.requests:
            self.assertEqual(request['chat_template_kwargs']['reasoning_effort'],'xhigh')
        self.assertTrue(all(r['max_tokens']<=13107 for r in summaries),'Use Pi’s compaction allowance, not the model output capacity.')
        self.assertEqual(len(metrics['requested_settings']),len(self.requests))


if __name__=='__main__':unittest.main()
