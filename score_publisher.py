"""Local preview and explicit GitHub publication of aggregate-only files."""
import argparse
import base64
import json
import re
import secrets
import subprocess
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import score_report
import hardware_records

PAGE='''<!doctype html><meta charset="utf-8"><title>Hourglass score preview</title><style>body{background:#101722;color:#eaf0fa;font:16px system-ui;max-width:1400px;margin:32px auto;padding:0 28px}input,button,select{font:inherit;padding:10px;border-radius:7px;border:1px solid #627080}input,select{background:#172231;color:#eaf0fa;min-width:0}button{cursor:pointer}button:disabled{opacity:.5}img{display:block;width:100%;height:auto;border:1px solid #2c394a;border-radius:14px;margin:20px 0}pre{white-space:pre-wrap}a{color:#74e5c4}fieldset{border:1px solid #39495b;border-radius:12px;padding:20px;margin:24px 0}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}label{display:flex;flex-direction:column;gap:6px;font-size:14px}.actions{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-top:20px}.help{font-size:13px;color:#b7c5d5}h2{font-size:20px}</style>
<h1>Record & publish score</h1><p id="summary"></p>
<fieldset id="hardware"><legend>Inference hardware for this run</legend><p class="help">Choose the machine that ran the model. Save hardware to update the local record and regenerate the report before publishing. This does not change model settings.</p><div class="fields"><label>Recorded machine<select id="machine"></select></label><label>Machine label<input id="label" placeholder="M3 Ultra desktop / Spark workstation"></label><label>Chip / CPU platform<input id="chip"></label><label>Memory (GiB)<input id="memory" type="number" min="0" step="any"></label><label>CPU cores<input id="cores" type="number" min="1" step="1"></label><label>GPU and configuration<input id="gpu" placeholder="GPU name, count and optional core details"></label></div><div class="actions"><button id="saveHardware" disabled>Save hardware & refresh preview</button><span id="hardwareStatus" class="help"></span></div></fieldset>
<h2>Weighted score over time</h2><p class="help">One line per compatible model on this machine. Steps mark correct answers.</p><img id="graph" alt="Weighted score over active time">
<h2>Accuracy × token efficiency × speed</h2><p class="help">Up is more accurate. Right uses fewer output tokens. Larger bubbles mean more scored answers per active minute.</p><img id="quadrants" alt="Accuracy token efficiency and speed quadrant chart">
<p id="files"></p><p class="help">Review these six aggregate files. Questions, answers and traces stay private. Hardware edits require a refreshed preview.</p>
<div class="actions"><label>GitHub repository<input id="repo" placeholder="owner/repository"></label><button id="publish" disabled>Publish these files to GitHub</button></div><p id="status" role="status"></p>
<script>
const $=id=>document.getElementById(id),job=new URLSearchParams(location.search).get('job');let token,machines=[],dirty=false;const names=['README.md','comparison.svg','quadrants.svg','comparison.json','report.json','score.svg'];
function fill(h){$('label').value=h.label||'';$('chip').value=h.chip||'';$('memory').value=h.memory_bytes?h.memory_bytes/2**30:'';$('cores').value=h.cpu_cores||'';$('gpu').value=Array.isArray(h.gpu)?h.gpu.map(g=>g.model+(g.cores?' · '+g.cores+' cores':'')).join('; '):(h.gpu||'')}
function changed(){dirty=true;$('publish').disabled=true;$('hardwareStatus').textContent='Save the hardware details to update this report.'}
async function init(){try{const r=await fetch('/api/preview?job='+encodeURIComponent(job));const d=await r.json();if(!r.ok)throw Error(d.error);token=d.token;machines=d.machines;$('machine').replaceChildren(...machines.map(h=>new Option(h.label,h.machine_key)),new Option('Add a different physical machine','new'));$('machine').value=d.hardware.source==='unknown'?'new':d.hardware.machine_key;fill(d.hardware.source==='unknown'?{}:d.hardware);$('graph').src='/file/'+token+'/comparison.svg';$('quadrants').src='/file/'+token+'/quadrants.svg';$('files').innerHTML=names.map(n=>'<a target="_blank" href="/file/'+token+'/'+n+'">'+n+'</a>').join(' · ');if(!$('repo').value)$('repo').value=d.repo;$('summary').textContent=d.summary;$('hardwareStatus').textContent='Saved hardware source: '+d.hardware.source;dirty=false;$('saveHardware').disabled=false;$('publish').disabled=d.hardware.source==='unknown'}catch(e){$('status').textContent=e.message}}
$('machine').onchange=()=>{fill(machines.find(h=>h.machine_key===$('machine').value)||{});changed()};for(const id of ['label','chip','memory','cores','gpu'])$(id).oninput=changed;
$('saveHardware').onclick=async()=>{const b=$('saveHardware');b.disabled=true;try{const r=await fetch('/api/hardware',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,hardware:{machine_key:$('machine').value,label:$('label').value,chip:$('chip').value,memory_gib:$('memory').value,cpu_cores:$('cores').value,gpu:$('gpu').value}})});const d=await r.json();if(!r.ok)throw Error(d.error);await init();$('hardwareStatus').textContent='Hardware saved for this run. The graphs and GitHub files now use it.'}catch(e){$('status').textContent=e.message}finally{b.disabled=false}};
$('publish').onclick=async()=>{const b=$('publish');b.disabled=true;$('status').textContent='Publishing reviewed files…';try{if(dirty)throw Error('Save hardware and refresh the preview first.');const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,repo:$('repo').value})});const d=await r.json();if(!r.ok)throw Error(d.error);$('status').textContent='Published: ';const a=document.createElement('a');a.href=d.url;a.textContent=d.url;$('status').append(a)}catch(e){$('status').textContent=e.message;b.disabled=dirty}};init();
</script>
'''


