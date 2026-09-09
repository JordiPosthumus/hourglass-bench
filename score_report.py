"""Aggregate-only, reviewable public reports. Never serialize raw benchmark records."""
import datetime as dt
import hashlib
import html
import json
import statistics
import math
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

    scored=[r for r in rows if r.get('evaluation_id')==job['id'] and r.get('task') in {t['task'] for t in expected} and r.get('status')=='completed' and r.get('termination')!='not_attempted' and r.get('score_reason') not in ('wrong_streak_limit','five_wrong_in_row')]
    tokens=[r.get('completion_tokens') for r in scored]
    complete=bool(scored) and all(type(t) in (int,float) and math.isfinite(t) and t>=0 for t in tokens)
    efficiency={'accuracy':sum(bool(r.get('solved')) for r in scored)/len(scored) if scored else None,'median_output_tokens':statistics.median(tokens) if complete else None,'scored_answers':len(scored),'token_data_complete':complete,'answers_per_active_minute':len(scored)/(h['elapsed_s']/60) if h['elapsed_s']>0 and not job.get('hour_timing_unknown') else None}
    hardware=hardware_records.recorded(root,manifest)
    report={'efficiency':efficiency,'hardware':hardware,'machine_key':hardware['machine_key'],'format':'hourglass-public-report-v1','model':str(job['model']),
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
    readme=f"# Hourglass Bench result\n\n![Score graph](score.svg)\n\nModel: {report['model'].replace(chr(10),' ')}\n\n**{h['weighted_points']:.2f} weighted points{star}**, {h['points']} correct. Status: **{h['state']}**.\n\nFixed difficulty weights: charts 1–10 → 1–2; games 1–5 → 1–2; math high school / undergraduate / graduate → 1 / 1.5 / 2. One award per question within 3,600 active seconds.\n\nBank fingerprint: `{report['bank_fingerprint']}`. Compare the same bank, order, repeat policy, model settings and hardware. Inference machine: {hardware['label']}. Model configuration disclosure has not been supplied.\n\n[Aggregate data](report.json)\n\nHardware source: {hardware.get('source','unknown')}.\n"
    readme+='\n### Recorded inference hardware\n\n```json\n'+json.dumps(hardware,indent=2)+'\n```\n'
    if credits:readme+='\n<sub>*Clock adjusted to exclude a harness interruption.</sub>\n'
    return {'report.json':json.dumps(report,indent=2)+'\n','score.svg':svg,'README.md':readme}


def compatible_reports(reports, scope='same'):
    if scope not in ('same','all'):raise ValueError('Invalid comparison scope.')
    if not reports:raise ValueError('No reports to compare.')
    keys=('bank_fingerprint','scoring','timing_policy','benchmark_version')+(() if scope=='all' else ('machine_key',))
    return [r for r in reports if all(r.get(k)==reports[0].get(k) for k in keys)]


def hardware_label(report):
    return report.get('hardware',{}).get('label','Hardware not recorded')


def comparison(reports, scope='same'):
    """Overlay only reports from the same bank, order and score policy."""
    if not reports:raise ValueError('No reports to compare.')
    reference=reports[0]
    compatible=compatible_reports(reports,scope)
    maximum=max(1,max(r['weighted_points'] for r in compatible))
    import math
    ymax=max(2,math.ceil(maximum/2)*2)
    colors=['#74e5c4','#9aaaff','#ffbf69','#f58aaa','#7ed5ff','#d5adff','#f5e384','#a9db80']
    height=720+len(compatible)*32
    elements=[f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" viewBox="0 0 900 {height}"><rect width="900" height="{height}" fill="#101722"/><g font-family="sans-serif" fill="#eaf0fa">',
              f'<text x="45" y="38" font-size="24">Hourglass Bench · {html.escape("All hardware" if scope=="all" else hardware_label(reference))}</text>',
              '<text x="45" y="65" font-size="13">Cumulative weighted points · each step is a correct answer · flat means no new points</text>']
    for i in range(5):
        value=ymax*i/4;y=580-i*120
        elements.append(f'<path d="M65 {y}H850" stroke="#2c394a"/><text x="27" y="{y+5}" font-size="12">{value:g}</text>')
    for minute in range(0,61,10):
        x=65+minute/60*785
        elements.append(f'<text x="{x-8}" y="611" font-size="12">{minute}</text>')
    elements.append('<text x="390" y="645" font-size="13">Active minutes</text>')
    for i,r in enumerate(compatible):
        color=colors[i%len(colors)]
        points=' '.join(f"{65+p['seconds']/3600*785:.2f},{580-p['weighted']/ymax*480:.2f}" for p in r['curve'])
        y=692+i*32;star='*' if r.get('clock_adjustment_seconds') else ''
        label=html.escape(f"{r['model']} · {hardware_label(r)} · {r['weighted_points']:.2f}{star} · {r['raw_correct']} correct · {r['state']}")
        dash=' stroke-dasharray="7 3"' if i>=len(colors) else ''
        elements.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"{dash}/><path d="M45 {y-4}H70" stroke="{color}" stroke-width="3"{dash}/><text x="82" y="{y}" font-size="13">{label}</text>')
    if any(r.get('clock_adjustment_seconds') for r in compatible):
        elements.append(f'<text x="45" y="{height-12}" font-size="10">*Clock adjusted to exclude a harness interruption.</text>')
    elements.append('</g></svg>')
    return {'comparison.svg':''.join(elements),'comparison.json':json.dumps({'format':'hourglass-comparison-v1','scope':scope,'reports':compatible},indent=2)+'\n'}


def quadrants(reports, scope='same'):
    reference=reports[0]
    compatible=compatible_reports(reports,scope)
    points=[r for r in compatible if r.get('efficiency',{}).get('token_data_complete')]
    def fit(values,fallback,min_span,ceiling=math.inf):
        if not values:return fallback
        lo,hi=min(values),max(values);span=max(hi-lo,min_span);pad=max(span*.15,(span-(hi-lo))/2)
        step=10**math.floor(math.log10(span/4))
        return max(0,math.floor((lo-pad)/step)*step),min(ceiling,math.ceil((hi+pad)/step)*step)
    tokens=[r['efficiency']['median_output_tokens'] for r in points]
    tmin,tmax=fit(tokens,(0,1000),max([100]+[t*.1 for t in tokens]))
    amin,amax=fit([r['efficiency']['accuracy'] for r in points],(0,1),.1,1)
    left,right,top,bottom=90,840,110,500;cx=(left+right)/2;cy=(top+bottom)/2
    x=lambda t:right-(t-tmin)/(tmax-tmin)*(right-left)
    y=lambda a:bottom-(a-amin)/(amax-amin)*(bottom-top)
    colors=['#28674f','#4268b0','#ac6630','#98577d','#368893']
    height=650+len(points)*40
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" viewBox="0 0 900 {height}"><rect width="900" height="{height}" rx="16" fill="#ffffff"/><g font-family="sans-serif" fill="#34453d">',f'<text x="40" y="38" font-size="23">Accuracy × token efficiency × speed</text><text x="40" y="65" font-size="14">{html.escape("All hardware" if scope=="all" else hardware_label(reference))} · larger bubbles mean more scored answers per active minute</text>']
    for bx,by,fill in [(left,top,'#fff3d9'),(cx,top,'#e0f1e4'),(left,cy,'#f9e2df'),(cx,cy,'#e8edf8')]:
        out.append(f'<rect x="{bx}" y="{by}" width="{cx-left}" height="{cy-top}" fill="{fill}"/>')
    for i in range(5):
        a=amin+(amax-amin)*i/4;yy=y(a);xx=left+(right-left)*i/4;t=tmax-(tmax-tmin)*i/4
        out.append(f'<path d="M{left} {yy}H{right}" stroke="white"/><text x="75" y="{yy+5}" text-anchor="end" font-size="12">{a*100:.1f}%</text><text x="{xx}" y="530" text-anchor="middle" font-size="12">{t:,.0f}</text>')
    out.append(f'<path d="M{cx} {top}V{bottom}M{left} {cy}H{right}" stroke="#91a195" stroke-dasharray="5 5"/><text x="90" y="93" font-size="14">Accuracy ↑</text><text x="460" y="561" text-anchor="middle" font-size="14">Median output tokens per scored answer · fewer →</text>')
    for xx,yy,label,anchor in [(100,150,'ACCURATE · MORE TOKENS','start'),(830,150,'ACCURATE · FEWER TOKENS ↗','end'),(100,485,'LESS ACCURATE · MORE TOKENS','start'),(830,485,'LESS ACCURATE · FEWER TOKENS','end')]:
        out.append(f'<text x="{xx}" y="{yy}" font-size="10" text-anchor="{anchor}">{label}</text>')
    max_speed=max([r['efficiency'].get('answers_per_active_minute') or 0 for r in points]+[.000001])
    for i,r in sorted(enumerate(points),key=lambda item:-(item[1]['efficiency'].get('answers_per_active_minute') or 0)):
        e=r['efficiency'];speed=e.get('answers_per_active_minute');radius=20*math.sqrt(speed/max_speed) if speed else 6
        px,py=x(e['median_output_tokens']),y(e['accuracy']);color=colors[i%len(colors)]
        rate=f'{speed:.2f}/min' if speed is not None else 'speed unavailable'
        name=html.escape(r['model']+' · '+hardware_label(r));label=html.escape(f"{r['model']} · {hardware_label(r)} · {e['accuracy']*100:.1f}% correct · {e['median_output_tokens']:,.0f} tokens · {rate} · n={e['scored_answers']} · {r['state']}")
        out.append(f'<circle cx="{px}" cy="{py}" r="{radius}" fill="{color}" fill-opacity=".75" stroke="white" stroke-width="3"><title>{label}</title></circle><text x="{px}" y="{py-radius-8}" text-anchor="{"end" if px>cx else "start"}" font-size="11" fill="{color}">{name}</text><text x="40" y="{607+i*40}" font-size="12" fill="{color}">{label}</text>')
    if not points:out.append('<text x="460" y="280" text-anchor="middle">No complete output-token records for this comparison</text>')
    out.append(f'<text x="40" y="{height-20}" font-size="10">Axes fit the data; quadrants bisect their ranges. Question subsets and tokenizers may differ. Bubble area is proportional to speed.</text></g></svg>')
    return {'quadrants.svg':''.join(out)}


def ranking(reports, scope='same'):
    ranked=sorted(compatible_reports(reports,scope),key=lambda r:(-r['weighted_points'],r['model'],hardware_label(r),r.get('machine_key','')))
    width=1100;height=180+len(ranked)*86;maximum=max(1,max(r['weighted_points'] for r in ranked))
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}" fill="#101722"/><g font-family="sans-serif" fill="#eaf0fa">',
         '<text x="36" y="42" font-size="26">Hourglass Bench · score ranking</text>',
         f'<text x="36" y="70" font-size="14">{html.escape("All hardware" if scope=="all" else hardware_label(reports[0]))} · weighted points · higher is better</text>',
         '<text x="36" y="95" font-size="12" fill="#aebdd0">Selected run + latest matching run per model and machine. Partial and running scores are not extrapolated.</text>']
    for i,r in enumerate(ranked):
        y=132+i*86;label=html.escape(r['model']);hardware=html.escape(hardware_label(r));value=r['weighted_points'];star='*' if r.get('clock_adjustment_seconds') else ''
        out.append(f'<text x="36" y="{y}" font-size="14">{i+1}. {label}</text><text x="36" y="{y+20}" font-size="12" fill="#aebdd0">{hardware}</text><rect x="36" y="{y+30}" width="{value/maximum*830:.2f}" height="20" rx="3" fill="#74e5c4"><title>{label} · {hardware} · {value:.2f} points · {html.escape(r["state"])}</title></rect><text x="{48+value/maximum*830:.2f}" y="{y+45}" font-size="13">{value:.2f}{star} · {html.escape(r["state"])}</text>')
    out.append(f'<text x="36" y="{height-18}" font-size="11" fill="#aebdd0">Same bank, order and scoring rules. Hardware and model settings affect results. *Clock adjustment, when marked.</text></g></svg>')
    return {'ranking.svg':''.join(out)}
