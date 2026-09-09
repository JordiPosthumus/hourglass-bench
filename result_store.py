"""Append-only result publication with recoverable per-attempt commits."""
import json
import datetime as dt
import fcntl
from pathlib import Path
import urllib.parse


def append(root, record):
    path = Path(root)/'results'/'results.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if path.exists() and path.stat().st_size:
        with path.open('rb') as stream:
            stream.seek(-1, 2)
            needs_newline = stream.read(1) != b'\n'
    with path.open('a') as stream:
        if needs_newline:
            stream.write('\n')  # Preserve a torn old line instead of overwriting it.
        stream.write(json.dumps(record, allow_nan=False) + '\n')


def commit(root, directory, record):
    path = Path(directory)/'metrics.json'
    temporary = path.with_name('metrics.json.tmp')
    temporary.write_text(json.dumps(record, indent=1, allow_nan=False))
    temporary.replace(path)
    append(root, record)


def _reconcile(root, manifest):
    """Restore completed commits missing from the index; never rewrite old rows."""
    root = Path(root)
    index = root/'results'/'results.jsonl'
    known = set()
    if index.exists():
        for line in index.read_text().splitlines():
            try:
                known.add(json.loads(line).get('run_id'))
            except (ValueError, AttributeError, TypeError):
                pass
    restored = []
    for expected in manifest.get('expected', []):
        directory = root/'results'/expected['task']/urllib.parse.quote(manifest['model'], safe='')
        for path in directory.glob('run-*/metrics.json'):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(record,dict) or not path.resolve().is_relative_to((root/'results').resolve()):
                continue
            rid = record.get('run_id')
            if not isinstance(rid,str) or not rid or rid in known or record.get('evaluation_id') != manifest['id']:
                continue
            if record.get('model_config_hash') != manifest.get('config_hash') or record.get('task_sha') != expected['task_sha']:
                continue
            if record.get('task') != expected['task'] or record.get('model') != manifest['model']:
                continue
            if record.get('artifact_dir') != str(path.parent.relative_to(root)):
                continue
            if type(record.get('run')) is not int or not 1 <= record['run'] <= expected.get('repeat', 1):
                continue
            if record.get('status') not in ('completed', 'error', 'timeout') or not record.get('ts'):
                continue
            try:
                stamp=dt.datetime.fromisoformat(record['ts'])
                if stamp.tzinfo is None:continue
            except (TypeError,ValueError):continue
            restored.append((path, record))
            known.add(rid)
    if restored:
        # Keep the original index byte-for-byte before adding recovered commits.
        backup = root/'backups'/('reconciled-results-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup.mkdir(parents=True)
        if index.exists():
            (backup/'results-before.jsonl').write_bytes(index.read_bytes())
        (backup/'recovered-run-ids.json').write_text(json.dumps([r['run_id'] for _, r in restored]))
        for _, record in sorted(restored, key=lambda item: item[1]['ts']):
            append(root, record)
    return len(restored)


def reconcile(root, manifest):
    # The worker owns this same lock through committing its rows. Never race it.
    root=Path(root).resolve()
    with (root/'.run.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 0
        return _reconcile(root,manifest)
