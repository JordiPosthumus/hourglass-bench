"""Freeze inference-machine identity separately from model settings and secrets."""
import datetime as dt
import hashlib
import json
import platform
import subprocess
import uuid
from urllib.parse import urlparse


def capture(root,config):
    profiles_path=root/'hardware-profiles.json'
    profiles=json.loads(profiles_path.read_text()) if profiles_path.exists() else {}
    endpoint=config.get('base_url','')
    profile=profiles.get(endpoint)
    label=config.get('hardware')
    if isinstance(label,str) and label.strip():
        label=label.strip()
        # Reuse an established identity when its recorded label is retained.
        if profile and profile.get('label')==label:
            identity=str(profile['machine_id'])
            result={k:profile[k] for k in ('chip','memory_bytes','cpu_cores','gpu') if k in profile}
        else:
            identity='hardware-label:'+label.casefold()
            result={}
        result.update(label=label,machine_key=hashlib.sha256(identity.encode()).hexdigest(),source='owner supplied')
    elif profile:
        # Remote hardware is owner supplied; never mistake the controller for the server.
        identity=profile.get('machine_id')
        if not identity:raise ValueError('Hardware profile requires a stable machine_id.')
        result={k:profile[k] for k in ('label','chip','memory_bytes','cpu_cores','gpu') if k in profile}
        result.update(machine_key=hashlib.sha256(str(identity).encode()).hexdigest(),source='owner supplied')
    elif urlparse(endpoint).hostname in ('localhost','127.0.0.1','::1'):
        identity_path=root/'.machine-id'
        if not identity_path.exists():
            try:
                with identity_path.open('x') as f:f.write(uuid.uuid4().hex+'\n')
            except FileExistsError:pass
        identity=identity_path.read_text().strip()
        result={'machine_key':hashlib.sha256(identity.encode()).hexdigest(),'source':'local system query','chip':platform.processor() or platform.machine()}
        if platform.system()=='Darwin':
            def query(key):return subprocess.check_output(['/usr/sbin/sysctl','-n',key],text=True,timeout=5,stderr=subprocess.DEVNULL).strip()
            try:result.update(chip=query('machdep.cpu.brand_string'),memory_bytes=int(query('hw.memsize')),cpu_cores=int(query('hw.physicalcpu')))
            except (OSError,subprocess.SubprocessError,ValueError):return None
        if platform.system()=='Darwin':
            try:
                displays=json.loads(subprocess.check_output(['/usr/sbin/system_profiler','SPDisplaysDataType','-json'],text=True,timeout=10,stderr=subprocess.DEVNULL)).get('SPDisplaysDataType',[])
                result['gpu']=[{'model':d.get('sppci_model'),'cores':d.get('sppci_cores')} for d in displays]
            except (OSError,subprocess.SubprocessError,ValueError):pass
        result['label']=result['chip']+(f" · {result['memory_bytes']/1024**3:g} GiB" if result.get('memory_bytes') else '')
    else:return None
    result['captured_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    return result


def recorded(root,manifest):
    import run_editor
    path=root/'hardware-records'/(manifest['id']+'.json')
    attachment=json.loads(path.read_text()) if path.exists() else None
    current=attachment if attachment and attachment.get('source')=='owner recorded' else manifest.get('hardware') or attachment or {'machine_key':'unknown-'+hashlib.sha256(manifest['id'].encode()).hexdigest(),'label':'Hardware not recorded','source':'unknown'}
    details=run_editor.snapshot(root,manifest['id'])
    label=(details or {}).get('values',{}).get('hardware')
    if label and label!=current.get('label') and (not attachment or attachment.get('run_editor_hardware')!=label):
        current={'label':label,'machine_key':hashlib.sha256(('hardware-label:'+label.casefold()).encode()).hexdigest(),'source':'owner recorded','captured_at':dt.datetime.fromtimestamp(details['recorded_at'],dt.timezone.utc).isoformat()}
    return current


def revision(record):
    return hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()


def save_user_record(root,manifest,fields,known_machines,expected_revision):
    """An explicit per-run amendment; preserve frozen metadata and back up the prior view."""
    import math
    import shutil
    current=recorded(root,manifest)
    if revision(current)!=expected_revision:raise ValueError('Hardware changed since this preview. Refresh before saving.')
    def string(key,required=False):
        value=fields.get(key,'')
        if not isinstance(value,str) or len(value)>160 or any(ord(c)<32 for c in value):raise ValueError('Invalid '+key+'.')
        value=value.strip()
        if required and not value:raise ValueError(key+' is required.')
        return value
    if fields.get('label_only'):
        label=string('label',True)
        if label==current.get('label') and current.get('source')!='unknown':
            result=dict(current)
        else:
            result={'machine_key':hashlib.sha256(('hardware-label:'+label.casefold()).encode()).hexdigest(),'label':label}
        result.update(source='owner recorded',captured_at=dt.datetime.now(dt.timezone.utc).isoformat())
    else:
        machine=fields.get('machine_key')
        if machine=='new':machine=hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()
        elif machine not in known_machines:raise ValueError('Select a recorded machine or create a new one.')
        result={'machine_key':machine,'label':string('label',True),'chip':string('chip'),'source':'owner recorded','captured_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        for source,target,multiplier in [('memory_gib','memory_bytes',1024**3),('cpu_cores','cpu_cores',1)]:
            value=fields.get(source)
            if value in (None,''):continue
            if isinstance(value,bool):raise ValueError('Invalid '+source+'.')
            try:number=float(value)
            except (TypeError,ValueError):raise ValueError('Invalid '+source+'.')
            if not math.isfinite(number) or number<=0 or number>1000000 or (source=='cpu_cores' and not number.is_integer()):raise ValueError('Invalid '+source+'.')
            result[target]=round(number*multiplier)
        gpu=string('gpu')
        if gpu:result['gpu']=[{'model':gpu}]
    import run_editor
    details=run_editor.snapshot(root,manifest['id'])
    if details:result['run_editor_hardware']=details['values'].get('hardware')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=root/'backups'/('hardware-amendment-'+stamp);backup.mkdir(parents=True)
    (backup/'previous-effective-hardware.json').write_text(json.dumps(current,indent=2)+'\n')
    (backup/'DELTA.txt').write_text('Owner recorded hardware for evaluation '+manifest['id']+'. Frozen manifest and model settings remain unchanged. Restore the prior sidecar, or remove the new one if no sidecar existed, while no hardware edit is in progress.\n')
    path=root/'hardware-records'/(manifest['id']+'.json');path.parent.mkdir(exist_ok=True)
    if path.exists():shutil.copy2(path,backup/path.name)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,indent=2)+'\n');temporary.replace(path)
    return result
