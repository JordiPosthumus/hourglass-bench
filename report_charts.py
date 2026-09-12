"""Recorded points-over-time charts with directly identifiable runs."""
import html
import heapq
import math
import unicodedata

COLORS=('#177b61','#5079c1','#bd7c39','#a26c99','#469aac','#9a9450')

# Arial advances, in thousandths of an em. Report SVGs use the same font;
# conservative fallback widths keep unrecognized glyphs visible without a
# system-font or plotting-library dependency on the report server.
_ARIAL=(278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,584,584,584,556,1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,278,278,278,469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,556,500,722,500,500,500,334,260,334,584)


def text_width(text, size=11):
    def advance(char):
        if unicodedata.combining(char):return 0
        if 32<=ord(char)<127:return _ARIAL[ord(char)-32]
        if char=='·':return 278
        return 1000
    return sum(advance(c) for c in text)*size/1000*1.03


def wrap_text(text, width, size=11):
    """Keep the full text; prefer spaces and existing identifier separators."""
    lines=[]
    for paragraph in str(text).splitlines() or ['']:
        remaining=paragraph.strip()
        while remaining:
            end=0;last_break=0
            while end<len(remaining) and text_width(remaining[:end+1],size)<=width:
                if remaining[end].isspace() or remaining[end] in '-/·':last_break=end+1
                end+=1
            if end<len(remaining) and last_break:end=last_break
            end=max(1,end)
            lines.append(remaining[:end].rstrip());remaining=remaining[end:].lstrip()
    return lines or ['']


def label_box(name, width=210):
    lines=[(line,9) for line in wrap_text(name,width,9)]
    return {'lines':lines,'w':max(text_width(line,size) for line,size in lines)+16,
            'h':len(lines)*12+12}


def boxes_overlap(a,b,pad=0):
    return a['x']<b['x']+b['w']+pad and b['x']<a['x']+a['w']+pad and a['y']<b['y']+b['h']+pad and b['y']<a['y']+a['h']+pad


def box_hits_circle(box,point,pad=0):
    dx=point['x']-max(box['x'],min(point['x'],box['x']+box['w']))
    dy=point['y']-max(box['y'],min(point['y'],box['y']+box['h']))
    return dx*dx+dy*dy<(point['r']+pad)**2


def label_leader(point,box):
    """Connect the bubble perimeter to the nearest edge of its label."""
    tx=max(box['x'],min(point['x'],box['x']+box['w']))
    ty=max(box['y'],min(point['y'],box['y']+box['h']))
    dx,dy=tx-point['x'],ty-point['y'];distance=math.hypot(dx,dy)
    fraction=min(1,(point['r']+2)/distance) if distance else 0
    return (point['x']+dx*fraction,point['y']+dy*fraction,tx,ty)


def segment_hits_box(segment,box,pad=0):
    x,y,tx,ty=segment;dx,dy=tx-x,ty-y;lo,hi=0.,1.
    for origin,delta,lower,upper in [(x,dx,box['x']-pad,box['x']+box['w']+pad),
                                   (y,dy,box['y']-pad,box['y']+box['h']+pad)]:
        if abs(delta)<1e-9:
            if not lower<origin<upper:return False
        else:
            a,b=sorted(((lower-origin)/delta,(upper-origin)/delta));lo=max(lo,a);hi=min(hi,b)
            if lo>=hi:return False
    return True


