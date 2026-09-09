import json,unittest,tempfile,datetime as dt,subprocess
from pathlib import Path
import hour_score,scoring_policy,report_charts,run_editor,run_tracking
from test_hour_score import HourScoreTests,row

class NegativeMarking(HourScoreTests):
 def test_signed_score_and_neutral_outcomes(self):
  h=self.calculate({'scoring_policy':scoring_policy.NET},[row('a',1100,False),row('a',1200,False),row('b',1300,False,score_reason='unsupported_vision'),row('c',1400,False,score_reason='abstained')])
  self.assertEqual((h['weighted_points'],h['gross_points'],h['penalty_points'],h['abstained_questions'],h['unsupported_questions']),(-1,0,1,1,1))
  self.assertEqual(h['breakdown']['text']['weighted_points'],-1)
 def test_correct_repeat_supersedes_penalty(self):
  h=self.calculate({'scoring_policy':scoring_policy.NET},[row('a',1100,False),row('a',1200,True),row('a',1300,False)])
  self.assertEqual((h['weighted_points'],h['incorrect_questions']),(1,0))
 def test_deadline_errors_and_no_submission(self):
  h=self.calculate({'scoring_policy':scoring_policy.NET},[row('a',4600,False),row('b',4601,False),row('c',1500,False,status='error'),row('c',1600,False,termination='stopped')])
  self.assertEqual(h['weighted_points'],-1)
 def test_old_runs_keep_gross(self):
  h=self.calculate({},[row('a',1100,False),row('b',1200,True)])
  self.assertEqual(h['weighted_points'],1);self.assertIsNone(h['net_points']);self.assertEqual(h['penalty_points'],0)
 def test_signed_auc_and_chart_bounds(self):
  curve=[{'seconds':0,'weighted':0},{'seconds':600,'weighted':2},{'seconds':1200,'weighted':-1},{'seconds':3600,'weighted':-1}]
  self.assertEqual(report_charts.auc(curve,True)['point_minutes'],-20)
  svg=report_charts.progress_chart([{'weighted_points':-1,'curve':curve,'model':'fixture','state':'final'}])
  self.assertIn('Zero points',svg)
  import re
  coords=re.search(r'<polyline points="([^"]+)',svg).group(1).split()
  self.assertTrue(all(132<=float(p.split(',')[1])<=446 for p in coords))
 def test_schema_distinguishes_answer_and_abstention(self):
  schema,text=scoring_policy.submission({'value':{'type':'number'}},2,scoring_policy.WITH_ABSTENTION)
  self.assertIn('loses 1 point',text);self.assertIn('2 points',text)
  script="import {Check} from './vendor/pi-0.85.1/node_modules/typebox/build/value/index.mjs';const a=JSON.parse(process.argv[1]);console.log(JSON.stringify([{}, {value:2}, {abstain:true}, {abstain:false}, {value:2,abstain:true}].map(x=>Check(a,x))))"
  result=subprocess.run(['node','--input-type=module','-e',script,json.dumps(schema)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),[False,True,True,False,False])


class RunEditor(unittest.TestCase):
 def test_version_history_choices_and_conflict(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);manifest={'id':'fixture','model':'original','started':1000,'state':'stopped'}
   original=dict(manifest)
   a=run_editor.save(root,manifest,{'values':{'model_name':'Small model','quantization':'Q2','temperature':0},'applies_from':'run_start'})
   b=run_editor.save(root,manifest,{'values':{'model_name':'Small model','quantization':'Q4'},'applies_from':'run_start','base_revision':a['id']})
   self.assertEqual(manifest,original);self.assertEqual(len(run_editor.history(root,'fixture')),2)
   self.assertEqual(run_editor.snapshot(root,'fixture'),b)
   self.assertEqual(len(run_editor.catalog(root)['choices']),4)
   with self.assertRaises(ValueError):run_editor.save(root,manifest,{'values':{},'applies_from':'run_start','base_revision':a['id']})
   self.assertEqual(len(run_editor.history(root,'fixture')),2)
 def test_validation_and_timing(self):
  for v in ({'temperature':float('nan')},{'top_p':1.5},{'context_limit':-1},{'seed':1.5},{'model_name':4},{'unknown':'x'}):
   with self.subTest(v=v),self.assertRaises(ValueError):run_editor.clean(v)
  with tempfile.TemporaryDirectory() as root:
   with self.assertRaises(ValueError):run_editor.save(root,{'id':'fixture','state':'stopped'},{'values':{},'applies_from':'now'})
