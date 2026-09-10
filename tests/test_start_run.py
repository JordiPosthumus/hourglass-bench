import copy
import io
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

import calibration
import run_editor
import run_naming
import web


class StartRunTests(unittest.TestCase):
    def test_recorded_profile_is_used_without_guessing_alias_quantization(self):
        config={'model':'arbitrary-fp16-alias','inference_profile':{'backend':'mtplx','backend_version':'2.11.2'}}
        original=copy.deepcopy(config)
        identity=run_naming.describe({'model_config_snapshot':config})
        self.assertEqual(identity['fields']['server_name'],'MTPLX')
        self.assertEqual(identity['fields']['server_version'],'2.11.2')
        self.assertEqual(identity['fields']['quantization'],'')
        explicit=run_naming.describe({'model_config_snapshot':config},{'server_name':'My saved recipe','server_version':'Recorded build'})
        self.assertEqual(explicit['fields']['server_name'],'My saved recipe')
        self.assertEqual(explicit['fields']['server_version'],'Recorded build')
        self.assertEqual(config,original)

    def test_http_start_accepts_blank_labels_and_freezes_exact_execution_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);task=root/'tasks/example/task.json';task.parent.mkdir(parents=True)
            task.write_text(json.dumps({'id':'example','kind':'mcq','mode':'option_id','prompt':'Setup fixture.',
                'options':[{'id':'001','text':'Example choice one'},{'id':'002','text':'Example choice two'}],'answer':'001'}))
            config={'name':'fixture','model':'example-fp16-alias','base_url':'http://example.invalid/v1',
                    'max_tokens':262144,'context_window':262144,'hardware':'Recorded machine','reasoning':'xhigh'}
            path=root/'models.json';path.write_text(json.dumps({'models':[config]}));before=path.read_bytes()
            request={'model':'fixture','tasks':['example'],'repeat':1,'identity':{'hardware':'Recorded machine','model_name':config['model'],
                'server_name':'','server_version':'','quantization':''}}
            responses=[];handler=object.__new__(web.H);body=json.dumps(request).encode()
            handler.path='/api/run';handler.headers={'Content-Type':'application/json','Content-Length':str(len(body))};handler.rfile=io.BytesIO(body)
            handler._json=lambda value,status=200:responses.append((status,value))
            with patch.object(web,'ROOT',root),patch.object(web,'TASKS',root/'tasks'),patch.object(web,'queue',deque()),patch.object(web,'shutting_down',False):
                handler.do_POST()
                self.assertEqual(responses[0][0],200,responses)
                self.assertEqual(len(web.queue),1)
                job=web.queue[0];self.assertEqual(responses[0][1]['job'],job['id'])
                manifest=json.loads((root/'evaluations'/(job['id']+'.json')).read_text())
                self.assertEqual(manifest['model_config_snapshot'],config)
                self.assertEqual(manifest['config_hash'],calibration.digest(config))
                self.assertEqual(job['tasks'],['example']);self.assertEqual(job['repeat'],1)
                self.assertNotIn('quantization',run_editor.snapshot(root,job['id'])['values'])
            self.assertEqual(path.read_bytes(),before)

    def test_optional_labels_still_reject_invalid_or_execution_fields(self):
        for values in ({'server_name':'first\nsecond'},{'temperature':1},{'run_name':'x'*501},{'quantization':123}):
            with self.subTest(values=values),self.assertRaises(ValueError):run_editor.required_identity(values)


if __name__=='__main__':unittest.main()
