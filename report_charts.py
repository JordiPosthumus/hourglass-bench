"""Presentation-only step charts and an independently versioned AUC companion."""
import html
import math

COLORS=('#177b61','#5079c1','#bd7c39','#a26c99','#469aac','#9a9450')

def color_for(index):
    return COLORS[index] if index<len(COLORS) else f'hsl({(index*137.508)%360:.1f},52%,42%)'

def rules_label(report):
    version=report.get('benchmark_version') or 'unknown'
    policy=report.get('scoring') or 'unknown scoring'
    limit=report.get('execution',{}).get('question_timeout_s')
    deadline=f'{limit:g}s/question' if isinstance(limit,(int,float)) and limit>0 else ('900s/question' if report.get('question_timeout_policy')=='question-900s-auto-advance-v1' else 'legacy question limits' if not report.get('question_timeout_policy') else str(report['question_timeout_policy']))
    return f'v{version} · {policy} · {deadline}'


def auc(curve, final=False, window_s=3600):
    """Integrate the same recorded step function shown in the chart."""
    area=0.;last_time=0.;last_value=0.
    for p in sorted(curve,key=lambda p:p['seconds']):
        current=max(0,min(window_s,p['seconds']))
        area+=last_value*max(0,current-last_time)
        last_time=current;last_value=p['weighted']
    if final:area+=last_value*max(0,window_s-last_time)
    return {'version':'weighted-step-auc-v1','point_seconds':round(area,6),
            'mean_weighted_points':round(area/window_s,6) if final else None,
            'point_minutes':round(area/60,6),
            'window_s':window_s,'state':'final' if final else 'partial',
            'normalization':None}


def step_points(curve):
    """Keep score flat until each completion, including sparse historical curves."""
    points=[{'seconds':0,'weighted':0}]
    for p in sorted(curve,key=lambda p:p['seconds']):
        previous=points[-1]
        if p['seconds']!=previous['seconds']:
            points.append({'seconds':p['seconds'],'weighted':previous['weighted']})
        if p['weighted']!=points[-1]['weighted']:
            points.append({'seconds':p['seconds'],'weighted':p['weighted']})
    return points


def measured_points(curve):
    by_time={}
    for p in curve:by_time[p['seconds']]=p
    points=[]
    ordered=sorted(by_time.values(),key=lambda p:p['seconds'])
    for i,p in enumerate(ordered):
        if not points or p['weighted']!=points[-1]['weighted'] or i==len(ordered)-1:points.append(p)
    return points


