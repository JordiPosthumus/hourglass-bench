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
import results_history

PAGE='''<!doctype html><meta charset="utf-8"><title>Hourglass score preview</title><style>body{background:#101722;color:#eaf0fa;font:16px system-ui;max-width:1400px;margin:32px auto;padding:0 28px}input,button,select{font:inherit;padding:10px;border-radius:7px;border:1px solid #627080}input,select{background:#172231;color:#eaf0fa;min-width:0}button{cursor:pointer}button:disabled{opacity:.5}img{display:block;width:100%;height:auto;border:1px solid #2c394a;border-radius:14px;margin:20px 0}pre{white-space:pre-wrap}a{color:#74e5c4}fieldset{border:1px solid #39495b;border-radius:12px;padding:20px;margin:24px 0}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}label{display:flex;flex-direction:column;gap:6px;font-size:14px}.actions{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-top:20px}.help{font-size:13px;color:#b7c5d5}h2{font-size:20px}</style>
<h1>Record & publish score</h1><p id="summary"></p>
<fieldset id="hardware"><legend>Hardware for this run</legend><label>Hardware<input id="label" maxlength="160" placeholder="Spark 2 · NVIDIA GB10 · 128 GB"></label><div class="actions"><button id="saveHardware" disabled>Save hardware</button><span id="hardwareStatus" class="help"></span></div></fieldset>
<fieldset><legend>Public experiment labels</legend><p class="help">Use the same model family across revisions. These fields will be published; record the revision, quantization, engine, harness and parameters you actually used.</p><div class="fields"><label>Model Family<input id="exp_model_family" maxlength="500"></label><label>Model Revision<input id="exp_model_revision" maxlength="500"></label><label>Configuration<input id="exp_configuration" maxlength="500"></label><label>Quantization<input id="exp_quantization" maxlength="500"></label><label>Inference Engine<input id="exp_inference_engine" maxlength="500"></label><label>Harness Revision<input id="exp_harness_revision" maxlength="500"></label><label>Parameters<input id="exp_parameters" maxlength="500"></label></div><div class="actions"><button id="saveExperiment">Save experiment labels</button></div></fieldset><label>Compare<select id="scope"><option value="same">Same hardware</option><option value="all">All hardware</option></select></label><p class="help">Matching question bank and scoring rules. Selected run plus the latest matching run for each model and machine.</p><h2>Score ranking</h2><img id="ranking" alt="Models ranked by weighted score with hardware labels"><h2>Weighted score over time</h2><p class="help">Each step marks points earned at completion. AUC is calculated from this exact step graph.</p><img id="graph" alt="Weighted score over active time">
<h2>Accuracy × token efficiency × speed</h2><p class="help">Up is more accurate. Right uses fewer output tokens. Larger bubbles mean more scored answers per active minute.</p><img id="quadrants" alt="Accuracy token efficiency and speed quadrant chart">
<p id="files"></p><p class="help">Review these aggregate files. Publishing also updates the repository Results index and model-history charts from published snapshots. Questions, answers and traces stay private. Hardware edits require a refreshed preview.</p>
<div class="actions"><label>GitHub repository<input id="repo" placeholder="owner/repository"></label><button id="publish" disabled>Publish these files to GitHub</button></div><p id="status" role="status"></p>
<script>
const $=id=>document.getElementById(id),job=new URLSearchParams(location.search).get('job');let token,machines=[],dirty=false,hardwareDirty=false,experimentDirty=false;const names=['README.md','comparison.svg','quadrants.svg','ranking.svg','comparison.json','report.json','score.svg'];
function fill(h){$('label').value=h.label||''}
function changed(){dirty=true;hardwareDirty=true;$('publish').disabled=true;$('hardwareStatus').textContent='Save the hardware details to update this report.'}
$('scope').value=new URLSearchParams(location.search).get('scope')==='all'?'all':'same';
$('scope').onchange=()=>{if(dirty){$('status').textContent='Save hardware before changing the comparison.';return}init()};
async function init(){try{$('publish').disabled=true;const r=await fetch('/api/preview?job='+encodeURIComponent(job)+'&scope='+$('scope').value);const d=await r.json();if(!r.ok)throw Error(d.error);token=d.token;machines=d.machines;fill(d.hardware.source==='unknown'?{}:d.hardware);for(const k of experimentFields)$('exp_'+k).value=d.experiment[k]||'';$('ranking').src='/file/'+token+'/ranking.svg';$('graph').src='/file/'+token+'/comparison.svg';$('quadrants').src='/file/'+token+'/quadrants.svg';$('files').innerHTML=names.map(n=>'<a target="_blank" href="/file/'+token+'/'+n+'">'+n+'</a>').join(' · ');if(!$('repo').value)$('repo').value=d.repo;$('summary').textContent=d.summary;$('hardwareStatus').textContent='Saved hardware source: '+d.hardware.source;dirty=false;hardwareDirty=false;experimentDirty=false;$('saveHardware').disabled=false;$('publish').disabled=d.hardware.source==='unknown'}catch(e){$('status').textContent=e.message}}
const experimentFields=['model_family','model_revision','configuration','quantization','inference_engine','harness_revision','parameters'];
for(const k of experimentFields)$('exp_'+k).oninput=()=>{dirty=true;experimentDirty=true;$('publish').disabled=true;$('status').textContent='Save experiment labels before publishing.'};
async function saveDetails(){
 $('saveHardware').disabled=true;$('saveExperiment').disabled=true;
 try{const payload={token};if(hardwareDirty)payload.hardware={label_only:true,label:$('label').value};if(experimentDirty)payload.experiment=Object.fromEntries(experimentFields.map(k=>[k,$('exp_'+k).value]));
 const r=await fetch('/api/details',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw Error(d.error);await init();$('status').textContent='Hardware and experiment labels saved for this report.'}catch(e){$('status').textContent=e.message}finally{$('saveHardware').disabled=false;$('saveExperiment').disabled=false}
}
$('saveExperiment').onclick=saveDetails;
$('label').oninput=changed;
$('saveHardware').onclick=saveDetails;
$('publish').onclick=async()=>{const b=$('publish');b.disabled=true;$('status').textContent='Publishing reviewed files…';try{if(dirty)throw Error('Save hardware and refresh the preview first.');const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,repo:$('repo').value})});const d=await r.json();if(!r.ok)throw Error(d.error);$('status').textContent='Published: ';const a=document.createElement('a');a.href=d.url;a.textContent=d.url;$('status').append(a)}catch(e){$('status').textContent=e.message;b.disabled=dirty}};init();
</script>
'''


