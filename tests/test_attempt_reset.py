import json
import tempfile
import unittest
from pathlib import Path
import attempt_reset
import hour_score
import result_store

class ResetTests(unittest.TestCase):
    def test_active_or_queued_work_blocks_reset(self):
        from unittest.mock import patch
        import web
        for active,queued in (([{'id':'active'}],[]),([],[{'id':'queued'}])):
            with patch.object(web,'running',active),patch.object(web,'queue',queued),patch.object(attempt_reset,'reset') as mutation:
                with self.assertRaisesRegex(ValueError,'active and queued'):web.reset_attempts({})
                mutation.assert_not_called()

    def test_reset_flag_survives_api_and_blocks_report(self):
        from unittest.mock import patch
        import web,score_report
        self.assertEqual(web.public_job({'id':'job','model':'fixture','results_reset':'reset'})['results_reset'],'reset')
        with patch.object(score_report.score_weights,'enrich',return_value=[]):
            with self.assertRaisesRegex(ValueError,'results were reset'):
                score_report.build(Path('.'),{'id':'job'},[],{'expected':[],'results_reset':'reset'})

    def test_reset_preserves_bytes_and_prevents_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'results').mkdir();(root/'evaluations').mkdir()
            m={'id':'job','model':'model','config_hash':'hash','expected':[{'task':'A','task_sha':'sha','repeat':1}]}
            (root/'evaluations/job.json').write_text(json.dumps(m))
            a={'run_id':'a','evaluation_id':'job','model':'model','task':'A','model_config_hash':'hash','task_sha':'sha','run':1,'status':'completed','ts':'2026-09-09T12:00:00+00:00','artifact_dir':'results/A/model/run-a'}
            art=root/a['artifact_dir'];art.mkdir(parents=True);(art/'metrics.json').write_text(json.dumps(a));(art/'trace.json').write_bytes(b'original trace')
            untouched=b'{"run_id": "b", "task":"B"}  \ninvalid historical line\n'
            original=json.dumps(a).encode()+b'\n'+untouched;(root/'results/results.jsonl').write_bytes(original)
            state=attempt_reset.snapshot(root)
            out=attempt_reset.reset(root,{'revision':state['revision'],'attempts':['a'],'reason':'diagnostic exposure'})
            self.assertEqual((root/'results/results.jsonl').read_bytes(),untouched)
            self.assertEqual((root/out['backup']/'results-before.jsonl').read_bytes(),original)
            self.assertEqual((art/'trace.json').read_bytes(),b'original trace')
            self.assertEqual(result_store.reconcile(root,m),0)
            self.assertEqual(out['plans'],[{'job':'job','model':'model','tasks':['A']}])
            job=json.loads((root/'evaluations/job.json').read_text())
            self.assertEqual(hour_score.score(job,[])['state'],'unavailable')
            with self.assertRaisesRegex(ValueError,'Results changed'):
                attempt_reset.reset(root,{'revision':state['revision'],'attempts':['b'],'reason':'again'})

if __name__=='__main__':unittest.main()
