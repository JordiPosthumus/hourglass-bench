from collections import deque
import copy
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import result_store
import run_recovery
import web

SOURCE = Path(__file__).resolve().parents[1]


def until(predicate, timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.025)
    raise AssertionError('Process fixture did not finish before the test deadline')


class LifecycleTests(unittest.TestCase):
    def test_worker_survives_controller_kill_only_to_save_exit_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            worker="from run_guard import WorkerGuard\nimport pathlib,time\nwith WorkerGuard(%r):\n pathlib.Path(%r).write_text('ready')\n while True:time.sleep(.02)" % (temp,str(root/'ready'))
            parent="""import os,subprocess,sys,time,pathlib
root=sys.argv[1]
env=dict(os.environ,HOURGLASS_EVALUATION_ID='fixture',HOURGLASS_QUESTION_TOKEN='token',HOURGLASS_QUESTION_TASK='a',HOURGLASS_CONTROLLER_PID=str(os.getpid()),HOURGLASS_QUESTION_STARTED_AT=str(time.time()),HOURGLASS_QUESTION_STARTED_MONOTONIC=str(time.monotonic()))
p=subprocess.Popen([sys.executable,'-c',sys.argv[2]],env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
pathlib.Path(root,'pid').write_text(str(p.pid))
while True:time.sleep(.1)
"""
            parent_proc=subprocess.Popen([sys.executable,'-c',parent,temp,worker],cwd=SOURCE)
            child_pid=None
            try:
                until(lambda:(root/'ready').exists())
                child_pid=int((root/'pid').read_text())
                receipt=root/'logs/worker-fixture-token.json'
                self.assertEqual(json.loads(receipt.read_text())['phase'],'running')
                parent_proc.kill();parent_proc.wait(timeout=3)
                data=until(lambda:(lambda d:d if d['phase']!='running' else None)(json.loads(receipt.read_text())))
                self.assertEqual(data['phase'],'stopped')
                self.assertTrue(data['controller_lost'])
                self.assertLess(data['elapsed_s'],5)
                self.assertAlmostEqual(data['ended_at']-data['started_at'],data['elapsed_s'],delta=.1)
            finally:
                if parent_proc.poll() is None:parent_proc.kill();parent_proc.wait()
                if child_pid:
                    try:os.kill(child_pid,signal.SIGKILL)
                    except ProcessLookupError:pass

    def test_signals_wait_for_worker_persistence_and_reject_resume(self):
        # Actual signals and worker threads; no HTTP port or model calls.
        code="""import sys,time,pathlib,threading
from collections import deque
import web
root=pathlib.Path(sys.argv[1]);web.ROOT=root
job={'id':'active'};web.running[:]=[job]
web.queue=deque([{'id':'queued'}]);web.done=deque()
web.calibration.update_evaluation=lambda root,j:(root/(j['id']+'.json')).write_text(__import__('json').dumps(j))
class Server:
 def __init__(self):self.finished=threading.Event()
 def serve_forever(self):
  (root/'ready').write_text('yes');self.finished.wait(10)
 def shutdown(self):
  assert (root/'saved').exists();self.finished.set()
 def server_close(self):(root/'closed').write_text('yes')
def work():
 while not job.get('stop_requested'):time.sleep(.01)
 try:web.resume_job({'job':'active'})
 except ValueError as e:assert 'shutting down' in str(e)
 else:raise AssertionError('resume accepted during shutdown')
 time.sleep(.15)
 with web.condition:
  (root/'saved').write_text('complete');web.running.remove(job);web.condition.notify_all()
web.worker_thread=threading.Thread(target=work);web.worker_thread.start()
web.serve(Server())
"""
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
            with self.subTest(signal=sig),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                proc=subprocess.Popen([sys.executable,'-c',code,temp],cwd=SOURCE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    until(lambda:(root/'ready').exists())
                    proc.send_signal(sig)
                    out,err=proc.communicate(timeout=8)
                    self.assertEqual(proc.returncode,0,out+err)
                    self.assertTrue((root/'closed').exists())
                    self.assertEqual(json.loads((root/'queued.json').read_text())['state'],'cancelled')
                finally:
                    if proc.poll() is None:proc.kill();proc.wait()

    def test_receipt_recovery_keeps_original_metadata_and_excludes_downtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir()
            manifest={'id':'fixture','model':'m','state':'error','hour_timing_unknown':True,'scope':'original','benchmark_version':'original',
                      'active_intervals':[{'start':10,'end':20},{'start':40,'end':None}],
                      'active_question':{'token':'token','task':'a','started_at':45,'elapsed_before_s':7},'question_elapsed_s':{'a':12}}
            original=copy.deepcopy(manifest)
            receipt={'version':'worker-lifecycle-v1','evaluation_id':'fixture','token':'token','task':'a','started_at':45,'ended_at':50,'elapsed_s':5,'phase':'stopped'}
            path=root/'logs/worker-fixture-token.json';path.write_text(json.dumps(receipt))
            recovered,_=run_recovery.recover(root,manifest)
            self.assertEqual(manifest,original)
            self.assertEqual(recovered['elapsed_s'],20)
            self.assertEqual(recovered['question_elapsed_s']['a'],12)
            self.assertEqual(recovered['scope'],'original')
            self.assertEqual(recovered['benchmark_version'],'original')
            self.assertIsNone(run_recovery.recover(root,recovered))
            for change in ({'phase':'running'},{'token':'stale'},{'task':'other'},{'elapsed_s':100},{'ended_at':float('nan')}):
                path.write_text(json.dumps({**receipt,**change}))
                self.assertIsNone(run_recovery.recover(root,manifest))
            path.unlink()
            self.assertIsNone(run_recovery.recover(root,manifest))

    def test_receipt_arriving_after_startup_is_recovered_on_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'logs').mkdir();(root/'evaluations').mkdir()
            m={'id':'fixture','model':'m','state':'running','started':10,'active_intervals':[{'start':10,'end':None}],
               'active_question':{'token':'token','task':'a','started_at':12,'elapsed_before_s':3},
               'expected':[{'task':'a','repeat':1,'task_sha':'sha'}]}
            path=root/'evaluations/fixture.json';path.write_text(json.dumps(m))
            with patch.object(web,'ROOT',root),patch.object(web,'done',deque()),patch.object(web,'running',[]),patch.object(web,'queue',deque()):
                web.restore_job_history()
                self.assertTrue(web.done[0]['hour_timing_unknown'])
                receipt={'version':'worker-lifecycle-v1','evaluation_id':'fixture','token':'token','task':'a','started_at':12,'ended_at':15,'elapsed_s':3,'phase':'stopped'}
                (root/'logs/worker-fixture-token.json').write_text(json.dumps(receipt))
                web.refresh_recovered_history()
                self.assertEqual(web.done[0]['state'],'stopped')
                self.assertEqual(web.done[0]['elapsed_s'],5)
                self.assertEqual(web.done[0]['question_elapsed_s']['a'],6)
                saved=path.read_bytes();web.refresh_recovered_history()
                self.assertEqual(saved,path.read_bytes())

    def test_result_commit_gap_is_reconciled_once_without_rewriting_torn_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'results/a/m/run-one';directory.mkdir(parents=True)
            manifest={'id':'fixture','model':'m','config_hash':'config','expected':[{'task':'a','task_sha':'sha','repeat':1}]}
            record={'run_id':'one','evaluation_id':'fixture','model_config_hash':'config','task_sha':'sha','task':'a','model':'m','artifact_dir':str(directory.relative_to(root)),'run':1,'status':'completed','ts':'2026-09-09T14:00:00+00:00'}
            with patch.object(result_store,'append',side_effect=OSError('simulated crash after commit')):
                with self.assertRaises(OSError):result_store.commit(root,directory,record)
            index=root/'results/results.jsonl';original=b'{"torn":'
            index.write_bytes(original)
            with (root/'.run.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertEqual(result_store.reconcile(root,manifest),0)
            self.assertEqual(result_store.reconcile(root,manifest),1)
            self.assertEqual(result_store.reconcile(root,manifest),0)
            self.assertTrue(index.read_bytes().startswith(original+b'\n'))
            self.assertEqual(json.loads(index.read_text().splitlines()[1]),record)
            self.assertEqual(next((root/'backups').glob('*/results-before.jsonl')).read_bytes(),original)
            for change in ({'evaluation_id':'other'},{'task_sha':'stale'},{'model_config_hash':'stale'},{'artifact_dir':'elsewhere'}):
                (directory/'metrics.json').write_text(json.dumps({**record,**change,'run_id':'new'}))
                self.assertEqual(result_store.reconcile(root,manifest),0)


if __name__=='__main__':unittest.main()
