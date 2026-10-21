"""One fresh ordinary managed component joining resources and standard facilities."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import java_phase_native_products as products
from tools import dotnet_resource_runtime_fixture as fixture, dotnet_resource_runtime_node as runtime
from tools import dotnet_resource_timer_observer as observer, resource_tenant_node as tenants
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.dotnet_guest.build import build
from tools.dotnet_guest.compiler import runtime_inputs
from tools.dotnet_guest.task_wait import PROFILE as TASK_PROFILE
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import client_for_foreign, credential_denial, stop_observation_peer
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure, delete_all, deploy, sample, selected_revision
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.sdk_provider_scenario import close_failed_provider, start_provider

MATERIALS=('tools/qualify_dotnet_resource_runtime.py','tools/dotnet_resource_runtime_fixture.py',
    'tools/dotnet_resource_runtime_node.py','tools/dotnet_resource_timer_observer.py',
    'tools/dotnet_task_runtime_fixture.py','tools/dotnet_task_runtime_probe.py',
    'tools/java_phase_native_products.py','tools/java_replay_materials.py','tools/resource_runtime_node.py',
    'tools/go_node_stop_probe.py','tools/go_node_stop_timer_observer.py','tools/phase3_resource_profile.py',
    'tools/resource_tenant_node.py','tools/qualify_resource_tenants.py','tools/qualify_sdk_scratch.py',
    'tools/run_rust_capsule_workflow.py',
    'tools/rust_capsule_node.py','tools/rust_capsule_build.py','tools/rust_capsule_project.py',
    'tools/phase2_operator_process.py','tools/phase2_operator_scenario.py','tools/phase3_resource_identity.py',
    'tools/phase3_resource_os.py','tools/sdk_provider_scenario.py','tools/build_observation.py',
    'tools/build_process_signals.py','tools/dotnet_guest/compiler.py','tools/dotnet_guest/build.py',
    'tools/dotnet_guest/runtime.py','tools/dotnet_guest/task_wait.py','tools/dotnet_guest/closed_filesystem.py',
    'tools/dotnet_guest/managed_entropy.py','tools/dotnet_guest/entropy.py','tools/dotnet_guest/internal_io.py',
    'tools/dotnet_guest/composer.py','tools/dotnet_application_dependencies.py','tools/dotnet_dependency_authoring.py',
    '.github/workflows/dotnet-resource-runtime.yml')


def build_evidence(artifact):
    names=('BUILD-COMPLETE.json','build-observation.json','source-inputs.json','recipe-inputs.json',
        'package-inputs.json','runtime-profile.json','closed-runtime-coverage.json','compiler-patches.json',
        'task-wait-port.json','closed-filesystem-port.json','noncrypto-entropy-port.json','managed-entropy-port.json')
    identities={name:file_identity(artifact/name,32*1024**2) for name in names}
    component=file_identity(artifact/'component.wasm',64*1024**2)
    marker,observed,profile=(read_json(artifact/name,32*1024**2) for name in
        ('BUILD-COMPLETE.json','build-observation.json','runtime-profile.json'))
    require(marker['packageAssembled'] is True and marker['componentDigest']==observed['componentDigest']==component['sha256']
        and observed['componentSize']==component['bytes']
        and marker['observationDigest']==identities['build-observation.json']['sha256']
        and marker['sourceDigest']==identities['source-inputs.json']['sha256'],
        'resource-dotnet-normal-observed-package')
    require(observed['parameters']=={'compiler':'native-aot-llvm','bindings':'wit-bindgen-csharp','language':'csharp',
        'target':'wasi-wasm','runtime':'native-aot','locked':True,'ambientWasi':False}
        and profile['profile']=='runtime-logging' and set(profile['declaredImports'])==set(fixture.DECLARATIONS)
        and 'closedIoPort' not in profile,'resource-dotnet-current-runtime-logging-selection')
    for material,filename in (('build-recipe','recipe-inputs.json'),('package-inputs','package-inputs.json'),
        ('runtime-profile','runtime-profile.json'),('dotnet-task-wait-port','task-wait-port.json'),
        ('dotnet-closed-filesystem-port','closed-filesystem-port.json'),
        ('standard-rng-managed-port','managed-entropy-port.json')):
        selected=[row for row in observed['materials'] if row['name']==material];value=identities[filename]
        require(selected==[{'name':material,'digest':value['sha256'],'size':value['bytes']}],
            'resource-dotnet-observed-port-material')
    task=read_json(artifact/'task-wait-port.json');fs=read_json(artifact/'closed-filesystem-port.json')
    entropy=read_json(artifact/'managed-entropy-port.json');native=read_json(artifact/'noncrypto-entropy-port.json')
    require(task['profile']==TASK_PROFILE and task['completion']=='actual-task-only'
        and len(task['nativeAotReferenceBinding']['responseFiles'])==1
        and task['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest']==fs['derived']['digest']
        and fs['nativeAotReferenceBinding']['selectedCoreLibDigest']==fs['derived']['digest']
        and len(entropy['nativeAotReferenceBinding'])==1 and native['profile']=='dotnet-native-entropy-v2'
        and native['nativeLinkBinding']['secureWrapOccurrences']==1,'resource-dotnet-final-bcl-native-link-bindings')
    return {'component':component,'documents':identities,'package':package_identity(artifact,marker)}


def checked_release(release,capsule,before):
    require(capsule['metadata']=={'name':'examples/my-greeting','tenant':'examples'}
        and capsule['exports']==['examples:greeting/api@1.0.0']
        and capsule['component']['world']==release['world']=='examples:greeting/service@1.0.0'
        and release['name']==release['service']=='my-greeting'
        and release['componentDigest']==capsule['component']['digest']==before['component']['sha256'],
        'resource-dotnet-original-contracts-component-and-service')


def execute(artifact,native,output,*,late_completion=False,deadline=None):
    require(type(late_completion) is bool,'resource-dotnet-late-selector')
    output=fresh(output);before=build_evidence(artifact)
    record={'schemaVersion':'latent.dotnet.resource-runtime-node.v1','status':'incomplete',
        'fullTicketQualification':False,'runtimeGrantDenials':[],'secureOperationDenials':[]}
    remaining=600 if deadline is None else min(600,deadline-time.monotonic())
    require(remaining>=120,'resource-dotnet-original-node-time-reserved')
    commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=remaining,command_seconds=120)
    node=peer=None;clients={};stage='normal-neutral-package-signing'
    try:
        signed=output/'signed';commands.run(stage,native['capsule_authoring'],'demo-sign-neutral-resources',signed,artifact)
        signature=read_json(signed/'release-set.json')
        require(signature['schemaVersion']=='latent.capsule.demo.v1' and signature.get('tenant') is None
            and signature['tenants']==list(tenants.TENANTS) and signature['packagingOnly'] is True
            and signature['componentCompilationPerformed'] is False
            and signature['trust']=='isolated-neutral-resource-two-tenant-test-only'
            and signature['expiresAtUnixSeconds']>time.time()+180 and len(signature['releases'])==1,
            'resource-dotnet-normal-two-tenant-signature')
        record['signedRelease']=release=signature['releases'][0]
        checked_release(release,read_json(artifact/'capsule.json'),before)
        with owned_cancellation() as cancellation,tempfile.TemporaryDirectory(prefix='lsf-dotnet-resource-runtime-') as temporary:
            work=Path(temporary)
            for name in ('examples','node','peer'):(work/name).mkdir(mode=0o700)
            client=RecordingClient(native['latent'],work/'examples',cancellation,min(commands.deadline,time.monotonic()+480),
                evidence=output/'examples-controls',invocation_timeout_millis=120000,control_timeout_millis=15000)
            clients['examples']=client;peer,port=start_provider(client,work/'peer',maximum_seconds=480)
            try:
                config,settings=configure(work/'node',signed,port,language='dotnet')
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
                        '--evidence',signed/'my-greeting/evidence/index.json','--operation-id','resource-dotnet-publish-'+tenant,
                        '--expected-generation','0')
                    require(published['outcomeKnown'] and published['data']['release']['digest']==before['component']['sha256'],
                        'resource-dotnet-fresh-component-admitted')
                    publications[tenant]=published['data']['operation']['publication']['id']
                    if late_completion:
                        from tools.java_http_release_preparation import prepare
                        record.setdefault('preparation', {})[tenant] = prepare(selected,
                            publications[tenant], tenant, before['component']['sha256'], output)
                    manifest=selected.directory/'resource-deployment.json'
                    write_json(manifest,tenants.scoped_deployment(read_json(signed/'my-greeting/deployment.json'),tenant))
                    target=deploy(selected,manifest,publications[tenant])
                    target,denied=runtime.grant(selected,node,manifest,publications[tenant],target,tenant)
                    record['runtimeGrantDenials'].append({'tenant':tenant,'invocation':denied,
                        'provider':tenants.provider_idle(selected,target),
                        'physical':sample(selected,probe,'resource-dotnet-denied-'+tenant,len(publications))})
                    if not late_completion:
                        stage='ordinary-secure-operation-denial-with-noncrypto-seed-granted'
                        revision=selected_revision(selected,target)
                        denied=runtime.call_mode(selected,target,'secure-denied','resource-dotnet-secure-denied-'+tenant)
                        runtime.checked_invocation(denied,before['component']['sha256'],revision,'secure-denied')
                        record['secureOperationDenials'].append({'tenant':tenant,'invocation':denied,
                            'noncryptoBytesGranted':True,'secureU64Granted':False,
                            'provider':tenants.provider_idle(selected,target),
                            'physical':sample(selected,probe,'resource-dotnet-secure-retired-'+tenant,len(publications))})
                    targets[tenant]=runtime.grant_secure(selected,node,manifest,publications[tenant],target,tenant)
                require(publications['examples']!=publications['foreign'],'resource-dotnet-independent-publications')
                record['credentialDenial']=credential_denial(clients['foreign'],targets['foreign'])
                stage='joined-resource-callback-clock-rng-log-programme'
                if late_completion:
                    from tools.resource_late_facilities import programme
                    record['programme']=programme(clients,targets,probe,output,before['component']['sha256'],'dotnet')
                else:
                    record['programme']=runtime.programme(clients,targets,probe,output,before['component']['sha256'])
                for tenant in tenants.TENANTS:delete_all(clients[tenant],[targets[tenant]['name']])
                record['afterDeletes']=sample(client,probe,'resource-dotnet-after-deletes',0)
                clients['foreign'].node=None;stop(client,node);record['nodeShutdown']=stopped_record(node)
                record['peerShutdown']=stop_observation_peer(peer)
                stderr=bytes(node.buffers[1]);(output/'node-stderr.txt').write_bytes(stderr)
                record['nativeTimerObservations']=observer.observe(stderr)
                require(record['nativeTimerObservations']['status'] in ({'not-observed','observed'} if late_completion else {'observed'}),
                    'resource-dotnet-final-positive-timers')
            finally:
                for selected in clients.values():selected.node=None
                if node is not None:node.close();(output/'node-stderr.txt').write_bytes(bytes(node.buffers[1]))
                if peer is not None:
                    if 'peerShutdown' not in record:record['peerFailure']=close_failed_provider(peer)
                    else:peer.close()
            cancellation.check()
        require(build_evidence(artifact)==before and record['nodeShutdown']['reaped']
            and record['nodeShutdown']['record']['clean'] and time.monotonic()<commands.deadline
            and sum(client.calls for client in clients.values())<=384,'resource-dotnet-final-identity-and-retirement')
        record.update(status='passed',build=before,commands=commands.records,cliCalls={t:c.calls for t,c in clients.items()})
        if late_completion:
            record.update(lateFacilitiesOnly=True, originalProgrammePassed=False)
        write_workflow_receipt(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records)
        write_workflow_receipt(output/'FAILED.json',record);raise


def qualify(native_directory,tools,output):
    require(sys.platform=='linux' and sys.version_info>=(3,13),'resource-dotnet-linux-python313')
    native_directory,tools=(Path(path).resolve(strict=True) for path in (native_directory,tools))
    output=Path(output).absolute()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output!=path and output not in path.parents and path not in output.parents for path in (native_directory,tools)),
        'resource-dotnet-separated-inputs')
    compiled=products.verify_prepared(native_directory);native=products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    output=fresh(output);source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    materials={name:file_identity(ROOT/name) for name in MATERIALS};current=source_identity(ROOT)
    runtime_source=runtime_inputs(ROOT)
    require(read_file(tools/'runtime-inputs.json')==runtime_source,'resource-dotnet-current-prepared-runtime-inputs')
    record={'schemaVersion':'latent.dotnet.resource-runtime-qualification.v1','status':'incomplete','source':source,
        'materials':materials,'compiledNative':compiled,'consumerNativeSource':current,
        'runtimeInputs':{'sha256':digest(runtime_source),'bytes':len(runtime_source)},
        'compilerInstallation':{name:file_identity(tools/name,16*1024**2) for name in
            ('INSTALL-COMPLETE.json','runtime-inputs.json','wasi-sdk.json')},
        'nativeProductsBuilt':0,'engineRebuilt':False,'guestComponentsCompiled':0,'freshNativeAotRequired':True,
        'nativeAotCompilationAttempted':False,
        'historicalGuestQualificationRelabelled':False,'fullTicketQualification':False}
    stage='outside-transitive-managed-library-capture'
    try:
        app,record['fixture']=fixture.project(output/'project',output/'outside')
        record['capture']=fixture.capture(app,output/'outside',tools)
        before=inventory(snapshot(app));write_json(output/'capture.json',record['capture'])
        stage='one-fresh-normal-offline-native-aot-component'
        record['nativeAotCompilationAttempted']=True
        artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,offline=True)
        record.update(guestComponentsCompiled=1,nativeAotCompilationSucceeded=True)
        record['freshBuild']=build_evidence(artifact)
        stage='normal-sign-admit-and-joined-runtime-programme';observed=execute(artifact,native,output/'node')
        require(observed['status']=='passed' and inventory(snapshot(app))==before
            and products.verify_prepared(native_directory)==compiled and source_identity(ROOT)==current
            and runtime_inputs(ROOT)==runtime_source and read_file(tools/'runtime-inputs.json')==runtime_source
            and record['compilerInstallation']=={name:file_identity(tools/name,16*1024**2)
                for name in record['compilerInstallation']}
            and subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()==source
            and materials=={name:file_identity(ROOT/name) for name in MATERIALS},'resource-dotnet-final-exact-input-identities')
        record.update(status='passed',nodeReceipt=file_identity(output/'node/qualified.json'),outcomes=15,
            signedAndAdmitted=True,sourceOriginalsRemoved=True)
        write_workflow_receipt(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','tools','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(qualify(args.native,args.tools,args.output)['status'])
