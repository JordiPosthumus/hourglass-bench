#!/usr/bin/env python3
"""Hourglass Bench local console. Stdlib HTTP, one worker, explicit model runs only."""
import json, os, signal, subprocess, threading, time, uuid, sys, mimetypes, shutil
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import urllib.request
import hourglass
import calibration
import run_tracking
import settings_records
import hour_score
import hour_deadline
import attempt_annotations

ROOT = Path(__file__).resolve().parent
TASKS, RESULTS, LOGS = ROOT/'tasks', ROOT/'results', ROOT/'logs'
PORT = int(os.environ.get('HOURGLASS_PORT', '8788'))
queue, running, done = deque(), [], deque(maxlen=100)
condition = threading.Condition()
worker_stop = False
worker_thread = None

def read_json(path, default=None):
    try: return json.loads(Path(path).read_text())
    except (OSError, ValueError): return default

def model_document():
    return read_json(ROOT/'models.json', read_json(ROOT/'models.example.json', {'models':[]}))

def model_names():
    return [m['name'] for m in model_document().get('models', []) if isinstance(m,dict) and isinstance(m.get('name'),str)]

def task_catalog():
    tasks=[]
    for p in sorted(TASKS.glob('*/task.json')):
        t=read_json(p)
        if not t: continue
        section=t.get('section') or ('charts' if t.get('kind')=='chart-vqa' else 'code')
        assets=t.get('assets') or ([t['image']] if t.get('image') else [])
        issues=hourglass.validate_mcq(t) if t.get('kind')=='mcq' else []
        for asset in assets:
            if not (p.parent/asset).is_file():issues.append('Missing asset: '+asset)
        if t.get('source') and not Path(t['source']['repo']).exists():issues.append('Source repository is unavailable')
        tasks.append({'id':p.parent.name,'kind':t.get('kind','fix'),'section':section,
                      'family':t.get('family') or section,'tier':t.get('tier',1),
                      'order_tier':run_tracking.difficulty_tier(t),'tier_estimated':t.get('tier') is None and run_tracking.difficulty_tier(t) is not None,
                      'level':t.get('level'),'title':t.get('title') or p.parent.name,'repeat':t.get('repeat',3),
                      'mode':t.get('mode'),'options':len(t.get('options') or t.get('choices') or []),
                      'vision':hourglass.requires_vision(t),'issues':issues,'task_type':t.get('provenance',{}).get('task_type'),
                      'timeout_s':None,'max_turns':t.get('max_turns',30)})
    return [next(t for t in tasks if t['id']==tid) for tid in ordered_tasks(tasks,[t['id'] for t in tasks])]

def ordered_tasks(catalog, tids):
    lookup={t['id']:t for t in catalog}; buckets={}
    for tid in tids:
        t=lookup[tid];section=t.get('section') or 'code'
        section={'chart':'charts','math_logic':'math'}.get(section,section)
        tier=t.get('order_tier',run_tracking.difficulty_tier(t))
        tier=tier if isinstance(tier,(int,float)) else float('inf')
        buckets.setdefault(tier,{}).setdefault(section,[]).append(tid)
    ordered=[]
    for tier in sorted(buckets):
        sections={section:deque(sorted(ids)) for section,ids in sorted(buckets[tier].items())}
        while any(sections.values()):
            for ids in sections.values():
                if ids:ordered.append(ids.popleft())
    return ordered

def valid_tasks(): return [t['id'] for t in task_catalog()]

def result_rows():
    rows=[]
    try:
        with (RESULTS/'results.jsonl').open() as f:
            for line in f:
                try: rows.append(json.loads(line))
                except ValueError: continue
    except FileNotFoundError: pass
    return attempt_annotations.apply(ROOT,rows)

def saved_manifest(jid):
    if not isinstance(jid,str) or not jid.isalnum():raise ValueError('Invalid run ID.')
    manifest=read_json(ROOT/'evaluations'/(jid+'.json'))
    if not manifest:raise ValueError('This run has no saved question manifest.')
    return manifest

