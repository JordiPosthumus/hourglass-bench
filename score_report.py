"""Aggregate-only, reviewable public reports. Never serialize raw benchmark records."""
import datetime as dt
import hashlib
import html
import json
import statistics
import math
import attempt_annotations
import repair_runs
import hour_score
import scoring_policy
import score_weights
import hardware_records
import results_history
import report_charts
import run_editor


def build(root, job, rows, manifest):
    if manifest.get('repair'):
        job={**job,'repair':manifest['repair'],'_repair_rows_materialized':True}
        rows=repair_runs.composite_rows(job,rows)
    rows=attempt_annotations.apply(root,rows)
    if manifest.get('results_reset'):job={**job,'results_reset':manifest['results_reset']}
    expected=score_weights.enrich(root,manifest['expected'])
    h=hour_score.score(job,rows,expected)
    if h['state']=='unavailable':raise ValueError(h['timing_note']+' This score cannot be published.')
    if any(t.get('weight_version')!=score_weights.VERSION for t in expected):
        raise ValueError('Cannot verify the frozen difficulty of every question.')
    identity={'questions':[(t.get('task_bundle_sha',t['task_sha']),t['weight'],t.get('vision',False),t['repeat']) for t in expected],
              'order':[next(t.get('task_bundle_sha',t['task_sha']) for t in expected if t['task']==tid) for tid in manifest['order']]}
    if manifest.get('option_layout_policy'):identity['option_layout_policy']=manifest['option_layout_policy']
    ledger=root/'timing-corrections.json'
    corrections=json.loads(ledger.read_text()) if ledger.exists() else []
    credits=[c for c in corrections if c.get('evaluation_id')==job['id']]
    intervals=job.get('active_intervals') or [{'start':job['started'],'end':job.get('ended')}]
    events=[]
    for r in rows:
        if r.get('evaluation_id')!=job['id']:continue
        try:ts=dt.datetime.fromisoformat(r['ts']).timestamp()
        except (KeyError,ValueError,TypeError):continue
        active=repair_runs.elapsed_at(job,r) if job.get('repair') else sum(max(0,min(ts,p.get('end') or ts)-p['start']) for p in intervals)
        if active<=min(3600,h['elapsed_s']):events.append((active,r))
    points=[{'seconds':0,'weighted':0,'correct':0}];filtered=[]
    for active,r in sorted(events,key=lambda e:e[0]):
        points.append({**points[-1],'seconds':round(active,3)})
        filtered.append(r);sample=hour_score.score(job,filtered,expected)
        points.append({'seconds':round(active,3),'weighted':sample['weighted_points'],'correct':sample['points']})
    points.append({'seconds':round(min(3600,h['elapsed_s']),3),'weighted':h['weighted_points'],'correct':h['points']})

    scored=[r for r in rows if r.get('evaluation_id')==job['id'] and r.get('task') in {t['task'] for t in expected} and r.get('status')=='completed' and r.get('termination')!='not_attempted' and r.get('score_reason') not in ('wrong_streak_limit','five_wrong_in_row')]
    if scoring_policy.is_net(job.get('scoring_policy')):scored=[r for r in scored if scoring_policy.final_answer(r)]
    tokens=[r.get('completion_tokens') for r in scored]
    complete=bool(scored) and all(type(t) in (int,float) and math.isfinite(t) and t>=0 for t in tokens)
    efficiency={'accuracy':sum(bool(r.get('solved')) for r in scored)/len(scored) if scored else None,'median_output_tokens':statistics.median(tokens) if complete else None,'scored_answers':len(scored),'token_data_complete':complete,'answers_per_active_minute':len(scored)/(h['elapsed_s']/60) if h['elapsed_s']>0 and not job.get('hour_timing_unknown') else None}
    hardware=hardware_records.recorded(root,manifest)
    report={'efficiency':efficiency,'hardware':hardware,'machine_key':hardware.get('comparison_key',hardware['machine_key']),'format':'hourglass-public-report-v1','model':str(job['model']),
            'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scoring':h['scoring_policy'],'gross_points':h['gross_points'],'net_points':h['net_points'],'incorrect_questions':h['incorrect_questions'],'abstained_questions':h['abstained_questions'],'penalty_points':h['penalty_points'],
            'timing_policy':h['version'],'benchmark_version':manifest['benchmark_version'],
            'bank_fingerprint':hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
            'is_current_run':job.get('state')=='running','state':h['state'],'weighted_points':h['weighted_points'],'raw_correct':h['points'],
            'completed_questions':h['completed_questions'],'total_questions':h['total_questions'],
            'active_seconds':round(h['elapsed_s'],3),'window_seconds':3600,
            'breakdown':h['breakdown'],'curve':points,
            'clock_adjustment_seconds':round(sum(c['credit_s'] for c in credits),3),
            'question_timeout_policy':job.get('question_timeout_policy'),
            'timeouts':h['timeouts'],
            'execution':{'question_timeout_s':job.get('question_timeout_s'),'stop_after_wrong':job.get('stop_after_wrong',20),'repeat':manifest.get('repeat',1)},
            'configuration_disclosure':'Model settings not supplied; compare only equivalent settings.'}
    report['caveats']=attempt_annotations.summary(rows,job['id'],public=True)+([repair_runs.CAVEAT] if job.get('repair') else [])
    report['unsupported_vision_questions']=len({r['task'] for active,r in events if r.get('score_reason')=='unsupported_vision'})
    report.update(run_key=hashlib.sha256(str(job['id']).encode()).hexdigest()[:24],
                  run_date=dt.datetime.fromtimestamp(job.get('started') or job.get('created') or 0,dt.timezone.utc).isoformat(),
                  experiment=results_history.load(root,job['id']))
    report['configuration_key']=run_editor.setup_key(manifest)
    if manifest.get('id'):report['display_name']=run_editor.display(root,manifest)['name']
    if job.get('repair'):report['display_name']+=' · Repaired'
    elif report['caveats']:report['display_name']+=' ⚠'
    report['auc']=report_charts.auc(points,final=h['state']=='final')
    report['auc']['scoring_policy']=h['scoring_policy']
    star='*' if credits else ''
    svg=report_charts.progress_chart([report])
    readme=f"# Hourglass Bench result\n\n![Score graph](score.svg)\n\nModel: {report['model'].replace(chr(10),' ')}\n\n**{h['weighted_points']:.2f} weighted points{star}**, {h['points']} correct. Status: **{h['state']}**.\n\nFixed difficulty weights: charts 1–10 → 1–2; games 1–5 → 1–2; math high school / undergraduate / graduate → 1 / 1.5 / 2. One award per question within 3,600 active seconds.\n\nBank fingerprint: `{report['bank_fingerprint']}`. Compare the same bank, order, repeat policy, model settings and hardware. Inference machine: {hardware['label']}. Model configuration disclosure has not been supplied.\n\n[Aggregate data](report.json)\n\nHardware source: {hardware.get('source','unknown')}.\n"
    if report['caveats']:
        readme+='\n## Result caveats\n\n'+'\n\n'.join('**'+c['label']+'** ('+str(c['attempts'])+' attempt(s)): '+c['message'] for c in report['caveats'])+'\n'
    if scoring_policy.is_net(h['scoring_policy']):readme+=f"\nNet scoring: +1–2 for a correct question, −1 for an incorrect final submission, zero for unsupported vision, timeout or no final submission. Gross: {h['gross_points']}; penalties: {h['penalty_points']}; abstained: {h['abstained_questions']}. A correct repeat supersedes an earlier incorrect answer; penalties never accumulate for repeated wrong answers to one question.\n"
    if h['scoring_policy']==scoring_policy.NET:readme+='\nExplicit abstention is not offered under net-hour-v2.\n'
    elif h['scoring_policy']==scoring_policy.WITH_ABSTENTION:readme+='\nThis historical run offered explicit abstention for zero points.\n'
    readme+='\n### Recorded inference hardware\n\n```json\n'+json.dumps(hardware,indent=2)+'\n```\n'
    readme+=f"\nUnsupported vision questions within the scoring window: **{report['unsupported_vision_questions']}**. These earn zero points; no extra penalty is applied. Text and vision subtotals are reported separately.\n"
    readme+='\n## Experiment configuration\n\n'+('\n'.join('- '+k.replace('_',' ')+': '+html.escape(v) for k,v in report['experiment'].items()) or 'Configuration not recorded.')+'\n\nThese evaluations use private questions. Only aggregate results and explicitly recorded public configuration labels are published.\n'
    a=report['auc']['point_minutes'] if report['auc']['state']=='final' else None
    readme+='\nAUC companion: '+(f'**{a:.2f} weighted point-minutes**' if a is not None else 'pending a final run')+'. This rewards points earned earlier; it does not replace the weighted one-hour score. It integrates the exact stepped score. There is no maximum or percentage normalization.\n'
    if job.get('repair'):readme+='\n**Repaired run.** '+repair_runs.NOTE+' Source: '+job['repair']['source_evaluation_id']+'.\n'
    if credits:readme+='\n<sub>*Clock adjusted to exclude a harness interruption.</sub>\n'
    if job.get('repair'):report['repair']={k:job['repair'][k] for k in ('policy','source_evaluation_id','source_version','source_elapsed_s','refunded_s','base_elapsed_s','note')}
    return {'report.json':json.dumps(report,indent=2)+'\n','score.svg':svg,'README.md':readme}


