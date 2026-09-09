"""Owner-defined approximate scales over recorded Hourglass points."""
import datetime as dt
import math
from pathlib import Path
import shutil
import time
import uuid

import calibration
import hour_score
import score_weights
import hardware_records
import run_editor

METHOD='equal-model-hourglass-linear-v1'


def fit(references):
    base={'method':METHOD,'status':'needs_references','message':'Assign targets to at least two models with different Hourglass scores.'}
    if len(references)<2:return base
    xs=[r['points'] for r in references];ys=[r['target'] for r in references]
    mean_x=sum(x/len(xs) for x in xs);mean_y=sum(y/len(ys) for y in ys)
    denominator=sum((x-mean_x)**2 for x in xs)
    if denominator<1e-18:return {**base,'message':'These models have the same Hourglass score. Add a reference with a different score to estimate other models.'}
    try:
        slope=sum((x-mean_x)*(y-mean_y) for x,y in zip(xs,ys))/denominator
        intercept=mean_y-slope*mean_x
        residuals=[{'evaluation_id':r['evaluation_id'],'fitted':intercept+slope*r['points'],'difference':r['target']-(intercept+slope*r['points'])} for r in references]
        if not all(math.isfinite(v) for v in [slope,intercept,*[r['difference'] for r in residuals]]):raise OverflowError
    except OverflowError:return {**base,'message':'These target magnitudes cannot be fitted reliably. Edit the target values.'}
    return {**base,'status':'ready','message':f'{len(references)} reference models define your approximate scale.',
            'slope':slope,'intercept':intercept,'min_points':min(xs),'max_points':max(xs),'residuals':residuals}


def document(root):
    return calibration.read(Path(root)/'model-scale.json',{'version':1,'references':[],'revision':None})


def evaluations(root,rows,jobs=(),now=None):
    root=Path(root);now=time.time() if now is None else now
    live={j['id']:j for j in jobs};output=[]
    for path in sorted((root/'evaluations').glob('*.json')):
        manifest=calibration.read(path,{})
        if not manifest.get('id') or not manifest.get('expected'):continue
        job={**manifest,**live.get(manifest['id'],{})}
        expected=score_weights.enrich(root,manifest['expected'])
        score=hour_score.score(job,rows,expected,now)
        details=job.get('run_details') or run_editor.snapshot(root,job['id']) or {}
        values=details.get('values',{})
        points=score['weighted_points']
        available=type(points) in (int,float) and math.isfinite(points) and score['state'] not in ('unavailable','not_started')
        output.append({'id':job['id'],'model':manifest['model'],'display_name':values.get('run_name') or values.get('model_name') or manifest['model'],
                       'created':manifest.get('created',0),'scope':manifest.get('scope',manifest['id']),
                       'benchmark_version':manifest.get('benchmark_version','unknown'),'questions':len(expected),
                       'hardware':hardware_records.recorded(root,manifest).get('label','Hardware not recorded'),
                       'points':points,'state':score['state'],'run_state':job.get('state'),'correct':score['points'],
                       'elapsed_s':score['elapsed_s'],'completed_questions':score['completed_questions'],
                       'scoring_policy':score['scoring_policy'],'timeouts':score['timeouts'],
                       'available':available,'unavailable_reason':None if available else 'This run needs a recorded score with known active time before you can assign a target.',
                       'config_hash':manifest.get('config_hash'),'bank_hash':calibration.digest(expected)})
    return sorted(output,key=lambda e:e['created'],reverse=True)


def report(root,rows,jobs=(),now=None):
    doc=document(root);references=doc['references'];fitted=fit(references)
    evs=evaluations(root,rows,jobs,now)
    by_id={r['evaluation_id']:r for r in references}
    for e in evs:
        ref=by_id.get(e['id']);e['reference']=ref;e['custom_score']=None;e['score_note']='Assign reference targets to estimate this score.'
        if not e['available']:e['score_note']=e['unavailable_reason']
        elif ref and ref['points']==e['points']:
            e['custom_score']=ref['target'];e['score_note']='Your assigned target'
        elif fitted['status']=='ready':
            value=fitted['intercept']+fitted['slope']*e['points']
            if math.isfinite(value):e['custom_score']=value
            e['score_note']='Estimated' if fitted['min_points']<=e['points']<=fitted['max_points'] else 'Extrapolated beyond your references'
            if ref:e['score_note']+=' · run score changed since target was saved'
        elif ref:e['score_note']='Run score changed since target was saved; add another reference to estimate.'
    return {'evaluations':evs,'references':references,'fit':fitted,'revision':doc.get('revision'),'method':METHOD}


def save(root,doc):
    root=Path(root);path=root/'model-scale.json'
    if path.exists():
        stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=root/'backups'/('model-scale-'+stamp+'.json');backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,backup)
    doc={**doc,'revision':uuid.uuid4().hex}
    calibration.write(path,doc)
    return doc


def set_reference(root,rows,body,jobs=()):
    with calibration.LOCK:
        ev=next((e for e in evaluations(root,rows,jobs) if e['id']==body.get('evaluation_id')),None)
        if not ev or not ev['available']:raise ValueError('Choose a run with a recorded Hourglass score and known active time.')
        target=body.get('target')
        if type(target) not in (int,float) or not math.isfinite(target):raise ValueError('Enter a finite number for your target.')
        if 'expected_points' in body and body['expected_points']!=ev['points']:
            raise ValueError('This run’s score changed. Refresh the scale, then assign the target to its updated score.')
        doc=document(root)
        refs=[r for r in doc['references'] if r['model']!=ev['model']]
        refs.append({k:ev[k] for k in ('model','display_name','points','state','elapsed_s','benchmark_version','scoring_policy','bank_hash','config_hash','hardware')}|
                    {'evaluation_id':ev['id'],'target':target,'recorded_at':dt.datetime.now(dt.timezone.utc).isoformat()})
        return save(root,{**doc,'references':refs})


def remove_reference(root,body,missing_ok=False):
    with calibration.LOCK:
        doc=document(root);refs=[r for r in doc['references'] if r['evaluation_id']!=body.get('evaluation_id')]
        if len(refs)==len(doc['references']):
            if missing_ok:return doc
            raise ValueError('That run has no saved target.')
        return save(root,{**doc,'references':refs})
