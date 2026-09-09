"""Recover a closed workload interval from a persisted, stopped Pi trace."""
import copy
import datetime as dt
import hashlib
import json
import math
from pathlib import Path


def recover(root, manifest):
    """Return a recovered manifest and evidence, or None when proof is incomplete.

    A last activity timestamp is insufficient. The adapter must have received a
    stopped result, waited for its child to exit, and persisted its shutdown trace.
    """
    if not manifest.get('hour_timing_unknown'):
        return None
    root = Path(root).resolve()
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
        proof_path = workdir/'interrupted-pi-trace.json'
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
        records_path = root/'results'/'results.jsonl'
        records = [json.loads(line) for line in records_path.read_text().splitlines() if line.strip()] if records_path.exists() else []
        rows = [r for r in records if r.get('evaluation_id') == jid]
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
        previous_question_seconds = question_elapsed.get(attempt['task'], 0)
        charged = ended - question_start
        question_elapsed[attempt['task']] = previous_question_seconds + charged
        recovered.update(state='stopped', ended=ended, active_started=None,
                         active_intervals=intervals, hour_timing_unknown=False,
                         elapsed_s=sum(p['end']-p['start'] for p in intervals),
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