def resume_plan(job, manifest, rows):
    raw=run_tracking.raw_attempts(manifest,rows)
    missing={t['task']:run_tracking.missing_repeats(manifest,raw,t['task']) for t in manifest['expected']}
    missing={tid:indices for tid,indices in missing.items() if indices}
    reason=None
    if job.get('state') not in ('error','cancelled','stopped'):reason='Only interrupted or cancelled runs can be resumed.'
    elif (job.get('elapsed_s') or 0)>=hour_score.WINDOW_S:reason='The one-hour scoring window is complete. Start a new run for another attempt.'
    elif not missing:reason='Every planned attempt is already complete.'
    config=next((m for m in model_document()['models'] if m['name']==manifest['model']),None)
    if not reason and (not config or calibration.digest(config)!=manifest['config_hash']):
        reason='The saved model settings changed. Start a fresh run to keep results comparable.'
    if not reason:
        for t in manifest['expected']:
            if (hourglass.sha(TASKS/t['task']/'task.json') or '')[:16]!=t['task_sha']:
                reason='Question content changed. Start a fresh run.';break
    mixed=manifest['benchmark_version']!=hourglass.BENCHMARK_VERSION
    return {'allowed':reason is None,'reason':reason,'remaining_questions':len(missing),
            'remaining_attempts':sum(map(len,missing.values())),'preserved_attempts':sum(t['repeat'] for t in manifest['expected'])-sum(map(len,missing.values())),
            'version_warning':f"This run began on v{manifest['benchmark_version']}; continuing on v{hourglass.BENCHMARK_VERSION} mixes versions and is excluded from calibration." if mixed else None}

def public_job(job, rows=None):
    result={k:job.get(k) for k in ('id','label','model','tasks','repeat','state','rc','created','started','ended','current_task','completed_tasks','total_tasks','error','stopped_after','resume_count','stop_after_wrong','stop_requested','stop_reason','active_intervals','hour_timing_unknown')}
    if rows is not None:
        manifest=read_json(ROOT/'evaluations'/(job['id']+'.json'))
        if manifest:
            raw=run_tracking.raw_attempts(manifest,rows)
            result['progress']=run_tracking.progress(manifest,raw,job,time.time())
            result['hour_score']=hour_score.score(job,rows,manifest['expected'])
            result['expected']=manifest['expected']
            result['benchmark_version']=manifest['benchmark_version']
            result['scope']=manifest.get('scope')
            result['resume']=resume_plan(job,manifest,rows)
            result['user_settings']=settings_records.records(ROOT,job['id'])
    return result

def state():
    doc=model_document();rows=result_rows()
    settings_cache={}
    for row in rows:
        jid=row.get('evaluation_id')
        if isinstance(jid,str) and jid.isalnum():
            if jid not in settings_cache:settings_cache[jid]=settings_records.records(ROOT,jid)
            row['user_settings']=settings_cache[jid]
    with condition:
        jobs={'running':[public_job(j,rows) for j in running], 'pending':[public_job(j,rows) for j in queue], 'done':[public_job(j,rows) for j in done]}
    return {'app':'Hourglass Bench','version':2,'tasks':task_catalog(),'models':model_names(),
            'model_configs':doc.get('models',[]),'models_json':json.dumps(doc,indent=2),
            'model_errors':hourglass.validate_models(doc),'results':rows,
            'calibration_available':True,'benchmark_version':hourglass.BENCHMARK_VERSION,'harness':{'name':'pi','version':'0.85.1','temperature_policy':'server_default'},
            'score_policy':{'version':hour_score.VERSION,'window_s':hour_score.WINDOW_S,'metric':'distinct_correct_within_active_hour'},
            'execution_policy':{'timeouts':False,'stop_after_wrong':run_tracking.STOP_AFTER_WRONG,'order':'estimated_tier_then_alternating_sections'},
            'provenance':read_json(ROOT/'provenance.json',{}),'jobs':jobs,
            'sandbox_available':shutil.which('sandbox-exec') is not None}

