"""Synthetic tests for replay preflight, idempotence and guarded rollback."""
from pathlib import Path
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ReplayChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.bundle, self.source, self.backups = [base / n for n in ('bundle', 'source', 'backups')]
        self.bundle.mkdir(); self.source.mkdir()
        shutil.copy2(ROOT / 'backend-patches/output-space/replay.py', self.bundle / 'replay.py')
        self.before = b"message = 'before'\n"
        self.after = b"message = 'after'\n"
        rows = []
        for name in ('one.py', 'two.py'):
            (self.source / name).write_bytes(self.before)
            diff = ''.join(difflib.unified_diff(self.before.decode().splitlines(True), self.after.decode().splitlines(True), fromfile='a/'+name, tofile='b/'+name))
            (self.bundle / (name+'.patch')).write_text(diff)
            rows.append({'backend':'vllm','target':name,'patch':name+'.patch','before_sha256':hashlib.sha256(self.before).hexdigest(),'after_sha256':hashlib.sha256(self.after).hexdigest()})
        (self.bundle / 'manifest.json').write_text(json.dumps({'files':rows}))

    def run_helper(self, *args, success=True):
        result = subprocess.run([sys.executable, str(self.bundle/'replay.py'), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return json.loads(result.stdout) if success else result

    def apply(self):
        return self.run_helper('--backend','vllm','--source-root',str(self.source),'--apply','--idle-confirmed','--backup-dir',str(self.backups))

    def test_check_apply_noop_and_rollback(self):
        self.run_helper('--backend','vllm','--source-root',str(self.source),'--check')
        self.assertEqual((self.source/'one.py').read_bytes(), self.before)
        applied = self.apply()
        self.assertEqual((self.source/'one.py').read_bytes(), self.after)
        self.assertEqual(self.apply()['mode'], 'already applied')
        self.run_helper('--rollback',applied['receipt'],'--idle-confirmed')
        for name in ('one.py','two.py'):
            self.assertEqual((self.source/name).read_bytes(), self.before)

    def test_unknown_later_source_prevents_all_writes(self):
        (self.source/'two.py').write_text('unrelated change\n')
        self.run_helper('--backend','vllm','--source-root',str(self.source),'--apply','--idle-confirmed','--backup-dir',str(self.backups),success=False)
        self.assertEqual((self.source/'one.py').read_bytes(), self.before)
        self.assertFalse(self.backups.exists())

    def test_rollback_refuses_changed_source_or_backup(self):
        applied = self.apply(); receipt = Path(applied['receipt'])
        (self.source/'two.py').write_text('subsequent work\n')
        self.run_helper('--rollback',str(receipt),'--idle-confirmed',success=False)
        self.assertEqual((self.source/'one.py').read_bytes(), self.after)
        (self.source/'two.py').write_bytes(self.after)
        (receipt.parent/'original/one.py').write_text('corrupt backup\n')
        self.run_helper('--rollback',str(receipt),'--idle-confirmed',success=False)
        self.assertEqual((self.source/'two.py').read_bytes(), self.after)

    def test_rollback_handles_partly_restored_known_files(self):
        applied = self.apply()
        (self.source/'one.py').write_bytes(self.before)
        self.run_helper('--rollback',applied['receipt'],'--idle-confirmed')
        self.assertEqual((self.source/'two.py').read_bytes(), self.before)

    def test_apply_requires_explicit_idle_assertion(self):
        self.run_helper('--backend','vllm','--source-root',str(self.source),'--apply','--backup-dir',str(self.backups),success=False)
        self.assertEqual((self.source/'one.py').read_bytes(), self.before)

if __name__ == '__main__':
    unittest.main()
