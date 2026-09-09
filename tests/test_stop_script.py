import contextlib
import io
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class StopScriptTests(unittest.TestCase):
    def test_waits_for_saved_state_before_stopping_only_the_ui(self):
        code=Path('stop-hourglass-bench.sh').read_text().split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
        events=[];snapshots=0;killed=False
        root=Path.cwd()
        def run(args, **kwargs):
            return SimpleNamespace(stdout='' if killed or '4554' in ' '.join(args) else '123\n')
        def output(args, **kwargs):
            return 'python3 launch.py --no-open' if args[0]=='/bin/ps' else 'p123\nn'+str(root)+'\n'
        def urlopen(request, **kwargs):
            nonlocal snapshots
            path=request.full_url.split(':4534')[1];events.append(path)
            if path=='/api/health':data={'app':'Hourglass Bench'}
            elif path=='/api/state':
                snapshots+=1
                data={'jobs':{'pending':[{'id':'queued'}] if snapshots==1 else [],'running':[{'id':'active'}] if snapshots<3 else []}}
            else:data={'ok':True}
            return io.StringIO(json.dumps(data))
        def kill(pid, sig):
            nonlocal killed
            self.assertGreaterEqual(snapshots,3)
            self.assertEqual((pid,sig),(123,signal.SIGINT))
            killed=True
        with patch('sys.argv',['stop']),patch.dict('os.environ',{'JORDI_PORT':'4534','HOURGLASS_PORT':'4534'}),patch('subprocess.run',side_effect=run),patch('subprocess.check_output',side_effect=output),patch('urllib.request.urlopen',side_effect=urlopen),patch('os.kill',side_effect=kill),patch('time.sleep'),contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code,'stop-script','exec'),{})
        self.assertTrue(killed)
        self.assertLess(events.index('/api/cancel'),events.index('/api/stop'))
        self.assertEqual(events.count('/api/stop'),1)


if __name__=='__main__':
    unittest.main()
