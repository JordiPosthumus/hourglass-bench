import datetime as dt
import json
import subprocess
import unittest

import hour_score


def row(task, at, solved=True, status='completed', **extra):
    return {'evaluation_id':'fixture','task':task,'status':status,'solved':solved,
            'ts':dt.datetime.fromtimestamp(at,dt.timezone.utc).isoformat(),**extra}


class HourScoreTests(unittest.TestCase):
    def calculate(self, job, rows, now=4700):
        job={'id':'fixture','started':1000,'tasks':['a','b','c'],'state':'running',**job}
        expected=[{'task':'a','vision':False},{'task':'b','vision':True},{'task':'c','vision':False}]
        result=hour_score.score(job,rows,expected,now)
        script="const {hourScore}=require('./ui/hour-score');let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{const a=JSON.parse(s);console.log(JSON.stringify(hourScore(...a)))})"
        js=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps([job,rows,expected,now]),text=True))
        self.assertEqual(result,js)
        return result

    def test_exact_deadline_late_answers_and_retries(self):
        r=self.calculate({},[row('a',1100,status='error',solved=False),row('a',2000),
                             row('a',4601,solved=False),row('b',4600),row('c',4600.001)])
        self.assertEqual(r['points'],2)
        self.assertEqual(r['breakdown']['text']['points'],1)
        self.assertEqual(r['breakdown']['vision']['points'],1)
        self.assertEqual(r['after_deadline_questions'],2)
        self.assertEqual(r['errors'],1)
        self.assertEqual(r['state'],'final')

    def test_reset_withholds_original_hour(self):
        r=self.calculate({'results_reset':'reset-id'},[row('a',1200)])
        self.assertEqual(r['state'],'unavailable')
        self.assertIsNone(r['weighted_points'])

    def test_repeats_cannot_inflate_question_count(self):
        r=self.calculate({},[row('a',1200),row('a',1300),row('b',1400,False)],1500)
        self.assertEqual(r['points'],1)
        self.assertEqual(r['incorrect_questions'],1)
        self.assertEqual(r['state'],'in_progress')

    def test_pause_excluded_but_active_overhead_counts(self):
        job={'resume_count':1,'active_intervals':[{'start':1000,'end':2000},{'start':10000,'end':None}]}
        r=self.calculate(job,[row('a',2000),row('b',12600),row('c',12601)],12700)
        self.assertEqual(r['points'],2)
        self.assertEqual(r['elapsed_s'],3700)

    def test_historical_pause_unknown_is_not_fabricated(self):
        r=self.calculate({'resume_count':1},[row('a',2000)])
        self.assertIsNone(r['points'])
        self.assertEqual(r['state'],'unavailable')

    def test_partial_and_full_completion(self):
        r=self.calculate({'state':'stopped','ended':1500},[row('a',1400)])
        self.assertEqual(r['state'],'partial')
        r=self.calculate({'state':'completed','ended':1500},[row('a',1200),row('b',1300),row('c',1400)])
        self.assertEqual(r['state'],'final')

    def test_unknown_timestamp_and_policy_skips(self):
        r=self.calculate({},[row('a',1200),{'evaluation_id':'fixture','task':'b','status':'completed','solved':True}])
        self.assertIsNone(r['points'])
        r=self.calculate({},[row('a',1200),row('b',1300,False,score_reason='wrong_streak_limit')],1400)
        self.assertEqual(r['completed_questions'],1)

    def test_not_started(self):
        r=self.calculate({'started':None,'state':'pending'},[])
        self.assertEqual(r['state'],'not_started')
        self.assertEqual(r['remaining_s'],3600)


class TotalScoreTests(unittest.TestCase):
    calculate = HourScoreTests.calculate
    def test_same_work_has_same_total_regardless_of_completion_time(self):
        for ended in (1000,1900,2800):
            h=self.calculate({'state':'completed','ended':ended},[row(t,ended) for t in 'abc'])
            self.assertEqual(h['hourglass_score'],3)
            self.assertNotIn('auc_point_seconds',h)
    def test_new_round_attempts_accumulate_and_do_not_erase_mistakes(self):
        h=self.calculate({'scoring_policy':'net-hour-v3','round_policy':'whole-bank-slowest-wrong-first-v1'},
                         [row('a',1100,False,run=1),row('a',1200,True,run=2),row('a',1300,True,run=3)],1400)
        self.assertEqual(h['hourglass_score'],1)
        self.assertEqual(h['points'],2);self.assertEqual(h['penalty_points'],1)
        self.assertEqual(h['state'],'in_progress')
