"""One captured ordinary Java component, two independent HTTP installations."""
from __future__ import annotations

import copy
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.guest_runtime_profiles import profiles
from tools import java_http_phase_node as phase
from tools.phase2_operator_process import read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_resource_tenants import client_for_foreign, credential_denial
from tools.resource_tenant_node import FOREIGN_TOKEN, SUBJECTS, TENANTS, require_denied_before_guest
from tools.rust_capsule_node import (RecordingClient, delete_all, deploy, finish_call, sample,
                                    selected_revision, start_call)
from tools.rust_capsule_project import fresh
from tools.standard_http.observations import validate as validate_peer
from tools.standard_http.peer import Peer
from tools.static_api.node import policy

SERVICE = 'java-standard-http'
ORIGINALS = ('component.wasm', 'BUILD-COMPLETE.json', 'source-inputs.json', 'recipe-inputs.json',
             'compiler-inputs.json', 'build-observation.json', 'capsule.json',
             'http-client-profile.json', 'runtime-profile.json', 'java-classpath.json')


def cleanup_owner(stack, owner, record, kind):
    def close(exception_type, _exception, _traceback):
        try:
            owner.close()
        except BaseException:
            if exception_type is None:
                raise
            record.setdefault('cleanupRefusals', []).append(kind)
        return False
    stack.push(close)


def checked_signing(signed, artifact, release_set, original):
    require(release_set.get('schemaVersion') == 'latent.capsule.demo.v1'
        and release_set.get('tenant') is None and release_set.get('tenants') == list(TENANTS)
        and release_set.get('packagingOnly') is True and release_set.get('componentCompilationPerformed') is False
        and release_set.get('trust') == 'isolated-neutral-resource-two-tenant-test-only'
        and release_set.get('inheritedCompilerObservationAsset') == 'resource-original-build-observation.json'
        and release_set.get('expiresAtUnixSeconds', 0) > time.time()+180
        and type(release_set.get('releases')) is list and len(release_set['releases']) == 1,
        'java-tenants-explicit-packaging-only-signature')
    release, = release_set['releases']
    capsule = read_json(artifact/'capsule.json')
    require(capsule['metadata'] == {'name': 'examples/'+SERVICE, 'tenant': 'examples'}
        and capsule['exports'] == ['examples:java-standard-http/api@1.0.0']
        and release['name'] == release['service'] == SERVICE
        and release['world'] == capsule['component']['world']
        and release['componentDigest'] == capsule['component']['digest'] == original['component.wasm']['sha256'],
        'java-tenants-original-component-world-and-service')
    previous = read_json(artifact/'build-observation.json')
    observation = read_json(signed/'build-observation.json')
    identity = file_identity(signed/'build-observation.json')
    require(identity['sha256'] == release['observationDigest']
        and observation['source'] == previous['source']
        and observation['parameters'] == previous['parameters']
        and observation['componentDigest'] == previous['componentDigest'] == release['componentDigest']
        and observation['componentSize'] == previous['componentSize'] == original['component.wasm']['bytes']
        and observation['buildType'] == previous['buildType']
        and observation['hermetic'] is False and observation['reproducibility'] == 'not-checked',
        'java-tenants-original-compiler-ancestry')
    materials = {row['name']: row for row in observation['materials']}
    require(len(materials) == len(observation['materials']) and all(
        materials.get(row['name']) == row for row in previous['materials'] if row['name'] != 'package-inputs'),
        'java-tenants-original-compiler-materials')
    ancestry = materials.get('resource-original-build-observation')
    require(ancestry == {'name': 'resource-original-build-observation',
        'digest': original['build-observation.json']['sha256'], 'size': original['build-observation.json']['bytes']}
        and {'resource-neutral-package-source', 'resource-neutral-derivation'} <= materials.keys(),
        'java-tenants-explicit-packaging-derivation')
    return {'release': release, 'signedBuildObservation': identity, 'originalBuildObservation':
        original['build-observation.json'], 'derivationMaterials': [materials[name] for name in
        ('resource-original-build-observation', 'resource-neutral-package-source', 'resource-neutral-derivation')]}


