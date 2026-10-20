"""Normal packaging/signing and same-node resource isolation on retained builds.

The caller authenticates each original component producer before supplying its
exact expected identities. This module never compiles a guest or reconstructs
an old successful observation from guessed metadata.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.java_server_tenants import require_operator_token_denial
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import TOKEN, connect, stop
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_os import Probe
from tools.resource_tenant_inputs import LANGUAGES, native_products, original_build
from tools import resource_tenant_node as tenant_node
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure, delete_all, deploy, sample, call
from tools.rust_capsule_project import ROOT, decode_json, fresh, read_json, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.sdk_provider_scenario import close_failed_provider, start_provider

MATERIALS = ('tools/qualify_resource_tenants.py','tools/resource_tenant_inputs.py',
    'tools/resource_tenant_node.py','tools/resource_tenant_originals.py','tools/rust_capsule_node.py',
    'tools/rust_capsule_project.py','tools/java_server_tenants.py','tools/phase2_operator_process.py',
    'tools/phase2_operator_scenario.py','tools/phase3_resource_identity.py','tools/phase3_resource_os.py',
    'tools/phase3_resource_profile.py','tools/sdk_provider_scenario.py','tools/rust_capsule_cases.py',
    'tools/run_rust_capsule_workflow.py','tools/build_observation.py','tools/build_process.py',
    'tools/build_process_linux.py','tools/qualify_sdk_scratch.py','tools/embedded_resource_fixture.py',
    'tools/java_resource_fixture.py','tools/java_capsule_project.py','tools/dotnet_standard_console_fixture.py',
    'tools/c_compiled_resource_fixture.py')


def signed_inputs(directory, component):
    value = read_json(directory/'release-set.json')
    require(value.get('schemaVersion') == 'latent.capsule.demo.v1' and value.get('tenant') is None
        and value.get('tenants') == list(tenant_node.TENANTS)
        and value.get('trust') == 'isolated-neutral-resource-two-tenant-test-only'
        and value.get('packagingOnly') is True and value.get('componentCompilationPerformed') is False
        and value.get('inheritedCompilerObservationAsset') == 'resource-original-build-observation.json'
        and value.get('expiresAtUnixSeconds',0) > time.time()+180
        and type(value.get('releases')) is list and len(value['releases']) == 1,
        'resource-tenant-explicit-packaging-only-signature-scope')
    release = value['releases'][0]
    require(release['name'] == release['service'] == 'my-greeting'
        and release['world'] == 'examples:greeting/service@1.0.0' and release['componentDigest'] == component,
        'resource-tenant-original-world-component-neutral-service')
    return release


def client_for_foreign(original, node, work, evidence):
    work.mkdir(mode=0o700)
    client = RecordingClient(Path(original.executable),work,original.cancellation,original.deadline,
        evidence=evidence,invocation_timeout_millis=original.invocation_timeout_millis,
        control_timeout_millis=original.control_timeout_millis)
    client.config = work/'client.json'
    write_json(client.config,{'formatVersion':1,'defaultProfile':'operator','profiles':[{
        'name':'operator','endpoint':'http://'+node.startup_record['endpoint'],'tenant':'foreign',
        'token':tenant_node.FOREIGN_TOKEN,'connectTimeoutMillis':2000,'rpcTimeoutMillis':15000}]})
    client.node = node
    return client


def credential_denial(client, target):
    original = client.config
    before = client.call('deployment','get',target['name'])
    require(before['outcomeKnown'] and before['category'] == 'success'
        and before['data']['deployment']['manifest']['metadata']['tenant'] == 'foreign',
        'resource-tenant-foreign-deployment-exists')
    value = read_json(original);value['profiles'][0]['token'] = TOKEN
    spoof = client.directory/'examples-token-foreign-profile.json';write_json(spoof,value)
    try:
        client.config = spoof
        denied = client.call('deployment','get',target['name'],codes=(4,6))
        require_operator_token_denial(denied,client.last_exit_status)
        status = client.last_exit_status
    finally:client.config = original
    after = client.call('deployment','get',target['name'])
    require(after == before,'resource-tenant-denied-token-changed-publication-or-route')
    return {'status':'denied','exitCode':status,'response':denied,
        'authorizedBefore':before,'authorizedAfter':after,'credentialsRetained':False}


def stop_observation_peer(peer):
    peer.stop()
    lines = bytes(peer.buffers[0]).splitlines()
    require(len(lines) == 1 and len(lines[0]) <= 1024, 'resource-tenant-observation-peer-record')
    counts = decode_json(lines[0])
    require(type(counts) is dict and set(counts) == {'requests','authorized','unexpected','holds','closedHolds'}
        and all(type(value) is int and value == 0 for value in counts.values()),
        'resource-tenant-observation-peer-must-have-zero-contacts')
    require(peer.closed and peer.owner.finished and peer.owner.process.returncode == 0,
        'resource-tenant-observation-peer-not-reaped')
    return {'counts':counts,'closed':True,'reaped':True,'exitCode':0}


def qualify(language, original: Path, expected: dict, native: Path, producer: dict, output: Path):
    require(language in LANGUAGES and sys.platform == 'linux' and sys.version_info >= (3,13),
        'resource-tenant-linux-python313-language')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'resource-tenant-output-outside-checkout')
    source = original_build(original,language,expected)
    binaries,native_proof = native_products(native,producer)
    consumer_native_source = source_identity(ROOT)
    output = fresh(output)
    materials = {name:file_identity(ROOT/name) for name in MATERIALS}
    record = {'schemaVersion':'latent.resource.tenant-isolation.v1','language':language,'status':'incomplete',
        'original':source,'native':native_proof,'materials':materials,'guestComponentsCompiled':0,
        'packagingOperation':'fresh-neutral-packaging-and-ephemeral-signing',
        'publisherAuthenticated':False,'fullTicketQualification':False,
        'consumerNativeSource':consumer_native_source,
        'consumerNativeSourceEqualsCompiledProducer':consumer_native_source == native_proof['nativeSource'],
        'invocations':[],'providerIdle':[],'samples':[]}
    commands = Commands(ROOT,output,build_environment(output),deadline_seconds=1100,command_seconds=120)
    node = peer = None;clients = {};stage = 'fresh-neutral-package-and-sign'
    try:
        for path in binaries.values():path.chmod(0o700)
        signed = output/'signed'
        commands.run(stage,binaries['examples/capsule_authoring'],'demo-sign-neutral-resources',signed,original)
        release = signed_inputs(signed,source['component']['sha256']);record['signedRelease'] = release
        observation_path = signed/'my-greeting/build-observation.json'
        observation = read_json(observation_path)
        original_observation = read_json(original/'build-observation.json')
        inherited = [row for row in observation['materials'] if row['name'] == 'resource-original-build-observation']
        require(observation['buildType'] == original_observation['buildType']
            and observation['componentDigest'] == source['component']['sha256']
            and observation['source'] == original_observation['source']
            and observation['parameters'] == original_observation['parameters']
            and inherited == [{'name':'resource-original-build-observation',
                'digest':source['buildObservation']['sha256'],'size':source['buildObservation']['bytes']}]
            and len([row for row in observation['materials'] if row['name'] == 'resource-neutral-derivation']) == 1
            and observation['hermetic'] is False and observation['reproducibility'] == 'not-checked',
            'resource-tenant-fresh-packaging-must-retain-original-compiler-ancestry')
        record['freshPackagingObservation'] = {'identity':file_identity(observation_path),
            'observation':observation,'operation':'packaging-only','componentCompilationPerformed':False}
        capsule = read_json(original/'capsule.json');capabilities = tenant_node.required_imports(capsule)
        source_deployment = signed/'my-greeting/deployment.json'
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-resource-tenants-') as temporary:
            work = Path(temporary)
            for name in ('examples','node','peer'):(work/name).mkdir(mode=0o700)
            seconds = 1200 if language == 'typescript' else 900
            client = RecordingClient(binaries['latent'],work/'examples',cancellation,
                min(commands.deadline,time.monotonic()+seconds),evidence=output/'examples-controls',
                invocation_timeout_millis=5000 if language in {'c','rust'} else 120000)
            clients['examples'] = client
            peer,port = start_provider(client,work/'peer',maximum_seconds=seconds)
            try:
                config,settings = configure(work/'node',signed,port,runtime_grants=False,language=language)
                tenant_node.configure(settings,capsule,language)
                config.write_bytes((json.dumps(settings,sort_keys=True,separators=(',',':'))+'\n').encode())
                stage = 'same-node-startup'
                node = connect(client,binaries['latentd'],work/'node',config,'examples',0)
                clients['foreign'] = client_for_foreign(client,node,work/'foreign',output/'foreign-controls')
                probe = Probe(node,file_identity(binaries['latentd']))
                record['startup'] = node.startup_record
                targets,publications,manifests = {},{},{}
                for tenant in tenant_node.TENANTS:
                    selected = clients[tenant]
                    published = selected.call('release','publish-package',signed/'my-greeting/package',
                        '--evidence',signed/'my-greeting/evidence/index.json',
                        '--operation-id','resource-publish-'+tenant,'--expected-generation','0')
                    require(published['outcomeKnown'] and published['data']['release']['digest'] == source['component']['sha256'],
                        'resource-tenant-publication-component')
                    publications[tenant] = published['data']['operation']['publication']['id']
                    manifest = selected.directory/'resource-deployment.json'
                    write_json(manifest,tenant_node.scoped_deployment(read_json(source_deployment),tenant))
                    manifests[tenant] = manifest
                    targets[tenant] = deploy(selected,manifest,publications[tenant])
                require(publications['examples'] != publications['foreign'],'resource-tenant-independent-publications')
                record['publications'] = publications
                targets['examples'] = tenant_node.install_grants(client,node,manifests['examples'],
                    publications['examples'],targets['examples'],capabilities,language,'examples')
                if capabilities:
                    stage = 'foreign-requires-independent-runtime-grants'
                    argument,_,_ = tenant_node.sequence(language)
                    denied = call(clients['foreign'],targets['foreign'],'greeting','greet',[argument],
                        'resource-'+language+'-foreign-without-grants')
                    record['invocations'].append(denied);tenant_node.require_denied_before_guest(denied)
                    record['providerIdle'].append(tenant_node.provider_idle(clients['foreign'],targets['foreign']))
                    record['samples'].append(sample(client,probe,'foreign-no-grants-retired',2))
                    record['foreignGrantDenial'] = denied
                targets['foreign'] = tenant_node.install_grants(clients['foreign'],node,manifests['foreign'],
                    publications['foreign'],targets['foreign'],capabilities,language,'foreign')
                stage = 'credential-tenant-fence'
                record['credentialDenial'] = credential_denial(clients['foreign'],targets['foreign'])
                stage = 'resource-trap-other-tenant-and-fresh-same-tenant'
                record['resourceTenantIsolation'] = tenant_node.programme(clients,targets,probe,
                    source['component']['sha256'],language,record)
                for tenant in tenant_node.TENANTS:delete_all(clients[tenant],[targets[tenant]['name']])
                record['samples'].append(sample(client,probe,'after-both-tenant-deletes',0))
                clients['foreign'].node = None;stop(client,node)
                record['nodeShutdown'] = stopped_record(node)
                record['peerShutdown'] = stop_observation_peer(peer)
            finally:
                for selected in clients.values():selected.node = None
                if node is not None:node.close()
                if peer is not None:
                    if 'peerShutdown' not in record:record['peerFailure'] = close_failed_provider(peer)
                    else:peer.close()
            cancellation.check()
        stage = 'final-identity-and-retirement'
        require(source == original_build(original,language,expected)
            and native_proof == native_products(native,producer)[1]
            and source_identity(ROOT) == consumer_native_source
            and materials == {name:file_identity(ROOT/name) for name in MATERIALS}
            and sum(selected.calls for selected in clients.values()) <= 384
            and time.monotonic() < commands.deadline and record['nodeShutdown']['reaped']
            and record['nodeShutdown']['record']['clean'],'resource-tenant-final-source-products-physical-retirement')
        record.update(status='passed',commands=commands.records,
            cliCalls={tenant:selected.calls for tenant,selected in clients.items()})
        write_workflow_receipt(output/'qualified.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records)
        if node is not None:node.close()
        if peer is not None and 'peerShutdown' not in record and 'peerFailure' not in record:
            record['peerFailure'] = close_failed_provider(peer)
        write_workflow_receipt(output/'FAILED.json',record)
        raise


if __name__ == '__main__':
    from tools.resource_tenant_originals import ORIGINALS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language',choices=tuple(ORIGINALS))
    parser.add_argument('--verify-native-producer',type=Path)
    parser.add_argument('--verify-original-producer',type=Path)
    for name in ('original','original-producer','native','native-producer','output'):
        parser.add_argument('--'+name,type=Path)
    arguments = parser.parse_args()
    if arguments.verify_native_producer is not None:
        from tools.resource_tenant_inputs import validate_producer
        validate_producer(read_json(arguments.verify_native_producer))
        print('passed')
    elif arguments.verify_original_producer is not None:
        from tools.resource_tenant_originals import validate_producer
        validate_producer(arguments.language,read_json(arguments.verify_original_producer))
        print('passed')
    else:
        require(arguments.language is not None and all(getattr(arguments,name) is not None
            for name in ('original','original_producer','native','native_producer','output')),
            'resource-tenant-explicit-producer-and-original-paths-required')
        from tools.resource_tenant_originals import prepare
        restored,expected,acquisition = prepare(arguments.language,arguments.original.resolve(strict=True),
            read_json(arguments.original_producer),arguments.output.with_name(arguments.output.name+'-original'))
        observed = qualify(arguments.language,restored,expected,arguments.native.resolve(strict=True),
            read_json(arguments.native_producer),arguments.output)
        print(observed['status'])