def gh(path,payload=None):
    args=['gh','api',path]
    if payload is not None:args+=['--method','POST','--input','-']
    proc=subprocess.run(args,input=json.dumps(payload) if payload is not None else None,text=True,capture_output=True,timeout=60)
    if proc.returncode:raise ValueError('GitHub request failed. Check gh authentication, repository access and branch protection.')
    return json.loads(proc.stdout)


def publish(repo,token,files):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Enter owner/repository.')
    meta=gh('repos/'+repo);branch=meta['default_branch'];branchpath=urllib.parse.quote(branch,safe='')
    head=gh(f'repos/{repo}/git/ref/heads/{branchpath}')['object']['sha']
    tree=gh(f'repos/{repo}/git/commits/{head}')['tree']['sha']
    folder='reports/'+token
    entries=[]
    for name,body in files.items():
        blob=gh(f'repos/{repo}/git/blobs',{'content':base64.b64encode(body.encode()).decode(),'encoding':'base64'})
        entries.append({'path':folder+'/'+name,'mode':'100644','type':'blob','sha':blob['sha']})
    updated=gh(f'repos/{repo}/git/trees',{'base_tree':tree,'tree':entries})
    commit=gh(f'repos/{repo}/git/commits',{'message':'Publish Hourglass Bench score','tree':updated['sha'],'parents':[head]})
    # A non-forced ref update refuses concurrent branch changes.
    proc=subprocess.run(['gh','api',f'repos/{repo}/git/refs/heads/{branchpath}','--method','PATCH','--input','-'],input=json.dumps({'sha':commit['sha'],'force':False}),text=True,capture_output=True,timeout=60)
    if proc.returncode:raise ValueError('Branch update refused. Refresh the preview and retry.')
    return f'https://github.com/{repo}/tree/{commit["sha"]}/{folder}'


