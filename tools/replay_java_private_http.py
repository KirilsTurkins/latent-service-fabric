#!/usr/bin/env python3
"""Explicit mixed-source native replay; fresh Java components, unchanged provider gates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as inputs
from tools.application_dependency_store import DependencyError, Store
from tools.build_observation import build_environment
from tools.java_application_dependencies import deterministic_jar
from tools.java_capsule_build import RECIPE, build
from tools.java_dependency_authoring import edit, review
from tools.java_dependency_resolution import resolve
from tools.guest_dependency_inputs import capture_source
from tools.java_standard_http_node import run as provider_controls
from tools.java_standard_http_project import project as standard_project
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.java_replay_materials import prepare, native_products, verify_prepared
from tools.java_standard_http_library import compiler_cache
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

from tools.qualify_java_private_http import (IDENTITIES, MAX_SECONDS, MAX_BUILD_SECONDS, PRODUCTS,
    make_jars, capture, negative_inputs, verify_node)

FEATURE_SOURCE = '0c869e3912244b798131403c683a0901fa2220e5'


def qualify(output, prepared, wasi_sdk, read_only_cache):
    require(sys.platform == 'linux', 'java-private-http-linux-required')
    require(output != ROOT and ROOT not in output.parents, 'java-private-http-outside-source-required')
    output = fresh(output)
    deadline = time.monotonic() + MAX_SECONDS
    environment = build_environment(output)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output / 'acquisition'), environment,
                        deadline_seconds=MAX_SECONDS, command_seconds=60)
    commands.deadline = deadline
    materials = {name: file_identity(ROOT / name) for name in
                 (*dict.fromkeys(RECIPE), 'tools/qualify_java_private_http.py', 'tools/java_standard_http_node.py')}
    diagnostic_materials = {name: file_identity(ROOT/name) for name in
                            ('tools/java_replay_materials.py', 'tools/replay_java_private_http.py')}
    require(materials['tools/qualify_java_private_http.py']['sha256'] ==
            'sha256:dc99932e14b8628091e8820d6551ded6f7397395e6130923f2f74f3a9de7c405',
            'java-replay-production-feature-source')
    binaries = native_products(prepared)
    before = {name: file_identity(path) for name, path in binaries.items()}
    native_source = verify_prepared(prepared)
    native_receipt = file_identity(prepared / 'retrieval.json')
    rows, phase = [], 'outside-jar-acquisition'
    try:
        library = fresh(output / 'original-library')
        jars = make_jars(library, commands)
        projects = []
        for ordinal, identities in enumerate(IDENTITIES):
            root = fresh(output / ('variant-' + str(ordinal)))
            app, captured = capture(root, jars, identities)
            projects.append((root, app, captured))
        require(len({captured['sdkLockDigest'] for _, _, captured in projects}) == 1
                and len({identity for _, _, captured in projects for identity in captured['identities']}) == 4,
                'java-private-http-varied-identity-or-sdk-drift')
        negatives = negative_inputs(projects[0][1])
        shutil.rmtree(library)
        require(not library.exists(), 'java-private-http-originals-not-removed')
        compiler_inputs = None
        for ordinal, (root, app, captured) in enumerate(projects):
            phase = 'variant-' + str(ordinal) + '-offline-build'
            source = inventory(snapshot(app))
            captured_source = inventory(capture_source(app, 'java').files)
            remaining = min(MAX_BUILD_SECONDS, deadline - time.monotonic())
            require(remaining > 0, 'java-private-http-original-deadline-expired')
            artifact = build(app, root / 'build', binaries['capsule_contracts'], binaries['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
                timeout=remaining, read_only_cache=read_only_cache)
            require(not library.exists() and inventory(snapshot(app)) == source,
                    'java-private-http-original-or-reviewed-source-drift')
            require(read_file(artifact / 'source-inputs.json') == captured_source,
                    'java-private-http-compiled-source-drift')
            classpath = read_json(artifact / 'java-classpath.json')
            selected = {row['id']: row for row in classpath['artifacts']}
            require(set(selected) == set(captured['identities']), 'java-private-http-compiled-classpath')
            for name, identity in zip(('primary', 'child'), captured['identities'], strict=True):
                require(selected[identity]['originalDigest'] == captured['originalJars'][name]['sha256'],
                        'java-private-http-compiled-original-jar')
            require(any(row['owner'] == captured['identities'][1]
                        and row['path'] == 'outside/http/badge.txt' for row in classpath['resources']),
                    'java-private-http-compiled-transitive-resource')
            recipe = read_json(artifact / 'recipe-inputs.json')
            require(recipe == {name: {'digest': materials[name]['sha256'], 'size': materials[name]['bytes']}
                              for name in RECIPE}
                    and not any('compatibility-catalogue/' in name for name in recipe),
                    'java-private-http-catalogue-data-input')
            actual_compiler = read_file(artifact / 'compiler-inputs.json', 8 * 1024 * 1024)
            require(compiler_inputs is None or compiler_inputs == actual_compiler,
                    'java-private-http-compiler-input-drift')
            compiler_inputs = actual_compiler
            phase = 'variant-' + str(ordinal) + '-signed-provider'
            node = provider_controls(artifact, {name: binaries[name] for name in
                ('latent', 'latentd', 'capsule_authoring')}, root / 'node', deadline=deadline)
            verify_node(node)
            rows.append({'ordinal': ordinal, 'capture': captured, 'originalsRemovedBeforeBuild': True,
                'component': file_identity(artifact / 'component.wasm'),
                'sourceInputs': file_identity(artifact / 'source-inputs.json'),
                'recipeInputs': file_identity(artifact / 'recipe-inputs.json'),
                'compilerInputs': file_identity(artifact / 'compiler-inputs.json'),
                'runtimeProfile': file_identity(artifact / 'http-client-profile.json'),
                'providerReceipt': file_identity(root / 'node/qualification.json'),
                'cases': node['cases'], 'shutdown': node['shutdown'], 'peer': node['peer'],
                'catalogueDataInputs': [], 'applicationTransportInjected': False})
        require(materials == {name: file_identity(ROOT / name) for name in materials}
                and before == {name: file_identity(path) for name, path in binaries.items()}
                and native_receipt == file_identity(prepared / 'retrieval.json')
                and diagnostic_materials == {name: file_identity(ROOT/name) for name in diagnostic_materials}
                and time.monotonic() < deadline, 'java-private-http-final-material-drift')
        result = {'schemaVersion': 'latent.java.private-http.replay-qualification.v1', 'status': 'passed',
            'materials': materials, 'nativeProducts': before, 'nativeSource': native_source,
            'featureSource': FEATURE_SOURCE, 'fixtureSource': subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'productionNativeTupleRecreated': False, 'nativeRecompiled': False,
            'diagnosticMaterials': diagnostic_materials,
            'variants': rows, 'negativeControls': negatives,
            'privateHttpInvocations': 26, 'libraryStartupOnBuildHost': False,
            'publishedSecondClientQualified': False, 'fullTicketQualification': False,
            'limitations': ['Plain HTTP synchronous URLConnection profile; no new HTTPS or phase-timeout semantics.',
                'Historical native products stay source-attributed; no new native host compilation claim.',
                'Sampled native RSS is not an allocator/kernel upper-bound proof.']}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'phase': phase,
                'completedVariants': len(rows), 'fullTicketQualification': False})
        except Exception:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--wasi-sdk', type=Path)
    parser.add_argument('--cache-output', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == 'linux', 'java-replay-linux-required')
    output = args.output.resolve()
    require(output != ROOT and ROOT not in output.parents, 'java-replay-outside-source')
    if args.prepare:
        require(not any((args.prepared, args.wasi_sdk, args.cache_output)), 'java-replay-prepare-only')
        prepare(output)
    else:
        require(all((args.prepared, args.wasi_sdk, args.cache_output)), 'java-replay-inputs-required')
        prepared = args.prepared.resolve(strict=True)
        verify_prepared(prepared)
        cache_root = args.cache_output.resolve()
        require(cache_root != ROOT and ROOT not in cache_root.parents, 'java-replay-cache-outside-source')
        cache_root = fresh(cache_root)
        environment = build_environment(cache_root)
        if 'JAVA_HOME' in os.environ:
            environment['JAVA_HOME'] = os.environ['JAVA_HOME']
        commands = Commands(ROOT, fresh(cache_root/'commands'), environment,
                            deadline_seconds=900, command_seconds=60)
        cache = compiler_cache(commands, args.wasi_sdk.resolve(strict=True), cache_root, None)
        result = qualify(output, prepared, args.wasi_sdk.resolve(strict=True), cache)
        verify_prepared(prepared)
        print(json.dumps({'status': result['status'], 'invocations': result['privateHttpInvocations']}))
