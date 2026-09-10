import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path
import calibration as c


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, vision in [('text', False), ('image', True)]:
            p = self.root/'tasks'/name/'task.json'; p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'repeat': 1, 'assets': ['image.png'] if vision else []}))
        self.rows = []

    def evaluation(self, name, answers, repeat=1, version='1.1.0', tasks=None):
        job = {'id':name, 'model':name, 'tasks':tasks or ['text','image'], 'repeat':repeat,
               'created':100, 'started':101, 'state':'completed'}
        cfg = {'model':name,'name':name}
        m = c.evaluation_manifest(self.root,job,version,cfg)
        for task, correct in zip(m['expected'],answers):
            for i in range(repeat):
                self.rows.append({'evaluation_id':name,'run_id':f'{name}-{task["task"]}-{i}',
                                  'run':i+1,'model':name,'model_config_hash':c.digest(cfg),'task':task['task'],
                                  'task_sha':task['task_sha'],'task_bundle_sha':task['task_bundle_sha'],'benchmark_version':version,
                                  'solved':correct,'status':'completed','node':'node','duration_s':2})
        return m

    def refs(self, points):
        return [{'model':str(i),'accuracy':x,'target':y} for i,(x,y) in enumerate(points)]

    def test_two_anchor_mapping_and_multi_model_equal_weight(self):
        fit=c.fit(self.refs([(0.2,1),(0.8,5)]))
        self.assertEqual(fit['status'],'ready');self.assertAlmostEqual(fit['intercept']+fit['slope']*.5,3)
        fit=c.fit(self.refs([(0.2,1),(0.5,3),(0.8,5)]))
        self.assertAlmostEqual(fit['rmse'],0);self.assertAlmostEqual(fit['leave_one_out_mae'],0)

    def test_blocks_unstable_contradictory_and_flat_scales(self):
        for points in [[(.2,1),(.21,5)],[(.2,5),(.8,1)],[(.2,1),(.2,2),(.8,5)],[(.2,1),(.8,1)]]:
            self.assertEqual(c.fit(self.refs(points))['status'],'blocked')
        self.assertEqual(c.fit(self.refs([(.2,1)]))['status'],'needs_references')

    def test_reports_residuals_instead_of_forcing_three_targets(self):
        fit=c.fit(self.refs([(0.2,1),(0.5,1.1),(0.8,5)]))
        self.assertGreater(fit['rmse'],0);self.assertTrue(fit['warnings']);self.assertGreater(fit['leave_one_out_mae'],0)

    def test_complete_counts_time_and_vision_zero(self):
        self.evaluation('a',[False,True])
        self.rows[0]['score_reason']='unsupported_vision'
        e=c.evaluations(self.root,self.rows)[0]
        self.assertTrue(e['eligible']);self.assertEqual(e['accuracy'],.5);self.assertEqual(e['duration_s'],4)
        self.assertEqual(e['breakdown']['vision']['accuracy'],0);self.assertEqual(e['breakdown']['text']['accuracy'],1)

    def test_incomplete_duplicate_error_version_and_configuration_rejected(self):
        self.evaluation('a',[True,True]);valid=list(self.rows)
        self.assertFalse(c.evaluations(self.root,valid[:1])[0]['eligible'])
        self.assertFalse(c.evaluations(self.root,valid+[valid[0]])[0]['eligible'])
        for key,value in [('status','error'),('benchmark_version','other'),('task_sha','changed'),('model_config_hash','changed'),('model','other')]:
            altered=[dict(r) for r in valid];altered[0][key]=value
            self.assertFalse(c.evaluations(self.root,altered)[0]['eligible'],key)

    def test_reference_replacement_backup_and_prediction(self):
        a=self.evaluation('a',[False,False]);self.evaluation('b',[True,True]);self.evaluation('c',[False,True])
        c.set_reference(self.root,self.rows,{'evaluation_id':'a','target':1})
        c.set_reference(self.root,self.rows,{'evaluation_id':'b','target':5})
        report=c.report(self.root,self.rows);e=next(e for e in report['evaluations'] if e['id']=='c')
        self.assertEqual(e['calibrated_score'],3)
        c.set_reference(self.root,self.rows,{'evaluation_id':'a','target':0})
        self.assertEqual(len(c.report(self.root,self.rows)['scopes'][a['scope']]['references']),2)
        self.assertEqual(len(list((self.root/'backups').glob('calibration-*'))),2)
        c.remove_reference(self.root,{'scope':a['scope'],'evaluation_id':'a'})
        self.assertEqual(c.report(self.root,self.rows)['scopes'][a['scope']]['fit']['status'],'needs_references')

    def test_separate_versions_questions_repeats_and_no_extrapolation(self):
        a=self.evaluation('a',[False,True]);b=self.evaluation('b',[True,True]);self.evaluation('c',[False,False])
        d=self.evaluation('d',[True,True],version='next');f=self.evaluation('f',[True],tasks=['text']);g=self.evaluation('g',[True,True],repeat=2)
        self.assertEqual(a['scope'],b['scope']);self.assertEqual(len({a['scope'],d['scope'],f['scope'],g['scope']}),4)
        c.set_reference(self.root,self.rows,{'evaluation_id':'a','target':1});c.set_reference(self.root,self.rows,{'evaluation_id':'b','target':5})
        report=c.report(self.root,self.rows)
        for name in ('c','d','f','g'):
            e=next(e for e in report['evaluations'] if e['id']==name);self.assertIsNone(e['calibrated_score'])

    def test_target_validation_and_incomplete_reference(self):
        self.evaluation('a',[True,True])
        for target in [None,True,'5',-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):c.set_reference(self.root,self.rows,{'evaluation_id':'a','target':target})
        with self.assertRaises(ValueError):c.set_reference(self.root,self.rows[:1],{'evaluation_id':'a','target':1})

    def test_saved_reference_is_frozen(self):
        a=self.evaluation('a',[False,False]);c.set_reference(self.root,self.rows,{'evaluation_id':'a','target':1})
        self.rows[0]['solved']=True
        report=c.report(self.root,self.rows)
        self.assertEqual(report['scopes'][a['scope']]['references'][0]['accuracy'],0)

    def test_legacy_active_evaluation_timestamp_matching(self):
        job={'id':'old','model':'old','tasks':['text'],'repeat':1,'created':100,'started':101,'state':'running'}
        m=c.evaluation_manifest(self.root,job,'1.1.0',{'model':'old'},legacy=True)
        row={'run_id':'old-result','model':'old','task':'text','task_sha':m['expected'][0]['task_sha'],
             'benchmark_version':'1.1.0','status':'completed','solved':True,
             'ts':dt.datetime.fromtimestamp(102,dt.timezone.utc).isoformat()}
        self.assertTrue(c.evaluations(self.root,[row])[0]['eligible'])
        row['ts']=dt.datetime.fromtimestamp(99,dt.timezone.utc).isoformat()
        self.assertFalse(c.evaluations(self.root,[row])[0]['eligible'])

if __name__=='__main__':unittest.main()
