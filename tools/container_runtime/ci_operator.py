#!/usr/bin/env python3
"""Headless CI management through a local Docker host, with durable no-replay journals."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_runtime import files
from native_runtime.common import InstallError, document, encode, require
from operator_model import identifier, members, receipt_matches, validate
from operator_process import run

SOCKET = 'unix:///var/run/docker.sock'
RECEIVER = '/opt/lsf/runtime/operator_receiver.py'


class Transport:
    def __init__(self, docker):
        self.docker = str(docker)
        require(docker.is_absolute(), 'operator-absolute-docker-required')
        with files.regular(docker, 128 * 1024 * 1024, owners={0}):
            pass
        self.receiver = RECEIVER

    def inspect(self, identity):
        require(re.fullmatch(r'[a-f0-9]{64}', identity), 'operator-full-container-id-required')
        fields = {'container': '.Id', 'image': '.Image', 'running': '.State.Running', 'started': '.State.StartedAt',
                  'user': '.Config.User', 'privileged': '.HostConfig.Privileged', 'mounts': '.Mounts'}
        template = '{' + ','.join('"' + key + '":{{json ' + value + '}}' for key, value in fields.items()) + '}'
        value = document(run([self.docker, '--host', SOCKET, 'inspect', '--format', template, identity]))
        require(value['container'] == identity and value['running'] is True
                and value['privileged'] is False and value['user'] == '10001:10001', 'operator-node-container-profile')
        mounts = {row['Destination']: row for row in value.pop('mounts')}
        for name, writable in (('/etc/lsf', False), ('/work', False), ('/var/lib/lsf', True), ('/var/cache/lsf', True)):
            require(name in mounts and mounts[name]['RW'] is writable, 'operator-node-mount-profile')
        value['dataMount'] = {key: mounts['/var/lib/lsf'][key] for key in ('Type', 'Source', 'Destination')}
        return value

    def call(self, target, request, directory, recover=False):
        require(time.time() < target['expires'], 'operator-selection-expired')
        before = self.inspect(target['identity']['container'])
        require(before == target['identity'], 'operator-replica-changed-no-dispatch')
        payload = encode({'node': target['node'], 'tenant': target['tenant'], 'expires': target['expires'],
                          'recover': recover, 'request': request})
        require(len(payload) <= 65536, 'operator-request-byte-bound')
        # stdin is a private finite file, never a shell, environment token or CLI credential.
        with tempfile.TemporaryFile(dir=directory) as stream:
            stream.write(payload); stream.seek(0)
            raw = run([self.docker, '--host', SOCKET, 'exec', '--interactive', target['identity']['container'],
                       '/usr/local/bin/python3', '-I', self.receiver], stream)
        result = document(raw, 524288)
        require(result.get('schemaVersion') == 'latent.cli.result.v1', 'operator-channel-result-unavailable')
        require(self.inspect(target['identity']['container']) == before, 'operator-replica-changed-outcome-unconfirmed')
        return result


def protected(path):
    return document(files.read(path, 1048576, owners={0, os.geteuid()}, private=True))


def binding(target):
    # A fresh finite transport lease may recover the same exact node instance.
    # It cannot retarget an old journal to a restarted/replaced container.
    return hashlib.sha256(encode({key: value for key, value in target.items() if key != 'expires'})).hexdigest()


def operate(transport, target, request, journal, recover=False):
    validate(request, target['tenant'])
    mutation = request['kind'] in {'publish', 'route'}
    require(not recover or mutation, 'operator-only-mutations-have-recovery-journals')
    with files.directory(journal.parent, {0, os.geteuid()}) as parent:
        metadata = os.fstat(parent)
        require(metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o077, 'operator-private-journal-directory')
    with files.lock(journal.parent / '.ci-operator.lock', timeout=0):
        if recover:
            saved = protected(journal)
            require(saved['request'] == request and saved['binding'] == binding(target), 'operator-journal-target-mismatch')
            require(saved['status'] in {'pending', 'uncertain', 'confirmed'}, 'operator-no-pending-mutation')
        else:
            require(not journal.exists(), 'operator-journal-exists-recover-original-operation')
            saved = {'schemaVersion': 'latent.container-operator-journal.v1', 'binding': binding(target),
                     'target': target, 'request': request, 'status': 'pending' if mutation else 'reading'}
            files.create(journal, encode(saved))
        try:
            result = transport.call(target, request, journal.parent, recover)
            if mutation:
                if receipt_matches(result, request, target['tenant']):
                    status = 'confirmed'
                elif recover or result.get('outcomeKnown') is not True:
                    status = 'uncertain'
                else:
                    status = 'rejected'
            else:
                status = 'observed' if result.get('outcomeKnown') is True else 'uncertain'
            saved.update(status=status, result=result)
        except (InstallError, OSError, ValueError, KeyError, TypeError):
            saved.update(status='uncertain' if mutation else 'unavailable', reason='inspect-original-operation-no-replay')
        files.replace(journal, encode(saved))
        return {'schemaVersion': 'latent.container-operator-result.v1', 'status': saved['status'],
                'operation': request.get('id'), 'journal': str(journal), 'mutationReplayed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('select', 'run', 'recover'))
    parser.add_argument('--docker', type=Path, default=Path('/usr/bin/docker'))
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--container')
    parser.add_argument('--image')
    parser.add_argument('--node')
    parser.add_argument('--tenant')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    try:
        transport = Transport(args.docker)
        if args.action == 'select':
            identity = transport.inspect(args.container)
            require(identity['image'] == args.image, 'operator-reviewed-image-required')
            identifier(args.node); identifier(args.tenant)
            value = {'schemaVersion': 'latent.container-operator-target.v1', 'identity': identity,
                     'node': args.node, 'tenant': args.tenant, 'expires': int(time.time()) + 900}
            files.create(args.target.absolute(), encode(value))
            print(encode({'selected': True, 'expires': value['expires'], 'managementPublished': False}).decode(), end='')
            return 0
        target = protected(args.target.absolute())
        members(target, ('schemaVersion', 'identity', 'node', 'tenant', 'expires'))
        require(target['schemaVersion'] == 'latent.container-operator-target.v1', 'operator-target-format')
        require(args.request is not None and args.journal is not None, 'operator-request-and-journal-required')
        result = operate(transport, target, protected(args.request.absolute()), args.journal.absolute(), args.action == 'recover')
        print(encode(result).decode(), end='')
        return 0 if result['status'] in {'confirmed', 'observed'} else 5
    except (InstallError, OSError, ValueError, KeyError, TypeError) as error:
        reason = str(error) if isinstance(error, InstallError) else 'operator-input-or-private-storage-failed'
        print(encode({'schemaVersion': 'latent.container-operator-result.v1', 'status': 'failed', 'reason': reason}).decode(), end='')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
