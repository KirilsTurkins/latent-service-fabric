"""One original Waki call under the existing private numeric Trap observer."""
from __future__ import annotations
import argparse
from contextlib import ExitStack,contextmanager
import json
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import diagnose_go_entry_frames as frames, diagnose_go_timer_failure as host
from tools import java_resource_private_observer as observer, rust_http_private_build as support
from tools import replay_rust_wasi_http_runtime as replay, rust_wasi_http_runtime_node as node
from tools import release_preparation_cli_native_products as products
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.java_replay_materials import api,git_source_identity
from tools.phase2_operator_process import require,stopped_record
from tools.phase2_operator_scenario import connect,stop
from tools.phase3_resource_identity import file_identity,source_identity
from tools.phase3_resource_os import Probe
from tools.resource_tenant_node import TENANTS
from tools.rust_capsule_node import RecordingClient,deploy,start_call,finish_call,selected_revision
from tools.rust_capsule_project import ROOT,digest,fresh,inventory,read_file,read_json,snapshot,write_json
from tools.standard_http.peer import Peer

FAILURE='docs/testing/evidence/rust-wasi-http-first-trap-2026-10-21.json'
COMPONENT={'sha256':'sha256:ceff069712671613cbb1d330fbb256979147b3d630b14114e59df5025193ab6f','bytes':932193}
OBSERVER_INPUTS={
    'tools/java_resource_private_observer.py':{'sha256':'sha256:396486c56ff463ef26372993756334eada35848ed6a49b7eb2cc57d5c5e8a524','bytes':4783},
    'tools/java_resource_private_build.py':{'sha256':'sha256:4ea5d223dcdb1a64856bea96ba9526f5d205d38001f549160f82d4f31f0901c5','bytes':3333}}
MATERIALS=(*replay.MATERIALS,FAILURE,'tools/diagnose_rust_wasi_http_trap.py',
    'tools/rust_http_private_build.py','tools/java_resource_private_observer.py',
    'tools/java_resource_private_build.py','tools/diagnose_go_entry_frames.py',
    'tools/diagnose_go_timer_failure.py',host.FRAME_PREFLIGHT_SOURCE)


def original_failure(value):
    require(value['source']=='d41298716494bf57943ea4d481ea5609c9ad05b4'
        and value['run']==39535525173 and value['job']==119011167982
        and value['artifact']=={'id':12318280672,'size_in_bytes':2214457,
            'digest':'sha256:f7073580f985b9a4224079336d12697acd4e70ddd9ec559368d235720f6def9c'}
        and value['outerConclusion']=='failure' and value['qualification'] is False
        and value['causeProven'] is False,'rust-private-original-failed-replay-origin')
    row=value['invocation'];response=row['response'];data=response['data']
    require(row['activation']=='examples-json' and row['exitCode']==4 and row['processReaped'] is True
        and row['decoded'] is None and response['outcomeKnown'] is True and response['requestDispatched'] is True
        and data['terminalState']=='guest_trap' and data['resolvedRevision']['releaseDigest']==COMPONENT['sha256']
        and data['consumption']['outboundRequests']==1 and response['error']['code']=='guest-trap',
        'rust-private-original-first-waki-trap')
    return row


def final_observation(client,service,output,record,*,primary_failure):
    failure=None
    try:
        stop(client,service);record['shutdown']=stopped_record(service)
    except BaseException as error:
        failure=error;record['shutdown']={'status':'refused','qualification':False}
    try:record['trapObservation']=observer.capture(bytes(service.buffers[1]))
    except BaseException as error:
        if failure is None:failure=error
        record['trapObservation']={'status':'refused','qualification':False}
    try:write_json(output/'observation.json',record)
    except BaseException as error:
        if failure is None:failure=error
    if failure is not None and not primary_failure:raise failure


@contextmanager
def owned_cleanup(record):
    stack=ExitStack()
    try:yield stack
    except BaseException:
        try:stack.close()
        except BaseException:
            record['cleanupRefused']=True;record['originalFailurePreserved']=True
        raise
    else:stack.close()


