import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import endpoint_hardware as eh
import hardware_records
import web

class EndpointHardwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.url='http://127.0.0.1:38002/v1'
        self.models=[{'name':'Model A','model':'fixture','base_url':self.url,'max_tokens':262144,'extra':{'reasoning_effort':'high'}},{'name':'Model B','base_url':self.url},{'name':'Remote','base_url':'http://remote.test/v1'}]
        (self.root/'models.json').write_text(json.dumps({'models':self.models}));self.original=(self.root/'models.json').read_bytes()
    def save(self,**changes):
        body={'base_url':self.url,'revision':eh.revision(eh.load(self.root)),'machine':'new','label':'Test Spark','chip':'Test GB10','memory_gib':'128','cpu_cores':'20','gpu_model':'Test GPU'};body.update(changes)
        return eh.save(self.root,self.models,body)
    def test_tunnel_uses_remote_hardware_without_changing_models_or_history(self):
        h=self.root/'evaluations';h.mkdir();m=h/'old.json';m.write_text('{"hardware":{"label":"Original"}}')
        result=self.save()
        with patch.object(hardware_records.platform,'system',side_effect=AssertionError('Do not inspect controller')):record=hardware_records.capture(self.root,self.models[0])
        self.assertEqual(record['label'],'Test Spark');self.assertEqual(record['memory_bytes'],128*2**30);self.assertEqual(record['source'],'owner supplied')
        self.assertEqual((self.root/'models.json').read_bytes(),self.original);self.assertEqual(m.read_text(),'{"hardware":{"label":"Original"}}')
        self.assertTrue((self.root/result['backup']/'previously-absent.txt').exists());self.assertEqual(len(result['hardware']['endpoints']),2)
    def test_identity_reuse_extensions_and_backup(self):
        self.save();profiles=eh.load(self.root);identity=profiles[self.url]['machine_id']
        profiles[self.url]['private_extension']={'keep':True};profiles[self.url]['gpu'][0]['cores']='existing';profiles['http://unrelated/v1']={'machine_id':'other','label':'Other','unknown':'keep'}
        (self.root/'hardware-profiles.json').write_text(json.dumps(profiles));before=hardware_records.capture(self.root,self.models[0])
        result=self.save(base_url='http://remote.test/v1',machine='machine:'+identity,label='Renamed Spark');after=eh.load(self.root)
        self.assertEqual(after[self.url]['label'],'Renamed Spark');self.assertEqual(after[self.url]['private_extension'],{'keep':True});self.assertEqual(after[self.url]['gpu'][0]['cores'],'existing');self.assertEqual(after['http://unrelated/v1'],profiles['http://unrelated/v1'])
        self.assertEqual(hardware_records.capture(self.root,{'base_url':'http://remote.test/v1'})['machine_key'],before['machine_key'])
        self.assertEqual(json.loads((self.root/result['backup']/'hardware-profiles.json').read_text()),profiles);self.assertNotIn('private_extension',json.dumps(result['hardware']))
    def test_invalid_and_stale_requests_do_not_write(self):
        for changes in [{'cpu_cores':'1.5'},{'memory_gib':'nan'},{'memory_gib':True},{'label':''},{'machine':'machine:missing'},{'base_url':'http://missing/v1'},{'machine':'local','base_url':'http://remote.test/v1'},{'revision':'stale'}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.save(**changes)
            self.assertFalse((self.root/'hardware-profiles.json').exists())
        old=eh.revision({});self.save();before=(self.root/'hardware-profiles.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):self.save(revision=old)
        self.assertEqual((self.root/'hardware-profiles.json').read_bytes(),before)
    def test_local_choice_and_unknown_optional_fields(self):
        self.save(memory_gib='',cpu_cores='',gpu_model='');before=eh.load(self.root)
        for k in ['memory_bytes','cpu_cores','gpu']:self.assertNotIn(k,before[self.url])
        result=self.save(machine='local');self.assertIn('machine_id',eh.load(self.root)[self.url]);self.assertEqual(json.loads((self.root/result['backup']/'hardware-profiles.json').read_text()),before)
    def test_corrupt_profiles_not_replaced(self):
        p=self.root/'hardware-profiles.json';p.write_text('not json');self.assertIn('error',eh.snapshot(self.root,self.models))
        with self.assertRaises(ValueError):eh.save(self.root,self.models,{})
        self.assertEqual(p.read_text(),'not json')
    def test_stale_review_cannot_create_evaluation(self):
        body={'model':'Model A','tasks':['fixture'],'repeat':1,'hardware_revision':eh.revision({})};self.save()
        with patch.object(web,'ROOT',self.root),patch.object(web,'task_catalog',return_value=[{'id':'fixture','issues':[]}]),patch.object(web,'ordered_tasks',return_value=['fixture']),patch.object(web.calibration,'evaluation_manifest') as create:
            with self.assertRaisesRegex(ValueError,'changed after review'):web.enqueue(body)
            create.assert_not_called()
