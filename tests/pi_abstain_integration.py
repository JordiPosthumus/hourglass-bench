import os,sys,json,threading,tempfile,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from http.server import HTTPServer,BaseHTTPRequestHandler
import harness_runner
os.environ['HOURGLASS_SCORING_POLICY']='net-hour-v1'
requests=[]
steps=[('write',{'path':'proof.txt','content':'before'}),('edit',{'path':'proof.txt','edits':[{'oldText':'before','newText':'after'}]}),('read',{'path':'proof.txt'}),('read',{'path':'/etc/passwd'}),('bash',{'command':'cat proof.txt','timeout':0.001}),('answer_question',{'abstain':True})]
class H(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'models':[{'key':'fixture','max_context_length':262144,'loaded_instances':[{'id':'fixture','config':{'context_length':262144,'temperature':0.73}}]}]}).encode())
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
  name,args=steps[min(len(requests)-1,len(steps)-1)]
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  for delta,finish in [({'role':'assistant','reasoning_content':'Fixture reasoning.','tool_calls':[{'index':0,'id':'call_1','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},None),({},'tool_calls')]:
   self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':finish}],'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})+'\n\n').encode())
  self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
server=HTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory() as d:
 try:
  trace,metrics,answer,_=harness_runner.run({'id':'T','kind':'mcq','prompt':'Pick 001','options':[{'id':'001','text':'one'},{'id':'002','text':'two'}],'max_turns':10},{'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','max_tokens':262144,'temperature':1,'extra':{'temperature':2}},pathlib.Path(d),True)
  print(json.dumps({'metrics':metrics,'answer':answer,'requests':len(requests)}))
  assert answer=={'abstain':True}
  assert 'loses 1 point' in str(requests[0]['messages'])
  assert any('abstain' in str(t) for t in requests[0]['tools'])
  assert (pathlib.Path(d)/'proof.txt').read_text()=='after'
  events=[i['event'] for i in trace if 'event' in i]
  results=[e for e in events if e['type']=='tool_execution_end']
  assert not results[0].get('isError') and not results[1].get('isError')
  assert results[3].get('isError'),results[3]
  assert not results[4].get('isError'),results[4]
  assert requests and all('temperature' not in r and r['max_tokens']==262144 for r in requests)
  assert metrics['temperature']==0.73
  assert metrics['thinking_settings']['pi_thinking_level']=='medium'
  assert metrics['thinking_settings']['server_effective_reasoning'] is None
  assert metrics['thinking_settings']['thinking_content_observed'] is True
  assert all(x['pi_thinking_level']=='medium' for x in metrics['requested_settings'])
  assert all('reasoning_effort' not in r and 'reasoning' not in r for r in requests)
  assert {'read','bash','edit','write','answer_question'} <= {t['function']['name'] for t in requests[0]['tools']}
 except Exception as e:
  print(str(e));print(json.dumps(getattr(e,'trace',[]),indent=2));raise
server.shutdown()
