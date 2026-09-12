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
            'execution':{'question_timeout_s':job.get('question_timeout_s'),'stop_after_wrong':job.get('stop_after_wrong'),'repeat':manifest.get('repeat',1),'round_policy':manifest.get('round_policy')},
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
    report.update({key:h[key] for key in ('score_version','hourglass_score','total_available_points')})
    star='*' if credits else ''
    svg=report_charts.progress_chart([report])
    readme=f"# Hourglass result\n\n![Score graph](score.svg)\n\nModel: {report['model'].replace(chr(10),' ')}\n\n**Hourglass score: {h['hourglass_score']:.1f}{star}**, {h['points']} correct. Status: **{h['state']}**.\n\nFixed difficulty weights: charts 1–10 → 1–2; games 1–5 → 1–2; math high school / undergraduate / graduate → 1 / 1.5 / 2. Awards follow the recorded attempt policy within 3,600 active seconds.\n\nBank fingerprint: `{report['bank_fingerprint']}`. Compare the same bank, order, repeat policy, model settings and hardware. Inference machine: {hardware['label']}. Model configuration disclosure has not been supplied.\n\n[Aggregate data](report.json)\n\nHardware source: {hardware.get('source','unknown')}.\n"
    if report['caveats']:
        readme+='\n## Result caveats\n\n'+'\n\n'.join('**'+c['label']+'** ('+str(c['attempts'])+' attempt(s)): '+c['message'] for c in report['caveats'])+'\n'
    if scoring_policy.is_net(h['scoring_policy']):readme+=f"\nNet scoring: +1–2 for a correct question, −1 for an incorrect final submission, zero for unsupported vision, timeout or no final submission. Gross: {h['gross_points']}; penalties: {h['penalty_points']}; abstained: {h['abstained_questions']}. Every new-round attempt earns its reward or penalty under net-hour-v3. Historical runs retain their original once-per-question award policy.\n"
    if h['scoring_policy']==scoring_policy.NET:readme+='\nExplicit abstention is not offered under net-hour-v2.\n'
    elif h['scoring_policy']==scoring_policy.WITH_ABSTENTION:readme+='\nThis historical run offered explicit abstention for zero points.\n'
    readme+='\n### Recorded inference hardware\n\n```json\n'+json.dumps(hardware,indent=2)+'\n```\n'
    readme+=f"\nUnsupported vision questions within the scoring window: **{report['unsupported_vision_questions']}**. These earn zero points; no extra penalty is applied. Text and vision subtotals are reported separately.\n"
    readme+='\n## Experiment configuration\n\n'+('\n'.join('- '+k.replace('_',' ')+': '+html.escape(v) for k,v in report['experiment'].items()) or 'Configuration not recorded.')+'\n\nThese evaluations use private questions. Only aggregate results and explicitly recorded public configuration labels are published.\n'
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
    subtitle=('All versions' if scope=='history' else 'All hardware' if scope=='all' else hardware_label(reference))+' · larger bubbles mean more scored answers per active minute'
    subtitle_lines=report_charts.wrap_text(subtitle,820,14)
    annotation_top=90+(len(subtitle_lines)-1)*18
    left,right,top,bottom=90,840,annotation_top+100,annotation_top+490;cx=(left+right)/2
    x=lambda t:right-(math.log10(t)-math.log10(tmin))/(math.log10(tmax)-math.log10(tmin))*(right-left)
    y=lambda a:bottom-(a-amin)/(amax-amin)*(bottom-top)
    colors=['#28674f','#4268b0','#ac6630','#98577d','#368893']
    max_speed=max([r['efficiency'].get('answers_per_active_minute') or 0 for r in points]+[.000001])
    annotations=[]
    for i,r in enumerate(points):
        e=r['efficiency'];speed=e.get('answers_per_active_minute')
        annotations.append({'x':x(e['median_output_tokens']),'y':y(e['accuracy']),
                            'r':20*math.sqrt(speed/max_speed) if speed else 6,'color':colors[i%len(colors)],
                            'label':report_charts.label_box(r.get('display_name',r['model']))})
    # Keep full top-edge labels inside the SVG, with room above 100% accuracy.
    top=max(top,annotation_top+max((p['label']['h'] for p in annotations),default=0)+20)
    bottom=top+390
    for point,r in zip(annotations,points):point['y']=y(r['efficiency']['accuracy'])
    def captions():
        result=[]
        for xx,yy,text,anchor in [(left+10,top+40,'ACCURATE · MORE TOKENS','start'),(right-10,top+40,'ACCURATE · FEWER TOKENS ↗','end'),
                                  (left+10,bottom-15,'LESS ACCURATE · MORE TOKENS','start'),(right-10,bottom-15,'LESS ACCURATE · FEWER TOKENS','end')]:
            w=report_charts.text_width(text,10)
            lower,upper=(top+25,(top+bottom)/2-15) if yy<(top+bottom)/2 else ((top+bottom)/2+25,bottom-15)
            for candidate in sorted({yy,*range(math.ceil(lower),math.floor(upper)+1,20)},key=lambda value:(abs(value-yy),value)):
                box={'x':xx-(w if anchor=='end' else 0),'y':candidate-12,'w':w,'h':16}
                if not any(report_charts.box_hits_circle(box,p,6) for p in annotations):
                    yy=candidate;break
            result.append((xx,yy,text,anchor))
        return result
    def caption_boxes():
        return [{'x':xx-(report_charts.text_width(text,10) if anchor=='end' else 0),'y':yy-12,
                 'w':report_charts.text_width(text,10),'h':16} for xx,yy,text,anchor in captions()]+[{'x':85,'y':top-46,'w':90,'h':22}]
    bounds=(left+8,annotation_top,right-8,bottom-8)
    boxes=report_charts.place_labels(annotations,bounds,caption_boxes())
    if boxes is None:
        boxes=report_charts.place_labels(annotations,bounds,caption_boxes(),clear_leaders=False)
    expanded=boxes is None
    if expanded:
        # If the plot is saturated, add an annotation band. Keep every full label
        # at the same font size; the underlying scales and bubble areas stay exact.
        cell_w=max(p['label']['w'] for p in annotations)+12
        cell_h=max(p['label']['h'] for p in annotations)+12
        columns=max(1,int((right-left-16+12)//cell_w));rows=math.ceil(len(annotations)/columns)
        top=annotation_top+rows*cell_h+45;bottom=top+390
        for point,r in zip(annotations,points):point['y']=y(r['efficiency']['accuracy'])
        boxes=[None]*len(annotations)
        for slot,index in enumerate(sorted(range(len(annotations)),key=lambda i:(annotations[i]['x'],annotations[i]['y'],i))):
            label=annotations[index]['label']
            boxes[index]={'x':left+8+(slot%columns)*cell_w,'y':annotation_top+(slot//columns)*cell_h,'w':label['w'],'h':label['h']}
    width=900
    cy=(top+bottom)/2
    footer_y=bottom+88
    footer='Logarithmic token axis; positive counts only ('+str(omitted)+' zero-token runs omitted). Quadrants bisect the displayed ranges. Question subsets and tokenizers may differ. Bubble area is proportional to speed.'
    footer_lines=report_charts.wrap_text(footer,width-80,10);height=footer_y+len(footer_lines)*14+22
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-label-layout="{"expanded" if expanded else "near"}"><rect width="{width}" height="{height}" rx="16" fill="#ffffff"/><g font-family="Arial,Helvetica,sans-serif" fill="#34453d">','<text x="40" y="38" font-size="23">Accuracy × token efficiency × speed</text>']
    for row,text in enumerate(subtitle_lines):out.append(f'<text x="40" y="{65+18*row}" font-size="14">{html.escape(text)}</text>')
    for bx,by,fill in [(left,top,'#fff3d9'),(cx,top,'#e0f1e4'),(left,cy,'#f9e2df'),(cx,cy,'#e8edf8')]:
        out.append(f'<rect x="{bx}" y="{by}" width="{cx-left}" height="{cy-top}" fill="{fill}"/>')
    for i in range(5):
        a=amin+(amax-amin)*i/4;yy=y(a)
        out.append(f'<path d="M{left} {yy}H{right}" stroke="white"/><text x="75" y="{yy+5}" text-anchor="end" font-size="12">{a*100:.1f}%</text>')
    for tick in log_axis['ticks']:out.append(f'<text x="{x(tick)}" y="{bottom+30}" text-anchor="middle" font-size="12">{tick:,.2f}</text>')
    out.append(f'<path d="M{cx} {top}V{bottom}M{left} {cy}H{right}" stroke="#91a195" stroke-dasharray="5 5"/><text x="90" y="{top-28}" font-size="14">Accuracy ↑</text><text x="460" y="{bottom+61}" text-anchor="middle" font-size="14">Median output tokens per scored answer · log scale · fewer →</text>')
    for xx,yy,label,anchor in captions():
        out.append(f'<text x="{xx}" y="{yy}" font-size="10" text-anchor="{anchor}">{label}</text>')
    for i,(point,box) in enumerate(zip(annotations,boxes)):
        blockers=[b for j,b in enumerate(boxes) if j!=i]+caption_boxes()
        route=report_charts.routed_leader(point,box,blockers)
        path='M'+'L'.join(f'{xx:.3f} {yy:.3f}' for xx,yy in route)
        out.append(f'<path data-leader-for="{i}" d="{path}" fill="none" stroke="{point["color"]}" stroke-width="1" stroke-opacity=".8" stroke-linejoin="round"/>')
    for i,r in sorted(enumerate(points),key=lambda item:-(item[1]['efficiency'].get('answers_per_active_minute') or 0)):
        e=r['efficiency'];speed=e.get('answers_per_active_minute');radius=20*math.sqrt(speed/max_speed) if speed else 6
        px,py=x(e['median_output_tokens']),y(e['accuracy']);color=colors[i%len(colors)]
        rate=f'{speed:.2f}/min' if speed is not None else 'speed unavailable'
        label=html.escape(f"{r.get('display_name',r['model'])} · {e['accuracy']*100:.1f}% correct · {e['median_output_tokens']:,.0f} tokens · {rate} · n={e['scored_answers']} · {r['state']}")
        out.append(f'<circle data-point="{i}" cx="{px}" cy="{py}" r="{radius}" fill="{color}" fill-opacity=".75" stroke="white" stroke-width="3"><title>{label}</title></circle>')
    for i,(point,box) in enumerate(zip(annotations,boxes)):out.append(report_charts.svg_label(point,box,i))
    if not points:out.append('<text x="460" y="280" text-anchor="middle">No complete output-token records for this comparison</text>')
    for i,text in enumerate(footer_lines):out.append(f'<text x="40" y="{footer_y+12+i*14}" font-size="10">{html.escape(text)}</text>')
    out.append('</g></svg>')
    return {'quadrants.svg':''.join(out)}


def ranking(reports, scope='same'):
    entries=[]
    for report in compatible_reports(reports,scope):
        measured=report.get('hourglass_score')
        if type(measured) not in (int,float) or not math.isfinite(measured):continue
        entries.append({'report':report,'value':measured})
    entries.sort(key=lambda e:(e['value'] is None,-e['value'] if e['value'] is not None else 0,
                               e['report']['model'],hardware_label(e['report']),e['report'].get('run_key','')))
    # Names remain complete, wrapped before rotation. Allocate their actual
    # rotated footprint so neither the first label nor neighbouring names clip.
    for entry in entries:
        r=entry['report']
        entry['lines']=[(line,12,'#eaf0fa') for line in report_charts.wrap_text(r.get('display_name',r['model']),250,12)]
        if r.get('repeat_count',1)>1:entry['lines'].append((f'Mean of {r["repeat_count"]} completed runs',10,'#92a5b9'))
    angle=math.sqrt(.5)
    label_h=max((len(e['lines'])*16 for e in entries),default=32)
    pitch_min=max(112,math.ceil(label_h/angle)+14)
    left=max(80,math.ceil(250*angle+40-pitch_min/2));right=max(40,math.ceil(label_h*angle+40-pitch_min/2))
    width=max(1100,left+right+max(1,len(entries))*pitch_min)
    scope_label='All versions · all hardware' if scope=='history' else 'All hardware' if scope=='all' else hardware_label(reports[0])
    scope_lines=report_charts.wrap_text(scope_label,width-80,12)
    legend_y=120+(len(scope_lines)-1)*17;top=legend_y+65;bottom=top+350
    pitch=(width-left-right)/max(1,len(entries));bar_width=min(82,pitch*.55)
    values=[e['value'] for e in entries if e['value'] is not None]
    low=min([0,*values]);high=max([0,*values]);span=high-low or 1
    raw_step=span/5;power=10**math.floor(math.log10(raw_step))
    step=next(m*power for m in (1,2,5,10) if m*power>=raw_step)
    low=math.floor(low/step)*step;high=math.ceil(high/step)*step
    if high==low:high=low+step
    y=lambda value:bottom-(value-low)/(high-low)*(bottom-top)
    zero=y(0);name_y=bottom+(64 if low<0 else 34);label_bottom=name_y
    for i,entry in enumerate(entries):
        center=left+(i+.5)*pitch;entry['center']=center
        corners=[]
        for row,(text,size,_) in enumerate(entry['lines']):
            for xx in (-report_charts.text_width(text,size),0):
                for yy in (row*16-size,row*16+4):
                    corners.append((center+(xx+yy)*angle,name_y+(-xx+yy)*angle))
        xs,ys=zip(*corners)
        entry['bounds']=(min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys))
        label_bottom=max(label_bottom,max(ys))
    notes=['Bars show recorded total points. Partial and live runs are not extrapolated.']
    notes.append('Compare the same bank, order and rules; details are in the run record.')
    if any(e['report'].get('clock_adjustment_seconds') for e in entries):notes.append('* Includes a disclosed clock adjustment.')
    footer_lines=[line for note in notes for line in report_charts.wrap_text(note,width-80,11)]
    footer_y=label_bottom+38;height=math.ceil(footer_y+len(footer_lines)*16+24)
    esc=html.escape
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-chart="ranking-bars">',
         f'<rect width="{width}" height="{height}" rx="14" fill="#101722"/><g font-family="Arial,Helvetica,sans-serif" fill="#eaf0fa">',
         '<text x="36" y="39" font-size="26">Hourglass · score ranking</text>',
         '<text x="36" y="69" font-size="14" fill="#c4d0df">higher is better, measures amount of agentic work completed in an hour.</text>']
    for row,text in enumerate(scope_lines):out.append(f'<text x="36" y="{94+17*row}" font-size="12" fill="#92a5b9">{esc(text)}</text>')
    out.append(f'<text x="36" y="{legend_y}" font-size="11" fill="#c4d0df">Recorded points · final, partial and live states labelled</text>')
    digits=max(0,-math.floor(math.log10(step)))
    for i in range(round((high-low)/step)+1):
        value=low+i*step;yy=y(value)
        out.append(f'<path d="M{left} {yy:.3f}H{width-right}" stroke="{"#617485" if abs(value)<1e-9 else "#253340"}"/><text x="{left-14}" y="{yy+4:.3f}" text-anchor="end" font-size="11" fill="#aebdd0">{value:,.{digits}f}</text>')
    for rank,entry in enumerate(entries,1):
        r=entry['report'];value=entry['value'];center=entry['center']
        star='*' if r.get('clock_adjustment_seconds') else ''
        state=r.get('state','unknown').replace('_',' ')
        title=r['model']+(' · '+r['display_name'] if r.get('display_name') and r['display_name']!=r['model'] else '')
        title+=f" · Measured score: {r['hourglass_score']:.2f} · {state}"
        score_attr='' if value is None else repr(value)
        out.append(f'<g data-rank="{rank}" data-model="{esc(r["model"],quote=True)}" data-score="{score_attr}"><title>{esc(title)}</title>')
        if value is not None:
            endpoint=y(value);bar_y=min(zero,endpoint);bar_h=abs(zero-endpoint)
            out.append(f'<rect data-bar="{rank}" x="{center-bar_width/2:.3f}" y="{bar_y:.3f}" width="{bar_width:.3f}" height="{bar_h:.3f}" fill="#74e5c4"/>')
            label_y=endpoint-26 if value>=0 else endpoint+23
            number=f'{value:.1f}'+star
            status=state
        else:
            out.append(f'<path d="M{center-10:.3f} {zero:.3f}h20" stroke="#7890a5" stroke-width="2"/>')
            label_y=zero-26;number='—';status='score unavailable'
        out.append(f'<text x="{center:.3f}" y="{label_y:.3f}" text-anchor="middle" font-size="18" font-weight="600">{number}</text><text x="{center:.3f}" y="{label_y+17:.3f}" text-anchor="middle" font-size="10" fill="#aebdd0">{esc(status)}</text></g>')
        bounds=','.join(f'{v:.3f}' for v in entry['bounds'])
        out.append(f'<g data-name-for="{rank}" data-label-bounds="{bounds}" transform="translate({center:.3f} {name_y:.3f}) rotate(-45)" text-anchor="end">')
        for row,(text,size,color) in enumerate(entry['lines']):out.append(f'<text x="0" y="{row*16}" font-size="{size}" fill="{color}">{esc(text)}</text>')
        out.append('</g>')
    if not entries:out.append(f'<text x="{width/2}" y="{(top+bottom)/2}" text-anchor="middle" fill="#aebdd0">No comparable Hourglass scores available</text>')
    for row,text in enumerate(footer_lines):out.append(f'<text x="36" y="{footer_y+16*row:.3f}" font-size="11" fill="#92a5b9">{esc(text)}</text>')
    out.append('</g></svg>')
    return {'ranking.svg':''.join(out)}
