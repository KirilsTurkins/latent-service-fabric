"""Two normal compiler captures and eight actual explicit application fallback calls."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build, go_capsule_build
from tools import c_thread_admission_native_products as native
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, inventory, read_json, snapshot, write_json
from tools.sdk_explicit_fallback_fixture import LANGUAGES, project
from tools.sdk_explicit_fallback_node import run

REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'
MATERIALS = tuple(dict.fromkeys((*c_capsule_build.RECIPE, *go_capsule_build.RECIPE,
    'tools/qualify_sdk_explicit_fallback.py', 'tools/sdk_explicit_fallback_fixture.py',
    'tools/sdk_explicit_fallback_node.py', 'tools/qualify_sdk_scratch.py', 'tools/sdk_scratch_fixture.py',
    'tools/sdk_scratch_probe.py', 'tools/resource_tenant_node.py', 'tools/qualify_resource_tenants.py',
    'tools/resource_tenant_inputs.py', 'tools/resource_tenant_originals.py',
    'tools/java_server_tenants.py', 'tools/rust_capsule_node.py', 'tools/run_rust_capsule_workflow.py',
    'tools/rust_capsule_cases.py', 'tools/phase2_operator_process.py', 'tools/phase2_operator_scenario.py',
    'tools/phase3_resource_identity.py', 'tools/phase3_resource_os.py', 'tools/phase3_resource_profile.py',
    'tools/sdk_provider_scenario.py', 'tools/c_thread_admission_native_products.py',
    'tools/c_thread_package_native_products.py', 'tools/sdk_native_products_reader.py',
    'tools/java_replay_materials.py', 'tools/build_process_signals.py', 'tools/build_process_linux.py',
    'tools/c_guest/__init__.py', 'tools/go_guest/__init__.py', 'tools/dev_workflow/client.py',
    'tools/dev_workflow/process.py', 'tools/guest_runtime_profiles.py',
    'tools/java_control_refusal_diagnostic.py', 'tools/java_server_lifecycle.py',
    'tools/java_server_lifecycle_peer.py', 'tools/java_server_node.py', 'tools/native_runtime/__init__.py',
    'tools/native_runtime/common.py', 'tools/native_runtime/files.py', 'tools/native_runtime/verify.py',
    'tools/phase2_operator_canary.py', 'tools/phase3_management_scenario.py',
    'tools/sdk_provider_http_fixture.py', 'tools/server_routes.py', 'tools/server_source.py')))


def materials():
    require(len(MATERIALS) == len(set(MATERIALS)) <= 256, 'fallback-material-count-bound')
    rows = {name: file_identity(ROOT / name, 1024**2) for name in MATERIALS}
    require(sum(row['bytes'] for row in rows.values()) <= 16 * 1024**2, 'fallback-material-byte-bound')
    return rows


def compiled(artifact, before):
    require((artifact / 'source-inputs.json').read_bytes() == before, 'fallback-exact-captured-source')
    marker = read_json(artifact / 'BUILD-COMPLETE.json')
    package = package_identity(artifact, marker)
    require(read_json(artifact / 'capsule.json')['execution']['limits']['logBytes'] == 0,
        'fallback-original-no-log-budget')
    return {'marker': marker, 'sourceInputs': file_identity(artifact / 'source-inputs.json'),
        'recipeInputs': file_identity(artifact / 'recipe-inputs.json'), 'package': package,
        'component': file_identity(artifact / 'component.wasm', 64 * 1024**2),
        'buildObservation': file_identity(artifact / 'build-observation.json')}


def selected_tools(binaries):
    """Use the reader API names, independently of its original receipt keys."""
    require(set(binaries) == {'latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'},
        'fallback-exact-reader-product-api')
    return {name: binaries[name] for name in ('capsule_contracts', 'package', 'capsule_authoring')}


def qualify(products: Path, output: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
        'fallback-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'fallback-output-outside-checkout')
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=900)
    origin = native.verify_prepared(products)
    binaries = native.native_products(products)
    tools = selected_tools(binaries)
    for binary in binaries.values():
        binary.chmod(0o700)
    identities = {name: file_identity(path, 512 * 1024**2) for name, path in binaries.items()}
    native_inputs = read_json(products / 'source-inputs.json')
    # Old host code is authenticated as old code. Current compiler inputs have their own receipts.
    source = source_identity(ROOT)
    before = materials()
    record = {'schemaVersion': 'latent.sdk.explicit-fallback.qualification.v1', 'status': 'incomplete',
        'nativeOrigin': origin, 'nativeProductIdentities': identities,
        'perProductCompilation': native_inputs['perProductCompilation'],
        'consumerNativeSource': source, 'consumerNativeSourceIsProductCompilationClaim': False,
        'materials': before, 'languages': {}, 'guestBuildsRequested': 2,
        'nativeProductsRebuilt': False, 'old27Or33ProgrammeReplayed': False,
        'filesystemGrantAdded': False, 'transparentFilesystemCompatibility': False,
        'fullTicketQualification': False}
    stage = 'fresh-captured-application-source'
    try:
        for language in LANGUAGES:
            location = output / language
            location.mkdir(mode=0o700)
            app, fixture = project(language, location / 'application')
            captured = inventory(snapshot(app))
            entry = {'fixture': fixture}
            record['languages'][language] = entry
            stage = language + '-normal-compiler-package'
            artifact = location / 'build'
            commands.run(stage, sys.executable, '-B', ROOT / f'tools/{language}_capsule.py', 'build', app,
                '--output', artifact, '--repository', REPOSITORY,
                '--contracts-tool', tools['capsule_contracts'], '--packager', tools['package'])
            entry['build'] = compiled(artifact, captured)
            stage = language + '-normal-neutral-signing'
            signed = location / 'signed'
            commands.run(stage, tools['capsule_authoring'], 'demo-sign-neutral-resources', signed, artifact)
            stage = language + '-four-actual-fallback-trap-fresh-outcomes'
            node = run(language, artifact, signed, binaries, location / 'node', commands.deadline)
            require(node['status'] == 'passed' and len(node['cases']) == 4
                and inventory(snapshot(app)) == captured and compiled(artifact, captured) == entry['build'],
                'fallback-four-outcomes-source-build-unchanged')
            entry.update(node=file_identity(location / 'node/qualified.json'), outcomeCount=4)
        stage = 'final-source-products-and-retirement'
        require(materials() == before and source_identity(ROOT) == source and native.verify_prepared(products) == origin
            and {name: file_identity(path, 512 * 1024**2) for name, path in binaries.items()} == identities
            and len(record['languages']) == 2 and time.monotonic() < commands.deadline,
            'fallback-final-source-products-and-total-bound')
        record.update(status='passed', attempts=8, commands=commands.records)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        try:
            write_json(output / 'FAILED.json', record)
        except BaseException:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-products', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.native_products, args.output)
    print(json.dumps({'status': result['status'], 'attempts': result['attempts']}))