def compatible_reports(reports, scope='same'):
    if scope not in ('same','all','history'):raise ValueError('Invalid comparison scope.')
    if not reports:raise ValueError('No reports to compare.')
    if scope=='history':return list(reports)
    keys=('bank_fingerprint',)+(() if scope!='same' else ('machine_key',))
    def major(report):
        version=str(report.get('benchmark_version') or 'unknown')
        return version.split('.')[0] if version.split('.')[0].isdigit() else version
    return [r for r in reports if major(r)==major(reports[0]) and all(r.get(k)==reports[0].get(k) for k in keys)]


def hardware_label(report):
    return report.get('hardware',{}).get('label','Hardware not recorded')


def comparison(reports, scope='same'):
    """Compare the same frozen bank and major release, retaining recorded policies."""
    if not reports:raise ValueError('No reports to compare.')
    reference=reports[0]
    compatible=compatible_reports(reports,scope)
    chart=report_charts.progress_chart(compatible,scope)
    return {'comparison.svg':chart,'comparison.json':json.dumps({'format':'hourglass-comparison-v1','scope':scope,'reports':compatible},indent=2)+'\n'}


def quadrants(reports, scope='same'):
    reference=reports[0]
    compatible=compatible_reports(reports,scope)
    points=[r for r in compatible if r.get('efficiency',{}).get('token_data_complete') and (r.get('efficiency',{}).get('median_output_tokens') or 0)>0]
    omitted=sum(bool(r.get('efficiency',{}).get('token_data_complete')) and not (r.get('efficiency',{}).get('median_output_tokens') or 0)>0 for r in compatible)
    def fit(values,fallback,min_span,ceiling=math.inf):
        if not values:return fallback
        lo,hi=min(values),max(values);span=max(hi-lo,min_span);pad=max(span*.15,(span-(hi-lo))/2)
        step=10**math.floor(math.log10(span/4))
        return max(0,math.floor((lo-pad)/step)*step),min(ceiling,math.ceil((hi+pad)/step)*step)
    tokens=[r['efficiency']['median_output_tokens'] for r in points]
    log_axis=report_charts.token_axis(tokens);tmin,tmax=log_axis['min'],log_axis['max']
    amin,amax=fit([r['efficiency']['accuracy'] for r in points],(0,1),.1,1)
    left,right,top,bottom=90,840,110,500;cx=(left+right)/2;cy=(top+bottom)/2
    x=lambda t:right-(math.log10(t)-math.log10(tmin))/(math.log10(tmax)-math.log10(tmin))*(right-left)
    y=lambda a:bottom-(a-amin)/(amax-amin)*(bottom-top)
    colors=['#28674f','#4268b0','#ac6630','#98577d','#368893']
    height=650+len(points)*58
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" viewBox="0 0 900 {height}"><rect width="900" height="{height}" rx="16" fill="#ffffff"/><g font-family="sans-serif" fill="#34453d">',f'<text x="40" y="38" font-size="23">Accuracy × token efficiency × speed</text><text x="40" y="65" font-size="14">{html.escape("All versions" if scope=="history" else "All hardware" if scope=="all" else hardware_label(reference))} · larger bubbles mean more scored answers per active minute</text>']
    for bx,by,fill in [(left,top,'#fff3d9'),(cx,top,'#e0f1e4'),(left,cy,'#f9e2df'),(cx,cy,'#e8edf8')]:
        out.append(f'<rect x="{bx}" y="{by}" width="{cx-left}" height="{cy-top}" fill="{fill}"/>')
    for i in range(5):
        a=amin+(amax-amin)*i/4;yy=y(a)
        out.append(f'<path d="M{left} {yy}H{right}" stroke="white"/><text x="75" y="{yy+5}" text-anchor="end" font-size="12">{a*100:.1f}%</text>')
    for tick in log_axis['ticks']:out.append(f'<text x="{x(tick)}" y="530" text-anchor="middle" font-size="12">{tick:,.2f}</text>')
    out.append(f'<path d="M{cx} {top}V{bottom}M{left} {cy}H{right}" stroke="#91a195" stroke-dasharray="5 5"/><text x="90" y="93" font-size="14">Accuracy ↑</text><text x="460" y="561" text-anchor="middle" font-size="14">Median output tokens per scored answer · log scale · fewer →</text>')
    for xx,yy,label,anchor in [(100,150,'ACCURATE · MORE TOKENS','start'),(830,150,'ACCURATE · FEWER TOKENS ↗','end'),(100,485,'LESS ACCURATE · MORE TOKENS','start'),(830,485,'LESS ACCURATE · FEWER TOKENS','end')]:
        out.append(f'<text x="{xx}" y="{yy}" font-size="10" text-anchor="{anchor}">{label}</text>')
    max_speed=max([r['efficiency'].get('answers_per_active_minute') or 0 for r in points]+[.000001])
    for i,r in sorted(enumerate(points),key=lambda item:-(item[1]['efficiency'].get('answers_per_active_minute') or 0)):
        e=r['efficiency'];speed=e.get('answers_per_active_minute');radius=20*math.sqrt(speed/max_speed) if speed else 6
        px,py=x(e['median_output_tokens']),y(e['accuracy']);color=colors[i%len(colors)]
        rate=f'{speed:.2f}/min' if speed is not None else 'speed unavailable'
        name=html.escape(r.get('display_name',r['model'])+' · '+hardware_label(r));label=html.escape(f"{r.get('display_name',r['model'])} · {hardware_label(r)} · {e['accuracy']*100:.1f}% correct · {e['median_output_tokens']:,.0f} tokens · {rate} · n={e['scored_answers']} · {r['state']}")
        out.append(f'<circle cx="{px}" cy="{py}" r="{radius}" fill="{color}" fill-opacity=".75" stroke="white" stroke-width="3"><title>{label}</title></circle><text x="{px}" y="{py-radius-8}" text-anchor="{"end" if px>cx else "start"}" font-size="11" fill="{color}">{name}</text><text x="40" y="{607+i*58}" font-size="12" fill="{color}">{label}</text><text x="40" y="{625+i*58}" font-size="11" fill="{color}">{html.escape(report_charts.rules_label(r))}</text>')
    if not points:out.append('<text x="460" y="280" text-anchor="middle">No complete output-token records for this comparison</text>')
    out.append(f'<text x="40" y="{height-20}" font-size="10">Logarithmic token axis; positive counts only ({omitted} zero-token runs omitted). Quadrants bisect the displayed ranges. Question subsets and tokenizers may differ. Bubble area is proportional to speed.</text></g></svg>')
    return {'quadrants.svg':''.join(out)}


