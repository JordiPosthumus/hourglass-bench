import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import score_report
import score_weights
import score_publisher
import hour_score

class WeightedReportTests(unittest.TestCase):
    def test_fixed_scales_and_javascript_parity(self):
        tasks=[{'section':'charts','tier':i} for i in range(1,11)]+[{'section':'games','tier':i} for i in range(1,6)]+[{'section':'math_logic','level':i} for i in ['advanced_high_school','advanced_undergraduate','graduate']]
        expected=[score_weights.weight(t) for t in tasks]
        script="const {questionWeight}=require('./ui/hour-score');console.log(JSON.stringify(JSON.parse(process.argv[1]).map(questionWeight)))"
        self.assertEqual(expected,json.loads(subprocess.check_output(['node','-e',script,json.dumps(tasks)],text=True)))
        self.assertEqual(expected[:1]+expected[9:11]+expected[14:], [1,2,1,2,1,1.5,2])

    def test_report_allowlist_duplicate_deadline_and_credit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task={'section':'games','tier':5,'prompt':'SECRET QUESTION','answer':'SECRET ANSWER'}
            p=root/'tasks'/'SECRET-ID'/'task.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(task))
            expected=[{'task':'SECRET-ID','task_sha':hashlib.sha256(p.read_bytes()).hexdigest()[:16],'vision':False,'repeat':2}]
            job={'id':'fixture','model':'demo','started':1000,'ended':4600,'tasks':['SECRET-ID'],'state':'stopped','active_intervals':[{'start':1000,'end':4600}]}
            rows=[{'evaluation_id':'fixture','task':'SECRET-ID','status':'completed','solved':True,'ts':dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat(),'reasoning':'SECRET TRACE'} for t in (1100,1200,4700)]
            manifest={'expected':expected,'order':['SECRET-ID'],'benchmark_version':'fixture'}
            (root/'timing-corrections.json').write_text(json.dumps([{'evaluation_id':'fixture','credit_s':12}]))
            files=score_report.build(root,job,rows,manifest);report=json.loads(files['report.json'])
            self.assertEqual(report['weighted_points'],2);self.assertEqual(report['raw_correct'],1)
            self.assertEqual(report['clock_adjustment_seconds'],12)
            self.assertTrue(all('SECRET' not in v for v in files.values()))
            self.assertIn('*Clock adjusted',files['README.md'])
            self.assertEqual(report['curve'][-1]['seconds'],3600)
            p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'frozen difficulty'):score_report.build(root,job,rows,manifest)

    def test_publication_has_only_three_files_and_nonforce_commit(self):
        replies=[{'default_branch':'main'},{'object':{'sha':'head'}},{'tree':{'sha':'tree'}},{'sha':'b1'},{'sha':'b2'},{'sha':'b3'},{'sha':'updated'},{'sha':'commit'}]
        with patch.object(score_publisher,'gh',side_effect=replies) as api,patch.object(score_publisher.subprocess,'run') as run:
            run.return_value.returncode=0
            url=score_publisher.publish('owner/repo','token',{'report.json':'{}','score.svg':'svg','README.md':'readme'})
            self.assertIn('/commit/reports/token',url)
            entries=api.call_args_list[-2].args[1]['tree']
            self.assertEqual([e['path'] for e in entries],['reports/token/report.json','reports/token/score.svg','reports/token/README.md'])
            self.assertFalse(json.loads(run.call_args.kwargs['input'])['force'])
