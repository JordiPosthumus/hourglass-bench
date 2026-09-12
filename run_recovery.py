import diagnostics
"""Recover a closed workload interval from a persisted, stopped Pi trace."""
import copy
import datetime as dt
import hashlib
import json
import math
from pathlib import Path


def read_rows(root, jid):
    path=Path(root)/'results'/'results.jsonl'
    rows=[]
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                record=json.loads(line)
                if isinstance(record,dict) and record.get('evaluation_id')==jid:rows.append(record)
            except ValueError:pass
    return rows


def recover_receipt(root, manifest):
    try:
        context=manifest['active_question'];token=context['token'];jid=manifest['id']
        if not isinstance(token,str) or not isinstance(jid,str) or not token.isalnum() or not jid.isalnum():return None
        file=Path(root)/'logs'/f'worker-{jid}-{token}.json'
        receipt=json.loads(file.read_text())
        if receipt.get('version')!='worker-lifecycle-v1' or receipt.get('phase') not in ('stopped','completed','error'):return None
        if any(receipt.get(k)!=value for k,value in [('evaluation_id',jid),('token',token),('task',context['task']),('started_at',context['started_at'])]):return None
        intervals=copy.deepcopy(manifest['active_intervals'])
        if not intervals or intervals[-1].get('end') is not None:return None
        ended=receipt['ended_at'];duration=receipt['elapsed_s'];started=context['started_at']
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (ended,duration,started)):return None
        if any(type(p.get('start')) not in (int,float) or not math.isfinite(p['start']) for p in intervals):return None
        if not intervals[-1]['start']<=started<=ended or duration<0 or abs(duration-(ended-started))>2:return None
        before=context.get('elapsed_before_s',0)
        if type(before) not in (int,float) or not math.isfinite(before) or before<0:return None
        for index,part in enumerate(intervals[:-1]):
            if type(part.get('end')) not in (int,float) or not math.isfinite(part['end']):return None
            if not part['start']<=part['end']<=intervals[index+1]['start']:return None
        rows=read_rows(root,jid)
        if any(dt.datetime.fromisoformat(r['ts']).timestamp()>ended for r in rows):return None
        intervals[-1]['end']=ended
        recovered=copy.deepcopy(manifest)
        recovered.setdefault('question_elapsed_s',{})[context.get('elapsed_key',context['task'])]=context.get('elapsed_before_s',0)+duration
        recovered.update(state='stopped',ended=ended,active_started=None,active_intervals=intervals,
                         hour_timing_unknown=False,elapsed_s=(manifest.get('repair') or {}).get('base_elapsed_s',0)+sum(p['end']-p['start'] for p in intervals),
                         current_task=context['task'],error=None,rc=130,stop_requested=False,
                         stop_reason='controller_interrupted',completed_tasks=len({r['task'] for r in rows if r.get('status')=='completed'}))
        evidence={'version':'worker-receipt-recovery-v1','task':context['task'],'worker_ended_at':ended,
                  'active_seconds':recovered['elapsed_s'],'question_seconds_charged':duration,
                  'receipt_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                  'note':'Recovered from the matching worker exit receipt. Completed answers retained; downtime excluded.'}
        recovered.setdefault('timing_recoveries',[]).append(evidence)
        return recovered,{**evidence,'files':[file]}
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return None


def recover(root, manifest):
    """Return a recovered manifest and evidence, or None when proof is incomplete.

    A last activity timestamp is insufficient. The adapter must have received a
    stopped result, waited for its child to exit, and persisted its shutdown trace.
    """
    if not manifest.get('hour_timing_unknown'):
        return None
    root = Path(root).resolve()
    if manifest.get('active_question'):
        return recover_receipt(root,manifest)
    try:
        intervals = copy.deepcopy(manifest['active_intervals'])
        if not intervals or intervals[-1].get('end') is not None:
            return None
        start = intervals[-1]['start']
        for i, part in enumerate(intervals):
            end = part.get('end')
            if not isinstance(part['start'], (int, float)) or not math.isfinite(part['start']):
                return None
            if i < len(intervals)-1 and (not isinstance(end, (int, float)) or not math.isfinite(end) or end < part['start'] or end > intervals[i+1]['start']):
                return None
        jid = manifest['id']
        attempt_path = root/'logs'/f'attempt-{jid}.json'
        phase_path = root/'logs'/f'phase-{jid}.json'
        attempt = json.loads(attempt_path.read_text())
        phase = json.loads(phase_path.read_text())
        workdir = Path(attempt['workdir']).resolve()
        if not workdir.is_relative_to(root/'sandboxes'):
            return None
        if attempt['task'] not in {t['task'] for t in manifest['expected']}:
            return None
        proof_path = diagnostics.source(root,workdir,'interrupted-pi-trace.json',attempt.get('diagnostic_isolation') or manifest.get('diagnostic_isolation'))
        proof_bytes = proof_path.read_bytes()
        proof = json.loads(proof_bytes)
        finished = proof['trace'][-1].get('result', {})
        if finished.get('termination') != 'stopped' or finished.get('answer'):
            return None
        if phase.get('phase') != 'finished':
            return None
        metrics = proof['metrics']
        if metrics.get('usage_complete') is not False or metrics.get('tool_calls') != phase.get('tool_calls') or metrics.get('completion_tokens') != phase.get('completed_output_tokens'):
            return None
        # Trace persistence follows child exit. Include that cleanup in used time.
        ended = proof_path.stat().st_mtime
        if not start <= attempt['started'] <= phase['at'] <= ended <= phase['at'] + 60:
            return None
        rows = read_rows(root,jid)
        timestamps = [dt.datetime.fromisoformat(r['ts']).timestamp() for r in rows]
        if any(t > attempt['started'] for t in timestamps):
            return None  # Evidence belongs to an older attempt.
        if any(r.get('run_id') == attempt.get('run_id') for r in rows):
            return None  # Already recorded; never double-charge a finished attempt.
        intervals[-1]['end'] = ended
        recovered = copy.deepcopy(manifest)
        # Include startup before the last attempt and preserve earlier repeats.
        # When the question start was lost, the preceding completion is a
        # conservative boundary; disclose the small extra startup charge.
        question_start = max([start] + [t for t in timestamps if start <= t <= attempt['started']])
        question_elapsed = recovered.setdefault('question_elapsed_s', {})
        elapsed_key = f"{attempt['task']}:{attempt.get('run',1)}" if manifest.get('round_policy') else attempt['task']
        previous_question_seconds = question_elapsed.get(elapsed_key, 0)
        charged = ended - question_start
        question_elapsed[elapsed_key] = previous_question_seconds + charged
        recovered.update(state='stopped', ended=ended, active_started=None,
                         active_intervals=intervals, hour_timing_unknown=False,
                         elapsed_s=(manifest.get('repair') or {}).get('base_elapsed_s',0)+sum(p['end']-p['start'] for p in intervals),
                         current_task=attempt['task'], error=None, rc=130,
                         stop_reason='controller_interrupted', stop_requested=False,
                         completed_tasks=len({r['task'] for r in rows if r.get('status') == 'completed'}))
        evidence = {
            'version': 'stopped-pi-recovery-v1', 'run_id': attempt.get('run_id'),
            'task': attempt['task'], 'phase_finished_at': phase['at'],
            'trace_persisted_at': ended, 'active_seconds': recovered['elapsed_s'],
            'question_seconds_charged': charged,
            'question_startup_allowance_s': attempt['started']-question_start,
            'trace_sha256': hashlib.sha256(proof_bytes).hexdigest(),
            'note': 'Recovered through shutdown-trace persistence after Pi stopped. Completed answers retained; downtime excluded. Interrupted question includes startup from the preceding saved completion.'}
        recovered.setdefault('timing_recoveries', []).append(evidence)
        return recovered, {**evidence, 'files': [attempt_path, phase_path, proof_path]}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
