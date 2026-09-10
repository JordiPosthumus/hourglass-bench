#!/usr/bin/env python3
"""Version the installed private bank and export a verified, immutable Git bundle."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def inventory(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '.git' not in p.relative_to(root).parts
            and '__pycache__' not in p.parts and p.name != '.DS_Store' and p.suffix != '.pyc'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--message', required=True)
    parser.add_argument('--backup-dir', type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    bank=root/'private-question-bank'
    if git(bank, 'status', '--porcelain'):
        raise SystemExit('The private bank has uncommitted edits. Review and commit those before syncing an installed-bank snapshot.')
    if git(bank, 'remote'):
        raise SystemExit('The private bank has a remote configured. Review it before using this local-only workflow.')
    registered=[Path(p).resolve() for p in json.loads((root/'private-data-paths.json').read_text())['paths']]
    destination=(args.backup_dir or registered[0]).expanduser().resolve()
    if destination not in registered:
        raise SystemExit('Register this exact backup directory in private-data-paths.json before exporting private answers.')
    # Snapshot only the installed bank and summaries. Author audit files stay
    # under their own reviewed Git history and are never overwritten here.
    source=root/'tasks';target=bank/'tasks'
    current=inventory(source)
    for name in inventory(target):
        if name not in current:(target/name).unlink()
    for name in current:
        p=target/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,p)
    shutil.copy2(root/'question-summaries.json',bank/'question-summaries.json')
    import web
    catalog=web.task_catalog()
    (bank/'roster.json').write_text(json.dumps({'version':web.hourglass.BENCHMARK_VERSION,'order_policy':web.ORDER_POLICY,
        'order':[t['id'] for t in catalog],'catalog':catalog},indent=2)+'\n')
    git(bank, 'add', '--', 'tasks', 'question-summaries.json', 'roster.json')
    if git(bank, 'diff', '--cached', '--name-only'):
        git(bank, 'commit', '-m', args.message)
    commit=git(bank, 'rev-parse', 'HEAD')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    name=f'hourglass-questions-{stamp}-{commit[:12]}.bundle'
    exports=root/'backups/question-bank-exports';exports.mkdir(parents=True,exist_ok=True)
    bundle=exports/name
    git(bank, 'bundle', 'create', str(bundle), '--all')
    git(bank, 'bundle', 'verify', str(bundle))
    with tempfile.TemporaryDirectory(prefix='question-bank-restore-', dir=exports) as temp:
        restored=Path(temp)/'restored'
        subprocess.run(['git','clone','--quiet',str(bundle),str(restored)],check=True)
        if git(restored,'rev-parse','HEAD')!=commit or inventory(restored)!=inventory(bank):
            raise RuntimeError('Bundle restore did not exactly match the committed private bank.')
    digest=hashlib.sha256(bundle.read_bytes()).hexdigest()
    destination.mkdir(parents=True,exist_ok=True)
    exported=destination/name
    with exported.open('xb') as out, bundle.open('rb') as src:shutil.copyfileobj(src,out)
    if hashlib.sha256(exported.read_bytes()).hexdigest()!=digest:
        raise RuntimeError('Exported bundle hash mismatch; local verified bundle retained.')
    record={'format':'hourglass-private-bank-backup-v1','commit':commit,'bundle':name,'sha256':digest,
            'bytes':bundle.stat().st_size,'questions':len(catalog),'restore_verified':True,
            'icloud_status':'Written and read back locally. Cloud upload completion is not verified.'}
    exported.with_suffix('.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({**record,'path':str(exported)},indent=2))


if __name__=='__main__':main()