def resume_job(body):
    with condition:
        jid=body.get('job')
        if any(j['id']==jid for j in [*queue,*running]):raise ValueError('This run is already queued or active.')
        manifest=saved_manifest(jid)
        previous=next((j for j in done if j['id']==jid),manifest)
        rows=result_rows();plan=resume_plan(previous,manifest,rows)
        if not plan['allowed']:raise ValueError(plan['reason'])
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:6]
        backup=ROOT/'backups'/('resume-'+stamp);backup.mkdir(parents=True)
        shutil.copy2(ROOT/'evaluations'/(jid+'.json'),backup/'evaluation.json')
        log=LOGS/f'job-{jid}.log'
        if log.exists():shutil.copy2(log,backup/log.name)
        if manifest.get('legacy_time_match') and 'legacy_run_ids' not in manifest:
            manifest['legacy_run_ids']=[r['run_id'] for r in run_tracking.raw_attempts(manifest,rows) if not r.get('evaluation_id')]
        elapsed=previous.get('elapsed_s')
        if elapsed is None:elapsed=max(0,(previous.get('ended') or time.time())-(previous.get('started') or time.time()))
        order=manifest.get('order') or [t['task'] for t in manifest['expected']]
        job={**manifest,'tasks':order,'stop_after_wrong':run_tracking.STOP_AFTER_WRONG,'state':'pending','ended':None,'error':None,'rc':None,
             'elapsed_s':elapsed,'active_started':None,'stop_requested':False,'resume_count':manifest.get('resume_count',0)+1,
             'resume_versions':list(dict.fromkeys(manifest.get('resume_versions',[])+[hourglass.BENCHMARK_VERSION])),
             'completed_tasks':len(order)-plan['remaining_questions'],'total_tasks':len(order),
             'label':manifest.get('label',manifest['model']+' · resumed run')}
        # Backfill only an uninterrupted historical interval. Never invent old pause history.
        if not job.get('active_intervals') and previous.get('started'):
            if previous.get('resume_count'):
                job['hour_timing_unknown']=True
            elif previous.get('ended'):
                job['active_intervals']=[{'start':previous['started'],'end':previous['ended']}]
            else:
                job['hour_timing_unknown']=True
        # Keep the original version/scope and raw attempts; a cross-version continuation is never relabelled.
        manifest.update({k:job[k] for k in ('state','ended','error','rc','elapsed_s','active_started','resume_count','resume_versions')})
        calibration.write(ROOT/'evaluations'/(jid+'.json'),manifest)
        for j in list(done):
            if j['id']==jid:done.remove(j)
        queue.append(job);condition.notify_all()
        return job

def record_settings(body):
    with condition:
        manifest=saved_manifest(body.get('job'))
        return settings_records.append(ROOT,manifest,body)

def stop_job(body):
    with condition:
        job=next((j for j in running if j['id']==body.get('job')),None)
        if not job:raise ValueError('This run is not active.')
        job['stop_requested']=True
        job['stop_reason']='hour_limit' if body.get('reason')=='hour_limit' else 'user'
        proc=job.get('_process')
        if proc is not None and proc.poll() is None:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        return {'ok':True,'job':job['id']}

