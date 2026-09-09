import copy,datetime as dt,json,subprocess,tempfile,unittest
from pathlib import Path
from collections import deque
from unittest.mock import patch
import calibration,hour_score,web,run_editor,results_history,report_charts,score_report,scoring_policy

class AuditFixes(unittest.TestCase):
 def test_snapshot_is_independent_and_integrity_checked(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);config={'name':'fixture','model':'fixture','base_url':'http://fixture.invalid/v1','max_tokens':262144,'extra':{'top_p':.91,'secret_fixture':'PRIVATE'}}
   manifest={'id':'fixture','config_hash':calibration.digest(config),'model_config_snapshot':copy.deepcopy(config)}
   config['max_tokens']=12;config['extra']['top_p']=.1
   path=calibration.frozen_config_path(root,manifest,config)
   saved=json.loads(path.read_text())['models'][0]
   self.assertEqual(saved['max_tokens'],262144);self.assertEqual(saved['extra']['top_p'],.91)
   path.write_text('{}')
   with self.assertRaisesRegex(ValueError,'changed'):calibration.frozen_config_path(root,manifest,config)
 def test_recovery_withholds_unknown_time_and_preserves_backup(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'evaluations').mkdir()
   original={'id':'fixture','model':'fixture','state':'running','started':1000,'elapsed_s':10,'active_started':1000,'active_intervals':[{'start':1000,'end':None}],'expected':[{'task':'a','repeat':1}]}
   path=root/'evaluations/fixture.json';path.write_text(json.dumps(original))
   jobs=deque()
   with patch.object(web,'ROOT',root),patch.object(web,'done',jobs):web.restore_job_history()
   restored=jobs[0];h=hour_score.score(restored,[],now=5000)
   self.assertEqual(restored['state'],'error');self.assertTrue(restored['hour_timing_unknown']);self.assertEqual(h['state'],'unavailable')
   self.assertEqual(json.loads(next((root/'backups').glob('*/evaluation-before.json')).read_text()),original)
   self.assertEqual(json.loads(path.read_text())['state'],'error')
 def test_repeat_completion_and_null_policy_python_js_parity(self):
  expected=[{'task':'a','repeat':3}];job={'id':'fixture','tasks':['a'],'started':1000,'state':'running','scoring_policy':None}
  rows=[]
  script="const {hourScore}=require('./ui/hour-score');const a=JSON.parse(process.argv[1]);console.log(JSON.stringify(hourScore(...a)))"
  for n in range(1,4):
   rows.append({'evaluation_id':'fixture','task':'a','run':n,'status':'completed','solved':n==1,'ts':dt.datetime.fromtimestamp(1000+n,dt.timezone.utc).isoformat()})
   h=hour_score.score(job,rows,expected,1010)
   self.assertEqual(h,json.loads(subprocess.check_output(['node','-e',script,json.dumps([job,rows,expected,1010])],text=True)))
   self.assertEqual(h['state'],'final' if n==3 else 'in_progress')
   self.assertEqual(h['scoring_policy'],'weighted-hour-v1')
 def test_log_axis_parity_and_decade_spacing(self):
  script="const {tokenAxis}=require('./ui/token-axis');console.log(JSON.stringify(tokenAxis(JSON.parse(process.argv[1]))))"
  for values in ([2455],[1,10,100,1000],[0,0],[],[.5,2],[10,10000000]):
   axis=report_charts.token_axis(values)
   js=json.loads(subprocess.check_output(['node','-e',script,json.dumps(values)],text=True))
   self.assertAlmostEqual(axis['guide']/js['guide'],1,places=14)
   self.assertEqual({k:v for k,v in axis.items() if k!='guide'},{k:v for k,v in js.items() if k!='guide'})
   self.assertGreater(axis['min'],0);self.assertGreater(axis['max'],axis['min'])
  base={'model':'a','hardware':{'label':'fixture'},'machine_key':'one','bank_fingerprint':'same','scoring':'net-hour-v2','timing_policy':'hour','benchmark_version':'test','state':'final','efficiency':{'token_data_complete':True,'accuracy':.9,'median_output_tokens':1,'scored_answers':1,'answers_per_active_minute':1}}
  reports=[{**base,'model':str(t),'efficiency':{**base['efficiency'],'median_output_tokens':t}} for t in (1,10,100,1000,0)]
  import xml.etree.ElementTree as ET
  svg=score_report.quadrants(reports)['quadrants.svg'];circles=ET.fromstring(svg).findall('.//{http://www.w3.org/2000/svg}circle');xs=[float(c.attrib['cx']) for c in circles]
  self.assertEqual(len(xs),4);self.assertAlmostEqual(xs[0]-xs[1],xs[1]-xs[2]);self.assertAlmostEqual(xs[1]-xs[2],xs[2]-xs[3]);self.assertIn('1 zero-token runs omitted',svg)
 def test_editor_report_labels_and_new_run_copy(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source={'id':'source','state':'stopped','model':'fixture','started':1000};target={'id':'target','state':'pending','model':'fixture','created':2000}
   a=run_editor.save(root,source,{'values':{'model_name':'Fixture family','quantization':'Q2','temperature':0,'hardware':'Fixture hardware','notes':'PRIVATE NOTE'},'applies_from':'run_start'})
   labels=results_history.load(root,'source');self.assertEqual(labels['model_family'],'Fixture family');self.assertEqual(labels['quantization'],'Q2');self.assertNotIn('PRIVATE',str(labels))
   results_history.save(root,'source',{'quantization':'Public override'})
   self.assertEqual(results_history.load(root,'source')['quantization'],'Public override')
   run_editor.save(root,source,{'values':{**a['values'],'quantization':'Q4'},'applies_from':'run_start','base_revision':a['id']})
   self.assertEqual(results_history.load(root,'source')['quantization'],'Q4')
   run_editor.copy_setup(root,source,target)
   self.assertEqual(run_editor.snapshot(root,'target')['values'],run_editor.snapshot(root,'source')['values'])
   self.assertEqual(results_history.load(root,'target')['quantization'],'Q4')
   self.assertEqual(len(run_editor.history(root,'source')),2)
 def test_new_submission_matches_original_schema_and_has_no_score_prompt(self):
  for props in ({'value':{'type':'number'}},{'option':{'type':'string'}},{'summary':{'type':'string'}}):
   schema,text=scoring_policy.submission(props,2,scoring_policy.NET)
   old,old_text=scoring_policy.submission(props,2,scoring_policy.LEGACY)
   self.assertEqual(schema,old);self.assertEqual(text,'');self.assertEqual(old_text,'');self.assertNotIn('abstain',schema['properties'])
 def test_timeout_is_not_counted_as_an_answer_without_policy(self):
  script="const fs=require('fs'),vm=require('vm');const s=fs.readFileSync('ui/app.js','utf8');const c={};vm.createContext(c);vm.runInContext(s.slice(s.indexOf('function isFinalScore(')),c);console.log(JSON.stringify([c.isFinalScore({status:'timeout',score_reason:'question_timeout'}),c.isFinalScore({status:'completed',solved:false,scoring_policy:'net-hour-v2'}),c.isFinalScore({status:'completed',solved:false,scoring_policy:'net-hour-v2',score_reason:'unsupported_vision'})]));"
  self.assertEqual(json.loads(subprocess.check_output(['node','-e',script],text=True)),[False,True,False])
