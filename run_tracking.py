"""Read-only views over append-only attempt history, including resumed runs."""
import scoring_policy
import datetime as dt
from collections import defaultdict

STOP_AFTER_WRONG = 20
MATH_LEVEL_TIERS = {"advanced_high_school": 1, "advanced_undergraduate": 5, "graduate": 9}

def difficulty_tier(task):
    tier=task.get("tier")
    return tier if isinstance(tier,(int,float)) else MATH_LEVEL_TIERS.get(task.get("level"))

def is_early_stop(row):
    return row.get("score_reason") in ("five_wrong_in_row", "wrong_streak_limit")



def timestamp(row):
    try:return dt.datetime.fromisoformat(row['ts']).timestamp()
    except (ValueError,TypeError,KeyError):return 0


def raw_attempts(manifest, rows, manifests=()):
    if manifest.get('repair'):
        import repair_runs
        return repair_runs.composite_rows(manifest,rows)
    own=[r for r in rows if r.get('evaluation_id')==manifest['id']]
    if not manifest.get('legacy_time_match'):return own
    if 'legacy_run_ids' in manifest:
        ids=set(manifest['legacy_run_ids'])
        legacy=[r for r in rows if r.get('run_id') in ids and not r.get('evaluation_id')]
    else:
        start=manifest.get('started') or manifest['created']
        later=[m['started'] for m in manifests if m.get('started') and m['started']>start]
        end=manifest.get('ended') or (min(later) if later else float('inf'))
        legacy=[r for r in rows if not r.get('evaluation_id') and r.get('model')==manifest['model'] and start<=timestamp(r)<=end]
    return legacy+own


def effective_attempts(rows):
    # Failed attempts remain in the raw audit trail but are superseded for scoring by a completed retry.
    grouped={}
    for r in rows:
        key=(r.get('task'),r.get('run',1))
        previous=grouped.get(key)
        if previous is None or r.get('status')=='completed' or previous.get('status')!='completed':grouped[key]=r
    return list(grouped.values())


def missing_repeats(manifest, rows, tid):
    if any(r.get('task')==tid and r.get('status')=='timeout' for r in rows):return []
    count=next(t['repeat'] for t in manifest['expected'] if t['task']==tid)
    complete={r.get('run',1) for r in effective_attempts(rows) if r.get('task')==tid and r.get('status')=='completed'}
    return [i for i in range(1,count+1) if i not in complete]


def progress(manifest, raw, job, now):
    effective=effective_attempts(raw)
    by_task=defaultdict(list)
    for r in effective:
        if r.get('status')=='completed':by_task[r['task']].append(r)
    points=0;finished=0;answered_questions=0;streak=0
    order=manifest.get('order') or [t['task'] for t in manifest['expected']]
    expected={t['task']:t['repeat'] for t in manifest['expected']}
    for tid in order:
        rs=by_task[tid];n=expected[tid]
        points+=sum(bool(r.get('solved')) for r in rs)/n
        if any(r.get('task')==tid and r.get('status')=='timeout' for r in effective):
            finished+=1
            continue
        if len(rs)==n:
            finished+=1
            if not any(is_early_stop(r) for r in rs):
                if scoring_policy.is_net(manifest.get('scoring_policy')) and not any(scoring_policy.final_answer(r) for r in rs):continue
                answered_questions+=1
                streak=0 if any(r.get('solved') for r in rs) else streak+1
    scored=[r for r in effective if r.get('status')=='completed' and not is_early_stop(r)]
    if scoring_policy.is_net(manifest.get('scoring_policy')):scored=[r for r in scored if scoring_policy.final_answer(r)]
    elapsed=job.get('elapsed_s')
    if elapsed is None:
        elapsed=max(0,(job.get('ended') or now)-(job.get('started') or now)) if job.get('started') else 0
    if job.get('state')=='running' and job.get('active_started'):
        elapsed+=max(0,now-job['active_started'])
    breakdown={}
    for lane in ('text','vision'):
        tasks=[t for t in manifest['expected'] if bool(t.get('vision'))==(lane=='vision')]
        tids={t['task'] for t in tasks}
        attempts=[r for r in scored if r['task'] in tids]
        correct=sum(bool(r.get('solved')) for r in attempts)
        breakdown[lane]={'points':sum(sum(bool(r.get('solved')) for r in by_task[t['task']])/t['repeat'] for t in tasks),
                         'total_questions':len(tasks),'finished_questions':sum(len(by_task[t['task']])==t['repeat'] for t in tasks),
                         'correct_attempts':correct,'scored_attempts':len(attempts),'accuracy':correct/len(attempts) if attempts else None,
                         'not_attempted':sum(is_early_stop(r) for r in effective if r['task'] in tids),
                         'errors':sum(r.get('status')=='error' for r in raw if r.get('task') in tids)}
    return {'breakdown':breakdown,'points':points,'total_questions':len(expected),'finished_questions':finished,
            'answered_questions':answered_questions,'correct_attempts':sum(bool(r.get('solved')) for r in scored),
            'scored_attempts':len(scored),'accuracy':sum(bool(r.get('solved')) for r in scored)/len(scored) if scored else None,
            'not_attempted':sum(is_early_stop(r) for r in effective),
            'timeouts':len({r['task'] for r in effective if r.get('status')=='timeout'}),
            'errors':sum(r.get('status')=='error' for r in raw),'elapsed_s':elapsed,
            'questions_per_minute':answered_questions*60/elapsed if elapsed>0 else None,
            'stop_after_wrong':job.get('stop_after_wrong') or manifest.get('stop_after_wrong') or STOP_AFTER_WRONG,
            'wrong_streak':min(streak,job.get('stop_after_wrong') or manifest.get('stop_after_wrong') or STOP_AFTER_WRONG), 'attempt_time_s':sum(r.get('duration_s',0) or 0 for r in raw)}
