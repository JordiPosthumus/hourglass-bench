"""Run directly: exercises the actual stop API helper against native Pi bash."""
import json,os,pathlib,subprocess,sys,tempfile,threading,time
from http.server import HTTPServer,BaseHTTPRequestHandler
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import web
class H(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(b'{"models":[{"key":"fixture","max_context_length":262144}]}')
 def do_POST(self):
  self.rfile.read(int(self.headers['Content-Length']))
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  delta={'role':'assistant','tool_calls':[{'index':0,'id':'call1','type':'function','function':{'name':'bash','arguments':json.dumps({'command':'echo $$ > tool.pid; sleep 30; echo survived > survived.txt'})}}]}
  for d,f in [(delta,None),({},'tool_calls')]:self.wfile.write(('data: '+json.dumps({'id':'f','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':d,'finish_reason':f}]})+'\n\n').encode())
  self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
server=HTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory() as d:
 task={'kind':'mcq','prompt':'wait','mode':'numeric','max_turns':3}
 cfg={'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','max_tokens':262144}
 code='import pathlib,harness_runner;harness_runner.run('+repr(task)+','+repr(cfg)+',pathlib.Path('+repr(d)+'),True)'
 proc=subprocess.Popen([sys.executable,'-c',code],cwd=web.ROOT,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  deadline=time.monotonic()+15
  while not (pathlib.Path(d)/'tool.pid').exists():
   if proc.poll() is not None:raise AssertionError(proc.communicate())
   if time.monotonic()>deadline:raise AssertionError('Native bash did not start')
   time.sleep(.05)
  pid=int((pathlib.Path(d)/'tool.pid').read_text());job={'id':'stop-fixture','_process':proc};web.running.append(job)
  started=time.monotonic();web.stop_job({'job':'stop-fixture'});proc.wait(timeout=10)
  assert job['stop_requested'];assert not (pathlib.Path(d)/'survived.txt').exists()
  try:os.kill(pid,0)
  except ProcessLookupError:pass
  else:raise AssertionError('Bash still alive after stop')
  print('Stop cancelled Pi and native bash in',round(time.monotonic()-started,3),'seconds')
 finally:
  web.running[:]=[j for j in web.running if j.get('id')!='stop-fixture']
  if proc.poll() is None:os.killpg(proc.pid,15)
server.shutdown()
