#!/usr/bin/env python3
"""Open the local UI without interrupting existing services or runs."""
import argparse,json,os,socket,urllib.request,webbrowser,threading
import web
import score_publisher

def existing_bench(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=30) as r:
            info=json.load(r)
            if info.get('workspace_key') and info['workspace_key']!=web.workspace_key():
                raise SystemExit(f'Port {port} belongs to another checkout. Set HOURGLASS_PORT to a free port.')
            return info.get('app') in ('Hourglass','Hourglass Bench')
    except Exception:return False

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--no-open',action='store_true');args=ap.parse_args()
    explicit='HOURGLASS_PORT' in os.environ
    wanted=int(os.environ.get('HOURGLASS_PORT','4534'))
    ports=[wanted]
    for port in ports:
        url=f'http://127.0.0.1:{port}'
        if existing_bench(port):
            print(f'Hourglass is already running: {url}',flush=True)
            if not args.no_open:webbrowser.open(url)
            return
        try:server=web.ThreadingHTTPServer(('127.0.0.1',port),web.H)
        except OSError:
            if explicit:raise SystemExit(f'Port {port} is occupied by another service. Choose HOURGLASS_PORT; existing service left running.')
            continue
        if port!=wanted:print(f'Port {wanted} is occupied; using {port}. Existing services left running.',flush=True)
        web.PORT=port;web.start_worker()
        print(f'Hourglass → {url}',flush=True)
        if not args.no_open:threading.Thread(target=lambda:webbrowser.open(url),daemon=True).start()
        web.serve(server)
        return
    raise SystemExit('No free UI port found. Set HOURGLASS_PORT to a free port.')
if __name__=='__main__':main()
