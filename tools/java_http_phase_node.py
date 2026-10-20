"""Finite signed V7 ordinary-client and operation-deadline programme."""
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
from tools.guest_runtime_profiles import profiles
from tools.java_http_fiber_node import configuration as fiber_configuration, ACTIVATION, OPS
from tools.java_http_phase_fixture import CASES, ConnectBacklog
from tools.java_standard_http_node import SERVICE
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
from tools.standard_http.vectors import DOMAIN, json_bytes
from tools.static_api.node import policy

CAPABILITY = 'latent:http/phase-timing@0.4.0'
PROFILE = 'bounded-streaming-http-phase-timing-v1'
TERMINAL = {4: 'deadline-exceeded', 5: 'cancelled', 8: 'deadline-exceeded', 9: 'cancelled'}
FRESH_AFTER = {4, 5, 7, 8, 9}


def configuration(directory, releases, peer, credential, backlogs):
    path = fiber_configuration(directory, releases, peer, credential)
    value = read_json(path)
    provider = value['providers']['httpStreaming']
    provider['phaseTiming'] = True
    for backlog in backlogs:
        provider['configuration']['destinations'].append({
            'origin': backlog.origin(),
            'addresses': {'networks': ['127.0.0.1/32'], 'specialAddresses': ['127.0.0.1']},
            'resolution': {'kind': 'static', 'addresses': ['127.0.0.1']},
            'allowedRequestHeaders': ['accept', 'user-agent', 'x-conformance'],
            'redirectDestinations': []})
    selected = [row for row in value['providers']['bindings']
                if row['contract'] == 'latent:http/streaming@0.3.0']
    require(len(selected) == 1, 'java-phase-original-http-binding')
    selected[0]['contract'] = CAPABILITY
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return path


