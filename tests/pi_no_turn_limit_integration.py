import sys,json,threading,tempfile,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from http.server import HTTPServer,BaseHTTPRequestHandler
import harness_runner
requests=[]
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
  name,args=('bash',{'command':'true'}) if len(requests)==1 else ('answer_question',{'option':'001'})
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  for delta,finish in [({'role':'assistant','tool_calls':[{'index':0,'id':'fixture','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},None),({},'tool_calls')]:
   self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\n').encode())
  self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
server=HTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with tempfile.TemporaryDirectory() as d:
  trace,metrics,answer,_=harness_runner.run({'id':'fixture','kind':'mcq','prompt':'Fixture','options':[{'id':'001','text':'a'},{'id':'002','text':'b'}],'max_turns':1},{'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','context_window':262144,'max_tokens':262144},pathlib.Path(d),True)
  assert metrics['termination']=='answered',metrics
  assert answer=={'option':'001'} and metrics['tool_calls']==2 and len(requests)==2
  print('Native Pi has no turn cap: continued beyond max_turns=1 and answered on the second request.')
finally:server.shutdown()
