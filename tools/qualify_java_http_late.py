"""One ordinary Java component for late accepted HTTP task completion."""
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
from tools.java_capsule_build import FIBER_IO_PROFILE, build
from tools.java_guest.c_failure_context import PHASE_FIXTURE_SOURCES
from tools.java_http_late_fixture import project, SOURCE
from tools.java_http_late_node import run as node_controls
from tools.java_http_mixed_node import identities
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_http_mixed import compiler_cache, MATERIALS as BODY_MATERIALS
from tools.qualify_java_http_phases import resolve_review, component_profile
from tools.qualify_java_http_prepared_tenants import current_native
from tools import release_preparation_cli_native_products as native
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

MATERIALS = tuple(dict.fromkeys((*BODY_MATERIALS, SOURCE, 'tools/java_http_late_fixture.py',
    'tools/java_http_late_node.py', 'tools/qualify_java_http_late.py')))


def execute(commands, binaries, wasi_sdk, output):
    output = fresh(output);before = {name: file_identity(ROOT/name) for name in MATERIALS}
    products = {name: file_identity(path) for name, path in binaries.items()}
    stage = 'project'
    try:
        app = project(output/'application')
        stage = 'normal-public-client-capture-review'
        captured = resolve_review(commands, app, output/'candidate.json')
        stage = 'pinned-compiler-dependencies-only'
        cache = compiler_cache(wasi_sdk, output, min(600, commands.deadline-time.monotonic()))
        stage = 'one-offline-late-completion-component'
        remaining = min(900, commands.deadline-time.monotonic())
        require(remaining > 0, 'java-late-original-build-deadline')
        artifact = build(app, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
            timeout=remaining, read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE,
            failure_contexts=PHASE_FIXTURE_SOURCES)
        actual = {row['id']: row['originalDigest'] for row in read_json(artifact/'java-classpath.json')['artifacts']}
        require(set(actual) == set(captured['originalJars']) and all(
            actual[name] == identity['digest'] for name, identity in captured['originalJars'].items()),
            'java-late-original-client-jars-changed')
        component_profile(artifact, 'java-late-selected-component-profile')
        stage = 'signed-logical-cancel-late-completion'
        result = node_controls(artifact, {name: binaries[name] for name in ('latent', 'latentd', 'capsule_authoring')},
            output/'node', deadline=commands.deadline)
        require(result['status'] == 'passed' and result['invocations'] == 4 and len(result['cases']) == 4
            and result['authorityDenials'] == 1 and result['httpContacts'] == 6, 'java-late-incomplete-programme')
        require(before == {name: file_identity(ROOT/name) for name in before}
            and products == {name: file_identity(path) for name, path in binaries.items()},
            'java-late-final-source-or-product-drift')
        final = {'schemaVersion': 'latent.java.http-late-campaign.v1', 'status': 'passed',
            'materials': before, 'nativeProducts': products, 'capturedLibraries': captured,
            'artifact': identities(artifact), 'nodeReceipt': file_identity(output/'node/qualification.json'),
            'invocations': 4, 'authorityDenials': 1, 'httpContacts': 6,
            'nativeRecompiledByConsumer': False, 'newGuestComponentsCompiled': 1,
            'scope': 'late-accepted-task-completion-after-logical-cancel-before-activation-retirement',
            'postRetiredStoreCallbackClaimed': False, 'full688Qualified': False, 'full741Qualified': False,
            'limitations': ['Read-only runtime Result observation is test instrumentation, not a transport/executor.',
                'Earlier closing/drain/trap/cross-tenant programmes retain their original source evidence.',
                'No callback after a retired Store, arbitrary JVM scheduling, HTTPS or release qualification.']}
        write_json(output/'final-materials.json', {'materials': before, 'nativeProducts': products})
        write_json(output/'qualification.json', final);return final
    except BaseException:
        try:write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage, 'full688Qualified': False})
        except BaseException:pass
        raise


def run(output, prepared, wasi_sdk):
    history = native.verify_prepared(prepared);production = current_native(prepared)
    output = fresh(output);environment = build_environment(output)
    if 'JAVA_HOME' in os.environ:environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output/'commands'), environment, deadline_seconds=1800, command_seconds=300)
    result = execute(commands, native.native_products(prepared), wasi_sdk, output/'campaign')
    require(history == native.verify_prepared(prepared) and production == current_native(prepared),
        'java-late-final-native-source-protocol-drift')
    result.update(nativeProducer=history, nativeProductionSourceProof=production,
        fixtureSource=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    write_json(output/'qualification.json', result);return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--wasi-sdk', type=Path, required=True)
    args = parser.parse_args();output = args.output.resolve()
    require(sys.platform == 'linux' and output != ROOT and ROOT not in output.parents, 'java-late-owned-linux-output-required')
    run(output, args.prepared.resolve(strict=True), args.wasi_sdk.resolve(strict=True))
