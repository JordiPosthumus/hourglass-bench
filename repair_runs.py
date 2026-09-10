"""Explicit reconstructed evaluations. Originals and their clocks stay immutable."""
import copy
import datetime as dt
import hashlib
import json
import math
import shutil
import task_identity
import time
import uuid
from pathlib import Path

POLICY='reconstructed-hour-v1'
NOTE='Repaired run: retained results and their recorded cost are combined with freshly measured replacement work. Remaining time continues the original question order. This reconstructs an hour; it is not an uninterrupted measurement. Original results are retained.'
CAVEAT={'code':'reconstructed_hour','label':'Repaired run','message':NOTE,'attempts':0}
FIELDS='scoring_policy node tier temperature temperature_source thinking_settings run_id task run model status solved score_reason parsed_answer termination duration_s ts task_sha task_bundle_sha benchmark_version artifact_dir kind section mode opt_n completion_tokens prompt_tokens tool_calls harness pi_version requested_settings caveats'.split()


def active_at(manifest, ts):
    intervals=manifest.get('active_intervals') or ([{'start':manifest['started'],'end':manifest.get('ended')}] if manifest.get('started') else [])
    return sum(max(0,min(ts,p.get('end') or ts)-p['start']) for p in intervals)


def composite_rows(manifest, rows):
    own=[r for r in rows if r.get('evaluation_id')==manifest.get('id')]
    if not manifest.get('repair'):return own
    known={(r.get('run_id'),r.get('repair_inherited')) for r in own}
    inherited=[{**r,'evaluation_id':manifest['id'],'repair_inherited':True} for r in manifest['repair']['retained'] if (r.get('run_id'),True) not in known]
    return inherited+own


def elapsed_at(manifest, row):
    if row.get('repair_inherited'):return row['repair_elapsed_s']
    ts=dt.datetime.fromisoformat(row['ts']).timestamp()
    return manifest.get('repair',{}).get('base_elapsed_s',0)+active_at(manifest,ts)


def dependencies(root, jid):
    result=[]
    for p in (Path(root)/'evaluations').glob('*.json'):
        try:m=json.loads(p.read_text())
        except (OSError,ValueError):continue
        if m.get('repair',{}).get('source_evaluation_id')==jid:result.append(m['id'])
    return result


def frozen_config(root, source):
    import calibration
    config=source.get('model_config_snapshot')
    if config is None:
        sidecar=Path(root)/'evaluations'/(source['id']+'.model.json')
        path=sidecar if sidecar.exists() else Path(root)/'models.json'
        try:config=next((c for c in json.loads(path.read_text()).get('models',[]) if c.get('name')==source['model'] and calibration.digest(c)==source.get('config_hash')),None)
        except (OSError,ValueError):config=None
    if not config or calibration.digest(config)!=source.get('config_hash'):raise ValueError('The original frozen model settings cannot be verified.')
    return copy.deepcopy(config)


def question_sources(root,source):
    """Resolve verified original versions without replacing the current question bank."""
    root=Path(root);sources={};bundles={}
    for expected in source['expected']:
        tid=expected['task']
        candidates=([root/source['task_snapshot']/tid] if source.get('task_snapshot') else [])
        candidates += [root/'tasks'/tid,*sorted((root/'backups').glob('*/original-bank/'+tid),reverse=True)]
        for directory in candidates:
            try:
                bundle=task_identity.verify(directory,expected)
            except (OSError,ValueError,KeyError):continue
            sources[tid]=str(directory);bundles[tid]=bundle;break
        else:raise ValueError('The original question content has changed and no verified archive is available for '+tid+'. Start a fresh run.')
    return sources,bundles