def ranking(reports, scope='same'):
    ranked=sorted(compatible_reports(reports,scope),key=lambda r:(-r['weighted_points'],r['model'],hardware_label(r),r.get('machine_key','')))
    width=1100;height=180+len(ranked)*86;maximum=max(1,max(abs(r['weighted_points']) for r in ranked))
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}" fill="#101722"/><g font-family="sans-serif" fill="#eaf0fa">',
         '<text x="36" y="42" font-size="26">Hourglass Bench · score ranking</text>',
         f'<text x="36" y="70" font-size="14">{html.escape("All hardware" if scope=="all" else hardware_label(reports[0]))} · weighted points · higher is better</text>',
         '<text x="36" y="95" font-size="12" fill="#aebdd0">Selected run + latest matching run per model and machine. Partial and running scores are not extrapolated.</text>']
    for i,r in enumerate(ranked):
        y=132+i*86;label=html.escape(r['model']);hardware=html.escape(hardware_label(r)+' · '+report_charts.rules_label(r));value=r['weighted_points'];star='*' if r.get('clock_adjustment_seconds') else ''
        out.append(f'<text x="36" y="{y}" font-size="14">{i+1}. {label}</text><text x="36" y="{y+20}" font-size="12" fill="#aebdd0">{hardware}</text><rect x="{451+min(0,value)/maximum*415:.2f}" y="{y+30}" width="{abs(value)/maximum*415:.2f}" height="20" rx="3" fill="#74e5c4"><title>{label} · {hardware} · {value:.2f} points · {html.escape(r["state"])}</title></rect><text x="{463+value/maximum*415:.2f}" y="{y+45}" font-size="13">{value:.2f}{star} · {html.escape(r["state"])}</text>')
    out.append(f'<text x="36" y="{height-18}" font-size="11" fill="#aebdd0">Same bank and major release; recorded scoring and deadlines may differ. *Clock adjustment, when marked.</text></g></svg>')
    return {'ranking.svg':''.join(out)}
