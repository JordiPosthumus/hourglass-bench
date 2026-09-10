import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import model_catalog as catalog
import model_store
import hourglass

class CatalogTests(unittest.TestCase):
    def inspect(self, docs, url='http://example.invalid:8000'):
        seen=[]
        def read(url):
            path=catalog.urllib.parse.urlsplit(url).path;seen.append(path)
            return {'url':url,'status':200 if path in docs else 404,'http_server':'fixture','data':docs.get(path)}
        with patch.object(catalog,'read_endpoint',side_effect=read):result=catalog.inspect_endpoint(url)
        self.assertTrue(set(seen)<= {'/v1/models','/models','/api/v1/models','/props','/health'})
        return result
    def test_generic_context_and_props(self):
        result=self.inspect({'/v1/models':{'data':[{'id':'ds4','max_model_len':1048576,'top_provider':{'max_completion_tokens':262144},'owned_by':'ds4.c','supported_parameters':['tools']}]},'/props':{'total_slots':4,'default_generation_settings':{'params':{'n_ctx':1048576,'n_predict':-1}}},'/health':{'status':'ok'}})
        self.assertEqual(result['base_url'],'http://example.invalid:8000/v1')
        self.assertEqual(result['models'][0]['context_length'],1048576)
        self.assertEqual(result['models'][0]['max_output_tokens'],262144)
        self.assertEqual(result['models'][0]['provider'],'ds4.c')
        self.assertEqual(result['models'][0]['supported_parameters'],['tools'])
        self.assertIsNone(result['models'][0]['loaded'])
        self.assertIn({'label':'Parallel slots','value':4,'source':'/props'},result['reported'])
    def test_unknown_and_malformed_native(self):
        for malformed in (None,False,4,{},[{'key':'a','loaded_instances':[None,2,{'id':'a','config':3}]}]):
            result=self.inspect({'/v1/models':{'data':[{'id':'a','top_provider':3}]},'/api/v1/models':{'models':malformed}})
            self.assertIsNone(result['models'][0]['context_length'])
    def test_loaded_alias_context(self):
        result=self.inspect({'/v1/models':{'data':[{'id':'alias'}]},'/api/v1/models':{'models':[{'key':'disk/model','max_context_length':262144,'loaded_instances':[{'id':'alias','config':{'context_length':131072}}]}]}})
        self.assertEqual(result['models'][0]['context_length'],131072)
        self.assertTrue(result['models'][0]['loaded'])
    def test_input_variants(self):
        for suffix in ('/v1','/v1/models','/v1/chat/completions','/api/v1/models'):
            self.assertEqual(self.inspect({'/v1/models':{'data':[]}},'http://example.invalid:8000'+suffix)['base_url'],'http://example.invalid:8000/v1')
    def test_authenticated_discovery_headers(self):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.status=200;response.headers={'Server':'fixture'}
        response.read.return_value=b'{"data":[{"id":"protected-model"}]}'
        response.__enter__.return_value=response
        with patch.object(catalog.urllib.request,'urlopen',return_value=response) as request_call:
            result=catalog.inspect_endpoint('http://example.invalid/v1','test-secret')
        self.assertEqual(result['models'][0]['model_id'],'protected-model')
        self.assertIsNone(result['error'])
        self.assertEqual(request_call.call_count,4)
        for call in request_call.call_args_list:
            request=call.args[0]
            self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.get_header('Authorization'),'Bearer test-secret')
        self.assertNotIn('test-secret',json.dumps(result))

    def test_auth_errors_and_optional_probe_denial(self):
        for status in (401,403):
            def read(url):
                return {'url':url,'status':status,'http_server':'fixture'}
            with patch.object(catalog,'read_endpoint',side_effect=read):
                result=catalog.inspect_endpoint('http://example.invalid/v1')
            self.assertIn(f'HTTP {status}',result['error'])
            self.assertTrue(result['reachable'])
        def read(url):
            return {'url':url,'status':200 if url.endswith('/v1/models') else 401,
                    'http_server':'fixture','data':{'data':[{'id':'ok'}]} if url.endswith('/v1/models') else None}
        with patch.object(catalog,'read_endpoint',side_effect=read):
            self.assertIsNone(catalog.inspect_endpoint('http://example.invalid/v1')['error'])

    def test_http_error_keeps_server_and_hides_body(self):
        import io
        from unittest.mock import MagicMock
        error=catalog.urllib.error.HTTPError('http://example.invalid',401,'Unauthorized',{'Server':'uvicorn'},io.BytesIO(b'secret'))
        with patch.object(catalog.urllib.request,'urlopen',side_effect=error):
            result=catalog.read_endpoint('http://example.invalid')
        self.assertEqual(result['http_server'],'uvicorn')
        self.assertEqual(result['status'],401)
        self.assertNotIn('secret',json.dumps(result))

    def test_lms_variants_and_alias(self):
        disk=[{'model':{'modelKey':'vendor/model','type':'llm','maxContextLength':262144},'variants':[{'modelKey':'vendor/model@q4'},{'modelKey':'vendor/model@q8'}]}]
        rows=catalog.normalize_lms(disk,[{'modelKey':'vendor/model','selectedVariant':'vendor/model@q4','identifier':'my-alias','contextLength':131072}])
        self.assertEqual([r['model_id'] for r in rows],['my-alias','vendor/model@q8'])
        self.assertEqual(rows[0]['context_length'],131072)
        self.assertFalse(rows[1]['loaded'])
    def test_lms_only_read_commands(self):
        with patch.object(catalog,'lms_binary',return_value='lms'),patch.object(catalog,'lms_json',side_effect=[[],[],{'running':True,'port':1235}]) as call:
            self.assertEqual(catalog.lmstudio()['base_url'],'http://127.0.0.1:1235/v1')
            self.assertEqual([c.args[1] for c in call.call_args_list],[['ls','--llm','--variants','--json'],['ps','--json'],['server','status','--json']])
    def test_redacts_metadata(self):
        self.assertEqual(catalog.metadata({'api_key':'secret','nested':{'prompt':'text'}}),{'api_key':'[redacted]','nested':{'prompt':'[redacted]'}})

