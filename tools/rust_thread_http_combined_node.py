"""One signed, separately granted combined Rust HTTP/ThreadPool witness.

The selected diagnostic profile and its 96 MiB accounting reservation are
experimental. A passing call proves only this fixed programme, not the cost
bound, the normal builder, standard sockets, or the whole SDK milestone.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.go_standard_http_node import OPS
from tools.phase2_operator_process import require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, delete_all, deploy, finish_call, sample, start_call
from tools.rust_capsule_project import ROOT, fresh, read_json
from tools.rust_thread_http_combined_package import IMPORTS, PROFILE, SOURCE, RUN, WRAPPED
from tools.rust_thread_http_sibling_node import invoke
from tools.rust_thread_runtime_node import cleanup_owner
from tools import rust_wasi_http_runtime_node as http
from tools.static_api.node import policy
from tools.resource_tenant_node import require_denied_before_guest
from tools.standard_http.observations import require_zero_contact
from tools.standard_http.peer import Peer

NATIVE = 'latent:runtime-native/threads@0.1.0'
PROVIDERS = (
    ('clockMonotonic', http.CLOCK, ['now-nanos'], 'activation-monotonic-v1', 'clock'),
    ('activation', http.ACTIVATION, list(OPS), 'activation-owned-v1', 'clock'),
    ('activation', NATIVE, ['start'], 'conservative-native-total-starts-v1', 'context'),
    ('http-standard', http.HTTP, list(http.HTTP_OPS), 'bounded-streaming-http-identity-v1', 'http'),
)


def configure(directory, releases, peers, credentials):
    path = http.configuration(directory, releases, peers, credentials)
    value = read_json(path)
    require(value['securityProfile'] == 'local-experimental-v1'
            and value['providers']['activationRuntime']['limits'] == http.RUNTIME_LIMITS,
            'rust-combined-explicit-local-profile')
    value.setdefault('engine', {})['threadingProfile'] = PROFILE
    value['cache']['sourceBytes'] = 128 * 1024 * 1024
    providers = value['providers']
    activation = providers['activationRuntime']
    activation['nativeThreads'] = True
    providers['bindings'].append({'name': 'native-examples', 'tenant': 'examples',
        'consumerService': http.SERVICE, 'providerService': activation['identity']['service'],
        'contract': NATIVE, 'providerBinding': 'native-examples-installed'})
    require(len(providers['bindings']) == 7 and value['cache']['sourceBytes'] == 128 * 1024 * 1024,
            'rust-combined-original-ledger-and-four-explicit-bindings')
    path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
    return path


def grant(client, node, publication, peer):
    # Both activation and native registrations have the same provider id;
    # match the capability too, and authenticate all descriptors before writes.
    selected = []
    for identity, capability, operations, profile, kind in PROVIDERS:
        rows = [row for row in node.startup_record['providers']
                if row['id'] == identity and row['capability'] == capability]
        require(len(rows) == 1 and rows[0]['tenant'] == 'examples'
                and rows[0]['profile'] == profile and rows[0]['configurationEpoch'] == '1',
                'rust-combined-exact-provider-descriptor')
        selected.append((rows[0], capability, operations, profile, kind))
    result = []
    for descriptor, capability, operations, profile, kind in selected:
        identity = 'native' if capability == NATIVE else descriptor['id']
        name = identity + '-examples'
        policy(client, 'provider-binding', name + '-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': [] if kind == 'http' else operations}})
        if kind == 'http':
            resources = {'kind': 'http', 'origins': [peer.origin('primary')],
                'methods': ['GET', 'POST'], 'paths': [], 'pathPrefixes': ['/conformance/']}
            ceiling = {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}
        else:
            resources = {'kind': kind}
            ceiling = {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}
        policy(client, 'policy', name + '-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'ordinary-combined', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [http.SERVICE], 'publications': [publication], 'capability': capability,
            'operations': operations, 'resources': resources, 'ceiling': ceiling}]})
        result.append({'capability': capability, 'policy': name + '-allow'})
    require({row['capability'] for row in result} == set(IMPORTS), 'rust-combined-four-separate-grants')
    return result


def run(artifact: Path, native: dict, output: Path) -> dict:
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 2 * 1024 * 1024)
    require(component == WRAPPED, 'rust-combined-exact-retained-component')
    projection = read_json(artifact / 'qualification-projection.json', 64 * 1024)
    require(projection['componentDigest'] == component['sha256']
            and projection['selectedHostProfile'] == PROFILE
            and projection['compilerSource'] == SOURCE and projection['compilerRun'] == RUN
            and projection['compilerRunConclusion'] == 'failure'
            and projection['applicationRecompiled'] is False, 'rust-combined-original-compiler-projection')
    before = {name: file_identity(path, 512 * 1024 * 1024) for name, path in native.items()}
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=420, command_seconds=60)
    record = {'schemaVersion': 'latent.rust.combined-http.signed-witness.v1', 'status': 'incomplete',
        'component': component, 'compilerProjection': projection, 'nativeProducts': before,
        'full743Qualified': False, 'full689Qualified': False, 'physicalVerificationWorkBoundQualified': False,
        'normalRustBuilderRouteOpened': False}
    stage = 'new-neutral-packaging-and-signing'
    try:
        signed = output / 'signed'
        commands.run(stage, native['capsule_authoring'], 'demo-sign-neutral-resources', signed, artifact)
        original = {'component.wasm': component, 'build-observation.json': file_identity(artifact / 'build-observation.json')}
        record['signing'] = http.checked_signing(artifact, signed, original)
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-rust-combined-') as temporary, \
                cleanup_owner(record) as cleanup:
            work = Path(temporary)
            for name in ('node', 'client', 'peer'):
                (work / name).mkdir(mode=0o700)
            peers, credentials, protected = {}, {}, []
            for tenant in http.TENANTS:
                directory = work / 'peer' / tenant
                directory.mkdir(mode=0o700)
                secret = ('Bearer ' + secrets.token_hex(32)).encode()
                protected.append(secret)
                credentials[tenant] = directory / 'authorization'
                credentials[tenant].write_bytes(secret)
                credentials[tenant].chmod(0o600)
                peers[tenant] = Peer(secret, maximum_seconds=300)
                cleanup.callback(peers[tenant].close)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 300), evidence=output / 'controls')
            config = configure(work / 'node', signed, peers, credentials)
            record['configurationIdentity'] = file_identity(config)
            stage = 'start-local-experimental-diagnostic-node'
            node = connect(client, native['latentd'], work / 'node', config, 'examples', 1)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = Probe(node, before['latentd'])
            source = signed / http.SERVICE
            stage = 'publish-original-signed-component'
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'rust-combined-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True
                    and published['data']['release']['digest'] == component['sha256'],
                    'rust-combined-original-signed-publication')
            publication = published['data']['operation']['publication']['id']
            manifest = client.directory / 'deployment.json'
            write_json(manifest, http.deployment(read_json(source / 'deployment.json'), 'examples'))
            target = deploy(client, manifest, publication)
            grants = grant(client, node, publication, peers['examples'])
            missing = [row for row in grants if row['capability'] != NATIVE]
            target = deploy(client, manifest, publication, generation=str(target['generation']), grants=missing)
            stage = 'deny-missing-native-grant-before-entry'
            snapshots = {tenant: peer.observation() for tenant, peer in peers.items()}
            origin = peers['examples'].origin('primary')
            endpoint = f"{origin['scheme']}://{origin['host']}:{origin['port']}"
            denied = finish_call(client, start_call(client, target, 'greeting', 'greet',
                ['thread-http|' + endpoint], 'rust-combined-native-denied'))
            require_denied_before_guest(denied)
            for tenant, peer in peers.items():
                peer.poll(0)
                require_zero_contact(snapshots[tenant], peer.observation())
            record['nativeGrantRefusal'] = {'invocation': denied,
                'retirement': http.retire(client, probe, target, output, 'native-denied', population=1)}
            target = deploy(client, manifest, publication, generation=str(target['generation']), grants=grants)
            stage = 'actual-signed-held-http-sibling-programme'
            record['witness'] = invoke(client, node, target, peers['examples'], probe, output, component['sha256'])
            stage = 'physical-retirement-and-node-shutdown'
            delete_all(client, [target['name']])
            record['afterDelete'] = sample(client, probe, 'rust-combined-after-delete', 0)
            stop(client, node)
            record['nodeShutdown'] = stopped_record(node)
            require(record['nodeShutdown']['reaped'] is True
                    and record['nodeShutdown']['record']['clean'] is True, 'rust-combined-clean-node-stop')
            record['peers'] = {}
            for tenant, peer in peers.items():
                observed = peer.close()
                public = json.dumps(observed, ensure_ascii=True).encode()
                require(all(secret not in public and secret.removeprefix(b'Bearer ') not in public
                            for secret in protected), 'rust-combined-no-peer-secret-retained')
                vectors = [row.get('vector') for row in observed['requests']]
                if tenant == 'examples':
                    require(vectors in (['pending-headers', 'partial-body', 'domain-json', 'domain-json'],
                                        ['partial-body', 'pending-headers', 'domain-json', 'domain-json']),
                            'rust-combined-only-four-expected-peer-vectors')
                else:
                    require(vectors == [], 'rust-combined-foreign-peer-not-contacted')
                record['peers'][tenant] = http.check_peer_final(observed, vectors)
                write_json(output / (tenant + '-peer-final.json'), observed)
            cancellation.check()
        require(component == file_identity(artifact / 'component.wasm', 2 * 1024 * 1024)
                and before == {name: file_identity(path, 512 * 1024 * 1024) for name, path in native.items()}
                and time.monotonic() < commands.deadline, 'rust-combined-final-source-and-owner-identity')
        record.update(status='passed', actualSignedSiblingProgress=True,
                      acceptedPeerRequests=4, commands=commands.records)
        write_json(output / 'witness.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage, qualification=False, commands=commands.records)
        try:
            write_json(output / 'FAILED.json', record)
        except BaseException:
            pass
        raise