def execute(artifact,binaries,output,deadline):
    output=fresh(output);record={'qualification':False,'status':'incomplete','invocations':[]}
    environment=build_environment(output);signed=output/'releases'
    original={name:file_identity(artifact/name) for name in ('component.wasm','build-observation.json')}
    result=run_bounded_result([str(binaries['capsule_authoring']),'demo-sign-neutral-resources',str(signed),str(artifact)],
        output,environment,min(30,deadline-time.monotonic()),65536)
    require(result.returncode==0,'rust-private-normal-signing')
    record['signing']=node.checked_signing(artifact,signed,original)
    with tempfile.TemporaryDirectory(prefix='lsf-rust-http-private-') as temporary, \
            owned_cancellation() as cancellation,owned_cleanup(record) as cleanup:
        work=Path(temporary)
        for name in ('node','examples','peers'):(work/name).mkdir(mode=0o700)
        peers={};credentials={}
        for tenant in TENANTS:
            directory=work/'peers'/tenant;directory.mkdir(mode=0o700)
            secret=('Bearer '+secrets.token_hex(32)).encode()
            credential=directory/'authorization';credential.write_bytes(secret);credential.chmod(0o600)
            credentials[tenant]=credential
            peers[tenant]=Peer(secret,maximum_seconds=120);cleanup.callback(peers[tenant].close)
        client=RecordingClient(binaries['latent'],work/'examples',cancellation,min(deadline,time.monotonic()+110),
            evidence=output/'controls')
        config=node.configuration(work/'node',signed,peers,credentials)
        record['configurationIdentity']=file_identity(config)
        service=connect(client,binaries['latentd'],work/'node',config,'examples',1);cleanup.callback(service.close)
        probe=Probe(service,file_identity(binaries['latentd'],512*1024**2));primary=False
        try:
            source=signed/node.SERVICE
            clients={'examples':client,'foreign':node.client_for_foreign(client,service,work/'foreign',output/'foreign-controls')}
            targets={}
            for tenant in TENANTS:
                selected=clients[tenant]
                published=selected.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                    '--operation-id','rust-http-private-publish-'+tenant,'--expected-generation','0')
                require(published['outcomeKnown'] is True
                    and published['data']['release']['digest']==COMPONENT['sha256'],'rust-private-original-component-publication')
                publication=published['data']['operation']['publication']['id']
                manifest=selected.directory/'deployment.json'
                write_json(manifest,node.deployment(read_json(source/'deployment.json'),tenant))
                target=deploy(selected,manifest,publication)
                grants=node.grant(selected,service,publication,tenant,peers[tenant])
                targets[tenant]=deploy(selected,manifest,publication,generation=str(target['generation']),grants=grants)
            target=targets['examples']
            record['selectedRevision']=selected_revision(client,target)
            record['originalInvocationBudgets']=target['budget']
            endpoint=peers['examples'].url('domain-json')
            process=start_call(client,target,'greeting','greet',['alpha|waki|json|'+endpoint],'examples-json')
            invocation_failed=False
            try:
                expires=min(deadline,time.monotonic()+10)
                while not process.owner.exited():
                    require(time.monotonic()<expires,'rust-private-original-call-deadline')
                    process.drain();service.drain()
                    for peer in peers.values():peer.poll(.002)
                row=finish_call(client,process)
                record['invocations'].append(row);write_json(output/'invocation-examples-json.json',row)
            except BaseException:
                invocation_failed=True;node.retain_after_failure(process,service,output,'examples-json');raise
            finally:node.close_call(process,primary_failure=invocation_failed)
            record['retirement']=node.retire(client,probe,target,output,'private-first-call',population=2)
            record['startup']=service.startup_record
            record['status']='diagnosed'
        except BaseException:
            primary=True;raise
        finally:
            # stop performs normal complete/drain BEFORE close. Capture only the
            # closed observer records, never raw stderr or credential strings.
            final_observation(client,service,output,record,primary_failure=primary)
    return record


