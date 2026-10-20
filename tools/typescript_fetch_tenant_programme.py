"""One original phase component, independent HTTP credentials, one reused cell."""
from __future__ import annotations

import copy
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import qualify_typescript_fetch_runtime as base
from tools import typescript_fetch_conformance as calls
from tools import typescript_fetch_phase_fixture as fixture
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase2_operator_scenario import connect
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_resource_tenants import client_for_foreign, credential_denial
from tools.qualify_typescript_fetch_conformance import shutdown_owned_node
from tools.resource_tenant_node import FOREIGN_TOKEN, SUBJECTS, TENANTS, require_denied_before_guest
from tools.rust_capsule_node import RecordingClient, deploy, sample, selected_revision, start_call
from tools.rust_capsule_project import fresh
from tools.standard_http.observations import validate
from tools.standard_http.vectors import DOMAIN, json_bytes
from tools.static_api.node import policy

SERVICE = 'typescript-fetch'


def register_cleanup(stack, owner, record, kind):
    def close(exception_type, _exception, _traceback):
        try:
            owner.close()
        except BaseException:
            if exception_type is None:
                raise
            record.setdefault('cleanupRefusals', []).append(kind)
        return False
    stack.push(close)


def checked_signing(source, artifact, release):
    original = read_json(artifact/'build-observation.json')
    signed = read_json(source/'build-observation.json')
    original_identity = file_identity(artifact/'build-observation.json')
    signed_identity = file_identity(source/'build-observation.json')
    require(signed_identity['sha256'] == release['observationDigest']
        and signed['source'] == original['source']
        and signed['componentDigest'] == original['componentDigest'] == release['componentDigest']
        and signed['componentSize'] == original['componentSize']
        and signed['buildType'] == original['buildType'], 'fetch-tenants-original-signing-ancestry')
    materials = {row['name']:row for row in signed['materials']}
    require(len(materials) == len(signed['materials']) and all(
        row == materials.get(row['name']) for row in original['materials'] if row['name'] != 'package-inputs'),
        'fetch-tenants-original-compiler-materials')
    inherited = materials.get('resource-original-build-observation')
    require(inherited == {'name':'resource-original-build-observation',
        'digest':original_identity['sha256'],'size':original_identity['bytes']}
        and {'resource-neutral-package-source','resource-neutral-derivation'} <= materials.keys(),
        'fetch-tenants-explicit-packaging-derivation')
    return {'originalBuildObservation':original_identity,'signedBuildObservation':signed_identity,
            'derivationMaterials':[materials[name] for name in
                ('resource-original-build-observation','resource-neutral-package-source','resource-neutral-derivation')]}


def checked_release(release, capsule, original):
    from tools.typescript_guest.runtime_profile import scoped_selected_world
    require(capsule['metadata'] == {'name':'examples/'+SERVICE,'tenant':'examples'}
        and capsule['exports'] == ['examples:typescript-fetch/api@1.0.0']
        and capsule['component']['world'] == scoped_selected_world('examples:typescript-fetch/service@1.0.0')
        and release['name'] == release['service'] == SERVICE
        and release['world'] == capsule['component']['world']
        and release['componentDigest'] == capsule['component']['digest'] == original['component']['sha256'],
        'fetch-tenants-original-component-world-and-service')


def retire(client, probe, target, output, label):
    physical = sample(client,probe,'after-'+label,2)
    slots, = [row for row in physical['inventory']['topology']['entries'] if row['name']=='invocation-cleanup-slots']
    require(slots['activeCount'] == '0','fetch-tenants-original-cleanup-slots')
    usage = client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']['nodeUsage']
    require(not usage['unavailable'] and all(name in usage['counters'] and int(usage['counters'][name]) == 0
        for name in ACTIVE_COUNTERS),'fetch-tenants-original-physical-retirement')
    write_json(output/('after-'+label+'.json'),{'physical':physical,'provider':usage})


