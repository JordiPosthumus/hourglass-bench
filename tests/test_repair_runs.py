import os
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import evaluation_store
import hour_score
import repair_runs
import run_tracking
import scoring_policy
import score_report


def at(t):return dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        expected=[]
        for tid in ('A','B','C','D'):
            p=self.root/'tasks'/tid/'task.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'prompt':'PRIVATE QUESTION','answer':'PRIVATE ANSWER','section':'games','tier':1,'repeat':1}))
            expected.append({'task':tid,'task_sha':hashlib.sha256(p.read_bytes()).hexdigest()[:16],'repeat':1,'weight':1,'weight_version':'weighted-hour-v1','vision':False})
        cfg={'name':'fixture','model':'fixture','base_url':'http://fixture.invalid/v1','context_window':262144,'max_tokens':262144,'reasoning':'medium'}
        self.source={'id':'original','model':'fixture','model_id':'fixture','model_config_snapshot':cfg,'config_hash':evaluation_store.digest(cfg),'expected':expected,'order':['A','B','C','D'],'tasks':['A','B','C','D'],
                     'benchmark_version':'2.5.0','state':'stopped','started':1000,'ended':4600,'elapsed_s':3600,'active_intervals':[{'start':1000,'end':4600}],
                     'repeat':1,'question_timeout_s':900,'stop_after_wrong':20,'scoring_policy':scoring_policy.NET,'question_elapsed_s':{'A':200,'B':900,'C':400},'current_task':'C','scope':'original-scope','created':900}
        self.rows=[{'run_id':tid,'evaluation_id':'original','model':'fixture','task':tid,'task_sha':expected[i]['task_sha'],'run':1,'ts':at(t),'status':status,'solved':solved,'duration_s':duration,'completion_tokens':50,'parsed_answer':{'answer':'A'},'benchmark_version':'2.5.0','reasoning':'PRIVATE TRACE'} for i,(tid,t,status,solved,duration) in enumerate([('A',1200,'completed',False,200),('B',2200,'timeout',False,900)])]
        self.rows[0]['caveats']=[{'code':'diagnostic_trace_exposure'}]
        (self.root/'evaluations').mkdir();evaluation_store.write(self.root/'evaluations/original.json',self.source)
        (self.root/'results').mkdir();(self.root/'results/results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows))
        (self.root/'models.json').write_text(json.dumps({'models':[cfg]}))

    def create(self,tasks=None):
        p=repair_runs.plan(self.root,self.source,self.rows,tasks)
        job=repair_runs.create(self.root,self.source,self.rows,{'tasks':p['tasks'],'revision':p['revision']},'2.5.1')
        return p,job

    def test_normal_run_with_explicit_null_repair(self):
        source=copy.deepcopy(self.source);source['repair']=None
        expected=hour_score.score(self.source,self.rows,self.source['expected'])
        self.assertEqual(hour_score.score(source,self.rows,source['expected']),expected)
        report=json.loads(score_report.build(self.root,source,self.rows,source)['report.json'])
        self.assertNotIn('repair',report)
        import question_context
        question_context.build(self.root,[report],[source],self.rows,4600)
        evaluation_store.write(self.root/'evaluations/original.json',source)
        self.assertEqual(repair_runs.dependencies(self.root,'original'),[])

    def test_preserves_original_and_exact_config_with_explicit_credit(self):
        original=(self.root/'evaluations/original.json').read_bytes();index=(self.root/'results/results.jsonl').read_bytes()
        p,job=self.create()
        self.assertEqual(p['tasks'],['A']);self.assertEqual(p['remaining_s'],200);self.assertEqual(p['continuation'],['C','D'])
        self.assertEqual(job['question_elapsed_s'],{'B':900,'C':400});self.assertEqual(job['elapsed_s'],3400)
        self.assertEqual(job['model_config_snapshot'],self.source['model_config_snapshot']);self.assertEqual(job['question_timeout_s'],900)
        self.assertEqual((self.root/'evaluations/original.json').read_bytes(),original);self.assertEqual((self.root/'results/results.jsonl').read_bytes(),index)
        self.assertEqual((self.root/job['repair']['backup']/'results-before.jsonl').read_bytes(),index)
        raw=run_tracking.raw_attempts(job,self.rows)
        self.assertEqual([r['task'] for r in raw],['B']);self.assertTrue(raw[0]['repair_inherited'])
        self.assertEqual(run_tracking.missing_repeats(job,raw,'B'),[])
        self.assertEqual(run_tracking.missing_repeats(job,raw,'A'),[1]);self.assertNotIn('reasoning',raw[0])
        self.assertEqual(repair_runs.dependencies(self.root,'original'),[job['id']])

    def test_legacy_config_must_match_original_digest_and_no_new_timeout(self):
        self.source.pop('model_config_snapshot');self.source.pop('question_timeout_s');self.source.pop('question_elapsed_s')
        p,job=self.create();self.assertEqual(p['remaining_s'],200);self.assertNotIn('question_timeout_s',job)
        self.assertEqual(job['model_config_snapshot']['max_tokens'],262144)
        (self.root/'models.json').write_text('{"models":[]}')
        with self.assertRaisesRegex(ValueError,'frozen model settings'):repair_runs.plan(self.root,self.source,self.rows)

    def test_review_revision_questions_and_unknown_clock(self):
        p=repair_runs.plan(self.root,self.source,self.rows)
        for source in ({**self.source,'hour_timing_unknown':True},{**self.source,'state':'running'}):
            with self.assertRaises(ValueError):repair_runs.plan(self.root,source,self.rows)
        with self.assertRaisesRegex(ValueError,'changed'):repair_runs.create(self.root,self.source,self.rows,{'tasks':['A'],'revision':'stale'},'2.5.1')
        (self.root/'tasks/A/task.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'content has changed'):repair_runs.plan(self.root,self.source,self.rows)
        self.assertEqual(len(list((self.root/'evaluations').glob('*.json'))),1)

    def test_score_boundary_pause_and_javascript_parity(self):
        p,job=self.create();job.update(started=10000,ended=11101,state='stopped',active_intervals=[{'start':10000,'end':10050},{'start':10950,'end':11101}],elapsed_s=3601,resume_count=1)
        fresh=[{'evaluation_id':job['id'],'run_id':'new-'+t,'task':t,'run':1,'status':'completed','solved':True,'ts':at(ts)} for t,ts in [('A',10020),('C',11100),('D',11100.001)]]
        h=hour_score.score(job,self.rows+fresh)
        self.assertEqual(h['points'],2);self.assertEqual(h['elapsed_s'],3601);self.assertEqual(h['timeouts'],1);self.assertEqual(h['after_deadline_questions'],1);self.assertEqual(h['state'],'final')
        script="const {hourScore}=require('./ui/hour-score');console.log(JSON.stringify(hourScore(...JSON.parse(process.argv[1]))))"
        browser=json.loads(subprocess.check_output(['node','-e',script,json.dumps([job,self.rows+fresh,job['expected'],11100])],text=True))
        self.assertEqual(h,browser)
        materialized=repair_runs.composite_rows(job,self.rows+fresh)
        self.assertEqual(hour_score.score(job,materialized),h)
        self.assertEqual(run_tracking.progress(job,materialized,job,11100)['elapsed_s'],3601)

    def test_reports_label_repair_without_private_questions_or_traces(self):
        p,job=self.create();job.update(started=10000,ended=10200,state='stopped',active_intervals=[{'start':10000,'end':10200}])
        r={'evaluation_id':job['id'],'run_id':'replacement','task':'A','run':1,'status':'completed','solved':True,'ts':at(10020),'completion_tokens':8}
        files=score_report.build(self.root,job,self.rows+[r],job);report=json.loads(files['report.json'])
        self.assertEqual(report['weighted_points'],1);self.assertEqual(report['repair']['policy'],repair_runs.POLICY)
        self.assertIn('Repaired run',files['README.md']);self.assertIn('Repaired run',files['score.svg'])
        self.assertFalse(any('PRIVATE' in text for text in files.values()))
        self.assertTrue(all(p['weighted']==0 for p in report['curve'] if p['seconds']<3420))
        self.assertEqual(report['curve'][-1]['weighted'],1)

    def test_repair_question_context_uses_reconstructed_time(self):
        import question_context
        p,job=self.create();job.update(started=10000,state='running',current_task='A',active_intervals=[{'start':10000,'end':None}])
        timeline=question_context.timeline(job,job,self.rows,{},10005)
        self.assertEqual(timeline['end_s'],3405)
        self.assertEqual(timeline['spans'][-1]['task'],'A')
        self.assertEqual(timeline['spans'][-1]['start_s'],3400)
        self.assertTrue(timeline['spans'][0]['status'].startswith('Retained'))
        self.assertIn('Repaired run',timeline['timing_basis'])

    def test_cli_lock_also_blocks_start_before_mutation(self):
        import fcntl
        p=repair_runs.plan(self.root,self.source,self.rows)
        with (self.root/'.run.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'active model work'):
                repair_runs.create(self.root,self.source,self.rows,{'tasks':['A'],'revision':p['revision']},'2.5.1')
        self.assertEqual(len(list((self.root/'evaluations').glob('*.json'))),1)

    def test_busy_repair_never_queues_or_creates(self):
        import web
        for active,pending in (([{'id':'other'}],[]),([],[{'id':'queued'}])):
            with patch.object(web,'running',active),patch.object(web,'queue',pending),patch.object(repair_runs,'create') as create:
                with self.assertRaisesRegex(ValueError,'Each repair starts manually'):web.start_repair({})
                create.assert_not_called()


    @unittest.skipUnless(os.environ.get('HOURGLASS_NATIVE_REPAIR_TEST')=='1','Native process-group fixture; run with HOURGLASS_NATIVE_REPAIR_TEST=1')
    def test_worker_replaces_then_continues_and_stops_at_budget(self):
        import web,threading,time
        from collections import deque
        self.source['question_elapsed_s']={'A':0.8,'B':3598.2,'C':1}
        self.rows[0].update(ts=at(1000.8),duration_s=0.8)
        self.rows[1].update(ts=at(4599),status='completed',solved=True,duration_s=3598.2)
        (self.root/'results/results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows))
        before=(self.root/'results/results.jsonl').read_bytes()
        p,job=self.create()
        runner="""import sys,time,json,os,datetime
from pathlib import Path
tid=sys.argv[2]
with open('invoked.txt','a') as f:f.write(tid+'\\n')
time.sleep(3 if tid=='D' else .05)
r={'evaluation_id':os.environ['HOURGLASS_EVALUATION_ID'],'run_id':'fresh-'+tid,'model':'fixture','task':tid,'run':1,'status':'completed','solved':True,'ts':datetime.datetime.now(datetime.timezone.utc).isoformat()}
with open('results/results.jsonl','a') as f:f.write(json.dumps(r)+'\\n')
"""
        for name in ('hourglass.py','hourglass.py'):(self.root/name).write_text(runner)
        cond=threading.Condition();finished=[];thread_errors=[]
        with patch.multiple(web,ROOT=self.root,RESULTS=self.root/'results',LOGS=self.root/'logs',condition=cond,queue=deque([job]),running=[],done=finished,worker_stop=False),patch.object(web,'model_document',return_value={'models':[self.source['model_config_snapshot']]}),patch.object(web.live_tps,'collect'),patch.object(web.hour_deadline,'chime'),patch.object(threading,'excepthook',side_effect=lambda e:thread_errors.append(str(e.exc_value))):
            thread=threading.Thread(target=web.worker,daemon=True);thread.start()
            try:
                with cond:self.assertTrue(cond.wait_for(lambda:bool(finished),timeout=6))
            finally:
                with cond:web.worker_stop=True;cond.notify_all()
                thread.join(timeout=2)
        self.assertEqual(thread_errors,[])
        self.assertEqual(job['state'],'stopped',job.get('error'));self.assertEqual(job['stop_reason'],'hour_limit')
        self.assertEqual((self.root/'invoked.txt').read_text().splitlines(),['A','C','D'])
        self.assertTrue((self.root/'results/results.jsonl').read_bytes().startswith(before))
        self.assertGreaterEqual(job['elapsed_s'],3600);self.assertLess(job['elapsed_s'],3601)
        self.assertEqual(job['question_elapsed_s']['B'],3598.2)
        self.assertGreater(job['question_elapsed_s']['C'],1)
        persisted=json.loads((self.root/'evaluations'/(job['id']+'.json')).read_text())
        self.assertEqual(persisted['repair'],job['repair'])
        actual=[json.loads(l) for l in (self.root/'results/results.jsonl').read_text().splitlines()]
        self.assertEqual(hour_score.score(job,actual)['points'],3)


    def test_archived_questions_are_frozen_without_changing_current_bank(self):
        import shutil,task_identity
        archive=self.root/'backups/revision/original-bank'
        shutil.copytree(self.root/'tasks',archive)
        current=self.root/'tasks/A/task.json';current.write_text('{"prompt":"new bank","answer":"new answer"}')
        before=current.read_bytes();p,job=self.create()
        frozen=self.root/job['task_snapshot']/'A'
        expected=next(e for e in job['expected'] if e['task']=='A')
        task_identity.verify(frozen,expected)
        self.assertEqual((frozen/'task.json').read_bytes(),(archive/'A/task.json').read_bytes())
        self.assertEqual(current.read_bytes(),before)
        self.assertEqual(p['question_sources']['A'],str(archive/'A'))

    def test_asset_change_after_review_rejects_repair(self):
        asset=self.root/'tasks/A/image.png';asset.write_bytes(b'first')
        p=repair_runs.plan(self.root,self.source,self.rows)
        asset.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Review the repair again'):
            repair_runs.create(self.root,self.source,self.rows,{'tasks':p['tasks'],'revision':p['revision']},'test')
        self.assertEqual(len(list((self.root/'evaluations').glob('*.json'))),1)

    def test_reset_or_unknown_clock_does_not_claim_repaired_score_available(self):
        _,job=self.create();job.update(state='stopped',started=10000,ended=10200,active_intervals=[{'start':10000,'end':10200}])
        h=hour_score.score(dict(job,results_reset=True),self.rows)
        self.assertEqual(h['state'],'unavailable');self.assertIn('reset',h['timing_note'])
        h=hour_score.score(dict(job,hour_timing_unknown=True),self.rows)
        self.assertEqual(h['state'],'unavailable');self.assertIn('withheld',h['timing_note'])


if __name__=='__main__':unittest.main()