class ModelStoreTests(unittest.TestCase):
    def test_append_backup_and_stale_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old={'models':[{'name':'existing','model':'model','base_url':'http://host/v1','max_tokens':262144,'extra':{'custom':[1,2]}}],'owner_field':{'keep':True}}
            original=json.dumps(old).encode();(root/'models.json').write_bytes(original)
            _,revision=model_store.read(root)
            entry={'name':'new','model':'fixture','base_url':'http://other/v1','max_tokens':1048576,'context_window':1048576,'output_budget':'explicit','custom':{'preserve':True},'sampling_era':'explicit-v1','inference_profile':{'mapping_version':'request-api-v1','backend':'omlx','backend_version':'fixture','lane':'standard','route':{'kind':'direct'},'values':{'temperature':0,'top_p':0.95}}}
            result=model_store.add(root,entry,hourglass.validate_models,revision)
            saved=json.loads((root/'models.json').read_text());self.assertEqual(saved['models'][0],old['models'][0]);self.assertEqual(saved['owner_field'],old['owner_field']);self.assertEqual(saved['models'][1],entry)
            self.assertEqual((root/result['backup']/'models.json').read_bytes(),original)
            changed=(root/'models.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'changed elsewhere'):model_store.save_json(root,json.dumps(old),hourglass.validate_models,revision)
            with self.assertRaisesRegex(ValueError,'already saved'):model_store.add(root,entry,hourglass.validate_models)
            self.assertEqual((root/'models.json').read_bytes(),changed)
    def test_requires_explicit_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            for budget in (None,0,False,-1,'1024'):
                with self.assertRaises(ValueError):model_store.add(Path(tmp),{'name':'new','model':'id','base_url':'http://host/v1','max_tokens':budget},hourglass.validate_models)
            self.assertFalse((Path(tmp)/'models.json').exists())

if __name__=='__main__':unittest.main()