def configure(factory, directory, signed, startups, credentials):
    path, owner = factory(directory, signed, startups['examples'], credentials['examples'])
    value = read_json(path)
    require(value['cells'][0]['capacity'] == 1 and value['cells'][0]['queueCapacity'] == 2,
            'fetch-tenants-original-single-cell')
    providers = value['providers']
    original = providers['httpStreaming']
    require(original['phaseTiming'] is True and original['identity']['tenant'] == 'examples',
            'fetch-tenants-original-phase-installation')
    second = copy.deepcopy(original)
    second['identity'].update(id='http-standard-foreign', tenant='foreign', service='foreign-http')
    second['configuration']['destinations'] = startups['foreign']['destinations']
    second['credentialDirectory'] = str(credentials['foreign'].parent)
    second['credentials'][0]['file'] = credentials['foreign'].name
    providers['additionalHttpStreaming'] = [second]
    bindings = providers['bindings']
    for binding in bindings:binding['consumerService'] = SERVICE
    providers['scalarAliases'] = []
    for name in (*profiles('java'), 'activation'):
        settings = 'activationRuntime' if name == 'activation' else name
        identity = providers[settings]['identity']
        service = 'foreign-activation' if name == 'activation' else 'foreign-runtime'
        providers['scalarAliases'].append({'source': name, 'identity': {
            **identity, 'id': name+'-foreign', 'tenant': 'foreign', 'service': service}})
        original_binding, = [b for b in bindings if b['providerBinding'] == name+'-installed']
        bindings.append({**original_binding, 'name': name+'-foreign', 'tenant': 'foreign',
                         'providerService': service})
    http, = [b for b in bindings if b['contract'] == fixture.HTTP]
    bindings.append({**http, 'name': 'http-foreign', 'tenant': 'foreign', 'providerService': 'foreign-http'})
    value['credentials'].append({'token': FOREIGN_TOKEN, 'subject': SUBJECTS['foreign'],
                                 'tenant': 'foreign', 'role': 'operator'})
    require(2+2*(len(profiles('java'))+1) <= 14, 'fetch-tenants-original-descriptor-ceiling')
    path.write_bytes((json.dumps(value, indent=2)+'\n').encode())
    return path, owner


def scoped_deployment(original, tenant):
    require(tenant in TENANTS and original['metadata'].get('tenant') is None
        and original['spec']['service'] == SERVICE and original['spec']['grants'] == [],
        'fetch-tenants-original-neutral-deployment')
    selected = copy.deepcopy(original)
    selected['metadata'].update(tenant=tenant, name='fetch-'+tenant)
    return selected


def grants(client, node, publication, tenant, origin):
    result = []
    runtime = [(name, *values) for name, values in profiles('java').items()]
    runtime.append(('activation', base.ACTIVATION, 'activation-owned-v1', base.ACTIVATION_OPS, 'clock'))
    runtime.append(('http-standard', fixture.HTTP, 'bounded-streaming-http-phase-timing-v1',
        ['open','write','finish','read','chunk-bytes','trailers','abort-upload','abort-body'], 'http'))
    for name, capability, profile, operations, kind in runtime:
        operations = [operations] if isinstance(operations, str) else operations
        provider = name if tenant == 'examples' else name+'-foreign'
        descriptor, = [row for row in node.startup_record['providers'] if row['id'] == provider]
        require(descriptor['tenant'] == tenant and descriptor['capability'] == capability
            and descriptor['profile'] == profile and descriptor['configurationEpoch'] == '1',
            'fetch-tenants-exact-scoped-installation')
        binding = 'http-installed' if kind == 'http' else name+'-installed'
        policy(client, 'provider-binding', binding, {'formatVersion':1, 'tenant':tenant,
            'capability':capability, 'providerProfile':profile,
            'configurationDigest':descriptor['configurationDigest'], 'configurationEpoch':1,
            'restriction':{'operations':[] if kind == 'http' else operations}})
        resources = {'kind': kind}
        if kind == 'http':resources.update(origins=[origin], methods=['GET'],
            paths=['/conformance/json','/conformance/hold/headers','/conformance/body/partial'], pathPrefixes=[])
        ceiling = ({'operations':64,'inputBytes':65536,'outputBytes':262144,'wallTimeMillis':5000}
                   if kind == 'http' else
                   {'operations':4096,'inputBytes':0,'outputBytes':32768,'wallTimeMillis':5000})
        selected = name+'-allow'
        policy(client, 'policy', selected, {'formatVersion':1,'tenant':tenant,'rules':[{
            'id':'fetch-tenants','effect':'allow','principals':[{'kind':'administrator','subject':SUBJECTS[tenant]}],
            'services':[SERVICE],'publications':[publication],'capability':capability,
            'operations':operations,'resources':resources,'ceiling':ceiling}]})
        result.append({'capability':capability,'policy':selected})
    return result


