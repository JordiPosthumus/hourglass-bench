import json,tempfile,unittest
from pathlib import Path
import diagnostics,hourglass,question_deadline
from unittest.mock import patch

class DiagnosticStoreTests(unittest.TestCase):
 def test_new_store_and_legacy_recovery_are_distinct(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);work=root/'sandboxes'/'task';work.mkdir(parents=True)
   legacy=work/'partial-pi-trace.jsonl';legacy.write_text('legacy')
   self.assertEqual(diagnostics.source(root,work,'partial-pi-trace.jsonl'),legacy)
   private=diagnostics.directory(root,work,create=True)
   self.assertFalse(private.is_relative_to(work))
   self.assertEqual(diagnostics.source(root,work,'partial-pi-trace.jsonl'),private/'partial-pi-trace.jsonl')
   self.assertNotEqual(diagnostics.source(root,work,'partial-pi-trace.jsonl',diagnostics.POLICY),legacy)
 def test_integrity_is_outside_workspace_and_task_contents_stay(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);task={'id':'fixture','files':{'fixture.txt':'original','partial-pi-trace.jsonl':'authored'},'verifier':{'forbidden':['fixture.txt']}}
   with patch.object(hourglass,'ROOT',root),patch.object(hourglass,'SANDBOX',root/'sandboxes'):
    work=hourglass.build(task)
   self.assertEqual((work/'fixture.txt').read_text(),'original')
   self.assertEqual((work/'partial-pi-trace.jsonl').read_text(),'authored')
   self.assertFalse((work/'.hourglass-integrity.json').exists())
   integrity=json.loads((diagnostics.directory(root,work)/'integrity.json').read_text())
   self.assertEqual(integrity,{'fixture.txt':hourglass.sha(work/'fixture.txt')})
 def test_checkpoint_inside_workspace_is_rejected(self):
  with tempfile.TemporaryDirectory() as temp:
   work=Path(temp)/'work';work.mkdir()
   with self.assertRaises(ValueError):diagnostics.protected_profile('(version 1)\n(allow default)',[Path(temp)],work,[work/'phase.json'])

if __name__=='__main__':unittest.main()
