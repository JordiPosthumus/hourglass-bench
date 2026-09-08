"""User observations are append-only and separate from measured server settings."""
import datetime as dt
import json
import math
import uuid
from pathlib import Path

NUMERIC={'temperature':(0,None),'top_p':(0,1),'top_k':(0,None),'min_p':(0,1),'repetition_penalty':(0,None)}

def records(root,jid):
    path=Path(root)/'evaluations'/(jid+'.settings.jsonl')
    if not path.exists():return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def append(root,manifest,body,now=None):
    when=now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    applies=body.get('applies_from')
    if applies not in ('run_start','now'):raise ValueError('Choose whether these settings applied from the start or changed now.')
    if applies=='now' and manifest.get('state')!='running':raise ValueError('Only an active run can record settings changing now.')
    if applies=='run_start' and not manifest.get('started'):raise ValueError('This run has not started yet.')
    supplied=body.get('settings')
    if not isinstance(supplied,dict):raise ValueError('Settings must be an object.')
    clean={}
    if set(supplied)-set(NUMERIC)-{'reasoning'}:raise ValueError('Unknown sampling setting.')
    for name,value in supplied.items():
        if value is None or value=='':continue
        if name=='reasoning':
            if not isinstance(value,str) or len(value)>200:raise ValueError('Reasoning settings must be text, up to 200 characters.')
            if value.strip():clean[name]=value.strip()
            continue
        low,high=NUMERIC[name]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<low or (high is not None and value>high):raise ValueError('Invalid '+name+' value.')
        if name=='top_k' and int(value)!=value:raise ValueError('top_k must be an integer.')
        clean[name]=value
    if not clean:raise ValueError('Enter at least one setting; blank fields remain unknown.')
    note=body.get('note','')
    if not isinstance(note,str) or len(note)>1000:raise ValueError('Source note must be text, up to 1000 characters.')
    record={'id':uuid.uuid4().hex,'source':'user_reported','evaluation_id':manifest['id'],
            'recorded_at':when,'effective_at':manifest['started'] if applies=='run_start' else when,
            'applies_from':applies,'settings':clean,'note':note.strip()}
    path=Path(root)/'evaluations'/(manifest['id']+'.settings.jsonl')
    with path.open('a') as f:
        f.write(json.dumps(record,allow_nan=False)+'\n');f.flush()
    return record
