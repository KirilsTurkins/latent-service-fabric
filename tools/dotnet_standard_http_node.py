"""Finite ordinary default HttpClient controls on the signed enforced node."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from contextlib import ExitStack
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.guest_runtime_profiles import RUNTIME
from tools.dotnet_guest.entropy_grants import configure as configure_entropy
from tools.dotnet_standard_http_project import managed_source
from tools.phase2_operator_process import Process, read_json, require, write_json, stopped_record
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import RecordingClient, deploy, delete_all, sample
from tools.runtime_owner_refusal_diagnostic import retain as retain_runtime_owner_refusals
from tools.rust_capsule_project import ROOT, digest, fresh, read_file
from tools.standard_http.observations import validate as validate_peer
from tools.static_api.node import policy

CAPABILITY = 'latent:http/streaming@0.3.0'
SERVICE = 'examples/dotnet-standard-http'
ACTIVATION = 'latent:runtime/activation@0.1.0'
OPS = ['register', 'park', 'wake', 'settle', 'close', 'observe', 'wait-for',
       'wait-until', 'timer-start', 'timer-next', 'timer-stop']
CLOCKS = {name: row for name, row in RUNTIME.items() if name != 'random'}
PREFIXES = ((100, 'entry-export'), (101, 'request-ready-plus-cleanup'),
            (102, 'headers-ready-plus-cleanup'), (103, 'stream-ready-plus-cleanup'),
            (104, 'body-copied-plus-cleanup'))


def configuration(directory, releases, startup, credential):
    path = configure_node(directory, releases, 'examples')
    value = read_json(path)
    value['securityProfile'] = 'local-experimental-v1'
    value['cells'][0]['maximumMemoryBytes'] = 134217728
    value['execution']['maximumWallTimeMillis'] = 120000
    value['shutdownGraceMillis'] = 5000
    value['audit'].update(records=4096, diskBytes=67108864)
    value['budgetProfile'] = {'mode': 'phase3', 'maximumOutboundRequests': 8,
        'maximumBlobReadBytes': 0, 'maximumBlobWriteBytes': 0}
    value['capabilityPolicies'] = {'formatVersion': 1, 'maximumControlJobs': 2,
        'store': {'maximumRecords': 64, 'maximumOutcomes': 128, 'maximumCatalogBytes': 4194304,
                  'maximumReadOwners': 64, 'maximumPageRecords': 16}}
    provider = {'identity': {'id': 'http-standard', 'tenant': 'examples', 'service': 'http-host', 'epoch': 1},
        'credentialDirectory': str(credential.parent),
        'credentials': [{'reference': 'standard-peer', 'file': credential.name, 'destination': 0, 'header': 'authorization'}],
        'configuration': {'formatVersion': 1, 'destinations': startup['destinations'],
            'limits': {'maximumRequestBodyBytes': 4096, 'maximumResponseBodyBytes': 32768,
                'maximumEncodedResponseBytes': 65536, 'maximumHeaderBytes': 4096,
                'maximumHeaders': 16, 'maximumRedirects': 0}, 'extraRoots': [], 'publicRoots': False},
        'limits': {'maximumInputBytes': 4096, 'maximumOutputBytes': 32768,
                   'maximumChunkBytes': 16384, 'maximumOutstandingChunks': 2}}
    value['providers'] = {'formatVersion': 1, 'httpStreaming': provider,
        'bindings': [{'name': 'http-standard', 'tenant': 'examples', 'consumerService': SERVICE,
            'providerService': 'http-host', 'contract': CAPABILITY, 'providerBinding': 'http-installed'}]}
    for name, (contract, _profile, _operation, _kind) in CLOCKS.items():
        value['providers'][name] = {'identity': {'id': name, 'tenant': 'examples', 'service': 'runtime-host', 'epoch': 1}}
        value['providers']['bindings'].append({'name': name + '-standard', 'tenant': 'examples',
            'consumerService': SERVICE, 'providerService': 'runtime-host', 'contract': contract,
            'providerBinding': name + '-installed'})
    value['providers']['activationRuntime'] = {
        'identity': {'id': 'activation', 'tenant': 'examples', 'service': 'activation-host', 'epoch': 1},
        'limits': {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
                   'timers': 8, 'results': 8, 'nativeOwners': 8}}
    value['providers']['bindings'].append({'name': 'activation-standard', 'tenant': 'examples',
        'consumerService': SERVICE, 'providerService': 'activation-host', 'contract': ACTIVATION,
        'providerBinding': 'activation-installed'})
    configure_entropy(value, service=SERVICE)
    # Replace only this owned private configuration; no installed service changes.
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return path


def grants(client, node, publication, origin):
    result = []
    for name, (capability, profile, operation, kind) in CLOCKS.items():
        descriptor = next(row for row in node.startup_record['providers'] if row['id'] == name)
        require(descriptor['capability'] == capability and descriptor['profile'] == profile,
                'standard-dotnet-runtime-provider-profile')
        policy(client, 'provider-binding', name + '-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': [operation]}})
        policy(client, 'policy', name + '-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [SERVICE], 'publications': [publication], 'capability': capability, 'operations': [operation],
            'resources': {'kind': kind}, 'ceiling': {'operations': 4096, 'inputBytes': 0,
                'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        result.append({'capability': capability, 'policy': name + '-allow'})
    for capability, identity, binding, operations, kind, ceiling in (
            (ACTIVATION, 'activation', 'activation-installed', OPS, 'clock',
             {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}),
            ('latent:random/random@0.1.0', 'noncrypto-random', 'noncrypto-random-installed', ['bytes'], 'random',
             {'operations': 16, 'inputBytes': 8, 'outputBytes': 4096, 'wallTimeMillis': 5000})):
        descriptor = next(row for row in node.startup_record['providers'] if row['id'] == identity)
        require(descriptor['capability'] == capability, 'standard-dotnet-provider-identity')
        policy(client, 'provider-binding', binding, {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': descriptor['profile'],
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': operations}})
        policy(client, 'policy', identity+'-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [SERVICE], 'publications': [publication], 'capability': capability,
            'operations': operations, 'resources': {'kind': kind}, 'ceiling': ceiling}]})
        result.append({'capability': capability, 'policy': identity+'-allow'})
    runtime = list(result)
    descriptor = next(row for row in node.startup_record['providers'] if row['capability'] == CAPABILITY)
    require(descriptor['profile'] == 'bounded-streaming-http-identity-v1', 'standard-dotnet-http-provider-profile')
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': CAPABILITY, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'ordinary-http', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [SERVICE], 'publications': [publication], 'capability': CAPABILITY,
        'operations': ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body'],
        'resources': {'kind': 'http', 'origins': [origin], 'methods': ['GET', 'POST'], 'paths': [],
                      'pathPrefixes': ['/conformance/']},
        'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}}]})
    result.append({'capability': CAPABILITY, 'policy': 'http-allow'})
    return runtime, result


def managed_failure(decoded):
    if type(decoded) is not list or len(decoded) != 1 or type(decoded[0]) is not str or len(decoded[0]) > 128:
        return None
    parts = decoded[0].split(':')
    if (len(parts) != 3 or parts[0] != 'managed-failure-v1'
            or parts[1] not in {'entry', 'request-ready', 'send-begun', 'headers-ready', 'stream-ready',
                                'body-copied', 'json-parsed', 'result-ready'}
            or parts[2] not in {'platform-not-supported', 'disposed', 'invalid-operation', 'not-supported',
                                'argument', 'out-of-memory', 'cancelled', 'http', 'json', 'io', 'other'}):
        return None
    return {'formatVersion': 1, 'phase': parts[1], 'exceptionFamily': parts[2], 'qualification': False}


def invoke(client, target, which, url, activation):
    path, budget = client.directory/(activation+'.json'), client.directory/(activation+'-budget.json')
    write_json(path, [which, url]); write_json(budget, target['budget'])
    process = Process([client.executable, '--output', 'json', '--config', str(client.config), '--profile', 'operator',
        '--rpc-timeout-ms', '120000', 'invoke', '--service', SERVICE, '--route', target['name'],
        '--contract', 'examples:dotnet-standard-http/api@1.0.0', '--function', 'run', '--activation-id', activation,
        '--input', str(path), '--budget', str(budget), '--budget-profile', 'phase3'],
        client.directory, client.environment, client.cancellation, maximum=65536)
    try:
        completed = process.complete(min(client.deadline, time.monotonic()+123))
    finally:
        process.close()
    value = json.loads(completed.stdout)
    payload = value['data'].get('payload')
    decoded = json.loads(base64.b64decode(payload['data'], validate=True)) if payload else None
    row = {'exitCode': completed.returncode, 'response': value, 'decoded': decoded, 'processReaped': process.owner.finished}
    failure = managed_failure(decoded)
    if failure is not None:
        row['managedFailure'] = failure
    write_json(client.evidence/(activation+'.json'), row)
    return row


def retire(client, target, probe, output, name):
    # The same complete owner-idle observation applies to acceptance and probes.
    retired = sample(client, probe, 'after-'+name, 1)
    slots = next(row for row in retired['inventory']['topology']['entries']
                 if row['name'] == 'invocation-cleanup-slots')
    require(slots['activeCount'] == '0', 'standard-dotnet-cleanup-slots-retired')
    write_json(output/('after-'+name+'.json'), retired)
    usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']['nodeUsage']
    require(not usage['unavailable'] and all(key in usage['counters'] and int(usage['counters'][key]) == 0
        for key in ACTIVE_COUNTERS), 'standard-dotnet-provider-physical-owners')


def prefix_revision(row, component):
    if (type(row) is not dict or row.get('processReaped') is not True
            or type(row.get('response')) is not dict):
        return None
    response = row['response']
    if (response.get('outcomeKnown') is not True or response.get('requestDispatched') is not True
            or type(response.get('data')) is not dict):
        return None
    pin = response['data'].get('resolvedRevision')
    if (type(pin) is not dict or set(pin) != {'publicationId', 'releaseDigest', 'revisionId', 'routeGeneration'}
            or not all(type(value) is str for value in pin.values())
            or re.fullmatch(r'publication:sha256:[0-9a-f]{64}', pin['publicationId']) is None
            or pin['releaseDigest'] != component
            or re.fullmatch(r'revision-v1:sha256:[0-9a-f]{64}', pin['revisionId']) is None
            or re.fullmatch(r'[1-9][0-9]{0,19}', pin['routeGeneration']) is None):
        return None
    return dict(pin)


def guest_trap(row):
    response = row.get('response', {})
    return (type(row.get('exitCode')) is int and row['exitCode'] == 4 and row.get('decoded') is None
            and response.get('category') == 'platform-failure' and type(response.get('error')) is dict
            and response['error'].get('code') == 'guest-trap'
            and response.get('data', {}).get('terminalState') == 'guest_trap')


def prefix_diagnostics(result, client, target, url, probe, output, original):
    """Failure-only fresh prefixes; these never satisfy an acceptance case."""
    diagnostic = {'formatVersion': 1, 'qualification': False, 'originalFailurePreserved': True,
                  'status': 'not-eligible', 'probes': []}
    result['prefixDiagnostics'] = diagnostic
    component = result['artifact']['component.wasm']['sha256']
    pin = prefix_revision(original, component)
    if pin is None or not guest_trap(original):
        return
    stage = 'original-retirement'
    try:
        retire(client, target, probe, output, 'failed-json')
        diagnostic['status'] = 'in-progress'
        for selector, boundary in PREFIXES:
            stage = 'original-deadline'
            require(time.monotonic() < client.deadline, 'standard-dotnet-prefix-original-deadline')
            stage = 'prefix-invocation'
            name = 'prefix-' + str(selector)
            row = invoke(client, target, selector, url+'/conformance/json', 'standard-'+name)
            observation = {'boundary': boundary, 'outcome': 'unconfirmed', 'ownersIdle': False}
            diagnostic['probes'].append(observation)
            stage = 'prefix-retirement'
            require(row.get('processReaped') is True, 'standard-dotnet-prefix-process-unreaped')
            retire(client, target, probe, output, name)
            observation['ownersIdle'] = True
            if prefix_revision(row, component) != pin:
                diagnostic['status'] = 'unconfirmed-revision'
                return
            if type(row.get('exitCode')) is int and row['exitCode'] == 0:
                if row.get('decoded') == ['fixture-prefix-v1:'+boundary]:
                    observation['outcome'] = 'checkpoint-returned'
                elif managed_failure(row.get('decoded')) is not None:
                    observation['outcome'] = 'managed-failure'
                    observation['managedFailure'] = managed_failure(row['decoded'])
                else:
                    diagnostic['status'] = 'unconfirmed-result'
                    return
            elif guest_trap(row):
                observation['outcome'] = 'guest-trap'
            else:
                diagnostic['status'] = 'unconfirmed-result'
                return
        diagnostic['status'] = 'observed'
    except Exception:
        diagnostic.update(status='incomplete', failurePhase=stage)


def require_case_result(name, row, expected, observe_failure):
    try:
        require(row['exitCode'] == 0 and row['decoded'] == [expected], 'standard-dotnet-'+name+'-result')
    except Exception:
        if name == 'json':
            try:
                observe_failure()
            except BaseException:
                # Diagnostic failure or interruption cannot replace the original failure.
                pass
        raise


def request_api_binding(artifact: Path, *, synchronous_send: bool, pre_cancelled_async: bool = False) -> dict:
    """Bind the API label to the normal compiler's captured source and component."""
    managed = managed_source(synchronous_send=synchronous_send, pre_cancelled_async=pre_cancelled_async)
    source = read_file(artifact/'source-inputs.json')
    observed = read_json(artifact/'build-observation.json')
    component = file_identity(artifact/'component.wasm')
    identity = {'digest': digest(managed), 'size': len(managed)}
    selected = json.loads(source).get('src/Main.cs')
    require(type(selected) is dict and type(selected.get('size')) is int and selected == identity,
            'standard-dotnet-observed-request-api-mismatch')
    require(observed['source']['snapshotDigest'] == digest(source)
            and observed['componentDigest'] == component['sha256']
            and type(observed['componentSize']) is int and observed['componentSize'] == component['bytes'],
            'standard-dotnet-observed-request-api-binding')
    return {'name': 'HttpClient.Send' if synchronous_send else 'HttpClient.SendAsync',
        'completionOption': 'ResponseHeadersRead', 'managedSource': identity,
        'sourceSnapshotDigest': digest(source), 'componentDigest': component['sha256']}


