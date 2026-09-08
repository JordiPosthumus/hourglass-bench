import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import hourglass,launch,web,harness_runner
class AuditTests(unittest.TestCase):
 def test_discovery_timeout_returns_false(self):
  with patch.object(launch.urllib.request,'urlopen',side_effect=TimeoutError('silent socket')) as call:
   self.assertFalse(launch.existing_bench(8788));self.assertEqual(call.call_args.kwargs['timeout'],30)
 def test_metadata_timeout_stays_unknown(self):
  with patch.object(harness_runner.urllib.request,'urlopen',side_effect=TimeoutError('silent socket')) as call:
   m=harness_runner.server_metadata({'base_url':'http://localhost/v1','model':'x'})
   self.assertIsNone(m['temperature']);self.assertIn('metadata_error',m);self.assertEqual(call.call_args.kwargs['timeout'],30)
 def test_connection_check_timeout_reports_unreachable(self):
  with patch.object(web,'model_document',return_value={'models':[{'name':'x','base_url':'http://localhost/v1','model':'x'}]}),patch.object(web.urllib.request,'urlopen',side_effect=TimeoutError('silent socket')) as call:
   self.assertFalse(web.check_model('x')['reachable']);self.assertEqual(call.call_args.kwargs['timeout'],30)
 def test_provenance_timeouts_and_deduplicated_endpoints(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'models.json';p.write_text(json.dumps({'models':[{'base_url':'http://localhost/v1'}]*3}))
   with patch.object(hourglass.subprocess,'run',side_effect=TimeoutError('probe')) as shell,patch.object(hourglass.urllib.request,'urlopen',side_effect=TimeoutError('socket')) as http:
    result=hourglass.capture_provenance(p)
   self.assertEqual(http.call_count,2);self.assertTrue(all(c.kwargs['timeout']==30 for c in http.call_args_list));self.assertTrue(all(c.kwargs['timeout']==30 for c in shell.call_args_list));self.assertIn('unreachable',result['servers']['http://localhost/v1']['models'])
 def test_skips_withhold_all_repeats_claim(self):
  with tempfile.TemporaryDirectory() as d:
   base={'task':'x','model':'m','benchmark_version':'2.0.0','status':'completed','solved':False}
   hourglass.cmd_leaderboard(None,rows=[{**base,'solved':True},{**base,'score_reason':'wrong_streak_limit'}],root=Path(d),emit=False)
   doc=(Path(d)/'leaderboard.md').read_text()
   self.assertIn('policy-defined zeros, not observed incorrect',doc);self.assertIn('| 2 | 1 | 1 | not fully observed |',doc)
