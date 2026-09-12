import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import question_rounds as rounds
import scoring_policy
import hour_score
import run_archive


def attempt(task, number, seconds, solved=False, status='completed'):
    return {'task':task,'run':number,'duration_s':seconds,'solved':solved,'status':status}


class RoundTests(unittest.TestCase):
    def test_wrong_slowest_then_unfinished_then_correct_slowest_stable_ties(self):
        order=list('abcdefg')
        rows=[attempt('a',1,20),attempt('b',1,100,True),attempt('c',1,50),
              attempt('d',1,900,status='timeout'),attempt('e',1,40,True),
              attempt('f',1,50),attempt('g',1,500,status='not_attempted')]
        before=copy.deepcopy(rows)
        self.assertEqual(rounds.next_order(order,rows,1),list('cfadgbe'))
        self.assertEqual(rows,before)

    def test_first_pass_then_whole_bank_then_latest_round_and_resume(self):
        job={'round_policy':rounds.POLICY,'tasks':list('abc')};saved=[];rows=[]
        plan=rounds.attempts(job,{'order':list('abc')},lambda:rows,lambda:saved.append(copy.deepcopy(job)))
        for task,seconds,solved in [('a',10,True),('b',80,False),('c',90,False)]:
            self.assertEqual(next(plan),(task,1));rows.append(attempt(task,1,seconds,solved))
        self.assertEqual(next(plan),('c',2));rows.append(attempt('c',2,5,True))
        plan.close()
        resumed=rounds.attempts(copy.deepcopy(saved[-1]),{'order':list('abc')},lambda:rows,lambda:None)
        self.assertEqual(next(resumed),('b',2));rows.append(attempt('b',2,60,True))
        self.assertEqual(next(resumed),('a',2));rows.append(attempt('a',2,1,False))
        self.assertEqual(next(resumed),('a',3));resumed.close()

    def test_every_attempt_counts_without_erasing_penalties_or_ending_at_bank(self):
        job={'id':'x','tasks':['a'],'started':1000,'state':'running','round_policy':rounds.POLICY,'scoring_policy':scoring_policy.NET}
        rows=[]
        for number,solved in enumerate([False,True,True,False],1):
            rows.append({**attempt('a',number,10,solved),'evaluation_id':'x','ts':dt.datetime.fromtimestamp(1000+number*10,dt.timezone.utc).isoformat()})
        h=hour_score.score(job,rows,[{'task':'a','weight':2}],now=1100)
        self.assertEqual(h['hourglass_score'],2) # -1 +2 +2 -1
        self.assertEqual(h['points'],2);self.assertEqual(h['penalty_points'],2)
        self.assertEqual(h['state'],'in_progress');self.assertNotIn('auc_point_seconds',h)
        late={**rows[-1],'run':5,'solved':True,'ts':dt.datetime.fromtimestamp(4601,dt.timezone.utc).isoformat()}
        self.assertEqual(hour_score.score(job,rows+[late],[{'task':'a','weight':2}],now=4601)['hourglass_score'],2)

    def test_timeout_is_per_round_not_per_question_forever(self):
        rows=[attempt('a',1,900,status='timeout')]
        self.assertTrue(rounds.resolved(rows,'a',1));self.assertFalse(rounds.resolved(rows,'a',2))


class ArchiveTests(unittest.TestCase):
    def test_archive_restore_preserves_all_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'evaluations').mkdir();(root/'results').mkdir()
            files={'evaluations/a.json':b'{"id":"a","expected":[]}', 'results/results.jsonl':b'{"evaluation_id":"a"}\n','models.json':b'{"models":[]}'}
            for name,data in files.items():(root/name).write_bytes(data)
            run_archive.set_archived(root,'a',True);self.assertTrue(run_archive.is_archived(root,'a'))
            run_archive.set_archived(root,'a',False);self.assertFalse(run_archive.is_archived(root,'a'))
            for name,data in files.items():self.assertEqual((root/name).read_bytes(),data)
            self.assertEqual(len(list((root/'backups').iterdir())),2)
            with self.assertRaises(ValueError):run_archive.set_archived(root,'../a',True)
