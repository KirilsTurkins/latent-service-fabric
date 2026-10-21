"""Real managed content ownership and accepted work on the default HTTP profile."""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import dotnet_standard_http_node as base
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.dotnet_http_mixed_fixture import CASES
from tools.java_http_mixed_node import retain_partial
from tools.java_http_release_preparation import prepare
from tools.java_http_tenant_node import cleanup_owner
from tools.resource_tenant_node import SUBJECTS
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import (RecordingClient, deploy, delete_all, sample,
    start_call, finish_call, selected_revision)
from tools.rust_capsule_project import fresh, read_json, write_json
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer
from tools.static_api.node import policy
from tools.qualify_sdk_scratch import package_identity

TEMPLATE = 'dotnet-standard-http'
EXPECTED = (
    'options:15:validation:3', 'views:57:same:eof:closed', 'borrowed:57:open',
    'headers:4109:pending:context:isolated', 'content:4109:pending:context:isolated',
    'stream-content:4096:owned:1', 'producer:4096:pending:sibling:finished',
    'length-mismatch:transport-error', 'request-limit:transport-error',
    'body-cancel:5:token:sibling', 'response-dispose:5:closed', 'root-return:accepted',
    None, 'late:cancelled:4109:not-overwritten', 'reserved-header:transport-error',
    'redirect:302:unfollowed', 'fresh:200:0', 'denied', None, None, None)
CONTACTS = (0, 1, 1, 3, 3, 1, 2, 2, 0, 2, 1, 1, 1, 2, 0, 1, 1, 0, 1, 1, 1)
HELPER_MODES = frozenset((3, 4, 6, 7))
GATED_MODES = frozenset((3, 4, 6, 9, 10, 11, 12, 13, 18, 19))
RELEASE_MODES = frozenset((3, 4, 6, 13))
LIVE_MODES = RELEASE_MODES | frozenset((18, 19))
TERMINAL = {12: 'guest-trap', 18: 'cancelled', 19: 'deadline-exceeded'}
ARTIFACTS = ('component.wasm', 'BUILD-COMPLETE.json', 'source-inputs.json',
    'recipe-inputs.json', 'compiler-inputs.json', 'build-observation.json',
    'runtime-profile.json', 'http-error-port.json', 'task-wait-port.json',
    'capsule.json', 'package-inputs.json')


def identities(artifact):
    value = {name: file_identity(artifact/name, 64*1024**2 if name == 'component.wasm' else 16*1024**2)
        for name in ARTIFACTS}
    value['package'] = package_identity(artifact, read_json(artifact/'BUILD-COMPLETE.json'))
    return value


def configuration(directory, releases, peers, credentials):
    startup = {'origins': peers['main'].observation()['origins'],
        'destinations': peers['main'].provider_destinations()+peers['helper'].provider_destinations()[:1]}
    path = base.configuration(directory, releases, startup, credentials['main'])
    value = read_json(path)
    provider = value['providers']['httpStreaming']
    require(provider['credentials'] == [{'reference': 'standard-peer', 'file': credentials['main'].name,
        'destination': 0, 'header': 'authorization'}], 'managed-mixed-original-credential-scope')
    require(credentials['main'].parent == credentials['helper'].parent,
        'managed-mixed-owned-credential-directory')
    provider['credentials'].append({'reference': 'sibling-peer', 'file': credentials['helper'].name,
        'destination': 2, 'header': 'authorization'})
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf8')
    return path


