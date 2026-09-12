import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import results_history as h
import score_publisher as p

class HistoryTests(unittest.TestCase):
 def report(self,key='a',**kw):
  return dict(model='demo',run_key=key,run_date='2026-01-01T00:00:00Z',experiment={'model_family':'Demo','configuration':key},hardware={'label':'Test hardware'},machine_key='machine',bank_fingerprint='bank',scoring='weighted-hour-v1',timing_policy='hour-v1',benchmark_version='v1',execution={'repeat':1},state='final',score_version='total-points-v1',hourglass_score=8.11,total_available_points=10,weighted_points=4,raw_correct=3,active_seconds=3600,efficiency={'token_data_complete':True,'accuracy':.75,'scored_answers':4,'median_output_tokens':1000,'answers_per_active_minute':.5},curve=[{'seconds':0,'weighted':0},{'seconds':3600,'weighted':4}],**kw)
 def test_labels_are_explicit_and_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'evaluations').mkdir()
   self.assertEqual(h.load(root,'a'),{})
   h.save(root,'a',{'model_family':' Demo ','configuration':' Q4 '})
   self.assertEqual(h.load(root,'a'),{'model_family':'Demo','configuration':'Q4'})
   with self.assertRaises(ValueError):h.save(root,'a',{'api_key':'secret'})
 def test_catalog_keeps_runs_and_republication_is_idempotent(self):
  first=h.catalog_files([],self.report(),'first')
  catalog=json.loads(first['reports/catalog.json'])
  second=h.catalog_files(catalog,self.report('b'),'second')
  catalog=json.loads(second['reports/catalog.json']);self.assertEqual(len(catalog),2)
  again=h.catalog_files(catalog,self.report(),'replacement')
  self.assertEqual(len(json.loads(again['reports/catalog.json'])),2)
  self.assertIn('private questions',again['reports/README.md'])
  self.assertTrue(any(k.endswith('-quadrants.svg') for k in again))
  self.assertTrue(any(k.endswith('-comparison.svg') for k in again))
 def test_history_separates_protocol_hardware_and_partial_runs(self):
  a=self.report();b={**self.report('b'),'machine_key':'other'};c={**self.report('c'),'state':'partial'};d={**self.report('d'),'question_timeout_policy':'900'}
  svg=h.evolution([a,b,c,d]);self.assertEqual(svg.count('protocol '),4)
  self.assertEqual(svg.count('<polyline'),3)
 def test_public_allowlist_omits_raw_runtime_data(self):
  r=self.report();r.update(prompt='SECRET',trace='SECRET',base_url='SECRET',api_key='SECRET')
  files=h.catalog_files([],r,'snapshot');self.assertNotIn('SECRET',''.join(files.values()))
 def test_publisher_updates_snapshot_and_history_atomically(self):
  calls=[]
  def gh(path,payload=None):
   calls.append((path,payload))
   if path=='repos/owner/repo':return {'default_branch':'main'}
   if '/git/ref/' in path:return {'object':{'sha':'head'}}
   if path.endswith('/git/commits/head'):return {'tree':{'sha':'base'}}
   return {'sha':'new'}
  with patch.object(p,'gh',side_effect=gh),patch.object(p,'published_catalog',return_value=[]),patch.object(p.subprocess,'run') as run:
   run.return_value.returncode=0
   p.publish('owner/repo','snapshot',{'report.json':json.dumps(self.report()),'README.md':'reviewed'})
   tree=next(payload for path,payload in calls if path.endswith('/git/trees'))
   paths=[e['path'] for e in tree['tree']]
   self.assertIn('reports/snapshot/report.json',paths);self.assertIn('reports/catalog.json',paths);self.assertIn('reports/README.md',paths)
   self.assertEqual(tree['base_tree'],'base');self.assertFalse(json.loads(run.call_args.kwargs['input'])['force'])
 def test_catalog_permission_failure_is_not_treated_as_empty(self):
  with patch.object(p.subprocess,'run') as run:
   run.return_value.returncode=1;run.return_value.stderr='Forbidden (HTTP 403)'
   with self.assertRaisesRegex(ValueError,'No history'):p.published_catalog('owner/repo','head')
   run.return_value.stderr='Not Found (HTTP 404)';self.assertEqual(p.published_catalog('owner/repo','head'),[])

class StepChartTests(unittest.TestCase):
 def test_completion_markers_do_not_change_raw_curve(self):
  import report_charts as c
  curve=[{'seconds':0,'weighted':0},{'seconds':900,'weighted':0},{'seconds':900,'weighted':2},{'seconds':1800,'weighted':2}]
  before=json.dumps(curve)
  self.assertEqual(c.measured_points(curve),[curve[0],curve[2],curve[3]])
  self.assertEqual(json.dumps(curve),before)

 def test_step_renderer_has_no_diagonal_score_segments(self):
  import report_charts as c
  curve=[{'seconds':0,'weighted':0},{'seconds':900,'weighted':2},{'seconds':1800,'weighted':3},{'seconds':3600,'weighted':3}]
  before=json.dumps(curve);points=c.step_points(curve)
  self.assertEqual(points,[{'seconds':0,'weighted':0},{'seconds':900,'weighted':0},{'seconds':900,'weighted':2},{'seconds':1800,'weighted':2},{'seconds':1800,'weighted':3},{'seconds':3600,'weighted':3}])
  self.assertTrue(all(a['seconds']==b['seconds'] or a['weighted']==b['weighted'] for a,b in zip(points,points[1:])))
  self.assertEqual(json.dumps(curve),before)

if __name__=='__main__':unittest.main()

class LegacyScoreTests(unittest.TestCase):
 def test_legacy_points_are_not_relabelled_as_total_scores(self):
  r=HistoryTests().report();r.pop('hourglass_score');r.pop('score_version')
  files=h.catalog_files([],r,'legacy')
  self.assertIn('Not calculated',files['reports/README.md'])
  self.assertNotIn('protocol ',h.evolution([r]))
