import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import settings_records,web
class SettingsRecordsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'evaluations').mkdir()
  self.manifest={'id':'abc123','started':100,'state':'running'}
  (self.root/'evaluations/abc123.json').write_text(json.dumps(self.manifest))
 def test_append_keeps_history_and_unknown_fields(self):
  a=settings_records.append(self.root,self.manifest,{'settings':{'temperature':0,'top_p':'','reasoning':'on'},'applies_from':'run_start'},now=200)
  b=settings_records.append(self.root,self.manifest,{'settings':{'temperature':.8},'applies_from':'now'},now=300)
  records=settings_records.records(self.root,'abc123');self.assertEqual(records,[a,b]);self.assertEqual(a['effective_at'],100);self.assertEqual(b['effective_at'],300);self.assertEqual(a['settings'],{'temperature':0,'reasoning':'on'});self.assertEqual(a['source'],'user_reported')
 def test_reject_invalid_values_and_unspecified_timing(self):
  for settings in ({'temperature':-1},{'temperature':float('nan')},{'top_k':1.5},{'top_p':1.1},{'min_p':True},{'unknown':1},{}):
   with self.subTest(settings=settings),self.assertRaises(ValueError):settings_records.append(self.root,self.manifest,{'settings':settings,'applies_from':'now'})
  with self.assertRaises(ValueError):settings_records.append(self.root,self.manifest,{'settings':{'temperature':1}})
  self.assertEqual(settings_records.records(self.root,'abc123'),[])
 def test_api_does_not_change_config_or_manifest(self):
  config=self.root/'models.json';config.write_text('{"models":[]}');before=(self.root/'evaluations/abc123.json').read_bytes()
  with patch.object(web,'ROOT',self.root):
   record=web.record_settings({'job':'abc123','settings':{'temperature':.7},'applies_from':'run_start','note':'API settings panel'})
   with self.assertRaises(ValueError):web.record_settings({'job':'../escape','settings':{'temperature':1},'applies_from':'now'})
  self.assertEqual(record['note'],'API settings panel');self.assertEqual(config.read_text(),'{"models":[]}');self.assertEqual((self.root/'evaluations/abc123.json').read_bytes(),before)
