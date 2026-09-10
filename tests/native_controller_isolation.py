"""Relaxed filesystem mode must not retrieve private state through the local UI."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import HTTPServer,BaseHTTPRequestHandler
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hourglass
class H(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'FIXTURE')
a=HTTPServer(('127.0.0.1',0),H);b=HTTPServer(('127.0.0.1',0),H)
for server in (a,b):threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'HOURGLASS_PORT':str(a.server_port)}):
        for sandboxed in (True,False):
            for server in (a,b):
                result=subprocess.run(['/usr/bin/sandbox-exec','-p',hourglass.sandbox_profile(d,sandboxed),'/usr/bin/curl','--silent','--show-error','--max-time','2',f'http://127.0.0.1:{server.server_port}/'],capture_output=True)
                if server is a or sandboxed:assert result.returncode!=0 and b'FIXTURE' not in result.stdout,(sandboxed,result)
                else:assert result.returncode==0 and result.stdout==b'FIXTURE',result
            print('sandboxed='+str(sandboxed)+': controller denied; ordinary network policy preserved')
finally:
    a.shutdown();b.shutdown()
