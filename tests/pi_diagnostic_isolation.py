"""Native fake-provider proof: task IO works; all four tools deny diagnostics."""
import io,json,os,pathlib,shlex,subprocess,sys,tempfile,threading,time
from http.server import HTTPServer,BaseHTTPRequestHandler
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import diagnostics,harness_runner,hourglass
ROOT=pathlib.Path(__file__).resolve().parents[1]
SECRET='PRIVATE_DIAGNOSTIC_CANARY_7a5493'
requests=[];steps=[]
class H(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(b'{"models":[{"key":"fixture","max_context_length":262144,"loaded_instances":[{"id":"fixture","config":{"context_length":262144,"temperature":0.73}}]}]}')
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
  name,args=steps[min(len(requests)-1,len(steps)-1)]
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  delta={'role':'assistant','tool_calls':[{'index':0,'id':'call_'+str(len(requests)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
  for d,f in [(delta,None),({},'tool_calls')]:
   self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':d,'finish_reason':f}],'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})+'\n\n').encode())
  self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
server=HTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 for sandboxed in (True,False):
  requests.clear()
  with tempfile.TemporaryDirectory(prefix='hourglass-diagnostic-fixture-') as temp:
   work=pathlib.Path(temp);private=diagnostics.directory(ROOT,work,create=True)
   (work/'fixture.txt').write_text('TASK_FILE_IS_ACCESSIBLE')
   # A task may legitimately use the old filename: no filename blacklist.
   (work/'partial-pi-trace.jsonl').write_text('TASK_OWNED_SAME_NAME')
   secret=private/'probe-secret.txt';secret.write_text(SECRET)
   (work/'trace-link').symlink_to(secret)
   steps[:]=[
    ('read',{'path':'fixture.txt'}),
    ('write',{'path':'written.txt','content':'before'}),
    ('edit',{'path':'written.txt','edits':[{'oldText':'before','newText':'after'}]}),
    ('bash',{'command':'cat fixture.txt written.txt'}),
    ('read',{'path':'partial-pi-trace.jsonl'}),
    ('read',{'path':str(secret)}),
    ('write',{'path':str(secret),'content':'overwritten'}),
    ('edit',{'path':str(secret),'edits':[{'oldText':'PRIVATE','newText':'changed'}]}),
    ('read',{'path':'trace-link'}),
    ('bash',{'command':'cat '+shlex.quote(str(secret))}),
    ('bash',{'command':'cat trace-link'}),
    ('bash',{'command':'python3 -c '+shlex.quote('print(open('+repr(str(secret))+').read())')}),
    ('bash',{'command':'ln '+shlex.quote(str(secret))+' attempted-hardlink && cat attempted-hardlink'}),
    ('bash',{'command':'cat '+shlex.quote(str(private/'agent/request.json'))}),
    ('bash',{'command':'cat '+shlex.quote(str(private/'partial-pi-trace.jsonl'))}),
    ('answer_question',{'option':'001'}),
   ]
   started=time.monotonic()
   trace,metrics,answer,_=harness_runner.run({'id':'fixture','kind':'mcq','prompt':'Complete the fixture.','options':[{'id':'001','text':'one'}]},
    {'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','max_tokens':262144},work,sandboxed)
   ends=[x['event'] for x in trace if x.get('event',{}).get('type')=='tool_execution_end']
   assert answer=={'option':'001'} and (work/'written.txt').read_text()=='after'
   assert not any(e.get('isError') for e in ends[:5]),ends[:5]
   assert all(e.get('isError') for e in ends[5:15]),ends[5:15]
   assert secret.read_text()==SECRET
   tool_responses=[m for request in requests for m in request.get('messages',[]) if m.get('role')=='tool']
   assert SECRET not in json.dumps(tool_responses)
   assert 'TASK_OWNED_SAME_NAME' in json.dumps(tool_responses)
   assert (private/'partial-pi-trace.jsonl').stat().st_size>0
   assert list((private/'agent/sessions').rglob('*.jsonl'))
   assert (private/'agent/request.json').exists()
   assert (work/'partial-pi-trace.jsonl').read_text()=='TASK_OWNED_SAME_NAME'
   assert not (work/'interrupted-pi-trace.json').exists()
   assert all(r['max_tokens']==262144 and 'temperature' not in r for r in requests)
   assert metrics['context_window']==262144
   artifact=work/'human-artifacts';artifact.mkdir();diagnostics.publish(ROOT,work,artifact)
   assert (artifact/'partial-pi-trace.jsonl').read_bytes()==(private/'partial-pi-trace.jsonl').read_bytes()
   assert json.loads((artifact/'diagnostics.json').read_text())['diagnostic_isolation']==diagnostics.POLICY
   print(json.dumps({'sandboxed':sandboxed,'tool_calls':len(ends),'blocked_probes':10,'duration_s':round(time.monotonic()-started,3),'context':metrics['context_window'],'output_limit':262144,'policy':metrics['diagnostic_isolation']}))
finally:server.shutdown()
