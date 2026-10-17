"""Fresh verifier process: stdio barriers and pre-import product-effect veto."""
import hashlib
import json
import os
import sys
from pathlib import Path


def main():
    root, directory, receipt, mode = sys.argv[1:]
    root = Path(root)
    counts = dict.fromkeys(('socket', 'dns', 'connect', 'child'), 0)
    events = []

    class ForbiddenEffect(BaseException):
        pass

    def observe(event, args):
        category = None
        if event == 'socket.__new__':
            category = 'socket'
        elif event.startswith('socket.'):
            category = 'connect' if event == 'socket.connect' else 'dns'
        elif event in ('subprocess.Popen', 'os.system', 'os.fork', 'os.forkpty',
                       'os.posix_spawn', 'os.exec', 'os.spawn'):
            category = 'child'
        if category:
            counts[category] += 1
            events.append(event)
            raise ForbiddenEffect()

    identity = dict(pid=os.getpid(),
                    start=Path('/proc/self/stat').read_text().split(') ')[1].split()[19],
                    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    sys.addaudithook(observe)
    output = dict(identity=identity, counts=counts, events=events, origins={}, callbacks=0,
                  observer_installed_before_product_import=True)
    print(json.dumps(identity), flush=True)
    assert sys.stdin.readline() == 'GO\n'
    if mode.startswith('control-'):
        event = {'control-socket': 'socket.__new__', 'control-dns': 'socket.getaddrinfo',
                 'control-connect': 'socket.connect', 'control-child': 'subprocess.Popen'}[mode]
        try:
            sys.audit(event, None)
        except ForbiddenEffect:
            output['control_blocked'] = True
        assert output.get('control_blocked') is True
    else:
        from aiddos.lab import profile, session

        for module in (profile, session):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(root / 'src')
            output['origins'][module.__name__] = dict(
                path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        value = profile.template()
        value['target'].update(connect_ipv4='127.0.0.1', port=8080, scheme='http',
                               http_host='Example.test', path='/PRIVATE_SENTINEL')
        value['source'].update(bind_ipv4='127.0.0.1', interface='lo')
        value['expected']['http_status'] = 200
        value['budget']['max_attempts'] = 1
        raw = profile.canonical(value)
        if mode == 'error':
            real = session._write

            def partial(fd, data):
                output['fault_fired'] = True
                real(fd, data[:13])
                raise OSError('PRIVATE_SENTINEL')

            session._write = partial

        def action(permit):
            output['callbacks'] += 1
            permit.checkpoint()

        try:
            owner = session.SessionOwner.admit(raw, hashlib.sha256(raw).hexdigest(), directory)
        except session.SessionError as failure:
            output['code'] = failure.code
        else:
            assert owner.run_attempt(action) == 1
            output['result'] = owner.finish()
    Path(receipt).write_text(json.dumps(output, sort_keys=True) + '\n')
    print(json.dumps(output), flush=True)


if __name__ == '__main__':
    main()
