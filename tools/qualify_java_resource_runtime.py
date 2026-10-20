"""One fresh ordinary Java component joining resources and declared facilities."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as inputs
from tools import java_resource_runtime_fixture as fixture, java_resource_runtime_node as runtime
from tools import java_resource_timer_observer as observer, resource_tenant_node as tenants
from tools import wait_runtime_native_products as products
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.java_capsule_build import FIBER_IO_PROFILE, RECIPE, build
from tools.java_guest.resources import PROFILE as RESOURCE_PROFILE
from tools.java_guest import coroutine_patch
from tools.java_standard_http_library import compiler_cache
from tools.phase2_operator_process import require,stopped_record
from tools.phase2_operator_scenario import connect,stop
from tools.phase3_resource_identity import file_identity,source_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import client_for_foreign,credential_denial,stop_observation_peer
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient,configure,delete_all,deploy,sample
from tools.rust_capsule_project import ROOT,digest,fresh,inventory,read_file,read_json,snapshot,write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.sdk_provider_scenario import close_failed_provider,start_provider

MATERIALS=tuple(sorted(set((*fixture.MATERIALS,*RECIPE,
    'tools/qualify_java_resource_runtime.py','tools/java_resource_runtime_fixture.py',
    'tools/java_resource_runtime_node.py','tools/java_resource_timer_observer.py',
    'tools/sdk_native_products_reader.py','tools/wait_runtime_native_products.py',
    'tools/java_replay_materials.py','tools/java_standard_http_library.py',
    'tools/resource_runtime_node.py','tools/resource_tenant_node.py','tools/qualify_resource_tenants.py',
    'tools/go_node_stop_probe.py','tools/go_node_stop_timer_observer.py','tools/phase3_resource_profile.py',
    'tools/qualify_sdk_scratch.py','tools/run_rust_capsule_workflow.py','tools/rust_capsule_node.py',
    'tools/phase2_operator_process.py','tools/phase2_operator_scenario.py','tools/phase3_resource_identity.py',
    'tools/phase3_resource_os.py','tools/sdk_provider_scenario.py',
    '.github/workflows/java-resource-runtime.yml'))))


def build_evidence(artifact):
    names=('BUILD-COMPLETE.json','build-observation.json','source-inputs.json','recipe-inputs.json',
        'package-inputs.json','runtime-profile.json','source-origins.json','coroutine-compiler-preparation.json',
        'java-classpath.json','application-dependencies.json','bindings.json')
    identities={name:file_identity(artifact/name,32*1024**2) for name in names}
    component=file_identity(artifact/'component.wasm',64*1024**2)
    marker,observed,profile=(read_json(artifact/name,32*1024**2) for name in
        ('BUILD-COMPLETE.json','build-observation.json','runtime-profile.json'))
    require(marker['packageAssembled'] is True and marker['javaRuntimeProfile']==FIBER_IO_PROFILE
        and marker['componentDigest']==observed['componentDigest']==component['sha256']
        and observed['componentSize']==component['bytes']
        and marker['observationDigest']==identities['build-observation.json']['sha256']
        and marker['sourceDigest']==identities['source-inputs.json']['sha256'],
        'resource-java-normal-observed-package')
    require(observed['parameters']=={'compiler':'teavm-c','entryPoint':'dev.latent.app.Capsule',
        'target':'wasm32-wasip1','bindings':'lsf-java-wit-v1','optimization':'O2','javaHeapBytes':4194304}
        and profile['profile']==FIBER_IO_PROFILE
        and {'dev.latent.app.Capsule','outside.resourceruntime.Library','outside.resourceruntimedata.Data'}
            <=set(profile['checkpointClasses']), 'resource-java-original-compiler-and-library-checkpoints')
    # The maintained builder retains this public preparation receipt; the
    # loader's private coroutine-compiler-profile.json is not a package output.
    prepared=read_json(artifact/'coroutine-compiler-preparation.json')
    require(prepared['schemaVersion']=='latent.java.coroutine-compiler-patch.v1'
        and prepared['upstreamSourceSha256']==coroutine_patch.UPSTREAM_SHA256
        and prepared['originalInputsUnchanged'] is True
        and prepared['realCorrectedIrInputsPreserved'] is True
        and prepared['realOriginalIrDefectObserved'] is True
        and set(prepared['replacedClasses'])==coroutine_patch.PATCH_CLASSES,
        'resource-java-original-public-coroutine-preparation')
    for name,filename in (('build-recipe','recipe-inputs.json'),('package-inputs','package-inputs.json'),
        ('java-runtime-profile','runtime-profile.json'),('java-source-origins','source-origins.json'),
        ('application-dependency-closure','application-dependencies.json'),('java-classpath-selection','java-classpath.json')):
        require([row for row in observed['materials'] if row['name']==name]==[
            {'name':name,'digest':identities[filename]['sha256'],'size':identities[filename]['bytes']}],
            'resource-java-observed-compiler-material')
    resources=read_json(artifact/'bindings.json')['immutableResources']
    require(resources['profile']==RESOURCE_PROFILE
        and resources['resourceInputs']==json.loads(inventory(fixture.DATA))
        and resources['streamOwnership']=='fresh-decoded-byte-array-per-open',
        'resource-java-original-transitive-resource-port')
    return {'component':component,'documents':identities,'package':package_identity(artifact,marker)}


def checked_release(release,capsule,before):
    require(capsule['metadata']=={'name':'examples/my-greeting','tenant':'examples'}
        and capsule['exports']==['examples:greeting/api@1.0.0']
        and capsule['component']['world']==release['world']=='examples:greeting/service@1.0.0'
        and release['name']==release['service']=='my-greeting'
        and release['componentDigest']==capsule['component']['digest']==before['component']['sha256'],
        'resource-java-original-world-component-service')


def execute(artifact,native,output,deadline,*,diagnostic=False):
    require(type(diagnostic) is bool,'resource-java-closed-diagnostic-selector')
    output=fresh(output);before=build_evidence(artifact)
    record={'schemaVersion':'latent.java.resource-runtime-node.v1','status':'incomplete',
        'fullTicketQualification':False,'runtimeGrantDenials':[]}
    remaining=int(min(600,deadline-time.monotonic()))
    require(remaining>=120,'resource-java-original-node-deadline')
    commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),
        deadline_seconds=remaining,command_seconds=120)
    node=peer=None;clients={};stage='normal-neutral-package-signing'
    try:
        signed=output/'signed';commands.run(stage,native['capsule_authoring'],'demo-sign-neutral-resources',signed,artifact)
        signature=read_json(signed/'release-set.json')
        require(signature['schemaVersion']=='latent.capsule.demo.v1' and signature.get('tenant') is None
            and signature['tenants']==list(tenants.TENANTS) and signature['packagingOnly'] is True
            and signature['componentCompilationPerformed'] is False
            and signature['trust']=='isolated-neutral-resource-two-tenant-test-only'
            and signature['expiresAtUnixSeconds']>time.time()+180 and len(signature['releases'])==1,
            'resource-java-normal-two-tenant-signature')
        record['signedRelease']=release=signature['releases'][0]
        checked_release(release,read_json(artifact/'capsule.json'),before)
        with owned_cancellation() as cancellation,tempfile.TemporaryDirectory(prefix='lsf-java-resource-runtime-') as temporary:
            work=Path(temporary)
            for name in ('examples','node','peer'):(work/name).mkdir(mode=0o700)
            client=RecordingClient(native['latent'],work/'examples',cancellation,min(commands.deadline,time.monotonic()+480),
                evidence=output/'examples-controls',invocation_timeout_millis=120000,control_timeout_millis=15000)
            clients['examples']=client;peer,port=start_provider(client,work/'peer',maximum_seconds=480)
            try:
                config,settings=configure(work/'node',signed,port,language='java')
                runtime.configure(settings,read_json(artifact/'capsule.json'))
                config.write_bytes((json.dumps(settings,sort_keys=True,separators=(',',':'))+'\n').encode())
                stage='original-profile-two-tenant-startup';client.environment[observer.ENVIRONMENT]='1'
                node=connect(client,native['latentd'],work/'node',config,'examples',0)
                clients['foreign']=client_for_foreign(client,node,work/'foreign',output/'foreign-controls')
                record['startup']=node.startup_record;probe=Probe(node,file_identity(native['latentd']))
                targets={};publications={}
                for tenant in tenants.TENANTS:
                    selected=clients[tenant]
                    published=selected.call('release','publish-package',signed/'my-greeting/package',
                        '--evidence',signed/'my-greeting/evidence/index.json','--operation-id','resource-java-publish-'+tenant,
                        '--expected-generation','0')
                    require(published['outcomeKnown'] and published['data']['release']['digest']==before['component']['sha256'],
                        'resource-java-fresh-component-admitted')
                    publications[tenant]=published['data']['operation']['publication']['id']
                    manifest=selected.directory/'resource-deployment.json'
                    write_json(manifest,tenants.scoped_deployment(read_json(signed/'my-greeting/deployment.json'),tenant))
                    target=deploy(selected,manifest,publications[tenant])
                    targets[tenant],denied=runtime.grants(selected,node,manifest,publications[tenant],target,tenant)
                    record['runtimeGrantDenials'].append({'tenant':tenant,'invocation':denied,
                        'provider':tenants.provider_idle(selected,targets[tenant]),
                        'physical':sample(selected,probe,'resource-java-denied-'+tenant,len(publications))})
                require(publications['examples']!=publications['foreign'],'resource-java-independent-publications')
                record['credentialDenial']=credential_denial(clients['foreign'],targets['foreign'])
                stage='ordinary-joined-resource-callback-clock-rng-log-programme'
                if diagnostic:
                    from tools.java_resource_runtime_diagnostic import programme
                    record['diagnostic']=programme(clients,targets,probe,output,before['component']['sha256'])
                else:
                    record['programme']=runtime.programme(clients,targets,probe,output,before['component']['sha256'])
                for tenant in tenants.TENANTS:delete_all(clients[tenant],[targets[tenant]['name']])
                record['afterDeletes']=sample(client,probe,'resource-java-after-deletes',0)
                clients['foreign'].node=None;stop(client,node);record['nodeShutdown']=stopped_record(node)
                record['peerShutdown']=stop_observation_peer(peer)
                stderr=bytes(node.buffers[1]);(output/'node-stderr.txt').write_bytes(stderr)
                record['nativeTimerObservations']=observer.observe(stderr)
                require(record['nativeTimerObservations']['status'] in ({'not-observed','observed'} if diagnostic else {'observed'}),
                    'resource-java-final-positive-timers')
            finally:
                for selected in clients.values():selected.node=None
                if node is not None:node.close();(output/'node-stderr.txt').write_bytes(bytes(node.buffers[1]))
                if peer is not None:
                    if 'peerShutdown' not in record:record['peerFailure']=close_failed_provider(peer)
                    else:peer.close()
            cancellation.check()
        require(build_evidence(artifact)==before and record['nodeShutdown']['reaped']
            and record['nodeShutdown']['record']['clean'] and time.monotonic()<commands.deadline
            and sum(client.calls for client in clients.values())<=384,'resource-java-final-identity-and-retirement')
        record.update(status='diagnostic-observed' if diagnostic else 'passed',diagnosticOnly=diagnostic,
            originalProgrammePassed=not diagnostic,build=before,commands=commands.records,cliCalls={t:c.calls for t,c in clients.items()})
        write_workflow_receipt(output/('diagnostic.json' if diagnostic else 'qualified.json'),record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records)
        write_workflow_receipt(output/'FAILED.json',record);raise


def qualify(native_directory,wasi_sdk,output,*,read_only_cache=None):
    require(sys.platform=='linux' and sys.version_info>=(3,13),'resource-java-linux-python313')
    native_directory,wasi_sdk=(Path(path).resolve(strict=True) for path in (native_directory,wasi_sdk))
    output=Path(output).absolute()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output!=path and output not in path.parents and path not in output.parents for path in (native_directory,wasi_sdk)),
        'resource-java-separated-inputs')
    compiled=products.verify_prepared(native_directory);native=products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    output=fresh(output);source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    materials={name:file_identity(ROOT/name) for name in MATERIALS};current=source_identity(ROOT)
    native_before={name:file_identity(path,512*1024**2) for name,path in native.items()}
    commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=1500,command_seconds=600)
    record={'schemaVersion':'latent.java.resource-runtime-qualification.v1','status':'incomplete','source':source,
        'materials':materials,'compiledNative':compiled,'consumerNativeSource':current,
        'nativeProductsBuilt':0,'engineRebuilt':False,'guestComponentsCompiled':0,
        'historicalGuestQualificationRelabelled':False,'fullTicketQualification':False}
    stage='normal-outside-transitive-jar-capture'
    try:
        record['fixture']=None
        app,record['fixture']=fixture.capture(output/'project',commands)
        original_source=inventory(snapshot(app))
        stage='normal-pinned-compiler-cache-acquisition'
        cache_root=output/'compiler';cache_root.mkdir()
        cache=compiler_cache(commands,wasi_sdk,cache_root,read_only_cache)
        record['compilerCacheSelection']=read_json(cache_root/'compiler-cache-selection.json')
        # The maintained cache-acquisition path compiles one unsigned control;
        # it is separate from the single fresh joined/signable component.
        record['unsignedCompilerControlComponents']=int(read_only_cache is None)
        record['guestComponentsCompiled']=record['unsignedCompilerControlComponents']
        stage='one-fresh-offline-fiber-io-component'
        remaining=min(900,commands.deadline-time.monotonic()-300)
        require(remaining>60,'resource-java-reserved-runtime-deadline')
        artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',wasi_sdk,timeout=remaining,
            read_only_cache=cache,runtime_profile=FIBER_IO_PROFILE)
        record['guestComponentsCompiled']+=1;record['joinedGuestComponentsCompiled']=1
        record['build']=build_evidence(artifact)
        require(read_file(artifact/'source-inputs.json')==original_source,'resource-java-exact-original-compiled-source')
        classpath=read_json(artifact/'java-classpath.json')
        require({row['id']:row['originalDigest'] for row in classpath['artifacts']}==
            {name:row['digest'] for name,row in record['fixture']['originalJars'].items()},
            'resource-java-exact-original-transitive-classpath')
        stage='fresh-sign-admit-two-tenant-joined-programme'
        record['node']=execute(artifact,native,output/'node',commands.deadline)
        require(inventory(snapshot(app))==original_source
            and inputs.verify_inputs(app,'java').identity==record['fixture']['capturedInputIdentity']
            and materials=={name:file_identity(ROOT/name) for name in materials}
            and native_before=={name:file_identity(path,512*1024**2) for name,path in native.items()}
            and compiled==products.verify_prepared(native_directory) and current==source_identity(ROOT)
            and time.monotonic()<commands.deadline,'resource-java-final-source-products-unchanged')
        record.update(status='passed',commands=commands.records)
        write_json(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records)
        write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','wasi-sdk','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--read-only-cache',type=Path)
    args=parser.parse_args()
    print(qualify(args.native,args.wasi_sdk,args.output,read_only_cache=args.read_only_cache)['status'])