def clear_job(body):
    with condition, calibration.LOCK:
        jid=body.get('job');manifest=saved_manifest(jid)
        if running:raise ValueError('Wait for active model work to finish before clearing history.')
        if any(j['id']==jid for j in queue):raise ValueError('Remove this run from the queue before clearing it.')
        rows=result_rows();manifests=[read_json(p,{}) for p in (ROOT/'evaluations').glob('*.json')]
        removed=run_tracking.raw_attempts(manifest,rows,manifests)
        ids={r['run_id'] for r in removed if r.get('run_id')}
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:6]
        backup=ROOT/'backups'/('cleared-run-'+stamp+'-'+jid);backup.mkdir(parents=True)
        source=ROOT/'evaluations'/(jid+'.json');shutil.copy2(source,backup/'evaluation.json')
        settings_path=ROOT/'evaluations'/(jid+'.settings.jsonl')
        if settings_path.exists():shutil.copy2(settings_path,backup/'user-settings.jsonl')
        result_file=RESULTS/'results.jsonl';lines=result_file.read_bytes().splitlines(keepends=True) if result_file.exists() else []
        if result_file.exists():shutil.copy2(result_file,backup/'results-before.jsonl')
        (backup/'removed-results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in removed))
        log=LOGS/f'job-{jid}.log'
        if log.exists():shutil.copy2(log,backup/log.name)
        artifacts=[]
        retained=[r for r in rows if r.get('evaluation_id')!=jid and r.get('run_id') not in ids]
        retained_paths={r.get('artifact_dir') for r in retained}
        for r in removed:
            rel=r.get('artifact_dir')
            if not rel or rel in retained_paths:continue
            path=(ROOT/rel).resolve()
            if path.is_relative_to(RESULTS.resolve()) and path.is_dir() and path.name.startswith('run-') and path not in artifacts:
                dest=backup/'artifacts'/path.relative_to(RESULTS.resolve());dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copytree(path,dest);artifacts.append(path)
        doc=calibration.read(ROOT/'calibration.json',{'schema_version':1,'scopes':{}});changed=False
        for scope in doc['scopes'].values():
            refs=[r for r in scope['references'] if r['evaluation_id']!=jid]
            if len(refs)!=len(scope['references']):
                scope.update(references=refs,revision=uuid.uuid4().hex,fit=calibration.fit(refs));changed=True
        if changed:
            shutil.copy2(ROOT/'calibration.json',backup/'calibration-before.json')
            calibration.save_document(ROOT,doc)
        kept=[]
        for line in lines:
            try:r=json.loads(line)
            except ValueError:kept.append(line);continue
            if r.get('evaluation_id')!=jid and r.get('run_id') not in ids:kept.append(line)
        if result_file.exists():
            tmp=RESULTS/('results-clear-'+uuid.uuid4().hex+'.tmp');tmp.write_bytes(b''.join(kept));tmp.replace(result_file)
        for name in ('leaderboard.md','frontier.md'):
            if (ROOT/name).exists():shutil.copy2(ROOT/name,backup/name)
        hourglass.cmd_leaderboard(None,rows=retained,root=ROOT,emit=False)
        hourglass.cmd_frontier(None,rows=retained,root=ROOT,emit=False)
        source.unlink()
        if log.exists():log.unlink()
        for path in artifacts:shutil.rmtree(path)
        for job in list(done):
            if job['id']==jid:done.remove(job)
        (backup/'README.md').write_text('Cleared from visible history. evaluation.json, removed-results.jsonl, log and artifacts preserve this run. results-before.jsonl is the complete pre-clear history snapshot.\n')
        return {'ok':True,'backup':str(backup.relative_to(ROOT)),'removed_attempts':len(removed)}

def worker():
    while True:
        with condition:
            condition.wait_for(lambda: queue or worker_stop)
            if worker_stop:return
            job=queue.popleft();now=time.time()
            job.update(state='running',active_started=now,elapsed_s=job.get('elapsed_s',0))
            job.setdefault('active_intervals',[]).append({'start':now,'end':None})
            if not job.get('started'):job['started']=now
            running.append(job);calibration.update_evaluation(ROOT,job)
            threading.Thread(target=hour_deadline.watch_job,args=(job,condition,stop_job),daemon=True).start()
        LOGS.mkdir(exist_ok=True)
        try:
            manifest=saved_manifest(job['id'])
            expected={t['task']:t['repeat'] for t in manifest['expected']}
            with (LOGS/f"job-{job['id']}.log").open('a') as log:
                log.write(f"\n{'RESUME' if job.get('resume_count') else 'RUN'} · Hourglass Bench {hourglass.BENCHMARK_VERSION}\n");log.flush()
                wrong_streak=0;job['completed_tasks']=0
                stop_limit=job.get('stop_after_wrong') or run_tracking.STOP_AFTER_WRONG
                for tid in job['tasks']:
                    if job.get('stop_requested'):
                        job.update(state='stopped',error=None);break
                    raw=run_tracking.raw_attempts(manifest,result_rows())
                    missing=run_tracking.missing_repeats(manifest,raw,tid)
                    skip=wrong_streak>=stop_limit
                    if missing:
                        with condition:job['current_task']=tid
                        cmd=[sys.executable,'-u',str(ROOT/'hourglass.py'),'run',tid,'--model',job['model'],
                             '--repeat',str(expected[tid]),'--repeat-indices',','.join(map(str,missing))]
                        log.write(f"\n=== {tid} · repeats {','.join(map(str,missing))} ===\n");log.flush()
                        with condition:
                            if job.get('stop_requested'):
                                job.update(state='stopped',error=None);break
                            proc=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
                                                  env=dict(os.environ,NODE_ID=os.environ.get('NODE_ID','unknown'),HOURGLASS_EVALUATION_ID=job['id'],HOURGLASS_SKIP_REASON='wrong_streak_limit' if skip else '',HOURGLASS_STOP_AFTER_WRONG=str(stop_limit)))
                            job['_process']=proc
                        rc=proc.wait()
                        with condition:job.pop('_process',None)
                        if job.get('stop_requested'):
                            job.update(state='stopped',rc=rc,error=None)
                            log.write('\n'+('ONE-HOUR DEADLINE REACHED. Score frozen; completed attempts retained.' if job.get('stop_reason')=='hour_limit' else 'STOPPED BY USER. Completed attempts retained; unfinished attempts can be resumed.')+'\n');log.flush();break
                        if rc:
                            with condition:job.update(state='error',rc=rc,error=f'{tid} could not complete. Open its log for details.')
                            break
                        raw=run_tracking.raw_attempts(manifest,result_rows())
                        if run_tracking.missing_repeats(manifest,raw,tid):
                            with condition:job.update(state='error',rc=1,error=f'{tid} did not produce a valid result.')
                            break
                    with condition:job['completed_tasks']+=1
                    if not skip:
                        attempts=[r for r in run_tracking.effective_attempts(raw) if r.get('task')==tid]
                        wrong_streak=0 if any(r.get('solved') for r in attempts) else wrong_streak+1
                        if wrong_streak>=stop_limit:
                            with condition:job['stopped_after']=tid
                            log.write(f'\nSTOP: {stop_limit} consecutive incorrect questions. Remaining questions recorded as not-attempted zeros.\n');log.flush()
                else:
                    with condition:job.update(state='completed',rc=0)
        except Exception as e:
            with condition:job.update(state='error',rc=1,error=str(e))
        finally:
            with condition:
                job['ended']=time.time();job['elapsed_s']+=job['ended']-job['active_started'];job['active_started']=None
                job['active_intervals'][-1]['end']=job['ended']
                running.remove(job);done.append(job);condition.notify_all();calibration.update_evaluation(ROOT,job)
            if job.get('stop_reason')=='hour_limit' or job['state']=='completed':hour_deadline.chime()

