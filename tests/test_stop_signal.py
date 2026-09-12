"""A stop signal arriving during a buffered stdout read must preserve the trace."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class BufferedSignalStopTests(unittest.TestCase):
 def test_stop_during_read_drains_without_reentrant_io(self):
  script=r'''
import json,sys,threading,time,os,signal,subprocess
from pathlib import Path
import harness_runner as h
h.verify_frozen=lambda:'fixture'
h.server_metadata=lambda cfg:{'context_window':4096,'temperature':None,'temperature_source':'fixture'}
real_popen=subprocess.Popen
child="import signal,time,json,sys\ndef stop(*_):\n print('y'*1_000_000,flush=True)\n sys.stderr.write('x'*1_000_000);sys.stderr.flush()\n print(json.dumps({'shutdown':'drained'}),flush=True)\n sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\nprint(json.dumps({'event':{'type':'turn_start'}}),flush=True)\ntime.sleep(30)\n"
def provider(*args,**kwargs):return real_popen([sys.executable,'-u','-c',child],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
h.subprocess.Popen=provider
ready=threading.Event()
def observed_print(*args,**kwargs):
 print(*args,**kwargs)
 if args and args[0]=='MODEL Pi turn: waiting for response':ready.set()
h.print=observed_print
def interrupt_read():
 assert ready.wait(5),'harness never began reading the fixture response'
 time.sleep(.1);os.kill(os.getpid(),signal.SIGTERM)
threading.Thread(target=interrupt_read,daemon=True).start()
try:
 h.run({'id':'fixture','kind':'mcq','prompt':'fixture','options':[{'id':'001','text':'fixture'}]}, {'base_url':'http://unused.invalid/v1','model':'fixture','max_tokens':1024},Path(sys.argv[1]),False)
except SystemExit as e:
 assert e.code==130,e.code
 proof=json.loads(h.diagnostics.source(h.ROOT,Path(sys.argv[1]),'interrupted-pi-trace.json').read_text())
 assert not (Path(sys.argv[1])/'partial-pi-trace.jsonl').exists()
 assert not (Path(sys.argv[1])/'interrupted-pi-trace.json').exists()
 assert any(x.get('shutdown')=='drained' for x in proof['trace']),proof
 assert len(proof['stderr'])==1_000_000,len(proof['stderr'])
 assert any(len(item.get('pi_output',''))==1_000_000 for item in proof['trace'])
 print('stop trace drained and preserved')
else:raise AssertionError('expected interrupted exit')
'''
  with tempfile.TemporaryDirectory() as d:
   result=subprocess.run([sys.executable,'-c',script,d],cwd=ROOT,text=True,capture_output=True,timeout=10)
  self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
  self.assertIn('stop trace drained and preserved',result.stdout)
if __name__=='__main__':unittest.main()
