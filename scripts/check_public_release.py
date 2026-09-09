#!/usr/bin/env python3
"""Reject private runtime paths and obvious credentials in tracked first-party files."""
from pathlib import Path
import re
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
private={'tasks','incoming','banks','question-banks','results','evaluations','sandboxes','logs','backups','hardware-records'}
blocked={'models.json','provenance.json','calibration.json','leaderboard.md','frontier.md','attempt-annotations.json','timing-corrections.json','hardware-profiles.json','.machine-id','docs/MAINTAINER-HANDOFF.md'}
errors=[]
for name in filter(None,files):
    p=Path(name)
    if p.parts[0] in private or name in blocked or name.startswith('ui/question-assets/') or p.name.startswith('.env'):
        errors.append('Private path tracked: '+name)
    if name.startswith('vendor/'):
        continue
    data=(root/name).read_bytes()
    if re.search(rb'(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{32,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)',data):
        errors.append('Possible credential: '+name)
    if re.search(b'/' + b'Users/' + rb'[^/\s]+/',data):
        errors.append('Personal absolute path: '+name)
if errors:
    print('\n'.join(errors));sys.exit(1)
print('Public release check passed: no tracked private-bank/runtime paths or obvious first-party credentials.')
