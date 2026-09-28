"""Hosted-CI-compatible execution against a real node in another network namespace."""
from __future__ import annotations

import copy
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/source/tools')
sys.path.insert(0, '/source/tools/container_runtime')
from ci_operator import Transport, operate, protected
from native_runtime import files
from native_runtime.common import InstallError, encode, require
from operator_process import run

INSIDE = '/source/tools/container_runtime/qualification_operator_inside.py'


def main():
    node, image = sys.argv[1:]
    root = Path('/journal')
    root.mkdir(mode=0o700, exist_ok=True); root.chmod(0o700)
    transport = Transport(Path('/usr/bin/docker'))
    identity = transport.inspect(node)
    require(identity['image'] == image, 'qualification-image')
    target = {'schemaVersion': 'latent.container-operator-target.v1', 'identity': identity,
              'node': 'container-qualification', 'tenant': 'tests', 'expires': int(time.time()) + 900}
    files.create(root / 'target.json', encode(target))
    calls, deadline = 0, time.monotonic() + 180

    def inside(mode):
        command = ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'exec', node,
                   '/usr/local/bin/python3', INSIDE]
        try:
            return json.loads(run([*command, mode], seconds=100))
        except InstallError:
            diagnostic = json.loads(run([*command, 'failure']))
            files.replace(root / 'qualification-command-failure.json', encode(diagnostic))
            raise InstallError('qualification-native-outcome: ' + json.dumps(diagnostic)) from None

    def command(request, *, recovery=None, selected=None, expected=None):
        nonlocal calls
        calls += 1
        require(calls <= 48 and time.monotonic() < deadline, 'qualification-ci-operation-bound')
        journal = recovery or root / ('command-' + str(calls) + '.json')
        summary = operate(transport, selected or target, request, journal, recovery is not None)
        if expected:
            require(summary['status'] == expected, 'qualification-operator-status-' + summary['status'])
        return protected(journal), journal

    work = inside('inputs')['work']
    publications = {}
    for name in ('site', 'documentation'):
        observed, _ = command({'kind': 'package-inspect', 'value': work + '/' + name + '/package'}, expected='observed')
        require(observed['result']['category'] == 'success', 'qualification-package-inspection')
        result, _ = command({'kind': 'publish', 'id': 'container-' + name, 'generation': '0',
            'package': work + '/' + name + '/package', 'evidence': work + '/' + name + '-evidence/index.json'}, expected='confirmed')
        publications[name] = result['result']['data']['operation']['publication']['id']

    def route(name, publication, path='/', method='GET', cut=False):
        current, _ = command({'kind': 'trigger-get', 'value': name}, expected='observed')
        data = current['result']['data']
        generation = data['trigger']['generation'] if data['trigger'] else '0'
        request = {'kind': 'route', 'id': 'ci-' + str(calls), 'generation': generation,
            'stateVersion': data['stateVersion'], 'manifest': {'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
                'metadata': {'name': name, 'tenant': 'tests'}, 'spec': {
                    'target': {'kind': 'static-web', 'publication': publication}, 'configuration': {
                        'profile': 'static-site-v1', 'scheme': 'http', 'host': 'frontend.example.test',
                        'path': path, 'pathMatch': 'prefix', 'method': method}}}}
        if cut:
            transport.receiver = '/source/tools/container_runtime/qualification_operator_cut.py'
        try:
            value, journal = command(request, expected='uncertain' if cut else 'confirmed')
        finally:
            transport.receiver = '/opt/lsf/runtime/operator_receiver.py'
        return request, journal, value

    for name, path in [('site', '/'), ('documentation', '/docs')]:
        for method in ('GET', 'HEAD'):
            route(name + '-' + method.lower(), publications[name], path, method)
    serving = inside('record')
    # An explicit cutover and new rollback operation leave the original site
    # selected without changing container identity, revision, or management exposure.
    for publication in (publications['documentation'], publications['site']):
        for method in ('GET', 'HEAD'):
            route('site-' + method.lower(), publication, method=method)
    first, journal, _ = route('ci-cut', publications['site'], '/ci-cut', cut=True)
    require(inside('remove-cut-marker')['actualNativeCommit'], 'qualification-actual-cut-commit')
    recovered, _ = command(first, recovery=journal, expected='confirmed')
    require(recovered['request'] == first, 'qualification-original-request-changed')
    # The same exact instance may use a renewed transport lease to recover the
    # original operation. Neither operation identity nor preconditions change.
    renewed = copy.deepcopy(target); renewed['expires'] = int(time.time()) + 900
    command(first, recovery=journal, selected=renewed, expected='confirmed')
    cancelled, _, _ = route('ci-cancel', publications['site'], '/ci-cancel')
    current, _ = command({'kind': 'trigger-get', 'value': 'ci-cancel'}, expected='observed')
    cancelled.update(id='ci-cancelled-worker', generation=current['result']['data']['trigger']['generation'],
                     stateVersion=current['result']['data']['stateVersion'])
    files.create(root / 'cancel-request.json', encode(cancelled))
    child = subprocess.Popen([sys.executable, '-I', '/source/tools/container_runtime/qualification_operator_cancel.py'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        until = time.monotonic() + 12
        while not inside('cancel-marker').get('actualNativeCommit'):
            require(time.monotonic() < until and child.poll() is None, 'qualification-cancel-commit-not-observed')
            time.sleep(0.05)
        child.send_signal(signal.SIGTERM)
        child.wait(timeout=6)
        require(child.returncode == 0, 'qualification-cancelled-worker-journal')
        require(protected(root / 'cancel-journal.json')['status'] == 'uncertain', 'qualification-cancelled-response-unknown')
        command(cancelled, recovery=root / 'cancel-journal.json', expected='confirmed')
        until = time.monotonic() + 7
        while not inside('cancel-marker').get('responseOwnerFinished'):
            require(time.monotonic() < until, 'qualification-cancelled-response-owner-not-reaped')
            time.sleep(0.1)
    finally:
        if child.poll() is None: child.kill()
        child.wait(timeout=5); child.stderr.close()
    evicted, old, _ = route('ci-evicted', publications['site'], '/ci-evicted', cut=True)
    inside('remove-cut-marker')
    eviction = inside('evict')
    command(evicted, recovery=old, expected='uncertain')
    # An expired lease and stale instance selection fail before native dispatch.
    for key, altered in [('expires', 1), ('node', 'wrong-node'), ('tenant', 'foreign-tenant')]:
        selected = copy.deepcopy(target); selected[key] = altered
        command({'kind': 'web-get', 'value': publications['site']}, selected=selected, expected='unavailable')
    selected = copy.deepcopy(target); selected['identity']['started'] = '1970-01-01T00:00:00Z'
    command({'kind': 'web-get', 'value': publications['site']}, selected=selected, expected='unavailable')
    transport.receiver = '/source/tools/container_runtime/qualification_operator_denied.py'
    try:
        command({'kind': 'web-get', 'value': publications['site']}, expected='unavailable')
    finally:
        transport.receiver = '/opt/lsf/runtime/operator_receiver.py'
    # Actual OS authorization denial: this unprivileged worker cannot open the
    # daemon socket. No cloud RBAC outcome is inferred from it.
    denied = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'inspect', '--format', '{{.Id}}', node],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        user=65534, group=65534, extra_groups=[], timeout=5)
    require(denied.returncode != 0, 'qualification-daemon-access-was-not-denied')
    require(inside('permission-marker') == {'actualNativePermissionDenied': True}, 'qualification-native-permission-denial')
    require(transport.inspect(node) == identity, 'qualification-content-release-restarted-node')
    print(json.dumps({'schemaVersion': 'latent.container-operator-qualification.v1', 'passed': True,
        'noninteractive': True, 'separateNetworkNamespaces': True, 'credentialsOutsideNode': False,
        'publishInspectGetHeadCutoverRollback': True, 'serving': serving, 'lostResponseRecoveredWithoutReplay': True,
        'actualReceiptEviction': eviction, 'unknownNotReplayed': True, 'runtimeInstanceUnchanged': True,
        'wrongNodeTenantExpiredAndStaleSelectionDenied': True, 'daemonPermissionDenied': True,
        'workerCancelledAfterActualCommit': True, 'cancelledOwnerFinished': True, 'renewedLeaseRecoveredOriginal': True,
        'actualInvocationOnlyCredentialDenied': True,
        'operatorCommands': calls, 'maximumSeconds': 180, 'cloudQualified': False}))


if __name__ == '__main__':
    main()
