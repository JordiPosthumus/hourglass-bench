"""Append-only, user-reported run details and persistent reusable choices."""
import run_naming
import json
import math
import threading
import time
import uuid
from pathlib import Path

LOCK=threading.RLock()
FIELDS={'run_name':'Run name','model_name':'Model name','model_revision':'Model revision / source','quantization':'Quantization','server_name':'Server name','server_version':'Server version / PR','hardware':'Hardware','temperature':'Temperature','top_p':'Top p','top_k':'Top k','min_p':'Min p','repetition_penalty':'Repetition penalty','seed':'Seed','context_limit':'Context limit','output_limit':'Output limit','reasoning':'Reasoning mode / budget','concurrency':'Concurrency','cache':'Cache / speculative decoding','notes':'Notes'}
NUMBERS={'temperature':(0,None),'top_p':(0,1),'top_k':(0,None),'min_p':(0,1),'repetition_penalty':(0,None),'seed':(None,None),'context_limit':(1,None),'output_limit':(1,None),'concurrency':(1,None)}
INTEGERS={'top_k','seed','context_limit','output_limit','concurrency'}

def read_lines(path):
    if not path.exists():return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def append_line(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as f:f.write(json.dumps(value,allow_nan=False)+'\n');f.flush()

def clean(values):
    if not isinstance(values,dict) or set(values)-set(FIELDS):raise ValueError('Unknown run detail.')
    output={}
    for key,value in values.items():
        if value is None or value=='':continue
        if key in NUMBERS:
            low,high=NUMBERS[key]
            if type(value) not in (int,float) or not math.isfinite(value) or low is not None and value<low or high is not None and value>high or key in INTEGERS and int(value)!=value:raise ValueError('Invalid '+FIELDS[key]+'.')
        elif key=='run_name' and (not isinstance(value,str) or len(value)>500 or any(ord(c)<32 for c in value)):raise ValueError('Run names must be one line of at most 500 characters.')
        elif not isinstance(value,str) or len(value)>2000:raise ValueError('Text fields must contain at most 2000 characters.')
        elif not value.strip():continue
        else:value=value.strip()
        if key in run_naming.IDENTITY_FIELDS:value=run_naming.normalize(key,value)
        output[key]=value
    return output

def history(root,jid):
    if not isinstance(jid,str) or not jid.isalnum():raise ValueError('Invalid run ID.')
    return read_lines(Path(root)/'evaluations'/(jid+'.details.jsonl'))

def snapshot(root,jid):
    records=history(root,jid)
    return records[-1] if records else None

def catalog(root):
    return {'fields':FIELDS,'numeric':list(NUMBERS),'integer':list(INTEGERS),'choices':read_lines(Path(root)/'run-detail-choices.jsonl')}

def save(root,manifest,body):
    values=clean(body.get('values'));base=body.get('base_revision')
    timing=body.get('applies_from')
    if timing not in ('run_start','now'):raise ValueError('Choose when these details applied.')
    if timing=='now' and manifest.get('state')!='running':raise ValueError('Only an active run can record a change effective now.')
    note=body.get('reason','')
    if not isinstance(note,str) or len(note)>2000:raise ValueError('Change note must be text of at most 2000 characters.')
    with LOCK:
        current=snapshot(root,manifest['id'])
        if base!=(current or {}).get('id'):raise ValueError('This run was edited elsewhere. Reload before saving.')
        record={'id':uuid.uuid4().hex,'evaluation_id':manifest['id'],'recorded_at':time.time(),'effective_at':manifest.get('started') if timing=='run_start' else time.time(),'applies_from':timing,'source':'user_reported','values':values,'reason':note.strip(),'previous_revision':base}
        append_line(Path(root)/'evaluations'/(manifest['id']+'.details.jsonl'),record)
        choices=catalog(root)['choices']
        for key,value in values.items():
            if key in ('run_name','notes'):continue
            if not any(c['field']==key and c['value']==value for c in choices):
                choice={'id':uuid.uuid4().hex,'field':key,'value':value,'created_at':record['recorded_at']}
                append_line(Path(root)/'run-detail-choices.jsonl',choice);choices.append(choice)
        remember_setup(root,manifest,record)
        return record


PUBLIC_MAP={'model_name':'model_family','model_revision':'model_revision','run_name':'configuration','quantization':'quantization'}
PUBLIC_PARAMETERS=('temperature','top_p','top_k','min_p','repetition_penalty','seed','context_limit','output_limit','reasoning','concurrency','cache')

def display_values(root,manifest):
    current=snapshot(root,manifest['id'])
    values=dict((current or {}).get('values',{}))
    key=setup_key(manifest)
    shared=[r for r in read_lines(Path(root)/'run-detail-setups.jsonl') if key and r.get('key')==key]
    if shared:
        latest=max(shared,key=lambda r:r['recorded_at'])
        for field in (*run_naming.IDENTITY_FIELDS,'run_name'):
            values.pop(field,None)
            if field in latest['values']:values[field]=latest['values'][field]
    return values

def display(root,manifest):
    import hardware_records
    import hardware_groups
    values=display_values(root,manifest)
    if values.get('hardware'):values['hardware']=hardware_groups.canonical_label(root,values['hardware'])
    return run_naming.describe(manifest,values,hardware_records.recorded(root,manifest))

def public_labels(root,jid):
    """Only labeled report fields; never notes, endpoint URLs or configuration secrets."""
    record=snapshot(root,jid)
    path=Path(root)/'evaluations'/(jid+'.json')
    values=display_values(root,json.loads(path.read_text())) if path.exists() else (record or {}).get('values',{})
    labels={target:str(values[key])[:500] for key,target in PUBLIC_MAP.items() if key in values}
    engine=' · '.join(str(values[k]) for k in ('server_name','server_version') if values.get(k))
    if engine:labels['inference_engine']=engine[:500]
    parameters='; '.join(FIELDS[k]+': '+str(values[k]) for k in PUBLIC_PARAMETERS if k in values)
    if parameters:labels['parameters']=parameters[:500]
    path=Path(root)/'evaluations'/(jid+'.json')
    if path.exists():labels['configuration']=display(root,json.loads(path.read_text()))['name'][:500]
    return labels

def copy_setup(root,source,manifest):
    """Copy descriptive setup to a new run, preserving all original history."""
    import settings_records
    import results_history
    import hardware_records
    prior=snapshot(root,source['id'])
    if prior:
        save(root,manifest,{'values':dict(prior['values']),'applies_from':'run_start','reason':'Copied setup from run '+source['id']})
    previous=settings_records.records(root,source['id'])
    if previous:
        settings={}
        for record in sorted(previous,key=lambda r:(r.get('effective_at') or 0,r.get('recorded_at') or 0)):settings.update(record['settings'])
        append_line(Path(root)/'evaluations'/(manifest['id']+'.settings.jsonl'),{
            'id':uuid.uuid4().hex,'source':'user_reported','evaluation_id':manifest['id'],
            'recorded_at':time.time(),'effective_at':None,'applies_from':'run_start','settings':settings,
            'note':'Copied from run '+source['id']+'; confirm these settings still apply.','copied_from':source['id']})
    labels=results_history.load(root,source['id'])
    if labels:results_history.save(root,manifest['id'],labels)
    # Keep a per-run hardware amendment when it was recorded explicitly.
    attachment=Path(root)/'hardware-records'/(source['id']+'.json')
    if attachment.exists():
        hardware=hardware_records.recorded(root,source)
        target=Path(root)/'hardware-records'/(manifest['id']+'.json');target.parent.mkdir(parents=True,exist_ok=True)
        hardware={**hardware,'copied_from':source['id']}
        target.write_text(json.dumps(hardware,indent=2)+'\n')

def setup_key(manifest):
    """Exact execution configuration and recorded inference machine only."""
    import hashlib
    hardware=manifest.get('hardware') or {}
    if not manifest.get('config_hash') or not manifest.get('model'):return None
    identity={'model':manifest['model'],'config_hash':manifest['config_hash'],
              'machine':hardware.get('machine_key'),'hardware':hardware.get('label')}
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

def remember_setup(root,manifest,record):
    key=setup_key(manifest)
    if key:
        append_line(Path(root)/'run-detail-setups.jsonl',{'key':key,'source_run':manifest['id'],
                    'recorded_at':record['recorded_at'],'values':dict(record['values'])})

def reusable_setup(root,manifest):
    """Also discover pre-feature setups in surviving runs and deletion backups."""
    key=setup_key(manifest)
    if not key:return None
    root=Path(root)
    candidates=[r for r in read_lines(root/'run-detail-setups.jsonl') if r.get('key')==key]
    paths=list((root/'evaluations').glob('*.json'))+list((root/'backups').glob('cleared-run-*/evaluation.json'))
    for path in paths:
        try:
            previous=json.loads(path.read_text())
            if setup_key(previous)!=key or previous.get('id')==manifest.get('id'):continue
            records=read_lines(path.parent/(previous['id']+'.details.jsonl'))
            if records:
                r=records[-1]
                candidates.append({'key':key,'source_run':previous['id'],'recorded_at':r['recorded_at'],'values':r['values']})
        except (OSError,ValueError,KeyError,TypeError):continue
    return max(candidates,key=lambda r:r['recorded_at']) if candidates else None

def reuse_setup(root,manifest):
    with LOCK:
        if snapshot(root,manifest['id']):return None
        prior=reusable_setup(root,manifest)
        if prior is None:return None
        return save(root,manifest,{'values':prior['values'],'applies_from':'run_start',
                    'reason':'Reused saved editor setup from run '+prior['source_run']+' for the same configuration and hardware. Confirm reported details still apply.'})


def initial_identity(root,config):
    import calibration
    import hardware_records
    manifest={'id':'preview','model':config['name'],'model_id':config['model'],
              'config_hash':calibration.digest(config),'model_config_snapshot':config,
              'hardware':hardware_records.capture(root,config)}
    prior=reusable_setup(root,manifest)
    values=dict((prior or {}).get('values',{}))
    identity=run_naming.describe(manifest,values)
    return {'identity':identity,'values':{**identity['fields'],**{k:v for k,v in values.items() if k in (*run_naming.IDENTITY_FIELDS,'run_name')}}}


def required_identity(values):
    values=clean(values)
    if set(values)-set((*run_naming.IDENTITY_FIELDS,'run_name')):raise ValueError('Only naming fields are accepted here.')
    missing=[FIELDS[k] for k in ('hardware','server_name','model_name','quantization') if not values.get(k) or values[k].casefold()=='xxx']
    if missing:raise ValueError('Complete the configuration name before starting: '+', '.join(missing)+'.')
    return values
