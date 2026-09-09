"""Controller-owned question deadlines; model servers are never signalled."""
import datetime as dt
import diagnostics
import hashlib
import json
import math
import os
import signal
import subprocess
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

LIMIT_S = 900
POLICY = 'question-900s-auto-advance-v1'
STOP_GRACE_S = 2


def configured_limit(job):
    value = job.get('question_timeout_s')
    if value is None:
        return None  # Historical manifests retain their original policy.
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('Question timeout must be a positive finite duration.')
    return value


def terminate_group(proc):
    """Cancel native Pi, then bound cleanup if a child ignores the signal."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    def force_if_needed():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    timer = threading.Timer(STOP_GRACE_S, force_if_needed)
    timer.daemon = True
    timer.start()
    return timer


def wait(proc, job, condition, deadline):
    hour = job.get('_hour_deadline_monotonic')
    boundary = min(x for x in (deadline, hour) if x is not None) if deadline is not None or hour is not None else None
    if boundary is None:
        return proc.wait(), False
    try:
        rc = proc.wait(timeout=max(0, boundary - time.monotonic()))
    except subprocess.TimeoutExpired:
        rc = None
    with condition:
        now = time.monotonic()
        if hour is not None and now >= hour:
            job.update(stop_requested=True, stop_reason='hour_limit')
        timed_out = deadline is not None and now >= deadline and not job.get('stop_requested')
        if timed_out:
            job['question_timeout_at'] = time.time()
        timer = terminate_group(proc) if rc is None else None
    rc = proc.wait() if rc is None else rc
    if timer is not None:
        try:os.killpg(proc.pid, 0)
        except ProcessLookupError:pass
        else:timer.join(STOP_GRACE_S + .1)
    return rc, timed_out


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def checkpoint(path, value):
    if not path:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False) + '\n')
    temporary.replace(path)


def timeout_record(root, manifest, job, tid, repeat, state, started, deadline, version):
    """Append a policy zero after cancellation, retaining the interrupted trace."""
    root = Path(root)
    expected = next(t for t in manifest['expected'] if t['task'] == tid)
    task = read_json(root / 'tasks' / tid / 'task.json', {})
    active = state.get('task') == tid and state.get('run') == repeat
    workdir = Path(state['workdir']) if active and state.get('workdir') else None
    # Only read a workspace created by this checkout, never a path from a model.
    if workdir is not None and not workdir.resolve().is_relative_to((root / 'sandboxes').resolve()):
        workdir = None
    isolation=state.get('diagnostic_isolation') or manifest.get('diagnostic_isolation')
    proof = read_json(diagnostics.source(root,workdir,'interrupted-pi-trace.json',isolation), {}) if workdir else {}
    metrics = proof.get('metrics', {})
    trace = proof.get('trace', [])
    now = time.time()
    run_id = state.get('run_id') if active else None
    run_id = run_id or dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    artifact = root / 'results' / tid / urllib.parse.quote(job['model'], safe='') / ('run-' + run_id)
    artifact.mkdir(parents=True, exist_ok=True)
    if (artifact / 'trace.json').exists():
        trace = read_json(artifact / 'trace.json', trace)
    partial=diagnostics.source(root,workdir,'partial-pi-trace.jsonl',isolation) if workdir else None
    if not proof and partial and partial.exists():
        for line in partial.read_text().splitlines():
            try: trace.append(json.loads(line))
            except ValueError: trace.append({'pi_output':line})
    trace.append({'question_timeout': {'limit_s': job['question_timeout_s'], 'deadline_at': deadline,
                                      'cancelled_at': job.get('question_timeout_at'), 'policy': POLICY}})
    (artifact / 'trace.json').write_text(json.dumps(trace, indent=1))
    if workdir:diagnostics.publish(root,workdir,artifact)
    if not (artifact / 'patch.diff').exists():
        (artifact / 'patch.diff').write_text('')
    if proof.get('stderr'):
        (artifact / 'stderr.txt').write_text(proof['stderr'])
    prov = state.get('provenance', {}) if active else {}
    duration = max(0, now - state.get('started', started)) if active else 0
    row = {**metrics, 'task': tid, 'model': job['model'], 'run': repeat, 'run_id': run_id,
           'evaluation_id': job['id'], 'model_config_hash': manifest.get('config_hash'),
           'scoring_policy':manifest.get('scoring_policy') or 'weighted-hour-v1',
           'benchmark_version': version, 'task_sha': expected['task_sha'],
           'artifact_dir': str(artifact.relative_to(root)), 'kind': task.get('kind', 'mcq'),
           'section': task.get('section'), 'family': task.get('family'), 'tier': task.get('tier'),
           'mode': task.get('mode'), 'node': prov.get('node'), 'pi_version': prov.get('pi_version'),
           'status': 'timeout', 'solved': False, 'score_reason': 'question_timeout',
           'termination': 'question_timeout', 'parsed_answer': {}, 'tampered': [], 'patch_lines': 0,
           'verified_output': f"Question exceeded {job['question_timeout_s']:g} seconds; zero points; continuing to the next question.",
           'duration_s': round(duration, 3), 'prompt_tokens': metrics.get('prompt_tokens'),
           'completion_tokens': metrics.get('completion_tokens'), 'tool_calls': metrics.get('tool_calls'),
           'tok_per_s': None, 'question_timeout_s': job['question_timeout_s'],
           'question_timeout_policy': POLICY, 'question_started_at': started,
           'question_deadline_at': deadline, 'timeout_at': deadline,
           'attempted': active, 'trace_available': len(trace) > 1,
           'stop_after_wrong': job.get('stop_after_wrong'),
           'ts': dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat()}
    if isolation:row['diagnostic_isolation']=isolation
    row['combo_hash'] = hashlib.sha256(f'{job["id"]}|{tid}|{run_id}'.encode()).hexdigest()[:12]
    (artifact / 'metrics.json').write_text(json.dumps(row, indent=1))
    with (root / 'results' / 'results.jsonl').open('a') as output:
        output.write(json.dumps(row) + '\n')
    return row
