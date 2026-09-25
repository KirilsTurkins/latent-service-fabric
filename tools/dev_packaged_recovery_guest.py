"""Observe real expiry and authority failures in two disposable installed nodes."""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time
from types import SimpleNamespace


def run(args):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise ValueError('unprivileged-installed-recovery-owner-required')
    helper_path = args.helper.absolute()
    if helper_path.resolve() != helper_path or not re.fullmatch(r'sha256:[a-f0-9]{64}', args.helper_sha256):
        raise ValueError('exact-installed-helper-required')
    for path in (helper_path, *helper_path.parents):
        info = path.lstat()
        sticky = info.st_uid == 0 and stat.S_ISDIR(info.st_mode) and info.st_mode & stat.S_ISVTX
        if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022 and not sticky or stat.S_ISLNK(info.st_mode):
            raise ValueError('protected-installed-helper-required')
    with helper_path.open('rb') as stream:
        raw = stream.read(2097153)
    if len(raw) > 2097152 or 'sha256:' + hashlib.sha256(raw).hexdigest() != args.helper_sha256:
        raise ValueError('installed-helper-digest-mismatch')
    if args.workspace not in {'test-packaged-rust-expiry', 'test-packaged-rust-unknown'}:
        raise ValueError('explicit-recovery-qualification-workspace-required')
    packet = sys.stdin.buffer.read(1572865)
    if len(packet) > 1572864:
        raise ValueError('recovery-conductor-input-limit')
    request = json.loads(packet)
    sys.path.insert(0, str(helper_path))
    from tools.dev_workflow import client, helper, paths, state
    from tools.dev_workflow.common import decode, digest, encode, require
    root = state.workspace(helper.root_directory(), args.workspace)
    layout, current = helper.installation(root)
    require(decode(paths.read(layout.node.parent, layout.node.name))['securityProfile'] == 'local-experimental-v1',
            'explicit-local-recovery-profile-required')

    if args.mode == 'configure-expiry':
        require(args.workspace.endswith('-expiry'), 'explicit-expiry-workspace-required')
        with state.lock(root):
            require(not any((root / name).exists() for name in ('lifecycle.json', 'last-deployment.json', 'test-profile.json')),
                    'configure-supported-retention-before-first-node-start')
            original = paths.read(layout.node.parent, layout.node.name)
            node = decode(original)
            node.setdefault('retention', {})['terminalTtlMillis'] = 3000
            state.atomic(layout.node.parent, layout.node.name, node)
            return {'terminalTtlMillis': 3000, 'clockChanged': False, 'receiptStoreEdited': False,
                'beforeConfigurationSha256': digest(original), 'configurationSha256': digest(encode(node))}

    cli, journal = helper.client(root, deadline=time.monotonic() + 90)
    if args.mode == 'authority':
        require(args.workspace.endswith('-unknown') and journal.read()['pending'] is None,
                'ready-authority-workspace-without-pending-operation-required')
        arguments = request['arguments']
        require(set(arguments) == {'service', 'contract', 'function', 'mediaType', 'input'}, 'closed-authority-invoke-fields')
        raw = base64.b64decode(arguments['input'], validate=True)
        require(len(raw) <= 1048576, 'authority-invoke-input-bound')
        path = root / 'qualification-authority-input.json'
        paths.write_new(path, raw)
        original = decode(paths.read(layout.client.parent, layout.client.name))
        result = {}
        for kind in ('wrong-token', 'wrong-tenant'):
            name = 'qualification-' + kind
            require(not (root / (name + '-intent.json')).exists(), 'inspect-original-authority-invocation-before-new-attempt')
            selected = copy.deepcopy(original)
            selected['profiles'][0]['token' if kind == 'wrong-token' else 'tenant'] = (
                secrets.token_hex(32) if kind == 'wrong-token' else 'another-tenant')
            configuration = root / (name + '.json')
            paths.write_new(configuration, encode(selected))
            foreign = client.Client(current / 'bin/latent', configuration, root, deadline=time.monotonic() + 30)
            activation = 'qualification-' + secrets.token_hex(16)
            state.atomic(root, name + '-intent.json', {'activationId': activation, 'inputSha256': digest(raw)})
            observed = foreign.call('invoke', '--service', arguments['service'], '--contract', arguments['contract'],
                '--function', arguments['function'], '--media-type', arguments['mediaType'], '--input', path,
                '--activation-id', activation)
            require(observed['category'] == 'platform-failure' and observed['outcomeKnown'] is True
                    and observed['error']['code'] in {'unauthenticated', 'permission-denied'}, 'cross-authority-invocation-not-denied')
            result[kind] = {'category': observed['category'], 'outcomeKnown': True, 'code': observed['error']['code'],
                'activationId': activation, 'calls': 1, 'credentialInArguments': False, 'privateConfigurationExported': False}
        return result
    if args.mode == 'expire-original-invoke':
        require(args.workspace.endswith('-expiry') and journal.read()['pending'] is None,
                'fresh-expiry-intent-required')
        node = decode(paths.read(layout.node.parent, layout.node.name))
        require(node['retention']['terminalTtlMillis'] == 3000, 'configured-real-receipt-retention-required')
        source = request['faultSource']['source'].encode('utf-8')
        require(len(source) <= 16384 and digest(source) == request['faultSource']['sha256'], 'reviewed-fault-source-digest')
        with tempfile.TemporaryDirectory(prefix='qualification-observer-', dir=root) as directory:
            paths.write_new(Path(directory) / 'qualification_fault_probe.py', source)
            sys.path.insert(0, directory)
            saved = sys.stdin
            try:
                from qualification_fault_probe import run as inject_original
                sys.stdin = io.TextIOWrapper(io.BytesIO(encode(request['arguments'])))
                injection = inject_original(SimpleNamespace(helper=helper_path, helper_sha256=args.helper_sha256,
                    workspace=args.workspace, kind='invoke'))
            finally:
                sys.stdin = saved
                sys.path.remove(directory)
        pending = journal.read()['pending']
        require(injection['selectedMutationCalls'] == injection['remoteMutationCalls'] == 1
                and injection['pending']['id'] == pending['id'], 'one-original-expiring-invocation-required')
        found = cli.lookup('invoke', pending['id'])
        require(found['category'] == 'success' and found['outcomeKnown'] is True
            and found['data']['activationId'] == pending['id'] and found['data']['terminalState'] == 'completed',
            'original-terminal-receipt-not-observed-before-expiry')
        began = time.monotonic()
        polls = 0
        while True:
            require(time.monotonic() - began < 20 and polls < 100, 'real-receipt-expiry-not-observed')
            time.sleep(0.2)
            expired = cli.lookup('invoke', pending['id'])
            polls += 1
            if expired['category'] != 'success':
                break
        require(expired['category'] == 'not-found' and expired['outcomeKnown'] is True,
                'actual-receipt-expiry-not-transport-failure-required')
        require(journal.read()['pending'] == pending, 'expiry-must-retain-original-intent')
        return {'injection': injection, 'found': found, 'expired': expired, 'terminalTtlMillis': 3000,
            'clockChanged': False, 'receiptStoreEdited': False, 'readOnlyPolls': polls,
            'waitSeconds': round(time.monotonic() - began, 3), 'sameOriginalRetained': True}
    if args.mode == 'deployment-state':
        selected = state.load(root, 'last-deployment.json')
        actual = cli.call('deployment', 'get', selected['deployment'], '--operation-snapshot')
        require(actual['category'] == 'success' and actual['outcomeKnown'] is True, 'actual-deployment-observation-required')
        return {'controller': selected, 'serverGeneration': actual['data']['deployment']['generation']}
    raise ValueError('closed-recovery-observation-mode-required')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--helper-sha256', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--mode', choices=('configure-expiry', 'authority', 'expire-original-invoke', 'deployment-state'), required=True)
    print(json.dumps(run(parser.parse_args()), sort_keys=True))
