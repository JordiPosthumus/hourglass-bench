"""Public experiment labels and aggregate model history; never reads task content."""
import datetime as dt
import hashlib
import html
import json
from pathlib import Path

FIELDS=('model_family','model_revision','configuration','quantization','inference_engine','harness_revision','parameters')

def load(root,jid):
    path=Path(root)/'evaluations'/(jid+'.experiment.json')
    return json.loads(path.read_text()) if path.exists() else {}

def clean(value):
    if not isinstance(value,dict) or set(value)-set(FIELDS):raise ValueError('Unknown experiment field.')
    result={}
    for key,text in value.items():
        if not isinstance(text,str) or len(text)>500:raise ValueError('Experiment fields must be text of at most 500 characters.')
        if text.strip():result[key]=text.strip()
    return result

def save(root,jid,value):
    value=clean(value);path=Path(root)/'evaluations'/(jid+'.experiment.json')
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)
    return value

def revision(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def cohort(r):
    return tuple(json.dumps(r.get(k),sort_keys=True) for k in ('bank_fingerprint','scoring','timing_policy','benchmark_version','question_timeout_policy','execution','machine_key'))

def family(r):return r.get('experiment',{}).get('model_family') or r['model']

def label(r):
    e=r.get('experiment',{})
    return ' · '.join(x for x in (r.get('run_date','Unknown date')[:10],e.get('model_revision'),e.get('configuration')) if x)

def evolution(reports):
    """Small multiples separate incompatible protocols/hardware and final/partial runs."""
    groups={}
    reports=sorted(reports,key=lambda x:(x.get('run_date') or '',x.get('run_key') or ''))
    numbers={id(r):i+1 for i,r in enumerate(reports)}
    for r in sorted(reports,key=lambda x:(x.get('run_date') or '',x.get('run_key') or '')):
        groups.setdefault((cohort(r),r.get('state')=='final'),[]).append(r)
    height=max(180,260*len(groups));out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}"><rect width="1000" height="{height}" fill="white"/><g font-family="sans-serif" fill="#263e32">']
    for i,((key,final),rs) in enumerate(groups.items()):
        top=i*260;maximum=max(1,*[r['weighted_points'] for r in rs]);points=[]
        heading=f"{family(rs[0])} · {rs[0].get('hardware',{}).get('label','Unknown hardware')} · {'Final' if final else 'Partial snapshots (not directly comparable)'} · protocol {hashlib.sha256(str(key).encode()).hexdigest()[:8]}"
        out.append(f'<text x="30" y="{top+25}" font-size="14">{html.escape(heading[:135])}</text>')
        for n,r in enumerate(rs):
            x=65+n*860/max(1,len(rs)-1);y=top+170-r['weighted_points']/maximum*110;points.append(f'{x},{y}')
            title=label(r)+f" · {r['weighted_points']:.2f} points · {r.get('active_seconds',0):.0f}s"
            out.append(f'<circle cx="{x}" cy="{y}" r="5" fill="#217b55"><title>{html.escape(title)}</title></circle><text x="{x}" y="{y-12}" text-anchor="middle" font-size="12">{r["weighted_points"]:.2f}</text><text x="{x}" y="{top+200}" text-anchor="middle" font-size="10">{html.escape((r.get("run_date") or "Unknown")[:10])}</text><text x="{x}" y="{top+219}" text-anchor="middle" font-size="10">#{numbers[id(r)]}</text>')
        if final:out.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#217b55" stroke-width="1"/>')
    if not groups:out.append('<text x="30" y="70">No published runs yet.</text>')
    out.append('</g></svg>');return ''.join(out)

PUBLIC_KEYS=('format','model','run_key','run_date','experiment','hardware','machine_key','bank_fingerprint','scoring','timing_policy','benchmark_version','question_timeout_policy','execution','state','weighted_points','raw_correct','active_seconds','efficiency','clock_adjustment_seconds','curve','breakdown','unsupported_vision_questions','auc')

def catalog_files(existing,report,token):
    entry={k:report[k] for k in PUBLIC_KEYS if k in report};entry['report_folder']=token
    # Republishing one run updates its catalog entry; immutable snapshot folders remain.
    entries=[e for e in existing if not report.get('run_key') or e.get('run_key')!=report['run_key']]+[entry]
    entries.sort(key=lambda r:(r.get('run_date') or '',r.get('run_key') or ''))
    lines=['# Results','',"I use private questions for my Hourglass Bench evaluations. Published reports contain aggregate scores and deliberately recorded configuration labels; questions, answers and traces remain private.",'','Each row is a dated run. Improvement charts group a model family and keep hardware, bank and execution protocols separate. Partial runs are shown separately and are not extrapolated. Changes are observations, not proof that one configuration caused an improvement.','']
    def cell(v):return html.escape(str(v)).replace('|','&#124;').replace('\n',' ')
    families={}
    for r in entries:families.setdefault(family(r),[]).append(r)
    files={'reports/catalog.json':json.dumps(entries,indent=2)+'\n'}
    for name,rs in sorted(families.items()):
        slug=hashlib.sha256(name.encode()).hexdigest()[:16]
        files[f'reports/models/{slug}.svg']=evolution(rs)
        lines += ['## '+cell(name),'',f'![Model history](models/{slug}.svg)','','| # | Run date | Revision / configuration | Hardware | Points | Text | Vision | Vision unsupported | AUC point-min | Status | Report |','|---|---|---|---|---:|---:|---:|---:|---:|---|---|']
        for n,r in enumerate(rs,1):
            e=r.get('experiment',{});lines.append(f"| {n} | {cell(r.get('run_date','Unknown'))} | {cell(' / '.join(filter(None,[e.get('model_revision'),e.get('configuration')])) or 'Unrecorded')} | {cell(r.get('hardware',{}).get('label','Unknown'))} | {r['weighted_points']:.2f} | {cell(r.get('breakdown',{}).get('text',{}).get('weighted_points','—'))} | {cell(r.get('breakdown',{}).get('vision',{}).get('weighted_points','—'))} | {cell(r.get('unsupported_vision_questions','—'))} | {cell(r.get('auc',{}).get('point_minutes') if r.get('auc',{}).get('state')=='final' else 'Pending')} | {cell(r['state'])} | [Snapshot]({r['report_folder']}/README.md) |")
        lines.append('')
        import score_report
        panels={}
        for r in rs:panels.setdefault((cohort(r),r.get('state')=='final'),[]).append(r)
        for number,group in enumerate(panels.values(),1):
            # Reuse the same charts with each dated configuration as a separate series.
            if not all(r.get('curve') for r in group):continue
            variants=[{**r,'model':label(r)+' · '+r.get('experiment',{}).get('quantization','')} for r in group]
            prefix=f'models/{slug}-{number}'
            for generated in (score_report.comparison(variants),score_report.quadrants(variants),score_report.ranking(variants)):
                for name,body in generated.items():
                    if name.endswith('.svg'):files[f'reports/{prefix}-{name}']=body
            lines += [f'### Configuration comparison {number}', '',
                      f"{cell(group[0].get('hardware',{}).get('label','Unknown hardware'))} · {'Final runs' if group[0].get('state')=='final' else 'Partial runs; elapsed time differs'}", '',
                      f'![Score trajectories]({prefix}-comparison.svg)', '',
                      f'![Accuracy, token efficiency and speed]({prefix}-quadrants.svg)', '',
                      f'[Score ranking]({prefix}-ranking.svg)', '']
    files['reports/README.md']='\n'.join(lines)+'\n'
    return files
