#!/usr/bin/env python3
"""Finite signed Fetch/provider experiment, never whole-ticket certification."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.dev_workflow.node_diagnostics import original_result
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import Process, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.qualify_typescript_dependencies import prepared_native
from tools.qualify_typescript_fetch_component import project as compiler_project
from tools.rust_capsule_node import RecordingClient, call, delete_all, deploy, sample
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot
from tools.runtime_owner_refusal_diagnostic import BUCKETS, retain as retain_runtime_owner_refusals
from tools.standard_http.observations import validate as validate_peer
from tools.standard_http.vectors import DOMAIN, json_bytes
from tools.static_api.node import policy
from tools.typescript_guest.build import build
from tools.typescript_guest.fetch_profile import PROFILE
from tools.typescript_guest.project import validate
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

FIXTURE = 'sdk/typescript-guest/probes/fetch-runtime'
SERVICE = 'examples/typescript-fetch'
HTTP = 'latent:http/streaming@0.3.0'
ACTIVATION = 'latent:runtime/activation@0.1.0'
ACTIVATION_OPS = ['register', 'park', 'wake', 'settle', 'close',
                  'timer-start', 'timer-next', 'timer-stop']
PRODUCTS = ('latent', 'latentd', 'capsule_contracts', 'package', 'capsule_authoring')
# Match the maintained actual TypeScript local-service runtime experiment.
OWNER_LIMITS = {'tasks': 16, 'executors': 2, 'queuedWork': 16, 'waits': 8,
                'timers': 8, 'results': 8, 'nativeOwners': 64}
EVENT_CLONE_VECTORS = (('event-clone-repeated', 20, 'event-clone:repeated:12:40'),
                       ('event-clone-nested', 21, 'event-clone:nested:12:ordered'))
ABORT_CLONE_VECTORS = (('abort-clone-normal', 22, 'abort-clone:normal:12'),
                       ('abort-clone-refusal', 23, 'abort-clone:two-native-register-refusals:recovered'),
                       ('abort-clone-fresh', 22, 'abort-clone:normal:12'))
ABORT_ANY_VECTORS = (('abort-any-frames', 24, 'abort-any:80:nested:12:ordered'),
                     ('abort-any-refusal', 25, 'abort-any:refusal:closed:recovered'),
                     ('abort-any-fresh', 24, 'abort-any:80:nested:12:ordered'))
ABORT_DEFAULT_VECTORS = (('abort-default-reason', 26, 'abort-default:shared:2:thrown'),
                         ('abort-default-fresh', 26, 'abort-default:shared:2:thrown'))
COMBINATOR_VECTORS = (('combinator-retained', 27, 'combinator:retained:3:ordered'),
                      ('combinator-refusal', 28, 'combinator:native-refusal:closed:recovered'),
                      ('combinator-fresh', 27, 'combinator:retained:3:ordered'))
COMPLETED_CAPTURE_VECTORS = (('combinator-completed-control', 30, 'combinator:completed:released:3'),
                             ('combinator-completed-retained', 29, None),
                             ('combinator-completed-fresh', 30, 'combinator:completed:released:3'))


def execution_vectors(completed_capture_diagnostic):
    require(type(completed_capture_diagnostic) is bool, 'fetch-runtime-diagnostic-selection')
    if completed_capture_diagnostic:
        return [(name, mode, '/conformance/json', expected, 0)
                for name, mode, expected in COMPLETED_CAPTURE_VECTORS]
    return [('entry', 1, '/conformance/json', 'entered', 0),
        ('request-ready', 2, '/conformance/json', 'request-ready', 0),
        ('promise-ready', 3, '/conformance/json', 'promise-ready', 0),
        ('request-copy-ready', 4, '/conformance/json', 'request-copy-ready', 0),
        *((name, mode, '/conformance/json', expected, 0)
          for name, mode, expected in EVENT_CLONE_VECTORS),
        *((name, mode, '/conformance/json', expected, 0)
          for name, mode, expected in ABORT_CLONE_VECTORS),
        *((name, mode, '/conformance/json', expected, 0)
          for name, mode, expected in ABORT_ANY_VECTORS),
        *((name, mode, '/conformance/json', expected, 0)
          for name, mode, expected in ABORT_DEFAULT_VECTORS),
        *((name, mode, '/conformance/json', expected, 0)
          for name, mode, expected in COMBINATOR_VECTORS),
        ('json', 0, '/conformance/json', '1:200:'+json_bytes(DOMAIN).decode()+':used', 1),
        ('http404', 0, '/conformance/status/404',
            '1:404:'+json_bytes({'status':404, 'message':'domain-error'}).decode()+':used', 1),
        ('fresh', 0, '/conformance/json', '1:200:'+json_bytes(DOMAIN).decode()+':used', 1)]


def project(directory: Path) -> Path:
    app = compiler_project(directory)
    for name in ('main.ts', 'default-client.ts'):
        (app / 'src' / name).write_bytes(read_file(ROOT / FIXTURE / name))
    wit = read_file(ROOT / FIXTURE / 'world.wit')
    (app / 'wit/world.wit').write_bytes(wit)
    lock = read_json(app / 'sdk-lock.json')
    lock['template'] = {'name': 'typescript-fetch',
        'sourceDigest': digest(read_file(app / 'src/main.ts')), 'witDigest': digest(wit)}
    (app / 'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    validate(snapshot(app))
    return app


def configuration(directory, releases, startup, credential):
    path = configure_node(directory, releases, 'examples')
    value = read_json(path)
    value['cells'][0]['maximumMemoryBytes'] = 134217728
    value['execution']['maximumWallTimeMillis'] = 120000
    value['cache'].update(entries=2, preparations=1)
    value['shutdownGraceMillis'] = 5000
    value['audit'].update(records=4096, diskBytes=67108864)
    value['budgetProfile'] = {'mode': 'phase3', 'maximumOutboundRequests': 1,
        'maximumBlobReadBytes': 0, 'maximumBlobWriteBytes': 0}
    value['capabilityPolicies'] = {'formatVersion': 1, 'maximumControlJobs': 2,
        'store': {'maximumRecords': 64, 'maximumOutcomes': 128, 'maximumCatalogBytes': 4194304,
                  'maximumReadOwners': 64, 'maximumPageRecords': 16}}
    value['providers'] = {'formatVersion': 1, 'bindings': [], 'httpStreaming': {
        'identity': {'id': 'http-standard', 'tenant': 'examples', 'service': 'http-host', 'epoch': 1},
        'credentialDirectory': str(credential.parent),
        'credentials': [{'reference': 'standard-peer', 'file': credential.name,
                         'destination': 0, 'header': 'authorization'}],
        'configuration': {'formatVersion': 1, 'destinations': startup['destinations'],
            'limits': {'maximumRequestBodyBytes': 4096, 'maximumResponseBodyBytes': 8192,
                'maximumEncodedResponseBytes': 16384, 'maximumHeaderBytes': 4096,
                'maximumHeaders': 16, 'maximumRedirects': 0}, 'extraRoots': [], 'publicRoots': False},
        'limits': {'maximumInputBytes': 4096, 'maximumOutputBytes': 8192,
                   'maximumChunkBytes': 65536, 'maximumOutstandingChunks': 2}}}
    providers = value['providers']
    providers['bindings'].append({'name': 'http-standard', 'tenant': 'examples',
        'consumerService': SERVICE, 'providerService': 'http-host', 'contract': HTTP,
        'providerBinding': 'http-installed'})
    for name, (contract, _profile, _operation, _kind) in profiles('java').items():
        providers[name] = {'identity': {'id': name, 'tenant': 'examples', 'service': 'runtime-host', 'epoch': 1}}
        providers['bindings'].append({'name': name+'-fetch', 'tenant': 'examples', 'consumerService': SERVICE,
            'providerService': 'runtime-host', 'contract': contract, 'providerBinding': name+'-installed'})
    providers['activationRuntime'] = {'identity': {'id': 'activation', 'tenant': 'examples',
        'service': 'activation-host', 'epoch': 1}, 'limits': dict(OWNER_LIMITS)}
    providers['bindings'].append({'name': 'activation-fetch', 'tenant': 'examples', 'consumerService': SERVICE,
        'providerService': 'activation-host', 'contract': ACTIVATION, 'providerBinding': 'activation-installed'})
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return path


def grants(client, node, publication, origin):
    result = []
    runtime = [(name, *values) for name, values in profiles('java').items()]
    runtime.append(('activation', ACTIVATION, 'activation-owned-v1', ACTIVATION_OPS, 'clock'))
    for name, capability, profile, operation, kind in runtime:
        operations = [operation] if isinstance(operation, str) else operation
        descriptor = next(row for row in node.startup_record['providers'] if row['id'] == name)
        require(descriptor['capability'] == capability and descriptor['profile'] == profile,
                'fetch-runtime-provider-profile')
        policy(client, 'provider-binding', name+'-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': operations}})
        policy(client, 'policy', name+'-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [SERVICE], 'publications': [publication], 'capability': capability,
            'operations': operations, 'resources': {'kind': kind},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        result.append({'capability': capability, 'policy': name+'-allow'})
    runtime_grants = list(result)
    descriptor = next(row for row in node.startup_record['providers'] if row['capability'] == HTTP)
    require(descriptor['profile'] == 'bounded-streaming-http-identity-v1', 'fetch-http-provider-profile')
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': HTTP, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'fetch-get', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [SERVICE], 'publications': [publication], 'capability': HTTP,
        'operations': ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body'],
        'resources': {'kind': 'http', 'origins': [origin], 'methods': ['GET'],
                      'paths': ['/conformance/json', '/conformance/status/404'], 'pathPrefixes': []},
        'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}}]})
    return runtime_grants, result+[{'capability': HTTP, 'policy': 'http-allow'}]


def require_result(row, expected, outbound):
    require(row['exitCode'] == 0 and row['decoded'] == [expected]
        and row['response']['outcomeKnown'] is True and row['processReaped'], 'fetch-runtime-typed-result')
    consumption = row['response']['data']['consumption']
    require(type(consumption['outboundRequests']) is int and consumption['outboundRequests'] == outbound
        and all(type(consumption[name]) is int and consumption[name] == 0 for name in ('childCalls', 'effectCount')),
        'fetch-runtime-external-effects')


def require_denied(row):
    require(row['exitCode'] == 4 and row['response']['error']['code'] == 'permission-denied'
        and row['response']['outcomeKnown'] is True
        and row['processReaped'] and row['decoded'] is None, 'fetch-runtime-grant-denial')
    consumption = row['response']['data']['consumption']
    require(consumption['cpuFuel'] == '0' and all(type(consumption[name]) is int and consumption[name] == 0
        for name in ('outboundRequests', 'childCalls', 'effectCount')), 'fetch-runtime-denial-effects')


def require_completed_capture_refusal(row):
    response = row.get('response') if isinstance(row, dict) else None
    observed = original_result(response)
    consumption = observed.get('consumption', {})
    data = response.get('data', {}) if isinstance(response, dict) else {}
    require(type(row) is dict and row.get('exitCode') == 4 and row.get('decoded') is None
        and row.get('processReaped') is True and observed.get('outcomeKnown') is True
        and observed.get('category') == 'platform-failure'
        and observed.get('guestTrapCode') == 'runtime-lifecycle-unproven'
        and isinstance(data, dict) and data.get('terminalState') == 'guest_trap'
        and all(type(consumption.get(name)) is str and int(consumption[name]) > 0
                for name in ('cpuFuel', 'peakMemoryBytes'))
        and all(consumption.get(name) == '0' for name in ('outboundRequests', 'childCalls', 'effectCount')),
        'fetch-runtime-completed-capture-lifecycle-refusal')


def require_completed_capture_owners(observation):
    require(type(observation) is dict and observation.get('formatVersion') == 1
        and type(observation.get('formatVersion')) is int and observation.get('qualification') is False
        and observation.get('scope') == 'host-runtime-finalization-refusals-only-no-retirement-proof'
        and observation.get('tasksIncludesManagedIdleWorkers') is True
        and observation.get('status') == 'observed' and observation.get('invalidMarkerCount') == 0
        and type(observation.get('invalidMarkerCount')) is int and observation.get('atCaptureLimit') is False
        and type(observation.get('records')) is list and len(observation['records']) == 1,
        'fetch-runtime-completed-capture-owner-observation')
    record = observation['records'][0]
    limits = {'tasks': OWNER_LIMITS['tasks'], 'executors': OWNER_LIMITS['executors'],
              'queued-work': OWNER_LIMITS['queuedWork'], 'waits': OWNER_LIMITS['waits'],
              'timers': OWNER_LIMITS['timers'], 'results': OWNER_LIMITS['results'],
              'native': OWNER_LIMITS['nativeOwners']}
    require(type(record) is dict and set(record) == set(BUCKETS)
        and all(type(record[name]) is int and 0 <= record[name] <= limits[name] for name in BUCKETS)
        and record['native'] >= 3 and all(record[name] == 0 for name in BUCKETS if name != 'native'),
        'fetch-runtime-completed-capture-native-bucket')
    return record


def retire(client, probe, target, output, name):
    value = sample(client, probe, 'after-'+name, 1)
    slots = next(row for row in value['inventory']['topology']['entries'] if row['name'] == 'invocation-cleanup-slots')
    require(slots['activeCount'] == '0', 'fetch-runtime-cleanup-slots')
    write_json(output/('after-'+name+'.json'), value)
    usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']['nodeUsage']
    require(not usage['unavailable'] and all(name in usage['counters'] and int(usage['counters'][name]) == 0
        for name in ACTIVE_COUNTERS), 'fetch-runtime-physical-owners')


def peer_evidence(observation):
    validate_peer(observation)
    require(observation['state'] == 'stopped' and observation['startedRequests'] == 3
        and observation['completedResponseWrites'] == 3 and observation['acceptedConnections'] == 3
        and observation['rejectedRequests'] == observation['committedMutations'] == 0
        and [row.get('vector') for row in observation['requests']] == ['domain-json', 'http-404', 'domain-json']
        and all(row['role'] == 'primary' for row in observation['requests']), 'fetch-runtime-peer-contact-count')
    return observation


def empty_peer_evidence(observation):
    validate_peer(observation)
    require(observation['state'] == 'stopped'
        and all(observation[name] == 0 for name in ('acceptedConnections', 'startedRequests',
            'completedResponseWrites', 'rejectedRequests', 'committedMutations', 'receivedBytes'))
        and observation['requests'] == [] and observation['events'] == [],
        'fetch-runtime-completed-capture-peer-contact')
    return observation


def build_evidence(artifact):
    """A raw Compiler output cannot substitute for normal packaged build evidence."""
    names = ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
        'recipe-inputs.json', 'package-inputs.json', 'typescript-runtime-selection.json')
    identities = {name: file_identity(artifact/name, 8*1024*1024) for name in names}
    component = file_identity(artifact/'component.wasm', 64*1024*1024)
    complete, observation, selected = (read_json(artifact/name, 8*1024*1024) for name in
        ('BUILD-COMPLETE.json', 'build-observation.json', 'typescript-runtime-selection.json'))
    require(complete.get('packageAssembled') is True
        and complete.get('componentDigest') == observation.get('componentDigest') == component['sha256']
        and observation.get('componentSize') == component['bytes']
        and complete.get('observationDigest') == identities['build-observation.json']['sha256']
        and complete.get('sourceDigest') == identities['source-inputs.json']['sha256'],
        'fetch-runtime-normal-packaged-build-required')
    require(observation.get('parameters') == {'compiler': 'componentize-js', 'bindings': 'jco',
        'language': 'typescript', 'target': 'wasm32-component', 'runtime': 'spidermonkey', 'ambientWasi': False}
        and selected.get('profile') == IMPORT_PROFILE and selected.get('qualification') == 'unknown'
        and selected.get('apiSupport') == 'not-evaluated', 'fetch-runtime-source-owned-profile-required')
    materials = observation.get('materials', [])
    for name, filename in (('build-recipe', 'recipe-inputs.json'), ('package-inputs', 'package-inputs.json'),
                           ('typescript-runtime-selection', 'typescript-runtime-selection.json')):
        matches = [row for row in materials if row.get('name') == name]
        identity = identities[filename]
        require(matches == [{'name': name, 'digest': identity['sha256'], 'size': identity['bytes']}],
            'fetch-runtime-build-material-binding')
    require((artifact/'package').is_dir(), 'fetch-runtime-package-missing')
    return {'component': component, 'documents': identities}


def execute(artifact, native, output, *, completed_capture_diagnostic=False):
    output = fresh(output)
    require(type(completed_capture_diagnostic) is bool, 'fetch-runtime-diagnostic-selection')
    if completed_capture_diagnostic:
        result = {'schemaVersion': 'latent.typescript.completed-capture-node.v1', 'status': 'in-progress',
            'scope': 'signed-completed-callback-lifecycle-observation', 'fullTicketQualification': False,
            'retainedInvocationSucceeded': False, 'physicalStoreRetirementProved': False, 'cases': []}
    else:
        result = {'schemaVersion': 'latent.typescript.fetch-runtime.v1', 'status': 'in-progress',
            'scope': 'finite-signed-default-fetch-json-body-subset', 'fullTicketQualification': False,
            'unchangedPublishedClients': 'not-run', 'privateConsumer': 'not-run', 'cases': []}
    expires, stage = time.monotonic()+300, 'sign'
    node, refusals_retained = None, False
    try:
        original = build_evidence(artifact)
        result['artifact'] = original
        environment = build_environment(output)
        signed = output/'releases'
        signed_result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, environment, timeout_seconds=30, max_output_bytes=65536)
        require(signed_result.returncode == 0, 'fetch-runtime-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-typescript-fetch-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node', 'peer'): (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_text('Bearer '+secrets.token_hex(32), encoding='ascii'); credential.chmod(0o600)
            client = RecordingClient(native['latent'], work/'client', cancellation, expires,
                evidence=output/'controls', invocation_timeout_millis=120000, control_timeout_millis=125000)
            stage = 'peer'
            peer = Process([sys.executable, str(ROOT/'tools/java_standard_http_peer.py'), '--credential', str(credential)],
                work/'peer', environment, cancellation, maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(expires, time.monotonic()+10))
            config = configuration(work/'node', signed, startup, credential)
            result['configurationIdentity'] = file_identity(config)
            stage = 'node'
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1,
                           control_refusal_diagnostic=completed_capture_diagnostic)
            cleanup.callback(node.close)
            probe = Probe(node, file_identity(native['latentd']))
            source = signed/'typescript-fetch'
            stage = 'publication'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'fetch-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            origin = startup['origins']['primary']
            address = f"http://{origin['host']}:{origin['port']}"
            if completed_capture_diagnostic:
                _runtime, authorized = grants(client, node, publication, origin)
            else:
                for phase, selected in (('runtime-denied', None), ('http-denied', 'runtime')):
                    stage = phase
                    if selected is not None:
                        runtime, authorized = grants(client, node, publication, origin)
                        target = deploy(client, source/'deployment.json', publication,
                            generation=str(target['generation']), grants=runtime)
                    row = call(client, target, 'typescript-fetch', 'run', [1, address+'/conformance/json'], 'fetch-'+phase)
                    result[phase] = row
                    require_denied(row)
                    retire(client, probe, target, output, phase)
            target = deploy(client, source/'deployment.json', publication,
                generation=str(target['generation']), grants=authorized)
            for name, mode, path, expected, outbound in execution_vectors(completed_capture_diagnostic):
                stage = name
                row = call(client, target, 'typescript-fetch', 'run', [mode, address+path], 'fetch-'+name)
                if completed_capture_diagnostic and name == 'combinator-completed-retained':
                    require_completed_capture_refusal(row)
                else:
                    require_result(row, expected, outbound)
                result['cases'].append(name)
                retire(client, probe, target, output, name)
            delete_all(client, [target['name']])
            stop(client, node)
            result['shutdown'] = stopped_record(node)
            require(result['shutdown']['reaped'] and result['shutdown']['record']['clean'], 'fetch-runtime-node-shutdown')
            if completed_capture_diagnostic:
                observation = retain_runtime_owner_refusals(node, output)
                refusals_retained = True
                owners = require_completed_capture_owners(observation)
                result['completedCapture'] = {'controlAndFreshFulfilled': True,
                    'retainedDisposition': 'runtime-lifecycle-unproven', 'hostOwnerBuckets': owners,
                    'ownerAttribution': 'aggregate-native-bucket-with-matched-release-control',
                    'physicalStoreRetirementProved': False, 'fullTicketQualification': False}
            peer.stop()
            peer_observation = json.loads(bytes(peer.buffers[0]).splitlines()[0])
            result['peer'] = (empty_peer_evidence(peer_observation) if completed_capture_diagnostic
                              else peer_evidence(peer_observation))
            require(peer.owner.finished, 'fetch-runtime-peer-not-reaped')
        require(build_evidence(artifact) == original, 'fetch-runtime-built-artifact-changed')
        if completed_capture_diagnostic:
            result.update(status='observed', signedGuestExecuted=True,
                          retainedInvocationSucceeded=False, physicalStoreRetirementProved=False)
        else:
            result.update(status='passed', signedExecution='passed', providerExecution='passed')
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        result.update(status='failed', stage=stage)
        write_json(output/'FAILED.json', result)
        raise
    finally:
        if completed_capture_diagnostic and node is not None and not refusals_retained:
            retain_runtime_owner_refusals(node, output)


def native_inputs(native, native_tuple, prepared):
    if prepared is not None:
        require(native is None and native_tuple is None, 'fetch-runtime-native-input-selection')
        return prepared_native(prepared)
    require(native is not None and native_tuple is not None, 'fetch-runtime-native-input-selection')
    binaries = {name: native/name for name in PRODUCTS}
    return binaries, ordinary_tuple(native_tuple, binaries)


def diagnose_completed_capture(qualified, output, *, native=None, native_tuple=None, prepared=None):
    """Observe a separate known lifecycle refusal using the already built signed-Fetch component."""
    qualified, output = Path(qualified).resolve(), Path(output).resolve()
    native, native_tuple, prepared = (None if path is None else Path(path).resolve()
                                     for path in (native, native_tuple, prepared))
    require(qualified != ROOT and ROOT not in qualified.parents and output != ROOT and ROOT not in output.parents
        and qualified != output and qualified not in output.parents and output not in qualified.parents,
        'fetch-runtime-completed-capture-output-separation')
    originals, identity = native_inputs(native, native_tuple, prepared)
    standard_path = qualified/'qualification.json'
    standard = read_json(standard_path)
    require(standard.get('schemaVersion') == 'latent.typescript.signed-fetch-subset.v1'
        and standard.get('status') == 'passed' and standard.get('fullTicketQualification') is False
        and standard.get('nativeTuple') == identity == read_json(qualified/'native-inputs.json')
        and standard.get('runtimeProfile') == IMPORT_PROFILE and standard.get('fetchProfile') == PROFILE,
        'fetch-runtime-completed-capture-normal-owner')
    standard_execution = qualified/'node/qualification.json'
    standard_node = read_json(standard_execution)
    require(standard.get('execution') == file_identity(standard_execution)
        and standard_node.get('status') == 'passed' and standard_node.get('signedExecution') == 'passed'
        and standard_node.get('providerExecution') == 'passed' and standard_node.get('cases') == standard.get('cases'),
        'fetch-runtime-completed-capture-normal-execution')
    app, artifact = qualified/'application', qualified/'build'
    source = inventory(snapshot(app))
    require(digest(source) == standard.get('sourceIdentityDigest')
        and all(read_file(app/'src'/name) == read_file(ROOT/FIXTURE/name)
                for name in ('main.ts', 'default-client.ts'))
        and read_file(app/'wit/world.wit') == read_file(ROOT/FIXTURE/'world.wit'),
        'fetch-runtime-completed-capture-application-source')
    build = build_evidence(artifact)
    require(standard.get('component') == build['component']
        and standard.get('build') == file_identity(artifact/'BUILD-COMPLETE.json'),
        'fetch-runtime-completed-capture-built-component')
    binaries = {name: qualified/'selected-native'/name for name in PRODUCTS}
    captured = {name: file_identity(path, 512*1024*1024) for name, path in binaries.items()}
    require(captured == {name: file_identity(path, 512*1024*1024) for name, path in originals.items()},
        'fetch-runtime-completed-capture-native-identity')
    output = fresh(output)
    try:
        observed = execute(artifact, binaries, output/'node', completed_capture_diagnostic=True)
        require(observed.get('status') == 'observed' and observed.get('signedGuestExecuted') is True
            and observed.get('retainedInvocationSucceeded') is False
            and observed.get('physicalStoreRetirementProved') is False
            and observed.get('cases') == [row[0] for row in COMPLETED_CAPTURE_VECTORS],
            'fetch-runtime-completed-capture-observation')
        require(source == inventory(snapshot(app)) and build == build_evidence(artifact)
            and captured == {name: file_identity(path, 512*1024*1024) for name, path in binaries.items()}
            and identity == native_inputs(native, native_tuple, prepared)[1]
            and standard == read_json(standard_path), 'fetch-runtime-completed-capture-input-changed')
        result = {'schemaVersion': 'latent.typescript.completed-capture-diagnostic.v1', 'status': 'observed',
            'signedGuestExecuted': True, 'retainedInvocationSucceeded': False,
            'retainedOutcome': 'runtime-lifecycle-unproven', 'physicalStoreRetirementProved': False,
            'fullTicketQualification': False, 'sourceIdentityDigest': digest(source),
            'component': build['component'], 'nativeTuple': identity,
            'standardQualification': file_identity(standard_path),
            'nodeObservation': file_identity(output/'node/qualification.json'),
            'ownerRefusals': file_identity(output/'node/runtime-owner-refusals.json'),
            'cases': observed['cases']}
        write_json(output/'observation.json', result)
        return result
    except BaseException:
        write_json(output/'FAILED.json', {'status': 'failed', 'fullTicketQualification': False,
                                          'physicalStoreRetirementProved': False})
        raise


def qualify(output, tools, engine, splicer, native=None, native_tuple=None, prepared=None):
    output, tools, engine, splicer = (Path(path).resolve() for path in (output, tools, engine, splicer))
    native, native_tuple, prepared = (None if path is None else Path(path).resolve()
                                     for path in (native, native_tuple, prepared))
    require(output != ROOT and ROOT not in output.parents, 'fetch-runtime-output-outside-checkout')
    require(all(output != path and output not in path.parents and path not in output.parents
        for path in (tools, engine, splicer, native, native_tuple, prepared) if path is not None),
        'fetch-runtime-input-output-separation')
    originals, identity = native_inputs(native, native_tuple, prepared)
    output = fresh(output)
    stage = 'capture'
    try:
        app = project(output/'application')
        source = inventory(snapshot(app))
        write_json(output/'native-inputs.json', identity)
        selected = fresh(output/'selected-native')
        binaries = {name: selected/name for name in PRODUCTS}
        for name, original in originals.items():
            shutil.copyfile(original, binaries[name])
            binaries[name].chmod(0o700)
        captured = {name: file_identity(path, 512*1024*1024) for name, path in binaries.items()}
        require(captured == {name: file_identity(path, 512*1024*1024) for name, path in originals.items()},
            'fetch-runtime-native-copy-changed')
        stage = 'normal-build-and-package'
        artifact = build(app, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
            runtime_engine=engine/'engine.wasm', runtime_engine_receipt=engine/'engine-input.json',
            runtime_splicer=splicer/'splicer', runtime_splicer_receipt=splicer/'splicer-input.json')
        stage = 'signed-provider-execution'
        observed = execute(artifact, binaries, output/'node')
        require(identity == native_inputs(native, native_tuple, prepared)[1], 'fetch-runtime-native-inputs-changed')
        require(captured == {name: file_identity(path, 512*1024*1024) for name, path in binaries.items()},
            'fetch-runtime-selected-native-changed')
        require(source == inventory(snapshot(app)), 'fetch-runtime-application-changed')
        result = {'schemaVersion': 'latent.typescript.signed-fetch-subset.v1', 'status': 'passed',
            'fullTicketQualification': False, 'sourceIdentityDigest': digest(source),
            'runtimeProfile': IMPORT_PROFILE, 'fetchProfile': PROFILE, 'nativeTuple': identity,
            'build': file_identity(artifact/'BUILD-COMPLETE.json'), 'component': file_identity(artifact/'component.wasm'),
            'execution': file_identity(output/'node/qualification.json'), 'cases': observed['cases'],
            'remainingAcceptance': ['two-unchanged-clients', 'private-consumer', 'top-level-Request',
                'Abort-streaming-cancellation-timeout-races', 'reaction-timer-memory-limits', 'cross-tenant-reuse']}
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage, 'fullTicketQualification': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'tools', 'engine', 'splicer'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('native', 'native-tuple', 'prepared-qualification'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--observe-completed-capture-from', type=Path)
    args = parser.parse_args()
    if args.observe_completed_capture_from is not None:
        print(json.dumps(diagnose_completed_capture(args.observe_completed_capture_from, args.output,
            native=args.native, native_tuple=args.native_tuple, prepared=args.prepared_qualification)))
    else:
        print(json.dumps(qualify(args.output, args.tools, args.engine, args.splicer,
            args.native, args.native_tuple, args.prepared_qualification)))
