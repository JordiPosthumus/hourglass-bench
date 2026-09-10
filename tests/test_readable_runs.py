import copy
import tempfile
import unittest
from pathlib import Path
import run_editor
import run_naming
import repeat_reports

class ReadableRunsTests(unittest.TestCase):
    def test_example_and_override_reset(self):
        values={'hardware':'DGX Spark','server_name':'BlazuxBF16KVC1','model_name':'Qwen3.8','quantization':'NVFP4'}
        self.assertEqual(run_naming.describe({},values)['name'],'DGXSP-BlazuxBF16KVC1-Qwen3.8-NVFP4')
        self.assertEqual(run_naming.describe({},dict(values,run_name='Mine'))['name'],'Mine')
        self.assertEqual(run_naming.describe({})['name'],'XXX-XXX-XXX-XXX')
        with self.assertRaises(ValueError):run_editor.required_identity({'hardware':'XXX'})
        self.assertEqual(run_editor.required_identity(values),values)
    def test_shared_corrections_and_reset_preserve_sidecars(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a={'id':'a','model':'m','model_id':'M','config_hash':'c','hardware':{'label':'H','machine_key':'h'}};b=dict(a,id='b')
            run_editor.save(root,a,{'values':{'run_name':'First','temperature':.5},'applies_from':'run_start'})
            before=(root/'evaluations/a.details.jsonl').read_bytes()
            record=run_editor.save(root,b,{'values':{'run_name':'Corrected','temperature':.9},'applies_from':'run_start'})
            self.assertEqual(run_editor.display(root,a)['name'],'Corrected')
            self.assertEqual(run_editor.display_values(root,a)['temperature'],.5)
            run_editor.save(root,b,{'values':{},'base_revision':record['id'],'applies_from':'run_start'})
            self.assertFalse(run_editor.display(root,a)['overridden'])
            self.assertEqual((root/'evaluations/a.details.jsonl').read_bytes(),before)
    def test_repeat_mean_curve_and_incompatible_runs(self):
        a={'run_key':'a','configuration_key':'c','model':'m','state':'final','bank_fingerprint':'b','benchmark_version':'2.6','scoring':'net','weighted_points':2,'curve':[{'seconds':0,'weighted':0,'correct':0},{'seconds':60,'weighted':2,'correct':1}]}
        b=dict(a,run_key='b',weighted_points=4,curve=[{'seconds':0,'weighted':0,'correct':0},{'seconds':120,'weighted':4,'correct':2}])
        old=dict(a,run_key='old',bank_fingerprint='old');live=dict(a,run_key='live',is_current_run=True,state='partial')
        reports=[a,b,old,live];before=copy.deepcopy(reports);out=repeat_reports.average(reports)
        self.assertEqual(len(out),3);mean=out[0];self.assertEqual(mean['weighted_points'],3)
        self.assertEqual([p['weighted'] for p in mean['curve'] if p['seconds']==60],[0,1])
        self.assertEqual([p['weighted'] for p in mean['curve'] if p['seconds']==120],[1,3])
        self.assertEqual(mean['member_run_keys'],['a','b']);self.assertEqual(reports,before)
    def test_http_name_preview_uses_current_fields(self):
        import io,json,web
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            body={'job':'a','values':{'hardware':'DGX Spark','server_name':'BlazuxBF16KVC1','model_name':'Qwen3.8','quantization':'NVFP4'}}
            raw=json.dumps(body).encode();handler=object.__new__(web.H)
            handler.path='/api/run-name';handler.headers={'Content-Type':'application/json','Content-Length':str(len(raw))};handler.rfile=io.BytesIO(raw)
            responses=[];handler._json=lambda value,status=200:responses.append((status,value))
            with patch.object(web,'ROOT',Path(d)),patch.object(web,'saved_manifest',return_value={'id':'a','model':'m'}):handler.do_POST()
            self.assertEqual(responses[0][0],200);self.assertEqual(responses[0][1]['name'],'DGXSP-BlazuxBF16KVC1-Qwen3.8-NVFP4')
