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

PAGE='''<!doctype html><meta charset="utf-8"><title>Publish Hourglass score</title><style>body{background:#101722;color:#eaf0fa;font:16px system-ui;max-width:850px;margin:40px auto}input,button{font:inherit;padding:10px;margin:8px}img{width:100%}pre{white-space:pre-wrap}a{color:#74e5c4}</style><h1>Publish score</h1><p>Review the exact three files before publishing. Reports contain aggregate results; questions, answers and traces are excluded.</p><img id="graph"><p id="files"></p><pre id="summary"></pre><label>GitHub repository <input id="repo" placeholder="owner/repository"></label><button id="publish" disabled>Publish these files to GitHub</button><p id="status"></p><script>
let token;const status=document.getElementById('status');async function init(){try{let r=await fetch('/api/preview?job='+encodeURIComponent(new URLSearchParams(location.search).get('job')));let d=await r.json();if(!r.ok)throw Error(d.error);token=d.token;document.getElementById('repo').value=d.repo;document.getElementById('graph').src='/file/'+token+'/score.svg';document.getElementById('files').innerHTML=['README.md','report.json','score.svg'].map(n=>'<a target="_blank" href="/file/'+token+'/'+n+'">'+n+'</a>').join(' · ');document.getElementById('summary').textContent=d.summary;document.getElementById('publish').disabled=false}catch(e){status.textContent=e.message}}document.getElementById('publish').onclick=async()=>{const b=document.getElementById('publish');b.disabled=true;status.textContent='Publishing…';try{let r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,repo:document.getElementById('repo').value})});let d=await r.json();if(!r.ok)throw Error(d.error);status.textContent='Published: ';let a=document.createElement('a');a.href=d.url;a.textContent=d.url;status.append(a)}catch(e){status.textContent=e.message;b.disabled=false}};init();</script>'''


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
                if u.path=='/api/preview':
                    jid=urllib.parse.parse_qs(u.query).get('job',[''])[0]
                    if not jid.isalnum():raise ValueError('Invalid run.')
                    with urllib.request.urlopen(f'http://127.0.0.1:{source_port}/api/state',timeout=15) as response:state=json.load(response)
                    jobs=sum(state['jobs'].values(),[]);job=next(j for j in jobs if j['id']==jid)
                    manifest=json.loads((root/'evaluations'/(jid+'.json')).read_text())
                    files=score_report.build(root,job,state['results'],manifest);token=secrets.token_hex(12)
                    with lock:
                        if len(previews)>100:previews.pop(next(iter(previews)))
                        previews[token]={'files':files,'published':None}
                    report=json.loads(files['report.json'])
                    self.send(json.dumps({'token':token,'repo':repo,'summary':f"{report['weighted_points']:.2f} points · {report['raw_correct']} correct · {report['state']}\nThis publishes the snapshot shown above."}));return
                if u.path.startswith('/file/'):
                    _,_,token,name=u.path.split('/');files=previews[token]['files']
                    self.send(files[name],{'score.svg':'image/svg+xml','report.json':'application/json','README.md':'text/plain; charset=utf-8'}[name]);return
                self.send('{}',status=404)
            except Exception as e:self.send(json.dumps({'error':str(e)}),status=400)
        def do_POST(self):
            try:
                origin=f'http://127.0.0.1:{port}'
                if self.headers.get('Host')!=f'127.0.0.1:{port}' or self.headers.get('Origin')!=origin:raise ValueError('Open the local preview page to publish.')
                if self.path!='/api/publish':raise ValueError('Unknown action.')
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=2048:raise ValueError('Invalid request size.')
                data=json.loads(self.rfile.read(size))
                with lock:
                    preview=previews[data['token']]
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