def gh(path,payload=None):
    args=['gh','api',path]
    if payload is not None:args+=['--method','POST','--input','-']
    proc=subprocess.run(args,input=json.dumps(payload) if payload is not None else None,text=True,capture_output=True,timeout=60)
    if proc.returncode:raise ValueError('GitHub request failed. Check gh authentication, repository access and branch protection.')
    return json.loads(proc.stdout)


def published_catalog(repo,head):
    path=f'repos/{repo}/contents/reports/catalog.json?ref={head}'
    proc=subprocess.run(['gh','api',path],text=True,capture_output=True,timeout=60)
    if proc.returncode:
        if '(HTTP 404)' in proc.stderr:return []
        raise ValueError('Could not read the published results catalog. No history was overwritten.')
    doc=json.loads(proc.stdout);entries=json.loads(base64.b64decode(doc['content']))
    if not isinstance(entries,list):raise ValueError('Invalid published results catalog.')
    for entry in entries:
        if not isinstance(entry,dict) or not re.fullmatch(r'[a-zA-Z0-9_-]+',entry.get('report_folder','')):raise ValueError('Invalid catalog snapshot path.')
    return entries


def publish(repo,token,files):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Enter owner/repository.')
    meta=gh('repos/'+repo);branch=meta['default_branch'];branchpath=urllib.parse.quote(branch,safe='')
    head=gh(f'repos/{repo}/git/ref/heads/{branchpath}')['object']['sha']
    tree=gh(f'repos/{repo}/git/commits/{head}')['tree']['sha']
    folder='reports/'+token
    entries=[]
    additions={folder+'/'+name:body for name,body in files.items()}
    report=json.loads(files.get('report.json','{}'))
    if report.get('run_key'):
        additions.update(results_history.catalog_files(published_catalog(repo,head),report,token))
    for name,body in additions.items():
        blob=gh(f'repos/{repo}/git/blobs',{'content':base64.b64encode(body.encode()).decode(),'encoding':'base64'})
        entries.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
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
                    query=urllib.parse.parse_qs(u.query)
                    scope=query.get('scope',['same'])[0]
                    if scope not in ('same','all'):raise ValueError('Invalid comparison scope.')
                    view=query.get('view',['comparison'])[0]
                    if view not in ('comparison','ranking','quadrants'):raise ValueError('Invalid chart view.')
                    jid=query.get('job',[''])[0]
                    if not jid.isalnum():raise ValueError('Invalid run.')
                    with urllib.request.urlopen(f'http://127.0.0.1:{source_port}/api/state',timeout=15) as response:state=json.load(response)
                    jobs=sum(state['jobs'].values(),[]);job=next(j for j in jobs if j['id']==jid)
                    manifest=json.loads((root/'evaluations'/(jid+'.json')).read_text())
                    files=score_report.build(root,job,state['results'],manifest)
                    reports=[json.loads(files['report.json'])];seen={(job['model'],reports[0]['machine_key'])}
                    for other in sorted(jobs,key=lambda j:j.get('created') or 0,reverse=True):
                        if other['id']==jid or not other.get('started'):continue
                        try:
                            saved=json.loads((root/'evaluations'/(other['id']+'.json')).read_text())
                            candidate=json.loads(score_report.build(root,other,state['results'],saved)['report.json'])
                        except (ValueError,KeyError,FileNotFoundError):continue
                        reference=reports[0]
                        identity=(other['model'],candidate['machine_key'])
                        if identity in seen or len(score_report.compatible_reports([reference,candidate],scope))!=2:continue
                        reports.append(candidate);seen.add(identity)
                    files.update(score_report.comparison(reports,scope))
                    files.update(score_report.quadrants(reports,scope))
                    files.update(score_report.ranking(reports,scope))
                    files['README.md']+='\nComparison scope: '+('all hardware' if scope=='all' else 'same hardware')+'. Selected run plus latest matching run per model and machine; model settings may differ.\n'
                    files['README.md']=files['README.md'].replace('![Score graph](score.svg)','![Score ranking](ranking.svg)\n\n![Models over time](comparison.svg)\n\n[Individual score graph](score.svg) · [Comparison data](comparison.json)\n\n![Accuracy, token efficiency and speed](quadrants.svg)')
                    if u.path=='/chart.svg':
                        self.send(files[view+'.svg'],'image/svg+xml');return
                    machines={}
                    for known in jobs:
                        saved=json.loads((root/'evaluations'/(known['id']+'.json')).read_text())
                        machine=hardware_records.recorded(root,saved)
                        if machine.get('source')!='unknown':machines[machine['machine_key']]=machine
                    token=secrets.token_hex(12)
                    with lock:
                        if len(previews)>100:previews.pop(next(iter(previews)))
                        previews[token]={'files':files,'published':None,'job':jid,'machines':list(machines),'experiment_revision':results_history.revision(reports[0].get('experiment',{})),'hardware_revision':hardware_records.revision(reports[0]['hardware'])}
                    report=json.loads(files['report.json'])
                    self.send(json.dumps({'token':token,'repo':repo,'experiment':report.get('experiment',{}),'hardware':report['hardware'],'machines':list(machines.values()),'summary':f"{report['hardware']['label']}\n{report['weighted_points']:.2f} points · {report['raw_correct']} correct · {report['state']}\nThis publishes the snapshot shown above, including compatible model comparisons."}));return
                if u.path.startswith('/file/'):
                    _,_,token,name=u.path.split('/');files=previews[token]['files']
                    self.send(files[name],{'score.svg':'image/svg+xml','comparison.svg':'image/svg+xml','ranking.svg':'image/svg+xml','quadrants.svg':'image/svg+xml','comparison.json':'application/json','report.json':'application/json','README.md':'text/plain; charset=utf-8'}[name]);return
                self.send('{}',status=404)
            except Exception as e:self.send(json.dumps({'error':str(e)}),status=400)
        def do_POST(self):
            try:
                origin=f'http://127.0.0.1:{port}'
                if self.headers.get('Host')!=f'127.0.0.1:{port}' or self.headers.get('Origin')!=origin:raise ValueError('Open the local preview page to publish.')
                if self.path not in ('/api/publish','/api/hardware','/api/experiment','/api/details'):raise ValueError('Unknown action.')
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=4096:raise ValueError('Invalid request size.')
                data=json.loads(self.rfile.read(size))
                with lock:
                    preview=previews[data['token']]
                    manifest=json.loads((root/'evaluations'/(preview['job']+'.json')).read_text())
                    current=hardware_records.recorded(root,manifest)
                    if self.path=='/api/details':
                        if results_history.revision(results_history.load(root,preview['job']))!=preview['experiment_revision']:raise ValueError('Experiment labels changed. Refresh before saving.')
                        if hardware_records.revision(current)!=preview['hardware_revision']:raise ValueError('Hardware changed. Refresh before saving.')
                        experiment=results_history.clean(data['experiment']) if 'experiment' in data else None
                        if 'hardware' in data:hardware_records.save_user_record(root,manifest,data['hardware'],preview['machines'],preview['hardware_revision'])
                        if experiment is not None:results_history.save(root,preview['job'],experiment)
                        self.send(json.dumps({'ok':True}));return
                    if self.path=='/api/experiment':
                        value=results_history.save(root,preview['job'],data['experiment'])
                        self.send(json.dumps({'ok':True,'experiment':value}));return
                    if self.path=='/api/hardware':
                        record=hardware_records.save_user_record(root,manifest,data['hardware'],preview['machines'],preview['hardware_revision'])
                        self.send(json.dumps({'ok':True,'hardware':record}));return
                    if results_history.revision(results_history.load(root,preview['job']))!=preview['experiment_revision']:raise ValueError('Experiment labels changed. Refresh the preview before publishing.')
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
