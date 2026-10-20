"""One fresh phase Fetch component; shared source-bound V7 native products."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_typescript_fetch_runtime as base
from tools import qualify_typescript_published_fetch as published
from tools import typescript_fetch_conformance as calls
from tools import typescript_fetch_phase_fixture as fixture
from tools import typescript_phase_abort_observer as observer
from tools import typescript_published_fetch_fixture as dependencies
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase2_operator_scenario import connect
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_typescript_fetch_conformance import shutdown_owned_node
from tools.rust_capsule_node import RecordingClient, deploy, start_call, sample
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, snapshot
from tools.standard_http.vectors import DOMAIN, json_bytes
from tools.static_api.node import policy
from tools.typescript_guest.build import build

SOURCES = ('.github/workflows/typescript-fetch-phases.yml', fixture.SOURCE,
    'tools/typescript_fetch_phase_fixture.py', 'tools/qualify_typescript_fetch_phases.py',
    'tools/http_phase_wit.py', 'tools/typescript_phase_abort_observer.py',
    'tools/typescript_published_fetch_fixture.py', 'tools/qualify_typescript_published_fetch.py',
    'tools/qualify_typescript_fetch_runtime.py', 'tools/typescript_fetch_conformance.py',
    'tools/qualify_typescript_fetch_conformance.py', 'tools/http_phase_native_products.py',
    'tools/standard_http/peer.py', 'tools/standard_http/vectors.py',
    'tools/standard_http/protocol.py', 'tools/standard_http/observations.py')


def configuration(directory, releases, startup, credential):
    path = base.configuration(directory, releases, startup, credential)
    value = read_json(path)
    value['providers']['httpStreaming']['phaseTiming'] = True
    bindings = value['providers']['bindings']
    matches = [row for row in bindings if row['contract'] == base.HTTP]
    require(len(matches) == 1, 'phase-fetch-original-http-binding')
    matches[0]['contract'] = fixture.HTTP
    path.write_bytes((json.dumps(value, indent=2)+'\n').encode())
    owner = published.client_owner_configuration(path)
    return path, owner


def grants(client, node, publication, origin):
    result = []
    runtime = [(name, *values) for name, values in profiles('java').items()]
    runtime.append(('activation', base.ACTIVATION, 'activation-owned-v1', base.ACTIVATION_OPS, 'clock'))
    for name, capability, profile, operation, kind in runtime:
        operations = [operation] if isinstance(operation, str) else operation
        descriptor = next(row for row in node.startup_record['providers'] if row['id'] == name)
        require(descriptor['capability'] == capability and descriptor['profile'] == profile,
                'phase-fetch-runtime-provider')
        policy(client, 'provider-binding', name+'-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': operations}})
        policy(client, 'policy', name+'-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [base.SERVICE], 'publications': [publication], 'capability': capability,
            'operations': operations, 'resources': {'kind': kind},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        result.append({'capability': capability, 'policy': name+'-allow'})
    descriptor = next(row for row in node.startup_record['providers'] if row['capability'] == fixture.HTTP)
    require(descriptor['profile'] == 'bounded-streaming-http-phase-timing-v1', 'phase-fetch-http-provider')
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': fixture.HTTP, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'phase-fetch', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [base.SERVICE], 'publications': [publication], 'capability': fixture.HTTP,
        'operations': ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body'],
        'resources': {'kind': 'http', 'origins': [origin], 'methods': ['GET', 'POST'],
            'paths': ['/conformance/json', '/conformance/status/404', '/conformance/status/500',
                      '/conformance/hold/headers', '/conformance/body/partial',
                      '/conformance/mutation/close'], 'pathPrefixes': []},
        'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}}]})
    return result, result+[{'capability': fixture.HTTP, 'policy': 'http-allow'}]



def after_public_abort(client, node, process, peer, probe, target, mode):
    """The second accepted timer is source-ordered after exact public rejection."""
    expires = min(client.deadline, time.monotonic()+3)
    for _ in range(64):
        require(time.monotonic() < expires and not process.owner.exited(),
                'phase-fetch-public-abort-barrier-deadline')
        peer.poll(.05)
        process.drain()
        node.drain()
        observed = observer.observe(bytes(node.buffers[1]))
        require(observed['status'] in ('not-observed', 'observed'),
                'phase-fetch-public-abort-native-marker')
        records = [row for row in observed['records'] if row['mode'] == mode]
        starts = [row for row in records if row['event'] == 'start-accepted']
        entered = [row for row in records if row['event'] == 'next-entered']
        require(len(starts) <= 2, 'phase-fetch-public-abort-exact-timer-programme')
        if len(starts) != 2 or not entered or entered[-1]['sequence'] <= starts[-1]['sequence']:
            continue
        require(entered[-1]['tasks'] >= 1 and entered[-1]['waits'] >= 1
            and 1 <= entered[-1]['timers'] <= 2 and len(peer.gates()) == 1,
                'phase-fetch-public-abort-original-pending-timer')
        usage = client.call('capability', 'list', '--deployment', target['name'],
            '--include-node-usage')['data']['nodeUsage']
        require(not usage['unavailable'] and int(usage['counters']['pool_running_requests']) == 1
            and int(usage['counters']['io_calls']) >= 1, 'phase-fetch-public-abort-original-io-still-charged')
        physical = sample(client, probe, 'after-public-abort-before-peer-release', 1, active=True)
        require(not process.owner.exited(), 'phase-fetch-public-abort-caller-still-owned')
        return {'nativeRecords': observed, 'selectedMode': mode, 'providerOwners': usage,
                'physicalOwners': physical, 'publicExactReasonBeforeSecondTimer': True,
                'peerReleased': False, 'nativeHookChanged': False}
    raise ValueError('phase-fetch-public-abort-barrier-attempts')


def missing_provider(signed, native, output):
    """An actual second node omits the selected phase provider and its binding."""
    output = fresh(output)
    record = {'status': 'in-progress', 'phaseProviderInstalled': False,
              'unavailableCountersCountedAsZero': False}
    try:
        with tempfile.TemporaryDirectory(prefix='lsf-phase-absent-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('node', 'client', 'peer'):
                (work/name).mkdir(mode=0o700)
            authorization = ('Bearer '+secrets.token_hex(32)).encode()
            credential = work/'peer/authorization'
            credential.write_bytes(authorization)
            credential.chmod(0o600)
            peer = fixture.PhasePeer(authorization, maximum_seconds=120)
            cleanup.callback(peer.close)
            startup = {'destinations': peer.provider_destinations(),
                       'origins': {role: peer.origin(role) for role in ('primary', 'secondary')}}
            config, owner = configuration(work/'node', signed, startup, credential)
            value = read_json(config)
            require(value['providers']['httpStreaming']['phaseTiming'] is True,
                    'phase-fetch-absence-original-selection')
            del value['providers']['httpStreaming']
            selected = [row for row in value['providers']['bindings'] if row['contract'] == fixture.HTTP]
            require(len(selected) == 1, 'phase-fetch-absence-exact-binding')
            value['providers']['bindings'].remove(selected[0])
            config.write_bytes((json.dumps(value, indent=2)+'\n').encode())
            record.update(configurationIdentity=file_identity(config), ownerProfile=owner)
            client = RecordingClient(native['latent'], work/'client', cancellation, time.monotonic()+120,
                evidence=output/'controls', invocation_timeout_millis=120000, control_timeout_millis=125000)
            client.environment[observer.ENVIRONMENT] = '1'
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(node.close)
            require(all(row['capability'] != fixture.HTTP for row in node.startup_record['providers']),
                    'phase-fetch-absence-real-startup')
            record['startup'] = node.startup_record
            probe = Probe(node, file_identity(native['latentd']))
            source = signed/'typescript-fetch'
            publication = client.call('release', 'publish-package', source/'package', '--evidence',
                source/'evidence/index.json', '--operation-id', 'phase-absent-publish',
                '--expected-generation', '0')['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            row = calls.invoke(client, target, peer, 0, 'domain-json', 'phase-provider-absent')
            write_json(output/'invocation.json', row)
            response = row['response']
            require(row['exitCode'] == 4 and row['processReaped'] and row['decoded'] is None
                and response['outcomeKnown'] is True and response['data']['terminalState'] == 'rejected'
                and response['error']['code'] == 'incompatible-contract'
                and all(int(value) == 0 for name, value in response['data']['consumption'].items()
                        if name != 'wallTimeMicros'), 'phase-fetch-missing-provider-refusal-before-guest')
            record['invocation'] = row
            record['physicalRetirement'] = sample(client, probe, 'phase-provider-absent-retired', 1)
            record['providerObservation'] = client.call('capability', 'list', '--deployment', target['name'],
                '--include-node-usage')['data']['nodeUsage']
            record['shutdown'] = shutdown_owned_node(client, node)
            peer.close()
            observed = peer.observation()
            fixture.validate(observed)
            require(observed['state'] == 'stopped' and observed['acceptedConnections'] == 0
                and observed['startedRequests'] == 0 and not observed['requests'],
                    'phase-fetch-missing-provider-zero-real-contact')
            record['peer'] = observed
        record['status'] = 'passed'
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record['status'] = 'failed'
        write_json(output/'FAILED.json', record)
        raise


def execute(artifact, native, output):
    output = fresh(output)
    original = base.build_evidence(artifact)
    record = {'status': 'in-progress', 'cases': [], 'fullTicketQualification': False,
              'phaseTimeoutOptionsSupplied': False, 'crossTenantQualified': False}
    stage = 'sign'
    try:
        signed = output/'releases'
        result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=30, max_output_bytes=65536)
        require(result.returncode == 0, 'phase-fetch-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-phase-fetch-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('node', 'client', 'peer'):
                (work/name).mkdir(mode=0o700)
            authorization = ('Bearer '+secrets.token_hex(32)).encode()
            credential = work/'peer/authorization'
            credential.write_bytes(authorization)
            credential.chmod(0o600)
            peer = fixture.PhasePeer(authorization, maximum_seconds=300)
            cleanup.callback(peer.close)
            startup = {'destinations': peer.provider_destinations(),
                       'origins': {role: peer.origin(role) for role in ('primary', 'secondary')}}
            config, owner = configuration(work/'node', signed, startup, credential)
            record.update(configurationIdentity=file_identity(config), ownerProfile=owner)
            client = RecordingClient(native['latent'], work/'client', cancellation, time.monotonic()+300,
                evidence=output/'controls', invocation_timeout_millis=120000, control_timeout_millis=125000)
            client.environment[observer.ENVIRONMENT] = '1'
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(node.close)
            probe = Probe(node, file_identity(native['latentd']))
            source = signed/'typescript-fetch'
            stage = 'publish'
            published_release = client.call('release', 'publish-package', source/'package', '--evidence',
                source/'evidence/index.json', '--operation-id', 'phase-fetch-publish', '--expected-generation', '0')
            publication = published_release['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            for name, selected in (('runtime-denied', None), ('http-denied', 'runtime')):
                stage = name
                if selected:
                    runtime, authorized = grants(client, node, publication, startup['origins']['primary'])
                    target = deploy(client, source/'deployment.json', publication,
                        generation=str(target['generation']), grants=runtime)
                row = calls.invoke(client, target, peer, 0, 'domain-json', 'phase-'+name)
                write_json(output/('invocation-'+name+'.json'), row)
                base.require_denied(row)
                require(peer.observation()['acceptedConnections'] == 0, 'phase-fetch-denied-contact')
                base.retire(client, probe, target, output, name)
            target = deploy(client, source/'deployment.json', publication,
                generation=str(target['generation']), grants=authorized)
            for name, mode, vector, expected in fixture.VECTORS:
                stage = name
                if expected is None:
                    expected = '1|'+('ky:', 'wretch:', 'outside:')[mode]+json_bytes(DOMAIN).decode()
                activation = ('node-stop-pending' if vector == 'pending-headers' else 'node-stop-drain') if mode == 9 else 'phase-'+name
                process = start_call(client, target, 'typescript-fetch', 'run', [mode, peer.url(vector)], activation)
                try:
                    if mode == 9:
                        gate = calls.wait_gate(client, process, peer)
                        try:
                            observed = after_public_abort(client, node, process, peer, probe, target,
                                'pending' if vector == 'pending-headers' else 'drain')
                        finally:
                            node.drain()
                            write_json(output/('native-'+name+'.json'), observer.observe(bytes(node.buffers[1])))
                        write_json(output/('after-public-'+name+'.json'), observed)
                        peer.release(gate)
                    row = calls.drive(client, process, peer)
                finally:
                    process.close()
                write_json(output/('invocation-'+name+'.json'), row)
                outbound = 0 if mode in (12, 14) else 1
                base.require_result(row, expected, outbound)
                if mode in (12, 14):
                    peer.poll(0)
                    require(all(item['role'] == 'primary' for item in peer.observation()['requests']),
                            'phase-fetch-denied-target-contact')
                base.retire(client, probe, target, output, name)
                record['cases'].append({'name': name, 'result': row['decoded'], 'outbound': outbound})
            for name, vector, wall, code in (('root-cancel', 'pending-headers', 5000, 'cancelled'),
                                           ('root-deadline', 'partial-body', 3000, 'deadline-exceeded')):
                stage = name
                activation = 'phase-'+name
                process = start_call(client, target, 'typescript-fetch', 'run', [10, peer.url(vector)], activation, wall=wall)
                try:
                    calls.wait_gate(client, process, peer)
                    usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']['nodeUsage']
                    require(not usage['unavailable'] and int(usage['counters']['pool_running_requests']) == 1
                        and int(usage['counters']['io_calls']) >= 1, 'phase-fetch-held-provider-owner')
                    write_json(output/('held-'+name+'.json'), usage)
                    if name == 'root-cancel':
                        cancelled = client.call('activation', 'cancel', activation, '--reason', 'phase Fetch root cancellation')
                        require(cancelled['outcomeKnown'] and cancelled['data']['disposition'] == 'accepted',
                                'phase-fetch-root-cancel-acknowledgement')
                    row = calls.drive(client, process, peer)
                    write_json(output/('invocation-'+name+'.json'), row)
                    require(row['exitCode'] == 4 and row['response']['error']['code'] == code
                        and row['response']['outcomeKnown'] and row['processReaped']
                        and row['response']['data']['consumption']['outboundRequests'] == 1,
                        'phase-fetch-original-root-terminal')
                    peer.poll(0)
                    require(not peer.gates(), 'phase-fetch-original-transport-retired')
                    base.retire(client, probe, target, output, name)
                    record['cases'].append({'name': name, 'terminal': code, 'outbound': 1})
                finally:
                    process.close()
            stage = 'fresh'
            row = calls.invoke(client, target, peer, 0, 'domain-json', 'phase-fresh')
            write_json(output/'invocation-fresh.json', row)
            base.require_result(row, '1|ky:'+json_bytes(DOMAIN).decode(), 1)
            base.retire(client, probe, target, output, 'fresh')
            record['cases'].append({'name': 'fresh', 'result': row['decoded'], 'outbound': 1})
            record['shutdown'] = shutdown_owned_node(client, node)
            write_json(output/'shutdown.json', record['shutdown'])
            write_json(output/'timer-observer-final.json', observer.observe(bytes(node.buffers[1])))
            peer.close()
            record['peer'] = fixture.peer_evidence(peer.observation())
            write_json(output/'peer.json', record['peer'])
        stage = 'missing-provider'
        record['missingProvider'] = missing_provider(signed, native, output/'missing-provider')
        require(base.build_evidence(artifact) == original, 'phase-fetch-built-input-changed')
        record.update(status='passed', artifact=original)
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        write_json(output/'FAILED.json', record)
        raise


def qualify(acquired: Path, native_input: Path, tools: Path, output: Path):
    from tools.http_phase_native_products import native_products, verify_prepared
    acquired, native_input, tools, output = (path.resolve() for path in (acquired, native_input, tools, output))
    require(ROOT != output and ROOT not in output.parents
        and all(output != path and output not in path.parents and path not in output.parents
                for path in (acquired, native_input, tools)), 'phase-fetch-separated-inputs')
    output = fresh(output)
    identity = verify_prepared(native_input)
    native = native_products(native_input)
    before_native = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    source_before = {name: file_identity(ROOT/name, 2*1024**2) for name in SOURCES}
    write_json(output/'qualification-source-inputs.json', source_before)
    app = fixture.project(output/'application')
    captured = dependencies.capture(app, output/'outside', fixture.PRIVATE_NAME, '1.0.0')
    write_json(output/'dependency-capture.json', captured)
    before = inventory(snapshot(app))
    artifact = build(app, output/'build', native['capsule_contracts'], native['package'],
        'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
        runtime_engine=acquired/'engine/engine.wasm', runtime_engine_receipt=acquired/'engine/engine-input.json',
        runtime_splicer=acquired/'splicer/splicer', runtime_splicer_receipt=acquired/'splicer/splicer-input.json')
    bundled = read_json(artifact/'bundle-selected-inputs.json', 8*1024**2)
    require(bundled['standardFetchProfile'] == fixture.PROFILE, 'phase-fetch-actual-selected-backend')
    execution = execute(artifact, native, output/'node')
    require(before == inventory(snapshot(app)) and source_before == {
        name: file_identity(ROOT/name, 2*1024**2) for name in SOURCES}, 'phase-fetch-source-changed')
    require(identity == verify_prepared(native_input) and before_native == {
        name: file_identity(path, 512*1024**2) for name, path in native.items()}, 'phase-fetch-native-changed')
    record = {'schemaVersion': 'latent.typescript.phase-fetch.v1', 'status': 'passed',
        'qualificationSources': source_before, 'nativeProducer': identity, 'source': digest(before),
        'build': base.build_evidence(artifact), 'execution': file_identity(output/'node/qualification.json'),
        'cases': execution['cases'], 'fullTicketQualification': False}
    write_json(output/'qualification.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('acquired', 'native', 'tools', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.acquired, args.native, args.tools, args.output)))