def configuration(directory, releases, peers, credentials, *, factory=phase.configuration):
    path = factory(directory, releases, peers['examples'], credentials['examples'], [])
    value = read_json(path)
    require(len(value['cells']) == 1 and value['cells'][0]['capacity'] == 1
        and value['cells'][0]['queueCapacity'] == 2, 'java-tenants-original-single-cell')
    providers = value['providers']
    original = providers['httpStreaming']
    require(original['phaseTiming'] is True and original['identity'] == {
        'id': 'http-standard', 'tenant': 'examples', 'service': 'http-host', 'epoch': 1}
        and not providers.get('additionalHttpStreaming') and not providers.get('scalarAliases'),
        'java-tenants-original-phase-installation')
    second = copy.deepcopy(original)
    second['identity'] = {'id': 'http-standard-foreign', 'tenant': 'foreign', 'service': 'foreign-http', 'epoch': 1}
    second['configuration']['destinations'] = peers['foreign'].provider_destinations()
    second['credentialDirectory'] = str(credentials['foreign'].parent)
    second['credentials'][0]['file'] = credentials['foreign'].name
    providers['additionalHttpStreaming'] = [second]
    bindings = providers['bindings']
    for binding in bindings:
        require(binding['tenant'] == 'examples' and binding['consumerService'] == 'examples/'+SERVICE,
                'java-tenants-original-consumer-bindings')
        binding['consumerService'] = SERVICE
    providers['scalarAliases'] = []
    for name in (*profiles('java'), 'activation'):
        settings = 'activationRuntime' if name == 'activation' else name
        identity = providers[settings]['identity']
        require(identity['tenant'] == 'examples' and identity['epoch'] == 1, 'java-tenants-original-runtime-scope')
        service = 'foreign-activation' if name == 'activation' else 'foreign-runtime'
        providers['scalarAliases'].append({'source': name, 'identity': {
            **identity, 'id': name+'-foreign', 'tenant': 'foreign', 'service': service}})
        source, = [row for row in bindings if row['providerBinding'] == name+'-installed']
        bindings.append({**source, 'name': name+'-foreign', 'tenant': 'foreign', 'providerService': service})
    source, = [row for row in bindings if row['contract'] == phase.CAPABILITY]
    bindings.append({**source, 'name': 'http-foreign', 'tenant': 'foreign', 'providerService': 'foreign-http'})
    value['credentials'].append({'token': FOREIGN_TOKEN, 'subject': SUBJECTS['foreign'],
                                 'tenant': 'foreign', 'role': 'operator'})
    require(2+2*(len(profiles('java'))+1) <= 14, 'java-tenants-original-descriptor-ceiling')
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    return path


def scoped_deployment(original, tenant):
    require(tenant in TENANTS and original['metadata'].get('tenant') is None
        and original['spec']['service'] == SERVICE and original['spec']['grants'] == [],
        'java-tenants-original-neutral-deployment')
    selected = copy.deepcopy(original)
    selected['metadata'].update(tenant=tenant, name='java-http-'+tenant)
    return selected


