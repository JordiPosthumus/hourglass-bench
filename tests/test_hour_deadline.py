import threading
import io
import json
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

    def test_failure_sound_plays_bundled_audio_and_tolerates_missing_player(self):
        with mock.patch.object(hour_deadline.subprocess,'Popen') as play:
            hour_deadline.chime(failed=True)
            self.assertEqual(Path(play.call_args.args[0][1]),Path(hour_deadline.__file__).parent/'sounds/run-failed.wav')
            self.assertEqual(play.call_args.args[0][0],'/usr/bin/afplay')
        with mock.patch.object(hour_deadline.subprocess,'Popen',side_effect=FileNotFoundError):
            hour_deadline.chime(failed=True)

    def test_terminal_sound_distinguishes_failure_completion_and_manual_stop(self):
        cases=[({'state':'error'},mock.call(failed=True)),
               ({'state':'completed','stopped_after':'fixture'},mock.call(failed=True)),
               ({'state':'completed'},mock.call()),
               ({'state':'stopped','stop_reason':'hour_limit'},mock.call()),
               ({'state':'stopped','stop_reason':'user','stopped_after':'fixture'},None),
               ({'state':'cancelled'},None)]
        for job,expected in cases:
            with self.subTest(job=job),mock.patch.object(hour_deadline,'chime') as play:
                hour_deadline.finish_sound(job)
                self.assertEqual(play.call_args_list,[] if expected is None else [expected])

    def test_live_bridge_skips_history_deduplicates_and_hands_off_to_controller(self):
        old={'id':'old','state':'error','ended':1}
        failed={'id':'new','state':'error','ended':2}
        resumed={**failed,'resume_count':1,'ended':3}
        snapshots=[{'jobs':{'done':[old],'running':[{'id':'new','state':'running'}]}},
                   {'jobs':{'done':[{**old,'ended':99},failed]}},
                   {'jobs':{'done':[old,failed]}},
                   {'jobs':{'done':[old,resumed]}},
                   {'failure_sound_version':1,'jobs':{'done':[old,resumed]}}]
        with tempfile.TemporaryDirectory() as directory,\
             mock.patch.object(hour_deadline.urllib.request,'urlopen',side_effect=[io.BytesIO(json.dumps(s).encode()) for s in snapshots]) as get,\
             mock.patch.object(hour_deadline.time,'sleep'),mock.patch.object(hour_deadline,'chime') as play:
            hour_deadline.watch_failures('http://fixture.invalid',Path(directory)/'observer.lock')
            self.assertEqual(play.call_args_list,[mock.call(failed=True),mock.call(failed=True)])
            self.assertTrue(all(call.args==('http://fixture.invalid/api/state',) for call in get.call_args_list))

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
                     mock.patch.object(web,'saved_manifest',return_value={'id':'fixture','model_config_snapshot':{},'config_hash':web.evaluation_store.digest({}),'expected':[{'task':'a','repeat':1}]}),
                     mock.patch.object(web.evaluation_store,'update_evaluation'),mock.patch.object(hour_deadline,'chime')]
            for p in patches:p.start()
            thread=threading.Thread(target=web.worker)
            try:
                thread.start()
                with condition:
                    self.assertTrue(condition.wait_for(lambda:bool(done),timeout=3))
                    web.worker_stop=True;condition.notify_all()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(job['state'],'stopped',job)
                self.assertEqual(job['stop_reason'],'hour_limit')
                self.assertLess(job['rc'],0)
                hour_deadline.chime.assert_called_once()
            finally:
                with condition:web.worker_stop=True;condition.notify_all()
                thread.join(1)
                for p in reversed(patches):p.stop()
