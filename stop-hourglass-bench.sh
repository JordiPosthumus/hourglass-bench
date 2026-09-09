#!/usr/bin/env bash
# Stop this checkout's bench cleanly; model servers remain running.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 - "$@" <<'PY'
import json, os, pathlib, signal, subprocess, sys, time, urllib.error, urllib.request

root = pathlib.Path.cwd()
port = int(os.environ.get('HOURGLASS_PORT', '4534'))
base = f'http://127.0.0.1:{port}'

def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

def listener(target_port, script):
    result = subprocess.run(['/usr/sbin/lsof', '-nP', '-t', f'-iTCP@127.0.0.1:{target_port}', '-sTCP:LISTEN'], capture_output=True, text=True)
    pids = set(result.stdout.split())
    if not pids:
        return None
    if len(pids) != 1:
        raise RuntimeError(f'Multiple listeners on port {target_port}; leaving them untouched.')
    pid = int(pids.pop())
    command = subprocess.check_output(['/bin/ps', '-p', str(pid), '-o', 'command='], text=True).strip()
    cwd = subprocess.check_output(['/usr/sbin/lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'], text=True).splitlines()
    if 'n' + str(root) not in cwd or not any(pathlib.Path(word).name == script for word in command.split()):
        raise RuntimeError(f'Port {target_port} does not belong to this checkout’s {script}; leaving it untouched.')
    return pid

try:
    if len(sys.argv) > 1:
        if sys.argv[1:] in (['--help'], ['-h']):
            print('Usage: ./stop-hourglass-bench.sh\nUses HOURGLASS_PORT (default 4534). Cancels queued tests, stops the active test, waits for saved results, then closes the UI and its report helper. Model servers are left running.')
            sys.exit(0)
        raise RuntimeError('Unknown arguments. Use --help for usage.')
    pid = listener(port, 'launch.py')
    if pid is None:
        print('The bench UI is already stopped.')
    else:
        if request('/api/health').get('app') not in ('Hourglass Bench', 'JordiBench'):
            raise RuntimeError('The listener did not identify itself as Hourglass Bench.')
        deadline = time.monotonic() + 120
        requested = set()
        print('Stopping tests and waiting for results to be saved…', flush=True)
        while True:
            jobs = request('/api/state')['jobs']
            # Cancel waiting work before stopping the active run.
            for job in jobs['pending']:
                try:
                    request('/api/cancel', {'job': job['id']})
                except urllib.error.HTTPError as error:
                    if error.code != 400:
                        raise
            for job in jobs['running']:
                if job['id'] not in requested:
                    try:
                        request('/api/stop', {'job': job['id']})
                        requested.add(job['id'])
                    except urllib.error.HTTPError as error:
                        if error.code != 400:
                            raise
            if not jobs['running'] and not jobs['pending']:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Shutdown is still pending. The UI was left running to protect the run; check its log.')
            time.sleep(0.5)
        if listener(port, 'launch.py') != pid:
            raise RuntimeError('The UI process changed during shutdown; leaving it untouched.')
        os.kill(pid, signal.SIGINT)
        for _ in range(40):
            if listener(port, 'launch.py') is None:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError('The UI has not exited yet; no forced termination was used.')
        print('Bench stopped. Saved results are retained.')
    helper = listener(port + 20, 'score_publisher.py')
    if helper is not None:
        os.kill(helper, signal.SIGINT)
        print('Report viewer stopped.')
except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
    print(f'Could not finish stopping the bench: {error}', file=sys.stderr)
    sys.exit(1)
PY