def require_synchronous_peer(observation: dict) -> dict:
    """Extra peer evidence; node/provider owners are checked separately per call."""
    expected = {'domain-json': 2, 'http-404': 1, 'http-500': 1, 'truncated-body': 1,
        'oversized-body': 1, 'malformed-json': 1, 'partial-body': 2, 'pending-headers': 1,
        'method-bytes': 1, 'commit-close': 1}
    rows, events = observation['requests'], observation['events']
    require(Counter(row.get('vector') for row in rows) == expected,
            'standard-dotnet-send-exact-request-vectors')
    for row in rows:
        require(row.get('method') == ('POST' if row['vector'] in {'method-bytes', 'commit-close'} else 'GET'),
                'standard-dotnet-send-request-method')
        phase = {'pending-headers': 'headers', 'partial-body': 'body'}.get(row['vector'])
        if phase is not None:
            selected = [event for event in events if event['request'] == row['request']]
            pending = [event for event in selected if event['kind'] == 'gate-pending']
            require(len(pending) == 1 and pending[0].get('phase') == phase
                    and not any(event['kind'] in {'gate-released', 'response-write-complete'} for event in selected)
                    and (row['responseBytesWritten'] == 0 if phase == 'headers' else row['responseBytesWritten'] > 0),
                    'standard-dotnet-send-peer-not-genuinely-pending')
        if row['vector'] == 'commit-close':
            require(row.get('mutationCommitted') is True and row['responseBytesWritten'] == 0
                    and row.get('closeReason') == 'response-withheld-after-commit'
                    and sum(event['kind'] == 'mutation-committed' and event['request'] == row['request']
                            for event in events) == 1,
                    'standard-dotnet-send-uncertain-post-replayed-or-uncommitted')
    return {'exactContactVectors': True, 'headersAndBodyHeldWithoutRelease': True,
        'uncertainPostCommittedOnceWithoutResponse': True,
        'preCancelledAndDeniedRequestsWithoutAdditionalContact': True,
        'scope': 'peer-protocol-only'}


