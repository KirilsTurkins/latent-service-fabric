"""Finite ordinary default Go net/http controls on the signed enforced node."""
from __future__ import annotations

import argparse
import base64
import hashlib
from contextlib import ExitStack
import json
from pathlib import Path
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
from tools.phase2_operator_process import Process, read_json, require, write_json, stopped_record
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import RecordingClient, deploy, delete_all, sample
from tools.rust_capsule_project import ROOT, fresh
from tools.standard_http.observations import validate as validate_peer
from tools.static_api.node import policy

CAPABILITY = 'latent:http/streaming@0.3.0'
PEER_SOURCE = 'tools/java_standard_http_peer.py'
SERVICE = 'examples/go-standard-http'
ACTIVATION = 'latent:runtime/activation@0.1.0'
OPS = ['register', 'park', 'wake', 'settle', 'close', 'observe', 'wait-for',
       'wait-until', 'timer-start', 'timer-next', 'timer-stop']
RUNTIME_PROVIDERS = dict(RUNTIME)


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
    for name, (contract, _profile, _operation, _kind) in RUNTIME_PROVIDERS.items():
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
    # Replace only this owned private configuration; no installed service changes.
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return path


def grants(client, node, publication, origin):
    result = []
    for name, (capability, profile, operation, kind) in RUNTIME_PROVIDERS.items():
        descriptor = next(row for row in node.startup_record['providers'] if row['id'] == name)
        require(descriptor['capability'] == capability and descriptor['profile'] == profile,
                'standard-go-runtime-provider-profile')
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
            ):
        descriptor = next(row for row in node.startup_record['providers'] if row['id'] == identity)
        require(descriptor['capability'] == capability, 'standard-go-provider-identity')
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
    require(descriptor['profile'] == 'bounded-streaming-http-identity-v1', 'standard-go-http-provider-profile')
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


