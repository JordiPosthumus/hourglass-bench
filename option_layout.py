"""Reproducible option positions and IDs from a private evaluation seed."""
import copy
import hashlib
import random

POLICY='option-layout-v1'

def prepare(task,repeat,bundle,presentation_seed=""):
    result=copy.deepcopy(task)
    options=result.get('options')
    if result.get('mode')=='numeric' or not options:return result,None
    seed=hashlib.sha256(f'{POLICY}:{bundle}:{presentation_seed}:{repeat}'.encode()).hexdigest()
    rng=random.Random(int(seed,16))
    rng.shuffle(options)
    mapping={}
    for index,option in enumerate(options,1):
        old=option['id'];new=f'{index:03d}'
        mapping[new]=old
        option['id']=new
        if old==task['answer']:result['answer']=new
    result['shuffle']=False
    return result,{'policy':POLICY,'seed':seed,'display_to_original':mapping}
