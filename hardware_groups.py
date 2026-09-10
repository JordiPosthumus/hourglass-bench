"""Owner-defined comparison groups, independent of original physical identities."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import run_naming


def load(root):
    path=Path(root)/'hardware-groups.json'
    return json.loads(path.read_text()) if path.exists() else {'schema_version':1,'groups':[]}

def revision(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()

def key(label):
    return run_naming.hardware(label).casefold()

def apply(root,record):
    label=record.get('label','')
    groups=load(root)['groups']
    matches=[g for g in groups if key(label) in {key(a) for a in [g['label'],*g['aliases']]}]
    if len(matches)>1:raise ValueError('Hardware comparison aliases overlap; edit hardware groups.')
    if not matches:return record
    group=matches[0]
    return {**record,'original_label':record.get('original_label',label),'label':group['label'],
            'comparison_group':group['id'],'comparison_key':hashlib.sha256(('hardware-group:'+group['id']).encode()).hexdigest()}

def canonical_label(root,label):
    return apply(root,{'label':label})['label']

def snapshot(root):
    root=Path(root);doc=load(root);labels=set()
    for path in (root/'evaluations').glob('*.json'):
        try:
            m=json.loads(path.read_text())
            if isinstance(m.get('hardware'),dict) and m['hardware'].get('label'):labels.add(m['hardware']['label'])
        except (OSError,ValueError):continue
    for path in (root/'evaluations').glob('*.details.jsonl'):
        for line in path.read_text().splitlines():
            if line.strip():
                label=json.loads(line).get('values',{}).get('hardware')
                if label:labels.add(label)
    for path in (root/'hardware-records').glob('*.json'):
        record=json.loads(path.read_text())
        if record.get('label'):labels.add(record['label'])
    return {'document':doc,'revision':revision(doc),'observed_labels':sorted(labels,key=str.casefold)}

def save(root,body):
    root=Path(root);before=load(root)
    if body.get('revision')!=revision(before):raise ValueError('Hardware groups changed elsewhere. Reload before saving.')
    groups=body.get('groups')
    if not isinstance(groups,list) or len(groups)>200:raise ValueError('Provide at most 200 hardware groups.')
    used=set();ids=set();clean=[]
    for group in groups:
        if not isinstance(group,dict):raise ValueError('Invalid hardware group.')
        label=run_naming.normalize('hardware',group.get('label'))
        if not label:raise ValueError('Every comparison group needs a name.')
        gid=group.get('id') or uuid.uuid4().hex
        if not isinstance(gid,str) or not gid.isalnum() or len(gid)>80 or gid in ids:raise ValueError('Invalid or duplicate group ID.')
        ids.add(gid)
        aliases=group.get('aliases',[])
        if not isinstance(aliases,list) or len(aliases)>500:raise ValueError('Invalid aliases.')
        aliases=list(dict.fromkeys(run_naming.normalize('hardware',a) for a in aliases))
        if any(not a for a in aliases):raise ValueError('Alias names cannot be blank.')
        names={key(a) for a in [label,*aliases]}
        if used & names:raise ValueError('A hardware label can belong to only one comparison group.')
        used.update(names);clean.append({'id':gid,'label':label,'aliases':aliases})
    doc={'schema_version':1,'groups':clean}
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=root/'backups'/('hardware-groups-'+stamp);backup.mkdir(parents=True)
    target=root/'hardware-groups.json'
    if target.exists():shutil.copy2(target,backup/target.name)
    (backup/'change.json').write_text(json.dumps({'before':before,'after':doc,'effect':'Display names and comparison groups only; original runs and physical machine identities retained.'},indent=2)+'\n')
    tmp=target.with_name('hardware-groups.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(doc,indent=2)+'\n');tmp.replace(target)
    return snapshot(root)