def plan(root, source, rows, tasks=None):
    import calibration,run_tracking
    root=Path(root)
    if source.get('state') in ('pending','running'):raise ValueError('Finish the original run before reviewing its repair.')
    if source.get('repair'):raise ValueError('Choose the original run to prepare another repair.')
    if source.get('results_reset'):raise ValueError('This run has reset results. Use a fresh run.')
    if source.get('hour_timing_unknown') or not source.get('ended') or not source.get('started'):raise ValueError('A repair requires a known original clock.')
    config=frozen_config(root,source)
    sources,bundles=question_sources(root,source)
    elapsed=min(3600,active_at(source,source['ended']))
    raw=run_tracking.raw_attempts(source,rows)
    eligible=[]
    for r in raw:
        try:a=active_at(source,dt.datetime.fromisoformat(r['ts']).timestamp())
        except (ValueError,TypeError,KeyError):raise ValueError('An original attempt has no reliable completion timestamp.')
        if a<=elapsed and not run_tracking.is_early_stop(r):eligible.append((r,a))
    candidates=[]
    intervals=[]
    for tid in source['order']:
        rs=[(r,a) for r,a in eligible if r.get('task')==tid]
        measured=source.get('question_elapsed_s',{}).get(tid)
        if measured is None:measured=sum(r.get('duration_s',0) or 0 for r,a in rs)
        if not rs and not measured:continue
        if not isinstance(measured,(float,int)) or not math.isfinite(measured) or measured<0:raise ValueError('Invalid recorded question duration.')
        end=active_at(source,source['ended']) if tid==source.get('current_task') else max((a for r,a in rs),default=0)
        start=max(0,end-measured);end=min(elapsed,end)
        duration=max(0,end-start)
        flagged=any(c.get('code')=='diagnostic_trace_exposure' for r,a in rs for c in r.get('caveats',[]))
        candidates.append({'task':tid,'credit_s':duration,'flagged':flagged,'attempts':len(rs),'start':start,'end':end})
    selected=[c['task'] for c in candidates if c['flagged']] if tasks is None else tasks
    if not isinstance(selected,list) or any(not isinstance(t,str) for t in selected) or not set(selected).issubset({c['task'] for c in candidates}):raise ValueError('Choose recorded questions from this original run.')
    selected=set(selected)
    for c in sorted((c for c in candidates if c['task'] in selected),key=lambda c:c['start']):
        if c['credit_s']<=0:continue
        if intervals and c['start']<intervals[-1][1]-0.01:raise ValueError('Recorded question clocks overlap; a repair cannot safely credit this selection.')
        intervals.append((c['start'],c['end']))
    refunded=sum(b-a for a,b in intervals);base=max(0,elapsed-refunded)
    retained=[]
    for r,a in eligible:
        if r['task'] in selected:continue
        retained.append({**{k:r[k] for k in FIELDS if k in r},'repair_elapsed_s':max(0,a-sum(max(0,min(a,b)-x) for x,b in intervals)),'repair_source_evaluation_id':source['id']})
    order=[t for t in source['order'] if t in selected]+[t for t in source['order'] if t not in selected]
    retained_view=[{**r,'evaluation_id':'preview'} for r in retained]
    continuation=[t for t in source['order'] if t not in selected and run_tracking.missing_repeats(source,retained_view,t)]
    revision=calibration.digest({'source':source,'rows':raw,'question_bundles':bundles})
    return {'source_evaluation_id':source['id'],'model':source['model'],'revision':revision,'candidates':candidates,'tasks':[t for t in source['order'] if t in selected],
            'question_sources':sources,'question_bundles':bundles,'source_elapsed_s':elapsed,'refunded_s':refunded,'base_elapsed_s':base,'remaining_s':3600-base,'continuation':continuation,'order':order,'retained':retained,
            'requested':{k:config.get(k) for k in ('model','base_url','context_window','max_tokens','reasoning')},'note':NOTE}


def create(root, source, rows, body, version):
    import fcntl
    with (Path(root)/'.run.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Wait for active model work to finish before starting a repair.')
        return _create(root,source,rows,body,version)


def _create(root, source, rows, body, version):
    import calibration,diagnostics
    p=plan(root,source,rows,body.get('tasks'))
    if body.get('revision')!=p['revision']:raise ValueError('Original results changed. Review the repair again.')
    if not p['tasks'] or p['remaining_s']<=0:raise ValueError('Select at least one question with recorded time to replace.')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=Path(root)/'backups'/('repair-'+stamp);backup.mkdir(parents=True)
    calibration.write(backup/'original-evaluation.json',source)
    calibration.write(backup/'repair-plan.json',p)
    index=Path(root)/'results/results.jsonl'
    if index.exists():(backup/'results-before.jsonl').write_bytes(index.read_bytes())
    jid=uuid.uuid4().hex
    preserved=('model','model_id','config_hash','model_config_snapshot','hardware','expected','repeat','scoring_policy','stop_after_wrong','question_timeout_s','question_timeout_policy','option_layout_policy','presentation_seed')
    job={k:copy.deepcopy(source[k]) for k in preserved if k in source}
    job['model_config_snapshot']=frozen_config(root,source)
    frozen=Path(root)/'evaluations'/(jid+'.tasks');frozen.mkdir(parents=True)
    try:
        for expected in job['expected']:
            tid=expected['task'];expected['task_bundle_sha']=p['question_bundles'][tid]
            shutil.copytree(p['question_sources'][tid],frozen/tid)
            task_identity.verify(frozen/tid,expected)
    except Exception:
        shutil.rmtree(frozen)
        raise
    job['task_snapshot']=str(frozen.relative_to(root))

    repair={k:copy.deepcopy(p[k]) for k in ('source_evaluation_id','source_elapsed_s','refunded_s','base_elapsed_s','tasks','retained','continuation','note')}
    repair.update(policy=POLICY,source_version=source.get('benchmark_version'),source_revision=p['revision'],backup=str(backup.relative_to(root)))
    job.update(id=jid,label=source['model']+' · repaired run',repair=repair,benchmark_version=version,diagnostic_isolation=diagnostics.POLICY,
               order=p['order'],tasks=p['order'],created=time.time(),state='pending',started=None,ended=None,elapsed_s=p['base_elapsed_s'],active_started=None,active_intervals=[],
               legacy_time_match=False,question_elapsed_s={k:v for k,v in source.get('question_elapsed_s',{}).items() if k not in p['tasks']},
               total_tasks=len(p['order']),completed_tasks=0,scope=calibration.digest({'source':source.get('scope'),'repair':POLICY,'tasks':p['tasks']}))
    calibration.write(Path(root)/'evaluations'/(jid+'.json'),job)
    return job
