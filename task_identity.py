"""Full question bundle identity; legacy task.json hashes remain intact."""
import hashlib
import json
import subprocess
from pathlib import Path

POLICY='question-bundle-v1'

def identity(directory):
    directory=Path(directory).resolve()
    files={}
    for path in sorted(directory.rglob('*')):
        if '.git' in path.relative_to(directory).parts or '__pycache__' in path.parts:continue
        if path.is_symlink():raise ValueError('Question bundles must not contain symlinks.')
        if path.is_file():files[path.relative_to(directory).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    task=json.loads((directory/'task.json').read_text())
    source=task.get('source')
    if source:
        ref=source.get('sha') or source.get('ref','HEAD')
        files['@source-tree']=subprocess.check_output(['git','-C',source['repo'],'rev-parse',ref+'^{tree}'],text=True).strip()
    value={'policy':POLICY,'files':files}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def verify(directory,expected):
    actual=identity(directory)
    if expected.get('task_bundle_sha') and actual!=expected['task_bundle_sha']:
        raise ValueError('Question bundle changed after review; start a fresh run.')
    raw=hashlib.sha256((Path(directory)/'task.json').read_bytes()).hexdigest()[:16]
    if raw!=expected['task_sha']:raise ValueError('Question content changed after review; start a fresh run.')
    return actual
