"""Ordinary Java HTTP while real fiber work remains pending on a controlled peer."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.java_standard_http_node import SERVICE, configuration as http_configuration, grants as http_grants
from tools.phase2_operator_process import require, read_json, write_json, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import (RecordingClient, deploy, delete_all, sample, start_call,
                                    finish_call, selected_revision)
from tools.rust_capsule_project import fresh
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer
from tools.static_api.node import policy

ACTIVATION = 'latent:runtime/activation@0.1.0'
OPS = ['register', 'park', 'wake', 'settle', 'close', 'observe', 'wait-for',
       'wait-until', 'timer-start', 'timer-next', 'timer-stop']
CASES = ('pending-headers-timer-sibling', 'partial-body-independent-queues', 'root-return-drain',
         'root-exception-drain', 'pending-cancellation', 'pending-root-deadline', 'pending-fuel-trap')
EXPECTED = {0: '1:headers:200:1:1:200:root:child', 1: '1:queues:1:4109:1',
            2: '1:root-return:0', 7: '1:fresh:200:0:0'}
FAILURES = {3: 'guest-trap', 4: 'cancelled', 5: 'deadline-exceeded', 6: 'resource-exhausted'}


def configuration(directory, releases, peer, credential):
    startup = {'destinations': peer.provider_destinations()}
    path = http_configuration(directory, releases, startup, credential)
    value = read_json(path)
    value['providers']['activationRuntime'] = {
        'identity': {'id': 'activation', 'tenant': 'examples', 'service': 'activation-host', 'epoch': 1},
        'limits': {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
                   'timers': 8, 'results': 8, 'nativeOwners': 8}}
    value['providers']['bindings'].append({'name': 'activation-standard', 'tenant': 'examples',
        'consumerService': SERVICE, 'providerService': 'activation-host', 'contract': ACTIVATION,
        'providerBinding': 'activation-installed'})
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    return path


def grants(client, node, publication, origin):
    clocks, authorized = http_grants(client, node, publication, origin)
    descriptor = next(row for row in node.startup_record['providers'] if row['id'] == 'activation')
    require(descriptor['capability'] == ACTIVATION, 'java-http-fiber-activation-provider')
    policy(client, 'provider-binding', 'activation-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': ACTIVATION, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': OPS}})
    policy(client, 'policy', 'activation-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'owned-java-fibers', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [SERVICE], 'publications': [publication], 'capability': ACTIVATION,
        'operations': OPS, 'resources': {'kind': 'clock'},
        'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
    return clocks, authorized, authorized + [{'capability': ACTIVATION, 'policy': 'activation-allow'}]


def narrowed_target(target, mode):
    require(type(mode) is int and 0 <= mode <= 7, 'java-http-fiber-unknown-case')
    value = copy.deepcopy(target)
    if mode == 5:
        require(value['budget']['wallTimeLimitMillis'] >= 3000, 'java-http-fiber-wall-budget')
        value['budget']['wallTimeLimitMillis'] = 3000
    if mode == 6:
        require(value['budget']['cpuFuel'] >= 100_000_000, 'java-http-fiber-fuel-budget')
        value['budget']['cpuFuel'] = 100_000_000
    return value


def ready_sibling(observation, offset, gate=None):
    if gate is None:
        return False
    rows = observation['requests'][offset:]
    ready = {row['request'] for row in rows if row.get('role') == 'primary'
             and row.get('vector') == 'domain-json' and row.get('closeReason') == 'response-write-complete'}
    events = observation['events']
    held = [row['sequence'] for row in events if row.get('kind') == 'gate-pending'
            and row.get('request') == gate.request and row.get('phase') == gate.phase]
    return len(held) == 1 and any(row.get('kind') == 'response-write-complete'
        and row.get('request') in ready and row['sequence'] > held[0] for row in events)


def validate_result(row, mode, selected):
    response = row['response']
    require(row['processReaped'] is True and response['outcomeKnown'] is True,
            'java-http-fiber-unknown-or-unreaped')
    data = response['data']
    require(data.get('resolvedRevision') == selected,
            'java-http-fiber-signed-revision')
    if mode in EXPECTED:
        require(row['exitCode'] == 0 and row['decoded'] == [EXPECTED[mode]],
                'java-http-fiber-ordinary-result')
    else:
        code = FAILURES[mode]
        require(row['exitCode'] == 4 and response['category'] == 'platform-failure'
                and response['error']['code'] == code
                and data['terminalState'] == code.replace('-', '_'), 'java-http-fiber-terminal-result')


def validate_observed_result(row, mode, selected, peer, client, offset,
                             gate, active, released, cancelled):
    """Retain this public fixture's pending evidence before an assertion escapes."""
    try:
        validate_result(row, mode, selected)
    except BaseException:
        try:
            value = {'schemaVersion': 'latent.java.http-fiber-failure-observation.v1',
                'qualification': False, 'mode': mode, 'invocation': row,
                'requestOffset': offset, 'pendingOwner': active,
                'gate': None if gate is None else {'request': gate.request, 'phase': gate.phase},
                'releasedOnce': released, 'cancel': cancelled, 'peer': peer.observation()}
            if len(json.dumps(value, allow_nan=False).encode('utf-8')) > 1024 * 1024:
                value = {'schemaVersion': 'latent.java.http-fiber-failure-observation.v1',
                    'qualification': False, 'status': 'unavailable', 'refusal': 'bound'}
            write_json(client.evidence / 'invocation-failure.json', value)
        except Exception:
            pass
        raise