def restore_job_history():
    # Preserve visible activity/log links across a UI restart; never replay model work.
    known={j['id'] for j in done}
    for path in sorted((ROOT/'evaluations').glob('*.json')):
        m=read_json(path,{})
        if not m.get('id') or m['id'] in known:continue
        state=m.get('state','error')
        if state in ('pending','running'):
            state='error'
            m['error']='UI restarted before this evaluation finished. Saved attempts and logs are retained.'
        done.append({**m,'state':state,'tasks':m.get('order') or [t['task'] for t in m['expected']],
                     'total_tasks':len(m['expected']), 'label':m.get('label',m['model']+' · saved evaluation')})

def start_worker():
    global worker_thread,worker_stop
    with condition:
        if worker_thread and worker_thread.is_alive():return
        restore_job_history()
        worker_stop=False;worker_thread=threading.Thread(target=worker,daemon=True);worker_thread.start()

def enqueue(body):
    model=body.get('model'); tids=body.get('tasks'); repeat=body.get('repeat')
    if model not in model_names():raise ValueError('Choose a saved model.')
    if not isinstance(tids,list) or not tids or any(not isinstance(t,str) for t in tids):raise ValueError('Choose at least one test.')
    catalog={t['id']:t for t in task_catalog()}
    tids=list(dict.fromkeys(tids))
    if any(t not in catalog for t in tids):raise ValueError('A selected test no longer exists. Refresh the library.')
    bad=[t for t in tids if catalog[t]['issues']]
    if bad:raise ValueError('These tests need repair before running: '+', '.join(bad))
    if repeat is not None and (type(repeat) is not int or repeat<1):raise ValueError('Repeats must be a positive whole number, or use task defaults.')
    tids=ordered_tasks(list(catalog.values()),tids)
    job={'id':uuid.uuid4().hex,'label':f'{model} · {len(tids)} tests','model':model,'tasks':tids,
         'repeat':repeat,'stop_after_wrong':run_tracking.STOP_AFTER_WRONG,'state':'pending','created':time.time(),'completed_tasks':0,'total_tasks':len(tids)}
    config=next(m for m in model_document()['models'] if m['name']==model)
    calibration.evaluation_manifest(ROOT,job,hourglass.BENCHMARK_VERSION,config)
    with condition:queue.append(job);condition.notify_all()
    return job

