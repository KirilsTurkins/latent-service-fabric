"""One finite, noninteractive operator command inside the intended node namespace."""
from __future__ import annotations

import os
from pathlib import Path
import selectors
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, '/opt/lsf/runtime')
from native_runtime import files
from native_runtime.common import InstallError, document, encode, execute, require
from operator_model import identifier, members, validate

CLIENT = Path('/etc/lsf/ci-client.json')
CLI = '/opt/lsf/release/bin/latent'
CACHE = Path('/var/cache/lsf')
LOCK = None


def input_document():
    raw, deadline = bytearray(), time.monotonic() + 3
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and len(raw) <= 65536, 'operator-input-bound')
            require(selector.select(remaining), 'operator-input-timeout')
            block = os.read(sys.stdin.fileno(), min(8192, 65537 - len(raw)))
            if not block:
                return document(bytes(raw), 65536)
            raw.extend(block)


def call(tenant, *arguments):
    code, raw = execute([CLI, '--config', str(CLIENT), '--tenant', tenant, '--output', 'json',
        '--connect-timeout-ms', '500', '--rpc-timeout-ms', '5000', *map(str, arguments)],
        timeout=6, maximum=524288, stdout_only=True, pass_fds=(LOCK,) if LOCK is not None else ())
    result = document(raw, 524288)
    codes = {'success': 0, 'local-error': 2, 'declared-error': 3, 'platform-failure': 4,
             'transport-failure': 5, 'not-found': 6, 'interrupted': 130}
    require(result.get('schemaVersion') == 'latent.cli.result.v1' and codes.get(result.get('category')) == code
            and type(result.get('outcomeKnown')) is bool, 'operator-cli-response-invalid')
    return result


def receive(value):
    global LOCK
    require(os.geteuid() == os.getegid() == 10001, 'operator-receiver-node-identity')
    members(value, ('node', 'tenant', 'expires', 'recover', 'request'))
    identifier(value['node']); identifier(value['tenant'])
    require(type(value['expires']) is int and time.time() < value['expires'] <= time.time() + 900,
            'operator-selection-expired')
    require(type(value['recover']) is bool, 'operator-recovery-mode')
    request = validate(value['request'], value['tenant'])
    client = document(files.read(CLIENT, 65536, owners={0, 10001}, private=True, trusted_gid=10001), 65536)
    profiles = [row for row in client.get('profiles', []) if row.get('name') == client.get('defaultProfile')]
    require(len(profiles) == 1 and profiles[0].get('tenant') == value['tenant'], 'operator-credential-tenant-mismatch')
    # Kernel lock serializes all CI workers for this node. A cancelled worker's
    # child retains this bounded owner until its native operation has returned.
    with files.lock(CACHE / '.ci-operator.lock', timeout=0) as lease:
        LOCK = lease
        observed = call(value['tenant'], 'node', 'get', value['node'])
        require(observed.get('category') == 'success' and observed.get('outcomeKnown') is True
                and observed.get('data', {}).get('inventory', {}).get('node', {}).get('id') == value['node'],
                'operator-node-identity-or-permission-unavailable')
        require(time.time() < value['expires'], 'operator-selection-expired')
        kind = request['kind']
        if value['recover']:
            require(kind in {'publish', 'route'}, 'operator-mutation-journal-required')
            return call(value['tenant'], 'web' if kind == 'publish' else 'trigger', 'operation', request['id'])
        if kind == 'publish':
            # Inputs must be supplied through the separately reviewed read-only
            # /work mount. Native package and evidence validation remain authoritative.
            return call(value['tenant'], 'web', 'publish', request['package'], '--evidence', request['evidence'],
                        '--operation-id', request['id'], '--expected-generation', request['generation'])
        if kind == 'route':
            descriptor, name = tempfile.mkstemp(prefix='ci-route-', suffix='.json', dir=CACHE)
            path = Path(name)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(encode(request['manifest'])); stream.flush(); os.fsync(stream.fileno())
                return call(value['tenant'], 'trigger', 'apply', path, '--operation-id', request['id'],
                            '--expected-generation', request['generation'], '--expected-state-version', request['stateVersion'])
            finally:
                path.unlink(missing_ok=True)
        arguments = {'web-get': ('web', 'get', '--publication', request['value']),
                     'trigger-get': ('trigger', 'get', request['value']),
                     'package-inspect': ('package', 'inspect', request['value'])}[kind]
        return call(value['tenant'], *arguments)


def main():
    try:
        require(not sys.argv[1:], 'operator-receiver-has-no-command-line-input')
        print(encode(receive(input_document())).decode(), end='')
        return 0
    except InstallError as error:
        print(encode({'schemaVersion': 'latent.container-operator-error.v1', 'reason': str(error)}).decode(), end='')
    except (OSError, ValueError, KeyError, TypeError):
        print('{"schemaVersion":"latent.container-operator-error.v1","reason":"operator-private-input-or-channel-failed"}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
