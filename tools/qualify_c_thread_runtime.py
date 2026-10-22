"""One normal captured C build and its signed finite threading programme."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build as compiler
from tools import c_thread_runtime_fixture as fixture, c_thread_runtime_node as node
from tools.java_replay_materials import git_source_identity
from tools.c_guest.threading import IMPORTS, PROFILE, RECIPE as THREAD_RECIPE
from tools.c_guest import threading_compatibility as compatibility
from tools.c_guest.threading_compatibility import RECIPE as COMPATIBILITY_RECIPE
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json

# The normal compiler recipe binds the remaining compile-time helper closure.
# These are the actual node/acquisition imports, including their imported modules;
# no old language qualification receipt is relabelled as this programme.
MATERIALS = (
    'tools/qualify_c_thread_runtime.py', 'tools/c_thread_runtime_fixture.py',
    'tools/c_thread_runtime_node.py', 'tools/host_codec_native_products.py',
    'tools/host_codec_linear_memory_native_products.py',
    'tools/host_codec_linear_memory_native_products_reader.py',
    'tools/host_codec_owned_reply_native_products.py',
    'tools/host_codec_owned_reply_native_products_reader.py',
    'tools/c_thread_linear_memory_native_source.py',
    'tools/host_codec_native_products_reader.py',
    'tools/sdk_native_products_reader.py', 'tools/java_replay_materials.py',
    'tools/phase2_operator_canary.py', 'tools/phase2_operator_process.py',
    'tools/phase2_operator_scenario.py', 'tools/phase3_management_scenario.py',
    'tools/phase3_resource_identity.py', 'tools/phase3_resource_os.py',
    'tools/phase3_resource_profile.py', 'tools/rust_capsule_node.py',
    'tools/rust_capsule_cases.py', 'tools/qualify_resource_tenants.py',
    'tools/resource_tenant_inputs.py', 'tools/resource_tenant_node.py',
    'tools/qualify_sdk_scratch.py', 'tools/sdk_scratch_fixture.py',
    'tools/sdk_provider_http_fixture.py', 'tools/sdk_provider_scenario.py',
    'tools/run_rust_capsule_workflow.py', 'tools/java_server_tenants.py',
    'tools/java_server_node.py', 'tools/java_server_lifecycle.py',
    'tools/java_server_lifecycle_peer.py', 'tools/java_control_refusal_diagnostic.py',
    'tools/server_routes.py', 'tools/server_source.py',
    'tools/native_runtime/__init__.py', 'tools/native_runtime/common.py',
    'tools/native_runtime/files.py', 'tools/native_runtime/verify.py',
    'tools/dev_workflow/__init__.py', 'tools/dev_workflow/client.py',
    'tools/dev_workflow/process.py', 'tools/c_guest/__init__.py',
    'tools/build_process_signals.py', 'tools/guest_runtime_profiles.py',
    'tools/install_guest_bindgen.py', '.github/workflows/c-thread-runtime.yml',
    fixture.FIXTURE + 'main.c', fixture.FIXTURE + 'synchronization.c', fixture.FIXTURE + 'world.wit',
)


def materials():
    names = tuple(dict.fromkeys((*compiler.RECIPE, *THREAD_RECIPE, *COMPATIBILITY_RECIPE, *MATERIALS)))
    require(len(names) <= 256, 'c-thread-helper-count-bound')
    result = {name: file_identity(ROOT / name, 4 * 1024**2) for name in names}
    require(sum(row['bytes'] for row in result.values()) <= 16 * 1024**2,
            'c-thread-helper-byte-bound')
    return result


def supplement_evidence(artifact, component, derivation):
    supplement = read_json(artifact / compatibility.NAME, 65536)
    inspection = file_identity(artifact / 'compatibility-inspection.json', 65536)
    original = read_json(artifact / 'compatibility-inspection.json', 65536)
    require(supplement['schemaVersion'] == 'latent.c.threading.compatibility-supplement.v1'
            and supplement['selectedCompilerRuntimeProfile'] == PROFILE
            and supplement['componentDigest'] == original['componentDigest'] == component['sha256']
            and supplement['baseInspection'] == {'digest': inspection['sha256'], 'preserved': True}
            and supplement['fullProofRecomputedByteExact'] is True
            and supplement['baseInspectionReclassified'] is False
            and supplement['signedQualification'] is False and supplement['authority'] == 'none'
            and supplement['independentNativeGrantRequired'] is True
            and supplement['hostProfileValidationRequired'] is True
            and supplement['publicExport'] == derivation['publicExport']
            and all(supplement[name] == derivation[name]
                    for name in ('originalCoreDigest', 'derivedCoreDigest'))
            and supplement['derivationDigest'] == file_identity(artifact / 'c-threading-derivation.json')['sha256']
            and supplement['supplementalPort'] == {'interface': compatibility.PORT,
                'source': compatibility.WIT, 'sourceDigest': compatibility.WIT_DIGEST,
                'sourceBytes': compatibility.WIT_BYTES}, 'c-thread-packaged-supplement-proof')
    layers = read_json(artifact / 'package-source.json')['layers']
    assets = ((compatibility.NAME, compatibility.MEDIA),
        ('compatibility-inspection.json', 'application/vnd.latent.guest.compatibility.inspection.v1+json'),
        ('compatibility-report.json', 'application/vnd.latent.guest.compatibility.v1+json'))
    for name, media in assets:
        require([row for row in layers if row['path'] == name or row['source'] == name] == [
            {'path': name, 'source': name, 'role': 'asset', 'mediaType': media}],
            'c-thread-original-report-and-supplement-package-assets')
    return {name: file_identity(artifact / name, 65536) for name, _ in assets}


def build_evidence(artifact, source):
    marker = read_json(artifact / 'BUILD-COMPLETE.json')
    observed = read_json(artifact / 'build-observation.json')
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    require(read_file(artifact / 'source-inputs.json') == source
            and marker['packageAssembled'] is True
            and marker['sourceDigest'] == file_identity(artifact / 'source-inputs.json')['sha256']
            and marker['observationDigest'] == file_identity(artifact / 'build-observation.json')['sha256']
            and marker['componentDigest'] == observed['componentDigest'] == component['sha256']
            and observed['componentSize'] == component['bytes'], 'c-thread-normal-build-identity')
    require(observed['parameters'] == {'compiler': 'zig-cc', 'fixture': 'application',
            'target': 'wasm32-wasi', 'optimization': 'O2'}
            and any(row['stage'] == 'zig' and row['exitCode'] == 0 for row in marker['commands'])
            and all(row['exitCode'] == 0 for row in marker['commands']),
            'c-thread-original-compiler-success')
    derivation = read_json(artifact / 'c-threading-derivation.json')
    require(set(derivation) == {'formatVersion', 'profile', 'originalCoreDigest',
            'derivedCoreDigest', 'publicExport', 'rootRecordBytes',
            'canonicalComponentAuthenticated', 'standardRuntimeQualified'}
            and type(derivation['formatVersion']) is int and derivation['formatVersion'] == 1
            and derivation['profile'] == PROFILE and derivation['publicExport'] == fixture.API + '#greet'
            and type(derivation['rootRecordBytes']) is int and derivation['rootRecordBytes'] == 144
            and derivation['canonicalComponentAuthenticated'] is False
            and derivation['standardRuntimeQualified'] is False
            and all(type(derivation[name]) is str
                    and re.fullmatch(r'sha256:[0-9a-f]{64}', derivation[name])
                    for name in ('originalCoreDigest', 'derivedCoreDigest')),
            'c-thread-compiler-mechanism-not-runtime-qualification')
    for name in ('compiler-inputs.json', 'c-threading-derivation.json',
                 'c-threading-compatibility.json', 'recipe-inputs.json'):
        identity = file_identity(artifact / name, 16 * 1024**2)
        material = {'compiler-inputs.json': 'c-compiler-sysroot-and-isolation',
                    'c-threading-derivation.json': 'c-threading-derivation',
                    'c-threading-compatibility.json': 'c-threading-compatibility',
                    'recipe-inputs.json': 'build-recipe'}[name]
        require([row for row in observed['materials'] if row['name'] == material] == [
            {'name': material, 'digest': identity['sha256'], 'size': identity['bytes']}],
            'c-thread-observed-compiler-material')
    capsule = read_json(artifact / 'capsule.json')
    require(capsule['execution']['threading'] == 'cooperative'
            and len(capsule['imports']) == 2
            and {row['contract'] for row in capsule['imports']} == set(IMPORTS)
            and all(row['optional'] is False for row in capsule['imports'])
            and capsule['exports'] == [fixture.API], 'c-thread-selected-normal-component-contract')
    return {'component': component, 'marker': marker, 'derivation': derivation,
            'compatibilityAssets': supplement_evidence(artifact, component, derivation),
            'package': package_identity(artifact, marker)}


def assert_current(root, products=None):
    if products is not None and products.SOURCE == 'f5351a9331ed954c49ae83f2f4004e0f96d25d0e':
        from tools.c_thread_linear_memory_native_source import assert_current as selected_source
        return selected_source(root)
    if products is None:
        from tools import host_codec_native_products as products
    compiled = git_source_identity(products.SOURCE)
    current = source_identity(root)
    require(current == compiled, 'c-thread-current-native-source-must-be-byte-exact')
    return {'compiledSourceRevision': products.SOURCE, 'compiledNativeSource': compiled,
            'consumerNativeSource': current, 'compiledSourceByteExact': True,
            'reviewedSourceChanges': []}


def native_evidence(products, prepared):
    before = products.verify_prepared(prepared)
    proof = assert_current(ROOT, products)
    require(products.SOURCE == proof['compiledSourceRevision'],
            'c-thread-exact-native-producer')
    snapshot = read_json(prepared / 'source-inputs.json')
    require(len(snapshot['materials']) == 148
            and snapshot['native'] == proof['compiledNativeSource']
            and snapshot['materials'] == {name: file_identity(ROOT / name)
                for name in snapshot['materials']}, 'c-thread-all-current-auxiliary-materials-byte-exact')
    require(before['compiledSource'] == products.SOURCE
            and set(before['products']) == {'latent', 'latentd', 'examples/package',
                'examples/capsule_contracts', 'examples/capsule_authoring'},
            'c-thread-all-five-products-from-exact-native-producer')
    proof['perProductCompilation'] = {name: {'sourceRevision': products.SOURCE,
        'nativeSource': snapshot['native'], 'identity': identity}
        for name, identity in before['products'].items()}
    proof['auxiliaryMaterialsByteExact'] = 148
    return before, proof, products.native_products(prepared)


def qualify(prepared, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-thread-unprivileged-linux-python313')
    from tools import host_codec_owned_reply_native_products as products
    output = output.absolute()
    require(output != ROOT and output not in ROOT.parents and ROOT not in output.parents,
            'c-thread-output-outside-checkout')
    output = fresh(output)
    stage = 'authenticate-current-frozen-native-products'
    record = {'schemaVersion': 'latent.c.thread-runtime.qualification.v1',
              'status': 'incomplete', 'profile': PROFILE, 'full744Qualified': False,
              'nativeProductsRebuilt': False, 'otherLanguageComponentsRebuilt': False}
    started = time.monotonic()
    try:
        before, source_proof, native = native_evidence(products, prepared)
        record.update(producer={'source': products.SOURCE, 'receipt': before},
                      consumerNativeSource=source_proof['consumerNativeSource'],
                      nativeSourceCompatibility=source_proof, materials=materials())
        stage = 'normal-selected-c-application'
        application = fixture.prepare(output / 'application')
        source = inventory(snapshot(application))
        stage = 'one-normal-captured-selected-c-build'
        artifact = compiler.build(application, output / 'build', native['capsule_contracts'],
                                  native['package'], 'https://github.com/KirilsTurkins/latent-service-fabric')
        record['build'] = build_evidence(artifact, source)
        stage = 'signed-original-seventeen-and-three-synchronization-programme'
        record['node'] = node.run(artifact, native, output / 'node')
        require(record['node']['status'] == 'passed'
                and record['node']['programme']['status'] == 'passed'
                and record['node']['programme']['originalSeventeenOutcomePrefix'] == 17
                and len(record['node']['programme']['outcomes']) == 20,
                'c-thread-all-seventeen-original-and-three-synchronization-outcomes')
        stage = 'unchanged-source-tools-products-and-original-build'
        require(time.monotonic() - started <= 1100
                and source_identity(ROOT) == source_proof['consumerNativeSource']
                and native_evidence(products, prepared) == (before, source_proof, native)
                and materials() == record['materials']
                and inventory(snapshot(application)) == source
                and build_evidence(artifact, source) == record['build'], 'c-thread-final-source-product-and-build-fence')
        record.update(status='passed', observedCases=20)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, qualification=False)
        try:
            write_json(output / 'FAILED.json', record)
        except BaseException:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.prepared, args.output)['status']}))
