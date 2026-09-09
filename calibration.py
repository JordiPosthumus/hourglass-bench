"""Versioned calibration from complete, comparable evaluations. No model requests."""
import datetime as dt
import hashlib
import json
import math
import shutil
import threading
import uuid
import run_tracking
import score_weights
import scoring_policy
import hardware_records
from collections import Counter

LOCK = threading.RLock()
METHOD = 'equal-model-linear-v1'
MIN_ACCURACY_SPAN = 0.05


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def evaluation_manifest(root, job, version, config, legacy=False):
    expected = []
    for tid in sorted(job['tasks']):
        raw = (root / 'tasks' / tid / 'task.json').read_bytes()
        task = json.loads(raw)
        expected.append({'task': tid, 'task_sha': hashlib.sha256(raw).hexdigest()[:16],
                         'vision': task.get('kind') == 'chart-vqa' or bool(task.get('image') or task.get('assets')),
                         'section':task.get('section'),'tier':task.get('tier'),'level':task.get('level'),
                         'weight':score_weights.weight(task),'weight_version':score_weights.VERSION,
                         'repeat': job['repeat'] if job['repeat'] is not None else task.get('repeat', 3)})
    manifest = {'id': job['id'], 'model': job['model'], 'model_id': config['model'],
                'benchmark_version': version, 'expected': expected,
                'stop_after_wrong':job.get('stop_after_wrong'), 'order':job['tasks'],
                'created': job['created'], 'started': job.get('started'), 'state': job['state'],
                'config_hash': digest(config), 'legacy_time_match': legacy}
    manifest['hardware']=hardware_records.capture(root,config)
    manifest['scope'] = digest({'version': version, 'expected': expected, 'order':job['tasks'], 'stop_after_wrong':job.get('stop_after_wrong')})
    if 'scoring_policy' in job:
        manifest['scoring_policy']=job['scoring_policy']
        manifest['scope']=digest({'original_scope':manifest['scope'],'scoring_policy':job['scoring_policy']})
    with LOCK:
        write(root / 'evaluations' / (job['id'] + '.json'), manifest)
    return manifest


def update_evaluation(root, job):
    with LOCK:
        path = root / 'evaluations' / (job['id'] + '.json')
        manifest = read(path, None)
        if manifest:
            manifest.update({k: job[k] for k in ('started', 'ended', 'state', 'error', 'rc', 'completed_tasks', 'total_tasks', 'label', 'stopped_after', 'current_task', 'repeat', 'elapsed_s', 'active_started', 'resume_count', 'resume_versions','active_intervals','hour_timing_unknown','stop_reason') if k in job})
            write(path, manifest)


def timestamp(row):
    try:
        return dt.datetime.fromisoformat(row['ts']).timestamp()
    except (ValueError, TypeError, KeyError):
        return 0


