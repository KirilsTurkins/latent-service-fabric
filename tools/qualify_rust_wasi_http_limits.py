"""Reuse the authenticated 88b guest for nine individual owner-limit attempts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import replay_rust_wasi_http_forbidden_runtime as retained
from tools import rust_wasi_http_limit_node as campaign
from tools.dotnet_guest.internal_io import core_modules, integer
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

NATIVE_SOURCES = (
    'crates/latent-core/src/activation_runtime.rs',
    'crates/latent-core/src/activation_runtime/timer.rs',
    'crates/latent-node/src/activation_runner.rs',
    'crates/latent-wasmtime/src/host.rs', 'crates/latent-wasmtime/src/backend.rs',
    'crates/latent-wasmtime/src/native_stacks.rs',
    'crates/latent-wasmtime/src/native_stacks/workers.rs',
    'crates/latent-wasmtime/src/containment.rs',
    'apps/latentd/src/config/providers/activation_runtime.rs',
)
SOURCE_HELPERS = (
    'tools/check_rust_capsule_ownership.py',
    'tools/ci_rust_artifacts.py',
    'tools/ci_suite_inventory.py',
    'tools/dev_workflow/client.py',
    'tools/dev_workflow/process.py',
    'tools/guest_runtime_profiles.py',
    'tools/java_control_refusal_diagnostic.py',
    'tools/java_server_lifecycle.py',
    'tools/java_server_lifecycle_peer.py',
    'tools/java_server_node.py',
    'tools/java_server_tenants.py',
    'tools/native_runtime/__init__.py',
    'tools/native_runtime/common.py',
    'tools/native_runtime/files.py',
    'tools/native_runtime/verify.py',
    'tools/owned_test_process.py',
    'tools/phase2_operator_canary.py',
    'tools/phase3_management_scenario.py',
    'tools/phase3_resource_identity.py',
    'tools/prepared_test_harness.py',
    'tools/qualify_sdk_scratch.py',
    'tools/resource_tenant_inputs.py',
    'tools/run_oci_registry_tests.py',
    'tools/run_phase2_operator_workflow.py',
    'tools/run_rust_capsule_workflow.py',
    'tools/run_security_profile_workflow.py',
    'tools/rust_capsule_cases.py',
    'tools/sdk_provider_http_fixture.py',
    'tools/sdk_provider_scenario.py',
    'tools/sdk_scratch_fixture.py',
    'tools/server_routes.py',
    'tools/server_source.py',
    'tools/standard_http/__init__.py',
    'tools/test_run.py',
    'tools/wasmtime_48_0_7_native_products.py',
)
MATERIALS = tuple(dict.fromkeys(('tools/qualify_rust_wasi_http_limits.py',
    'tools/rust_wasi_http_limit_node.py', *retained.MATERIALS,
    *campaign.MATERIALS, *NATIVE_SOURCES, *SOURCE_HELPERS)))


def memory_shape(component):
    """Bounded inspection of the fixed authenticated component's memory types."""
    definitions = []
    modules = core_modules(component)
    require(len(modules) <= 32, 'rust-limit-core-count')
    for ordinal, body in enumerate(modules):
        at = 8
        while at < len(body):
            kind = body[at]; size, begin = integer(body, at+1); end = begin+size
            require(end <= len(body), 'rust-limit-core-section-bound'); at = end
            if kind != 5: continue
            count, position = integer(body, begin)
            require(count <= 4, 'rust-limit-memory-count')
            for _ in range(count):
                flags, position = integer(body, position)
                require(flags in (0, 1), 'rust-limit-original-memory32-only')
                minimum, position = integer(body, position)
                maximum = None
                if flags == 1: maximum, position = integer(body, position)
                definitions.append({'core':ordinal,'minimumPages':minimum,'maximumPages':maximum})
            require(position == end, 'rust-limit-complete-memory-section')
    require(definitions == [
        {'core':0,'minimumPages':17,'maximumPages':None},
        {'core':3,'minimumPages':19,'maximumPages':None},
        {'core':6,'minimumPages':17,'maximumPages':None}], 'rust-limit-original-three-memory-shapes')
    return {'definitions':definitions,'definedMinimumPages':53,'definedMinimumBytes':53*65536,
        'lowerRequestedBytes':3*1024**2,'definitionSumIsNotMeasuredRss':True,
        'actualTypedMemoryTerminalStillRequired':True}


