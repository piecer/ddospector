"""Verifier-owned fresh processes, not product subprocess capability."""
import hashlib
import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest
from authority_support import arguments, canonical, document
from test_session import configured

ROOT = Path(__file__).resolve().parents[2]


def approved_input(tmp_path, directory):
    raw, _ = configured(max_attempts=1)
    value = json.loads(raw)
    value['target']['path'] = '/PRIVATE_SENTINEL'  # Preserve the original child profile.
    inputs = arguments(document(canonical(value), directory))
    inputs['raw_authority'] = inputs['raw_authority'].decode('utf-8')
    path = tmp_path / 'authority.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(inputs, stream)
    return path, inputs['confirmed_authority_sha256']


def launch(tmp_path, directory, name, mode, authority_path=None):
    receipt = tmp_path / (name + '.json')
    env = dict(PATH=os.environ['PATH'], HOME=str(tmp_path), TMPDIR=str(tmp_path),
               PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT / 'src'))
    child = subprocess.Popen([sys.executable, str(ROOT / 'tests/lab/session_probe.py'),
        str(ROOT), str(directory), str(receipt), mode,
        '-' if authority_path is None else str(authority_path)], cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(5), 'child ready barrier timeout'
        line = child.stdout.readline()
        identity = json.loads(line)
        assert identity['pid'] == child.pid
        assert identity['start'] == Path(f'/proc/{child.pid}/stat').read_text().split(
            ') ')[1].split()[19]
        assert identity['boot'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return child, identity, receipt
    except BaseException:
        child.kill()
        child.communicate(timeout=5)
        raise


def complete(item):
    child, identity, receipt = item
    stdout, stderr = child.communicate(timeout=5)
    assert child.returncode == 0, (stdout, stderr)
    assert stderr == ''
    assert not Path(f'/proc/{identity["pid"]}').exists()
    result = json.loads(stdout)
    assert result == json.loads(receipt.read_bytes())
    result['process_absent_after_wait'] = True
    return result


def cleanup(items):
    for child, identity, _ in items:
        if child.poll() is None:
            current = Path(f'/proc/{child.pid}/stat').read_text().split(') ')[1].split()[19]
            assert current == identity['start']
            child.kill()
        child.communicate(timeout=5)
        assert not Path(f'/proc/{child.pid}').exists()


def no_effects(result, expected_authority):
    assert result['counts'] == dict(socket=0, dns=0, connect=0, child=0)
    assert result['events'] == []
    assert result['observer_installed_before_product_import'] is True
    assert set(result['origins']) == {
        'aiddos.lab.authority', 'aiddos.lab.profile', 'aiddos.lab.session'}
    assert result['authority_sha256'] == expected_authority
    if 'result' in result:
        assert result['result']['authority_sha256'] == expected_authority
    for origin in result['origins'].values():
        path = Path(origin['path'])
        assert path.is_relative_to(ROOT / 'src')
        assert origin['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_fresh_process_claim_race_and_success_reopen(tmp_path, record_property):
    directory = tmp_path / 'state'
    directory.mkdir(mode=0o700)
    approval, digest = approved_input(tmp_path, directory)
    items = []
    results = []
    try:
        for name in ('one', 'two'):
            items.append(launch(tmp_path, directory, name, 'race', approval))
        # Both imported observers and reached stdin before either admission begins.
        for child, _, _ in items:
            child.stdin.write('GO\n')
            child.stdin.flush()
        results = [complete(item) for item in items]
        assert sorted(r.get('code', 'COMPLETED') for r in results) == [
            'COMPLETED', 'SESSION_ALREADY_USED']
        assert sum(r['callbacks'] for r in results) == 1
        winner = next(r for r in results if 'result' in r)
        assert winner['result']['state'] == 'COMPLETED'
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        reopened = launch(tmp_path, directory, 'reopen', 'reopen', approval)
        items.append(reopened)
        reopened[0].stdin.write('GO\n')
        reopened[0].stdin.flush()
        results.append(complete(reopened))
        assert results[-1]['code'] == 'SESSION_ALREADY_USED'
        assert results[-1]['callbacks'] == 0
        assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
        for result in results:
            no_effects(result, digest)
    finally:
        cleanup(items)
        record_property('owned_processes', json.dumps(results, sort_keys=True))


def test_fresh_process_error_claim_still_spent(tmp_path, record_property):
    directory = tmp_path / 'state'
    directory.mkdir(mode=0o700)
    approval, digest = approved_input(tmp_path, directory)
    items, results = [], []
    try:
        for name, mode in (('failed', 'error'), ('reopen', 'reopen')):
            item = launch(tmp_path, directory, name, mode, approval)
            items.append(item)
            item[0].stdin.write('GO\n')
            item[0].stdin.flush()
            results.append(complete(item))
        assert [r['code'] for r in results] == ['RECORD_IO_ERROR', 'SESSION_ALREADY_USED']
        assert results[0]['fault_fired'] is True
        assert len((directory / 'baseline-claim.json').read_bytes()) == 13
        assert all(r['callbacks'] == 0 for r in results)
        for result in results:
            no_effects(result, digest)
    finally:
        cleanup(items)
        record_property('owned_processes', json.dumps(results, sort_keys=True))


@pytest.mark.parametrize('category', ['socket', 'dns', 'connect', 'child'])
def test_product_audit_veto_positive_controls(tmp_path, record_property, category):
    item = launch(tmp_path, tmp_path, 'control', 'control-' + category)
    results = []
    try:
        item[0].stdin.write('GO\n')
        item[0].stdin.flush()
        result = complete(item)
        results.append(result)
        assert result['counts'][category] == 1
        assert sum(result['counts'].values()) == 1
        assert len(result['events']) == 1
        assert result['control_blocked'] is True and result['origins'] == {}
    finally:
        cleanup([item])
        record_property('owned_processes', json.dumps(results, sort_keys=True))


def test_fresh_process_missing_authority_has_no_claim_or_callback(tmp_path, record_property):
    directory = tmp_path / 'state'
    directory.mkdir(mode=0o700)
    item = launch(tmp_path, directory, 'refused', 'missing-authority')
    results = []
    try:
        item[0].stdin.write('GO\n')
        item[0].stdin.flush()
        result = complete(item)
        results.append(result)
        assert result['code'] == 'AUTHORITY_REQUIRED' and result['callbacks'] == 0
        assert list(directory.iterdir()) == []
        no_effects(result, None)
    finally:
        cleanup([item])
        record_property('owned_processes', json.dumps(results, sort_keys=True))
