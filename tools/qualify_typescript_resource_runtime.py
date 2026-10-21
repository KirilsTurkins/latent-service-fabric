"""Compile one captured resource callback component and run its finite lifecycle."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if __package__ in {None, ''}:sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import java_phase_native_products as products
from tools import go_node_stop_timer_observer as timer_observer
from tools import resource_runtime_node as runtime, resource_tenant_node as tenants
from tools import typescript_resource_runtime_fixture as fixture, typescript_resource_runtime_inputs as compiler_inputs
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import client_for_foreign, credential_denial, stop_observation_peer
from tools.qualify_typescript_fetch_runtime import build_evidence
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure, delete_all, deploy, sample
from tools.rust_capsule_project import ROOT, fresh, inventory, read_json, snapshot, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.sdk_provider_scenario import close_failed_provider, start_provider
from tools.typescript_guest.build import build
from tools.typescript_guest.runtime_profile import scoped_selected_world

MATERIALS = ('tools/qualify_typescript_resource_runtime.py','tools/resource_runtime_node.py',
    'tools/typescript_resource_runtime_fixture.py','tools/typescript_resource_runtime_inputs.py',
    'tools/typescript_fetch_replay_inputs.py','tools/java_phase_native_products.py','tools/java_replay_materials.py',
    'tools/resource_tenant_node.py','tools/qualify_resource_tenants.py','tools/rust_capsule_node.py',
    'tools/phase2_operator_process.py','tools/phase2_operator_scenario.py','tools/phase3_resource_os.py',
    'tools/phase3_resource_identity.py','tools/sdk_provider_scenario.py','tools/typescript_guest/console.mjs',
    'tools/go_node_stop_timer_observer.py','tools/go_node_stop_probe.py','tools/go_entropy_replay_inputs.py',
    'tools/qualify_typescript_fetch_runtime.py','tools/run_rust_capsule_workflow.py',
    'tools/rust_capsule_build.py','tools/rust_capsule_project.py','tools/build_observation.py',
    'tools/build_process_signals.py','tools/typescript_guest/runtime_profile.py',
    '.github/workflows/typescript-resource-runtime.yml')


def checked_release(release, capsule, build_identity, *, language='typescript'):
    # The normal compiler deliberately derives the activation world in the
    # original namespace, while preserving the original public export contract.
    require(language in ('typescript','go'),'resource-runtime-closed-build-language')
    selected=(scoped_selected_world('examples:resource-runtime/service@1.0.0')
              if language == 'typescript' else 'examples:greeting/service@1.0.0')
    export='examples:resource-runtime/api@1.0.0' if language == 'typescript' else 'examples:greeting/api@1.0.0'
    require(capsule['metadata']=={'name':'examples/my-greeting','tenant':'examples'}
            and capsule['exports']==[export]
            and capsule['component']['world']==selected
            and release['name']==release['service']=='my-greeting'
            and release['world']==selected
            and release['componentDigest']==capsule['component']['digest']==build_identity['component']['sha256'],
            'resource-runtime-original-exports-derived-world-and-component')
    return release


def execute(artifact, native, output, *, language='typescript', late_completion=False):
    require(language in ('typescript','go'),'resource-runtime-closed-execution-language')
    require(type(late_completion) is bool and (not late_completion or language == 'go'),
            'resource-runtime-closed-late-programme')
    reader=build_evidence
    if language == 'go':
        from tools.go_resource_runtime_build import build_evidence as reader
    output = fresh(output)
    record = {'schemaVersion':'latent.'+language+'.resource-runtime-node.v1','status':'incomplete',
              'fullTicketQualification':False,'nativeThreadsQualified':False,'runtimeGrantDenials':[]}
    if late_completion:
        record.update(lateCompletionProgramme='running-AfterFunc-Stop-false-accepted-facilities-v1',
                      positiveWaitForPendingQualified=False)
    before = reader(artifact);stage='normal-neutral-package-and-sign'
    commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=600,command_seconds=120)
    node=peer=None;clients={}
    try:
        signed=output/'signed'
        commands.run(stage,native['capsule_authoring'],'demo-sign-neutral-resources',signed,artifact)
        signature=read_json(signed/'release-set.json')
        require(signature['schemaVersion']=='latent.capsule.demo.v1' and signature.get('tenant') is None
                and signature['tenants']==list(tenants.TENANTS)
                and signature['packagingOnly'] is True and signature['componentCompilationPerformed'] is False
                and signature['trust']=='isolated-neutral-resource-two-tenant-test-only'
                and signature['expiresAtUnixSeconds']>time.time()+180 and len(signature['releases'])==1,
                'resource-runtime-normal-two-tenant-signing')
        release=signature['releases'][0]
        record['signedRelease']=release
        checked_release(release,read_json(artifact/'capsule.json'),before,language=language)
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-resource-runtime-') as temporary:
            work=Path(temporary)
            for name in ('examples','node','peer'):(work/name).mkdir(mode=0o700)
            client=RecordingClient(native['latent'],work/'examples',cancellation,min(commands.deadline,time.monotonic()+480),
                evidence=output/'examples-controls',invocation_timeout_millis=120000,control_timeout_millis=15000)
            clients['examples']=client
            peer,port=start_provider(client,work/'peer',maximum_seconds=480)
            try:
                config,settings=configure(work/'node',signed,port,language=language)
                runtime.configure(settings,read_json(artifact/'capsule.json'),language=language)
                config.write_bytes((json.dumps(settings,sort_keys=True,separators=(',',':'))+'\n').encode())
                stage='two-tenant-single-cell-startup'
                client.environment[timer_observer.ENVIRONMENT]='1'
                node=connect(client,native['latentd'],work/'node',config,'examples',0)
                clients['foreign']=client_for_foreign(client,node,work/'foreign',output/'foreign-controls')
                record['startup']=node.startup_record
                probe=Probe(node,file_identity(native['latentd']))
                targets,publications={},{}
                for tenant in tenants.TENANTS:
                    selected=clients[tenant]
                    published=selected.call('release','publish-package',signed/'my-greeting/package',
                        '--evidence',signed/'my-greeting/evidence/index.json',
                        '--operation-id','resource-callback-publish-'+tenant,'--expected-generation','0')
                    require(published['outcomeKnown'] and published['data']['release']['digest']==before['component']['sha256'],
                            'resource-runtime-admitted-original-component')
                    publications[tenant]=published['data']['operation']['publication']['id']
                    manifest=selected.directory/'resource-callback-deployment.json'
                    write_json(manifest,tenants.scoped_deployment(read_json(signed/'my-greeting/deployment.json'),tenant))
                    target=deploy(selected,manifest,publications[tenant])
                    targets[tenant],denied=runtime.grant(selected,node,manifest,publications[tenant],target,tenant,language=language)
                    record['runtimeGrantDenials'].append({'tenant':tenant,'invocation':denied,
                        'provider':tenants.provider_idle(selected,targets[tenant]),
                        'physical':sample(selected,probe,'resource-runtime-denied-'+tenant,len(publications))})
                require(publications['examples']!=publications['foreign'],'resource-runtime-independent-publications')
                record['credentialDenial']=credential_denial(clients['foreign'],targets['foreign'])
                stage='resource-callback-cancel-trap-foreign-fresh-programme'
                if late_completion:
                    from tools.go_resource_late import programme
                    record['programme']=programme(clients,targets,probe,output,before['component']['sha256'])
                else:
                    record['programme']=runtime.programme(clients,targets,probe,output,before['component']['sha256'],language=language)
                for tenant in tenants.TENANTS:delete_all(clients[tenant],[targets[tenant]['name']])
                record['afterDeletes']=sample(client,probe,'resource-callback-after-deletes',0)
                clients['foreign'].node=None;stop(client,node)
                record['nodeShutdown']=stopped_record(node);record['peerShutdown']=stop_observation_peer(peer)
                stderr=bytes(node.buffers[1]);(output/'node-stderr.txt').write_bytes(stderr)
                record['nativeTimerObservations']=timer_observer.observe(stderr)
                require(late_completion or record['nativeTimerObservations']['status']=='observed',
                        'resource-runtime-final-positive-timer-observations')
            finally:
                for selected in clients.values():selected.node=None
                if node is not None:node.close()
                if node is not None:
                    (output/'node-stderr.txt').write_bytes(bytes(node.buffers[1]))
                if peer is not None:
                    if 'peerShutdown' not in record:record['peerFailure']=close_failed_provider(peer)
                    else:peer.close()
            cancellation.check()
        require(reader(artifact)==before and record['nodeShutdown']['reaped']
                and record['nodeShutdown']['record']['clean'] and time.monotonic()<commands.deadline
                and sum(c.calls for c in clients.values())<=384,'resource-runtime-final-build-and-physical-retirement')
        record.update(status='passed',build=before,commands=commands.records,cliCalls={t:c.calls for t,c in clients.items()})
        write_workflow_receipt(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records)
        write_workflow_receipt(output/'FAILED.json',record);raise


def qualify(native_directory, compiler_directory, tools, output):
    require(sys.platform=='linux' and sys.version_info>=(3,13),'resource-runtime-linux-python313')
    paths=[Path(p).resolve(strict=True) for p in (native_directory,compiler_directory,tools)]
    native_directory,compiler_directory,tools=paths;output=Path(output).absolute()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
            and all(output!=p and output not in p.parents and p not in output.parents for p in paths),
            'resource-runtime-separated-owned-inputs')
    native_record=products.verify_prepared(native_directory)
    compiler_record=compiler_inputs.verify(compiler_directory)
    native=products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    output=fresh(output);source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    materials={name:file_identity(ROOT/name) for name in MATERIALS};consumer_native=source_identity(ROOT)
    record={'schemaVersion':'latent.typescript.resource-runtime-qualification.v1','status':'incomplete',
        'source':source,'materials':materials,'compiledNative':native_record,'consumerNativeSource':consumer_native,
        'compilerInputs':compiler_record,'nativeProductsBuilt':0,'engineRebuilt':False,
        'guestComponentsCompiled':1,'fullTicketQualification':False}
    stage='ordinary-outside-transitive-capture'
    try:
        app,record['fixture']=fixture.project(output/'project',output/'outside')
        record['capture']=fixture.capture(app,output/'outside')
        before=inventory(snapshot(app));write_json(output/'capture.json',record['capture'])
        stage='fresh-normal-component-build'
        artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,
            runtime_engine=compiler_directory/'engine/engine.wasm',
            runtime_engine_receipt=compiler_directory/'engine/engine-input.json',
            runtime_splicer=compiler_directory/'splicer/splicer',
            runtime_splicer_receipt=compiler_directory/'splicer/splicer-input.json')
        record['freshBuild']=build_evidence(artifact)
        stage='signed-node-resource-callback-programme'
        observed=execute(artifact,native,output/'node')
        require(observed['status']=='passed' and inventory(snapshot(app))==before
                and products.verify_prepared(native_directory)==native_record
                and compiler_inputs.verify(compiler_directory)==compiler_record
                and source_identity(ROOT)==consumer_native
                and materials=={name:file_identity(ROOT/name) for name in MATERIALS},
                'resource-runtime-final-compiler-source-and-native-identities')
        record.update(status='passed',nodeReceipt=file_identity(output/'node/qualified.json'),outcomes=13,
            signedAndAdmitted=True,sourceOriginalsRemoved=True)
        write_workflow_receipt(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',record);raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','compiler','tools','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(qualify(args.native,args.compiler,args.tools,args.output)['status'])
