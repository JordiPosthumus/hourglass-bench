"""Backed-up model additions and revision-checked JSON edits."""
import contextlib
import copy
import hashlib
import json
import shutil
import threading
import time
import uuid

LOCK=threading.RLock()


def read(root):
    path=root/'models.json'
    data=path.read_bytes() if path.exists() else None
    rev=hashlib.sha256(data).hexdigest() if data is not None else 'missing'
    try:return json.loads(data),rev
    except (ValueError,TypeError):
        example=root/'models.example.json'
        try:return json.loads(example.read_text()),rev
        except (OSError,ValueError):return {'models':[]},rev


def revision(root):
    path=root/'models.json'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else 'missing'


@contextlib.contextmanager
def editing(root):
    import fcntl
    with LOCK, (root/'.models-edit.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield


def write(root,doc):
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:6]
    backup=root/'backups'/('models-'+stamp);backup.mkdir(parents=True)
    target=root/'models.json'
    if target.exists():shutil.copy2(target,backup/'models.json')
    temporary=root/('models.tmp-'+uuid.uuid4().hex)
    temporary.write_text(json.dumps(doc,indent=2,allow_nan=False)+'\n');temporary.replace(target)
    return {'ok':True,'backup':str(backup.relative_to(root)),'revision':revision(root)}


def check_revision(root,expected):
    if expected is not None and expected!=revision(root):
        raise ValueError('Model settings changed elsewhere. Refresh and review before saving; nothing was overwritten.')


def add(root,entry,validate,expected=None):
    import model_catalog
    if not isinstance(entry,dict):raise ValueError('Enter a model configuration.')
    entry=copy.deepcopy(entry)
    entry['base_url']=model_catalog.base_url(entry.get('base_url'))
    for key in ('name','model'):
        if not isinstance(entry.get(key),str) or not entry[key].strip():raise ValueError('Enter a '+('display name' if key=='name' else 'model ID')+'.')
        entry[key]=entry[key].strip()
    if type(entry.get('max_tokens')) is not int or entry['max_tokens']<=0:
        raise ValueError('Choose a positive output token limit explicitly.')
    extra=entry.get('extra')
    if isinstance(extra,dict) and 'max_tokens' in extra and (type(extra['max_tokens']) is not int or extra['max_tokens']!=entry['max_tokens']):
        raise ValueError('extra.max_tokens conflicts with the visible output token limit. Match or remove that override.')
    if 'context_window' in entry and (type(entry['context_window']) is not int or entry['context_window']<=0):
        raise ValueError('Context length must be a positive integer, or leave it blank for server discovery.')
    with editing(root):
        check_revision(root,expected)
        path=root/'models.json';doc=json.loads(path.read_text()) if path.exists() else read(root)[0]
        errors=validate(doc)
        if errors:raise ValueError('Fix the existing JSON first: '+'; '.join(errors))
        if any(m['name']==entry['name'] for m in doc['models']):raise ValueError('That display name is already saved. Choose another name for this configuration.')
        doc['models'].append(entry)
        errors=validate(doc)
        if errors:raise ValueError('; '.join(errors))
        result=write(root,doc)
        return {**result,'name':entry['name']}


def save_json(root,text,validate,expected=None):
    doc=json.loads(text);errors=validate(doc)
    if errors:raise ValueError('; '.join(errors))
    with editing(root):
        check_revision(root,expected)
        return write(root,doc)
