import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

import model_scale


class ModelScaleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'evaluations').mkdir();self.rows=[]

    def add(self,jid,points,version='2.5.0',**extra):
        m={'id':jid,'model':jid,'created':100,'started':100,'ended':3700,'state':'stopped','scope':version,'benchmark_version':version,
           'active_intervals':[{'start':100,'end':3700}],
           'expected':[{'task':str(i),'repeat':1,'weight':1,'weight_version':'weighted-hour-v1','task_sha':'sha'} for i in range(120)]}
        m.update(extra);(self.root/'evaluations'/(jid+'.json')).write_text(json.dumps(m))
        for i in range(points):self.rows.append({'evaluation_id':jid,'task':str(i),'run':1,'status':'completed','solved':True,'ts':dt.datetime.fromtimestamp(110+i,dt.timezone.utc).isoformat()})
        return m

    def assign(self,jid,target):return model_scale.set_reference(self.root,self.rows,{'evaluation_id':jid,'target':target})

    def test_completed_hours_with_unfinished_banks_work_across_point_releases(self):
        self.add('a',1,'2.2.0');self.add('b',3);self.add('c',2)
        before={p.name:p.read_bytes() for p in (self.root/'evaluations').glob('*')};rows=copy.deepcopy(self.rows)
        self.assign('a',1);self.assign('b',5)
        report=model_scale.report(self.root,self.rows);evs={e['id']:e for e in report['evaluations']}
        self.assertEqual(len(evs),3);self.assertTrue(all(e['available'] for e in evs.values()))
        self.assertEqual(evs['a']['custom_score'],1);self.assertEqual(evs['b']['custom_score'],5);self.assertEqual(evs['c']['custom_score'],3)
        self.assertEqual(rows,self.rows)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'evaluations').glob('*')})

    def test_edit_remove_backup_and_one_reference_per_saved_model(self):
        self.add('a',1);self.add('b',2);self.assign('a',1);self.assign('b',5);self.assign('a',2)
        self.assertEqual(len(model_scale.document(self.root)['references']),2)
        self.assertEqual(len(list((self.root/'backups').glob('model-scale-*.json'))),2)
        model_scale.remove_reference(self.root,{'evaluation_id':'a'})
        self.assertEqual(model_scale.report(self.root,self.rows)['fit']['status'],'needs_references')
        self.add('b2',3,model='b');self.assign('b2',7)
        refs=model_scale.document(self.root)['references'];self.assertEqual(len(refs),1);self.assertEqual(refs[0]['evaluation_id'],'b2')

    def test_partial_reference_is_frozen_and_score_changes_are_disclosed(self):
        m=self.add('a',1,ended=120,active_intervals=[{'start':100,'end':120}])
        self.assign('a',7)
        self.rows.append({'evaluation_id':'a','task':'2','run':1,'status':'completed','solved':True,'ts':dt.datetime.fromtimestamp(115,dt.timezone.utc).isoformat()})
        e=model_scale.report(self.root,self.rows)['evaluations'][0]
        self.assertEqual(e['points'],2);self.assertEqual(e['reference']['points'],1);self.assertIn('changed',e['score_note'])
        with self.assertRaisesRegex(ValueError,'score changed'):
            model_scale.set_reference(self.root,self.rows,{'evaluation_id':'a','target':8,'expected_points':1})

    def test_same_scores_keep_targets_but_cannot_estimate_others(self):
        self.add('a',1);self.add('b',1);self.assign('a',2);self.assign('b',5)
        report=model_scale.report(self.root,self.rows)
        self.assertNotEqual(report['fit']['status'],'ready');self.assertIn('same Hourglass score',report['fit']['message'])
        self.assertEqual(sorted(e['custom_score'] for e in report['evaluations']),[2,5])

    def test_unavailable_clock_refused_and_extrapolation_labelled(self):
        self.add('a',1);self.add('b',2);self.add('c',4);self.add('bad',1,hour_timing_unknown=True)
        self.assign('a',1);self.assign('b',3)
        report=model_scale.report(self.root,self.rows);evs={e['id']:e for e in report['evaluations']}
        self.assertEqual(evs['c']['custom_score'],7);self.assertIn('Extrapolated',evs['c']['score_note'])
        self.assertFalse(evs['bad']['available'])
        with self.assertRaises(ValueError):self.assign('bad',9)
        for target in (None,True,'5',float('nan'),float('inf')):
            with self.assertRaises(ValueError):self.assign('a',target)
        self.assign('a',-2);self.assertEqual(model_scale.document(self.root)['references'][-1]['target'],-2)


if __name__=='__main__':unittest.main()