def qualify(restored, prepared, output):
    require(sys.platform == 'linux' and sys.version_info >= (3,13), 'rust-limit-owned-linux-python313')
    restored = Path(restored).resolve(strict=True); prepared = Path(prepared).resolve(strict=True)
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(p != output and p not in output.parents and output not in p.parents
                for p in (restored,prepared)), 'rust-limit-fresh-separated-output')
    output = fresh(output); deadline = time.monotonic()+1100
    materials = {name:file_identity(ROOT/name,8*1024**2) for name in MATERIALS}
    record = {'schemaVersion':'latent.rust.wasi-http.limit-qualification.v1','status':'incomplete',
        'materials':materials,'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        'guestBuilds':0,'backendBuilds':0,'nativeBuilds':0,'fullTicketQualification':False}
    stage = 'original-88b-component-and-build-authentication'
    try:
        artifact, ancestry = retained.restore(restored,output)
        record['original'] = ancestry
        previous = read_json(restored/'rust-http-runtime-qualification/FAILED.json',16*1024**2)['materials']
        recipe = read_json(artifact/'recipe-inputs.json',8*1024**2)
        require(len(previous)==143 and len(recipe)==116,'rust-limit-original-full-source-closure')
        names = set(MATERIALS) | set(previous) | set(recipe)
        require(len(names)<=256,'rust-limit-helper-count-bound')
        materials = {name:file_identity(ROOT/name,8*1024**2) for name in sorted(names)}
        require(sum(r['bytes'] for r in materials.values())<=16*1024**2,'rust-limit-helper-byte-bound')
        record['materials'] = materials
        record['memoryShape'] = memory_shape((artifact/'component.wasm').read_bytes())
        stage = 'original-c713-native-and-134-auxiliary-authentication'
        producer = retained.native.verify_prepared(prepared)
        native_source = retained.assert_current(ROOT)
        require(native_source['compiledSourceRevision'] == retained.native.SOURCE, 'rust-limit-c713-native-binding')
        record['producer'] = producer; record['nativeSourceCompatibility'] = native_source
        record['auxiliaryCompatibility'] = retained.original.native_compatibility(
            read_json(prepared/'source-inputs.json')['materials'],
            {name:file_identity(ROOT/name) for name in read_json(prepared/'source-inputs.json')['materials']})
        products = retained.native.native_products(prepared)
        identities = {name:file_identity(path,512*1024**2) for name,path in products.items()}
        for path in products.values(): path.chmod(0o700)
        stage = 'nine-isolated-owner-and-memory-attempts'
        result = campaign.run(artifact,products,output/'node',deadline=deadline)
        require(result['status'] == 'passed' and len(result['attempts']) == 9 and len(result['phases']) == 4,
                'rust-limit-all-nine-required')
        require(producer == retained.native.verify_prepared(prepared)
            and native_source == retained.assert_current(ROOT)
            and identities == {name:file_identity(path,512*1024**2) for name,path in products.items()}
            and materials == {name:file_identity(ROOT/name,8*1024**2) for name in materials}
            and time.monotonic() < deadline, 'rust-limit-final-original-products-source-and-clock')
        record.update(status='passed',invocationAttempts=9,node=file_identity(output/'node/qualification.json'),
            signedQualification=True)
        write_json(output/'qualification.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage)
        try:write_json(output/'FAILED.json',record)
        except BaseException:pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original-artifact','native-products','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    print(qualify(args.original_artifact,args.native_products,args.output)['status'])