def diagnose(native_directory,retained,output,*,reuse_host=None,reuse_identity=None):
    require(sys.platform=='linux','rust-private-linux-only')
    output=fresh(output);deadline=time.monotonic()+600
    record={'schemaVersion':'latent.rust.wasi-http.private-trap.v1','qualification':False,'status':'incomplete',
        'guestComponentsCompiled':0,'backendComponentsBuilt':0,'nativeProductsBuilt':0,
        'publicErrorsChanged':False,'originalComponent':COMPONENT,
        'observerOrigin':'byte-exact private Java-labelled observer; Rust execution only',
        'limits':{'overallSeconds':600,'fetchSeconds':60,'privateBuildSeconds':450,
            'replayReserveSeconds':120,'records':16,'numericFrames':32}}
    primary=False
    try:
        failure=read_json(ROOT/FAILURE);original_failure(failure)
        run=api('actions/runs/'+str(failure['run']));job=api('actions/jobs/'+str(failure['job']))
        artifact_meta=api('actions/artifacts/'+str(failure['artifact']['id']))
        require(run['head_sha']==failure['source'] and run['conclusion']=='failure'
            and job['head_sha']==failure['source'] and job['run_id']==failure['run'] and job['conclusion']=='failure'
            and all(artifact_meta[k]==v for k,v in failure['artifact'].items())
            and artifact_meta['workflow_run']['id']==failure['run'],'rust-private-live-original-failure')
        artifact,ancestry=replay.restore(retained,output)
        original_build=inventory(snapshot(artifact))
        require(file_identity(artifact/'component.wasm',64*1024**2)==COMPONENT,'rust-private-exact-original-component')
        native=products.verify_prepared(native_directory);binaries=products.native_products(native_directory)
        require(source_identity(ROOT)==git_source_identity(products.SOURCE),'rust-private-exact6fd-native-source')
        inputs=read_json(native_directory/'source-inputs.json')
        record['nativeAuxiliaryCompatibility']=replay.original.native_compatibility(inputs['materials'],
            {name:file_identity(ROOT/name) for name in inputs['materials']})
        for path in binaries.values():path.chmod(0o700)
        source=source_identity(ROOT);materials={name:file_identity(ROOT/name) for name in dict.fromkeys(MATERIALS)}
        require(all(materials[name]==expected for name,expected in OBSERVER_INPUTS.items()),
            'rust-private-unchanged-reviewed-observer-files')
        sources,overlays=observer.overlay_sources(ROOT,fresh(output/'overlays'))
        record.update(originalReplayFailure=failure,originalCompile=ancestry,originalNative=native,
            consumerSource=source,materials=materials,sourceOverlays=sources)
        tools={name:shutil.which(name) for name in ('cargo','bwrap','sudo','setpriv','env')}
        require(all(tools.values()),'rust-private-existing-host-tools')
        environment=build_environment(output);target,target_source=support.private_target(ROOT,output,environment)
        environment.update(CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL='0',CARGO_PROFILE_DEV_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG='0',CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
            CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        binary=output/'private-latentd'
        identity={'qualification':False,'originalNative':native,'component':COMPONENT,
            'sourceOverlays':sources,'prefix':observer.PREFIX.decode().strip(),
            'scope':'private-first-waki-trap-only;not-production'}
        require((reuse_host is None)==(reuse_identity is None),'rust-private-reuse-pair')
        if reuse_host is None:
            registry=support.locked_registry_inputs(ROOT)
            fetched=run_bounded_result([tools['cargo'],'fetch','--locked','--target',registry['target']],
                ROOT,environment,min(60,deadline-time.monotonic()-120),1048576)
            record['registryHydration']={'inputs':registry,'exitCode':fetched.returncode,
                'diagnostics':support.retain_private_cargo(fetched,output,environment,stage='fetch')}
            require(fetched.returncode==0 and registry==support.locked_registry_inputs(ROOT),'rust-private-locked-fetch')
            built=run_bounded_result(frames.build_command(ROOT,overlays,environment,tools,host.frame_host_context()),
                ROOT,environment,min(450,deadline-time.monotonic()-120),1048576)
            record['privateBuild']={**frames.private_build_observation(built),
                'diagnostics':support.retain_private_cargo(built,output,environment),'targetSource':target_source}
            require(built.returncode==0 and record['privateBuild']['hostPreflight'] is not None,'rust-private-host-build')
            shutil.copyfile(target/'debug/latentd',binary)
        else:
            observed=read_json(reuse_identity)
            require(all(observed.get(k)==v for k,v in identity.items())
                and observed.get('privateHost')==file_identity(reuse_host,512*1024**2),'rust-private-reuse-preimage')
            shutil.copyfile(reuse_host,binary);record['privateHostReused']=True
        binary.chmod(0o700);private_identity=file_identity(binary,512*1024**2)
        require(private_identity!=file_identity(binaries['latentd'],512*1024**2),'rust-private-distinct-host')
        found=False;carry=b''
        with binary.open('rb') as stream:
            while raw:=stream.read(65536):
                found|=observer.PREFIX in carry+raw;carry=raw[-len(observer.PREFIX):]
        require(found,'rust-private-observer-marker')
        write_json(output/'private-host-identity.json',{**identity,'privateHost':private_identity})
        record['privateHost']=private_identity
        require(deadline-time.monotonic()>=30,'rust-private-replay-deadline')
        result=execute(artifact,{**binaries,'latentd':binary},output/'node',deadline)
        record['replay']=result
        require(result['trapObservation']['status']=='observed','rust-private-real-trap-required')
        require(products.verify_prepared(native_directory)==native and source_identity(ROOT)==source
            and materials=={name:file_identity(ROOT/name) for name in materials}
            and all(digest(read_file(ROOT/name))==row['original'] for name,row in sources.items())
            and file_identity(artifact/'component.wasm',64*1024**2)==COMPONENT
            and inventory(snapshot(artifact))==original_build
            and time.monotonic()<deadline,'rust-private-final-original-identities')
        record.update(status='observed',rawNodeOutputRetained=False)
    except BaseException:
        primary=True;record.update(status='failed');raise
    finally:
        try:write_json(output/'observation.json',record)
        except BaseException:
            if not primary:raise
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','retained','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('reuse-host','reuse-identity'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    print(diagnose(args.native,args.retained,args.output,reuse_host=args.reuse_host,reuse_identity=args.reuse_identity)['status'])
