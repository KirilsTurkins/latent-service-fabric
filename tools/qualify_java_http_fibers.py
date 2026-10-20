"""Fresh captured published Java client on the existing fiber-I/O implementation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.java_capsule_build import RECIPE, FIBER_IO_PROFILE, build
from tools.java_guest.c_failure_context import FIXTURE_SOURCES
from tools.java_standard_http_library import (COORDINATE, ORIGINAL_JAR, CANDIDATE,
    compiler_cache, project as library_project)
from tools.java_http_fiber_node import run as node_controls, CASES
from tools.java_replay_materials import prepare, verify_prepared, native_products
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

SOURCE = 'examples/java-http-fiber-lifecycle/Capsule.java'
WORLD = 'examples/java-http-fiber-lifecycle/world.wit'
MAX_SECONDS = 1800
MATERIALS = tuple(dict.fromkeys((*RECIPE, SOURCE, WORLD, 'tools/java_standard_http_library.py',
    'tools/java_standard_http_project.py', 'tools/java_standard_http_node.py',
    'tools/java_http_fiber_node.py', 'tools/qualify_java_http_fibers.py',
    'tools/java_replay_materials.py', 'tools/standard_http/peer.py', 'tools/standard_http/protocol.py',
    'tools/standard_http/vectors.py', 'tools/standard_http/observations.py',
    'tools/rust_capsule_node.py', 'tools/phase3_resource_profile.py', 'tools/phase3_resource_os.py',
    'tools/phase2_operator_process.py', 'tools/phase2_operator_scenario.py',
    'tools/guest_runtime_profiles.py', 'tools/static_api/node.py')))


def project(directory):
    app = library_project(directory)
    source, wit = read_file(ROOT/SOURCE), read_file(ROOT/WORLD)
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    (app/'wit/world.wit').write_bytes(wit)
    # These are exactly the captured SDK definitions, not synthetic type stubs.
    path = app/'wit/deps/activation-runtime/package.wit'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(read_file(app/'vendor/lsf/wit/platform/activation-runtime/package.wit'))
    lock = read_json(app/'sdk-lock.json')
    lock['template'] = {'name': 'java-http-fiber-lifecycle', 'sourceDigest': digest(source), 'witDigest': digest(wit)}
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    return app


def execute(commands, binaries, wasi_sdk, output, *, read_only_cache=None):
    """Normal resolve/review/CAS build; no compiler/SDK/factory changes."""
    output = fresh(output)
    before = {name: file_identity(ROOT/name) for name in MATERIALS}
    native = {name: file_identity(path) for name, path in binaries.items()}
    stage = 'project'
    try:
        app = project(output/'application')
        candidate = output/'candidate.json'
        stage = 'normal-resolve'
        commands.run('fiber-client-resolve', sys.executable, ROOT/'tools/java_capsule.py',
            'resolve', app, '--candidate', candidate, '--gradle', 'gradle')
        require(digest(read_file(candidate)) == CANDIDATE, 'java-http-fiber-original-client-closure')
        commands.run('fiber-client-review', sys.executable, ROOT/'tools/java_capsule.py',
            'review-lock', app, '--candidate', candidate, '--expect', CANDIDATE)
        stage = 'compiler-cache'
        cache = compiler_cache(commands, wasi_sdk, output, read_only_cache)
        stage = 'offline-component'
        remaining = min(900, commands.deadline-time.monotonic())
        require(remaining > 0, 'java-http-fiber-original-deadline-expired')
        artifact = build(app, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
            timeout=remaining, read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE,
            failure_contexts=FIXTURE_SOURCES)
        classpath = read_json(artifact/'java-classpath.json')
        jars = [row for row in classpath['artifacts'] if row['id'] == COORDINATE]
        require(len(jars) == 1 and jars[0]['originalDigest'] == ORIGINAL_JAR,
                'java-http-fiber-original-jar-drift')
        profile = read_json(artifact/'runtime-profile.json')
        require(profile['profile'] == FIBER_IO_PROFILE, 'java-http-fiber-runtime-profile-drift')
        stage = 'signed-lifecycle'
        node = node_controls(artifact, {key: binaries[key] for key in ('latent', 'latentd', 'capsule_authoring')},
                             output/'node', deadline=commands.deadline)
        require(node['status'] == 'passed' and len(node['cases']) == 11,
                'java-http-fiber-incomplete-lifecycle')
        require(before == {name: file_identity(ROOT/name) for name in before}
                and native == {name: file_identity(path) for name, path in binaries.items()}
                and time.monotonic() < commands.deadline, 'java-http-fiber-final-material-drift')
        result = {'schemaVersion': 'latent.java.http-fiber-campaign.v1', 'status': 'passed',
            'materials': before, 'nativeProducts': native,
            'library': {'coordinate': COORDINATE, 'originalDigest': ORIGINAL_JAR,
                        'capturedGraph': CANDIDATE, 'classpath': jars[0]},
            'artifact': {name: file_identity(artifact/name) for name in ('component.wasm', 'BUILD-COMPLETE.json',
                'source-inputs.json', 'recipe-inputs.json', 'compiler-inputs.json', 'build-observation.json',
                'http-client-profile.json', 'runtime-profile.json', 'java-classpath.json')},
            'runtimeProfile': profile, 'nodeReceipt': file_identity(output/'node/qualification.json'),
            'caseNames': list(CASES), 'lifecycleInvocations': 12, 'authorityDenials': 1,
            'full688Qualified': False, 'full741Qualified': False,
            'limitations': ['Finite ordinary HTTP/fiber-I/O proof only; not a full scheduler/port qualification.',
                'Uncaught Java root exception drains accepted work; fuel trap separately bypasses guest cleanup.',
                'No HTTPS/nonzero connect/read-timeout, cross-tenant, allocation bound or release claim.']}
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        try:
            write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage,
                'full688Qualified': False, 'full741Qualified': False, 'caseNames': list(CASES)})
        except Exception:
            pass
        raise


def run(output, prepared, wasi_sdk):
    require(sys.platform == 'linux', 'java-http-fiber-linux-required')
    require(output != ROOT and ROOT not in output.parents, 'java-http-fiber-output-outside-source')
    history = verify_prepared(prepared)
    binaries = native_products(prepared)
    output = fresh(output)
    environment = build_environment(output)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output/'commands'), environment,
                        deadline_seconds=MAX_SECONDS, command_seconds=300)
    result = execute(commands, binaries, wasi_sdk, output/'campaign')
    require(history == verify_prepared(prepared), 'java-http-fiber-retained-native-material-drift')
    result.update(schemaVersion='latent.java.http-fiber-replay.v1', nativeSource=history,
        nativeRecompiled=False, productionNativeTupleCreated=False,
        fixtureSource=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    write_json(output/'qualification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--wasi-sdk', type=Path)
    args = parser.parse_args()
    require(sys.platform == 'linux', 'java-http-fiber-linux-required')
    output = args.output.resolve()
    require(output != ROOT and ROOT not in output.parents, 'java-http-fiber-output-outside-source')
    if args.prepare:
        require(args.prepared is None and args.wasi_sdk is None, 'java-http-fiber-prepare-only')
        prepare(output)
    else:
        require(args.prepared is not None and args.wasi_sdk is not None, 'java-http-fiber-explicit-tools-required')
        value = run(output, args.prepared.resolve(strict=True), args.wasi_sdk.resolve(strict=True))
        print(json.dumps({'status': value['status'], 'invocations': value['lifecycleInvocations']}))
