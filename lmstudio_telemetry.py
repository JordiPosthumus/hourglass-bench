"""Passive LM Studio timing/slot reader. Never stores prompts or sends inference."""
import datetime as dt
import json
import math
import re
import time
from pathlib import Path

STAMP = r'\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]'
INFO = re.compile('^'+STAMP+r'\[INFO\]\[([^\]]+)\] (Running chat completion|Finished streaming response)')
SLOT = re.compile(r'^(?:'+STAMP+r'\[DEBUG\]\s*)?(?:\d+\.){3}\d+\s+[IWD]\s+slot\s+(\w+):\s+id\s+(\d+)\s+\|\s+task\s+(-?\d+)\s+\|\s+(.*)$')
DECODE = re.compile(r'n_gen\s*=\s*(\d+),\s*tg\s*=\s*([\d.]+) t/s,\s*tg_3s\s*=\s*([\d.]+) t/s')


def timestamp(text):
    # LM Studio writes local wall time, including the machine's DST offset.
    return dt.datetime.strptime(text,'%Y-%m-%d %H:%M:%S').timestamp()


class Reader:
    def __init__(self, directory, model, started, intervals=None):
        self.directory=Path(directory).expanduser()
        self.model=model
        self.started=started
        self.slots={}
        self.pending=[]
        self.offsets={}
        self.last_at=None
        self.last_event_at=None
        self.last_model_event_at=None
        self.last_phase=None
        self.ambiguity=False
        self.intervals=intervals or [{'start':started,'end':None}]
        self.released=[]

    def active_at(self, at):
        # Log timestamps have one-second precision.
        return any(math.floor(p['start'])<=at and (p.get('end') is None or at<=math.ceil(p['end'])) for p in self.intervals)

    def parse(self,line):
        info=INFO.match(line)
        if info:
            stamp,model,event=info.groups();at=timestamp(stamp)
            self.last_at=at;self.last_event_at=at
            if model==self.model:self.last_model_event_at=at
            if event=='Running chat completion':
                self.pending.append({'model':model,'started':at})
            else:
                # Normally slot release precedes this line. Only consume a
                # pending request if it never acquired a slot (e.g. rejection).
                self.released=[p for p in self.released if at-p['at']<=3]
                credit=next((p for p in self.released if p['model']==model),None)
                if credit:self.released.remove(credit)
                else:
                    prior=next((p for p in self.pending if p['model']==model),None)
                    if prior:self.pending.remove(prior)
            return None
        match=SLOT.match(line)
        if not match:return None
        stamp,action,slot,task,detail=match.groups()
        at=timestamp(stamp) if stamp else self.last_at
        if at is None:return None
        self.last_at=at;self.last_event_at=at
        key=(slot,task)
        if action=='launch_slot_' and 'processing task' in detail and 'is_child = 1' not in detail:
            # Attribution is deliberately withheld if launches interleave
            # across different models and the log lacks a shared request ID.
            models={p['model'] for p in self.pending}
            if len(models)==1:
                request=self.pending.pop(0)
            else:
                request={'model':None,'started':at}
                self.ambiguity=True
            if key in self.slots:self.ambiguity=True
            request['phase']='prefill'
            self.slots[key]=request
            if request['model']==self.model:self.last_phase='prefill'
        request=self.slots.get(key)
        if not request and action=='print_timing' and ('n_gen' in detail or 'prompt processing' in detail):
            # Monitoring may begin after a request's launch record rotated out.
            # An observed decode must never be presented as zero active work.
            self.slots[key]={'model':None,'started':at,'phase':'unknown'}
            self.ambiguity=True
        if action=='release' and 'stop processing' in detail:
            self.slots.pop(key,None)
            if request:self.released.append({'model':request['model'],'at':at})
            if request and request['model']==self.model:
                self.last_phase='finished';self.last_model_event_at=at
            return None
        if not request or request['model']!=self.model:return None
        self.last_model_event_at=at
        if 'prompt processing' in detail:
            self.last_phase='prefill';request['phase']='prefill'
        decode=DECODE.search(detail)
        if not decode:return None
        generated,average,chunk=map(float,decode.groups())
        if not all(math.isfinite(v) and v>=0 for v in (generated,average,chunk)):return None
        self.last_phase='decode'
        request['phase']='decode'
        if not self.active_at(at) or not self.active_at(request['started']):return None
        return {'at':at,'server_stamp':dt.datetime.fromtimestamp(at).isoformat(),
                'phase':'decode','tps':chunk,'request_avg_tps':average,
                'output_tokens':int(generated),'slot':int(slot),'request_id':task,
                'model_id':self.model,'source':'LM Studio log','window_s':3,
                'observed_requests':len(self.slots)+len(self.pending)}

    def poll(self):
        files=sorted(self.directory.glob('*/*.log'),key=lambda p:(p.stat().st_mtime,p.name))
        if not files:raise FileNotFoundError('No LM Studio server logs found.')
        # Read logs covering this run plus the preceding rotation to establish
        # request ownership. Existing offsets make subsequent reads incremental.
        older=[p for p in files if p.stat().st_mtime<self.started]
        files=older[-1:]+[p for p in files if p.stat().st_mtime>=self.started]
        samples=[]
        for path in files:
            stat=path.stat();prior=self.offsets.get(str(path))
            if prior and (prior[0]!=stat.st_ino or stat.st_size<prior[1]):
                self.slots.clear();self.pending.clear();self.ambiguity=True
            offset=prior[1] if prior and prior[0]==stat.st_ino and stat.st_size>=prior[1] else 0
            with path.open('rb') as stream:
                stream.seek(offset)
                while True:
                    begin=stream.tell();line=stream.readline()
                    if not line:break
                    if not line.endswith(b'\n'):
                        stream.seek(begin);break
                    # Only metadata patterns are retained, never log text.
                    try:sample=self.parse(line.decode('utf-8','replace'))
                    except ValueError:continue
                    if sample:samples.append(sample)
                self.offsets[str(path)]=(stat.st_ino,stream.tell())
        return samples

    def status(self, error=None):
        count=len(self.slots)+len(self.pending)
        model_requests=sum(r['model']==self.model for r in [*self.slots.values(),*self.pending])
        phases=[r.get('phase','prefill') for r in self.slots.values() if r['model']==self.model]
        server_phase='decode' if 'decode' in phases else 'prefill' if phases or any(r['model']==self.model for r in self.pending) else self.last_phase
        return {'at':time.time(),'phase':'telemetry_status','tps':None,
                'source':'LM Studio log','model_id':self.model,
                'server_phase':server_phase,'last_server_event_at':self.last_event_at,
                'last_model_event_at':self.last_model_event_at,
                'observed_requests':None if error or self.ambiguity else count,
                'observed_model_requests':None if error or self.ambiguity else model_requests,
                'attribution':'ambiguous' if self.ambiguity else 'model_and_slot',
                'error':error,'other_gpu_workloads':'not_measured',
                'coverage':'Observed LM Studio requests; other GPU processes are not measured.'}