def execute(artifact, native, output, factory):
    output = fresh(output)
    original = base.build_evidence(artifact)
    record = {'status':'in-progress','cases':[],'componentCompilationPerformed':False,
              'sameNode':True,'singleExecutionCell':True,'fullTicketQualification':False}
    try:
        signed = output/'releases'
        signed_result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign-neutral-resources',
            str(signed), str(artifact)], output, build_environment(output), timeout_seconds=30, max_output_bytes=65536)
        require(signed_result.returncode == 0, 'fetch-tenants-normal-neutral-packaging-and-signing')
        signature = read_json(signed/'release-set.json')
        require(signature.get('tenant') is None and signature['tenants'] == list(TENANTS)
            and signature['packagingOnly'] is True and signature['componentCompilationPerformed'] is False
            and signature['trust'] == 'isolated-neutral-resource-two-tenant-test-only'
            and signature['expiresAtUnixSeconds'] > time.time()+180 and len(signature['releases']) == 1,
            'fetch-tenants-original-two-tenant-signing')
        release, = signature['releases']
        checked_release(release, read_json(artifact/'capsule.json'), original)
        record['signingAncestry'] = checked_signing(signed/SERVICE, artifact, release)
        with tempfile.TemporaryDirectory(prefix='lsf-fetch-tenants-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            (work/'node').mkdir(mode=0o700);(work/'examples').mkdir(mode=0o700)
            peers, credentials, startups = {}, {}, {}
            for tenant in TENANTS:
                directory = work/('peer-'+tenant);directory.mkdir(mode=0o700)
                authorization = ('Bearer '+secrets.token_hex(32)).encode()
                credential = directory/'authorization';credential.write_bytes(authorization);credential.chmod(0o600)
                peer = fixture.PhasePeer(authorization, maximum_seconds=180)
                register_cleanup(cleanup,peer,record,'peer')
                peers[tenant], credentials[tenant] = peer, credential
                startups[tenant] = {'destinations':peer.provider_destinations(),
                    'origins':{role:peer.origin(role) for role in ('primary','secondary')}}
            require(credentials['examples'].read_bytes() != credentials['foreign'].read_bytes(),
                    'fetch-tenants-independent-private-credential-material')
            config, owner = configure(factory, work/'node', signed, startups, credentials)
            record.update(configurationIdentity=file_identity(config), ownerProfile=owner)
            client = RecordingClient(native['latent'], work/'examples', cancellation, time.monotonic()+180,
                evidence=output/'examples-controls', invocation_timeout_millis=120000, control_timeout_millis=15000)
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            register_cleanup(cleanup,node,record,'node')
            clients = {'examples':client,'foreign':client_for_foreign(client,node,work/'foreign',output/'foreign-controls')}
            probe = Probe(node,file_identity(native['latentd']))
            targets, publications = {}, {}
            source = signed/SERVICE
            for tenant in TENANTS:
                selected = clients[tenant]
                publication = selected.call('release','publish-package',source/'package','--evidence',
                    source/'evidence/index.json','--operation-id','fetch-tenant-publish-'+tenant,
                    '--expected-generation','0')['data']['operation']['publication']['id']
                publications[tenant] = publication
                manifest = selected.directory/'deployment.json'
                write_json(manifest,scoped_deployment(read_json(source/'deployment.json'),tenant))
                target = deploy(selected,manifest,publication)
                if tenant == 'foreign':
                    denied = calls.invoke(selected,target,peers[tenant],0,'domain-json','fetch-foreign-ungranted')
                    require_denied_before_guest(denied)
                    write_json(output/'foreign-grants-not-inherited.json',denied)
                    record['cases'].append({'tenant':tenant,'kind':'ungranted','invocation':denied})
                    retire(selected,probe,target,output,'foreign-ungranted')
                    require(all(p.observation()['acceptedConnections']==0 for p in peers.values()),
                            'fetch-tenants-ungranted-zero-contact')
                targets[tenant] = deploy(selected,manifest,publication,generation=str(target['generation']),
                    grants=grants(selected,node,publication,tenant,startups[tenant]['origins']['primary']))
            require(publications['examples'] != publications['foreign'],'fetch-tenants-independent-publications')
            record['credentialDenial'] = credential_denial(clients['foreign'],targets['foreign'])
            domain = json_bytes(DOMAIN).decode()
            def invoke(tenant,mode,vector,label,expected,*,destination=None,release_after=None):
                selected,target,peer = clients[tenant],targets[tenant],peers[destination or tenant]
                revision = selected_revision(selected,target)
                before = {t:p.observation()['startedRequests'] for t,p in peers.items()}
                row = calls.invoke(selected,target,peer,mode,vector,label,release_after=release_after)
                require(row['response']['data']['resolvedRevision'] == revision
                    and revision['releaseDigest'] == original['component']['sha256'], 'fetch-tenants-original-revision')
                base.require_result(row,expected,0 if mode == 14 else 1)
                for t,p in peers.items():
                    p.poll(0)
                    require(p.observation()['startedRequests']-before[t] == (1 if t == tenant and mode != 14 else 0),
                            'fetch-tenants-exact-private-contact-scope')
                retire(selected,probe,target,output,label)
                record['cases'].append({'tenant':tenant,'kind':label,'invocation':row})
            for tenant in TENANTS:invoke(tenant,0,'domain-json','fetch-ky-'+tenant,'1|ky:'+domain)
            for tenant in TENANTS:invoke(tenant,2,'domain-json','fetch-outside-'+tenant,'1|outside:'+domain)
            invoke('examples',9,'pending-headers','fetch-tenant-public-abort','abort:exact-reason|fresh=1',release_after=2)
            invoke('foreign',0,'domain-json','fetch-foreign-after-public-abort','1|ky:'+domain)
            selected,target,peer = clients['examples'],targets['examples'],peers['examples']
            revision = selected_revision(selected,target)
            process = start_call(selected,target,SERVICE,'run',[10,peer.url('partial-body')],'fetch-tenant-root-cancel')
            try:
                calls.wait_gate(selected,process,peer)
                usage = selected.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']['nodeUsage']
                require(not usage['unavailable'] and int(usage['counters']['pool_running_requests']) == 1
                    and int(usage['counters']['io_calls']) >= 1,'fetch-tenants-original-held-provider')
                cancel = selected.call('activation','cancel','fetch-tenant-root-cancel','--reason','Owned tenant HTTP root cancellation')
                require(cancel['outcomeKnown'] and cancel['data']['disposition'] == 'accepted','fetch-tenants-root-cancel-accepted')
                row = calls.drive(selected,process,peer)
                require(row['processReaped'] and row['exitCode'] == 4 and row['response']['outcomeKnown']
                    and row['response']['error']['code'] == 'cancelled'
                    and row['response']['data']['resolvedRevision'] == revision
                    and row['response']['data']['consumption']['outboundRequests'] == 1,'fetch-tenants-original-cancel-terminal')
                peer.poll(0);require(not peer.gates(),'fetch-tenants-original-cancel-physical-close')
                retire(selected,probe,target,output,'fetch-tenant-root-cancel')
                record['cases'].append({'tenant':'examples','kind':'root-cancel','invocation':row,'heldProvider':usage})
            finally:process.close()
            invoke('foreign',0,'domain-json','fetch-foreign-after-root-cancel','1|ky:'+domain)
            invoke('foreign',14,'domain-json','fetch-foreign-denied-first-origin','extension:denied:no-contact|fresh=1',destination='examples')
            invoke('foreign',13,'domain-json','fetch-foreign-extension-own-origin','extension:1:'+domain+'|fresh=1')
            invoke('examples',0,'domain-json','fetch-first-final-fresh','1|ky:'+domain)
            require(len(record['cases']) == 12,'fetch-tenants-twelve-invocation-outcomes')
            record['shutdown'] = shutdown_owned_node(client,node)
            clients['foreign'].node = None
            record['peers'] = {}
            for tenant,peer in peers.items():
                peer.close();observed=peer.observation();validate(observed)
                expected = (['domain-json','domain-json','pending-headers','partial-body','domain-json']
                            if tenant == 'examples' else ['domain-json']*5)
                require(observed['state'] == 'stopped' and observed['acceptedConnections'] == observed['startedRequests'] == 5
                    and observed['rejectedRequests'] == observed['committedMutations'] == 0
                    and observed['completedResponseWrites'] == (4 if tenant == 'examples' else 5)
                    and [r['vector'] for r in observed['requests']] == expected
                    and all(r['role']=='primary' and r['authorizationPresent'] is True for r in observed['requests']),
                    'fetch-tenants-exact-independent-credential-peer-record')
                record['peers'][tenant] = observed
            record['startup'] = node.startup_record
        require(base.build_evidence(artifact) == original,'fetch-tenants-original-build-unchanged')
        record['status']='passed';write_json(output/'qualification.json',record);return record
    except BaseException:
        record['status']='failed';write_json(output/'FAILED.json',record);raise