def check_model(name):
    models={m['name']:m for m in model_document().get('models',[]) if isinstance(m,dict) and 'name'in m}
    if name not in models:raise ValueError('Unknown saved model')
    m=models[name];url=m['base_url'].rstrip('/')+'/models';t=time.time()
    try:
        with urllib.request.urlopen(url,timeout=30) as r:doc=json.load(r)
        available=[x['id'] for x in doc.get('data',[]) if isinstance(x,dict) and isinstance(x.get('id'),str)]
        return {'name':name,'reachable':True,'listed':m['model'] in available,'available':available,
                'latency_ms':round((time.time()-t)*1000),'checked_at':time.time(),
                'message':'Endpoint responds. This does not test generation, tool support, or vision.'}
    except Exception as e:
        return {'name':name,'reachable':False,'listed':False,'available':[],'checked_at':time.time(),'message':str(e)}

class H(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_bytes(self,data,status=200,ctype='application/json'):
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def _json(self,obj,status=200):self.send_bytes(json.dumps(obj).encode(),status)
    def _text(self,text,status=200):self.send_bytes(text.encode(),status,'text/plain; charset=utf-8')
    def do_GET(self):
        u=urlparse(self.path);q=parse_qs(u.query)
        if u.path=='/api/state':self._json(state());return
        if u.path=='/api/calibration':self._json(calibration.report(ROOT,result_rows()));return
        if u.path=='/api/health':self._json({'app':'Hourglass Bench','version':2,'benchmark_version':hourglass.BENCHMARK_VERSION});return
        if u.path in ('/api/log','/api/log/full'):
            jid=q.get('job',[''])[0]
            if not jid.isalnum():self._json({'error':'Invalid job'},400);return
            p=LOGS/f'job-{jid}.log'
            if u.path=='/api/log/full':
                if not p.is_file():self._json({'error':'No log has been written yet.'},404);return
                self.send_bytes(p.read_bytes(),ctype='text/plain; charset=utf-8');return
            self._text(p.read_text()[-50000:] if p.is_file() else 'Waiting to start…');return
        if u.path in ('/api/task-display','/api/task-image'):
            tid=q.get('id',[''])[0]
            if tid not in valid_tasks():self._json({'error':'Unknown question'},404);return
            t=read_json(TASKS/tid/'task.json',{})
            assets=t.get('assets') or ([t['image']] if t.get('image') else [])
            images=[a for a in assets if (mimetypes.guess_type(a)[0] or '').startswith('image/')]
            if u.path=='/api/task-image':
                asset=q.get('asset',[''])[0];base=(TASKS/tid).resolve();p=(base/asset).resolve()
                if asset not in images or not p.is_relative_to(base) or not p.is_file():self._json({'error':'Image not found'},404);return
                self.send_bytes(p.read_bytes(),ctype=mimetypes.guess_type(p.name)[0]);return
            options=[]
            if t.get('kind')=='mcq' and t.get('mode')!='numeric':options=hourglass.mcq_display(t).splitlines()[1:]
            elif t.get('kind')=='chart-vqa':options=hourglass.shuffle_choices(t)[0].splitlines()[1:]
            self._json({'options':options,'images':['/api/task-image?id='+urllib.parse.quote(tid,safe='')+'&asset='+urllib.parse.quote(a,safe='') for a in images]});return
        if u.path=='/api/task':
            tid=q.get('id',[''])[0]
            if tid not in valid_tasks():self._json({'error':'Unknown test'},404);return
            t=read_json(TASKS/tid/'task.json',{})
            # Deliberately omit host-side answers and private verifier contents.
            self._json({'id':tid,'title':t.get('title',tid),'prompt':t.get('prompt',''),
                        'options':t.get('options') or t.get('choices') or [],'files':list((t.get('files') or {}).keys())});return
        if u.path=='/api/file':
            p=(ROOT/q.get('path',[''])[0]).resolve()
            if not p.is_relative_to(RESULTS.resolve()) or not p.is_file():self._json({'error':'Result file not found'},404);return
            self._text(p.read_text(errors='replace'));return
        rel='index.html' if u.path in ('/','/index.html') else u.path.removeprefix('/')
        p=(ROOT/'ui'/rel).resolve()
        if not p.is_relative_to((ROOT/'ui').resolve()) or not p.is_file():self._json({'error':'Not found'},404);return
        self.send_bytes(p.read_bytes(),ctype=mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):
                self._json({'error':'Cross-origin request rejected'},403);return
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self._json({'error':'Expected application/json'},415);return
            n=int(self.headers.get('Content-Length','0'))
            if n<0 or n>2_000_000:raise ValueError('Request body is too large')
            b=json.loads(self.rfile.read(n)) if n else {}
            if not isinstance(b,dict):raise ValueError('Expected a JSON object')
            route=urlparse(self.path).path
            if route=='/api/calibration/reference':
                scope=calibration.set_reference(ROOT,result_rows(),b);self._json({'ok':True,'scope':scope});return
            if route=='/api/calibration/remove':
                calibration.remove_reference(ROOT,b);self._json({'ok':True});return
            if route=='/api/run-settings':self._json({'ok':True,'record':record_settings(b)});return
            if route=='/api/stop':self._json(stop_job(b));return
            if route=='/api/clear-run':self._json(clear_job(b));return
            if route=='/api/resume':
                job=resume_job(b);self._json({'ok':True,'job':job['id']});return
            if route=='/api/run':
                job=enqueue(b);self._json({'ok':True,'job':job['id']});return
            if route=='/api/cancel':
                with condition:
                    job=next((j for j in queue if j['id']==b.get('job')),None)
                    if not job:raise ValueError('Only waiting runs can be removed. Active work is left running.')
                    queue.remove(job);job.update(state='cancelled',ended=time.time());done.append(job)
                    calibration.update_evaluation(ROOT,job)
                self._json({'ok':True});return
            if route=='/api/models':
                doc=json.loads(b.get('text',''));errors=hourglass.validate_models(doc)
                if errors:raise ValueError('; '.join(errors))
                stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:6]
                backup=ROOT/'backups'/('models-'+stamp);backup.mkdir(parents=True)
                target=ROOT/'models.json'
                if target.exists():shutil.copy2(target,backup/'models.json')
                tmp=ROOT/('models.tmp-'+uuid.uuid4().hex);tmp.write_text(json.dumps(doc,indent=2)+'\n');tmp.replace(target)
                self._json({'ok':True,'backup':str(backup.relative_to(ROOT))});return
            if route=='/api/check-model':self._json(check_model(b.get('model')));return
            if route=='/api/probe':
                p=subprocess.run([sys.executable,str(ROOT/'hourglass.py'),'probe'],cwd=ROOT,capture_output=True,text=True)
                self._json({'ok':p.returncode==0,'out':p.stdout+p.stderr});return
            if route=='/api/cert':
                tid=b.get('task')
                if tid not in valid_tasks():raise ValueError('Unknown test')
                p=subprocess.run([sys.executable,str(ROOT/'hourglass.py'),'cert',tid],cwd=ROOT,capture_output=True,text=True)
                self._json({'ok':p.returncode==0,'out':p.stdout+p.stderr});return
            self._json({'error':'Not found'},404)
        except (ValueError,TypeError,KeyError) as e:self._json({'error':str(e)},400)
        except subprocess.TimeoutExpired:self._json({'error':'The operation timed out. No model settings were changed.'},504)
        except Exception as e:self._json({'error':str(e)},500)

def main():
    server=ThreadingHTTPServer(('127.0.0.1',PORT),H)
    start_worker()
    print(f'Hourglass Bench → http://127.0.0.1:{PORT}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
