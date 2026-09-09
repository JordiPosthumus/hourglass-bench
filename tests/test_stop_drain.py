import signal
import subprocess
import sys
import unittest
import harness_runner

class StopDrainTests(unittest.TestCase):
    def test_shutdown_output_larger_than_pipe_capacity_is_drained(self):
        code="import signal,sys,time\ndef stop(*args):\n sys.stdout.write('x'*1000000);sys.stdout.flush();sys.stderr.write('end');sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\nprint('ready',flush=True)\nwhile True:time.sleep(.01)"
        proc=subprocess.Popen([sys.executable,'-u','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(proc.stdout.readline(),'ready\n')
            out,err=harness_runner.stop_child(proc)
            self.assertEqual(len(out),1000000);self.assertEqual(err,'end');self.assertEqual(proc.returncode,0)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
