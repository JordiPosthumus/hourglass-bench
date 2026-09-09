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
    if profile:
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
    if manifest.get('hardware'):return manifest['hardware']
    path=root/'hardware-records'/(manifest['id']+'.json')
    if path.exists():return json.loads(path.read_text())
    return {'machine_key':'unknown-'+hashlib.sha256(manifest['id'].encode()).hexdigest(),'label':'Hardware not recorded','source':'unknown'}
