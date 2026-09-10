"""Real macOS sandbox proof, with no inference or production mutations."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hourglass

root=Path(__file__).resolve().parents[1]
(root/'backups').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='native-bank-',dir=root/'backups') as temp, tempfile.TemporaryDirectory(prefix='hourglass-private-export-',dir='/private/tmp') as external:
    base=Path(temp);work=base/'workspace';work.mkdir()
    canary=base/'answer-key';canary.write_text('PRIVATE_CANARY')
    export=Path(external)/'trace.json';export.write_text('PRIVATE_CANARY')
    (work/'link').symlink_to(canary)
    targets=[canary,work/'link',export]
    targets += [p/'tasks'/next((p/'tasks').glob('*/task.json')).parent.name/'task.json' for p in hourglass.benchmark_worktrees() if any((p/'tasks').glob('*/task.json'))]
    client=Path.home()/'.codex/config.toml'
    if client.exists():targets.append(client)
    script='import pathlib,sys; pathlib.Path(sys.argv[1]).read_bytes()'
    for sandboxed in (True,False):
        profile=hourglass.sandbox_profile(work,sandboxed)
        for target in targets:
            result=subprocess.run(['/usr/bin/sandbox-exec','-p',profile,sys.executable,'-c',script,str(target)],cwd=work,capture_output=True)
            assert result.returncode!=0, 'Private read allowed: '+str(target)
            assert b'Operation not permitted' in result.stderr or b'Permission denied' in result.stderr,result.stderr
        result=subprocess.run(['/usr/bin/sandbox-exec','-p',profile,sys.executable,'-c','from pathlib import Path;p=Path("ordinary.txt");p.write_text("OK");assert p.read_text()=="OK"'],cwd=work,capture_output=True)
        assert result.returncode==0,result.stderr
        print(json.dumps({'sandboxed':sandboxed,'private_reads_denied':len(targets),'workspace_read_write':'passed'}))