def invoke(client, node, target, peer, probe, mode, name):
    """One invocation and at most one release/cancel; no operation replay."""
    chosen = narrowed_target(target, mode)
    selected = selected_revision(client, target)
    origin = peer.origin()
    endpoint = f"http://{origin['host']}:{origin['port']}"
    offset = len(peer.observation()['requests'])
    process = start_call(client, chosen, 'java-standard-http', 'run', [mode, endpoint], name)
    gate = active = cancelled = None
    released = False
    try:
        deadline = min(client.deadline, time.monotonic() + 125)
        while not process.owner.exited():
            require(time.monotonic() < deadline, 'java-http-fiber-invocation-deadline')
            process.drain()
            node.drain()
            peer.poll(.005)
            observed = peer.observation()
            require(observed['failure'] is None, 'java-http-fiber-peer-failed')
            gates = [item for item in peer.gates() if item.request > offset]
            require(len(gates) <= 1, 'java-http-fiber-ambiguous-pending-request')
            if gates and gate is None:
                gate = gates[0]
                require(gate.phase == ('body' if mode == 1 else 'headers'),
                        'java-http-fiber-wrong-pending-phase')
                active = sample(client, probe, 'held-' + name, 1, active=True)
            if gate is not None and mode in (0, 1, 2, 3) and not released:
                if mode in (2, 3) or ready_sibling(observed, offset, gate):
                    require(gate in peer.gates() and not process.owner.exited(),
                            'java-http-fiber-finalized-with-accepted-work')
                    peer.release(gate)
                    released = True
            if gate is not None and mode == 4 and cancelled is None:
                # Fence before dispatch: an uncertain cancellation is never retried.
                cancelled = {'attempted': True}
                value = client.call('activation', 'cancel', name, '--reason', 'Owned pending Java HTTP control')
                require(value['outcomeKnown'] and value['data']['activationId'] == name
                        and value['data']['disposition'] == 'accepted', 'java-http-fiber-cancel-unconfirmed')
                cancelled['receipt'] = value
        row = finish_call(client, process)
    finally:
        process.close()
    validate_observed_result(row, mode, selected, peer, client, offset,
                             gate, active, released, cancelled)
    if mode != 7:
        require(gate is not None and active is not None, 'java-http-fiber-no-actual-pending-witness')
    if mode in (0, 1):
        require(released, 'java-http-fiber-no-sibling-before-release')
    if mode == 4:
        require(cancelled is not None and 'receipt' in cancelled, 'java-http-fiber-no-cancel-receipt')
    if mode == 6:
        require(int(row['response']['data']['consumption']['cpuFuel']) == chosen['budget']['cpuFuel'],
                'java-http-fiber-fuel-not-exhausted')
        require(int(row['response']['data']['consumption']['wallTimeMicros']) < 5_000_000,
                'java-http-fiber-fuel-after-provider-timeout')
    # Pump the peer's observed FINs before retaining its post-operation state.
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0:
            break
    require(peer.observation()['openConnections'] == 0, 'java-http-fiber-peer-connection-retained')
    retired = sample(client, probe, 'after-' + name, 1)
    usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']['nodeUsage']
    require(not usage['unavailable'] and all(key in usage['counters'] and int(usage['counters'][key]) == 0
            for key in ACTIVE_COUNTERS), 'java-http-fiber-provider-not-physically-retired')
    result = {'case': name, 'mode': mode, 'invocation': row, 'pendingOwner': active,
        'releasedOnce': released, 'cancel': cancelled, 'retired': retired, 'providerUsage': usage,
        'peer': peer.observation(), 'selectedRevision': selected, 'budget': chosen['budget']}
    write_json(client.evidence / (name + '-lifecycle.json'), result)
    return result


