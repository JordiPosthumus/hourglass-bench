"""Fixed section scales, independent of which questions happen to be selected."""
import hashlib
import json
import math

VERSION = 'weighted-hour-v1'


def weight(task):
    section=task.get('section')
    if section=='challenge':return 2.0
    tier=task.get('tier')
    if section in ('math','math_logic'):
        return {'advanced_high_school':1.0,'advanced_undergraduate':1.5,'graduate':2.0}.get(task.get('level'),1.0)
    maximum=10 if section in ('chart','charts') or task.get('kind')=='chart-vqa' else 5 if section=='games' else None
    if maximum and isinstance(tier,(int,float)) and not isinstance(tier,bool) and math.isfinite(tier):
        return round(1+(min(maximum,max(1,tier))-1)/(maximum-1),6)
    return 1.0


def enrich(root, expected):
    """Prefer frozen metadata; backfill only from a task matching its recorded hash."""
    enriched=[]
    for item in expected:
        entry=dict(item)
        if entry.get('weight_version')==VERSION:
            enriched.append(entry);continue
        p=root/'tasks'/entry['task']/'task.json'
        if p.is_file():
            raw=p.read_bytes()
            if hashlib.sha256(raw).hexdigest()[:16]==entry.get('task_sha'):
                task=json.loads(raw)
                entry.update({k:task.get(k) for k in ('section','tier','level','kind')})
                entry.update(weight=weight(task),weight_version=VERSION)
        enriched.append(entry)
    return enriched
