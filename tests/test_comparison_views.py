import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import io
import score_report,hardware_records,harness_runner
class ComparisonViews(unittest.TestCase):
 def test_scopes_ranking_and_hardware_labels(self):
  base=dict(model='Same model',machine_key='one',hardware={'label':'Mac & desktop'},bank_fingerprint='a',scoring='v',timing_policy='h',benchmark_version='v',weighted_points=0,raw_correct=0,state='partial',curve=[])
  other={**base,'machine_key':'two','hardware':{'label':'Spark 2'},'weighted_points':8,'state':'in_progress'}
  reports=[base,other,{**other,'bank_fingerprint':'bad','model':'Exclude'}]
  self.assertEqual(len(json.loads(score_report.comparison(reports)['comparison.json'])['reports']),1)
  self.assertEqual(len(json.loads(score_report.comparison(reports,'all')['comparison.json'])['reports']),2)
  svg=score_report.ranking(reports,'all')['ranking.svg']
  self.assertLess(svg.index('Spark 2'),svg.index('Mac &amp; desktop'));self.assertNotIn('Exclude',svg);self.assertIn('0.00',svg);self.assertIn('in_progress',svg)
 def test_hardware_string_and_legacy_identity(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);cfg={'base_url':'http://server/v1','hardware':'Spark'}
   a=hardware_records.capture(root,cfg);b=hardware_records.capture(root,{**cfg,'model':'other'})
   self.assertEqual(a['machine_key'],b['machine_key']);self.assertEqual(a['label'],'Spark')
   (root/'hardware-profiles.json').write_text(json.dumps({cfg['base_url']:{'machine_id':'old','label':'Spark','chip':'GB10'}}))
   self.assertEqual(hardware_records.capture(root,cfg)['machine_key'],hardware_records.capture(root,{'base_url':cfg['base_url']})['machine_key'])
 def test_server_metadata_uses_matching_model(self):
  with patch.object(harness_runner.urllib.request,'urlopen',side_effect=[OSError('not LM Studio'),io.BytesIO(json.dumps({'data':[{'id':'other','context_length':1},{'id':'ds4','context_length':262144}]}).encode())]):
   meta=harness_runner.server_metadata({'base_url':'http://localhost/v1','model':'ds4'})
  self.assertEqual(meta['context_window'],262144);self.assertIsNone(meta['temperature'])
