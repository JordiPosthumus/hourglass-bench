"""Versioned, retrospective one-hour scoring; never controls model execution."""
import datetime as dt
import json
import time

VERSION = 'hour-v1'
WINDOW_S = 3600


def score(job, rows, expected=(), now=None):
    now = time.time() if now is None else now
    expected = expected or job.get('expected', [])
    tids = set(job.get('tasks') or job.get('order') or [t['task'] for t in expected])
    vision = {t['task']: bool(t.get('vision')) for t in expected}
    raw = [r for r in rows if r.get('evaluation_id') == job.get('id') and r.get('task') in tids]
    intervals = job.get('active_intervals')
    timing_known = not job.get('hour_timing_unknown') and (not job.get('resume_count') or bool(intervals))
    started = job.get('started')
    if not intervals:
        intervals = [{'start': started, 'end': job.get('ended')} ] if started else []

    def active_at(ts):
        return sum(max(0, min(ts, part.get('end') or ts) - part['start']) for part in intervals)

    elapsed = active_at(job.get('ended') or now) if timing_known else job.get('progress', {}).get('elapsed_s', 0)
    within, after, errors, unknown = [], set(), 0, 0
    for r in raw:
        if r.get('score_reason') in ('five_wrong_in_row', 'wrong_streak_limit'):
            continue
        try:
            ts = dt.datetime.fromisoformat(r['ts']).timestamp()
        except (KeyError, TypeError, ValueError):
            unknown += 1
            continue
        if not intervals or ts < intervals[0]['start']:
            unknown += 1
            continue
        if active_at(ts) > WINDOW_S:
            if r.get('status') == 'completed':
                after.add(r['task'])
            continue
        if r.get('status') == 'error':
            errors += 1
        elif r.get('status') == 'completed':
            within.append(r)
    available = timing_known and not unknown
    correct = {r['task'] for r in within if r.get('solved')}
    completed = {r['task'] for r in within}
    lanes = {}
    for lane in ('text', 'vision'):
        rs = [r for r in within if vision.get(r['task'], r.get('kind') == 'chart-vqa' or r.get('section') in ('chart', 'charts')) == (lane == 'vision')]
        lanes[lane] = {'points': len({r['task'] for r in rs if r.get('solved')}) if available else None,
                       'completed_questions': len({r['task'] for r in rs})}
    final = available and (elapsed >= WINDOW_S or bool(tids) and len(completed) == len(tids))
    state = 'unavailable' if not available else 'final' if final else 'in_progress' if job.get('state') == 'running' else 'not_started' if not started else 'partial'
    return {'version': VERSION, 'window_s': WINDOW_S, 'points': len(correct) if available else None,
            'correct_tasks': sorted(correct) if available else [], 'breakdown': lanes,
            'completed_questions': len(completed), 'incorrect_questions': len(completed - correct),
            'total_questions': len(tids), 'after_deadline_questions': len(after), 'errors': errors,
            'elapsed_s': elapsed, 'remaining_s': max(0, WINDOW_S - elapsed), 'state': state,
            'timing_note': 'Recorded completion timestamps on active wall clock, including thinking, tools and retries.' if available else 'Missing completion timestamps or historical pause intervals; hourly score withheld.'}


def leaderboard(root, rows):
    lines = ['## Hourglass Bench score · correct in one hour', '',
             'One point per distinct question completed correctly within 3,600 active seconds. '
             'Scores are not extrapolated. Compare the same bank, order and repeat policy. '
             'Metric: hour-v1; execution versions remain unchanged.', '',
             '| model | run | questions | score | text | vision | status |',
             '|---|---|---|---|---|---|---|']
    for p in sorted((root / 'evaluations').glob('*.json')):
        m = json.loads(p.read_text())
        if not m.get('id') or not m.get('expected'):
            continue
        h = score(m, rows)
        value = lambda n: '—' if n is None else str(n)
        lines.append(f"| {m['model']} | {m['id'][:8]} | {h['total_questions']} | {value(h['points'])} | {value(h['breakdown']['text']['points'])} | {value(h['breakdown']['vision']['points'])} | {h['state']} |")
    return '\n'.join(lines) + '\n\n'