def closed_diagnostic(row):
    """Decode only the fixture's closed numeric observation, never error text."""
    import re
    if type(row) is not dict:
        return {'status': 'unavailable'}
    decoded = row.get('decoded')
    if (type(row.get('exitCode')) is not int or row['exitCode'] != 0 or row.get('processReaped') is not True
            or type(decoded) is not list or len(decoded) != 1 or type(decoded[0]) is not str):
        return {'status': 'unavailable'}
    match = re.fullmatch(r'1:diagnostic:([1-7]):([0-9]{1,3}):([0-9]{1,3}):([01]):([01]):([01]):([0-9]{1,3}):([0-9]{1,3})', decoded[0])
    if match is None:
        return {'status': 'unavailable'}
    phase, root, child, timer, entered, completed, sibling, child_status = map(int, match.groups())
    codes = {0, *range(100, 116), 199, 200}
    if root not in codes or child not in codes or sibling not in {0, 200} or child_status not in {0, 200}:
        return {'status': 'unavailable'}
    return {'status': 'observed', 'phase': phase, 'rootError': root, 'childError': child,
        'timerFired': bool(timer), 'childEntered': bool(entered), 'childCompleted': bool(completed),
        'siblingStatus': sibling, 'childStatus': child_status}


def diagnose_pending(client, node, target, peer, probe):
    """Additional caught observation; no lifecycle assertion is replaced."""
    selected = selected_revision(client, target)
    offset = len(peer.observation()['requests'])
    origin = peer.origin()
    process = start_call(client, narrowed_target(target, 0), 'java-standard-http', 'run',
        [8, f"http://{origin['host']}:{origin['port']}"], 'pending-closed-diagnostic')
    gate, released = None, False
    try:
        deadline = min(client.deadline, time.monotonic() + 125)
        while not process.owner.exited():
            require(time.monotonic() < deadline, 'java-http-fiber-diagnostic-deadline')
            process.drain(); node.drain(); peer.poll(.005)
            observed = peer.observation()
            require(observed['failure'] is None, 'java-http-fiber-peer-failed')
            gates = [item for item in peer.gates() if item.request > offset]
            require(len(gates) <= 1, 'java-http-fiber-ambiguous-pending-request')
            if gates and gate is None: gate = gates[0]
            if gate is not None and not released and ready_sibling(observed, offset, gate):
                peer.release(gate); released = True
        row = finish_call(client, process)
    finally:
        process.close()
    require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
        and row['response']['data'].get('resolvedRevision') == selected,
        'java-http-fiber-diagnostic-original-owner')
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0: break
    observation = peer.observation()
    contacts = len(observation['requests']) - offset
    require(contacts in {1, 2} and observation['openConnections'] == 0,
        'java-http-fiber-diagnostic-contact-or-retirement')
    value = {'schemaVersion': 'latent.java.http-fiber-caught-observation.v1', 'qualification': False,
        'result': closed_diagnostic(row), 'contacts': contacts, 'releasedOnce': released,
        'selectedRevision': selected, 'retired': sample(client, probe, 'after-diagnostic', 1),
        'peer': observation}
    write_json(client.evidence / 'pending-closed-diagnostic-observation.json', value)
    return value