def progress_chart(reports,scope='same',legend=True):
    width=1100;height=700+math.ceil(len(reports)/2)*64 if legend else 660;left,right,top,bottom=82,1030,132,560
    values=[0,1]+[p['weighted'] for r in reports for p in r['curve']]+[r['weighted_points'] for r in reports]
    ymin,ymax=min(values),max(values);span=ymax-ymin
    ymin-=span*.04 if ymin<0 else 0;ymax+=span*.04
    x=lambda s:left+min(3600,s)/3600*(right-left)
    y=lambda v:bottom-(v-ymin)/(ymax-ymin)*(bottom-top)
    hardware='All hardware' if scope=='all' else reports[0].get('hardware',{}).get('label','Hardware not recorded')
    esc=html.escape
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="max-width:100%;height:auto"><rect width="{width}" height="{height}" rx="20" fill="#f5f7f5"/><g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" fill="#233f35">',
         '<text x="40" y="37" font-size="11" font-weight="600" letter-spacing="2" fill="#71827a">HOURGLASS BENCH</text><text x="40" y="74" font-size="29" font-weight="650">Progress through the hour</text>',
         f'<text x="40" y="101" font-size="13" fill="#6f8077">{esc(hardware[:130])} · weighted points</text>',
         f'<rect x="{left}" y="{top}" width="{right-left}" height="{bottom-top}" rx="8" fill="white"/>']
    for i in range(5):
        value=ymin+(ymax-ymin)*i/4;yy=y(value)
        out.append(f'<path d="M{left} {yy}H{right}" stroke="#e4ebe6"/><text x="{left-14}" y="{yy+4}" text-anchor="end" font-size="12" fill="#78897f">{value:.1f}</text>')
    out.append(f'<path d="M{left} {y(0)}H{right}" stroke="#71827a" stroke-width="1.5"><title>Zero points</title></path>')
    for minute in range(0,61,10):
        xx=x(minute*60);out.append(f'<text x="{xx}" y="{bottom+27}" text-anchor="middle" font-size="12" fill="#78897f">{minute}</text>')
    out.append(f'<text x="{(left+right)/2}" y="{bottom+52}" text-anchor="middle" font-size="12" fill="#78897f">ACTIVE MINUTES</text>')
    for i,r in enumerate(reports):
        color=color_for(i);points=step_points(r['curve']);coords=' '.join(f"{x(p['seconds']):.2f},{y(p['weighted']):.2f}" for p in points)
        dash=' stroke-dasharray="7 5"' if r.get('state')!='final' else ''
        out.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{4.5 if r.get('is_current_run') else 2.2}" stroke-linecap="round" stroke-linejoin="round"{dash}/>')
        for p in measured_points(r['curve'])[1:]:
            out.append(f'<circle cx="{x(p["seconds"]):.2f}" cy="{y(p["weighted"]):.2f}" r="3.6" fill="white" stroke="{color}" stroke-width="2"><title>{esc(r["model"])}: {p["weighted"]:.2f} points at {p["seconds"]/60:.2f} active minutes</title></circle>')
        if legend:
            xx=40+(i%2)*530;yy=653+(i//2)*64
            star='*' if r.get('clock_adjustment_seconds') else ''
            name=r['model']+(' · CURRENT RUN' if r.get('is_current_run') else '')
            short=name if len(name)<=57 else name[:54]+'…'
            meta=r.get('hardware',{}).get('label','Hardware not recorded')+' · '+rules_label(r)
            short_meta=meta if len(meta)<=88 else meta[:85]+'…'
            detail=f'{r["weighted_points"]:.2f}{star} points · {r.get("raw_correct",0)} correct · {r.get("state","unknown")}'
            out.append(f'<path d="M{xx} {yy-5}h22" stroke="{color}" stroke-width="3"{dash}/><text x="{xx+30}" y="{yy}" font-size="12" font-weight="600"><title>{esc(name)}</title>{esc(short)}</text><text x="{xx+30}" y="{yy+18}" font-size="11" fill="#71827a">{esc(detail)}</text><text x="{xx+30}" y="{yy+34}" font-size="10" fill="#71827a"><title>{esc(r.get("hardware",{}).get("label","Hardware not recorded"))} · {esc(rules_label(r))}</title>{esc(short_meta)}</text>')
    out.append(f'<text x="40" y="{height-27}" font-size="11" fill="#71827a">Each step marks the score after a final submission. AUC is the area under this exact step graph.</text>')
    if any(r.get('clock_adjustment_seconds') for r in reports):out.append(f'<text x="40" y="{height-10}" font-size="10" fill="#71827a">*Includes a disclosed clock adjustment.</text>')
    out.append('</g></svg>');return ''.join(out)


def token_axis(values):
    """A true base-10 axis: zero/missing token counts are not log-plottable."""
    values=[v for v in values if type(v) in (int,float) and math.isfinite(v) and v>0]
    low=math.floor(math.log10(min(values))) if values else 0
    high=max(low+1,math.ceil(math.log10(max(values)))) if values else 3
    ticks=[]
    for exponent in range(low,high+1):
        for multiplier in ((1,2,5) if high-low<=3 else (1,)):
            value=multiplier*10**exponent
            if 10**low<=value<=10**high:ticks.append(value)
    return {'min':10**low,'max':10**high,'ticks':ticks,'guide':10**((low+high)/2)}