def retain_peer_observation(raw: bytes, authorization: bytes, output: Path, result: dict, *,
        synchronous_send: bool, pre_cancelled_async: bool = False) -> None:
    """Keep bounded protocol evidence even when its acceptance predicates fail."""
    require(type(raw) is bytes and len(raw) <= 65536, 'standard-dotnet-peer-observation-size')
    require(type(authorization) is bytes and re.fullmatch(rb'Bearer [a-f0-9]{64}', authorization),
            'standard-dotnet-peer-observation-credential-shape')
    observation = json.loads(raw)
    canonical = json.dumps(observation, ensure_ascii=True).encode('ascii')
    token = authorization.removeprefix(b'Bearer ')
    require(all(secret not in encoded for secret in (authorization, token) for encoded in (raw, canonical)),
            'standard-dotnet-peer-observation-private-value')
    (output/'peer-observation.json').write_bytes(raw)
    result['peer'] = observation
    validate_peer(observation)
    require(observation['startedRequests'] == 12 and observation['rejectedRequests'] == 0
        and observation['committedMutations'] == 1
        and all(row['role'] == 'primary' for row in observation['requests']),
        'standard-dotnet-peer-contact-count')
    if synchronous_send:
        result['synchronousSend']['peer'] = require_synchronous_peer(observation)
    if pre_cancelled_async:
        result['asynchronousPreCancellation']['peer'] = require_synchronous_peer(observation)


