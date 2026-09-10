"""Reversible display/scoring corrections; original result evidence stays untouched."""
import json

CAVEATS = {
    'diagnostic_trace_exposure': {
        'label':'Trace exposure',
        'message':'Model tools read harness traces. Answers and scores are retained, but distraction and extra processing may have affected timing and the one-hour comparison. The size of the effect is unknown. Fixed for new runs in v2.5.1.'},
    'diagnostic_metadata_exposure': {
        'label':'Integrity metadata accessed',
        'message':'Model tools read harness integrity metadata. No trace feedback was observed in this attempt. Answers and scores are retained; any timing effect is unknown. Fixed for new runs in v2.5.1.'},
}


def summary(rows, job_id, public=False):
    result=[]
    for code,description in CAVEATS.items():
        affected=[r for r in rows if r.get('evaluation_id')==job_id and any(c.get('code')==code for c in r.get('caveats',[]))]
        if affected:
            entry={'code':code,**description,'attempts':len(affected)}
            if not public:entry['questions']=sorted({r['task'] for r in affected})
            result.append(entry)
    return result



def apply(root, rows):
    path=root/'attempt-annotations.json'
    if not path.exists():return rows
    annotations=json.loads(path.read_text()).get('attempts',{})
    output=[]
    for original in rows:
        annotation=annotations.get(original.get('run_id'))
        row=original
        if annotation and annotation.get('status')=='not_attempted':
            row=dict(original)
            row.update(status='not_attempted',score_reason='interrupted_retry',original_status=original.get('status'),
                       annotation=annotation,solved=False)
        if annotation:
            caveats=[{'code':c['code'],**CAVEATS[c['code']]} for c in annotation.get('caveats',[]) if c.get('code') in CAVEATS]
            if caveats:row={**row,'caveats':caveats}
        output.append(row)
    return output
