#!/usr/bin/env python3
"""Build captured ordinary libc calls, sign and execute the finite C profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build, c_capsule_project
from tools.c_guest.standard_facilities import COMBINED_PROFILE, DEFAULT, LOGGING_PROFILE, PROFILE
from tools.c_standard_facilities_probe import prepare
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.qualify_java_server_lifecycle_suite import native as build_native
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, read_file, read_json, write_json

HELPERS = ('tools/c_standard_facilities_probe.py', 'tools/qualify_c_standard_facilities.py',
           'tools/c_standard_logging_probe.py', 'tools/c_standard_combined_probe.py',
           'tools/c_compiled_resource_fixture.py',
           'tools/run_rust_capsule_workflow.py', 'tools/rust_capsule_node.py',
           'tools/guest_runtime_profiles.py', 'tools/guest_runtime_grants.py',
           'tools/qualify_java_server_lifecycle.py', 'tools/qualify_java_server_lifecycle_suite.py')
PUBLIC_FIELDS = ('schemaVersion', 'status', 'scope', 'invocations', 'samples', 'providerIdle',
                 'cStandardGrantSteps', 'cStandardLoggingGrant', 'cStandardCombinedGrantSteps',
                 'cCompiledResourceCases', 'cCompiledResourceRecovery',
                 'limits', 'nodeShutdown', 'peerShutdown',
                 'cliCalls', 'reason', 'peerFailure')


def identity():
    status = subprocess.run(['git', '-c', 'safe.directory=' + str(ROOT), 'status', '--porcelain',
                             '--untracked-files=normal'], cwd=ROOT, capture_output=True, check=True, timeout=15)
    require(not status.stdout, 'c-standard-qualification-requires-clean-recorded-source')
    revision = subprocess.run(['git', '-c', 'safe.directory=' + str(ROOT), 'rev-parse', 'HEAD', 'HEAD^{tree}'],
                              cwd=ROOT, capture_output=True, check=True, timeout=15).stdout.decode().splitlines()
    return {'head': revision[0], 'tree': revision[1], 'helpers': {
        name: file_identity(ROOT / name, 1048576) for name in sorted(set((*c_capsule_build.RECIPE, *HELPERS)))}}


def verify_compiled_resources(build, project, prepared):
    from tools import guest_resources
    from tools.build_snapshot import digest
    identities = {row['digest'] for row in prepared['resources']}
    objects = {'resources/objects/' + identity[7:]: read_file(build / 'resources/objects' / identity[7:], guest_resources.MAX_FILE)
               for identity in identities}
    lock = read_file(project / 'latent.dependencies.lock.json', guest_resources.MAX_DEPENDENCY_LOCK)
    verified = guest_resources.verify(read_file(build / guest_resources.INDEX, guest_resources.MAX_DOCUMENT), objects,
        source_digest=digest(read_file(build / 'source-inputs.json')),
        component_digest=digest(read_file(build / 'component.wasm', 64 * 1024 * 1024)),
        dependency_lock_digest=digest(lock), dependency_lock=lock)
    expected = {row['path']: (row['digest'], row['size'], row['mediaType']) for row in prepared['resources']}
    require({row['path']: (row['digest'], row['size'], row['mediaType']) for row in verified['resources']} == expected
            and all(row['origin'] == 'dependency' and row['owner'] == 'outside-owner/raw-resource/1'
                    for row in verified['resources']), 'c-compiled-resource-exact-package-bytes')
    require(verified['count'] == 4 and len(objects) == 3 and prepared['originalsRemoved'],
            'c-compiled-resource-alias-empty-offline-capture')
    compiler = read_json(build / 'compiler-inputs.json')
    resources = read_json(build / 'c-resources.json')
    for row in resources['resources']:
        require(any(item['path'].replace('\\', '/').endswith('/' + row['source'])
                    and item['digest'] == row['digest'] and item['size'] == row['size']
                    for item in compiler['preprocessorInputs']), 'c-compiled-resource-preprocessor-membership')
    return {'index': file_identity(build / guest_resources.INDEX), 'selection': file_identity(build / 'c-resources.json'),
            'count': 4, 'objects': 3, 'preprocessorMembership': True, 'sourceOriginalsRemoved': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('zig', 'wit-bindgen', 'wasm-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--native-directory', type=Path)
    parser.add_argument('--native-tuple', type=Path)
    parser.add_argument('--build-native', action='store_true')
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument('--standard-logging', action='store_true')
    profile.add_argument('--combined-profile', action='store_true')
    profile.add_argument('--compiled-resources', action='store_true')
    profile.add_argument('--libfetch-http', action='store_true')
    args = parser.parse_args(argv)
    if args.libfetch_http:
        return qualify_http(args)
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-standard-unprivileged-linux-python313-required')
    require((args.native_directory is None) == (args.native_tuple is None)
            and args.build_native == (args.native_directory is None), 'c-standard-select-one-complete-native-source')
    destination = args.output.absolute()
    require(destination != ROOT and ROOT not in destination.parents and destination not in ROOT.parents,
            'c-standard-qualification-must-be-outside-checkout')
    output = fresh(destination)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=900)
    commands.environment.update(CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR', str(ROOT / 'target')),
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0', CARGO_INCREMENTAL='0')
    source = identity()
    directory, receipt = args.native_directory, args.native_tuple
    if args.build_native:
        build_root = output / 'native-build'; build_root.mkdir(mode=0o700)
        directory, receipt = build_native(commands, build_root, tomllib.loads((ROOT / 'tools/toolchain.toml').read_text()))
    inputs = {name: directory.resolve(strict=True) / name
              for name in ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring')}
    native = ordinary_tuple(receipt, inputs)
    binaries = output / 'native'; binaries.mkdir(mode=0o700)
    owned = {}
    for name, original in inputs.items():
        target = binaries / name
        shutil.copyfile(original, target); target.chmod(0o700)
        require(file_identity(target, 512 * 1024 * 1024) == file_identity(original, 512 * 1024 * 1024),
                'c-standard-native-capture-changed')
        owned[name] = target
    installed = {'zig': args.zig.resolve(strict=True), 'wit-bindgen': args.wit_bindgen.resolve(strict=True),
                 'wasm-tools': args.wasm_tools.resolve(strict=True)}
    result = {'schemaVersion': 'latent.c-standard-facilities.qualification.v1', 'status': 'in-progress',
              'profile': DEFAULT if args.compiled_resources else COMBINED_PROFILE if args.combined_profile
                         else LOGGING_PROFILE if args.standard_logging else PROFILE,
              'source': source, 'nativeTuple': native, 'publisherAuthenticated': False,
              'releasePublished': False, 'builds': {}}
    stage = 'build'
    try:
        (output / 'projects').mkdir(mode=0o700)
        (output / 'builds').mkdir(mode=0o700)
        builds = []
        for template in TEMPLATES:
            project = c_capsule_project.create(output / 'projects' / template, template)
            if template == 'greeting':
                if args.compiled_resources:
                    from tools.c_compiled_resource_fixture import prepare as prepare_resources
                    result['capturedCompiledResources'] = prepare_resources(project)
                elif args.combined_profile:
                    from tools.c_standard_combined_probe import prepare as prepare_combined
                    result['capturedStandardLibrary'] = prepare_combined(project)
                elif args.standard_logging:
                    from tools.c_standard_logging_probe import prepare as prepare_logging
                    result['capturedStandardLibrary'] = prepare_logging(project)
                else:
                    result['capturedStandardLibrary'] = prepare(project)
            build = c_capsule_build.build(project, output / 'builds' / template,
                owned['capsule_contracts'], owned['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', installed=installed)
            result['builds'][template] = read_json(build / 'BUILD-COMPLETE.json')
            if template == 'greeting' and args.compiled_resources:
                result['compiledResources'] = verify_compiled_resources(build, project, result['capturedCompiledResources'])
            builds.append(build)
        stage = 'sign'
        commands.run('demo-sign', owned['capsule_authoring'], 'demo-sign', output / 'releases', *builds)
        stage = 'node'
        observed = run(owned['latent'], owned['latentd'], output / 'releases', output / 'node',
                       language='c', c_standard_facilities=not (args.standard_logging or args.combined_profile or args.compiled_resources),
                       c_standard_logging=args.standard_logging, c_standard_combined=args.combined_profile,
                       c_compiled_resources=args.compiled_resources)
        public = {name: observed[name] for name in PUBLIC_FIELDS if name in observed}
        write_json(output / 'node/public-workflow.json', public)
        grant_verified = (len(observed.get('cCompiledResourceCases', [])) == 6
                          and len(observed.get('cCompiledResourceRecovery', [])) == 2 if args.compiled_resources else
                          len(observed.get('cStandardCombinedGrantSteps', [])) == 4 if args.combined_profile else
                          observed.get('cStandardLoggingGrant', {}).get('capability') == 'latent:log/log@0.1.0'
                          if args.standard_logging else len(observed.get('cStandardGrantSteps', [])) == 3)
        require(observed['status'] == 'passed' and grant_verified,
                'c-standard-original-authoring-and-grant-matrix-must-pass')
        require(source == identity() and ordinary_tuple(receipt, inputs) == native
                and ordinary_tuple(receipt, owned) == native, 'c-standard-inputs-changed')
        result.update(status='passed', qualifier=file_identity(Path(__file__)),
                      workflow=file_identity(output / 'node/workflow.json'), invocations=len(observed['invocations']),
                      commands=commands.records)
        write_json(output / 'qualified.json', result)
    except BaseException as error:
        failure, public = output / 'node/FAILED.json', output / 'node/public-workflow.json'
        if failure.exists() and not public.exists():
            observed = read_json(failure)
            write_json(public, {name: observed[name] for name in PUBLIC_FIELDS if name in observed})
        result.update(status='failed', stage=stage, reason=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', result)
        raise
    print(json.dumps({'status': result['status'], 'invocations': result['invocations']}))
    return 0


HTTP_MATERIALS = (
    'tools/c_thread_runtime_fixture.py', 'tools/c_thread_runtime_node.py',
    'tools/qualify_c_thread_runtime.py', 'tools/go_standard_http_node.py',
    'tools/static_api/node.py', 'tools/standard_http/__init__.py',
    'tools/standard_http/peer.py', 'tools/standard_http/protocol.py',
    'tools/standard_http/vectors.py', 'tools/standard_http/observations.py',
    '.github/workflows/c-guest-authoring.yml',
    'sdk/c-guest/runtime-fixtures/libfetch/probe.c',
    'sdk/c-guest/runtime-fixtures/libfetch/world.wit',
)


def http_sources(commands, output, *, capture):
    import time
    from tools.qualify_c_thread_runtime import MATERIALS, THREAD_RECIPE, COMPATIBILITY_RECIPE
    names = sorted(set((*c_capsule_build.RECIPE, *HELPERS, *MATERIALS, *THREAD_RECIPE,
                        *COMPATIBILITY_RECIPE, *HTTP_MATERIALS)))
    require(len(names) <= 256, 'c-libfetch-helper-count')
    rows, total = {}, 0
    for name in names:
        require(time.monotonic() < commands.deadline, 'c-libfetch-capture-original-deadline')
        data = read_file(ROOT / name, 4 * 1024**2)
        total += len(data)
        require(total <= 16 * 1024**2, 'c-libfetch-helper-bytes')
        rows[name] = file_identity(ROOT / name, 4 * 1024**2)
        if capture:
            target = output / 'owner-inputs' / name
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
            require(file_identity(target, 4 * 1024**2) == rows[name], 'c-libfetch-retained-helper-identity')
    return rows


def http_build_evidence(artifact, source):
    from tools.c_thread_runtime_fixture import HTTP_API
    from tools.c_guest.threading import IMPORTS, PROFILE as THREAD_PROFILE
    from tools.qualify_c_thread_runtime import supplement_evidence
    marker = read_json(artifact / 'BUILD-COMPLETE.json')
    observation = read_json(artifact / 'build-observation.json')
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    require(read_file(artifact / 'source-inputs.json') == source
            and marker['packageAssembled'] is True
            and marker['sourceDigest'] == file_identity(artifact / 'source-inputs.json')['sha256']
            and marker['observationDigest'] == file_identity(artifact / 'build-observation.json')['sha256']
            and marker['componentDigest'] == observation['componentDigest'] == component['sha256']
            and observation['componentSize'] == component['bytes']
            and all(row['exitCode'] == 0 for row in marker['commands'])
            and any(row['stage'] == 'zig' for row in marker['commands']), 'c-libfetch-original-build-observation')
    capsule = read_json(artifact / 'capsule.json')
    require(capsule['execution']['threading'] == 'cooperative'
            and len(capsule['imports']) == 3
            and all(row['optional'] is False for row in capsule['imports'])
            and {row['contract'] for row in capsule['imports']} == {*IMPORTS, 'latent:http/streaming@0.3.0'}
            and capsule['exports'] == [HTTP_API], 'c-libfetch-actual-component-contract')
    derivation = read_json(artifact / 'c-threading-derivation.json')
    require(derivation['profile'] == THREAD_PROFILE and derivation['publicExport'] == HTTP_API + '#run'
            and type(derivation['rootRecordBytes']) is int and derivation['rootRecordBytes'] == 144
            and derivation['canonicalComponentAuthenticated'] is False
            and derivation['standardRuntimeQualified'] is False, 'c-libfetch-original-cooperative-derivation')
    assets = supplement_evidence(artifact, component, derivation)
    for name, material in (('compiler-inputs.json', 'c-compiler-sysroot-and-isolation'),
            ('c-threading-derivation.json', 'c-threading-derivation'),
            ('c-threading-compatibility.json', 'c-threading-compatibility'), ('recipe-inputs.json', 'build-recipe')):
        actual = file_identity(artifact / name, 16 * 1024**2)
        require([row for row in observation['materials'] if row['name'] == material] == [
            {'name': material, 'digest': actual['sha256'], 'size': actual['bytes']}],
            'c-libfetch-actual-compiler-material')
    return {'component': component, 'derivation': derivation, 'compatibilityAssets': assets}


def qualify_http(args):
    import time
    from tools import c_thread_runtime_fixture as fixture, c_thread_runtime_node as node
    from tools.phase3_resource_identity import source_identity
    from tools.rust_capsule_project import snapshot, inventory
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-libfetch-unprivileged-linux-python313')
    require(args.build_native and args.native_directory is None and args.native_tuple is None,
            'c-libfetch-one-current-native-build')
    stamp = os.environ.get('LSF_C_LIBFETCH_STARTED_NS', '')
    require(stamp.isascii() and stamp.isdigit() and len(stamp) <= 20, 'c-libfetch-setup-clock-required')
    elapsed = (time.time_ns() - int(stamp)) / 1_000_000_000
    require(0 <= elapsed < 1315, 'c-libfetch-setup-within-original-parent')
    parent = time.monotonic() + 1320 - elapsed
    destination = args.output.absolute()
    require(destination != ROOT and ROOT not in destination.parents and destination not in ROOT.parents,
            'c-libfetch-owned-output-outside-checkout')
    output = fresh(destination)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1320, command_seconds=900)
    commands.deadline = parent - 5
    commands.environment.update(CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR', str(ROOT / 'target')),
        CARGO_BUILD_JOBS='2', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0', CARGO_INCREMENTAL='0')
    result = {'schemaVersion': 'latent.c.libfetch.qualification.v1', 'status': 'incomplete',
              'scope': 'one-authentic-libfetch-client-five-signed-cells', 'full690Qualified': False,
              'fullCCostModelQualified': False, 'publisherAuthenticated': False, 'releasePublished': False,
              'limits': {'parentSeconds': 1320, 'commandSeconds': 900, 'cleanupReserveSeconds': 5,
                         'jobs': 2, 'cells': 5, 'components': 1}, 'setupSeconds': elapsed}
    stage = 'source'
    try:
        head = commands.run('libfetch-head', 'git', 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
        require(len(head) == 2 and all(len(value) == 40 and all(c in '0123456789abcdef' for c in value)
                                      for value in head), 'c-libfetch-source-head-tree')
        commands.run('libfetch-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        helpers = http_sources(commands, output, capture=True)
        original_source = source_identity(ROOT)
        result['source'] = {'head': head[0], 'tree': head[1], 'native': original_source, 'helpers': helpers}
        stage = 'current-native'
        build_root = output / 'native-build'; build_root.mkdir(mode=0o700)
        directory, receipt = build_native(commands, build_root,
            tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode('utf-8')))
        native_paths = {name: directory / name for name in
                        ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring')}
        native = ordinary_tuple(receipt, native_paths)
        result['nativeTuple'] = native
        stage = 'one-c-component'
        sdk_source = inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
        project = fixture.prepare_http(output / 'project')
        source = inventory(snapshot(project))
        require(read_json(project / 'sdk-lock.json')['sdk'] == json.loads(sdk_source),
                'c-libfetch-complete-original-sdk-captured')
        result['sdkInputsBefore'] = json.loads(sdk_source)
        installed = {'zig': args.zig.resolve(strict=True), 'wit-bindgen': args.wit_bindgen.resolve(strict=True),
                     'wasm-tools': args.wasm_tools.resolve(strict=True)}
        tools = {name: file_identity(path, 512 * 1024**2) for name, path in installed.items()}
        artifact = c_capsule_build.build(project, output / 'build', native_paths['capsule_contracts'],
            native_paths['package'], 'https://github.com/KirilsTurkins/latent-service-fabric',
            installed=installed, _deadline=parent)
        result['build'] = http_build_evidence(artifact, source)
        result['tools'] = tools
        stage = 'five-signed-cells'
        result['node'] = node.run_http(artifact, native_paths, output / 'node', deadline=commands.deadline)
        require(result['node']['status'] == 'passed' and len(result['node']['cases']) == 5,
                'c-libfetch-five-real-cells-required')
        require(helpers == http_sources(commands, output, capture=False)
                and original_source == source_identity(ROOT)
                and source == inventory(snapshot(project))
                and sdk_source == inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
                and ordinary_tuple(receipt, native_paths) == native
                and tools == {name: file_identity(path, 512 * 1024**2) for name, path in installed.items()},
                'c-libfetch-all-original-inputs-unchanged')
        commands.run('libfetch-still-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        require(time.monotonic() < commands.deadline, 'c-libfetch-original-deadline')
        result.update(status='passed', commands=commands.records)
        write_json(output / 'qualified.json', result)
        print(json.dumps({'status': 'passed', 'cells': 5, 'independentClientCount': 1, 'full690Qualified': False}))
        return 0
    except BaseException as error:
        result.update(status='failed', stage=stage, reason=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', result)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