def place_labels(points,bounds,obstacles=(),clear_leaders=True):
    """Search several placements so a crowded label cannot trap its neighbour.

    Bubble positions are immutable. Return None when more annotation space is
    needed; callers must allocate that space rather than discard any labels.
    """
    left,top,right,bottom=bounds
    candidates=[]
    for point in points:
        w,h=point['label']['w'],point['label']['h']
        if w>right-left or h>bottom-top:return None
        xs={left,right-w,point['x']-w/2,point['x']-w-point['r']-10,point['x']+point['r']+10}
        ys={top,bottom-h,point['y']-h/2,point['y']-point['r']-h-10,point['y']+point['r']+10}
        xs.update(range(math.ceil(left),math.floor(right-w)+1,20))
        ys.update(range(math.ceil(top),math.floor(bottom-h)+1,12))
        choices=[]
        for xx in sorted(xs):
            if not left<=xx<=right-w:continue
            for yy in sorted(ys):
                if not top<=yy<=bottom-h:continue
                box={'x':xx,'y':yy,'w':w,'h':h}
                if any(boxes_overlap(box,other,8) for other in obstacles):continue
                if any(box_hits_circle(box,p,7) for p in points):continue
                leader=label_leader(point,box)
                if clear_leaders and any(segment_hits_box(leader,other,2) for other in obstacles):continue
                distance=math.hypot(leader[2]-leader[0],leader[3]-leader[1])
                score=distance+abs(xx+w/2-point['x'])*.12+abs(yy+h/2-point['y'])*.05
                choices.append((score,box,leader))
        if not choices:return None
        candidates.append(sorted(choices,key=lambda choice:choice[0]))
    # Most constrained first, retaining alternative layouts at each step.
    order=sorted(range(len(points)),key=lambda i:(len(candidates[i]),i))
    beam=[(0,{})]
    for index in order:
        layouts=[]
        for total,placed in beam:
            accepted=0
            for score,box,leader in candidates[index]:
                if any(boxes_overlap(box,other[0],8) or (clear_leaders and (
                       segment_hits_box(leader,other[0],2) or
                       segment_hits_box(other[1],box,2))) for other in placed.values()):continue
                layouts.append((total+score,{**placed,index:(box,leader)}))
                accepted+=1
                if accepted==24:break
        if not layouts:return None
        beam=sorted(layouts,key=lambda layout:layout[0])[:24]
    return [beam[0][1][i][0] for i in range(len(points))]


def routed_leader(point,box,blockers):
    """Use a direct connector when clear, otherwise route around label boxes."""
    direct=label_leader(point,box)
    if not any(segment_hits_box(direct,b,2) for b in blockers):
        return [(direct[0],direct[1]),(direct[2],direct[3])]
    # A small visibility graph gives short, reproducible elbowed connectors.
    # Include the destination label as an obstacle, with ports just outside it.
    expanded=[{'x':b['x']-4,'y':b['y']-4,'w':b['w']+8,'h':b['h']+8} for b in [*blockers,box]]
    bx,by,w,h=box['x'],box['y'],box['w'],box['h']
    tx=max(bx+4,min(point['x'],bx+w-4));ty=max(by+4,min(point['y'],by+h-4))
    ports=[((tx,by-5),(tx,by)),((tx,by+h+5),(tx,by+h)),
           ((bx-5,ty),(bx,ty)),((bx+w+5,ty),(bx+w,ty))]
    nodes=[(point['x'],point['y'])]+[p for p,_ in ports]
    for b in expanded:
        nodes.extend((xx,yy) for xx in (b['x'],b['x']+b['w']) for yy in (b['y'],b['y']+b['h']))
    edges=[[] for _ in nodes]
    for i,a in enumerate(nodes):
        for j in range(i):
            b=nodes[j]
            if any(segment_hits_box((*a,*b),obstacle) for obstacle in expanded):continue
            distance=math.hypot(a[0]-b[0],a[1]-b[1])
            edges[i].append((j,distance));edges[j].append((i,distance))
    queue=[(0,0)];cost={0:0};previous={}
    while queue:
        distance,index=heapq.heappop(queue)
        if distance>cost[index]:continue
        if 1<=index<=4:
            route=[ports[index-1][1],nodes[index]]
            while index in previous:
                index=previous[index];route.append(nodes[index])
            route.reverse()
            dx,dy=route[1][0]-route[0][0],route[1][1]-route[0][1]
            length=math.hypot(dx,dy);fraction=min(1,(point['r']+2)/length) if length else 0
            route[0]=(point['x']+dx*fraction,point['y']+dy*fraction)
            return route
        for other,step in edges[index]:
            updated=distance+step
            if updated<cost.get(other,math.inf):
                cost[other]=updated;previous[other]=index;heapq.heappush(queue,(updated,other))
    # Non-overlapping rectangles with the source outside have a route. Reaching
    # this branch indicates an invalid caller layout, not a reason to hide text.
    raise ValueError('Chart connector source is enclosed by an annotation.')


