"""Aggregate-only, reviewable public reports. Never serialize raw benchmark records."""
import datetime as dt
import hashlib
import html
import json
import hour_score
import score_weights
import hardware_records


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

    hardware=hardware_records.recorded(root,manifest)
    report={'hardware':hardware,'machine_key':hardware['machine_key'],'format':'hourglass-public-report-v1','model':str(job['model']),
            'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scoring':h['weighted_version'],
            'timing_policy':h['version'],'benchmark_version':manifest['benchmark_version'],
            'bank_fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
            'state':h['state'],'weighted_points':h['weighted_points'],'raw_correct':h['points'],
            'completed_questions':h['completed_questions'],'total_questions':h['total_questions'],
            'active_seconds':round(h['elapsed_s'],3),'window_seconds':3600,
            'breakdown':h['breakdown'],'curve':points,
            'clock_adjustment_seconds':round(sum(c['credit_s'] for c in credits),3),
            'execution':{'stop_after_wrong':job.get('stop_after_wrong',20),'repeat':manifest.get('repeat',1)},
            'configuration_disclosure':'Model settings not supplied; compare only equivalent settings.'}
    maximum=max(1,h['weighted_points'],h['points'])
    poly=lambda key:' '.join(f"{60+p['seconds']/3600*660:.2f},{280-p[key]/maximum*180:.2f}" for p in points)
    esc=html.escape
    star='*' if credits else ''
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="430" viewBox="0 0 800 430"><rect width="800" height="430" fill="#101722"/><g font-family="sans-serif" fill="#eaf0fa"><text x="40" y="38" font-size="22">Hourglass Bench · {esc(report['model'])}</text><text x="40" y="70">{h['weighted_points']:.2f} weighted points{star} · {h['points']} correct · {h['state']}</text><path d="M60 95V280H720" stroke="#718096" fill="none"/><polyline points="{poly('weighted')}" fill="none" stroke="#74e5c4" stroke-width="3"/><polyline points="{poly('correct')}" fill="none" stroke="#9aaaff" stroke-width="2"/><text x="60" y="305">0</text><text x="650" y="305">60 minutes</text><text x="40" y="340" fill="#74e5c4">Weighted points</text><text x="210" y="340" fill="#9aaaff">Raw correct</text><text x="40" y="370">Text: {h['breakdown']['text']['weighted_points']:.2f} · Vision: {h['breakdown']['vision']['weighted_points']:.2f}</text><text x="40" y="400" font-size="11">{'*Clock adjusted to exclude a harness interruption.' if credits else 'Active wall clock · thinking, tools and retries included'}</text></g></svg>'''
    readme=f"# Hourglass Bench result\n\n![Score graph](score.svg)\n\nModel: {report['model'].replace(chr(10),' ')}\n\n**{h['weighted_points']:.2f} weighted points{star}**, {h['points']} correct. Status: **{h['state']}**.\n\nFixed difficulty weights: charts 1–10 → 1–2; games 1–5 → 1–2; math high school / undergraduate / graduate → 1 / 1.5 / 2. One award per question within 3,600 active seconds.\n\nBank fingerprint: `{report['bank_fingerprint']}`. Compare the same bank, order, repeat policy, model settings and hardware. Inference machine: {hardware['label']}. Model configuration disclosure has not been supplied.\n\n[Aggregate data](report.json)\n"
    if credits:readme+='\n<sub>*Clock adjusted to exclude a harness interruption.</sub>\n'
    return {'report.json':json.dumps(report,indent=2)+'\n','score.svg':svg,'README.md':readme}


def comparison(reports):
    """Overlay only reports from the same bank, order and score policy."""
    if not reports:raise ValueError('No reports to compare.')
    reference=reports[0]
    keys=('bank_fingerprint','scoring','timing_policy','benchmark_version','machine_key')
    compatible=[r for r in reports if all(r.get(k)==reference.get(k) for k in keys)]
    maximum=max(1,max(r['weighted_points'] for r in compatible))
    import math
    ymax=max(2,math.ceil(maximum/2)*2)
    colors=['#74e5c4','#9aaaff','#ffbf69','#f58aaa','#7ed5ff','#d5adff','#f5e384','#a9db80']
    height=390+len(compatible)*29
    elements=[f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" viewBox="0 0 900 {height}"><rect width="900" height="{height}" fill="#101722"/><g font-family="sans-serif" fill="#eaf0fa">',
              f'<text x="45" y="38" font-size="24">Hourglass Bench · {html.escape(reference.get("hardware",{}).get("label","Hardware not recorded"))}</text>',
              '<text x="45" y="65" font-size="13">Weighted points · same question bank and order · active wall clock</text>']
    for i in range(5):
        value=ymax*i/4;y=290-i*47.5
        elements.append(f'<path d="M65 {y}H850" stroke="#2c394a"/><text x="27" y="{y+5}" font-size="12">{value:g}</text>')
    for minute in range(0,61,10):
        x=65+minute/60*785
        elements.append(f'<text x="{x-8}" y="315" font-size="12">{minute}</text>')
    elements.append('<text x="390" y="341" font-size="13">Active minutes</text>')
    for i,r in enumerate(compatible):
        color=colors[i%len(colors)]
        points=' '.join(f"{65+p['seconds']/3600*785:.2f},{290-p['weighted']/ymax*190:.2f}" for p in r['curve'])
        y=377+i*29;star='*' if r.get('clock_adjustment_seconds') else ''
        label=html.escape(f"{r['model']} · {r['weighted_points']:.2f}{star} · {r['raw_correct']} correct · {r['state']}")
        dash=' stroke-dasharray="7 3"' if i>=len(colors) else ''
        elements.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"{dash}/><path d="M45 {y-4}H70" stroke="{color}" stroke-width="3"{dash}/><text x="82" y="{y}" font-size="13">{label}</text>')
    if any(r.get('clock_adjustment_seconds') for r in compatible):
        elements.append(f'<text x="45" y="{height-12}" font-size="10">*Clock adjusted to exclude a harness interruption.</text>')
    elements.append('</g></svg>')
    return {'comparison.svg':''.join(elements),'comparison.json':json.dumps({'format':'hourglass-comparison-v1','reports':compatible},indent=2)+'\n'}
