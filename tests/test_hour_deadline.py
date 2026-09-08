import threading
import time
import unittest
import tempfile
from pathlib import Path
from collections import deque
from unittest import mock

import hour_deadline


class HourDeadlineTests(unittest.TestCase):
    def test_elapsed_includes_prior_active_time(self):
        self.assertEqual(hour_deadline.remaining({'elapsed_s':3500,'active_started':1000},1050),50)
        self.assertEqual(hour_deadline.remaining({'elapsed_s':3500,'active_started':1000},1200),0)

    def test_timer_requests_only_targeted_stop(self):
        condition=threading.Condition()
        job={'id':'target','state':'running','elapsed_s':3599.95,'active_started':time.time()}
        called=[]
        thread=threading.Thread(target=hour_deadline.watch_job,args=(job,condition,called.append))
        thread.start();thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(called,[{'job':'target','reason':'hour_limit'}])

    def test_completion_cancels_timer(self):
        condition=threading.Condition()
        job={'id':'target','state':'running','elapsed_s':0,'active_started':time.time()}
        called=[]
        thread=threading.Thread(target=hour_deadline.watch_job,args=(job,condition,called.append))
        thread.start()
        with condition:
            job['state']='completed';condition.notify_all()
        thread.join(1)
        self.assertFalse(thread.is_alive());self.assertEqual(called,[])

    @mock.patch('hour_deadline.subprocess.Popen')
    @mock.patch('hour_deadline.pathlib.Path.exists',return_value=True)
    def test_chime_uses_system_sound(self,exists,popen):
        hour_deadline.chime()
        self.assertEqual(popen.call_args.args[0],['/usr/bin/afplay','/System/Library/Sounds/Glass.aiff'])

    def test_worker_deadline_stops_real_fixture_process(self):
        import web
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'hourglass.py').write_text('import time\ntime.sleep(30)\n')
            condition=threading.Condition();done=deque()
            job={'id':'fixture','tasks':['a'],'model':'fixture','state':'pending','elapsed_s':3599.8}
            patches=[mock.patch.object(web,'ROOT',root),mock.patch.object(web,'LOGS',root/'logs'),
                     mock.patch.object(web,'queue',deque([job])),mock.patch.object(web,'running',[]),
                     mock.patch.object(web,'done',done),mock.patch.object(web,'condition',condition),
                     mock.patch.object(web,'worker_stop',False),mock.patch.object(web,'result_rows',return_value=[]),
                     mock.patch.object(web,'saved_manifest',return_value={'id':'fixture','expected':[{'task':'a','repeat':1}]}),
                     mock.patch.object(web.calibration,'update_evaluation'),mock.patch.object(hour_deadline,'chime')]
            for p in patches:p.start()
            thread=threading.Thread(target=web.worker)
            try:
                thread.start()
                with condition:
                    self.assertTrue(condition.wait_for(lambda:bool(done),timeout=3))
                    web.worker_stop=True;condition.notify_all()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(job['state'],'stopped')
                self.assertEqual(job['stop_reason'],'hour_limit')
                self.assertLess(job['rc'],0)
                hour_deadline.chime.assert_called_once()
            finally:
                with condition:web.worker_stop=True;condition.notify_all()
                thread.join(1)
                for p in reversed(patches):p.stop()