def server(root,port,source_port,repo=''):
    previews={};lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data,kind='application/json',status=200):
            data=data.encode();self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            try:
                if self.headers.get('Host')!=f'127.0.0.1:{port}':raise ValueError('Invalid host.')
                u=urllib.parse.urlparse(self.path)
                if u.path=='/':self.send(PAGE,'text/html; charset=utf-8');return
                if u.path in ('/api/preview','/chart.svg'):
                    jid=urllib.parse.parse_qs(u.query).get('job',[''])[0]
                    if not jid.isalnum():raise ValueError('Invalid run.')
                    with urllib.request.urlopen(f'http://127.0.0.1:{source_port}/api/state',timeout=15) as response:state=json.load(response)
                    jobs=sum(state['jobs'].values(),[]);job=next(j for j in jobs if j['id']==jid)
                    manifest=json.loads((root/'evaluations'/(jid+'.json')).read_text())
                    files=score_report.build(root,job,state['results'],manifest)
                    reports=[json.loads(files['report.json'])];seen={job['model']}
                    for other in sorted(jobs,key=lambda j:j.get('created') or 0,reverse=True):
                        if other['model'] in seen or not other.get('started'):continue
                        try:
                            saved=json.loads((root/'evaluations'/(other['id']+'.json')).read_text())
                            candidate=json.loads(score_report.build(root,other,state['results'],saved)['report.json'])
                        except (ValueError,KeyError,FileNotFoundError):continue
                        reference=reports[0]
                        if any(candidate.get(k)!=reference.get(k) for k in ('bank_fingerprint','scoring','timing_policy','benchmark_version','machine_key')):continue
                        reports.append(candidate);seen.add(other['model'])
                    files.update(score_report.comparison(reports))
                    files.update(score_report.quadrants(reports))
                    files['README.md']=files['README.md'].replace('![Score graph](score.svg)','![Models over time](comparison.svg)\n\n[Individual score graph](score.svg) · [Comparison data](comparison.json)\n\n![Accuracy, token efficiency and speed](quadrants.svg)')
                    if u.path=='/chart.svg':
                        self.send(files['comparison.svg'],'image/svg+xml');return
                    machines={}
                    for known in jobs:
                        saved=json.loads((root/'evaluations'/(known['id']+'.json')).read_text())
                        machine=hardware_records.recorded(root,saved)
                        if machine.get('source')!='unknown':machines[machine['machine_key']]=machine
                    token=secrets.token_hex(12)
                    with lock:
                        if len(previews)>100:previews.pop(next(iter(previews)))
                        previews[token]={'files':files,'published':None,'job':jid,'machines':list(machines),'hardware_revision':hardware_records.revision(reports[0]['hardware'])}
                    report=json.loads(files['report.json'])
                    self.send(json.dumps({'token':token,'repo':repo,'hardware':report['hardware'],'machines':list(machines.values()),'summary':f"{report['hardware']['label']}\n{report['weighted_points']:.2f} points · {report['raw_correct']} correct · {report['state']}\nThis publishes the snapshot shown above, including compatible model comparisons."}));return
                if u.path.startswith('/file/'):
                    _,_,token,name=u.path.split('/');files=previews[token]['files']
                    self.send(files[name],{'score.svg':'image/svg+xml','comparison.svg':'image/svg+xml','quadrants.svg':'image/svg+xml','comparison.json':'application/json','report.json':'application/json','README.md':'text/plain; charset=utf-8'}[name]);return
                self.send('{}',status=404)
            except Exception as e:self.send(json.dumps({'error':str(e)}),status=400)
        def do_POST(self):
            try:
                origin=f'http://127.0.0.1:{port}'
                if self.headers.get('Host')!=f'127.0.0.1:{port}' or self.headers.get('Origin')!=origin:raise ValueError('Open the local preview page to publish.')
                if self.path not in ('/api/publish','/api/hardware'):raise ValueError('Unknown action.')
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=4096:raise ValueError('Invalid request size.')
                data=json.loads(self.rfile.read(size))
                with lock:
                    preview=previews[data['token']]
                    manifest=json.loads((root/'evaluations'/(preview['job']+'.json')).read_text())
                    current=hardware_records.recorded(root,manifest)
                    if self.path=='/api/hardware':
                        record=hardware_records.save_user_record(root,manifest,data['hardware'],preview['machines'],preview['hardware_revision'])
                        self.send(json.dumps({'ok':True,'hardware':record}));return
                    if hardware_records.revision(current)!=preview['hardware_revision']:raise ValueError('Hardware changed. Refresh the preview before publishing.')
                    if current.get('source')=='unknown':raise ValueError('Record the inference hardware before publishing.')
                    url=preview['published']
                    if not url:url=publish(data['repo'],data['token'],preview['files']);preview['published']=url
                self.send(json.dumps({'url':url}))
            except Exception as e:self.send(json.dumps({'error':str(e)}),status=400)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def start(root,source_port,repo=''):
    try:s=server(root,source_port+20,source_port,repo)
    except OSError:return False
    threading.Thread(target=s.serve_forever,daemon=True).start();return True

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-port',type=int,default=8788);p.add_argument('--repo',default='');a=p.parse_args()
    server(Path(__file__).resolve().parent,a.source_port+20,a.source_port,a.repo).serve_forever()
