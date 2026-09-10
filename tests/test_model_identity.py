import io,json,unittest
from unittest.mock import patch
import harness_runner,model_catalog

class ModelIdentityTests(unittest.TestCase):
 def metadata(self,identifier,models):
  def response(url,**kwargs):
   url=getattr(url,'full_url',url)
   return io.BytesIO(json.dumps({'models':models} if '/api/' in url else {'data':[]}).encode())
  with patch.object(harness_runner.urllib.request,'urlopen',side_effect=response):
   return harness_runner.server_metadata({'base_url':'http://localhost/v1','model':identifier})
 def test_selected_downloaded_variant_uses_served_base_id(self):
  rows=model_catalog.normalize_lms([{'model':{'modelKey':'vendor/model','selectedVariant':'vendor/model@q4','maxContextLength':131072},'variants':[{'modelKey':'vendor/model@q4'},{'modelKey':'vendor/model@q8'}]}],[])
  self.assertEqual([(r['model_id'],r['model_key']) for r in rows],[('vendor/model','vendor/model@q4'),('vendor/model@q8','vendor/model@q8')])
 def test_picker_id_round_trips_through_runtime_metadata(self):
  rows=model_catalog.normalize_lms([{'model':{'modelKey':'vendor/model','selectedVariant':'vendor/model@q4','maxContextLength':131072},'variants':[{'modelKey':'vendor/model@q4'}]}],[])
  native=[{'key':'vendor/model','selected_variant':'vendor/model@q4','variants':['vendor/model@q4'],'max_context_length':131072,'loaded_instances':[]}]
  self.assertEqual(self.metadata(rows[0]['model_id'],native)['context_window'],131072)
  self.assertEqual(self.metadata('vendor/model@q4',native)['context_window'],131072)
 def test_loaded_alias_uses_actual_context_not_other_model(self):
  native=[{'key':'other','max_context_length':999},{'key':'vendor/model','max_context_length':131072,'loaded_instances':[{'id':'custom-alias','config':{'context_length':65536}}]}]
  self.assertEqual(self.metadata('custom-alias',native)['context_window'],65536)
  self.assertNotIn('context_window',self.metadata('vendor/model@wrong',native))

if __name__=='__main__':unittest.main()
