"""Reversible removal of selected attempts, retaining raw diagnostic artifacts."""
import datetime as dt
import fcntl
import hashlib
import json
import uuid
import repair_runs
from pathlib import Path


def snapshot(root):
    root=Path(root)
    path=root/'results/results.jsonl'
    data=path.read_bytes() if path.exists() else b''
    rows=[]
    for line in data.splitlines():
        try: row=json.loads(line)
        except ValueError: continue
        if isinstance(row,dict) and row.get('run_id'): rows.append(row)
    ledger=root/'results/reset-ledger.json'
    history=json.loads(ledger.read_text()) if ledger.exists() else []
    return {'revision':hashlib.sha256(data).hexdigest(),'attempts':rows,'history':history}


def reset(root, body):
    root=Path(root)
    ids=body.get('attempts')
    if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids):
        raise ValueError('Select at least one recorded attempt.')
    reason=str(body.get('reason','')).strip()
    if not reason: raise ValueError('Describe why these results are being reset.')
    with (root/'.run.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Wait for active model work to finish.')
        state=snapshot(root)
        if body.get('revision')!=state['revision']: raise ValueError('Results changed. Refresh and review the selection again.')
        ids=set(ids); removed=[r for r in state['attempts'] if r['run_id'] in ids]
        if {r['run_id'] for r in removed}!=ids: raise ValueError('An attempt is no longer available.')
        jobs=sorted({r.get('evaluation_id') for r in removed if r.get('evaluation_id')})
        if any(repair_runs.dependencies(root,jid) for jid in jobs):raise ValueError('This original has linked repairs. Clear the linked repairs first.')
        stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=root/'backups'/('reset-attempts-'+stamp);backup.mkdir(parents=True)
        index=root/'results/results.jsonl'; data=index.read_bytes()
        ledger=root/'results/reset-ledger.json'
        (backup/'results-before.jsonl').write_bytes(data)
        (backup/'reset-ledger-before.json').write_bytes(ledger.read_bytes() if ledger.exists() else b'[]')
        record={'id':uuid.uuid4().hex,'at':stamp,'reason':reason,'attempts':sorted(ids),'jobs':jobs,'backup':str(backup.relative_to(root)),
                'plans':[{'job':jid,'model':next(r['model'] for r in removed if r.get('evaluation_id')==jid),'tasks':sorted({r['task'] for r in removed if r.get('evaluation_id')==jid})} for jid in jobs]}
        manifests=[]
        for jid in jobs:
            if '/' in jid or '..' in jid: raise ValueError('Invalid evaluation ID')
            path=root/'evaluations'/(jid+'.json')
            if path.exists():
                original=path.read_bytes();(backup/path.name).write_bytes(original)
                doc=json.loads(original);doc['results_reset']=record['id'];manifests.append((path,doc))
        (backup/'removed-results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in removed))
        (backup/'reset.json').write_text(json.dumps(record,indent=2))
        for name in ('leaderboard.md','frontier.md'):
            path=root/name
            if path.exists():(backup/name).write_bytes(path.read_bytes())
        # Ledger is durable before removing index rows, so crash recovery cannot resurrect them.
        tmp=ledger.with_suffix('.tmp');tmp.write_text(json.dumps(state['history']+[record],indent=2));tmp.replace(ledger)
        for path,doc in manifests:
            tmp=path.with_suffix('.reset.tmp');tmp.write_text(json.dumps(doc,indent=2));tmp.replace(path)
        kept=[]
        for line in data.splitlines(keepends=True):
            try: row=json.loads(line)
            except ValueError: kept.append(line);continue
            if not isinstance(row,dict) or row.get('run_id') not in ids: kept.append(line)
        tmp=index.with_suffix('.reset.tmp');tmp.write_bytes(b''.join(kept));tmp.replace(index)
        (backup/'README.md').write_text('Selected results removed from the index. Raw artifacts are retained at their original paths. Before restoring the index, stop all benchmark work and restore the saved evaluation manifests and reset ledger together.\n')
        return {'ok':True,'removed_attempts':len(removed),**record}
