"""Passive server-log telemetry: no inference requests or server changes."""
import json
import math
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
    try:manifest=json.loads((root/'evaluations'/(job['id']+'.json')).read_text())
    except (OSError,ValueError):manifest=job
    config=manifest.get('model_config_snapshot') or {}
    return source_for_config(root,config,job.get('model'),manifest.get('model_id'))


def endpoint_key(value):
    parts=urlsplit(value.rstrip('/'))
    if parts.hostname=='localhost':
        parts=parts._replace(netloc='127.0.0.1'+(':'+str(parts.port) if parts.port else ''))
    return urlunsplit(parts)


def source_for_config(root,config,name=None,model_id=None):
    try:sources=json.loads((Path(root)/'telemetry-sources.json').read_text())
    except (OSError,ValueError):sources={}
    if not isinstance(sources,dict):return None
    endpoint=(config.get('base_url') or '').rstrip('/')
    endpoints=sources.get('_endpoints',{})
    endpoint_source=next((value for key,value in endpoints.items() if endpoint_key(key)==endpoint_key(endpoint)),None) if isinstance(endpoints,dict) else None
    profile=config.get('inference_profile') or {}
    route=profile.get('route') or {}
    routes=sources.get('_routes',{})
    route_sources=next((value for key,value in routes.items() if endpoint_key(key)==endpoint_key(endpoint)),{}) if isinstance(routes,dict) else {}
    route_source=route_sources.get(route.get('name')) if route.get('kind')=='dsg' and isinstance(route_sources,dict) else None
    source=sources.get(name or config.get('name')) or route_source or endpoint_source
    if not isinstance(source,dict):
        backend=profile.get('backend')
        if endpoint and backend in ('mtplx','omlx','vllm','sglang','llamacpp','ollama') and route.get('kind')!='dsg':
            source={'type':backend,'base_url':endpoint}
        else:return None
    destination=source.get('base_url',endpoint)
    original_origin=urlsplit(endpoint_key(endpoint))[:2]
    destination_origin=urlsplit(endpoint_key(destination))[:2]
    # A distinct metrics origin needs its own explicit credential, if any.
    key=config.get('api_key') if original_origin==destination_origin else None
    return {'base_url':endpoint,'api_key':key,**source,
            'model_id':config.get('model') or model_id}


def collect(root,job,condition):
    source=source_for(root,job)
    if not source:
        job['_telemetry_error']='Live TPS is not connected for this endpoint.'
        return
    if source.get('type')=='lmstudio':
        import lmstudio_telemetry
        lmstudio_telemetry.collect(root,job,source,condition)
        return
    if source.get('type') in ('mtplx','omlx','vllm','sglang','llamacpp','ollama','dsg'):
        import endpoint_telemetry
        endpoint_telemetry.collect(root,job,source,condition)
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
            'error':status.get('error') if status else job.get('_telemetry_error') or (None if latest or source_for(root,job) else 'Live TPS is not connected for this endpoint.'),
            'concurrency':(status or {}).get('observed_requests'),'status':status,
            'note':'Measured server decode speed. Request overlap is scoped to the observed server; other GPU workloads are not measured.'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Attach passive telemetry to an active run without restarting it.')
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--job',required=True)
    args=parser.parse_args()
    if not args.job.isalnum():parser.error('Invalid run ID.')
    job=json.loads((args.root/'evaluations'/(args.job+'.json')).read_text())
    source=source_for(args.root,job)
    if not source:parser.error('No telemetry source is available for this endpoint.')
    if source.get('type')=='lmstudio':
        import lmstudio_telemetry
        lmstudio_telemetry.collect(args.root,job,source,follow_manifest=True)
    elif source.get('type') in ('mtplx','omlx','vllm','sglang','llamacpp','ollama','dsg'):
        import endpoint_telemetry
        endpoint_telemetry.collect(args.root,job,source,follow_manifest=True)
    else:
        parser.error('Standalone attachment supports HTTP and LM Studio telemetry; legacy SSH logs are collected by the controller.')