def run(artifact, binaries, output, *, deadline):
    require(time.monotonic() < deadline, 'java-http-fiber-original-deadline-expired')
    output = fresh(output)
    before = {name: file_identity(path) for name, path in binaries.items()}
    result = {'schemaVersion': 'latent.java.http-fiber-lifecycle.v1', 'status': 'in-progress',
        'binaries': before, 'cases': [], 'scope': 'finite-ordinary-http-and-fiber-io-lifecycle',
        'full688Qualified': False, 'full741Qualified': False}
    node = peer = None
    stage = 'sign'
    try:
        signed = output / 'releases'
        completed = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'java-http-fiber-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-java-http-fibers-') as private, owned_cancellation() as cancellation:
            work = Path(private)
            for name in ('client', 'node', 'peer'):
                (work/name).mkdir(mode=0o700)
            token = ('Bearer ' + secrets.token_hex(32)).encode('ascii')
            credential = work/'peer/authorization'
            credential.write_bytes(token)
            credential.chmod(0o600)
            peer = Peer(token, maximum_seconds=300)
            client = RecordingClient(binaries['latent'], work/'client', cancellation,
                min(deadline, time.monotonic()+280), evidence=output/'controls', invocation_timeout_millis=120000)
            config = configuration(work/'node', signed, peer, credential)
            stage = 'node'
            node = connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            probe = Probe(node, before['latentd'])
            source = signed/'java-standard-http'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'http-fiber-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            _clocks, without_activation, authorized = grants(client, node, publication, peer.origin())
            target = deploy(client, source/'deployment.json', publication,
                            generation=str(target['generation']), grants=without_activation)
            # The selected profile imports activation operations even for fresh GET.
            stage = 'activation-denial'
            origin = peer.origin()
            endpoint = f"http://{origin['host']}:{origin['port']}"
            denied = start_call(client, target, 'java-standard-http', 'run', [7, endpoint], 'fiber-grant-denied')
            denied_row = finish_call(client, denied)
            require(denied_row['exitCode'] == 4 and denied_row['response']['error']['code'] == 'permission-denied'
                    and denied_row['response']['data']['consumption']['cpuFuel'] == '0'
                    and peer.observation()['startedRequests'] == 0, 'java-http-fiber-authority-bypass')
            result['activationDenial'] = denied_row
            target = deploy(client, source/'deployment.json', publication,
                            generation=str(target['generation']), grants=authorized)
            stage = 'fresh-preflight'
            result['preflight'] = invoke(client, node, target, peer, probe, 7, stage)
            stage = 'pending-closed-diagnostic'
            result['diagnostic'] = diagnose_pending(client, node, target, peer, probe)
            for mode, name in enumerate(CASES):
                stage = name
                result['cases'].append(invoke(client, node, target, peer, probe, mode, name))
                if mode in FAILURES:
                    result['cases'].append(invoke(client, node, target, peer, probe, 7, name+'-fresh'))
            delete_all(client, [target['name']])
            stop(client, node)
            result['shutdown'] = stopped_record(node)
            require(result['shutdown']['reaped'] and result['shutdown']['record']['clean'],
                    'java-http-fiber-unclean-node-shutdown')
            node = None
            result['peer'] = peer.close()
            validate_peer(result['peer'])
            require(result['peer']['startedRequests'] - result['diagnostic']['contacts'] == 14
                    and result['peer']['rejectedRequests'] == 0
                    and result['peer']['committedMutations'] == 0
                    and all(row['role'] == 'primary' for row in result['peer']['requests']),
                    'java-http-fiber-peer-contact-or-replay')
            require(before == {name: file_identity(path) for name, path in binaries.items()},
                    'java-http-fiber-native-product-mutated')
            result['status'] = 'passed'
            write_json(output/'qualification.json', result)
            return result
    except BaseException:
        try:
            result.update(status='failed', stage=stage)
            write_json(output/'FAILED.json', result)
        except Exception:
            pass
        raise
    finally:
        # Preserve an original assertion if cleanup itself also reports failure.
        import sys
        original = sys.exc_info()[0] is not None
        for owned in (node, peer):
            if owned is not None:
                try:
                    owned.close()
                except Exception:
                    if not original:
                        raise
