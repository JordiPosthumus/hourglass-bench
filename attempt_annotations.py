"""Reversible display/scoring corrections; original result evidence stays untouched."""
import json


def apply(root, rows):
    path=root/'attempt-annotations.json'
    if not path.exists():return rows
    annotations=json.loads(path.read_text()).get('attempts',{})
    output=[]
    for original in rows:
        annotation=annotations.get(original.get('run_id'))
        if annotation and annotation.get('status')=='not_attempted':
            row=dict(original)
            row.update(status='not_attempted',score_reason='interrupted_retry',original_status=original.get('status'),
                       annotation=annotation,solved=False)
            output.append(row)
        else:output.append(original)
    return output
