"""Local question context for chart inspection; excluded from public reports."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import repair_runs
import report_charts
import run_tracking


def catalog(root):
    try:
        data=json.loads((Path(root)/'question-summaries.json').read_text())
        return data.get('questions',{}) if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}


def summary(entries, expected):
    entry=entries.get(expected.get('task'),{})
    if not isinstance(entry,dict):return 'Summary unavailable for this question version'
    text=entry.get('summary') if entry.get('task_sha')==expected.get('task_sha') else entry.get('versions',{}).get(expected.get('task_sha'))
    if (entry.get('task_sha')==expected.get('task_sha') or expected.get('task_sha') in entry.get('versions',{})) and isinstance(text,str) and 5<=len(text.split())<=7:
        return text
    return 'Summary unavailable for this question version'


def timeline(job, manifest, rows, entries, now):
    if manifest.get('repair'):job={**job,'repair':manifest['repair']}
    expected={e['task']:e for e in manifest.get('expected',[])}
    intervals=job.get('active_intervals') or ([{'start':job['started'],'end':job.get('ended')}] if job.get('started') else [])
    def active_at(stamp):
        return sum(max(0,min(stamp,p.get('end') or stamp)-p['start']) for p in intervals)
    base=(job.get('repair') or {}).get('base_elapsed_s',0)
    end=min(3600,base+active_at(job.get('ended') or now))
    spans=[];last=0
    raw=run_tracking.raw_attempts(manifest,rows)
    def add(task, stop, status):
        nonlocal last
        stop=min(end,max(last,stop))
        if spans and spans[-1]['task']==task:
            spans[-1].update(end_s=round(stop,3),status=status)
        else:
            spans.append({'task':task,'summary':summary(entries,expected[task]),'start_s':round(last,3),'end_s':round(stop,3),'status':status})
        last=stop
    for row in sorted(raw,key=lambda r:repair_runs.elapsed_at(job,r) if job.get('repair') else run_tracking.timestamp(r)):
        if row.get('task') not in expected or run_tracking.is_early_stop(row):continue
        stamp=run_tracking.timestamp(row)
        if not row.get('repair_inherited') and (not intervals or stamp<intervals[0]['start']):continue
        stop=repair_runs.elapsed_at(job,row) if job.get('repair') else active_at(stamp)
        if stop>end:continue
        if row.get('status')=='timeout':status='Timed out'
        elif row.get('status')=='error':status='Execution error'
        elif row.get('status')=='completed':
            status='Correct' if row.get('solved') else 'Unsupported vision' if row.get('score_reason')=='unsupported_vision' else 'No answer' if row.get('score_reason') in ('abstained','not_attempted','turn_limit') else 'Incorrect'
        else:continue
        if row.get('repair_inherited'):status='Retained · '+status
        elif job.get('repair'):last=max(last,min(base,end))
        add(row['task'],stop,status)
    current=job.get('current_task')
    if current in expected and end>last and (job.get('state')=='running' or run_tracking.missing_repeats(manifest,raw,current)):
        if job.get('repair'):last=max(last,min(base,end))
        add(current,end,'Working' if job.get('state')=='running' else 'Stopped')
    return {'spans':spans,'end_s':round(end,3),'state':job.get('state'),'timing_basis':repair_runs.NOTE if job.get('repair') else 'Active wall time between recorded question completions; includes setup, thinking, tools and retries. Pauses excluded.'}


def build(root, reports, jobs, rows, now, individual_reports=None):
    entries=catalog(root)
    lookup={hashlib.sha256(str(j['id']).encode()).hexdigest()[:24]:j for j in jobs}
    models=[]
    for index,report in enumerate(reports):
        if report.get('member_run_keys'):
            members=[r for r in (individual_reports or []) if r['run_key'] in report['member_run_keys']]
            children=build(root,members,jobs,rows,now)['models']
            models.append({'id':report['run_key'],'model':report['model'],'display_name':report['display_name'],'color':report_charts.color_for(index),'current':False,'points':report['weighted_points'],'hardware':report.get('hardware',{}).get('label',''),'rules':report_charts.rules_label(report),'members':children,'spans':[],'end_s':3600,'state':'final'})
            continue
        job=lookup.get(report['run_key'])
        if not job:continue
        manifest=json.loads((Path(root)/'evaluations'/(job['id']+'.json')).read_text())
        models.append({'id':job['id'],'model':report['model'],'display_name':report.get('display_name') or (job.get('run_identity') or {}).get('name') or (job.get('run_details') or {}).get('values',{}).get('run_name') or (job.get('run_details') or {}).get('values',{}).get('model_name') or report['model'],'hardware':report.get('hardware',{}).get('label','Hardware not recorded'),
                       'color':report_charts.color_for(index),'current':bool(report.get('is_current_run')),'run_date':report.get('run_date'),
                       'points':report['weighted_points'],'rules':report_charts.rules_label(report),
                       **timeline(job,manifest,rows,entries,now)})
    return {'models':models,'generated_at':now}
