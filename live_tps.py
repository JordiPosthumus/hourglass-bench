"""Passive server-log telemetry: no inference requests or server changes."""
import json
import math
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

REMOTE = '''import json,os,sys
p=sys.argv[1]; offset=int(sys.argv[2]); size=os.path.getsize(p)
if offset<0: offset=size
if offset>size: offset=0
with open(p,'rb') as f:
 f.seek(offset); data=f.read(262144)
end=data.rfind(b'\\n')+1
print(json.dumps({'offset':offset+end,'lines':data[:end].decode('utf-8','replace').splitlines()}))
'''
DECODE = re.compile(r'decoding chunk=([0-9.]+) t/s avg=([0-9.]+) t/s')

def parse(line, at):
    match=DECODE.search(line)
    if match:
        chunk,average=map(float,match.groups())
        if all(math.isfinite(v) and v>=0 for v in (chunk,average)):
            return {'at':at,'server_stamp':line[:13],'phase':'decode','tps':chunk,'request_avg_tps':average}
    for pattern,phase in (('prompt start','prefill'),('prompt done','waiting'),('finish=','finished')):
        if pattern in line:return {'at':at,'server_stamp':line[:13],'phase':phase,'tps':None}
    return None


def poll(source, offset):
    command='python3 -c '+shlex.quote(REMOTE)+' '+shlex.quote(source['log_path'])+' '+str(offset)
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=3',source['ssh_host'],command],capture_output=True,text=True,timeout=5,check=True)
    doc=json.loads(result.stdout)
    return doc['offset'],[s for line in doc['lines'] if (s:=parse(line,time.time()))]


def source_for(root,job):
    root=Path(root)
    try:sources=json.loads((root/'telemetry-sources.json').read_text())
    except (OSError,ValueError):sources={}
    if not isinstance(sources,dict):return None
    try:manifest=json.loads((root/'evaluations'/(job['id']+'.json')).read_text())
    except (OSError,ValueError):manifest=job
    config=manifest.get('model_config_snapshot') or {}
    endpoint=(config.get('base_url') or '').rstrip('/')
    endpoints=sources.get('_endpoints',{})
    source=sources.get(job['model']) or (endpoints.get(endpoint) if isinstance(endpoints,dict) else None)
    if not isinstance(source,dict):return None
    return {**source,'model_id':config.get('model') or manifest.get('model_id')}


def collect(root,job,condition):
    source=source_for(root,job)
    if not source:
        job['_telemetry_error']='Live TPS is not connected for this endpoint.'
        return
    if source.get('type')=='lmstudio':
        import lmstudio_telemetry
        lmstudio_telemetry.collect(root,job,source,condition)
        return
    path=root/'logs'/f"tps-{job['id']}.jsonl"
    offset=-1
    while job.get('state')=='running':
        try:
            offset,samples=poll(source,offset)
            if samples:
                with path.open('a') as output:
                    for sample in samples:output.write(json.dumps({**sample,'task':job.get('current_task')})+'\n')
            job['_telemetry_error']=None
        except (OSError,ValueError,subprocess.SubprocessError):job['_telemetry_error']='Server log unavailable; retrying.'
        with condition:
            if job.get('state')!='running':return
            condition.wait(timeout=2)


def snapshot(root,job):
    path=root/'logs'/f"tps-{job['id']}.jsonl"
    samples=[]
    if path.exists():
        with path.open('rb') as f:
            size=f.seek(0,2);f.seek(max(0,size-120000))
            if size>120000:f.readline()
            for line in f:
                try:samples.append(json.loads(line))
                except ValueError:pass
    try:phase=json.loads((root/'logs'/f"phase-{job['id']}.json").read_text())
    except (OSError,ValueError):phase={}
    samples=samples[-400:]
    latest=next((s for s in reversed(samples) if s.get('tps') is not None),None)
    status=next((s for s in reversed(samples) if s.get('phase')=='telemetry_status'),None)
    return {'samples':samples,'latest':latest,'phase':phase.get('phase'),'tool':phase.get('tool'),
            'stale':latest is None or time.time()-latest['at']>10 or job.get('state')!='running',
            'error':(status or {}).get('error') or job.get('_telemetry_error') or (None if latest or source_for(root,job) else 'Live TPS is not connected for this endpoint.'),
            'concurrency':(status or {}).get('observed_requests'),'status':status,
            'note':'Measured server decode speed. Request overlap is scoped to the observed server; other GPU workloads are not measured.'}