def svg_label(point,box,index):
    color=point['color'];x,y=box['x'],box['y'];w,h=box['w'],box['h']
    out=[f'<g data-label-for="{index}" data-box="{x:.3f},{y:.3f},{w:.3f},{h:.3f}">']
    for row,(text,size) in enumerate(point['label']['lines']):
        out.append(f'<text x="{x+8:.3f}" y="{y+13+row*12:.3f}" font-size="{size}" fill="{color}">{html.escape(text)}</text>')
    out.append('</g>');return ''.join(out)

def color_for(index):
    return COLORS[index] if index<len(COLORS) else f'hsl({(index*137.508)%360:.1f},52%,42%)'

def rules_label(report):
    version=report.get('benchmark_version') or 'unknown'
    policy=report.get('scoring') or 'unknown scoring'
    limit=report.get('execution',{}).get('question_timeout_s')
    deadline=f'{limit:g}s/question' if isinstance(limit,(int,float)) and limit>0 else ('900s/question' if report.get('question_timeout_policy')=='question-900s-auto-advance-v1' else 'legacy question limits' if not report.get('question_timeout_policy') else str(report['question_timeout_policy']))
    caveat=' · ⚠ '+', '.join(c['label'] for c in report.get('caveats',[])) if report.get('caveats') else ''
    return f'v{version} · {policy} · {deadline}'+caveat


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
    width=1440;left,right,top,bottom=82,1030,132,max(560,132+len(reports)*56)
    height=bottom+140+(math.ceil(len(reports)/2)*64 if legend else 0)
    values=[0,1]+[p['weighted'] for r in reports for p in r['curve']]+[r['weighted_points'] for r in reports]
    ymin,ymax=min(values),max(values);span=ymax-ymin
    ymin-=span*.04 if ymin<0 else 0;ymax+=span*.04
    x=lambda s:left+min(3600,s)/3600*(right-left)
    y=lambda v:bottom-(v-ymin)/(ymax-ymin)*(bottom-top)
    hardware=('All runs · all benchmark versions' if scope=='history' else 'All hardware') if scope!='same' else reports[0].get('hardware',{}).get('label','Hardware not recorded')
    esc=html.escape
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-plot-right="{right}" data-plot-bottom="{bottom}" style="max-width:100%;height:auto"><rect width="{width}" height="{height}" rx="20" fill="#f5f7f5"/><g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" fill="#233f35">',
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
    positions={}
    ordered=sorted(enumerate(reports),key=lambda item:y(item[1]['curve'][-1]['weighted'] if item[1]['curve'] else 0))
    previous=top-56
    for index,r in ordered:
        positions[index]=max(previous+56,y(r['curve'][-1]['weighted'] if r['curve'] else 0))
        previous=positions[index]
    overflow=max(0,previous-(bottom-38))
    for index in positions:positions[index]-=overflow
    for index in positions:positions[index]=max(top,positions[index])
    out.append('<style>.series{transition:opacity .12s}.series:focus{outline:none}.series:hover,.series:focus{opacity:1!important}.series:hover .score-line,.series:focus .score-line{stroke-width:5}svg:has(.series:hover) .series:not(:hover),svg:has(.series:focus) .series:not(:focus){opacity:.12!important}</style>')
    rank={index:place for place,(index,r) in enumerate(sorted(enumerate(reports),key=lambda item:-item[1]['weighted_points']),1)}
    has_current=any(r.get('is_current_run') for r in reports)
    # Retain palette/legend positions while painting the selected series last.
    for i,r in sorted(enumerate(reports),key=lambda item:bool(item[1].get('is_current_run'))):
        current=bool(r.get('is_current_run'))
        opacity=1 if current or not has_current else .3
        name=r.get('display_name',r['model'])
        detail=f"{name} · {r.get('hardware',{}).get('label','Hardware not recorded')} · {r.get('run_date','')} · {r.get('run_key','')} · {r['weighted_points']:.2f} points · {r.get('state','unknown')}"
        out.append(f'<g class="series" tabindex="0" aria-label="{esc(detail,quote=True)}" opacity="{opacity}" data-series="{i}" data-current="{str(current).lower()}"><title>{esc(detail)}</title>')
        color=color_for(i);points=step_points(r['curve']);coords=' '.join(f"{x(p['seconds']):.2f},{y(p['weighted']):.2f}" for p in points)
        dash=' stroke-dasharray="7 5"' if r.get('state')!='final' else ''
        out.append(f'<polyline class="score-line" points="{coords}" fill="none" stroke="{color}" stroke-width="{6 if current else 2.2}" stroke-linecap="round" stroke-linejoin="round"{dash}/>')
        for p in measured_points(r['curve'])[1:]:
            out.append(f'<circle cx="{x(p["seconds"]):.2f}" cy="{y(p["weighted"]):.2f}" r="{4.4 if current else 3.6}" fill="white" stroke="{color}" stroke-width="{2.8 if current else 2}"><title>{esc(r.get("display_name",r["model"]))}: {p["weighted"]:.2f} points at {p["seconds"]/60:.2f} active minutes</title></circle>')
        out.append(f'<polyline points="{coords}" fill="none" stroke="transparent" stroke-width="16" pointer-events="stroke"/>')
        last=points[-1];yy=positions[i];lx=right+38
        out.append(f'<path d="M{x(last["seconds"]):.2f} {y(last["weighted"]):.2f}L{right+16} {yy+5:.2f}H{lx-8}" fill="none" stroke="{color}" stroke-opacity=".65"/>')
        lines=wrap_text(name,300,12)
        short=lines[:2]
        if len(lines)>2:short[-1]+='…'
        out.append(f'<rect x="{lx-6}" y="{yy-14}" width="338" height="53" rx="6" fill="white" fill-opacity=".9"/>')
        for row,line in enumerate(short):out.append(f'<text x="{lx}" y="{yy+row*15:.2f}" font-size="12" font-weight="600" fill="{color}">{esc(line)}</text>')
        identity=(r.get('run_date','')[:16].replace('T',' ')+' · '+r.get('run_key','')[:6]).strip(' ·')
        out.append(f'<text x="{lx}" y="{yy+34:.2f}" font-size="11" fill="{color}">#{rank[i]} · {r["weighted_points"]:.1f} pts · {esc(identity)}</text>')
        out.append('</g>')
        if legend:
            xx=40+(i%2)*530;yy=bottom+93+(i//2)*64
            star='*' if r.get('clock_adjustment_seconds') else ''
            name=r.get('display_name',r['model'])+(' · CURRENT RUN' if r.get('is_current_run') else '')
            short=name if len(name)<=57 else name[:54]+'…'
            meta=r.get('hardware',{}).get('label','Hardware not recorded')+' · '+rules_label(r)
            short_meta=meta if len(meta)<=88 else meta[:85]+'…'
            detail=f'{r["weighted_points"]:.1f}{star} points · {r.get("raw_correct",0)} correct · {r.get("state","unknown")}'
            out.append(f'<path d="M{xx} {yy-5}h22" stroke="{color}" stroke-width="3"{dash}/><text x="{xx+30}" y="{yy}" font-size="12" font-weight="600"><title>{esc(name)}</title>{esc(short)}</text><text x="{xx+30}" y="{yy+18}" font-size="11" fill="#71827a">{esc(detail)}</text><text x="{xx+30}" y="{yy+34}" font-size="10" fill="#71827a"><title>{esc(r.get("hardware",{}).get("label","Hardware not recorded"))} · {esc(rules_label(r))}</title>{esc(short_meta)}</text>')
    out.append(f'<text x="40" y="{height-27}" font-size="11" fill="#71827a">Each step is a recorded submission. Total points are the score; hover or focus a line or right-hand label to identify its run.</text>')
    if any(r.get('caveats') for r in reports):out.append(f'<text x="40" y="{height-28}" font-size="11" fill="#986810">⚠ Includes runs with diagnostic exposure; scores retained, timing impact unknown. See run caveats.</text>')
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
