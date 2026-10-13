"""Fresh I2 real HTTP fixture; all children/resources belong to this invocation."""
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import s02_harness as h  # noqa: E402


def source_check(data):
    assert data['root'] == str(ROOT) and sys.prefix == data['prefix']
    assert sys.executable == data['python']
    assert h.identity_of(data['owner']['pid']) == data['owner']
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
               for p, sha in data['source'].items())


@contextmanager
def child(data, label, argv, *, env=None, pass_fds=()):
    output = Path(data['output'])
    environment = h.child_environment(output)
    environment['TMPDIR'] = '/home/piecer/.hermes/cache/scratch/i3w-lecrmpg5'
    if env:
        environment.update(env)
    p = subprocess.Popen(argv, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         pass_fds=pass_fds, start_new_session=True)
    ident = h.identity_of(p.pid)
    (output / (label + '-started.json')).write_text(json.dumps({
        'identity': ident, 'argv': argv, 'cwd': str(ROOT), 'environment': environment,
    }, indent=2) + '\n')
    try:
        yield p
    finally:
        rescued = False
        if p.poll() is None:
            assert h.identity_of(p.pid) == ident
            p.terminate()
        try:
            stdout, stderr = p.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            rescued = True
            assert h.identity_of(p.pid) == ident
            p.kill()
            stdout, stderr = p.communicate(timeout=2)
        (output / (label + '-stdout.log')).write_bytes(stdout)
        (output / (label + '-stderr.log')).write_bytes(stderr)
        receipt = {'identity': ident, 'actual_exit': p.returncode,
                   'rescued': rescued, 'reaped': p.returncode is not None,
                   'pipes_closed': p.stdout.closed and p.stderr.closed,
                   'absent': not Path(f'/proc/{p.pid}').exists()}
        (output / (label + '-exit.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        assert receipt['pipes_closed'] and receipt['absent'] and not rescued


def serve(data, fd):
    source_check(data)
    os.environ['AIDDOS_RUN_DB_SOCKET'] = data['socket']
    os.environ['AIDDOS_UI_STATE_PATH'] = data['state']
    import uvicorn

    from aiddos.api.app import app
    listener = socket.socket(fileno=fd)
    assert list(listener.getsockname()) == data['bind']
    uvicorn.Server(uvicorn.Config(app, log_level='critical', access_log=False)).run(
        sockets=[listener])


@contextmanager
def server(data):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    bind = listener.getsockname()
    data = {**data, 'bind': list(bind)}
    receipt = Path(data['output']) / 'api-handoff.json'
    receipt.write_text(json.dumps(data, indent=2) + '\n')
    sequence = 0

    def request(method, path, body=None):
        nonlocal sequence
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(7)
        sock.connect(bind)
        conn = http.client.HTTPConnection(bind[0], bind[1], timeout=7)
        conn.sock = sock
        raw = None if body is None else json.dumps(body).encode()
        try:
            conn.request(
                method, path, raw, {} if raw is None else {'Content-Type': 'application/json'}
            )
            response = conn.getresponse()
            content = response.read()
            headers = dict(response.getheaders())
            status = response.status
        finally:
            conn.close()
        sequence += 1
        corpus = ROOT / 'i2-evidence/producer-corpus' / Path(data['output']).parent.name
        corpus.mkdir(parents=True, exist_ok=True)
        name = f'{sequence:04d}'
        (corpus / (name + '.body')).write_bytes(content)
        (corpus / (name + '.json')).write_text(json.dumps({
            'method': method, 'path': path, 'status': status, 'headers': headers,
            'request': body, 'body_sha256': hashlib.sha256(content).hexdigest(),
            'source': data['source'], 'kind': 'actual-http-producer',
        }, indent=2) + '\n')
        assert headers.get('cache-control') == 'no-store'
        return status, json.loads(content)

    with child(data, 'api', [data['python'], str(Path(__file__)), '--serve', str(receipt),
                             str(listener.fileno())], pass_fds=(listener.fileno(),)) as p:
        listener.close()
        until = time.monotonic() + 5
        while True:
            try:
                if request('GET', '/api/v1/health')[0] == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            assert p.poll() is None and time.monotonic() < until
            time.sleep(0.03)
        yield request


def execute(data):
    source_check(data)
    import psycopg
    assert Path(psycopg.__file__).is_relative_to(ROOT / '.venv')
    output = Path(data['output'])
    assert output.is_relative_to(ROOT / 'implementation-evidence')
    assert Path(data['socket']).is_relative_to('/home/piecer/.hermes/cache/scratch/i3w-lecrmpg5')
    data = {**data, 'state': str(output / 'draft.json')}
    with child(data, 'migration', [data['python'], '-m', 'aiddos.runs.migrate'],
               env={'AIDDOS_RUN_DB_SOCKET': data['socket']}) as migration:
        assert migration.wait(timeout=8) == 0
    sys.path.insert(0, str(ROOT / 'tests/api'))
    from scenario_producer import definition
    with server(data) as request:
        targets = []
        for kind in ('DUT', 'SINK'):
            status, target = request(
                'POST', '/api/v1/targets',
                {'name': kind, 'kind': kind, 'address': 'never-resolve.invalid'},
            )
            assert status == 201
            targets.append(target)
        status, scenario = request('POST', '/api/v1/scenarios',
                                   {'revision': 0, 'definition': definition(targets)})
        assert status == 201
        record = scenario['scenario']
        value = {'request_id': str(uuid4()), 'mode': 'OFFLINE', 'scenario_id': record['id'],
                 'scenario_version': record['version'], 'scenario_digest': record['digest']}
        status, queued = request('POST', '/api/v1/offline-runs', value)
        assert status == 202 and queued['run']['state'] == 'QUEUED'
        with psycopg.connect(
            **h.connection_parameters(Path(data['socket'])), autocommit=True
        ) as db:
            captured = db.execute('SELECT request,snapshot FROM aiddos_runs_v1.inputs').fetchone()
        assert json.loads(captured[1]) == queued['snapshot']
        # These files were created by this exact API fixture, never caller S01 data.
        for p in output.glob('draft.json*'):
            if p.is_file():
                p.rename(p.with_name('unavailable-' + p.name))
        with child(data, 'worker', [data['python'], '-m', 'aiddos.runs.worker'],
                   env={'AIDDOS_RUN_DB_SOCKET': data['socket']}) as worker:
            until = time.monotonic() + 4
            while True:
                status, detail = request('GET', '/api/v1/offline-runs/' + queued['run']['id'])
                assert status == 200
                if detail['run']['state'] == 'SUCCEEDED' or time.monotonic() >= until:
                    break
                if worker.poll() is not None:
                    break
                time.sleep(0.05)
            (output / 'observed.json').write_text(json.dumps({
                'worker_exit': worker.poll(), 'detail': detail,
            }, indent=2) + '\n')
            assert detail['run']['state'] == 'SUCCEEDED'
            assert detail['snapshot'] == queued['snapshot']
            assert detail['result']['evaluation'] == 'NOT_EVALUATED'
            assert detail['result']['measurements'] is None
            assert detail['result']['defense_verdict'] is None
            with psycopg.connect(
                **h.connection_parameters(Path(data['socket'])), autocommit=True
            ) as db:
                assert db.execute('SELECT state FROM aiddos_runs_v1.jobs').fetchall() == [
                    ('SUCCEEDED',)
                ]
                assert json.loads(
                    db.execute('SELECT result FROM aiddos_runs_v1.results').fetchone()[0]
                ) == detail['result']
                assert db.execute(
                    'SELECT retained_count,unfinished_count,leased_count,reserved_bytes '
                    'FROM aiddos_runs_v1.quota'
                ).fetchone() == (1, 0, 0, 65536)
        (output / 'result.json').write_text(json.dumps({'detail': detail}, indent=2) + '\n')


if __name__ == '__main__':
    if sys.argv[1] == '--serve':
        serve(json.loads(Path(sys.argv[2]).read_text()), int(sys.argv[3]))
    else:
        data = json.loads(Path(sys.argv[1]).read_text())
        try:
            execute(data)
        except BaseException as exc:
            (Path(data['output']) / 'failure.json').write_text(json.dumps({
                'type': type(exc).__name__,
                'frames': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                           for f in traceback.extract_tb(exc.__traceback__)],
            }, indent=2) + '\n')
            raise SystemExit(1) from None
