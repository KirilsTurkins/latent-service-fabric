"""Fresh captured Go clients, catalogue-free normal build, same-cell HTTP isolation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if __package__ in {None,''}:
    sys.dont_write_bytecode = True
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools import go_catalogue_free_build as catalogue
from tools.go_http_tenant_fixture import CONTROL_SOURCE, LIBRARY_SOURCE, project
from tools.go_http_tenant_node import run
from tools.go_http_tenant_native_products import SOURCE, _git_materials, native_products, verify_prepared
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, fresh, read_json
from tools.run_rust_capsule_workflow import write_workflow_receipt

CONSUMER_NATIVE = '0c31349294b74da6620f67994f1e21fba58c3454'
NATIVE_SCOPES = ('Cargo.toml','Cargo.lock','rust-toolchain.toml','.cargo/config.toml',
    'apps','crates','sdk/rust','tools/optimization-workloads')
NATIVE_TEST_ONLY = frozenset(('crates/latent-wasmtime/tests/go_smtp_tls.rs',
    'crates/latent-wasmtime/tests/go_smtp_tls/setup.rs'))
MATERIALS = ('tools/qualify_go_http_tenants.py','tools/go_http_tenant_fixture.py','tools/go_http_tenant_node.py',
    'tools/go_http_library_fixture.py','tools/go_catalogue_free_build.py','tools/go_http_tenant_native_products.py',
    'tools/go_standard_http_node.py','tools/go_standard_http_project.py','tools/go_http_adversarial.py',
    'tools/resource_tenant_node.py','tools/qualify_resource_tenants.py','tools/rust_capsule_node.py',
    'tools/phase2_operator_process.py','tools/phase2_operator_scenario.py','tools/phase3_resource_identity.py',
    'tools/phase3_resource_os.py','tools/phase3_resource_profile.py','tools/guest_runtime_profiles.py',
    'tools/standard_http/peer.py','tools/standard_http/protocol.py','tools/standard_http/vectors.py',
    'tools/standard_http/observations.py','tools/java_standard_http_peer.py','tools/static_api/node.py',
    LIBRARY_SOURCE,CONTROL_SOURCE)
BUILD_FILES = ('BUILD-COMPLETE.json','component.wasm','capsule.json','deployment.json','build-observation.json',
    'source-inputs.json','recipe-inputs.json','go-runtime-transformations.json','bindings.json')


def validate_native_delta(names):
    require(type(names) is list and len(names) == len(set(names)) and set(names) == NATIVE_TEST_ONLY,
        'go-http-tenant-only-two-reviewed-uncompiled-smtp-tests')


def native_compatibility(prepared):
    proof = verify_prepared(prepared)
    current = source_identity(ROOT)
    require(current == git_source_identity(CONSUMER_NATIVE),
        'go-http-tenant-frozen-consumer-native-source-drift')
    changed = subprocess.check_output(['git','diff','--name-only',SOURCE,CONSUMER_NATIVE,'--',*NATIVE_SCOPES],
        cwd=ROOT,timeout=30).decode().splitlines()
    validate_native_delta(changed)
    # The exact two integration-test changes are authenticated by the immutable
    # consumer tree above. Neither is built by the producer's five normal
    # products or its --lib test commands. No current-native compilation claim.
    materials = _git_materials()
    auxiliary = {name:row for name,row in materials.items()
        if name.startswith(('wit/','schemas/','examples/echo-contract/wit/'))}
    require(auxiliary and all(file_identity(ROOT/name) == row for name,row in auxiliary.items()),
        'go-http-tenant-producer-abi-or-schema-drift')
    return {'producer':proof,'compiledSource':SOURCE,'consumerNativeSource':current,
        'consumerNativeReference':CONSUMER_NATIVE,'reviewedUncompiledTestDelta':changed,
        'auxiliaryCompileInputs':auxiliary,'currentNativeCompilationClaimed':False}


def qualify(prepared: Path,output: Path):
    require(sys.platform == 'linux','go-http-tenant-linux-required')
    output = fresh(output)
    require(ROOT not in output.parents and output not in ROOT.parents,'go-http-tenant-owned-output-outside-checkout')
    deadline = time.monotonic()+1200
    before = {name:file_identity(ROOT/name) for name in MATERIALS}
    record = {'schemaVersion':'latent.go.http-tenant-qualification.v1','status':'incomplete',
        'scope':'ordinary-sling-requests-private-worker-catalogue-free-build-and-two-tenant-http',
        'limits':{'overallSeconds':1200,'captureSeconds':300,'compilerSeconds':300,'nodeSeconds':300},
        'sourceMaterials':before,'fullTicketQualification':False,'normalKernelStreamEnabled':False,
        'httpsTransportSupported':False,'commands':[]}
    stage = 'authenticate-five-native-products'
    try:
        original_native = native_compatibility(prepared)
        record['native'] = original_native
        products = native_products(prepared)
        for path in products.values():path.chmod(0o700)
        native = {name:products[name]
            for name in ('latent','latentd','capsule_authoring','capsule_contracts','package')}
        go = Path(shutil.which('go') or 'missing-go').resolve(strict=True)
        original_go = file_identity(go)
        stage = 'fresh-client-source-and-private-worker'
        identity = 'outside.example.test/http-library/tenant-catalogue-free'
        app,library = project(output/'application',output/'private-original',identity)

        def command(label,argv,cwd,seconds):
            remaining = min(seconds,deadline-time.monotonic())
            require(remaining > 0,'go-http-tenant-original-deadline')
            env = build_environment(output)
            env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='')
            started = time.monotonic()
            value = run_bounded_result(argv,cwd,env,remaining,2*1024**2)
            for stream in ('stdout','stderr'):(output/(label+'.'+stream+'.log')).write_bytes(getattr(value,stream))
            record['commands'].append({'stage':label,'exitCode':value.returncode,
                'maximumSeconds':remaining,'seconds':time.monotonic()-started,'command':list(map(str,argv))})
            require(value.returncode == 0,'go-http-tenant-'+label+'-failed')

        stage = 'normal-native-resolution-review-and-origin-retention'
        command('capture',[sys.executable,'-B',str(ROOT/'tools/go_http_library_fixture.py'),
            '--project',str(app),'--private-source',str(library),'--identity',identity,'--go',str(go),
            '--output',str(output/'capture.json')],ROOT,300)
        captured = read_json(output/'capture.json')
        require(captured['privateOriginUnavailable'] is True and captured['privateModule'] == identity
            and captured['originalLibrarySourcesChanged'] is False and not library.exists(),
            'go-http-tenant-native-capture-and-unavailable-private-origin')
        record['capture'] = captured
        stage = 'remove-all-optional-reference-and-catalogue-data'
        compiler = output/'catalogue-free-compiler'
        staged = catalogue.stage(ROOT,compiler)
        record['catalogueFreeCompiler'] = staged
        stage = 'ordinary-maintained-compiler-in-catalogue-free-source-root'
        command('compile',[sys.executable,'-B',str(compiler/'tools/go_catalogue_free_build.py'),
            '--project',str(app),'--output',str(output/'build'),
            '--repository','https://github.com/KirilsTurkins/latent-service-fabric',
            '--contracts-tool',str(native['capsule_contracts']),'--packager',str(native['package']),
            '--expect-source-digest',staged['inventoryDigest']],output,300)
        require(catalogue.verify(compiler) == staged,'go-http-tenant-staged-compiler-mutated')
        record['build'] = {name:file_identity(output/'build'/name,64*1024**2) for name in BUILD_FILES}
        stage = 'signed-same-cell-two-tenant-ordinary-http'
        record['node'] = run(output/'build',{name:native[name] for name in ('latent','latentd','capsule_authoring')},
            output/'node',min(deadline,time.monotonic()+300))
        require(record['node']['status'] == 'passed' and len(record['node']['cases']) == 19
            and before == {name:file_identity(ROOT/name) for name in MATERIALS}
            and original_native == native_compatibility(prepared) and original_go == file_identity(go)
            and record['build'] == {name:file_identity(output/'build'/name,64*1024**2) for name in BUILD_FILES}
            and catalogue.verify(compiler) == staged and time.monotonic() < deadline,
            'go-http-tenant-final-source-component-native-and-compiler-freeze')
        record.update(status='passed',guestComponentsCompiled=1)
        write_workflow_receipt(output/'qualified.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    print(qualify(args.prepared.resolve(strict=True),args.output.resolve())['status'])
