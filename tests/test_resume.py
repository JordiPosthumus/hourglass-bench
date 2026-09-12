import json,tempfile,time,unittest,types
from pathlib import Path
from unittest.mock import patch
import web,hourglass,calibration as c,run_tracking as rt

class ResumeTests(unittest.TestCase):
    def setUp(self):
        sound=patch.object(web.hour_deadline,'chime');sound.start();self.addCleanup(sound.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.patches=[patch.object(web,k,self.root/v) for k,v in [('TASKS','tasks'),('RESULTS','results'),('LOGS','logs')]]+[patch.object(web,'ROOT',self.root)]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
        self.cfg={'name':'model','model':'fixture','base_url':'http://example.invalid/v1','max_tokens':262144,'hardware':'Fixture hardware','server_name':'Fixture server','quantization':'FP16'}
        (self.root/'models.json').write_text(json.dumps({'models':[self.cfg]}));web.RESULTS.mkdir();web.LOGS.mkdir()
        for i in range(21):
            p=web.TASKS/f'T{i:02d}'/'task.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'id':f'T{i:02d}','kind':'mcq','prompt':'fixture','options':[{'id':'001','text':'a'},{'id':'002','text':'b'}],'answer':'001','repeat':2}))
        with web.condition:web.queue.clear();web.running.clear();web.done.clear();web.worker_stop=False
        self.addCleanup(lambda:setattr(web,'worker_stop',False))
        self.rows=[]

    def interrupted(self,repeat=1,n=2):
        job=web.enqueue({'model':'model','tasks':[f'T{i:02d}' for i in range(n)]})
        with web.condition:web.queue.remove(job)
        job.update(state='error',started=100,ended=120,error='fixture error');web.done.append(job);c.update_evaluation(self.root,job)
        self.job=job;self.m=web.saved_manifest(job['id'])
        if repeat!=1:
            job['repeat']=repeat;self.m['repeat']=repeat
            for t in self.m['expected']:t['repeat']=repeat
            c.write(self.root/'evaluations'/(job['id']+'.json'),self.m)
        return job

    def row(self,tid,run=1,status='completed',solved=False,reason=None):
        expected=next(t for t in self.m['expected'] if t['task']==tid)
        r={'evaluation_id':self.job['id'],'task':tid,'run':run,'run_id':str(len(self.rows)),
           'status':status,'solved':solved,'duration_s':5,'model':'model','model_config_hash':c.digest(self.cfg),
           'benchmark_version':hourglass.BENCHMARK_VERSION,'task_sha':expected['task_sha'],'task_bundle_sha':expected['task_bundle_sha'],'node':'test'}
        if reason:r['score_reason']=reason
        self.rows.append(r);(web.RESULTS/'results.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in self.rows));return r

    def run_fake(self,solved=True):
        calls=[];outer=self
        class Proc:
            def __init__(self,cmd,**kwargs):
                tid=cmd[cmd.index('run')+1];indices=[1]
                skip=kwargs['env']['HOURGLASS_SKIP_REASON'];calls.append((tid,indices,skip))
                for i in indices:outer.row(tid,i,solved=solved and not skip,reason=skip or None)
            def wait(self, timeout=None):web.worker_stop=True;return 0
        with patch.object(web.subprocess,'Popen',Proc):web.worker()
        return calls

    def test_historical_multiple_attempt_run_cannot_resume(self):
        job=self.interrupted(repeat=2);self.row('T00',1,solved=True);self.row('T00',2,status='error');self.row('T01',1,solved=True)
        log=web.LOGS/f"job-{job['id']}.log";log.write_text('ORIGINAL LOG\n')
        before=(web.RESULTS/'results.jsonl').read_bytes()
        with self.assertRaisesRegex(ValueError,'runs once'):web.resume_job({'job':job['id']})
        self.assertEqual((web.RESULTS/'results.jsonl').read_bytes(),before)
        self.assertEqual(log.read_text(),'ORIGINAL LOG\n');self.assertFalse(web.queue)

    def test_resume_retains_wrong_streak_and_stop_rule(self):
        job=self.interrupted(n=21)
        for i in range(19):self.row(f'T{i:02d}')
        self.row('T19',status='error');web.resume_job({'job':job['id']})
        self.assertEqual(self.run_fake(solved=False),[('T19',[1],''),('T20',[1],'wrong_streak_limit')]);self.assertEqual(web.done[-1]['stopped_after'],'T19')
        with self.assertRaises(ValueError):web.resume_job({'job':job['id']})

    def test_duplicate_resume_rejected_and_frozen_settings_survive_catalog_edit(self):
        job=self.interrupted();self.row('T00',solved=True);web.resume_job({'job':job['id']})
        with self.assertRaises(ValueError):web.resume_job({'job':job['id']})
        with web.condition:web.queue.clear();web.done.append(job)
        cfg={**self.cfg,'max_tokens':123};(self.root/'models.json').write_text(json.dumps({'models':[cfg]}))
        resumed=web.resume_job({'job':job['id']})
        self.assertEqual(resumed['model_config_snapshot'],self.cfg)
        frozen=c.frozen_config_path(self.root,web.saved_manifest(job['id']),cfg)
        self.assertEqual(json.loads(frozen.read_text())['models'],[self.cfg])
        with web.condition:web.queue.clear();web.done.append(job)
        legacy=web.saved_manifest(job['id']);legacy.pop('model_config_snapshot');c.write(self.root/'evaluations'/(job['id']+'.json'),legacy)
        with self.assertRaisesRegex(ValueError,'settings changed'):web.resume_job({'job':job['id']})

    def test_changed_question_is_rejected(self):
        job=self.interrupted();(self.root/self.m['task_snapshot']/'T00'/'task.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'content changed'):web.resume_job({'job':job['id']})

    def test_cross_version_resume_is_labelled_and_not_calibrated(self):
        job=self.interrupted();self.m['benchmark_version']='1.1.0';c.write(self.root/'evaluations'/(job['id']+'.json'),self.m)
        self.row('T00',solved=True)['benchmark_version']='1.1.0'
        (web.RESULTS/'results.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in self.rows))
        plan=web.resume_plan(job,self.m,web.result_rows());self.assertTrue(plan['allowed']);self.assertIn('mixes versions',plan['version_warning'])
        web.resume_job({'job':job['id']});self.run_fake()
        self.assertFalse(c.evaluations(self.root,web.result_rows())[0]['eligible'])

    def test_progress_counts_points_rate_and_idle_time_correctly(self):
        job=self.interrupted(repeat=2);self.row('T00',1,solved=True);self.row('T00',2);self.row('T01',1,status='error')
        p=rt.progress(self.m,self.rows,{'state':'running','elapsed_s':20,'active_started':1000},1030)
        self.assertEqual(p['points'],.5);self.assertEqual(p['accuracy'],.5);self.assertEqual(p['finished_questions'],1)
        self.assertEqual(p['elapsed_s'],50);self.assertAlmostEqual(p['questions_per_minute'],1.2);self.assertEqual(p['errors'],1)
        p=rt.progress(self.m,self.rows,{'state':'pending','elapsed_s':20},9999);self.assertEqual(p['elapsed_s'],20)

    def test_early_stop_zeros_do_not_inflate_run_rate(self):
        self.interrupted();self.row('T00');self.row('T01',reason='five_wrong_in_row')
        p=rt.progress(self.m,self.rows,{'state':'completed','elapsed_s':60},500)
        self.assertEqual(p['finished_questions'],2);self.assertEqual(p['questions_per_minute'],1);self.assertEqual(p['scored_attempts'],1)

    def test_legacy_resume_freezes_original_attempt_ids(self):
        job=self.interrupted();r=self.row('T00',solved=True);r.pop('evaluation_id');r['ts']='1970-01-01T00:01:50+00:00'
        (web.RESULTS/'results.jsonl').write_text(json.dumps(r)+'\n');self.m['legacy_time_match']=True;c.write(self.root/'evaluations'/(job['id']+'.json'),self.m)
        web.resume_job({'job':job['id']});m=web.saved_manifest(job['id']);self.assertEqual(m['legacy_run_ids'],[r['run_id']])
        self.assertEqual(self.run_fake(),[('T01',[1],'')]);self.assertEqual(c.evaluations(self.root,web.result_rows())[0]['attempts'],2)

class ClearRunTests(unittest.TestCase):
    setUp=ResumeTests.setUp
    interrupted=ResumeTests.interrupted
    row=ResumeTests.row
    def test_clear_backs_up_exact_run_and_keeps_other_results(self):
        job=self.interrupted();r=self.row('T00',solved=True)
        artifact=web.RESULTS/'T00'/'model'/'run-fixture';artifact.mkdir(parents=True);(artifact/'trace.json').write_text('preserved trace')
        r['artifact_dir']=str(artifact.relative_to(self.root));other={**r,'evaluation_id':'other','run_id':'other','artifact_dir':'results/other/run-other'}
        self.rows.append(other);(web.RESULTS/'results.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in self.rows))
        log=web.LOGS/f"job-{job['id']}.log";log.write_text('preserved log')
        result=web.clear_job({'job':job['id']});backup=self.root/result['backup']
        self.assertEqual(web.result_rows(),[other]);self.assertFalse(artifact.exists());self.assertFalse(log.exists());self.assertFalse((self.root/'evaluations'/(job['id']+'.json')).exists())
        self.assertEqual((backup/log.name).read_text(),'preserved log');self.assertEqual((backup/'artifacts/T00/model/run-fixture/trace.json').read_text(),'preserved trace')
        self.assertEqual(len((backup/'results-before.jsonl').read_text().splitlines()),2);self.assertFalse(web.done)
    def test_clear_refuses_active_work_and_keeps_files(self):
        job=self.interrupted();self.row('T00');before=(web.RESULTS/'results.jsonl').read_bytes()
        web.running.append({'id':'active'})
        try:
            with self.assertRaisesRegex(ValueError,'active model work'):web.clear_job({'job':job['id']})
        finally:web.running.clear()
        self.assertEqual((web.RESULTS/'results.jsonl').read_bytes(),before)
    def test_clear_removes_reference_target_with_backup(self):
        job=self.interrupted();self.row('T00',solved=True);self.row('T01',solved=True);job['state']='completed';c.update_evaluation(self.root,job)
        c.set_reference(self.root,self.rows,{'evaluation_id':job['id'],'target':5})
        result=web.clear_job({'job':job['id']});doc=c.read(self.root/'calibration.json',{})
        self.assertTrue(all(not s['references'] for s in doc['scopes'].values()));self.assertTrue((self.root/result['backup']/'calibration-before.json').exists())

if __name__=='__main__':unittest.main()