def require_pre_cancelled_outbound(row: dict) -> None:
    require(type(row['response']['data']['consumption']['outboundRequests']) is int
            and row['response']['data']['consumption']['outboundRequests'] == 0,
            'standard-dotnet-send-pre-cancelled-outbound-attempt')


def run(artifact: Path, native: Path | dict[str, Path], output: Path, *, deadline: float | None = None,
        synchronous_send: bool = False, pre_cancelled_async: bool = False):
    expires = min(time.monotonic()+300, deadline) if deadline is not None else time.monotonic()+300
    require(expires > time.monotonic(), 'standard-dotnet-original-deadline-expired')
    output = fresh(output)
    result = {'schemaVersion': 'latent.dotnet.standard-http.qualification.v1', 'status': 'in-progress',
        'scope': 'ordinary-default-httpclient-and-signed-real-provider-subset',
        'unchangedThirdPartyLibraryQualification': False, 'releasePublication': 'not-performed', 'cases': []}
    binaries = ({name: native/name for name in ('latent', 'latentd', 'capsule_authoring')}
                if isinstance(native, Path) else dict(native))
    require(set(binaries) == {'latent', 'latentd', 'capsule_authoring'}, 'standard-dotnet-native-tuple-required')
    before = {name: file_identity(path) for name, path in binaries.items()}
    result['binaries'] = before
    tuple_path = native/'native-tuple.json' if isinstance(native, Path) else None
    if tuple_path is not None and tuple_path.exists():
        tuple_record = read_json(tuple_path)
        require(all({key: tuple_record['binaries'][name][key] for key in ('sha256', 'bytes')} == identity
                    for name, identity in before.items()), 'standard-dotnet-native-build-receipt-mismatch')
        result['nativeTuple'] = tuple_record
        result['nativeTupleIdentity'] = file_identity(tuple_path)
    result['artifact'] = {name: file_identity(artifact/name) for name in (
        'BUILD-COMPLETE.json', 'component.wasm', 'build-observation.json', 'source-inputs.json',
        'recipe-inputs.json', 'runtime-profile.json', 'closed-runtime-coverage.json', 'bindings.json')}
    if synchronous_send or pre_cancelled_async:
        result['artifact'].update({name: file_identity(artifact/name) for name in (
            'compiler-inputs.json', 'compiler-patches-preparation.json', 'compiler-patches.json')})
    source_paths = ('tools/dotnet_standard_http_project.py', 'tools/dotnet_standard_http_node.py',
        'tools/runtime_owner_refusal_diagnostic.py',
        'tools/qualify_dotnet_standard_http.py', 'examples/dotnet-standard-http/Main.cs',
        'examples/dotnet-standard-http/world.wit', 'tools/standard_http/process_peer.py',
        'tools/standard_http/peer.py', 'tools/standard_http/protocol.py', 'tools/standard_http/vectors.py',
        'tools/standard_http/observations.py', 'tools/dotnet_guest/async_exports.py',
        'tools/dotnet_guest_bindings.py', 'tools/dotnet_guest/entropy_grants.py', 'tools/static_api/node.py')
    result['sources'] = {name: file_identity(ROOT/name) for name in source_paths}
    result['limitations'] = ['Native process RSS is sampled, not allocator/native/kernel upper-bound proof.',
        'Finite ordinary standard-API controls; no two-client, private-library, all-runtime or full ticket qualification.']
    if synchronous_send:
        result['limitations'].append('Send with ResponseHeadersRead only; default buffering overloads are not exercised.')
    node = peer = client = None
    stage = 'request-api-binding'
    try:
        result['requestApi'] = request_api_binding(artifact, synchronous_send=synchronous_send,
                                                  pre_cancelled_async=pre_cancelled_async)
        stage = 'sign'
        environment = build_environment(output)
        signed = output/'releases'
        completed = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, environment, timeout_seconds=min(30, expires-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'standard-dotnet-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-dotnet-standard-http-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node', 'peer'):
                (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_text('Bearer '+secrets.token_hex(32), encoding='ascii'); credential.chmod(0o600)
            client = RecordingClient(binaries['latent'], work/'client', cancellation, expires,
                evidence=output/'controls', invocation_timeout_millis=120000)
            stage = 'peer'
            peer = Process([sys.executable, str(ROOT/'tools/standard_http/process_peer.py'), '--credential', str(credential)],
                           work/'peer', environment, cancellation, maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(client.deadline, time.monotonic()+10))
            config = configuration(work/'node', signed, startup, credential)
            result['configurationIdentity'] = file_identity(config)
            stage = 'node'
            node = connect(client, binaries['latentd'], work/'node', config, 'examples', 1,
                           control_refusal_diagnostic=True)
            cleanup.callback(node.close)
            probe = Probe(node, before['latentd'])
            result['baselineOs'] = probe.sample()
            stage = 'publication'
            source = signed/'dotnet-standard-http'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'standard-http-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            origin = startup['origins']['primary']
            url = f"http://{origin['host']}:{origin['port']}"
            secondary = startup['origins']['secondary']
            stage = 'runtime-denial'
            denied = invoke(client, target, 0, url+'/conformance/json', 'standard-runtime-denied')
            require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                    and denied['response']['data']['consumption']['cpuFuel'] == '0',
                    'standard-dotnet-runtime-grant-denial')
            runtime, authorized = grants(client, node, publication, origin)
            target = deploy(client, source/'deployment.json', publication, generation=str(target['generation']), grants=runtime)
            stage = 'http-denial'
            denied = invoke(client, target, 0, url+'/conformance/json', 'standard-http-denied')
            require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                    and denied['response']['data']['consumption']['cpuFuel'] == '0',
                    'standard-dotnet-http-grant-denial')
            target = deploy(client, source/'deployment.json', publication, generation=str(target['generation']), grants=authorized)
            stage = 'ordinary-http'
            send_revision = None
            cases = [('json', 0, '/conformance/json', '1:200:domain:7:caf\u00e9:first|\u03bb:'),
                     ('http404', 0, '/conformance/status/404', '1:404:error:domain-error'),
                     ('http500', 0, '/conformance/status/500', '1:500:error:domain-error'),
                     ('truncated', 0, '/conformance/body/truncated', '1:transport-error'),
                     ('oversized', 0, '/conformance/body/oversized', '1:transport-error'),
                     ('malformed-json', 0, '/conformance/body/malformed-json', '1:invalid-json'),
                     ('forbidden', 3, '/conformance/json', '1:transport-error'),
                     ('early', 2, '/conformance/body/partial', '1:early:4'),
                     ('cancel-headers', 4, '/conformance/hold/headers', '1:cancelled'),
                     ('cancel-body', 5, '/conformance/body/partial', '1:cancelled'),
                     ('post', 1, '/conformance/echo', '1:200:echo:AAECAw=='),
                     ('uncertain', 1, '/conformance/mutation/close', '1:transport-error'),
                     ('alternate-denied', 0, f"http://{secondary['host']}:{secondary['port']}/conformance/denied-target",
                         '1:transport-error'),
                     ('fresh', 0, '/conformance/json', '1:200:domain:7:caf\u00e9:first|\u03bb:')]
            for name, which, path, expected in cases:
                row = invoke(client, target, which, path if path.startswith('http://') else url+path, 'standard-'+name)
                require_case_result(name, row, expected,
                    lambda: prefix_diagnostics(result, client, target, url, probe, output, row))
                if synchronous_send or pre_cancelled_async:
                    revision = prefix_revision(row, result['artifact']['component.wasm']['sha256'])
                    require(revision is not None and (send_revision is None or revision == send_revision),
                            'standard-dotnet-send-signed-revision-or-process')
                    send_revision = revision
                result['cases'].append(name)
                # The shared outbound owner checks every activation-scoped and
                # service-resident row. Ingress-only exchange rows are absent on
                # this node, which has no HTTP listener installation.
                retire(client, target, probe, output, name)
            if synchronous_send or pre_cancelled_async:
                stage = 'synchronous-pre-cancelled' if synchronous_send else 'asynchronous-pre-cancelled'
                row = invoke(client, target, 6, url+'/conformance/json', 'standard-pre-cancelled')
                require_case_result('pre-cancelled', row, '1:cancelled', lambda: None)
                require_pre_cancelled_outbound(row)
                require(prefix_revision(row, result['artifact']['component.wasm']['sha256']) == send_revision,
                        'standard-dotnet-send-pre-cancelled-signed-revision-or-process')
                result['cases'].append('pre-cancelled')
                retire(client, target, probe, output, 'pre-cancelled')
                result['synchronousSend' if synchronous_send else 'asynchronousPreCancellation'] = {'ordinaryDefaultClient': True,
                    'sameSignedRevision': send_revision, 'freshManagedStatePerInvocation': True,
                    'allOriginalFourteenCases': True, 'preCancelledRequest': True,
                    'physicalOwnerChecksPerInvocation': True, 'fullTicketQualification': False}
            result['finalOs'] = probe.sample()
            delete_all(client, [target['name']])
            stop(client, node)
            result['shutdown'] = stopped_record(node)
            require(result['shutdown']['reaped'] and result['shutdown']['record']['clean'], 'standard-dotnet-node-clean-shutdown')
            retain_runtime_owner_refusals(node, output)
            node = None
            stage = 'peer-observation'
            peer.stop()
            retain_peer_observation(bytes(peer.buffers[0]), credential.read_bytes(), output, result,
                                    synchronous_send=synchronous_send, pre_cancelled_async=pre_cancelled_async)
            result['peerReaped'] = peer.owner.finished
            peer = None
        require(before == {name: file_identity(path) for name, path in binaries.items()}, 'standard-dotnet-native-tuple-changed')
        if tuple_path is not None and 'nativeTupleIdentity' in result:
            require(result['nativeTupleIdentity'] == file_identity(tuple_path), 'standard-dotnet-native-receipt-changed')
        require(result['artifact'] == {name: file_identity(artifact/name) for name in result['artifact']},
                'standard-dotnet-artifact-changed')
        require(result['sources'] == {name: file_identity(ROOT/name) for name in source_paths}, 'standard-dotnet-sources-changed')
        result['status'] = 'passed'
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        result.update(status='failed', stage=stage)
        write_json(output/'FAILED.json', result)
        raise
    finally:
        if node is not None:
            try:
                node.close()
            finally:
                retain_runtime_owner_refusals(node, output)
        if peer is not None: peer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--synchronous-send', action='store_true')
    parser.add_argument('--pre-cancelled-async', action='store_true')
    args = parser.parse_args()
    run(args.artifact, args.native, args.output, synchronous_send=args.synchronous_send,
        pre_cancelled_async=args.pre_cancelled_async)
