"""One fresh captured finite Task.Wait component on authenticated .7 products."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import dotnet_finite_wait_fixture as fixture, dotnet_finite_wait_node as node
from tools import wasmtime_48_0_7_native_products as products
from tools.dotnet_guest import task_wait, runtime
from tools.dotnet_guest.build import RECIPE, build
from tools.dotnet_guest.compiler import runtime_inputs
from tools.guest_compatibility_build import HOST_MANIFESTS, declared_host_abi
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.java_replay_materials import git_source_identity
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

DECLARATIONS = (runtime.CLOCK, runtime.ACTIVATION, runtime.WALL, runtime.RANDOM)
MATERIALS = tuple(sorted(set((*RECIPE,
    'tools/qualify_dotnet_finite_waits.py', 'tools/dotnet_finite_wait_fixture.py',
    'tools/dotnet_finite_wait_node.py', fixture.LIBRARY,
    'tools/dotnet_task_runtime_fixture.py', 'tools/dotnet_task_runtime_probe.py',
    'tools/wasmtime_48_0_7_native_products.py', 'tools/sdk_native_products_reader.py', 'tools/java_replay_materials.py',
    'tools/dotnet_resource_runtime_node.py', 'tools/dotnet_resource_runtime_fixture.py',
    'tools/dotnet_resource_timer_observer.py', 'tools/resource_tenant_node.py',
    'tools/resource_runtime_node.py', 'tools/go_node_stop_probe.py', 'tools/go_node_stop_timer_observer.py',
    'tools/guest_runtime_grants.py', 'tools/guest_runtime_profiles.py', 'tools/dotnet_guest/entropy_grants.py',
    'tools/qualify_resource_tenants.py', 'tools/qualify_sdk_scratch.py',
    'tools/rust_capsule_node.py', 'tools/phase2_operator_process.py', 'tools/phase2_operator_scenario.py',
    'tools/phase3_resource_identity.py', 'tools/phase3_resource_os.py', 'tools/phase3_resource_profile.py',
    'tools/sdk_provider_scenario.py', 'wit/host-abi-phase3-v5.json',
    'sdk/dotnet-guest/tools/http-errors/TaskWait.cs', 'sdk/dotnet-guest/tools/http-errors/Program.cs',
    'sdk/dotnet-guest/tools/http-errors/TaskWait.targets', 'sdk/dotnet-guest/tools/http-errors/IdleTimerDriver.cs',
    'sdk/dotnet-guest/tools/http-errors/ClosedFilesystem.cs', 'sdk/dotnet-guest/tools/http-errors/ClosedFilesystem.targets',
    '.github/workflows/dotnet-finite-task-waits.yml'))))


def recipe_inputs(artifact):
    host=HOST_MANIFESTS[declared_host_abi(read_json(artifact/'surface.json'))]
    return inventory({n:read_file(ROOT/n) for n in {*RECIPE,host}})


def current_native_source():
    current=source_identity(ROOT)
    require(current==git_source_identity(products.SOURCE), 'finite-wait-current-native-source-must-match-producer')
    return current


def build_evidence(artifact):
    names = ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json', 'recipe-inputs.json',
        'package-inputs.json', 'runtime-profile.json', 'compiler-patches.json', 'task-wait-port.json',
        'closed-filesystem-port.json', 'noncrypto-entropy-port.json', 'managed-entropy-port.json')
    identities = {n: file_identity(artifact/n, 32*1024**2) for n in names}
    component = file_identity(artifact/'component.wasm', 64*1024**2)
    marker, observed, profile = (read_json(artifact/n, 32*1024**2) for n in
        ('BUILD-COMPLETE.json', 'build-observation.json', 'runtime-profile.json'))
    require(marker['packageAssembled'] is True and marker['componentDigest']==observed['componentDigest']==component['sha256']
        and observed['componentSize']==component['bytes']
        and marker['observationDigest']==identities['build-observation.json']['sha256']
        and marker['sourceDigest']==identities['source-inputs.json']['sha256'], 'finite-wait-normal-observed-build')
    require(observed['parameters']=={'compiler':'native-aot-llvm','bindings':'wit-bindgen-csharp','language':'csharp',
        'target':'wasi-wasm','runtime':'native-aot','locked':True,'ambientWasi':False}
        and profile['profile']=='runtime' and sorted(profile['declaredImports'])==sorted(DECLARATIONS)
        and 'closedIoPort' not in profile, 'finite-wait-exact-runtime-without-http-log-or-closed-io')
    for material, filename in (('build-recipe','recipe-inputs.json'), ('package-inputs','package-inputs.json'),
        ('runtime-profile','runtime-profile.json'), ('dotnet-task-wait-port','task-wait-port.json'),
        ('dotnet-closed-filesystem-port','closed-filesystem-port.json'), ('standard-rng-managed-port','managed-entropy-port.json')):
        selected = [row for row in observed['materials'] if row['name']==material]; value=identities[filename]
        require(selected==[{'name':material,'digest':value['sha256'],'size':value['bytes']}], 'finite-wait-observed-selected-material')
    port = read_json(artifact/'task-wait-port.json')
    extras = {'profile','frameworkInput','tool','derived','sourceCaptureDigest','targetsDigest','nativeAotReferenceBinding','selection'}
    task_wait.validate_receipt({k:v for k,v in port.items() if k not in extras}, finite=True)
    fs = read_json(artifact/'closed-filesystem-port.json')
    require(port['profile']==task_wait.PROFILE and port['frameworkInput']['digest']==task_wait.SOURCE
        and port['derived']['digest']==port['outputDigest']
        and port['selection']['requiredDeclarations']==sorted(DECLARATIONS)
        and len(port['nativeAotReferenceBinding']['responseFiles'])==1
        and port['nativeAotReferenceBinding']['finalCoreLibDerivation']['intermediateDigest']==port['derived']['digest']
        and port['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest']==fs['derived']['digest']
        and fs['nativeAotReferenceBinding']['selectedCoreLibDigest']==fs['derived']['digest'], 'finite-wait-actual-final-corelib-binding')
    patches = read_json(artifact/'compiler-patches.json')
    require(patches['formatVersion']==1, 'finite-wait-compiler-patches-schema')
    rows = [row for row in patches['patches'] if row['name']==task_wait.PROFILE]
    require(len(rows)==1 and rows[0]['selected']==port['derived'] and rows[0]['original']==port['frameworkInput']
        and all(rows[0]['selection'][k]==port[k] for k in ('finiteAndCancellableWaits','generatedHelperCount',
            'finiteWaitCleanup','zeroTimeout','waitCancellation','publicWaitValidationAndExceptions')),
        'finite-wait-compiler-patch-selection')
    return {'component':component, 'documents':identities, 'taskWaitPort':port, 'package':package_identity(artifact,marker)}


def qualify(native_directory, tools, output):
    require(sys.platform=='linux' and sys.version_info>=(3,13), 'finite-wait-linux-python313')
    native_directory, tools = (Path(p).resolve(strict=True) for p in (native_directory,tools))
    output=Path(output).absolute()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output!=p and output not in p.parents and p not in output.parents for p in (native_directory,tools)),
        'finite-wait-separated-inputs')
    compiled=products.verify_prepared(native_directory); native=products.native_products(native_directory)
    for path in native.values(): path.chmod(0o700)
    output=fresh(output)
    source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    materials={n:file_identity(ROOT/n) for n in MATERIALS}; current=current_native_source()
    runtime_source=runtime_inputs(ROOT)
    require(read_file(tools/'runtime-inputs.json')==runtime_source, 'finite-wait-current-installer-runtime-inputs')
    installation={n:file_identity(tools/n,16*1024**2) for n in ('INSTALL-COMPLETE.json','runtime-inputs.json','wasi-sdk.json')}
    record={'schemaVersion':'latent.dotnet.finite-task-waits.qualification.v1','status':'incomplete','source':source,
        'materials':materials,'compiledNative':compiled,'consumerNativeSource':current,
        'runtimeInputs':{'sha256':digest(runtime_source),'bytes':len(runtime_source)},'compilerInstallation':installation,
        'nativeProductsBuilt':0,'engineRebuilt':False,'guestComponentsCompiled':0,'freshNativeAotRequired':True,
        'nativeAotCompilationAttempted':False,'historicalGuestQualificationRelabelled':False,
        'fullTicketQualification':False,'cpuPreemptionQualified':False,'applicationSchedulerReplacement':False}
    stage='ordinary-library-normal-capture'
    try:
        app,record['capture']=fixture.prepare(output/'project',output/'outside',tools)
        require(record['capture']['originalLibraryAndFeedRemoved'], 'finite-wait-originals-physically-removed')
        captured=inventory(snapshot(app));write_json(output/'capture.json',record['capture'])
        stage='single-fresh-normal-offline-native-aot';record['nativeAotCompilationAttempted']=True
        artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,offline=True)
        record.update(guestComponentsCompiled=1,nativeAotCompilationSucceeded=True)
        require(read_file(artifact/'source-inputs.json')==captured
            and read_file(artifact/'recipe-inputs.json')==recipe_inputs(artifact),
            'finite-wait-actual-source-and-recipe')
        record['freshBuild']=build_evidence(artifact)
        stage='signed-admitted-finite-waits-and-pending-root-terminals'
        actual=node.run(artifact,native,output/'node')
        require(actual['status']=='passed' and len(actual['cases'])==18
            and inventory(snapshot(app))==captured and products.verify_prepared(native_directory)==compiled
            and source_identity(ROOT)==current and runtime_inputs(ROOT)==runtime_source
            and read_file(tools/'runtime-inputs.json')==runtime_source
            and installation=={n:file_identity(tools/n,16*1024**2) for n in installation}
            and materials=={n:file_identity(ROOT/n) for n in MATERIALS}
            and subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()==source,
            'finite-wait-final-source-native-and-compiler-identities')
        record.update(status='passed',signedAndAdmitted=True,outcomes=18,nodeReceipt=file_identity(output/'node/qualified.json'))
        write_json(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','tools','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(qualify(args.native,args.tools,args.output)['status'])
