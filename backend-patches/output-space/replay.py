#!/usr/bin/env python3
"""Replay only recognized output-space patches; no server or settings changes."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

HERE = Path(__file__).resolve().parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def target_path(root, relative):
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError(f"Target escapes source root or is a symlink: {relative}")
    return target

def replace_bytes(path, data, mode):
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.output-space-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def rollback(receipt_path, idle_confirmed):
    if not idle_confirmed:
        raise ValueError('Rollback requires --idle-confirmed; stop or drain the server first.')
    receipt = json.loads(receipt_path.read_text())
    root = Path(receipt['source_root']).resolve()
    plan = []
    for row in receipt['files']:
        target = target_path(root, row['target'])
        backup = target_path(receipt_path.parent.resolve(), row['backup'])
        if digest(target) not in {row['before_sha256'], row['after_sha256']} or digest(backup) != row['before_sha256']:
            raise ValueError(f"Rollback refused: source or backup changed for {row['target']}")
        if digest(target) == row['after_sha256']:
            plan.append((target, backup.read_bytes(), row['mode']))
    for target, data, mode in plan:
        replace_bytes(target, data, mode)
    print(json.dumps({'rolled_back': len(plan), 'source_root': str(root), 'restart_required': True}))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['vllm', 'omlx'])
    parser.add_argument('--source-root', type=Path, help='The vllm/ or omlx/ Python package directory')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Default: verify and stage without writing sources')
    modes.add_argument('--apply', action='store_true')
    modes.add_argument('--rollback', type=Path, metavar='RECEIPT')
    parser.add_argument('--backup-dir', type=Path, help='Private parent directory for timestamped backups')
    parser.add_argument('--idle-confirmed', action='store_true', help='Operator confirms the service is idle/stopped or this is an offline image build')
    args = parser.parse_args()
    if args.rollback:
        return rollback(args.rollback.resolve(), args.idle_confirmed)
    if not args.backend or not args.source_root:
        parser.error('--backend and --source-root are required')
    if args.apply and (not args.backup_dir or not args.idle_confirmed):
        parser.error('--apply requires --backup-dir and --idle-confirmed')
    root = args.source_root.resolve(strict=True)
    manifest = json.loads((HERE / 'manifest.json').read_text())
    plan, states = [], []
    with tempfile.TemporaryDirectory(prefix='hourglass-output-space-') as tmp:
        scratch = Path(tmp).resolve()
        for row in manifest['files']:
            if row['backend'] != args.backend:
                continue
            target = target_path(root, row['target'])
            if not target.exists() and row.get('optional_if_absent'):
                states.append({'target': row['target'], 'state': 'optional contract absent; inspect other custom validators'})
                continue
            if not target.is_file():
                raise ValueError(f"Missing required source: {row['target']}; inspect the installed runtime, do not invent the file.")
            current = digest(target)
            if current == row['after_sha256']:
                states.append({'target': row['target'], 'state': 'already applied'})
                continue
            if current != row['before_sha256']:
                raise ValueError(f"Unknown source for {row['target']}; review/rebase this patch instead of overwriting it.")
            staged = target_path(scratch, row['target'])
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, staged)
            result = subprocess.run(['patch', '-p1', '--batch', '--forward'], cwd=scratch,
                                    input=(HERE / row['patch']).read_bytes(), capture_output=True)
            if result.returncode or digest(staged) != row['after_sha256']:
                raise ValueError(f"Patch did not produce the reviewed source: {row['target']}")
            plan.append((row, target, staged.read_bytes(), target.stat().st_mode))
            states.append({'target': row['target'], 'state': 'ready'})
        if not args.apply or not plan:
            print(json.dumps({'mode': 'check' if not args.apply else 'already applied', 'files': states}, indent=2))
            return
        # Recheck every source before any source write, then preserve all originals.
        for row, target, _, _ in plan:
            if digest(target) != row['before_sha256']:
                raise ValueError(f"Source changed during preflight: {row['target']}")
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = args.backup_dir.resolve() / f'output-space-{args.backend}-{stamp}-{uuid.uuid4().hex[:8]}'
        backup.mkdir(parents=True, mode=0o700)
        receipt = {'schema_version': 1, 'backend': args.backend, 'source_root': str(root), 'files': [], 'status': 'prepared'}
        for row, target, _, mode in plan:
            saved = backup / 'original' / row['target']
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
            receipt['files'].append({**row, 'backup': str(saved.relative_to(backup)), 'mode': mode})
        receipt_path = backup / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        try:
            for _, target, data, mode in plan:
                replace_bytes(target, data, mode)
        except BaseException:
            # Restore this operation's recognized originals on an interrupted apply.
            for row, target, _, mode in plan:
                replace_bytes(target, (backup / 'original' / row['target']).read_bytes(), mode)
            receipt['status'] = 'apply failed; originals restored'
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            raise
        receipt['status'] = 'applied; live validation pending'
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'applied': len(plan), 'receipt': str(receipt_path), 'restart_required': True, 'live_validation': 'pending'}, indent=2))

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
