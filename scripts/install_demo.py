#!/usr/bin/env python3
"""Install the public setup demo without touching an existing local task."""
from pathlib import Path
import shutil

root=Path(__file__).resolve().parents[1]
destination=root/'tasks/hello-world'
if destination.exists():
    raise SystemExit('tasks/hello-world already exists; no files changed.')
destination.parent.mkdir(exist_ok=True)
shutil.copytree(root/'examples/hello-world',destination)
print('Installed hello-world. Refresh the UI to select this setup demo.')