def grants(client, node, publication, tenant, origin):
    require(tenant in TENANTS, 'java-tenants-unknown-tenant')
    runtime = [(name, *values) for name, values in profiles('java').items()]
    runtime.append(('activation', phase.ACTIVATION, 'activation-owned-v1', phase.OPS, 'clock'))
    runtime.append(('http-standard', phase.CAPABILITY, phase.PROFILE,
        ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body'], 'http'))
    installations = []
    for name, capability, profile, operations, kind in runtime:
        operations = [operations] if isinstance(operations, str) else operations
        provider_id = name if tenant == 'examples' else name+'-foreign'
        service = ('http-host' if kind == 'http' else 'activation-host' if name == 'activation' else 'runtime-host') \
            if tenant == 'examples' else ('foreign-http' if kind == 'http' else
                                         'foreign-activation' if name == 'activation' else 'foreign-runtime')
        descriptor, = [row for row in node.startup_record['providers'] if row['id'] == provider_id]
        require(descriptor['tenant'] == tenant and descriptor['service'] == service
            and descriptor['capability'] == capability and descriptor['profile'] == profile
            and descriptor['configurationEpoch'] == '1', 'java-tenants-exact-scoped-installation')
        installations.append((name, capability, profile, operations, kind, descriptor))
    selected = []
    for name, capability, profile, operations, kind, descriptor in installations:
        binding = 'http-installed' if kind == 'http' else name+'-installed'
        policy(client, 'provider-binding', binding, {'formatVersion': 1, 'tenant': tenant,
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': [] if kind == 'http' else operations}})
        resources = {'kind': kind}
        if kind == 'http':
            resources.update(origins=[origin], methods=['GET'], paths=[
                '/conformance/json', '/conformance/hold/headers'], pathPrefixes=[])
        ceiling = ({'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}
                   if kind == 'http' else
                   {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000})
        policy_id = name+'-allow'
        policy(client, 'policy', policy_id, {'formatVersion': 1, 'tenant': tenant, 'rules': [{
            'id': 'java-tenants', 'effect': 'allow', 'principals': [
                {'kind': 'administrator', 'subject': SUBJECTS[tenant]}], 'services': [SERVICE],
            'publications': [publication], 'capability': capability, 'operations': operations,
            'resources': resources, 'ceiling': ceiling}]})
        selected.append({'capability': capability, 'policy': policy_id})
    return selected


def validate_result(row, selected, mode, *, denied_origin=False):
    response = row['response']
    require(row['processReaped'] is True and response['outcomeKnown'] is True
        and response['data'].get('resolvedRevision') == selected, 'java-tenants-original-result-owner')
    if denied_origin:
        # The unchanged fixture wraps the refused IOException in an uncaught
        # IllegalStateException. The peer counters independently prove no wire.
        require(mode == 6 and row['exitCode'] == 4 and response['category'] == 'platform-failure'
            and response['error']['code'] == 'guest-trap'
            and int(response['data']['consumption']['cpuFuel']) > 0
            and int(response['data']['consumption']['outboundRequests']) == 0,
            'java-tenants-ungranted-origin-must-not-contact')
    else:
        phase.validate_result(row, mode, selected)
        require(int(response['data']['consumption']['cpuFuel']) > 0, 'java-tenants-real-guest-invocation')


def retire(client, probe, target, output, label):
    physical = sample(client, probe, 'after-'+label, 2)
    slots, = [row for row in physical['inventory']['topology']['entries'] if row['name'] == 'invocation-cleanup-slots']
    require(slots['activeCount'] == '0', 'java-tenants-original-cleanup-slots')
    usage = phase.usage(client, target)
    require(all(int(usage['counters'][key]) == 0 for key in ACTIVE_COUNTERS), 'java-tenants-original-zero-physical-owners')
    path = output/(label+'-retired.json')
    write_json(path, {'physical': physical, 'providerUsage': usage})
    return {'path': path.name, **file_identity(path, 262144)}


def invoke(client, node, target, peer, peers, probe, mode, label, output, *, denied_origin=False):
    selected = selected_revision(client, target)
    offsets = {name: value.observation()['startedRequests'] for name, value in peers.items()}
    peer_name, = [name for name, value in peers.items() if value is peer]
    origin = peer.origin();endpoint = f"http://{origin['host']}:{origin['port']}"
    process = start_call(client, target, SERVICE, 'run', [mode, endpoint], label)
    pending = cancelled = None
    try:
        expires = min(client.deadline, time.monotonic()+125)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'java-tenants-original-invocation-deadline')
            process.drain();node.drain()
            for value in peers.values():
                value.poll(.005)
                require(value.observation()['failure'] is None, 'java-tenants-peer-failed')
            gates = [row for row in peer.gates() if row.request > offsets[peer_name]]
            require(len(gates) <= 1, 'java-tenants-ambiguous-pending-request')
            if gates and pending is None:
                gate, = gates
                require(mode in (2, 5) and gate.phase == 'headers', 'java-tenants-wrong-pending-phase')
                pending = {'request': gate.request, 'phase': gate.phase}
            if mode == 5 and pending is not None and cancelled is None:
                cancelled = {'attempted': True}
                response = client.call('activation', 'cancel', label, '--reason', 'Owned Java tenant HTTP root cancellation')
                require(response['outcomeKnown'] and response['data']['activationId'] == label
                    and response['data']['disposition'] == 'accepted', 'java-tenants-original-cancel-unconfirmed')
                cancelled['receipt'] = response
        row = finish_call(client, process)
    finally:
        process.close()
    validate_result(row, selected, mode, denied_origin=denied_origin)
    if mode in (2, 5):
        require(pending is not None, 'java-tenants-real-pending-witness-required')
    if mode == 5:
        require(cancelled is not None and 'receipt' in cancelled, 'java-tenants-real-cancel-receipt-required')
    for _ in range(64):
        for value in peers.values():value.poll(.005)
        if all(value.observation()['openConnections'] == 0 for value in peers.values()):break
    for name, value in peers.items():
        observed = value.observation()
        require(observed['openConnections'] == 0 and observed['startedRequests']-offsets[name]
            == (1 if value is peer and not denied_origin else 0), 'java-tenants-exact-credential-contact-scope')
    path = output/(label+'-case.json')
    write_json(path, {'label': label, 'mode': mode, 'selectedRevision': selected, 'invocation': row,
        'deniedOrigin': denied_origin, 'pending': pending, 'cancel': cancelled,
        'retirement': retire(client, probe, target, output, label)})
    return {'label': label, 'mode': mode, 'receipt': {'path': path.name, **file_identity(path, 262144)}}


def run(artifact, native, output, *, deadline):
    output = fresh(output)
    original = {name: file_identity(artifact/name) for name in ORIGINALS}
    products = {name: file_identity(path) for name, path in native.items()}
    result = {'schemaVersion': 'latent.java.http-tenant-node.v1', 'status': 'in-progress',
        'componentCompilationPerformed': False, 'sameNode': True, 'singleExecutionCell': True,
        'originalArtifact': original, 'nativeProducts': products, 'cases': [],
        'full688Qualified': False, 'full741Qualified': False}
    stage = 'neutral-packaging'
    try:
        signed = output/'releases'
        completed = run_bounded_result([str(native['capsule_authoring']), 'demo-sign-neutral-resources',
            str(signed), str(artifact)], output, build_environment(output),
            timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'java-tenants-normal-neutral-packaging-and-signing')
        result['signing'] = checked_signing(signed/SERVICE, artifact, read_json(signed/'release-set.json'), original)
        with tempfile.TemporaryDirectory(prefix='lsf-java-http-tenants-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('node', 'examples'):(work/name).mkdir(mode=0o700)
            peers, credentials = {}, {}
            for tenant in TENANTS:
                directory = work/('peer-'+tenant);directory.mkdir(mode=0o700)
                authorization = ('Bearer '+secrets.token_hex(32)).encode('ascii')
                credential = directory/'authorization';credential.write_bytes(authorization);credential.chmod(0o600)
                peer = Peer(authorization, maximum_seconds=300)
                cleanup_owner(cleanup, peer, result, 'peer')
                peers[tenant], credentials[tenant] = peer, credential
            require(credentials['examples'].read_bytes() != credentials['foreign'].read_bytes(),
                    'java-tenants-independent-private-credential-material')
            config = configuration(work/'node', signed, peers, credentials)
            result['configurationIdentity'] = file_identity(config)
            client = RecordingClient(native['latent'], work/'examples', cancellation,
                min(deadline, time.monotonic()+300), evidence=output/'examples-controls',
                invocation_timeout_millis=120000, control_timeout_millis=15000)
            stage = 'same-node-startup'
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            cleanup_owner(cleanup, node, result, 'node')
            clients = {'examples': client, 'foreign': client_for_foreign(client, node, work/'foreign', output/'foreign-controls')}
            for selected in clients.values(): phase.component_operator(selected)
            probe = Probe(node, products['latentd'])
            source = signed/SERVICE;targets, publications = {}, {}
            for tenant in TENANTS:
                selected = clients[tenant]
                published = selected.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                    '--operation-id', 'java-tenant-publish-'+tenant, '--expected-generation', '0')
                publication = published['data']['operation']['publication']['id']
                require(published['outcomeKnown'] and published['data']['release']['digest']
                    == original['component.wasm']['sha256'], 'java-tenants-original-publication-component')
                publications[tenant] = publication
                manifest = selected.directory/'deployment.json'
                write_json(manifest, scoped_deployment(read_json(source/'deployment.json'), tenant))
                target = deploy(selected, manifest, publication)
                if tenant == 'foreign':
                    stage = 'foreign-grants-not-inherited'
                    origin = peers[tenant].origin();endpoint = f"http://{origin['host']}:{origin['port']}"
                    process = start_call(selected, target, SERVICE, 'run', [0, endpoint], 'java-foreign-ungranted')
                    denied = finish_call(selected, process)
                    require_denied_before_guest(denied)
                    path = output/'foreign-grants-not-inherited.json';write_json(path, denied)
                    result['cases'].append({'tenant': tenant, 'kind': 'ungranted',
                        'receipt': {'path': path.name, **file_identity(path)}})
                    retire(selected, probe, target, output, 'foreign-ungranted')
                    require(all(value.observation()['acceptedConnections'] == 0 for value in peers.values()),
                            'java-tenants-ungranted-zero-contact')
                targets[tenant] = deploy(selected, manifest, publication, generation=str(target['generation']),
                    grants=grants(selected, node, publication, tenant, peers[tenant].origin()))
            require(publications['examples'] != publications['foreign'], 'java-tenants-independent-publications')
            result['publications'] = publications
            result['credentialDenial'] = credential_denial(clients['foreign'], targets['foreign'])
            programme = (
                ('examples', 0, 'webb-first', False), ('foreign', 0, 'webb-second', False),
                ('examples', 10, 'http-request-first', False), ('foreign', 10, 'http-request-second', False),
                ('examples', 2, 'read-timeout-first', False), ('foreign', 0, 'after-read-timeout-second', False),
                ('examples', 5, 'root-cancel-first', False), ('foreign', 10, 'after-root-cancel-second', False),
                ('foreign', 6, 'foreign-denied-first-origin', True),
                ('foreign', 0, 'foreign-fresh-after-refusal', False), ('examples', 6, 'first-final-fresh', False))
            for tenant, mode, label, denied in programme:
                stage = label
                result['cases'].append({'tenant': tenant, **invoke(clients[tenant], node, targets[tenant],
                    peers['examples' if denied else tenant], peers, probe, mode, 'java-tenant-'+label,
                    output, denied_origin=denied)})
            require(len(result['cases']) == 12, 'java-tenants-twelve-invocation-outcomes')
            for tenant in TENANTS:delete_all(clients[tenant], [targets[tenant]['name']])
            final = sample(client, probe, 'after-both-tenant-deletes', 0)
            write_json(output/'final-owner.json', final)
            clients['foreign'].node = None
            stop(client, node)
            shutdown = stopped_record(node)
            write_json(output/'node-stopped.json', shutdown)
            require(shutdown['reaped'] and shutdown['record']['clean'], 'java-tenants-original-clean-shutdown')
            result['peers'] = {}
            for tenant, peer in peers.items():
                observed = peer.close();path = output/(tenant+'-peer-stopped.json');write_json(path, observed)
                validate_peer(observed)
                expected = (['domain-json', 'domain-json', 'pending-headers', 'pending-headers', 'domain-json']
                            if tenant == 'examples' else ['domain-json']*5)
                require(observed['state'] == 'stopped' and observed['acceptedConnections'] == observed['startedRequests'] == 5
                    and observed['rejectedRequests'] == observed['committedMutations'] == 0
                    and observed['completedResponseWrites'] == (3 if tenant == 'examples' else 5)
                    and [row['vector'] for row in observed['requests']] == expected
                    and all(row['role'] == 'primary' and row['authorizationPresent'] is True for row in observed['requests']),
                    'java-tenants-exact-independent-credential-peer-record')
                result['peers'][tenant] = {'path': path.name, **file_identity(path, 262144)}
            result['startup'] = node.startup_record
        require(original == {name: file_identity(artifact/name) for name in ORIGINALS}
            and products == {name: file_identity(path) for name, path in native.items()},
            'java-tenants-final-source-or-native-product-drift')
        write_json(output/'final-products.json', {'artifact': original, 'native': products})
        result.update(status='passed', invocations=12, httpContacts=10,
            shutdown={'path': 'node-stopped.json', **file_identity(output/'node-stopped.json')},
            products={'path': 'final-products.json', **file_identity(output/'final-products.json')})
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        try:write_json(output/'FAILED.json', {**result, 'status': 'failed', 'stage': stage})
        except Exception:pass
        raise
