"""One fresh offline ordinary Java mixed-body component; no native rebuild."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.java_capsule_build import RECIPE, FIBER_IO_PROFILE, build
from tools.java_guest.compiler import Compiler, read_only_dependency_cache, tool_inventory
from tools.java_guest.c_failure_context import PHASE_FIXTURE_SOURCES
from tools.java_http_mixed_fixture import project, SOURCE, CASES
from tools.java_http_mixed_node import run as node_controls, identities
from tools.java_http_phase_fixture import WORLD
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_http_phases import resolve_review, component_profile, MATERIALS as PHASE_MATERIALS
from tools.qualify_java_http_prepared_tenants import current_native
from tools import release_preparation_cli_native_products as native
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json

MAX_SECONDS = 1800
CACHE_TASK = '''
// Public pinned compiler inputs only: no Java, C, Wasm or application build.
tasks.register('captureCompilerDependencies') {
    doLast {
        configurations.findAll { it.canBeResolved }.each { it.resolve() }
    }
}
'''
MATERIALS = tuple(dict.fromkeys((*RECIPE, *PHASE_MATERIALS, SOURCE, WORLD,
    'tools/java_http_mixed_fixture.py', 'tools/java_http_mixed_node.py',
    'tools/qualify_java_http_mixed.py', 'tools/qualify_java_http_prepared_tenants.py',
    'tools/java_http_release_preparation.py', 'tools/release_preparation_cli_native_products.py',
    '.github/workflows/java-http-fiber-lifecycle.yml')))


def compiler_cache(wasi_sdk, output, timeout):
    """Resolve pinned compiler configurations without compiling a greeting."""
    compiler = Compiler(output/'compiler-acquisition', wasi_sdk, timeout=timeout)
    project = fresh(compiler.directory/'project')
    pins = {}
    for source, target in (
            ('compiler.gradle', 'build.gradle'), ('feasibility/settings.gradle', 'settings.gradle'),
            ('feasibility/gradle/verification-metadata.xml', 'gradle/verification-metadata.xml')):
        raw = read_file(ROOT/'sdk/java-guest'/source)
        pins[source] = digest(raw)
        path = project/target;path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw + CACHE_TASK.encode() if target == 'build.gradle' else raw)
    compiler.run('pinned-compiler-dependency-acquisition', 'gradle', '--no-daemon',
        'captureCompilerDependencies', cwd=project)
    compiler.check_unchanged()
    selected = read_only_dependency_cache(compiler.directory/'gradle-home/caches/modules-2')
    value = {'schemaVersion': 'latent.java.compiler-dependency-acquisition.v1',
        'mode': 'pinned-configurations-only', 'sourcePins': pins,
        'taskDigest': digest(CACHE_TASK.encode()), 'inventoryDigest': digest(tool_inventory({'gradle-cache': selected})),
        'applicationRegistryResolution': False, 'guestComponentsCompiled': 0,
        'nativeProductsCompiled': 0, 'commands': compiler.records}
    write_json(output/'compiler-cache-selection.json', value)
    return selected


def execute(commands, binaries, wasi_sdk, output):
    output = fresh(output)
    before = {name: file_identity(ROOT/name) for name in MATERIALS}
    products = {name: file_identity(path) for name, path in binaries.items()}
    stage = 'project'
    try:
        app = project(output/'application')
        stage = 'normal-public-dependency-capture-review'
        captured = resolve_review(commands, app, output/'candidate.json')
        stage = 'pinned-compiler-dependencies-only'
        cache = compiler_cache(wasi_sdk, output, min(600, commands.deadline-time.monotonic()))
        stage = 'one-offline-mixed-body-component'
        remaining = min(900, commands.deadline-time.monotonic())
        require(remaining > 0, 'java-mixed-original-build-deadline')
        artifact = build(app, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
            timeout=remaining, read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE,
            failure_contexts=PHASE_FIXTURE_SOURCES)
        from tools.rust_capsule_project import read_json
        classpath = read_json(artifact/'java-classpath.json')
        actual = {row['id']: row['originalDigest'] for row in classpath['artifacts']}
        require(set(actual) == set(captured['originalJars']) and all(
            actual[name] == identity['digest'] for name, identity in captured['originalJars'].items()),
            'java-mixed-original-client-jars-changed')
        component_profile(artifact, 'java-mixed-selected-component-profile')
        stage = 'signed-mixed-body-controls'
        result = node_controls(artifact,
            {name: binaries[name] for name in ('latent', 'latentd', 'capsule_authoring')},
            output/'node', deadline=commands.deadline)
        require(result['status'] == 'passed' and result['invocations'] == len(CASES) == 10
            and result['authorityDenials'] == 1 and result['httpContacts'] == 11,
            'java-mixed-incomplete-programme')
        require(before == {name: file_identity(ROOT/name) for name in before}
            and products == {name: file_identity(path) for name, path in binaries.items()},
            'java-mixed-final-source-or-products-drift')
        final = {'schemaVersion': 'latent.java.http-mixed-campaign.v1', 'status': 'passed',
            'materials': before, 'nativeProducts': products, 'capturedLibraries': captured,
            'artifact': identities(artifact), 'nodeReceipt': file_identity(output/'node/qualification.json'),
            'invocations': 10, 'authorityDenials': 1, 'httpContacts': 11,
            'nativeRecompiledByConsumer': False, 'newGuestComponentsCompiled': 1,
            'full688Qualified': False, 'full741Qualified': False, 'lateCompletionClaimed': False,
            'limitations': ['Finite body-view/borrowed-output/partial-read/boundary/cancel controls only.',
                'The peer observes body gating and socket closure; a stale gate is never a late-completion witness.',
                'Prior default clients, tenant isolation and fiber programmes retain their own source attribution.']}
        write_json(output/'final-materials.json', {'materials': before, 'nativeProducts': products})
        write_json(output/'qualification.json', final)
        return final
    except BaseException:
        try:write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage, 'full688Qualified': False})
        except Exception:pass
        raise


def run(output, prepared, wasi_sdk):
    history = native.verify_prepared(prepared);production = current_native(prepared)
    output = fresh(output);environment = build_environment(output)
    if 'JAVA_HOME' in os.environ: environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output/'commands'), environment,
        deadline_seconds=MAX_SECONDS, command_seconds=300)
    result = execute(commands, native.native_products(prepared), wasi_sdk, output/'campaign')
    require(history == native.verify_prepared(prepared) and production == current_native(prepared),
        'java-mixed-final-native-source-protocol-drift')
    result.update(nativeProducer=history, nativeProductionSourceProof=production,
        fixtureSource=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    write_json(output/'qualification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--wasi-sdk', type=Path, required=True)
    args = parser.parse_args();output = args.output.resolve()
    require(sys.platform == 'linux' and output != ROOT and ROOT not in output.parents,
        'java-mixed-owned-linux-output-required')
    run(output, args.prepared.resolve(strict=True), args.wasi_sdk.resolve(strict=True))
