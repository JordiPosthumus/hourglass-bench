import copy
import json
import os
from collections import deque
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_recovery
import web
import hour_score


class RecoveryTests(unittest.TestCase):
    def fixture(self, root):
        for folder in ('logs', 'sandboxes/question', 'evaluations', 'results'):
            (root/folder).mkdir(parents=True, exist_ok=True)
        m={'id':'fixture','model':'fixture','state':'error','hour_timing_unknown':True,
           'started':1000,'active_intervals':[{'start':1000,'end':1100},{'start':2000,'end':None}],
           'resume_count':1,'expected':[{'task':'a','repeat':1},{'task':'b','repeat':1}],
           'question_elapsed_s':{'b':20}}
        attempt={'task':'b','run_id':'unfinished','started':2010,'workdir':str(root/'sandboxes/question')}
        phase={'phase':'finished','at':2050,'tool_calls':3,'completed_output_tokens':100}
        proof={'trace':[{'result':{'termination':'stopped','answer':{}}}],
               'metrics':{'usage_complete':False,'tool_calls':3,'completion_tokens':100}}
        (root/'logs/attempt-fixture.json').write_text(json.dumps(attempt))
        (root/'logs/phase-fixture.json').write_text(json.dumps(phase))
        file=root/'sandboxes/question/interrupted-pi-trace.json'
        file.write_text(json.dumps(proof));os.utime(file,(2050.1,2050.1))
        (root/'evaluations/fixture.json').write_text(json.dumps(m))
        return m

    def test_recovery_preserves_pause_and_charges_interrupted_question(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.fixture(root);original=copy.deepcopy(m)
            recovered,evidence=run_recovery.recover(root,m)
            self.assertEqual(m,original)
            self.assertAlmostEqual(recovered['elapsed_s'],150.1)
            self.assertAlmostEqual(recovered['question_elapsed_s']['b'],70.1)
            self.assertEqual(recovered['state'],'stopped')
            self.assertFalse(recovered['hour_timing_unknown'])
            self.assertIsNone(run_recovery.recover(root,recovered))
            self.assertAlmostEqual(hour_score.score(recovered,[],now=9000)['remaining_s'],3449.9)

    def test_incomplete_or_stale_evidence_does_not_guess(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.fixture(root)
            p=root/'logs/phase-fixture.json';phase=json.loads(p.read_text())
            for change in ({'phase':'waiting'},{'at':1900},{'tool_calls':99}):
                p.write_text(json.dumps({**phase,**change}))
                self.assertIsNone(run_recovery.recover(root,m))
            p.write_text(json.dumps(phase))
            proof=root/'sandboxes/question/interrupted-pi-trace.json'
            os.utime(proof,(9000,9000))
            self.assertIsNone(run_recovery.recover(root,m))

    def test_startup_saves_backup_before_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.fixture(root);jobs=deque()
            with patch.object(web,'ROOT',root),patch.object(web,'done',jobs):
                web.restore_job_history()
            saved=json.loads((root/'evaluations/fixture.json').read_text())
            self.assertEqual(saved['state'],'stopped')
            self.assertEqual(jobs[0]['state'],'stopped')
            self.assertEqual(json.loads(next((root/'backups').glob('*/evaluation-before.json')).read_text()),m)
            self.assertTrue(next((root/'backups').glob('*/interrupted-pi-trace.json')).exists())


if __name__=='__main__':
    unittest.main()
