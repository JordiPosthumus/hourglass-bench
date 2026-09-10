"""Harness-owned runtime files, separate from every model task workspace."""
import hashlib
import json
import os
from pathlib import Path
import shutil

POLICY = 'diagnostics-outside-workspace-v1'
DIRECTORY = 'runtime-diagnostics'
FILES = ('partial-pi-trace.jsonl', 'interrupted-pi-trace.json', 'stderr.txt', 'integrity.json')


def directory(root, workdir, create=False):
    root, workdir = Path(root).resolve(), Path(workdir).resolve()
    path = root / DIRECTORY / hashlib.sha256(str(workdir).encode()).hexdigest()
    if path.is_relative_to(workdir) or workdir.is_relative_to(path):
        raise ValueError('Diagnostic storage must be separate from the task workspace.')
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        identity = path / 'identity.json'
        if not identity.exists():
            identity.write_text(json.dumps({'policy': POLICY, 'workspace': str(workdir)}) + '\n')
    return path


def source(root, workdir, filename, policy=None):
    """Read historical workspace traces only for runs predating separation."""
    if filename not in FILES:
        raise ValueError('Unknown diagnostic file.')
    private = directory(root, workdir)
    if policy == POLICY or (private / 'identity.json').exists():
        return private / filename
    legacy = '.hourglass-integrity.json' if filename == 'integrity.json' else filename
    if filename == 'integrity.json' and not (Path(workdir)/legacy).exists() and (Path(workdir)/'.hourglass-integrity.json').exists():
        legacy = '.hourglass-integrity.json'
    return Path(workdir) / legacy


def descriptor(root, workdir):
    return {'diagnostic_isolation': POLICY,
            'diagnostics_dir': str(directory(root, workdir).relative_to(Path(root).resolve()))}


def publish(root, workdir, artifact):
    """Keep the existing trace.json route plus complete raw crash evidence."""
    private, artifact = directory(root, workdir), Path(artifact)
    if not (private / 'identity.json').exists():
        return
    files=[]
    for name in FILES:
        src = private / name
        if src.is_file():
            shutil.copy2(src, artifact / name)
            files.append(name)
    (artifact / 'diagnostics.json').write_text(json.dumps({**descriptor(root, workdir),
        'files':files, 'session_directory':str((private / 'agent' / 'sessions').relative_to(Path(root).resolve()))}, indent=2)+'\n')


def protected_profile(profile, roots, workdir, extra_files=()):
    """The OS applies these denials to bash and the file-tool worker equally."""
    cwd=Path(workdir).resolve()
    def quoted(path):return str(Path(path).resolve()).replace('\\','\\\\').replace('"','\\"')
    lines=[profile]
    for root in dict.fromkeys(Path(r).resolve() for r in roots):
        for name in (DIRECTORY, 'logs', 'results', 'evaluations', 'tasks', 'backups', '.git'):
            private=root/name
            if private == cwd:
                raise ValueError('Task workspace overlaps harness-owned runtime storage.')
            lines.append(f'(deny file-read* file-write* (subpath "{quoted(private)}"))')
    for root in dict.fromkeys(Path(r).resolve() for r in roots):
        lines.append(f'(deny file-read* file-write* (subpath "{quoted(root)}"))')
    lines.append(f'(allow file-read* file-write* (subpath "{quoted(cwd)}"))')
    for parent in cwd.parents:
        lines.append(f'(allow file-read-metadata (literal "{quoted(parent)}"))')
    for name in ('.codex', '.agents', '.claude', '.pi', '.hermes', '.openclaw', '.lmstudio/server-logs', '.lmstudio/conversations', '.ollama/logs'):
        lines.append(f'(deny file-read* file-write* (subpath "{quoted(Path.home()/name)}"))')
    # Private bank backups can live outside the checkout. Their owner-saved
    # locations receive the same protection in both tool execution modes.
    for root in dict.fromkeys(Path(r).resolve() for r in roots):
        registry=root/'private-data-paths.json'
        if not registry.is_file():continue
        data=json.loads(registry.read_text())
        paths=data.get('paths') if isinstance(data,dict) else None
        if not isinstance(paths,list) or any(not isinstance(p,str) or not Path(p).is_absolute() for p in paths):
            raise ValueError('Private data locations must be a list of absolute paths.')
        for path in paths:
            private=Path(path).resolve()
            if private==cwd or cwd.is_relative_to(private):
                raise ValueError('Task workspace overlaps registered private data.')
            lines.append(f'(deny file-read* file-write* (subpath "{quoted(private)}"))')
    # Known historical diagnostic exports may be outside the repository.
    for base in (Path('/private/tmp'), Path(os.environ.get('TMPDIR','/private/tmp'))):
        for private in base.glob('hourglass-*'):
            if private.resolve()==cwd or cwd.is_relative_to(private.resolve()):continue
            lines.append(f'(deny file-read* file-write* (subpath "{quoted(private)}"))')
    for filename in extra_files:
        if not filename:continue
        private=Path(filename).resolve()
        if private == cwd or private.is_relative_to(cwd):
            raise ValueError('Harness checkpoint files must be outside the task workspace.')
        for target in (private, private.with_name(private.name+'.tmp')):
            lines.append(f'(deny file-read* file-write* (literal "{quoted(target)}"))')
    return '\n'.join(lines)
