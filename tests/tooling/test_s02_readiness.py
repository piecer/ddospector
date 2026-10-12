"""Kernel-listener and real strictPort controls, not application acceptance."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("collision", [False, True])
def test_real_owned_listener_or_vite_collision(tmp_path, collision):
    script = r'''
import json,os,socket,sys
from pathlib import Path
from tools import s02_web_probe as probe
out=Path(sys.argv[1]); collision=sys.argv[2]=='True'
env={"PATH":"/usr/bin:/bin","HOME":str(out),"TMPDIR":str(out),"PYTHONDONTWRITEBYTECODE":"1"}
owner=probe.NativeChildren(out,env)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));sock.listen(5)
    port=sock.getsockname()[1]; url=f'http://127.0.0.1:{port}'
    assert port not in (5173,5180)
    try:
        if collision:
            # This invocation owns the sentinel; no accepting thread exists.
            argv=['/usr/bin/node',str(probe.ROOT/'web/node_modules/vite/bin/vite.js'),
                  str(probe.ROOT/'web'),'--host','127.0.0.1','--port',str(port),'--strictPort']
            with socket.socket() as api:
                api.bind(('127.0.0.1',0))
                proxy=f'http://127.0.0.1:{api.getsockname()[1]}'
                p=owner.launch('server',argv,{'VITE_API_PROXY_TARGET':proxy})
            requested=[]
            def forbidden(*args,**kwargs):
                requested.append(args[0]);raise AssertionError('HTTP before owned listener')
            probe.urllib.request.urlopen=forbidden
            try:
                probe.ready(url,p,start=owner.known[p.pid]['start_ticks'],
                    announcement=(out/'server.stdout',url))
            except RuntimeError as error:
                assert 'exited' in str(error)
            else:raise AssertionError('collision accepted')
            assert requested==[]
            assert 'already in use' in (out/'server.stderr').read_text()
        else:
            code="""
import http.server,socket,sys
server=http.server.HTTPServer(('127.0.0.1',0),http.server.BaseHTTPRequestHandler,bind_and_activate=False)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'owned')
server.socket.close();server.socket=socket.socket(fileno=int(sys.argv[1]));server.RequestHandlerClass=Handler
print(sys.argv[2],flush=True);server.serve_forever()
"""
            p=owner.launch('server',[sys.executable,'-c',code,str(sock.fileno()),url],pass_fds=(sock.fileno(),))
            probe.ready(url,p,start=owner.known[p.pid]['start_ticks'],
                announcement=(out/'server.stdout',url),expected_inode=os.fstat(sock.fileno()).st_ino,
                receipt=out/'binding.json')
            assert json.loads((out/'binding.json').read_text())['proven_before_http']
    finally:owner.retire_all()
assert owner.clean
'''
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    with subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-c", script, str(tmp_path), str(collision)],
        cwd=ROOT,
        env=env,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as p:
        stdout, stderr = p.communicate(timeout=15)
    assert p.returncode == 0, stdout + stderr
