#!/usr/bin/env python3
"""Open the local UI without interrupting existing services or runs."""
import argparse,json,os,socket,urllib.request,webbrowser,threading
import web
import score_publisher

def existing_bench(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=30) as r:
            return json.load(r).get('app') =='Hourglass Bench'
    except Exception:return False

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--no-open',action='store_true');args=ap.parse_args()
    explicit='HOURGLASS_PORT' in os.environ
    wanted=int(os.environ.get('HOURGLASS_PORT','8788'))
    ports=[wanted] if explicit else [wanted]+[p for p in range(8790,8811) if p!=wanted]
    for port in ports:
        url=f'http://127.0.0.1:{port}'
        if existing_bench(port):
            print(f'Hourglass Bench is already running: {url}',flush=True)
            if not args.no_open:webbrowser.open(url)
            return
        try:server=web.ThreadingHTTPServer(('127.0.0.1',port),web.H)
        except OSError:
            if explicit:raise SystemExit(f'Port {port} is occupied by another service. Choose HOURGLASS_PORT; existing service left running.')
            continue
        if port!=wanted:print(f'Port {wanted} is occupied; using {port}. Existing services left running.',flush=True)
        web.PORT=port;web.start_worker();publisher_started=score_publisher.start(web.ROOT,port)
        if not publisher_started:print(f'Score publisher port {port+20} is occupied; an existing helper may already be running.',flush=True)
        print(f'Hourglass Bench → {url}',flush=True)
        if not args.no_open:threading.Thread(target=lambda:webbrowser.open(url),daemon=True).start()
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()
        return
    raise SystemExit('No free UI port found. Set HOURGLASS_PORT to a free port.')
if __name__=='__main__':main()
