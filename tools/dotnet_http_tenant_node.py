"""The same managed component, two independent HTTP installations on one execution cell."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import dotnet_http_mixed_node as mixed
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.java_http_release_preparation import prepare
from tools.java_http_tenant_node import cleanup_owner
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import client_for_foreign, credential_denial
from tools.resource_tenant_node import TENANTS, FOREIGN_TOKEN, SUBJECTS, require_denied_before_guest
from tools.rust_capsule_node import RecordingClient, deploy, delete_all, sample, start_call, finish_call
from tools.rust_capsule_project import fresh, read_json, write_json
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer

SERVICE = mixed.TEMPLATE


def configuration(directory, releases, peers, credentials):
    path = mixed.configuration(directory, releases, peers['examples'], credentials['examples'])
    value = read_json(path);providers = value['providers']
    original = providers['httpStreaming']
    require('phaseTiming' not in original and not providers.get('additionalHttpStreaming')
        and not providers.get('scalarAliases') and value['cells'][0]['capacity'] == 1
        and value['cells'][0]['queueCapacity'] == 2, 'managed-tenants-original-default-http-and-cell')
    second = copy.deepcopy(original)
    second['identity'] = {'id': 'http-standard-foreign', 'tenant': 'foreign', 'service': 'foreign-http', 'epoch': 1}
    second['configuration']['destinations'] = peers['foreign']['main'].provider_destinations()+peers['foreign']['helper'].provider_destinations()[:1]
    second['credentialDirectory'] = str(credentials['foreign']['main'].parent)
    for credential, name in zip(second['credentials'], ('main', 'helper'), strict=True):
        credential['file'] = credentials['foreign'][name].name
    providers['additionalHttpStreaming'] = [second]
    for binding in providers['bindings']:
        require(binding['consumerService'] == mixed.base.SERVICE and binding['tenant'] == 'examples',
            'managed-tenants-original-consumer')
        binding['consumerService'] = SERVICE
    providers['scalarAliases'] = []
    for name in ('clockMonotonic', 'clockWall', 'random', 'activationRuntime'):
        original_identity = providers[name]['identity']
        source = original_identity['id']
        service = 'foreign-activation' if name == 'activationRuntime' else 'foreign-entropy' if name == 'random' else 'foreign-runtime'
        providers['scalarAliases'].append({'source': source, 'identity': {
            **original_identity, 'id': source+'-foreign', 'tenant': 'foreign', 'service': service}})
        binding, = [row for row in providers['bindings'] if row['providerBinding'] == source+'-installed']
        providers['bindings'].append({**binding, 'name': binding['name']+'-foreign',
            'tenant': 'foreign', 'providerService': service})
    binding, = [row for row in providers['bindings'] if row['contract'] == mixed.base.CAPABILITY]
    providers['bindings'].append({**binding, 'name': 'http-foreign', 'tenant': 'foreign', 'providerService': 'foreign-http'})
    value['credentials'].append({'token': FOREIGN_TOKEN, 'subject': SUBJECTS['foreign'], 'tenant': 'foreign', 'role': 'operator'})
    require(len(providers['scalarAliases']) == 4 and 2+2*4 == 10 <= 14,
        'managed-tenants-original-descriptor-bound')
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf8')
    return path


def signing(signed, artifact, original):
    release_set = read_json(signed.parent/'release-set.json')
    require(release_set.get('schemaVersion') == 'latent.capsule.demo.v1'
        and release_set.get('tenant') is None and release_set.get('tenants') == list(TENANTS)
        and release_set.get('packagingOnly') is True and release_set.get('componentCompilationPerformed') is False
        and release_set.get('trust') == 'isolated-neutral-resource-two-tenant-test-only'
        and release_set.get('inheritedCompilerObservationAsset') == 'resource-original-build-observation.json'
        and release_set.get('expiresAtUnixSeconds', 0) > time.time()+180
        and type(release_set.get('releases')) is list and len(release_set['releases']) == 1,
        'managed-tenants-explicit-neutral-packaging')
    release, = release_set['releases'];capsule = read_json(artifact/'capsule.json')
    require(capsule['metadata'] == {'name': 'examples/'+SERVICE, 'tenant': 'examples'}
        and capsule['exports'] == ['examples:dotnet-standard-http/api@1.0.0']
        and release['name'] == release['service'] == SERVICE
        and release['world'] == capsule['component']['world']
        and release['componentDigest'] == capsule['component']['digest'] == original['component.wasm']['sha256'],
        'managed-tenants-original-component-and-world')
    previous = read_json(artifact/'build-observation.json');observation = read_json(signed/'build-observation.json')
    identity = file_identity(signed/'build-observation.json')
    require(identity['sha256'] == release['observationDigest'] and all(observation[key] == previous[key]
        for key in ('source', 'parameters', 'componentDigest', 'componentSize', 'buildType'))
        and observation['hermetic'] is False and observation['reproducibility'] == 'not-checked',
        'managed-tenants-original-compiler-ancestry')
    materials = {row['name']: row for row in observation['materials']}
    require(len(materials) == len(observation['materials']) and all(materials.get(row['name']) == row
        for row in previous['materials'] if row['name'] != 'package-inputs')
        and materials.get('resource-original-build-observation') == {
            'name': 'resource-original-build-observation', 'digest': original['build-observation.json']['sha256'],
            'size': original['build-observation.json']['bytes']}
        and {'resource-neutral-package-source', 'resource-neutral-derivation'} <= materials.keys(),
        'managed-tenants-unmodified-compiler-and-explicit-package-derivation')
    return {'release': release, 'signedObservation': identity,
        'inheritedObservation': original['build-observation.json'], 'componentCompilationPerformed': False}


def scoped(original, tenant):
    require(tenant in TENANTS and original['metadata'].get('tenant') is None
        and original['spec']['service'] == SERVICE and original['spec']['grants'] == [],
        'managed-tenants-neutral-deployment')
    value = copy.deepcopy(original);value['metadata'].update(tenant=tenant, name='managed-http-'+tenant)
    return value


def run(artifact, native, output, *, deadline):
    output = fresh(output);original = mixed.identities(artifact)
    products = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    record = {'schemaVersion': 'latent.dotnet.http-tenant-node.v1', 'status': 'in-progress',
        'cases': [], 'originalBuild': original, 'nativeProducts': products,
        'sameNode': True, 'singleExecutionCell': True, 'componentCompilationPerformed': False,
        'full693Qualified': False, 'full746Qualified': False}
    stage = 'neutral-packaging'
    try:
        signed = output/'releases'
        completed = run_bounded_result([str(native['capsule_authoring']), 'demo-sign-neutral-resources',
            str(signed), str(artifact)], output, build_environment(output),
            timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'managed-tenants-normal-neutral-signing')
        source = signed/SERVICE;record['signing'] = signing(source, artifact, original)
        with tempfile.TemporaryDirectory(prefix='lsf-dotnet-http-tenants-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('node', 'examples'):(work/name).mkdir(mode=0o700)
            peers, credentials = {}, {}
            for tenant in TENANTS:
                directory = work/('credentials-'+tenant);directory.mkdir(mode=0o700)
                peers[tenant], credentials[tenant] = {}, {}
                for name in ('main', 'helper'):
                    secret = ('Bearer '+secrets.token_hex(32)).encode('ascii')
                    credentials[tenant][name] = directory/name
                    credentials[tenant][name].write_bytes(secret);credentials[tenant][name].chmod(0o600)
                    peers[tenant][name] = Peer(secret, maximum_seconds=300)
                    cleanup_owner(cleanup, peers[tenant][name], record, tenant+'-'+name)
            require(len({path.read_bytes() for group in credentials.values() for path in group.values()}) == 4,
                'managed-tenants-distinct-private-credentials')
            config = configuration(work/'node', signed, peers, credentials)
            record['configuration'] = file_identity(config)
            first = RecordingClient(native['latent'], work/'examples', cancellation,
                min(deadline, time.monotonic()+300), evidence=output/'examples-controls',
                invocation_timeout_millis=120000, control_timeout_millis=15000)
            stage = 'same-node-startup'
            node = connect(first, native['latentd'], work/'node', config, 'examples', 1)
            cleanup_owner(cleanup, node, record, 'node');probe = Probe(node, products['latentd'])
            clients = {'examples': first, 'foreign': client_for_foreign(first, node, work/'foreign', output/'foreign-controls')}
            targets, publications = {}, {}
            for tenant in TENANTS:
                client = clients[tenant]
                published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                    '--operation-id', 'managed-tenant-publish-'+tenant, '--expected-generation', '0')
                publication = published['data']['operation']['publication']['id'];publications[tenant] = publication
                require(published['outcomeKnown'] is True and published['data']['release']['digest'] == original['component.wasm']['sha256'],
                    'managed-tenants-exact-original-component-publication')
                stage = tenant+'-publication-preparation'
                record.setdefault('preparation', {})[tenant] = prepare(client, publication, tenant,
                    original['component.wasm']['sha256'], output)
                manifest = client.directory/'deployment.json';write_json(manifest, scoped(read_json(source/'deployment.json'), tenant))
                target = deploy(client, manifest, publication)
                if tenant == 'foreign':
                    stage = 'foreign-no-inherited-grants'
                    row = finish_call(client, start_call(client, target, SERVICE, 'run', [20,
                        mixed.endpoint(peers[tenant]['main'])+'|'+mixed.endpoint(peers[tenant]['helper'])+'|tenant-foreign'],
                        'managed-foreign-ungranted'))
                    require_denied_before_guest(row);record['foreignPreEntryRefusal'] = row
                    require(all(peer.observation()['acceptedConnections'] == 0 for group in peers.values() for peer in group.values()),
                        'managed-tenants-ungranted-zero-contact')
                _, authorized = mixed.grants(client, node, publication,
                    [peers[tenant][name].origin() for name in ('main', 'helper')], tenant=tenant, service=SERVICE)
                targets[tenant] = deploy(client, manifest, publication, generation=str(target['generation']), grants=authorized)
            require(publications['examples'] != publications['foreign'], 'managed-tenants-distinct-publications')
            record['publications'] = publications
            record['foreignCredentialRefusal'] = credential_denial(clients['foreign'], targets['foreign'])
            programme = (
                ('examples', 20, 'first-fresh', None), ('foreign', 20, 'foreign-fresh', None),
                ('examples', 18, 'first-cancel-pending-body', None), ('foreign', 20, 'foreign-after-cancel', None),
                ('examples', 12, 'first-trap-accepted-body', None), ('foreign', 20, 'foreign-after-trap', None),
                ('foreign', 17, 'foreign-denied-first-origin', 'examples'),
                ('examples', 17, 'first-denied-foreign-origin', 'foreign'),
                ('examples', 20, 'first-final-fresh', None), ('foreign', 20, 'foreign-final-fresh', None))
            for tenant, mode, label, denied in programme:
                stage = label
                offsets = {owner: {name: peer.observation()['startedRequests'] for name, peer in group.items()}
                    for owner, group in peers.items()}
                receipt = mixed.invoke(clients[tenant], node, targets[tenant], peers[tenant], probe, mode,
                    'managed-tenant-'+label, population=2, nonce='tenant-'+tenant if mode == 20 else None,
                    denied_peer=None if denied is None else peers[denied]['main'],
                    extra_peers=tuple(peer for owner, group in peers.items() if owner != tenant for peer in group.values()))
                for owner, group in peers.items():
                    if owner != tenant:
                        require(all(peer.observation()['startedRequests'] == offsets[owner][name] for name, peer in group.items()),
                            'managed-tenants-foreign-installation-contacted')
                record['cases'].append({'tenant': tenant, **receipt})
            for tenant in TENANTS:delete_all(clients[tenant], [targets[tenant]['name']])
            write_json(output/'final-owner.json', sample(first, probe, 'after-both-managed-tenants', 0))
            clients['foreign'].node = None;stop(first, node)
            shutdown = stopped_record(node);write_json(output/'node-stopped.json', shutdown)
            require(shutdown['reaped'] is True and shutdown['record']['clean'] is True, 'managed-tenants-clean-node-stop')
            for tenant, group in peers.items():
                for name, peer in group.items():
                    value = peer.close();write_json(output/(tenant+'-'+name+'-peer-stopped.json'), value);validate_peer(value)
                    expected = 4 if name == 'main' else 0
                    require(value['acceptedConnections'] == value['startedRequests'] == expected
                        and value['openConnections'] == value['rejectedRequests'] == value['committedMutations'] == 0
                        and all(row['role'] == 'primary' and row['authorizationPresent'] is True for row in value['requests']),
                        'managed-tenants-exact-independent-authorized-contacts')
        require(original == mixed.identities(artifact) and products == {
            name: file_identity(path, 512*1024**2) for name, path in native.items()}, 'managed-tenants-final-original-inputs')
        write_json(output/'final-products.json', {'build': original, 'native': products})
        record.update(status='passed', invocations=10, preEntryRefusals=1, credentialRefusals=1, httpContacts=8,
            shutdown=file_identity(output/'node-stopped.json'), finalProducts=file_identity(output/'final-products.json'))
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        try:write_json(output/'FAILED.json', {**record, 'status': 'failed', 'stage': stage})
        except BaseException:pass
        raise