def invoke(client, target, which, url, activation):
    path, budget = client.directory/(activation+'.json'), client.directory/(activation+'-budget.json')
    write_json(path, [which, url]); write_json(budget, target['budget'])
    process = Process([client.executable, '--output', 'json', '--config', str(client.config), '--profile', 'operator',
        '--rpc-timeout-ms', '120000', 'invoke', '--service', SERVICE, '--route', target['name'],
        '--contract', 'tests:go-standard-http/api@1.0.0', '--function', 'run', '--activation-id', activation,
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
    write_json(client.evidence/(activation+'.json'), row)
    return row


def library_cases(secondary: dict) -> list[tuple]:
    cases = []
    for index,name in enumerate(('sling','requests')):
        # Sling's original streaming JSON decoder can reject malformed bytes
        # before its deferred discard encounters the provider's size error.
        oversized = 'invalid-json' if index == 0 else 'transport-error'
        for label,mode,path,expected in (
            ('json',0,'/conformance/json','200:domain:7:caf\u00e9:first|\u03bb'),
            ('http404',0,'/conformance/status/404','404:error:domain-error'),
            ('http500',0,'/conformance/status/500','500:error:domain-error'),
            ('truncated',0,'/conformance/body/truncated','transport-error'),
            ('oversized',0,'/conformance/body/oversized',oversized),
            ('malformed-json',0,'/conformance/body/malformed-json','invalid-json'),
            ('forbidden',3,'/conformance/json','transport-error'),
            ('cancel-headers',4,'/conformance/hold/headers','cancelled'),
            ('partial-context-cancel',5,'/conformance/body/partial','cancelled'),
            ('post',1,'/conformance/echo','200:echo:AAECAw=='),
            ('uncertain',1,'/conformance/mutation/close','transport-error'),
            ('alternate-denied',0,f"http://{secondary['host']}:{secondary['port']}/conformance/denied-target",'transport-error'),
            ('pre-cancelled',6,'/conformance/json','cancelled'),
            ('sibling-cancel',7,'/conformance/hold/headers','cancelled'),
            ('fresh',0,'/conformance/json','200:domain:7:caf\u00e9:first|\u03bb')):
            cases.append((name+'-'+label,index*100+mode,path,expected))
    return cases


def run(artifact: Path, native: Path | dict[str, Path], output: Path, *, deadline: float | None = None,
        suite: str = 'standard'):
    require(suite in {'standard','libraries'},'standard-go-unknown-fixture-suite')
    expires = min(time.monotonic()+300, deadline) if deadline is not None else time.monotonic()+300
    require(expires > time.monotonic(), 'standard-go-original-deadline-expired')
    output = fresh(output)
    result = {'schemaVersion': 'latent.go.standard-http.qualification.v1', 'status': 'in-progress',
        'scope': 'ordinary-default-go-client-and-signed-real-provider-subset',
        'unchangedThirdPartyLibraryQualification': False, 'releasePublication': 'not-performed', 'cases': []}
    result['suite'] = suite
    binaries = ({name: native/name for name in ('latent', 'latentd', 'capsule_authoring')}
                if isinstance(native, Path) else dict(native))
    require(set(binaries) == {'latent', 'latentd', 'capsule_authoring'}, 'standard-go-native-tuple-required')
    before = {name: file_identity(path) for name, path in binaries.items()}
    result['binaries'] = before
    tuple_path = native/'native-tuple.json' if isinstance(native, Path) else None
    if tuple_path is not None and tuple_path.exists():
        tuple_record = read_json(tuple_path)
        require(all({key: tuple_record['binaries'][name][key] for key in ('sha256', 'bytes')} == identity
                    for name, identity in before.items()), 'standard-go-native-build-receipt-mismatch')
        result['nativeTuple'] = tuple_record
        result['nativeTupleIdentity'] = file_identity(tuple_path)
    result['artifact'] = {name: file_identity(artifact/name) for name in (
        'BUILD-COMPLETE.json', 'component.wasm', 'build-observation.json', 'source-inputs.json',
        'recipe-inputs.json', 'go-runtime-transformations.json', 'bindings.json')}
    source_paths = ('tools/go_standard_http_project.py', 'tools/go_standard_http_node.py',
        'tools/qualify_go_standard_http.py', 'sdk/go-guest/runtime/standard-http-conformance/main.go',
        'sdk/go-guest/runtime/standard-http-conformance/world.wit', PEER_SOURCE,
        'tools/standard_http/peer.py', 'tools/standard_http/protocol.py', 'tools/standard_http/vectors.py',
        'tools/standard_http/observations.py', 'tools/go_guest/http.py', 'tools/go_guest/http_context.py',
        'sdk/go-guest/runtime/http_async.go.in', 'sdk/go-guest/runtime/http_transport.go.in',
        'tools/static_api/node.py', 'tools/guest_runtime_profiles.py')
    if suite == 'libraries':
        source_paths += ('sdk/go-guest/runtime/http-library-conformance/main.go',
            'tools/go_http_library_fixture.py','tools/qualify_go_http_libraries.py')
    result['sources'] = {name: file_identity(ROOT/name) for name in source_paths}
    result['limitations'] = ['Native process RSS is sampled, not allocator/native/kernel upper-bound proof.',
        'Finite ordinary standard-API controls; no two-client, private-library, all-runtime or full ticket qualification.']
    if suite == 'libraries':
        result['limitations'] = ['Native RSS sampling is not an allocator/native/kernel upper-bound proof.',
            'Shared standard33 gate owns early-close/concrete Transport/custom extension controls.',
            'Sling partial-response context cancellation does not independently prove the header-return phase.',
            'No complete runtime, TLS, socket, pool or full ticket qualification.']
    node = peer = client = None
    stage = 'sign'
    try:
        environment = build_environment(output)
        signed = output/'releases'
        completed = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, environment, timeout_seconds=min(30, expires-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'standard-go-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-go-standard-http-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node', 'peer'):
                (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_text('Bearer '+secrets.token_hex(32), encoding='ascii'); credential.chmod(0o600)
            client = RecordingClient(binaries['latent'], work/'client', cancellation, expires,
                evidence=output/'controls', invocation_timeout_millis=120000)
            stage = 'peer'
            peer = Process([sys.executable, str(ROOT/PEER_SOURCE), '--credential', str(credential)],
                           work/'peer', environment, cancellation, maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(client.deadline, time.monotonic()+10))
            config = configuration(work/'node', signed, startup, credential)
            result['configurationIdentity'] = file_identity(config)
            stage = 'node'
            node = connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(node.close)
            probe = Probe(node, before['latentd'])
            result['baselineOs'] = probe.sample()
            stage = 'publication'
            source = signed/'go-standard-http'
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
                    'standard-go-runtime-grant-denial')
            runtime, authorized = grants(client, node, publication, origin)
            target = deploy(client, source/'deployment.json', publication, generation=str(target['generation']), grants=runtime)
            stage = 'http-denial'
            denied = invoke(client, target, 0, url+'/conformance/json', 'standard-http-denied')
            require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                    and denied['response']['data']['consumption']['cpuFuel'] == '0',
                    'standard-go-http-grant-denial')
            target = deploy(client, source/'deployment.json', publication, generation=str(target['generation']), grants=authorized)
            stage = 'ordinary-http'
            cases = [('json', 0, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb'),
                     ('http404', 0, '/conformance/status/404', '404:error:domain-error'),
                     ('http500', 0, '/conformance/status/500', '500:error:domain-error'),
                     ('truncated', 0, '/conformance/body/truncated', 'transport-error'),
                     ('oversized', 0, '/conformance/body/oversized', 'transport-error'),
                     ('malformed-json', 0, '/conformance/body/malformed-json', 'invalid-json'),
                     ('forbidden', 3, '/conformance/json', 'transport-error'),
                     ('early', 2, '/conformance/body/partial', 'early:4'),
                     ('cancel-headers', 4, '/conformance/hold/headers', 'cancelled'),
                     ('cancel-body', 5, '/conformance/body/partial', 'cancelled'),
                     ('post', 1, '/conformance/echo', '200:echo:AAECAw=='),
                     ('uncertain', 1, '/conformance/mutation/close', 'transport-error'),
                     ('alternate-denied', 0, f"http://{secondary['host']}:{secondary['port']}/conformance/denied-target",
                         'transport-error'),
                     ('pre-cancelled', 6, '/conformance/json', 'cancelled'),
                     ('sibling-cancel', 7, '/conformance/hold/headers', 'cancelled'),
                     ('concrete', 8, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb'),
                     ('clone', 9, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb'),
                     ('custom-separate', 10, '/conformance/json', '200:domain:7:caf\u00e9:\u03bb|'),
                     ('custom-dialer-denied', 11, '/conformance/json', 'custom-dialer-denied'),
                     ('physical-nonreuse-denied', 12, '/conformance/json', 'transport-error'),
                     ('negative-header-limit-denied', 13, '/conformance/json', 'transport-error'),
                     ('request-close-denied', 14, '/conformance/json', 'transport-error'),
                     ('negative-body-length-denied', 15, '/conformance/json', 'transport-error'),
                     ('absent-declared-body-denied', 16, '/conformance/json', 'transport-error'),
                     ('wire-header-timeout-denied', 17, '/conformance/json', 'transport-error'),
                     ('wire-header-limit-denied', 18, '/conformance/json', 'transport-error'),
                     ('wire-read-buffer-denied', 19, '/conformance/json', 'transport-error'),
                     ('wire-write-buffer-denied', 20, '/conformance/json', 'transport-error'),
                     ('user-agent-default', 21, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb'),
                     ('user-agent-empty', 22, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb'),
                     ('user-agent-first', 23, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb'),
                     ('noncanonical-user-agent-denied', 24, '/conformance/json', 'transport-error'),
                     ('fresh', 0, '/conformance/json', '200:domain:7:caf\u00e9:first|\u03bb')]
            if suite == 'libraries':
                cases = library_cases(secondary)
            for name, which, path, expected in cases:
                row = invoke(client, target, which, path if path.startswith('http://') else url+path, 'standard-'+name)
                require(row['exitCode'] == 0 and row['decoded'] == [expected], 'standard-go-'+name+'-result')
                result['cases'].append(name)
                # The shared outbound owner checks every activation-scoped and
                # service-resident row. Ingress-only exchange rows are absent on
                # this node, which has no HTTP listener installation.
                retired = sample(client, probe, 'after-'+name, 1)
                slots = next(row for row in retired['inventory']['topology']['entries']
                             if row['name'] == 'invocation-cleanup-slots')
                require(slots['activeCount'] == '0', 'standard-go-cleanup-slots-retired')
                write_json(output/('after-'+name+'.json'), retired)
                usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']['nodeUsage']
                require(not usage['unavailable'] and all(key in usage['counters'] and int(usage['counters'][key]) == 0
                    for key in ACTIVE_COUNTERS), 'standard-go-provider-physical-owners')
            result['finalOs'] = probe.sample()
            delete_all(client, [target['name']])
            stop(client, node)
            result['shutdown'] = stopped_record(node)
            require(result['shutdown']['reaped'] and result['shutdown']['record']['clean'], 'standard-go-node-clean-shutdown')
            node = None
            peer.stop()
            observation = json.loads(bytes(peer.buffers[0]).splitlines()[0])
            validate_peer(observation)
            contacts = 24 if suite == 'libraries' else 18
            require(observation['acceptedConnections'] == observation['startedRequests'] == contacts and observation['rejectedRequests'] == 0
                and observation['committedMutations'] == (2 if suite == 'libraries' else 1)
                and all(row['role'] == 'primary' for row in observation['requests']),
                'standard-go-peer-contact-count')
            if suite == 'standard':
                expected_agents = (b'Go-http-client/1.1', None, b'fixture-agent/1', b'Go-http-client/1.1')
                for row, agent in zip(observation['requests'][-4:], expected_agents, strict=True):
                    require(row['userAgent'] == {'present':agent is not None,
                        'bytes':len(agent) if agent is not None else 0,
                        'sha256':'sha256:'+hashlib.sha256(agent).hexdigest() if agent is not None else None},
                        'standard-go-user-agent-semantics')
            result['peer'] = observation
            result['peerReaped'] = peer.owner.finished
            peer = None
        require(before == {name: file_identity(path) for name, path in binaries.items()}, 'standard-go-native-tuple-changed')
        if tuple_path is not None and 'nativeTupleIdentity' in result:
            require(result['nativeTupleIdentity'] == file_identity(tuple_path), 'standard-go-native-receipt-changed')
        require(result['artifact'] == {name: file_identity(artifact/name) for name in result['artifact']},
                'standard-go-artifact-changed')
        require(result['sources'] == {name: file_identity(ROOT/name) for name in source_paths}, 'standard-go-sources-changed')
        result['status'] = 'passed'
        result['unchangedThirdPartyLibraryQualification'] = suite == 'libraries'
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        result.update(status='failed', stage=stage)
        write_json(output/'FAILED.json', result)
        raise
    finally:
        if node is not None: node.close()
        if peer is not None: peer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.artifact, args.native, args.output)
