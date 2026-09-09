"""Aggregate-only, reviewable public reports. Never serialize raw benchmark records."""
import datetime as dt
import hashlib
import html
import json
import hour_score
import score_weights


def build(root, job, rows, manifest):
    expected=score_weights.enrich(root,manifest['expected'])
    h=hour_score.score(job,rows,expected)
    if h['state']=='unavailable':raise ValueError('Timing is unavailable; this score cannot be published.')
    if any(t.get('weight_version')!=score_weights.VERSION for t in expected):
        raise ValueError('Cannot verify the frozen difficulty of every question.')
    identity={'questions':[(t['task_sha'],t['weight'],t.get('vision',False),t['repeat']) for t in expected],
              'order':[next(t['task_sha'] for t in expected if t['task']==tid) for tid in manifest['order']]}
    ledger=root/'timing-corrections.json'
    corrections=json.loads(ledger.read_text()) if ledger.exists() else []
    credits=[c for c in corrections if c.get('evaluation_id')==job['id']]
    intervals=job.get('active_intervals') or [{'start':job['started'],'end':job.get('ended')}]
    events=[]
    for r in rows:
        if r.get('evaluation_id')!=job['id']:continue
        try:ts=dt.datetime.fromisoformat(r['ts']).timestamp()
        except (KeyError,ValueError,TypeError):continue
        active=sum(max(0,min(ts,p.get('end') or ts)-p['start']) for p in intervals)
        if active<=min(3600,h['elapsed_s']):events.append((active,r))
    points=[{'seconds':0,'weighted':0,'correct':0}];filtered=[]
    for active,r in sorted(events,key=lambda e:e[0]):
        points.append({**points[-1],'seconds':round(active,3)})
        filtered.append(r);sample=hour_score.score(job,filtered,expected)
        points.append({'seconds':round(active,3),'weighted':sample['weighted_points'],'correct':sample['points']})
    points.append({'seconds':round(min(3600,h['elapsed_s']),3),'weighted':h['weighted_points'],'correct':h['points']})

    report={'format':'hourglass-public-report-v1','model':str(job['model']),
            'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scoring':h['weighted_version'],
            'timing_policy':h['version'],'benchmark_version':manifest['benchmark_version'],
            'bank_fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
            'state':h['state'],'weighted_points':h['weighted_points'],'raw_correct':h['points'],
            'completed_questions':h['completed_questions'],'total_questions':h['total_questions'],
            'active_seconds':round(h['elapsed_s'],3),'window_seconds':3600,
            'breakdown':h['breakdown'],'curve':points,
            'clock_adjustment_seconds':round(sum(c['credit_s'] for c in credits),3),
            'execution':{'stop_after_wrong':job.get('stop_after_wrong',20),'repeat':manifest.get('repeat',1)},
            'configuration_disclosure':'Not supplied; compare only with equivalent model settings and hardware.'}
    maximum=max(1,h['weighted_points'],h['points'])
    poly=lambda key:' '.join(f"{60+p['seconds']/3600*660:.2f},{280-p[key]/maximum*180:.2f}" for p in points)
    esc=html.escape
    star='*' if credits else ''
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="430" viewBox="0 0 800 430"><rect width="800" height="430" fill="#101722"/><g font-family="sans-serif" fill="#eaf0fa"><text x="40" y="38" font-size="22">Hourglass Bench · {esc(report['model'])}</text><text x="40" y="70">{h['weighted_points']:.2f} weighted points{star} · {h['points']} correct · {h['state']}</text><path d="M60 95V280H720" stroke="#718096" fill="none"/><polyline points="{poly('weighted')}" fill="none" stroke="#74e5c4" stroke-width="3"/><polyline points="{poly('correct')}" fill="none" stroke="#9aaaff" stroke-width="2"/><text x="60" y="305">0</text><text x="650" y="305">60 minutes</text><text x="40" y="340" fill="#74e5c4">Weighted points</text><text x="210" y="340" fill="#9aaaff">Raw correct</text><text x="40" y="370">Text: {h['breakdown']['text']['weighted_points']:.2f} · Vision: {h['breakdown']['vision']['weighted_points']:.2f}</text><text x="40" y="400" font-size="11">{'*Clock adjusted to exclude a harness interruption.' if credits else 'Active wall clock · thinking, tools and retries included'}</text></g></svg>'''
    readme=f"# Hourglass Bench result\n\n![Score graph](score.svg)\n\nModel: {report['model'].replace(chr(10),' ')}\n\n**{h['weighted_points']:.2f} weighted points{star}**, {h['points']} correct. Status: **{h['state']}**.\n\nFixed difficulty weights: charts 1–10 → 1–2; games 1–5 → 1–2; math high school / undergraduate / graduate → 1 / 1.5 / 2. One award per question within 3,600 active seconds.\n\nBank fingerprint: `{report['bank_fingerprint']}`. Compare the same bank, order, repeat policy, model settings and hardware. Hardware and configuration disclosure has not been supplied.\n\n[Aggregate data](report.json)\n"
    if credits:readme+='\n<sub>*Clock adjusted to exclude a harness interruption.</sub>\n'
    return {'report.json':json.dumps(report,indent=2)+'\n','score.svg':svg,'README.md':readme}
