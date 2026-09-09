"""Endpoint hardware profiles for future evaluations; never edits model settings."""
import copy
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import uuid
from urllib.parse import urlparse


def load(root):
    path = root / 'hardware-profiles.json'
    if not path.exists():
        return {}
    profiles = json.loads(path.read_text())
    if not isinstance(profiles, dict) or any(not isinstance(p, dict) for p in profiles.values()):
        raise ValueError('Hardware profiles must be a mapping of endpoints to machines.')
    return profiles


def revision(profiles):
    return hashlib.sha256(json.dumps(profiles, sort_keys=True).encode()).hexdigest()


def local_url(url):
    return urlparse(url).hostname in ('localhost', '127.0.0.1', '::1')


def fields(profile):
    return {k: copy.deepcopy(profile[k]) for k in ('machine_id', 'label', 'chip', 'memory_bytes', 'cpu_cores', 'gpu') if k in profile}


def snapshot(root, models):
    try:
        profiles = load(root)
    except (ValueError, OSError) as exc:
        return {'error': str(exc), 'endpoints': [], 'machines': [], 'revision': None}
    machines = {}
    for p in profiles.values():
        if p.get('machine_id'):
            machines.setdefault(str(p['machine_id']), fields(p))
    return {
        'revision': revision(profiles), 'machines': list(machines.values()),
        'endpoints': [
            {'base_url': url, 'models': [m['name'] for m in models if m.get('base_url') == url],
             'local_available': local_url(url), 'profile': fields(profiles[url]) if url in profiles else None}
            for url in dict.fromkeys(m.get('base_url') for m in models if isinstance(m.get('base_url'), str))
        ],
    }


def validate_fields(body):
    result = {}
    for key in ('label', 'chip', 'gpu_model'):
        value = body.get(key, '')
        if not isinstance(value, str) or len(value) > 160 or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid ' + key + '.')
        result[key] = value.strip()
    if not result['label']:
        raise ValueError('Enter a machine name, such as Spark 2.')
    for source, target, scale in [('memory_gib', 'memory_bytes', 1024**3), ('cpu_cores', 'cpu_cores', 1)]:
        value = body.get(source)
        if value in ('', None):
            continue
        if isinstance(value, bool):
            raise ValueError('Invalid ' + source + '.')
        try:
            number = float(value)
        except (ValueError, TypeError):
            raise ValueError('Invalid ' + source + '.') from None
        if not math.isfinite(number) or number <= 0 or number > 1000000 or (source == 'cpu_cores' and not number.is_integer()):
            raise ValueError('Enter a positive ' + source + (' integer.' if source == 'cpu_cores' else '.'))
        result[target] = round(number * scale)
    return result


def save(root, models, body):
    """Caller serializes saves with evaluation creation using its controller lock."""
    profiles = load(root)
    if body.get('revision') != revision(profiles):
        raise ValueError('Hardware settings changed elsewhere. Discard edits to reload before saving.')
    endpoint = body.get('base_url')
    if not isinstance(endpoint, str) or endpoint not in [m.get('base_url') for m in models]:
        raise ValueError('Select a saved endpoint. Save endpoint edits first.')
    updated = copy.deepcopy(profiles)
    choice = body.get('machine')
    if choice == 'local':
        if not local_url(endpoint):
            raise ValueError('This computer can only be selected for a local endpoint.')
        updated.pop(endpoint, None)
    else:
        values = validate_fields(body)
        machines = {str(p['machine_id']): p for p in profiles.values() if p.get('machine_id')}
        if choice == 'new':
            identity = uuid.uuid4().hex
        elif isinstance(choice, str) and choice.startswith('machine:') and choice[8:] in machines:
            identity = choice[8:]
        else:
            raise ValueError('Choose an existing machine or add another machine.')
        # Keep private extension fields and detailed GPU metadata when editing a profile.
        profile = copy.deepcopy(machines.get(identity, {}))
        if profiles.get(endpoint, {}).get('machine_id') == identity:
            profile = copy.deepcopy(profiles[endpoint])
        profile.update(machine_id=identity, label=values['label'], chip=values['chip'])
        for key in ('memory_bytes', 'cpu_cores'):
            if key in values:
                profile[key] = values[key]
            else:
                profile.pop(key, None)
        old_gpu = profile.get('gpu', [])
        if values['gpu_model']:
            if isinstance(old_gpu, list) and old_gpu and isinstance(old_gpu[0], dict):
                profile['gpu'] = [{**old_gpu[0], 'model': values['gpu_model']}, *old_gpu[1:]]
            else:
                profile['gpu'] = [{'model': values['gpu_model']}]
        else:
            profile.pop('gpu', None)
        # A physical machine has one set of details across its endpoints.
        for url, existing in updated.items():
            if existing.get('machine_id') == identity:
                merged = copy.deepcopy(existing)
                for key in ('label', 'chip', 'memory_bytes', 'cpu_cores', 'gpu'):
                    if key in profile:
                        merged[key] = copy.deepcopy(profile[key])
                    else:
                        merged.pop(key, None)
                updated[url] = merged
        updated[endpoint] = profile
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = root / 'backups' / ('endpoint-hardware-' + stamp)
    backup.mkdir(parents=True)
    target = root / 'hardware-profiles.json'
    if target.exists():
        shutil.copy2(target, backup / target.name)
    else:
        (backup / 'previously-absent.txt').write_text('hardware-profiles.json did not exist.\n')
    (backup / 'DELTA.txt').write_text('Save inference-machine details for future evaluations. Model settings and existing evaluations are unchanged.\n')
    tmp = root / ('hardware-profiles.tmp-' + uuid.uuid4().hex)
    try:
        with tmp.open('x') as f:
            os.chmod(tmp, 0o600)
            json.dump(updated, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return {'ok': True, 'backup': str(backup.relative_to(root)), 'hardware': snapshot(root, models)}
