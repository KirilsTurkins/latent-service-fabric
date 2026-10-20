"""Observe the unchanged failed Java guest with a private host; never qualify it."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import diagnose_go_entry_frames as frames,diagnose_go_timer_failure as host
from tools import java_resource_private_observer as observer,java_resource_private_build as support
from tools import replay_java_resource_runtime as replay,qualify_java_resource_runtime as qualification
from tools import wait_runtime_native_products as products
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.java_replay_materials import api
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity,source_identity
from tools.rust_capsule_project import ROOT,digest,fresh,read_file,read_json,write_json

SPEC='tools/fixtures/java-resource-runtime/063-retained-public-inventory.json'
COMPONENT={'sha256':'sha256:e97797bacbb32208804c74be12f776018ac25a775da4e2b6d8b5423e5d9e57c8','bytes':1954666}
MATERIALS=(*qualification.MATERIALS,SPEC,'tools/diagnose_java_resource_failure.py',
    'tools/java_resource_private_observer.py','tools/java_resource_private_build.py',
    'tools/diagnose_go_entry_frames.py','tools/diagnose_go_timer_failure.py')


def verify_members(directory,spec,restored=()):
    require(spec['memberCount']==225 and len(spec['members'])==225,'java-private-fixed-225-members')
    expected={row['path']:row for row in spec['members']}
    require(len(expected)==225,'java-private-distinct-members')
    pending=[directory];found=set();entries=total=0
    while pending:
        for path in pending.pop().iterdir():
            entries+=1;require(entries<=512 and not path.is_symlink(),'java-private-entry-or-link')
            if path.is_dir():pending.append(path);continue
            require(path.is_file(),'java-private-regular-member')
            name=path.relative_to(directory).as_posix();found.add(name)
            require(name in expected or name in restored,'java-private-unlisted-member')
            if name in expected:
                row=expected[name];total+=row['bytes']
                require(total<=16*1024**2 and file_identity(path,8*1024**2)=={
                    'sha256':row['sha256'],'bytes':row['bytes']},'java-private-member-preimage')
    require(found==set(expected)|set(restored),'java-private-complete-members')


def diagnose(native_directory,retained,output,*,reuse_host=None,reuse_identity=None):
    require(sys.platform=='linux','java-private-linux-only')
    output=fresh(output);deadline=time.monotonic()+600
    record={'schemaVersion':'latent.java.private-resource-trap.v1','qualification':False,
        'originalProgrammePassed':False,'status':'incomplete','guestComponentsCompiled':0,
        'engineRebuilt':False,'publicErrorsChanged':False,'originalComponent':COMPONENT,
        'limits':{'overallSeconds':600,'fetchSeconds':60,'privateBuildSeconds':450,
            'replayReserveSeconds':120,'records':16,'numericFrames':32}}
    try:
        spec=read_json(ROOT/SPEC)
        replay.verify_origin(spec,api(f'actions/runs/{spec["run"]}'),api(f'actions/jobs/{spec["job"]}'),
            api(f'actions/artifacts/{spec["artifact"]["id"]}'))
        verify_members(retained,spec)
        original=read_json(retained/'java-resource-runtime/FAILED.json');replay.original_materials(original,spec)
        build=retained/'java-resource-runtime/build';restored=replay.restore_original_layers(build)
        restored=['java-resource-runtime/build/'+name for name in restored]
        verify_members(retained,spec,restored)
        before=qualification.build_evidence(build);require(before['component']==COMPONENT,'java-private-exact-component')
        native=products.verify_prepared(native_directory);binaries=products.native_products(native_directory)
        require(native==original['compiledNative'],'java-private-original-native-tuple')
        for path in binaries.values():path.chmod(0o700)
        source=source_identity(ROOT);materials={name:file_identity(ROOT/name) for name in set(MATERIALS)}
        record.update(originalArtifact=spec['artifact'],originalSource=spec['source'],originalBuild=before,
            originalMembersVerified=225,originalNative=native,consumerSource=source,materials=materials)
        sources,overlays=observer.overlay_sources(ROOT,fresh(output/'overlays'))
        tools={name:shutil.which(name) for name in ('cargo','bwrap','sudo','setpriv','env')}
        require(all(tools.values()),'java-private-host-tools')
        environment=build_environment(output);target,target_source=support.private_target(ROOT,output,environment)
        environment.update(CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL='0',CARGO_PROFILE_DEV_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG='0',CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
            CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        binary=output/'private-latentd'
        identity={'qualification':False,'originalNative':native,'component':COMPONENT,
            'sourceOverlays':sources,'prefix':observer.PREFIX.decode().strip(),
            'scope':'private-diagnostic-only;not-production'}
        require((reuse_host is None)==(reuse_identity is None),'java-private-reuse-pair')
        if reuse_host is None:
            registry=support.locked_registry_inputs(ROOT)
            fetched=run_bounded_result([tools['cargo'],'fetch','--locked','--target',registry['target']],
                ROOT,environment,min(60,deadline-time.monotonic()-120),1048576)
            record['registryHydration']={'inputs':registry,'exitCode':fetched.returncode,
                'diagnostics':support.retain_private_cargo(fetched,output,environment,stage='fetch')}
            require(fetched.returncode==0 and registry==support.locked_registry_inputs(ROOT),'java-private-locked-fetch')
            built=run_bounded_result(frames.build_command(ROOT,overlays,environment,tools,host.frame_host_context()),
                ROOT,environment,min(450,deadline-time.monotonic()-120),1048576)
            record['privateBuild']={**frames.private_build_observation(built),
                'diagnostics':support.retain_private_cargo(built,output,environment),'targetSource':target_source}
            require(built.returncode==0 and record['privateBuild']['hostPreflight'] is not None,'java-private-host-build')
            shutil.copyfile(target/'debug/latentd',binary)
        else:
            observed=read_json(reuse_identity)
            require(all(observed.get(k)==v for k,v in identity.items())
                and observed.get('privateHost')==file_identity(reuse_host,512*1024**2),'java-private-reuse-preimage')
            shutil.copyfile(reuse_host,binary);record['privateHostReused']=True
        binary.chmod(0o700);private_identity=file_identity(binary,512*1024**2)
        require(private_identity!=file_identity(binaries['latentd'],512*1024**2),'java-private-distinct-host')
        found=False;carry=b''
        with binary.open('rb') as stream:
            while raw:=stream.read(65536):
                found|=observer.PREFIX in carry+raw;carry=raw[-len(observer.PREFIX):]
        require(found,'java-private-observer-marker')
        write_json(output/'private-host-identity.json',{**identity,'privateHost':private_identity})
        record['privateHost']=private_identity;record['sourceOverlays']=sources
        require(deadline-time.monotonic()>=30,'java-private-replay-deadline')
        try:
            record['replay']=qualification.execute(build,{**binaries,'latentd':binary},output/'node',deadline,diagnostic=True)
        finally:
            stderr=output/'node/node-stderr.txt'
            if stderr.exists():
                record['trapObservation']=observer.capture(read_file(stderr,262144));stderr.write_bytes(b'')
        require(record.get('trapObservation',{}).get('status')=='observed','java-private-real-trap-required')
        verify_members(retained,spec,restored)
        require(qualification.build_evidence(build)==before and products.verify_prepared(native_directory)==native
            and source_identity(ROOT)==source and materials=={name:file_identity(ROOT/name) for name in materials}
            and all(digest(read_file(ROOT/name))==row['original'] for name,row in sources.items())
            and time.monotonic()<deadline,'java-private-final-original-identities')
        record.update(status='observed',rawNodeOutputRetained=False)
    except BaseException as error:
        record.update(status='failed',errorCategory=type(error).__name__)
        raise
    finally:
        write_json(output/'observation.json',record)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','retained','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('reuse-host','reuse-identity'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    print(diagnose(args.native,args.retained,args.output,reuse_host=args.reuse_host,reuse_identity=args.reuse_identity)['status'])