def evaluations(root, rows):
    manifests = [read(p, {}) for p in sorted((root / 'evaluations').glob('*.json'))]
    output = []
    for m in manifests:
        if not m.get('id'): continue
        raw = run_tracking.raw_attempts(m, rows, manifests)
        attempts = run_tracking.effective_attempts(raw)
        expected = Counter({t['task']: t['repeat'] for t in m['expected']})
        actual = Counter(r.get('task') for r in attempts)
        reasons = []
        if m.get('scoring_policy')==scoring_policy.NET and any(not scoring_policy.final_answer(r) for r in attempts):
            reasons.append('Neutral outcomes are excluded from answer-accuracy calibration.')
        if actual != expected:
            reasons.append(f"Incomplete or duplicate attempts: {len(attempts)}/{sum(expected.values())} recorded.")
        if any(r.get('status') != 'completed' for r in attempts):
            reasons.append('Execution errors must be resolved before calibration.')
        if len({(r.get('task'),r.get('run',1)) for r in raw if r.get('status')=='completed'}) != sum(r.get('status')=='completed' for r in raw):
            reasons.append('Duplicate completed repeats were recorded.')
        hashes = {t['task']: t['task_sha'] for t in m['expected']}
        if any(r.get('benchmark_version') != m['benchmark_version'] or r.get('task_sha') != hashes.get(r.get('task')) for r in attempts):
            reasons.append('Benchmark version or question content changed during this evaluation.')
        ids = [r.get('run_id') for r in attempts]
        if len(set(ids)) != len(ids) or any(not x for x in ids):
            reasons.append('Attempt identifiers are missing or duplicated.')
        if len({r.get('node') for r in attempts}) > 1:
            reasons.append('This evaluation mixes machines.')
        if any(r.get('model') != m['model'] for r in attempts):
            reasons.append('This evaluation mixes model names.')
        if not m.get('legacy_time_match') and any(r.get('model_config_hash') != m['config_hash'] for r in attempts):
            reasons.append('Model configuration changed during this evaluation.')
        if m.get('state') in ('error', 'cancelled', 'stopped'):
            reasons.append('This evaluation did not finish successfully.')
        per_task = {tid: [r for r in attempts if r.get('task') == tid] for tid in expected}
        accuracy = sum(sum(bool(r.get('solved')) for r in rs) / len(rs) for rs in per_task.values() if rs) / len(expected) if not reasons else None
        breakdown = {}
        for category in ('text', 'vision'):
            tids = [t['task'] for t in m['expected'] if bool(t.get('vision')) == (category == 'vision')]
            value = sum(sum(bool(r.get('solved')) for r in per_task[tid])/len(per_task[tid]) for tid in tids) / len(tids) if tids and not reasons else None
            breakdown[category] = {'questions': len(tids), 'accuracy': value}
        output.append({**m, 'breakdown': breakdown, 'eligible': not reasons, 'reasons': reasons, 'accuracy': accuracy,
                       'attempts': len(attempts), 'expected_attempts': sum(expected.values()),
                       'not_attempted':sum(run_tracking.is_early_stop(r) for r in attempts),
                       'questions': len(expected), 'errors': sum(r.get('status') == 'error' for r in attempts),
                       'duration_s': sum(r.get('duration_s', 0) or 0 for r in raw),
                       'evidence_hash': digest(sorted(attempts, key=lambda r: r.get('run_id', ''))),
                       'node': attempts[0].get('node') if attempts else None})
    return sorted(output, key=lambda e: e['created'], reverse=True)


def fit(references):
    base = {'method': METHOD, 'status': 'needs_references', 'warnings': [], 'min_accuracy_span': MIN_ACCURACY_SPAN}
    if len(references) < 2:
        return {**base, 'message': 'Assign targets to at least two different models.'}
    points = sorted((r['accuracy'], r['target']) for r in references)
    span = points[-1][0] - points[0][0]
    if span < MIN_ACCURACY_SPAN - 1e-12:
        return {**base, 'status': 'blocked', 'message': 'Reference accuracies must span at least 5 percentage points to avoid an unstable scale.'}
    if any((x2 > x1 and y2 < y1) or (x2 == x1 and y2 != y1)
           for i, (x1, y1) in enumerate(points) for x2, y2 in points[i+1:]):
        return {**base, 'status': 'blocked', 'message': 'Reference targets contradict measured accuracy. Higher accuracy cannot receive a lower target; equal accuracy needs equal targets.'}
    n = len(points)
    mx, my = sum(x for x, y in points)/n, sum(y for x, y in points)/n
    slope = sum((x-mx)*(y-my) for x, y in points)/sum((x-mx)**2 for x, y in points)
    if slope <= 0:
        return {**base, 'status': 'blocked', 'message': 'Assign different target scores with a positive relationship to accuracy.'}
    intercept = my - slope*mx
    if not math.isfinite(slope) or not math.isfinite(intercept) or intercept + slope*points[0][0] < -1e-10:
        return {**base, 'status': 'blocked', 'message': 'These targets produce an invalid or negative fitted score within the reference range. Review the target spacing.'}
    residuals = [{'model': r['model'], 'target': r['target'], 'fitted': intercept+slope*r['accuracy'],
                  'residual': r['target']-(intercept+slope*r['accuracy'])} for r in references]
    rmse = math.sqrt(sum(r['residual']**2 for r in residuals)/n)
    warnings = []
    if n == 2: warnings.append('Two references define a line exactly; they do not validate it. Add a third or more.')
    if n >= 3 and max(abs(r['residual']) for r in residuals) > 0.2*(max(y for x,y in points)-min(y for x,y in points)):
        warnings.append('A reference misses the fitted line by more than 20% of the target range. Review its target before trusting this scale.')
    loo = []
    if n >= 3:
        for i, (x, y) in enumerate(points):
            others = points[:i]+points[i+1:]
            ax, ay = sum(a for a,b in others)/len(others), sum(b for a,b in others)/len(others)
            denom = sum((a-ax)**2 for a,b in others)
            if denom > 1e-12:
                b = sum((a-ax)*(v-ay) for a,v in others)/denom
                loo.append(abs(y-(ay+b*(x-ax))))
    return {**base, 'status': 'ready', 'message': f'{n} reference models, equally weighted.',
            'intercept': intercept, 'slope': slope, 'accuracy_min': points[0][0], 'accuracy_max': points[-1][0],
            'rmse': rmse, 'leave_one_out_mae': sum(loo)/len(loo) if len(loo)==n else None,
            'residuals': residuals, 'warnings': warnings}


