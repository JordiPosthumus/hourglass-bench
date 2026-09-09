import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import harness_runner,hourglass
class PiVisionRejection(unittest.TestCase):
 def run_failure(self,message,images=True):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'chart.png').write_bytes(b'fixture')
   task={'kind':'mcq','prompt':'question','options':[],'assets':['chart.png'] if images else []}
   proc=Mock(stdout=io.StringIO(json.dumps({'error':message})+'\n'),stderr=io.StringIO(''));proc.wait.return_value=1
   with patch.object(harness_runner,'verify_frozen',return_value='fixture'),patch.object(harness_runner,'server_metadata',return_value={'temperature':None,'temperature_source':'server default'}),patch.object(harness_runner.subprocess,'Popen',return_value=proc):
    with self.assertRaises(hourglass.AgentRunError) as caught:harness_runner.run(task,{'base_url':'http://fixture/v1','model':'fixture','context_window':262144,'max_tokens':262144},root,False)
   return caught.exception
 def test_exact_laguna_rejection_preserves_trace_and_metrics(self):
  error=self.run_failure('Error: 400: {"message":"The provided messages contain images, but poolside/laguna-s-2.1 does not support image inputs.","type":"invalid_request_error"}')
  self.assertTrue(hourglass.is_unsupported_vision(error));self.assertEqual(error.metrics['completion_tokens'],0);self.assertTrue(error.trace)
 def test_other_errors_and_text_requests_remain_errors(self):
  for message,images in [('Error: 400: invalid image format',True),('Error: 400: context length exceeded',True),('Error: 401: model does not support images',True),('Error: 400: model does not support images',False)]:
   with self.subTest(message=message,images=images):self.assertFalse(hourglass.is_unsupported_vision(self.run_failure(message,images)))

 def test_command_line_namespace_recognizes_harness_exception(self):
  import runpy
  cli=runpy.run_path(str(Path(hourglass.__file__)),run_name="cli_fixture")
  error=self.run_failure('Error: 400: {"message":"The provided messages contain images, but poolside/laguna-s-2.1 does not support image inputs."}')
  self.assertTrue(cli["is_unsupported_vision"](error))
