import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock
import question_deadline as qd
import web
import run_tracking
import live_tps

FIXTURE='''import json,os,sys,time
from pathlib import Path
root=Path.cwd(); tid=sys.argv[2]
indices=[1]
for repeat in indices:
 state={'task':tid,'run':repeat,'run_id':tid+str(repeat),'started':time.time()}
 Path(os.environ['HOURGLASS_ATTEMPT_CHECKPOINT']).write_text(json.dumps(state))
 if tid=='a':
  time.sleep(30)
 elif tid=='fail':
  time.sleep(.08);sys.exit(1)
 elif tid=='missing':
  sys.exit(0)
 row={'task':tid,'run':repeat,'status':'completed','solved':True,'evaluation_id':'fixture','ts':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
 with (root/'results/results.jsonl').open('a') as f:f.write(json.dumps(row)+'\\n')
'''

class QuestionDeadlineTests(unittest.TestCase):
 def exercise(self, tasks=('a','b'), used=None, hour_used=0, question_limit=.25):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'hourglass.py').write_text(FIXTURE);(root/'results').mkdir()
   expected=[{'task':t,'repeat':1,'task_sha':'fixture'} for t in tasks]
   manifest={'id':'fixture','expected':expected,'model_config_snapshot':{},'config_hash':web.calibration.digest({}),'scoring_policy':'net-hour-v2'}
   condition=threading.Condition();done=deque()
   job={'id':'fixture','tasks':list(tasks),'model':'fixture','state':'pending','elapsed_s':hour_used,'question_timeout_s':question_limit,'question_elapsed_s':used or {}}
   def rows():
    path=root/'results/results.jsonl'
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
   patches=[mock.patch.object(web,'ROOT',root),mock.patch.object(web,'LOGS',root/'logs'),mock.patch.object(web,'queue',deque([job])),mock.patch.object(web,'running',[]),mock.patch.object(web,'done',done),mock.patch.object(web,'condition',condition),mock.patch.object(web,'worker_stop',False),mock.patch.object(web,'result_rows',side_effect=rows),mock.patch.object(web,'saved_manifest',return_value=manifest),mock.patch.object(web.calibration,'update_evaluation'),mock.patch.object(web.hour_deadline,'chime')]
   for p in patches:p.start()
   thread=threading.Thread(target=web.worker);started=time.monotonic()
   try:
    thread.start()
    with condition:
     self.assertTrue(condition.wait_for(lambda:bool(done),timeout=4),job)
     web.worker_stop=True;condition.notify_all()
    thread.join(1)
    self.sound_calls=list(web.hour_deadline.chime.call_args_list)
    return job,rows(),time.monotonic()-started
   finally:
    with condition:web.worker_stop=True;condition.notify_all()
    thread.join(1)
    for p in reversed(patches):p.stop()

 def test_single_attempt_timeout_then_auto_advance(self):
  job,rows,elapsed=self.exercise()
  self.assertEqual(job['state'],'completed',job)
  self.assertEqual(self.sound_calls,[mock.call()])
  self.assertEqual([(r['task'],r['run'],r['status']) for r in rows],[('a',1,'timeout'),('b',1,'completed')])
  self.assertLess(elapsed,1.5);self.assertGreaterEqual(job['question_elapsed_s']['a'],.24)
  self.assertFalse(run_tracking.missing_repeats({'expected':[{'task':'a','repeat':3}]},rows,'a'))

 def test_resume_does_not_reset_question_clock(self):
  job,rows,elapsed=self.exercise(tasks=('a',),used={'a':.22})
  self.assertEqual([r['status'] for r in rows],['timeout'])
  self.assertLess(elapsed,.6)

 def test_hour_limit_has_priority(self):
  job,rows,elapsed=self.exercise(hour_used=3599.97)
  self.assertEqual(job['state'],'stopped',job);self.assertEqual(job['stop_reason'],'hour_limit')
  self.assertFalse(any(r['status']=='timeout' for r in rows));self.assertLess(elapsed,1)

 def test_failure_time_is_retained_for_resume(self):
  job,rows,elapsed=self.exercise(tasks=('fail',),question_limit=2)
  self.assertEqual(job['state'],'error');self.assertGreater(job['question_elapsed_s']['fail'],.07)
  self.assertEqual(self.sound_calls,[mock.call(failed=True)])

 def test_missing_result_plays_failure_sound_once(self):
  job,rows,elapsed=self.exercise(tasks=('missing',),question_limit=2)
  self.assertEqual(job['state'],'error');self.assertIn('valid result',job['error'])
  self.assertEqual(self.sound_calls,[mock.call(failed=True)])

 def test_child_cleanup_survives_parent_exit(self):
  with tempfile.TemporaryDirectory() as directory:
   marker=Path(directory)/'escaped'
   child="import signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(.5);pathlib.Path("+repr(str(marker))+").touch()"
   script='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);print("ready",flush=True);time.sleep(30)'
   proc=subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.PIPE,text=True,start_new_session=True)
   proc.stdout.readline();time.sleep(.08)
   with mock.patch.object(qd,'STOP_GRACE_S',.1):qd.terminate_group(proc)
   proc.wait(timeout=1);time.sleep(.6);proc.stdout.close()
   self.assertFalse(marker.exists())

 def test_tps_parser_exports_only_measurements(self):
  row=live_tps.parse('0909 05:58:01 ds4-server: secret prompt decoding chunk=23.95 t/s avg=24.01 t/s 12.495s',123)
  self.assertEqual(row['tps'],23.95);self.assertNotIn('secret',json.dumps(row))
  self.assertIsNone(live_tps.parse('model secret text',123))

if __name__=='__main__':unittest.main()