def grants(client, node, publication, origins):
    runtime = []
    for name, (capability, profile, operation, kind) in profiles('java').items():
        descriptor = next(row for row in node.startup_record['providers'] if row['id'] == name)
        require(descriptor['capability'] == capability and descriptor['profile'] == profile,
                'java-phase-runtime-provider')
        policy(client, 'provider-binding', name+'-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': [operation]}})
        policy(client, 'policy', name+'-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [SERVICE], 'publications': [publication], 'capability': capability,
            'operations': [operation], 'resources': {'kind': kind},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        runtime.append({'capability': capability, 'policy': name+'-allow'})
    activation = next(row for row in node.startup_record['providers'] if row['id'] == 'activation')
    require(activation['capability'] == ACTIVATION, 'java-phase-activation-provider')
    policy(client, 'provider-binding', 'activation-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': ACTIVATION, 'providerProfile': activation['profile'],
        'configurationDigest': activation['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': OPS}})
    policy(client, 'policy', 'activation-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'owned-java-fibers', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [SERVICE], 'publications': [publication], 'capability': ACTIVATION,
        'operations': OPS, 'resources': {'kind': 'clock'},
        'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
    runtime.append({'capability': ACTIVATION, 'policy': 'activation-allow'})
    descriptor = next(row for row in node.startup_record['providers'] if row['capability'] == CAPABILITY)
    require(descriptor['profile'] == PROFILE, 'java-phase-http-provider-profile')
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': CAPABILITY, 'providerProfile': PROFILE,
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'ordinary-http', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [SERVICE], 'publications': [publication], 'capability': CAPABILITY,
        'operations': ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body'],
        'resources': {'kind': 'http', 'origins': origins, 'methods': ['GET', 'POST'], 'paths': [],
            'pathPrefixes': ['/conformance/']},
        'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}}]})
    return runtime, runtime+[{'capability': CAPABILITY, 'policy': 'http-allow'}]


def expected(mode):
    if mode == 0: return '1:default-webb:200:Fixture:7'
    if mode == 10: return '1:default-http-request:200:7'
    if mode in (1, 6): return f'1:explicit:200:Fixture:{len(json_bytes(DOMAIN))}:1000:1000'
    if mode == 2: return '1:read-timeout:headers:true'
    if mode == 3: return '1:read-timeout:body:false'
    if mode == 7: return '1:connect-timeout:false'
    require(mode in TERMINAL, 'java-phase-unknown-result-mode')
    return None


def validate_result(row, mode, selected):
    require(type(mode) is int and 0 <= mode < len(CASES), 'java-phase-unknown-mode')
    response = row['response']
    require(row['processReaped'] is True and response['outcomeKnown'] is True
        and response['data'].get('resolvedRevision') == selected, 'java-phase-result-owner')
    if mode in TERMINAL:
        code = TERMINAL[mode]
        require(row['exitCode'] == 4 and response['category'] == 'platform-failure'
            and response['error']['code'] == code and response['data']['terminalState'] == code.replace('-', '_'),
            'java-phase-root-must-not-be-socket-timeout')
    else:
        require(row['exitCode'] == 0 and row['decoded'] == [expected(mode)], 'java-phase-ordinary-result')
    require(int(response['data']['consumption']['outboundRequests']) == 1,
            'java-phase-one-outbound-request')


def usage(client, target):
    value = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']['nodeUsage']
    require(not value['unavailable'] and all(key in value['counters'] for key in ACTIVE_COUNTERS),
            'java-phase-physical-usage-unavailable')
    return value


def invoke(client, node, target, peer, probe, backlogs, mode, name):
    chosen = copy.deepcopy(target)
    if mode in (4, 8):
        require(chosen['budget']['wallTimeLimitMillis'] >= 3000, 'java-phase-original-wall-ceiling')
        chosen['budget']['wallTimeLimitMillis'] = 3000
    origin = backlogs[mode-7].origin() if mode in (7, 8, 9) else peer.origin()
    endpoint = f"http://{origin['host']}:{origin['port']}"
    selected = selected_revision(client, target)
    offset = len(peer.observation()['requests'])
    process = start_call(client, chosen, 'java-standard-http', 'run', [mode, endpoint], name)
    pending = gate = cancelled = None
    observations, next_observation = [], 0.
    try:
        expires = min(client.deadline, time.monotonic()+125)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'java-phase-invocation-deadline')
            process.drain();node.drain();peer.poll(.005)
            require(peer.observation()['failure'] is None, 'java-phase-peer-failed')
            gates = [row for row in peer.gates() if row.request > offset]
            require(len(gates) <= 1, 'java-phase-ambiguous-gate')
            if gates and gate is None:
                gate = gates[0]
                require(mode in (2, 3, 4, 5) and gate.phase == ('body' if mode == 3 else 'headers'),
                        'java-phase-wrong-pending-phase')
                pending = {'kind': 'peer-gate', 'request': gate.request, 'phase': gate.phase}
            if (mode in (7, 8, 9) and pending is None and len(observations) < 16
                    and time.monotonic() >= next_observation):
                observed = usage(client, target)
                observations.append(observed)
                next_observation = time.monotonic()+.1
                if int(observed['counters']['pool_connecting_connections']) == 1:
                    pending = {'kind': 'actual-pool-connecting', 'usage': observed,
                        'owner': sample(client, probe, 'pending-'+name, 1, active=True)}
            if mode in (5, 9) and pending is not None and cancelled is None:
                cancelled = {'attempted': True}
                value = client.call('activation', 'cancel', name, '--reason', 'Owned Java phase control')
                require(value['outcomeKnown'] and value['data']['activationId'] == name
                    and value['data']['disposition'] == 'accepted', 'java-phase-cancel-unconfirmed')
                cancelled['receipt'] = value
        row = finish_call(client, process)
    finally:
        process.close()
    # Preserve every actual response before classifying it or querying cleanup.
    write_json(client.evidence/(name+'-result.json'), row)
    validate_result(row, mode, selected)
    if mode in (2, 3, 4, 5, 7, 8, 9):
        require(pending is not None, 'java-phase-no-real-pending-witness')
    if mode in (5, 9):
        require(cancelled is not None and 'receipt' in cancelled, 'java-phase-no-cancel-receipt')
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0: break
    observed = peer.observation()
    require(observed['openConnections'] == 0
        and len(observed['requests'])-offset == (0 if mode in (7, 8, 9) else 1),
        'java-phase-contact-or-close')
    retired = sample(client, probe, 'after-'+name, 1)
    physical = usage(client, target)
    require(all(int(physical['counters'][key]) == 0 for key in ACTIVE_COUNTERS),
            'java-phase-physical-owner-retained')
    result = {'case': name, 'mode': mode, 'invocation': row, 'selectedRevision': selected,
        'pending': pending, 'cancel': cancelled, 'retired': retired,
        'connectingObservations': observations,
        'providerUsage': physical, 'peer': observed, 'budget': chosen['budget']}
    path = client.evidence/(name+'-phase.json');write_json(path, result)
    return {'case': name, 'mode': mode, 'selectedRevision': selected,
            'receipt': {'path': 'controls/'+path.name, **file_identity(path, 262144)}}