def grants(client, node, publication, origins, *, tenant='examples', service=base.SERVICE):
    require(len(origins) == 2 and origins[0] != origins[1], 'managed-mixed-independent-origins')
    require(tenant in ('examples', 'foreign'), 'managed-mixed-exact-tenant')
    runtime = []
    profiles = [(name, capability, profile, [operation], {'kind': kind}, {
        'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000})
        for name, (capability, profile, operation, kind) in base.CLOCKS.items()]
    profiles += [
        ('activation', base.ACTIVATION, None, base.OPS, {'kind': 'clock'}, {
            'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}),
        ('noncrypto-random', 'latent:random/random@0.1.0', 'system-random-v1', ['bytes'], {'kind': 'random'}, {
            'operations': 16, 'inputBytes': 8, 'outputBytes': 4096, 'wallTimeMillis': 5000})]
    for name, capability, profile, operations, resources, ceiling in profiles:
        provider_id = name if tenant == 'examples' else name+'-foreign'
        descriptor, = [row for row in node.startup_record['providers'] if row['id'] == provider_id]
        expected_service = ('activation-host' if name == 'activation' else 'entropy-host' if name == 'noncrypto-random' else 'runtime-host') \
            if tenant == 'examples' else ('foreign-activation' if name == 'activation' else 'foreign-entropy' if name == 'noncrypto-random' else 'foreign-runtime')
        require(descriptor['tenant'] == tenant and descriptor['capability'] == capability
            and descriptor['service'] == expected_service and descriptor['configurationEpoch'] == '1'
            and (profile is None or descriptor['profile'] == profile),
            'managed-mixed-original-runtime-provider')
        policy(client, 'provider-binding', name+'-installed', {'formatVersion': 1, 'tenant': tenant,
            'capability': capability, 'providerProfile': descriptor['profile'],
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': operations}})
        policy(client, 'policy', name+'-allow', {'formatVersion': 1, 'tenant': tenant, 'rules': [{
            'id': 'runtime', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': SUBJECTS[tenant]}],
            'services': [service], 'publications': [publication], 'capability': capability,
            'operations': operations, 'resources': resources, 'ceiling': ceiling}]})
        runtime.append({'capability': capability, 'policy': name+'-allow'})
    provider_id = 'http-standard' if tenant == 'examples' else 'http-standard-foreign'
    descriptor, = [row for row in node.startup_record['providers'] if row['id'] == provider_id]
    require(descriptor['profile'] == 'bounded-streaming-http-identity-v1', 'managed-mixed-default-http-profile')
    require(descriptor['tenant'] == tenant and descriptor['capability'] == base.CAPABILITY,
        'managed-mixed-http-installation-tenant')
    require(descriptor['service'] == ('http-host' if tenant == 'examples' else 'foreign-http')
        and descriptor['configurationEpoch'] == '1', 'managed-mixed-http-installation-service-and-epoch')
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': tenant,
        'capability': base.CAPABILITY, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': tenant, 'rules': [{
        'id': 'ordinary-http', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': SUBJECTS[tenant]}],
        'services': [service], 'publications': [publication], 'capability': base.CAPABILITY,
        'operations': ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body'],
        'resources': {'kind': 'http', 'origins': origins, 'methods': ['GET', 'POST'], 'paths': [],
            'pathPrefixes': ['/conformance/']},
        'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}}]})
    return runtime, [*runtime, {'capability': base.CAPABILITY, 'policy': 'http-allow'}]


def usage(client, target):
    value = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']['nodeUsage']
    require(type(value) is dict and value.get('scope') == 'node'
        and type(value.get('unavailable')) is list and value['unavailable'] == []
        and type(value.get('counters')) is dict and all(name in value['counters'] for name in ACTIVE_COUNTERS),
        'managed-mixed-physical-usage-unavailable')
    for name in ACTIVE_COUNTERS:natural(value['counters'][name])
    return value


def endpoint(peer):
    origin = peer.origin()
    return f"http://{origin['host']}:{origin['port']}"


def helper_finished(value, offset):
    return any(row.get('vector') == 'domain-json' and row.get('closeReason') == 'response-write-complete'
        for row in value['requests'][offset:])


def sibling_marker(value, offset, mode):
    require(mode in (3, 4), 'managed-mixed-sibling-marker-mode')
    marker = b'managed-sibling-'+(b'content' if mode == 4 else b'headers')
    return helper_finished(value, offset) and any(row.get('vector') == 'method-bytes'
        and row.get('method') == 'POST' and row.get('bodyBytes') == len(marker)
        and row.get('bodySha256') == 'sha256:'+hashlib.sha256(marker).hexdigest()
        and row.get('closeReason') == 'response-write-complete' for row in value['requests'][offset:])


def helper_contacts(mode):
    return 2 if mode in (3, 4) else 1 if mode in HELPER_MODES else 0


def late_marker(value, offset, gate):
    marker = b'managed-task-cancelled'
    pending, = [row['sequence'] for row in value['events'] if row['kind'] == 'gate-pending'
        and row['request'] == gate.request and row['phase'] == 'body']
    completed = {row['request'] for row in value['requests'][offset:]
        if row.get('vector') == 'method-bytes' and row.get('method') == 'POST'
        and row.get('bodyBytes') == len(marker)
        and row.get('bodySha256') == 'sha256:'+hashlib.sha256(marker).hexdigest()
        and row.get('closeReason') == 'response-write-complete'}
    return any(row['kind'] == 'response-write-complete' and row['request'] in completed
        and row['sequence'] > pending for row in value['events'])


def natural(value):
    require((type(value) is int and 0 <= value < 2**64) or
        (type(value) is str and 0 < len(value) <= 20 and value.isascii() and value.isdecimal()
            and str(int(value)) == value and int(value) < 2**64), 'managed-mixed-canonical-count')
    return int(value)


def checked(row, mode, revision, budget, *, nonce=None):
    require(type(mode) is int and 0 <= mode < len(EXPECTED), 'managed-mixed-unknown-mode')
    response = row['response']
    require(row['processReaped'] is True and response['outcomeKnown'] is True
        and response['data'].get('resolvedRevision') == revision, 'managed-mixed-signed-result-owner')
    if mode in TERMINAL:
        require(row['exitCode'] == 4 and response['category'] == 'platform-failure'
            and response['error']['code'] == TERMINAL[mode], 'managed-mixed-root-terminal')
    else:
        if mode == 20:
            require(nonce in ('tenant-examples', 'tenant-foreign'), 'managed-mixed-exact-tenant-nonce')
            expected = 'fresh-tenant:'+nonce+':200:0'
        else:expected = EXPECTED[mode]
        if mode in (3, 4):
            require(type(row['decoded']) is list and len(row['decoded']) == 1
                and type(row['decoded'][0]) is str, 'managed-mixed-thread-local-result-shape')
            parts = row['decoded'][0].split(':')
            require(len(parts) == 11 and parts[:7] == ('1:'+expected+':thread-local').split(':')
                and all(0 < natural(value) < 2**31 for value in parts[7:]), 'managed-mixed-thread-local-thread-identities')
            require(row['exitCode'] == 0, 'managed-mixed-default-result')
        else:require(row['exitCode'] == 0 and row['decoded'] == ['1:'+expected], 'managed-mixed-default-result')
    used = response['data']['consumption']
    require(natural(used['outboundRequests']) == CONTACTS[mode]
        and 0 < natural(used['cpuFuel']) <= natural(budget['cpuFuel']) <= 1000000000
        and 0 < natural(used['peakMemoryBytes']) <= natural(budget['memoryBytes']) <= 134217728,
        'managed-mixed-original-budget-and-no-replay')


def invoke(client, node, target, peers, probe, mode, label, *, population=1, nonce=None, denied_peer=None, extra_peers=()):
    revision = selected_revision(client, target)
    selected = copy.deepcopy(target)
    if mode == 19:
        require(selected['budget']['wallTimeLimitMillis'] >= 3000, 'managed-mixed-original-root-deadline')
        selected['budget']['wallTimeLimitMillis'] = 3000
    main, helper = peers['main'], peers['helper']
    offsets = {name: len(peer.observation()['requests']) for name, peer in peers.items()}
    url = endpoint(main)
    if mode == 17:
        url = endpoint(denied_peer) if denied_peer is not None else endpoint(main).replace(
            str(main.origin()['port']), str(main.origin('secondary')['port']))
    argument = url+'|'+endpoint(helper)+(('|'+nonce) if nonce is not None else '')
    process = start_call(client, selected, TEMPLATE, 'run', [mode, argument], label)
    gate = pending = cancellation = None
    released = failed = False
    stage = 'waiting'
    try:
        expires = min(client.deadline, time.monotonic()+125)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'managed-mixed-invocation-deadline')
            process.drain();node.drain()
            for peer in (*peers.values(), *extra_peers):
                peer.poll(.005)
                require(peer.observation()['failure'] is None, 'managed-mixed-peer-failed')
            gates = [item for item in main.gates() if item.request > offsets['main']]
            require(len(gates) <= 1, 'managed-mixed-ambiguous-gate')
            if gates and gate is None:
                gate, = gates
                require(mode in GATED_MODES and gate.phase == ('upload' if mode == 6 else 'body'),
                    'managed-mixed-unexpected-gate')
                if mode in LIVE_MODES:
                    stage = 'pending-physical-owner'
                    pending = {'physical': sample(client, probe, 'pending-'+label, population, active=True),
                        'providerUsage': usage(client, target), 'peer': main.observation()}
                    require(int(pending['providerUsage']['counters']['broker_calls']) >= 1
                        and int(pending['providerUsage']['counters']['pool_running_requests']) >= 1,
                        'managed-mixed-premature-physical-refund')
                stage = 'waiting'
            if gate is not None and mode in RELEASE_MODES and not released:
                ready = (late_marker(main.observation(), offsets['main'], gate) if mode == 13
                    else sibling_marker(helper.observation(), offsets['helper'], mode) if mode in (3, 4)
                    else helper_finished(helper.observation(), offsets['helper']))
                if ready:
                    require(gate in main.gates() and not process.owner.exited(), 'managed-mixed-no-longer-pending')
                    peer_state = {'main': main.observation(), 'helper': helper.observation()}
                    write_json(client.evidence/(label+'-before-release.json'), peer_state)
                    main.release(gate);released = True
            if gate is not None and mode == 18 and cancellation is None:
                stage = 'root-cancellation';cancellation = {'attempted': True}
                result = client.call('activation', 'cancel', label, '--reason', 'Owned managed HTTP root cancellation')
                require(result['outcomeKnown'] is True and result['data']['activationId'] == label
                    and result['data']['disposition'] == 'accepted', 'managed-mixed-cancel-unconfirmed')
                cancellation['receipt'] = result;stage = 'waiting'
        stage = 'finish-result';row = finish_call(client, process)
    except BaseException:
        failed = True
        retain_partial(client, process, main, label, stage, gate, pending, cancellation, released)
        try:write_json(client.evidence/(label+'-helper-partial.json'), helper.observation())
        except BaseException:pass
        for index, peer in enumerate(extra_peers):
            try:
                value = peer.observation()
                require(len(json.dumps(value).encode()) <= 262144, 'managed-mixed-extra-peer-partial-bound')
                write_json(client.evidence/(label+'-extra-peer-'+str(index)+'-partial.json'), value)
            except BaseException:pass
        raise
    finally:
        try:process.close()
        except BaseException:
            try:write_json(client.evidence/(label+'-cleanup-refusal.json'), {'qualification': False, 'processCleanupConfirmed': False})
            except BaseException:pass
            if not failed:raise
    write_json(client.evidence/(label+'-result.json'), row)
    checked(row, mode, revision, selected['budget'], nonce=nonce)
    if mode in LIVE_MODES:require(gate is not None and pending is not None, 'managed-mixed-missing-real-pending')
    history = [event for event in main.observation()['events'] if event['kind'] == 'gate-pending'
        and event['request'] > offsets['main']]
    if mode in GATED_MODES:
        require(len(history) == 1 and history[0]['phase'] == ('upload' if mode == 6 else 'body'),
            'managed-mixed-missing-real-peer-gate-history')
    require(released == (mode in RELEASE_MODES), 'managed-mixed-gate-release-rule')
    if mode == 18:require(cancellation is not None and 'receipt' in cancellation, 'managed-mixed-missing-root-cancel')
    for _ in range(64):
        for peer in (*peers.values(), *extra_peers):peer.poll(.005)
        if all(peer.observation()['openConnections'] == 0 for peer in (*peers.values(), *extra_peers)):break
    observations = {name: peer.observation() for name, peer in peers.items()}
    for name, value in observations.items():
        validate_peer(value)
        contacts = helper_contacts(mode) if name == 'helper' else CONTACTS[mode]-helper_contacts(mode)
        require(value['openConnections'] == 0 and len(value['requests'])-offsets[name] == contacts,
            'managed-mixed-exact-contact-and-owner-retirement')
    physical = sample(client, probe, 'after-'+label, population)
    counters = usage(client, target)
    require(all(int(counters['counters'][name]) == 0 for name in ACTIVE_COUNTERS), 'managed-mixed-active-owner-retained')
    value = {'case': label, 'mode': mode, 'selectedRevision': revision, 'invocation': row,
        'pending': pending, 'peerGateHistory': history, 'releasedOnce': released, 'cancel': cancellation,
        'physicalRetirement': physical, 'providerUsage': counters, 'peers': observations,
        'budget': selected['budget'], 'postRetiredStoreCallbackClaimed': False}
    path = client.evidence/(label+'-case.json');write_json(path, value)
    return {'case': label, 'mode': mode, 'receipt': {'path': 'controls/'+path.name, **file_identity(path, 1024**2)}}


def run(artifact, native, output, *, deadline):
    output = fresh(output);original = identities(artifact)
    products = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    record = {'schemaVersion': 'latent.dotnet.http-mixed-node.v1', 'status': 'in-progress',
        'originalBuild': original, 'nativeProducts': products, 'cases': [],
        'applicationHandlerInjection': False, 'applicationSchedulerReplacement': False,
        'full693Qualified': False, 'full746Qualified': False}
    stage = 'normal-signing'
    try:
        signed = output/'releases'
        completed = run_bounded_result([str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'managed-mixed-normal-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-dotnet-http-mixed-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'credentials'): (work/name).mkdir(mode=0o700)
            peers, credentials = {}, {}
            for name in ('main', 'helper'):
                secret = ('Bearer '+secrets.token_hex(32)).encode('ascii')
                credentials[name] = work/'credentials'/name
                credentials[name].write_bytes(secret);credentials[name].chmod(0o600)
                peers[name] = Peer(secret, maximum_seconds=300)
                cleanup_owner(cleanup, peers[name], record, 'peer-'+name)
            client = RecordingClient(native['latent'], work/'client', cancellation,
                min(deadline, time.monotonic()+300), evidence=output/'controls',
                invocation_timeout_millis=120000, control_timeout_millis=15000)
            config = configuration(work/'node', signed, peers, credentials)
            record['configuration'] = file_identity(config)
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            cleanup_owner(cleanup, node, record, 'node');probe = Probe(node, products['latentd'])
            source = signed/TEMPLATE
            stage = 'publication-preparation'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'managed-mixed-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            record['preparation'] = prepare(client, publication, 'examples', original['component.wasm']['sha256'], output)
            target = deploy(client, source/'deployment.json', publication)
            stage = 'missing-grants-before-guest'
            denied = finish_call(client, start_call(client, target, TEMPLATE, 'run', [0,
                endpoint(peers['main'])+'|'+endpoint(peers['helper'])], 'managed-mixed-denied'))
            require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                and int(denied['response']['data']['consumption']['cpuFuel']) == 0
                and all(peer.observation()['acceptedConnections'] == 0 for peer in peers.values()),
                'managed-mixed-no-authority-bypass')
            record['preEntryRefusal'] = denied
            _, authorized = grants(client, node, publication, [peer.origin() for peer in peers.values()])
            target = deploy(client, source/'deployment.json', publication, generation=str(target['generation']), grants=authorized)
            for mode, label in enumerate(CASES):
                stage = label
                record['cases'].append(invoke(client, node, target, peers, probe, mode, 'managed-mixed-'+label))
            write_json(output/'final-owner.json', sample(client, probe, 'final-managed-mixed', 1))
            delete_all(client, [target['name']]);stop(client, node)
            shutdown = stopped_record(node);write_json(output/'node-stopped.json', shutdown)
            require(shutdown['reaped'] is True and shutdown['record']['clean'] is True, 'managed-mixed-clean-node-stop')
            for name, peer in peers.items():
                value = peer.close();write_json(output/(name+'-peer-stopped.json'), value);validate_peer(value)
                expected = sum(helper_contacts(mode) for mode in range(len(CASES)))
                if name != 'helper':expected = sum(CONTACTS[:len(CASES)])-expected
                require(value['startedRequests'] == value['acceptedConnections'] == expected
                    and value['openConnections'] == value['rejectedRequests'] == value['committedMutations'] == 0
                    and all(row['role'] == 'primary' and row['authorizationPresent'] is True for row in value['requests']),
                    'managed-mixed-exact-final-authorized-peer-contacts')
        require(original == identities(artifact) and products == {
            name: file_identity(path, 512*1024**2) for name, path in native.items()}, 'managed-mixed-final-product-identities')
        write_json(output/'final-products.json', {'build': original, 'native': products})
        record.update(status='passed', invocations=len(CASES), authorityDenials=1, httpContacts=sum(CONTACTS[:len(CASES)]),
            shutdown=file_identity(output/'node-stopped.json'), products=file_identity(output/'final-products.json'),
            peers={name: file_identity(output/(name+'-peer-stopped.json')) for name in peers})
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        try:write_json(output/'FAILED.json', {**record, 'status': 'failed', 'stage': stage})
        except BaseException:pass
        raise
