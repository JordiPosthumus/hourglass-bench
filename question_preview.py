"""Public question views reconstructed from a run's frozen presentation."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import option_layout


def public_fields(task):
    files = task.get('files') or {}
    allowed = task.get('public_preview_files') or []
    if not isinstance(allowed, list):
        allowed = []
    return {'id': task['id'], 'title': task.get('title', task['id']), 'prompt': task.get('prompt', ''),
            'options': task.get('options') or task.get('choices') or [], 'files': list(files),
            'public_files': {name: files[name] for name in allowed if isinstance(name, str) and isinstance(files.get(name), str)},
            'vision': task.get('kind') == 'chart-vqa' or bool(task.get('image') or task.get('assets'))}


def image_names(task):
    names = [task['image']] if isinstance(task.get('image'), str) else []
    names += [name for name in task.get('assets', []) if isinstance(name, str)]
    return list(dict.fromkeys(name for name in names if Path(name).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif')))


def images(task, job=None):
    return ['/api/task-asset?'+urlencode({'id': task['id'], 'file': name, **({'job': job} if job else {})}) for name in image_names(task)]


def task_directory(root, manifest, tid):
    root = Path(root).resolve()
    if not any(item['task'] == tid for item in manifest.get('expected', [])):
        raise ValueError('Question is outside this run.')
    directory = (root / manifest.get('task_snapshot', 'tasks') / tid).resolve()
    if not directory.is_relative_to(root/'evaluations') and directory != root/'tasks'/tid:
        raise ValueError('Invalid frozen question path.')
    return directory


def image_file(root, tid, name, manifest=None):
    root = Path(root).resolve()
    directory = task_directory(root, manifest, tid) if manifest else (root/'tasks'/tid).resolve()
    if not manifest and not directory.is_relative_to(root/'tasks'):
        raise ValueError('Invalid question path.')
    task = json.loads((directory/'task.json').read_text())
    path = (directory/name).resolve()
    if name not in image_names(task) or not path.is_relative_to(directory) or not path.is_file():
        raise ValueError('Only declared question images can be viewed.')
    return path


def for_run(root, manifest, tid, repeat):
    root = Path(root).resolve()
    expected = next((item for item in manifest.get('expected', []) if item['task'] == tid), None)
    limit=manifest.get('round_number',1) if manifest.get('round_policy') else (expected or {}).get('repeat',1)
    if expected is None or type(repeat) is not int or not 1 <= repeat <= limit:
        raise ValueError('Question or repeat is outside this run.')
    directory = task_directory(root, manifest, tid)
    raw = (directory/'task.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()[:16] != expected['task_sha']:
        raise ValueError('Frozen question changed; the exact run preview is unavailable.')
    task = json.loads(raw)
    policy = manifest.get('option_layout_policy')
    if policy == option_layout.POLICY:
        task, _ = option_layout.prepare(task, repeat, expected['task_bundle_sha'], manifest['presentation_seed'])
    elif policy:
        raise ValueError('This option presentation policy is not supported by the viewer.')
    result = public_fields(task)
    if task.get('shuffle') and task.get('options'):
        key = hashlib.sha256(task['id'].encode()).hexdigest()
        result['options'] = sorted(task['options'], key=lambda option: hashlib.sha256(f"{key}:{option['id']}".encode()).hexdigest())
    result['presentation'] = {'job': manifest['id'], 'repeat': repeat, 'policy': policy or 'legacy', 'exact': True}
    result['images'] = images(task, manifest['id'])
    return result


def active_repeat(root, manifest, tid):
    if manifest.get('round_policy'):return manifest.get('round_number',1)
    try:
        checkpoint = json.loads((Path(root)/'logs'/f"attempt-{manifest['id']}.json").read_text())
    except (OSError, ValueError):
        checkpoint = {}
    if checkpoint.get('task') == tid and isinstance(checkpoint.get('run'), int):
        return checkpoint['run']
    item = next((item for item in manifest.get('expected', []) if item['task'] == tid), {})
    if item.get('repeat') == 1:
        return 1
    raise ValueError('The active repeat is not available yet.')
