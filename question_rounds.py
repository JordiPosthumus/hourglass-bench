"""Whole-bank rounds within one clock; no previous answers enter model context."""
import math
import scoring_policy

POLICY = 'whole-bank-slowest-wrong-first-v1'


def enabled(job):
    return job.get('round_policy') == POLICY


def resolved(rows, task, number):
    return any(r.get('task') == task and r.get('run', 1) == number
               and r.get('status') in ('completed', 'timeout') for r in rows)


def next_order(order, rows, number):
    latest = {}
    for row in rows:
        if row.get('run', 1) == number and row.get('task') in order:
            latest[row['task']] = row

    def priority(task):
        row = latest.get(task, {})
        group = 0 if scoring_policy.incorrect(row) else 2 if row.get('solved') else 1
        duration = row.get('duration_s', 0)
        if not isinstance(duration, (int, float)) or not math.isfinite(duration):duration = 0
        return group, -max(0, duration)

    # Stable ties retain the original bank order.
    return sorted(order, key=priority)


def attempts(job, manifest, rows, persist):
    """Persist each round's order before execution, including across a resume."""
    original = list(manifest.get('order') or job['tasks'])
    if not enabled(job):
        yield from ((task, 1) for task in original)
        return
    while original and not job.get('stop_requested'):
        number = job.setdefault('round_number', 1)
        order = job.setdefault('round_order', list(original))
        persist()
        for task in order:
            if job.get('stop_requested'):return
            if not resolved(rows(), task, number):yield task, number
        if job.get('stop_requested'):return
        recorded = rows()
        if not all(resolved(recorded, task, number) for task in order):
            raise ValueError('The round has unfinished execution; resume before advancing.')
        job['round_order'] = next_order(original, recorded, number)
        job['round_number'] = number + 1
