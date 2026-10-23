"""One fresh captured-JAR checkpoint component on separately authenticated native products."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import java_dependency_checkpoint_fixture as fixture, rust_thread_native_products as products
from tools.application_dependencies import verify_inputs
from tools.build_observation import build_environment
from tools.java_capsule_build import RECIPE, FIBER_IO_PROFILE, build
from tools.java_dependency_checkpoint_node import execute
from tools.java_standard_http_library import compiler_cache
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, inventory, read_json, snapshot, write_json

MATERIALS=tuple(sorted(set((*RECIPE,fixture.SOURCE,fixture.REFERENCE,fixture.CONTROL,
    'tools/java_dependency_checkpoint_fixture.py','tools/java_dependency_checkpoint_node.py',
    'tools/qualify_java_dependency_checkpoints.py','tools/java_standard_http_library.py',
    'tools/qualify_java_fibers.py','tools/rust_thread_native_products.py',
    'tools/sdk_native_products_reader.py','tools/host_codec_native_products_reader.py',
    'tools/host_codec_owned_reply_native_products_reader.py','tools/java_replay_materials.py',
    'tools/resource_tenant_node.py','tools/resource_runtime_node.py','tools/java_resource_runtime_node.py',
    'tools/qualify_resource_tenants.py','tools/java_http_release_preparation.py',
    'tools/rust_capsule_node.py','tools/phase3_resource_profile.py','tools/phase3_resource_os.py',
    'tools/phase2_operator_process.py','tools/phase2_operator_scenario.py','tools/sdk_provider_scenario.py',
    'tools/run_rust_capsule_workflow.py','.github/workflows/java-dependency-checkpoints.yml'))))


def build_evidence(artifact):
    names=('BUILD-COMPLETE.json','build-observation.json','source-inputs.json','recipe-inputs.json',
        'package-inputs.json','runtime-profile.json','source-origins.json','java-classpath.json',
        'application-dependencies.json','compiler-inputs.json','coroutine-compiler-preparation.json')
    documents={name:file_identity(artifact/name,32*1024**2) for name in names}
    component=file_identity(artifact/'component.wasm',64*1024**2)
    marker,observed,profile=(read_json(artifact/name,32*1024**2) for name in
        ('BUILD-COMPLETE.json','build-observation.json','runtime-profile.json'))
    require(marker['packageAssembled'] is True and marker['javaRuntimeProfile']==FIBER_IO_PROFILE
        and marker['componentDigest']==observed['componentDigest']==component['sha256']
        and observed['componentSize']==component['bytes']
        and marker['observationDigest']==documents['build-observation.json']['sha256']
        and marker['sourceDigest']==documents['source-inputs.json']['sha256'],
        'java-checkpoint-observed-fresh-package')
    require(profile['profile']==FIBER_IO_PROFILE
        and {'dev.latent.app.Capsule',fixture.LIBRARY}<=set(profile['checkpointClasses'])
        and observed['parameters']=={'compiler':'teavm-c','entryPoint':'dev.latent.app.Capsule',
            'target':'wasm32-wasip1','bindings':'lsf-java-wit-v1','optimization':'O2','javaHeapBytes':4194304},
        'java-checkpoint-original-profile-heap-and-dependency-index')
    classpath=read_json(artifact/'java-classpath.json')
    require(len(classpath['artifacts'])==1 and classpath['artifacts'][0]['id']==fixture.COORDINATE
        and classpath['artifacts'][0]['originalDigest']==fixture.JAR,
        'java-checkpoint-exact-compiled-captured-jar')
    return {'component':component,'documents':documents,'classpath':classpath,
        'runtimeProfile':profile,'heapBytes':4194304,'signedQualification':False}


def qualify(native_directory,wasi_sdk,output,*,read_only_cache=None):
    require(sys.platform=='linux' and sys.version_info>=(3,13),'java-checkpoint-linux-python313')
    native_directory,wasi_sdk=(Path(p).resolve(strict=True) for p in (native_directory,wasi_sdk))
    output=Path(output).absolute()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output!=p and output not in p.parents and p not in output.parents for p in (native_directory,wasi_sdk)),
        'java-checkpoint-separated-inputs')
    origin=products.verify_prepared(native_directory);native=products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    output=fresh(output)
    before={name:file_identity(ROOT/name) for name in MATERIALS};consumer=source_identity(ROOT)
    commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=1800,command_seconds=600)
    record={'schemaVersion':'lsf.java.dependency-checkpoint-qualification.v1','status':'incomplete',
        'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip(),
        'consumerSource':consumer,'materials':before,'nativeOrigin':origin,'nativeProductsBuilt':0,
        'guestComponentsCompiled':0,'targetComponentsCompiled':0,'fullTicketQualification':False,
        'garbageCollectionObserved':False,'historicalGuestQualificationRelabelled':False}
    stage='normal-pinned-commons-capture'
    try:
        app,selected,original,record['capture']=fixture.capture(output/'project')
        source=inventory(snapshot(app))
        stage='maintained-unsigned-compiler-cache-warm-up'
        cache_root=output/'compiler';cache_root.mkdir()
        cache=compiler_cache(commands,wasi_sdk,cache_root,read_only_cache)
        record['compilerCacheSelection']=read_json(cache_root/'compiler-cache-selection.json')
        record['unsignedCompilerWarmupComponents']=int(read_only_cache is None)
        record['guestComponentsCompiled']=record['unsignedCompilerWarmupComponents']
        stage='reference-jdk-and-actual-plugin-ir'
        record['controls']=fixture.controls(commands,cache,selected,original,output/'controls')
        stage='one-fresh-offline-target-component'
        remaining=min(900,commands.deadline-time.monotonic()-300)
        require(remaining>60,'java-checkpoint-reserved-runtime-deadline')
        artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',wasi_sdk,
            timeout=remaining,read_only_cache=cache,runtime_profile=FIBER_IO_PROFILE)
        record['guestComponentsCompiled']+=1;record['targetComponentsCompiled']=1
        record['build']=build_evidence(artifact)
        require(record['build']['classpath']==record['capture']['selected']
            and record['controls']['selectedJar']['sha256']==record['build']['classpath']['artifacts'][0]['selectedDigest'],
            'java-checkpoint-same-selected-bytecode-for-model-and-component')
        require((artifact/'source-inputs.json').read_bytes()==source,'java-checkpoint-exact-compiled-source')
        stage='signed-two-tenant-dependency-checkpoint-programme'
        record['node']=execute(artifact,native,output/'node',commands.deadline,record['build']['component']['sha256'])
        require(build_evidence(artifact)==record['build'] and inventory(snapshot(app))==source
            and verify_inputs(app,'java').identity==record['capture']['capturedInputIdentity']
            and origin==products.verify_prepared(native_directory) and consumer==source_identity(ROOT)
            and before=={name:file_identity(ROOT/name) for name in before}
            and time.monotonic()<commands.deadline,'java-checkpoint-final-original-source-and-product-bindings')
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
