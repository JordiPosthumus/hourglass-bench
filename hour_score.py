"""Versioned, retrospective one-hour scoring; never controls model execution."""
import datetime as dt
import json
import time
import repair_runs
import score_weights
import scoring_policy

VERSION = 'hour-v1'
WINDOW_S = 3600


def score(job, rows, expected=(), now=None):
    now = time.time() if now is None else now
    expected = expected or job.get('expected', [])
    tids = set(job.get('tasks') or job.get('order') or [t['task'] for t in expected])
    vision = {t['task']: bool(t.get('vision')) for t in expected}
    if job.get('repair') and not job.get('_repair_rows_materialized'):rows=repair_runs.composite_rows(job,rows)
    raw = [r for r in rows if r.get('evaluation_id') == job.get('id') and r.get('task') in tids]
    intervals = job.get('active_intervals')
    timing_known = not job.get('hour_timing_unknown') and (not job.get('resume_count') or bool(intervals))
    started = job.get('started')
    if not intervals:
        intervals = [{'start': started, 'end': job.get('ended')} ] if started else []

    def active_at(ts):
        return sum(max(0, min(ts, part.get('end') or ts) - part['start']) for part in intervals)

    elapsed = active_at(job.get('ended') or now) if timing_known else job.get('progress', {}).get('elapsed_s', 0)
    elapsed += (job.get('repair') or {}).get('base_elapsed_s',0) if timing_known else 0
    within, after, errors, unknown = [], set(), 0, 0
    timeouts = set()
    for r in raw:
        if r.get('score_reason') in ('five_wrong_in_row', 'wrong_streak_limit'):
            continue
        try:
            ts = dt.datetime.fromisoformat(r['ts']).timestamp()
        except (KeyError, TypeError, ValueError):
            unknown += 1
            continue
        if not r.get('repair_inherited') and (not intervals or ts < intervals[0]['start']):
            unknown += 1
            continue
        row_elapsed=repair_runs.elapsed_at(job,r) if job.get('repair') else active_at(ts)
        if row_elapsed > WINDOW_S:
            if r.get('status') == 'completed':
                after.add(r['task'])
            continue
        if r.get('status') == 'timeout':
            timeouts.add(r['task'])
        elif r.get('status') == 'error':
            errors += 1
        elif r.get('status') == 'completed':
            within.append(r)
    available = timing_known and not unknown and not job.get("results_reset")
    correct = {r['task'] for r in within if r.get('solved')}
    completed = {r['task'] for r in within}
    net_policy = scoring_policy.is_net(job.get('scoring_policy'))
    wrong = {r['task'] for r in within if scoring_policy.incorrect(r)} - correct if net_policy else completed - correct
    abstained = {r['task'] for r in within if r.get('score_reason') == 'abstained'} - correct - wrong
    unsupported = {r['task'] for r in within if r.get('score_reason') == 'unsupported_vision'} - correct - wrong
    weights={t['task']:t.get('weight',score_weights.weight(t)) for t in expected}
    weighted=lambda ids:round(sum(weights.get(tid,1.0) for tid in ids),6) if available else None
    gross = weighted(correct)
    net = round(gross-len(wrong),6) if available else None
    lanes = {}
    for lane in ('text', 'vision'):
        rs = [r for r in within if vision.get(r['task'], r.get('kind') == 'chart-vqa' or r.get('section') in ('chart', 'charts')) == (lane == 'vision')]
        lanes[lane] = {'points': len({r['task'] for r in rs if r.get('solved')}) if available else None,
                       'weighted_points':(round(weighted({r['task'] for r in rs if r.get('solved')})-len(wrong & {r['task'] for r in rs}),6) if available else None) if net_policy else weighted({r['task'] for r in rs if r.get('solved')}),
                       'completed_questions': len({r['task'] for r in rs})}
    discovery = {}
    for domain in ('games', 'hourglass', 'dsg'):
        group = {t['task'] for t in expected if t.get('section') == 'repository_discovery' and t.get('discovery_domain') == domain} & tids
        if group:
            discovery[domain] = {'points': len(correct & group) if available else None,
                                 'weighted_points': round(weighted(correct & group) - (len(wrong & group) if net_policy else 0), 6) if available else None,
                                 'completed_questions': len(completed & group), 'total_questions': len(group)}
    repeats={t['task']:t.get('repeat',1) for t in expected}
    all_finished=bool(tids) and all(tid in timeouts or set(range(1,repeats.get(tid,1)+1)).issubset({r.get('run',1) for r in within if r['task']==tid}) for tid in tids)
    final = available and (elapsed >= WINDOW_S or all_finished)
    state = 'unavailable' if not available else 'final' if final else 'in_progress' if job.get('state') == 'running' else 'not_started' if not started else 'partial'
    return {'version': VERSION, 'window_s': WINDOW_S, 'points': len(correct) if available else None,
            'weighted_version':score_weights.VERSION,'weighted_points':net if net_policy else gross,
            'scoring_policy':job.get('scoring_policy') or scoring_policy.LEGACY,'gross_points':gross,'net_points':net if net_policy else None,
            'penalty_points':len(wrong) if net_policy else 0,'abstained_questions':len(abstained),'unsupported_questions':len(unsupported),
            'correct_tasks': sorted(correct) if available else [], 'breakdown': lanes,
            'repository_discovery': discovery,
            'timeouts':len(timeouts), 'resolved_questions':len(completed | timeouts),
            'question_timeout_policy':job.get('question_timeout_policy'),
            'completed_questions': len(completed), 'incorrect_questions': len(wrong),
            'total_questions': len(tids), 'after_deadline_questions': len(after), 'errors': errors,
            'elapsed_s': elapsed, 'remaining_s': max(0, WINDOW_S - elapsed), 'state': state,
            'repair_policy':(job.get('repair') or {}).get('policy'),
            'timing_note': 'Selected question results were reset; rerun them with a fresh clock. The original hourly score is withheld.' if job.get('results_reset') else repair_runs.NOTE if job.get('repair') and available else 'Recorded completion timestamps on active wall clock, including thinking, tools and retries.' if available else 'Missing completion timestamps or historical pause intervals; hourly score withheld.'}


def leaderboard(root, rows):
    lines = ['## Hourglass score · weighted points in one hour', '',
             'Correct questions within 3,600 active seconds earn 1–2 points on fixed section difficulty scales. Raw correct counts remain visible. '
             'Scores are not extrapolated. Compare the same bank, order and repeat policy. '
             'Metric: hour-v1; execution versions remain unchanged.', '',
             '| model | run | questions | weighted score | raw correct | text points | vision points | status |',
             '|---|---|---|---|---|---|---|---|']
    for p in sorted((root / 'evaluations').glob('*.json')):
        m = json.loads(p.read_text())
        if not m.get('id') or not m.get('expected'):
            continue
        h = score(m, rows,score_weights.enrich(root,m['expected']))
        value = lambda n: '—' if n is None else str(n)
        lines.append(f"| {m['model']} | {m['id'][:8]} | {h['total_questions']} | {value(h['weighted_points'])} | {value(h['points'])} | {value(h['breakdown']['text']['weighted_points'])} | {value(h['breakdown']['vision']['weighted_points'])} | {h['state']} |")
    return '\n'.join(lines) + '\n\n'