def run(artifact, binaries, output, *, deadline):
    output = fresh(output)
    before = {name: file_identity(path) for name, path in binaries.items()}
    result = {'schemaVersion': 'latent.java.http-phase-node.v1', 'status': 'in-progress',
        'nativeProducts': before, 'cases': [], 'full688Qualified': False, 'full741Qualified': False}
    node = peer = None
    backlogs = []
    stage = 'sign'
    try:
        signed = output/'releases'
        completed = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'java-phase-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-java-http-phases-') as private, owned_cancellation() as cancellation:
            work = Path(private)
            for name in ('client', 'node', 'peer'): (work/name).mkdir(mode=0o700)
            token = ('Bearer '+secrets.token_hex(32)).encode('ascii')
            credential = work/'peer/authorization';credential.write_bytes(token);credential.chmod(0o600)
            peer = Peer(token, maximum_seconds=300)
            for _ in range(3): backlogs.append(ConnectBacklog())
            client = RecordingClient(binaries['latent'], work/'client', cancellation,
                min(deadline, time.monotonic()+280), evidence=output/'controls', invocation_timeout_millis=120000)
            config = configuration(work/'node', signed, peer, credential, backlogs)
            stage = 'node'
            node = connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            probe = Probe(node, before['latentd'])
            source = signed/'java-standard-http'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'http-phase-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            origins = [peer.origin()]+[backlog.origin() for backlog in backlogs]
            runtime, authorized = grants(client, node, publication, origins)
            for allowed, name in (([], 'runtime-denied'), (runtime, 'phase-denied')):
                stage = name
                target = deploy(client, source/'deployment.json', publication,
                    generation=str(target['generation']), grants=allowed)
                origin = peer.origin();endpoint = f"http://{origin['host']}:{origin['port']}"
                call = start_call(client, target, 'java-standard-http', 'run', [6, endpoint], name)
                denied = finish_call(client, call)
                require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                    and denied['response']['data']['consumption']['cpuFuel'] == '0'
                    and peer.observation()['startedRequests'] == 0, 'java-phase-authority-bypass')
            target = deploy(client, source/'deployment.json', publication,
                generation=str(target['generation']), grants=authorized)
            for mode, name in enumerate(CASES):
                stage = name
                result['cases'].append(invoke(client, node, target, peer, probe, backlogs, mode, name))
                if mode in FRESH_AFTER:
                    result['cases'].append(invoke(client, node, target, peer, probe, backlogs, 6, name+'-fresh'))
            require(len(result['cases']) == 16, 'java-phase-incomplete-cases')
            delete_all(client, [target['name']]);stop(client, node)
            shutdown = stopped_record(node)
            write_json(client.evidence/'node-stopped.json', shutdown)
            require(shutdown['reaped'] and shutdown['record']['clean'], 'java-phase-unclean-shutdown')
            node = None
            observed = peer.close();peer = None
            write_json(client.evidence/'final-peer.json', observed)
            validate_peer(observed)
            require(observed['startedRequests'] == 13 and observed['rejectedRequests'] == 0
                and observed['committedMutations'] == 0
                and all(row['role'] == 'primary' for row in observed['requests']), 'java-phase-contact-count')
            for backlog in backlogs: backlog.close()
            write_json(client.evidence/'connect-fixtures-stopped.json', {'fixtures': 3, 'closed': True})
            require(before == {name: file_identity(path) for name, path in binaries.items()},
                    'java-phase-native-product-mutated')
            write_json(client.evidence/'native-products-final.json', {'before': before, 'after': before})
            result.update(status='passed', invocations=16, authorityDenials=2, httpContacts=13,
                shutdown={'path': 'controls/node-stopped.json', **file_identity(client.evidence/'node-stopped.json')},
                peer={'path': 'controls/final-peer.json', **file_identity(client.evidence/'final-peer.json')})
            write_json(output/'qualification.json', result)
            return result
    except BaseException:
        try:
            write_json(output/'FAILED.json', {**result, 'status': 'failed', 'stage': stage})
        except Exception:
            pass
        raise
    finally:
        import sys
        original = sys.exc_info()[0] is not None
        cleanup_failure = None
        for owned in (node, peer, *backlogs):
            if owned is not None:
                try: owned.close()
                except Exception as failure:
                    cleanup_failure = cleanup_failure or failure
        if not original and cleanup_failure is not None:
            raise cleanup_failure
