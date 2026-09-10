"""One-hour run stop and completion chime. Never touches a model server."""
import argparse
import json
import pathlib
import subprocess
import time
import urllib.request

WINDOW_S = 3600


def remaining(job, now=None):
    now = time.time() if now is None else now
    if job.get('progress') is not None:
        elapsed = job['progress']['elapsed_s']
    else:
        elapsed = job.get('elapsed_s', 0)
        if job.get('active_started') is not None:
            elapsed += max(0, now - job['active_started'])
    return max(0, WINDOW_S - elapsed)


def chime():
    sound = pathlib.Path('/System/Library/Sounds/Glass.aiff')
    if sound.exists():
        try:
            subprocess.Popen(['/usr/bin/afplay', str(sound)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # Audio availability must never break result persistence or the worker.


def watch_job(job, condition, stop):
    with condition:
        while job.get('state') == 'running':
            deadline = job.get('_hour_deadline_monotonic')
            wait = max(0, deadline-time.monotonic()) if deadline is not None else remaining(job)
            if wait <= 0:
                stop({'job':job['id'], 'reason':'hour_limit'})
                return
            condition.wait(timeout=wait)


def watch_existing(base, jid):
    """Bridge for a run already executing in a server loaded before this feature."""
    requested = False
    print(f'Watching {jid}: stop after 3600 active seconds, then chime.', flush=True)
    while True:
        try:
            with urllib.request.urlopen(base + '/api/state', timeout=10) as response:
                state = json.load(response)
            job = next((j for group in state['jobs'].values() for j in group if j['id'] == jid), None)
            if job is None:
                raise RuntimeError('Target run no longer appears in history.')
            if job['state'] not in ('running', 'pending'):
                if requested or job['state'] == 'completed':
                    chime()
                print(f"Run ended: {job['state']}; hourly stop requested={requested}.", flush=True)
                return
            deadline = job.get('_hour_deadline_monotonic')
            wait = max(0, deadline-time.monotonic()) if deadline is not None else remaining(job)
            if job['state'] == 'running' and wait <= 0 and not requested:
                req = urllib.request.Request(base+'/api/stop', data=json.dumps({'job':jid,'reason':'hour_limit'}).encode(), headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    json.load(response)
                requested = True
                print('One-hour deadline reached; stop requested.', flush=True)
            time.sleep(min(2, max(0.1, wait)) if not requested else 1)
        except (OSError, ValueError) as exc:
            print(f'Deadline watcher connection error: {exc}; retrying.', flush=True)
            time.sleep(2)


def watch_server(base):
    """Bridge all runs until the server is restarted with its built-in deadline."""
    seen, requested, finished = set(), set(), set()
    print('One-hour stop and chime armed for current and subsequent runs.', flush=True)
    while True:
        try:
            with urllib.request.urlopen(base + '/api/state', timeout=10) as response:
                state = json.load(response)
            if state.get('score_policy', {}).get('version') == 'hour-v1':
                print('Built-in deadline active; bridge exiting.', flush=True)
                return
            for job in [j for group in state['jobs'].values() for j in group]:
                jid = job['id']
                if job['state'] == 'running':
                    seen.add(jid)
                    if remaining(job) <= 0 and jid not in requested:
                        req = urllib.request.Request(base+'/api/stop', data=json.dumps({'job':jid,'reason':'hour_limit'}).encode(), headers={'Content-Type':'application/json'})
                        with urllib.request.urlopen(req, timeout=10) as response:
                            json.load(response)
                        requested.add(jid)
                        print(f'One-hour stop requested: {jid}', flush=True)
                elif jid in seen and job['state'] != 'pending' and jid not in finished:
                    if jid in requested or job['state'] == 'completed':
                        chime()
                    finished.add(jid)
                    print(f"Run ended: {jid} ({job['state']}).", flush=True)
            time.sleep(1)
        except (OSError, ValueError) as exc:
            print(f'Deadline bridge connection error: {exc}; retrying.', flush=True)
            time.sleep(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--job')
    parser.add_argument('--base-url', default='http://127.0.0.1:8788')
    args = parser.parse_args()
    if args.job:
        watch_existing(args.base_url, args.job)
    else:
        watch_server(args.base_url)