def collect(root, job, source, condition=None, follow_manifest=False):
    """Normal controller collector or a temporary attachment to a running job."""
    import fcntl
    root=Path(root);jid=job['id']
    if not jid.isalnum():raise ValueError('Invalid run ID.')
    path=root/'logs'/f'tps-{jid}.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    # A reattached collector and a restarted controller must never double-write.
    with (path.parent/f'tps-{jid}.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        reader=Reader(source['log_dir'],source['model_id'],job['started'],job.get('active_intervals'))
        seen=set()
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    row=json.loads(line)
                    if row.get('tps') is not None:seen.add((row.get('at'),row.get('slot'),row.get('request_id'),row.get('output_tokens')))
                except ValueError:pass
        while job.get('state')=='running':
            if follow_manifest:
                try:job=json.loads((root/'evaluations'/(jid+'.json')).read_text())
                except (OSError,ValueError):break
                if job.get('state')!='running':break
                active=job.get('active_question') or {}
                if active.get('token'):
                    try:receipt=json.loads((root/'logs'/f"worker-{jid}-{active['token']}.json").read_text())
                    except (OSError,ValueError):receipt={}
                    if receipt.get('controller_lost'):break
            error=None
            try:samples=reader.poll()
            except (OSError,ValueError) as exc:
                samples=[];error='LM Studio log unavailable; retrying.'
            with path.open('a') as output:
                for sample in samples:
                    key=(sample['at'],sample['slot'],sample['request_id'],sample['output_tokens'])
                    if key in seen:continue
                    seen.add(key);output.write(json.dumps(sample)+'\n')
                output.write(json.dumps(reader.status(error))+'\n');output.flush()
            if condition:
                with condition:
                    if job.get('state')!='running':break
                    condition.wait(timeout=2)
            else:time.sleep(2)


if __name__=='__main__':
    import argparse
    import live_tps
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--job',required=True)
    args=parser.parse_args()
    if not args.job.isalnum():parser.error('Invalid run ID')
    job=json.loads((args.root/'evaluations'/(args.job+'.json')).read_text())
    source=live_tps.source_for(args.root,job)
    if not source or source.get('type')!='lmstudio':parser.error('No LM Studio telemetry source configured')
    collect(args.root,job,source,follow_manifest=True)