def report(root, rows):
    evs = evaluations(root, rows)
    document = read(root / 'calibration.json', {'schema_version': 1, 'scopes': {}})
    for e in evs:
        scope = document['scopes'].get(e['scope'])
        e['calibrated_score'] = None
        e['score_note'] = 'No reference scale for this question set yet.'
        if not e['eligible']:
            e['score_note'] = 'Awaiting a complete, valid evaluation.'
        elif scope:
            f = scope['fit']
            e['calibration_revision'] = scope['revision']
            if f['status'] != 'ready': e['score_note'] = f['message']
            elif not f['accuracy_min'] <= e['accuracy'] <= f['accuracy_max']:
                e['score_note'] = 'Outside reference range. Add a reference at this accuracy to extend the scale.'
            else:
                e['calibrated_score'] = f['intercept'] + f['slope']*e['accuracy']
                e['score_note'] = 'Estimated from reference targets.'
    return {'evaluations': evs, 'scopes': document['scopes'], 'method': METHOD}


def set_reference(root, rows, body):
    with LOCK:
        ev = next((e for e in evaluations(root, rows) if e['id'] == body.get('evaluation_id')), None)
        if not ev or not ev['eligible']:
            raise ValueError('Choose a complete evaluation without execution errors or changed settings.')
        target = body.get('target')
        if type(target) not in (int, float) or not math.isfinite(target) or target < 0:
            raise ValueError('Target must be a finite, non-negative number.')
        path = root / 'calibration.json'
        doc = read(path, {'schema_version': 1, 'scopes': {}})
        scope = doc['scopes'].get(ev['scope'], {'benchmark_version': ev['benchmark_version'], 'expected': ev['expected'], 'references': []})
        refs = [r for r in scope['references'] if r['model_id'] != ev['model_id']]
        refs.append({k: ev[k] for k in ('model', 'model_id', 'accuracy', 'evidence_hash', 'node') } |
                    {'evaluation_id': ev['id'], 'target': target})
        scope.update(references=refs, revision=uuid.uuid4().hex, fit=fit(refs))
        doc['scopes'][ev['scope']] = scope
        save_document(root, doc)
        return scope


def remove_reference(root, body):
    with LOCK:
        doc = read(root / 'calibration.json', {'schema_version': 1, 'scopes': {}})
        scope = doc['scopes'].get(body.get('scope'))
        if not scope: raise ValueError('Unknown calibration scale.')
        scope['references'] = [r for r in scope['references'] if r['evaluation_id'] != body.get('evaluation_id')]
        scope.update(revision=uuid.uuid4().hex, fit=fit(scope['references']))
        save_document(root, doc)


def save_document(root, doc):
    path = root / 'calibration.json'
    if path.exists():
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = root / 'backups' / ('calibration-' + stamp + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    write(path, doc)
