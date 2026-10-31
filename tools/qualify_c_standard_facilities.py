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
from tools.c_guest.standard_facilities import (COMBINED_PROFILE, DEFAULT, LOGGING_PROFILE, PROFILE,
    FETCH_PROFILE, FETCH_STANDARD_PROFILE)
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
    profile.add_argument('--libucl-http', action='store_true')
    profile.add_argument('--outside-capture', action='store_true')
    args = parser.parse_args(argv)
    if args.libfetch_http or args.libucl_http or args.outside_capture:
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
    'tools/c_catalogue_free_build.py', 'tools/dev_tool_distribution.py',
    'wit/host-abi-phase3-v5.json',
)



LIBUCL_MATERIALS = tuple('sdk/c-guest/runtime-fixtures/libucl/' + name for name in (
    'UPSTREAM.json',
    'probe.c',
    'world.wit',
    'upstream/src/ucl_emitter.c',
    'upstream/src/ucl_emitter_streamline.c',
    'upstream/src/ucl_emitter_utils.c',
    'upstream/src/ucl_hash.c',
    'upstream/src/ucl_parser.c',
    'upstream/src/ucl_schema.c',
    'upstream/src/ucl_util.c',
    'upstream/src/ucl_msgpack.c',
    'upstream/src/ucl_cbor.c',
    'upstream/src/ucl_sexp.c',
    'upstream/include/ucl.h',
    'upstream/src/ucl_internal.h',
    'upstream/src/ucl_hash.h',
    'upstream/src/ucl_chartable.h',
    'upstream/src/mum.h',
    'upstream/src/tree.h',
    'upstream/klib/khash.h',
    'upstream/klib/kvec.h',
    'upstream/uthash/utlist.h',
    'upstream/uthash/utstring.h',
    'upstream/uthash/uthash.h',
    'upstream/COPYING',
    'upstream/configure.ac',
    'upstream/src/Makefile.am',
    'upstream/Makefile.unix',
))

def http_sources(commands, output, *, capture, runtime_profile=FETCH_PROFILE):
    import time
    from tools.qualify_c_thread_runtime import MATERIALS, THREAD_RECIPE, COMPATIBILITY_RECIPE
    require(type(runtime_profile) is str and runtime_profile in (FETCH_PROFILE, FETCH_STANDARD_PROFILE),
            'c-http-exact-runtime-profile')
    extra = LIBUCL_MATERIALS if runtime_profile == FETCH_STANDARD_PROFILE else ()
    names = sorted(set((*c_capsule_build.RECIPE, *HELPERS, *MATERIALS, *THREAD_RECIPE,
                        *COMPATIBILITY_RECIPE, *HTTP_MATERIALS, *extra)))
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


def http_build_evidence(artifact, source, *, runtime_profile=FETCH_PROFILE):
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
    from tools.c_guest.standard_facilities import PROFILE_IMPORTS
    require(type(runtime_profile) is str and runtime_profile in (FETCH_PROFILE, FETCH_STANDARD_PROFILE),
            'c-http-exact-runtime-profile')
    expected_imports = {*IMPORTS, *PROFILE_IMPORTS[runtime_profile]}
    capsule = read_json(artifact / 'capsule.json')
    require(capsule['execution']['threading'] == 'cooperative'
            and len(capsule['imports']) == len(expected_imports)
            and all(row['optional'] is False for row in capsule['imports'])
            and {row['contract'] for row in capsule['imports']} == expected_imports
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
    if runtime_profile == FETCH_STANDARD_PROFILE:
        from tools import guest_runtime_receipts
        from tools.c_guest import threading
        selection = read_json(artifact / 'standard-runtime-selection.json')
        guest_runtime_receipts.validate(selection,
            source=file_identity(artifact / 'source-inputs.json')['sha256'],
            component=component['sha256'], language='c', profile=runtime_profile)
        actual = file_identity(artifact / 'standard-runtime-selection.json', 65536)
        require([row for row in observation['materials'] if row['name'] == 'standard-runtime-selection'] == [
            {'name': 'standard-runtime-selection', 'digest': actual['sha256'], 'size': actual['bytes']}],
            'c-libucl-signed-normal-runtime-selection')
        for name, sha in threading.CLOCK_LIBC.items():
            material = threading.clock_libc_material_name(name)
            rows = [row for row in observation['materials'] if row['name'] == material]
            require(len(rows) == 1 and rows[0]['digest'] == 'sha256:' + sha
                    and type(rows[0]['size']) is int and 0 < rows[0]['size'] <= 32768,
                    'c-libucl-signed-original-clock-inputs')
    return {'component': component, 'derivation': derivation, 'compatibilityAssets': assets}


HTTP_ROUTING_CASES = tuple('component::c::tests::' + name for name in (
    'c_ready_handoff_final_graph_refuses_resume_or_mismatched_target',
    'c_wait_canonical_functions_keep_suspend_and_deferred_resume_distinct',
    'c_wait_final_graph_requires_the_exact_canonical_wake_target',
)) + ('c_preimage::tests::c_finite_preflight_refuses_expansive_signatures_locals_and_control_before_validator',)


def http_routing_result(raw, case):
    import re
    require(case in HTTP_ROUTING_CASES and type(raw) is bytes, 'c-libfetch-routing-control-input')
    text = raw.decode('utf-8')
    rows = re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)\r?$', text, re.MULTILINE)
    summaries = re.findall(r'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
        r'(\d+) measured; \d+ filtered out; finished in [^\r\n]+\r?$', text, re.MULTILINE)
    require(rows == [(case, 'ok')] and summaries == [('1', '0', '0', '0')],
            'c-libfetch-one-exact-routing-control-passed')
    return {'case': case, 'passed': 1, 'failed': 0, 'ignored': 0}


def http_routing_controls(commands, pins):
    import re
    import time
    original_deadline, original_seconds = commands.deadline, commands.command_seconds
    # One shared ceiling across all four real controls, clipped to the same
    # parent-5 deadline; neither a new parent nor a per-case allowance reset.
    commands.deadline = min(original_deadline, time.monotonic() + 120)
    commands.command_seconds = min(original_seconds, 120)
    try:
        # build_native already selected/validated the pinned direct rustc.
        # Its canonical toolchain bin directory also contains direct cargo;
        # do not repeat rustup/wasm/compiler probes outside this command owner.
        rustc = Path(commands.environment.get('RUSTC', ''))
        require(rustc.is_absolute() and rustc.name == 'rustc' and rustc.is_file()
                and rustc.resolve(strict=True) == rustc, 'c-libfetch-built-native-rustc')
        cargo = rustc.with_name('cargo')
        require(cargo.is_file() and not cargo.is_symlink() and cargo.resolve(strict=True) == cargo,
                'c-libfetch-direct-toolchain-cargo')
        cargo_identity = file_identity(cargo, 512 * 1024**2)
        reported = commands.run('libfetch-routing-cargo-version', cargo, '--version').decode('utf-8').strip()
        version = str(pins['rust']['toolchain'])
        require(len(reported) <= 256 and re.fullmatch(
            r'cargo ' + re.escape(version) + r'(?: \([^\r\n]+\))?', reported) is not None,
            'c-libfetch-routing-pinned-cargo-version')
        result = []
        for index, case in enumerate(HTTP_ROUTING_CASES):
            raw = commands.run('libfetch-routing-' + str(index), cargo, 'test', '--locked',
                '-p', 'latent-component-threading', '--lib', case, '--', '--exact', '--test-threads=1')
            result.append(http_routing_result(raw, case))
        require(file_identity(cargo, 512 * 1024**2) == cargo_identity
                and commands.environment.get('RUSTC') == str(rustc)
                and time.monotonic() < commands.deadline, 'c-libfetch-routing-shared-inputs-and-deadline')
        return {'cargo': cargo_identity, 'cargoVersion': reported, 'controls': result}
    finally:
        commands.deadline, commands.command_seconds = original_deadline, original_seconds


def outside_capture_evidence(project, artifact, variant):
    """Bind the actual normal source/resource capture, without borrowing a run."""
    from tools import c_thread_runtime_fixture as fixture, guest_resources
    from tools.application_dependencies import LOCK, MANIFEST
    from tools.build_snapshot import digest
    require(type(variant) is int and variant in (0, 1), 'c-outside-closed-identity-variant')
    identities = (('shop-floor/price-card', 'shop-floor/card-policy'),
                  ('warehouse/bin-label-reader', 'warehouse/label-policy'))[variant]
    lock_raw = read_file(project / LOCK, guest_resources.MAX_DEPENDENCY_LOCK)
    lock = json.loads(lock_raw)
    rows = lock['artifacts']
    require(len(rows) == 2 and [row['id'] for row in rows] == list(identities)
            and [row['role'] for row in rows] == ['application', 'resource']
            and rows[0]['dependencies'] == [identities[1]] and rows[1]['dependencies'] == []
            and lock['executableInputs'] == [] and lock['transformations'] == []
            and not (project.parent / ('outside-card-' + str(variant))).exists(),
            'c-outside-originals-removed-and-captured-identity-graph')
    expected = ({'card_client.c': fixture.CARD_LIBRARY, 'card_client.h': fixture.CARD_HEADER},
                {'expected-card.txt': fixture.CARD_RESOURCE})
    for row, files in zip(rows, expected):
        require({item['path']: (item['digest'], item['size']) for item in row['files']} ==
                {name: (digest(data), len(data)) for name, data in files.items()},
                'c-outside-original-library-resource-bytes')
    resources = read_json(artifact / 'c-resources.json')
    identity = digest(fixture.CARD_RESOURCE)
    selected = [{'path': 'configuration/card-policy.txt',
                 'source': 'dependencies/card-policy/expected-card.txt', 'mediaType': 'text/plain',
                 'owner': identities[1], 'digest': identity, 'size': len(fixture.CARD_RESOURCE)}]
    require(resources['resources'] == selected and resources['runtimeFilesystem'] == 'not-installed',
            'c-outside-actual-immutable-resource-selection')
    objects = {'resources/objects/' + identity[7:]: read_file(
        artifact / 'resources/objects' / identity[7:], guest_resources.MAX_FILE)}
    verified = guest_resources.verify(read_file(artifact / guest_resources.INDEX, guest_resources.MAX_DOCUMENT), objects,
        source_digest=digest(read_file(artifact / 'source-inputs.json')),
        component_digest=digest(read_file(artifact / 'component.wasm', 64 * 1024**2)),
        dependency_lock_digest=digest(lock_raw), dependency_lock=lock_raw)
    require(verified['count'] == 1 and objects['resources/objects/' + identity[7:]] == fixture.CARD_RESOURCE
            and len(verified['resources']) == 1
            and all(row['origin'] == 'dependency' and row['owner'] == identities[1]
                    and row['path'] == selected[0]['path'] and row['digest'] == identity
                    for row in verified['resources']), 'c-outside-source-component-lock-resource-binding')
    inputs = read_json(artifact / 'compiler-inputs.json')
    require(any(row['path'].replace('\\', '/').endswith('/' + selected[0]['source'])
                and row['digest'] == identity and row['size'] == len(fixture.CARD_RESOURCE)
                for row in inputs['preprocessorInputs']), 'c-outside-actual-embed-preprocessor-membership')
    return {'identityVariant': variant, 'artifactIds': list(identities),
            'manifest': file_identity(project / MANIFEST), 'lock': file_identity(project / LOCK),
            'trees': [row['treeDigest'] for row in rows], 'originalsRemoved': True,
            'resourceIndex': file_identity(artifact / guest_resources.INDEX),
            'compiledResource': selected[0], 'preprocessorMembership': True,
            'independentlyMaintainedClient': False, 'qualificationBorrowed': False}


def qualify_http(args):
    import time
    outside = getattr(args, 'outside_capture', False)
    require(type(outside) is bool, 'c-http-closed-outside-selection')
    expanded = args.libucl_http or outside
    require(type(expanded) is bool, 'c-http-closed-client-selection')
    runtime_profile = FETCH_STANDARD_PROFILE if expanded else FETCH_PROFILE
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
    result = {'schemaVersion': 'latent.c.outside-capture.qualification.v1' if outside else
                              'latent.c.http-pair.qualification.v1' if expanded else 'latent.c.libfetch.qualification.v1',
              'status': 'incomplete',
              'scope': 'two-normal-outside-capture-identity-variants' if outside else
                       'two-current-http-clients-same-expanded-profile' if expanded else
                       'one-authentic-libfetch-client-five-signed-cells', 'full690Qualified': False,
              'fullCCostModelQualified': False, 'publisherAuthenticated': False, 'releasePublished': False,
              'limits': {'parentSeconds': 1320, 'commandSeconds': 900, 'cleanupReserveSeconds': 5,
                         'jobs': 2, 'cells': 2 if outside else 10 if expanded else 5,
                         'components': 2 if expanded else 1}, 'setupSeconds': elapsed}
    if expanded:
        result['independentClientCount'] = 0
    if outside:
        result['limits'].update(perOwnerCommandRetentionBytes=16 * 1024**2, clientCalls=384,
                               clientRetentionBytes=4 * 1024**2, clientSeconds=240)
    stage = 'source'
    try:
        head = commands.run('libfetch-head', 'git', 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
        require(len(head) == 2 and all(len(value) == 40 and all(c in '0123456789abcdef' for c in value)
                                      for value in head), 'c-libfetch-source-head-tree')
        commands.run('libfetch-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        helpers = http_sources(commands, output, capture=True, runtime_profile=runtime_profile)
        original_source = source_identity(ROOT)
        result['source'] = {'head': head[0], 'tree': head[1], 'native': original_source, 'helpers': helpers}
        stage = 'current-native'
        build_root = output / 'native-build'; build_root.mkdir(mode=0o700)
        pins = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode('utf-8'))
        directory, receipt = build_native(commands, build_root, pins)
        native_paths = {name: directory / name for name in
                        ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring')}
        native = ordinary_tuple(receipt, native_paths)
        result['nativeTuple'] = native
        stage = 'four-exact-c-routing-controls'
        result['routingControls'] = http_routing_controls(commands, pins)
        stage = 'one-c-component'
        sdk_source = inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
        if outside:
            from tools import c_catalogue_free_build as isolated
            standalone_root, standalone_source = isolated.stage(ROOT, output / 'standalone-sdk')
            result['standaloneBuildSource'] = standalone_source
            installed = {'zig': args.zig.resolve(strict=True), 'wit-bindgen': args.wit_bindgen.resolve(strict=True),
                         'wasm-tools': args.wasm_tools.resolve(strict=True)}
            tools = {name: file_identity(path, 512 * 1024**2) for name, path in installed.items()}
            result['sdkInputsBefore'] = json.loads(sdk_source)
            prepared, variants = [], []
            result['outsideVariants'] = variants
            for variant in (0, 1):
                stage = 'build-outside-identity-' + str(variant)
                project = fixture.prepare_unseen_library(output / ('project-outside-' + str(variant)), variant)
                source = inventory(snapshot(project))
                require(read_json(project / 'sdk-lock.json')['sdk'] == json.loads(sdk_source)
                        and read_json(project / 'capsule-project.json')['runtimeProfile'] == runtime_profile
                        and read_json(project / 'capsule-project.json')['languageStandard'] == 'c23',
                        'c-outside-same-complete-sdk-normal-c23-profile')
                artifact = output / ('build-outside-' + str(variant))
                commands.run('outside-normal-build-' + str(variant), sys.executable, '-I', '-B',
                    standalone_root / isolated.SELF, '--project', project, '--output', artifact,
                    '--contracts-tool', native_paths['capsule_contracts'], '--packager', native_paths['package'],
                    '--zig', installed['zig'], '--wit-bindgen', installed['wit-bindgen'],
                    '--wasm-tools', installed['wasm-tools'], '--repository',
                    'https://github.com/KirilsTurkins/latent-service-fabric',
                    '--expect-source-digest', standalone_source['inventoryDigest'], '--deadline', repr(parent))
                isolated_build = read_json(artifact / isolated.PROOF)
                require(isolated.verify(standalone_root, standalone_source['inventoryDigest']) == standalone_source
                        and isolated_build['sourceInventory'] == standalone_source
                        and isolated_build['sourceInventoryBeforeAfterEqual'] is True
                        and isolated_build['normalBuilderRoot'] == str(standalone_root.resolve())
                        and isolated_build['isolatedPython'] is True
                        and isolated_build['bytecodeWritesDisabled'] is True
                        and isolated_build['docsPresent'] is False
                        and isolated_build['catalogueReaderPresent'] is False,
                        'c-outside-actual-normal-parent-builder-has-no-catalogue')
                for name, expected in tools.items():
                    actual = isolated_build['toolsBeforeAfter'][name]
                    require(actual['digest'] == expected['sha256'] and actual['size'] == expected['bytes'],
                            'c-outside-same-actual-compiler-tool')
                for name, selected in (('contracts-tool', 'capsule_contracts'), ('packager', 'package')):
                    actual, expected = isolated_build['toolsBeforeAfter'][name], native['binaries'][selected]
                    require(actual['digest'].removeprefix('sha256:') == expected.get(
                            'actualExecutableSha256', expected.get('sha256', '')).removeprefix('sha256:')
                            and actual['size'] == expected['bytes'], 'c-outside-same-actual-native-helper')
                build = http_build_evidence(artifact, source, runtime_profile=runtime_profile)
                selection = read_json(artifact / 'standard-runtime-selection.json')
                variants.append({'build': build, 'capture': outside_capture_evidence(project, artifact, variant),
                    'catalogueFreeBuild': file_identity(artifact / isolated.PROOF),
                    'runtimeProfile': runtime_profile, 'runtimeInputsDigest': selection['originalRuntimeInputsDigest']})
                prepared.append((project, source, artifact))
            require(variants[0]['capture']['trees'] == variants[1]['capture']['trees']
                    and variants[0]['capture']['artifactIds'] != variants[1]['capture']['artifactIds']
                    and variants[0]['capture']['manifest'] != variants[1]['capture']['manifest']
                    and variants[0]['capture']['lock'] != variants[1]['capture']['lock']
                    and variants[0]['runtimeInputsDigest'] == variants[1]['runtimeInputsDigest'],
                    'c-outside-only-identity-graph-varies-same-original-files-and-runtime')
            node_deadline = min(commands.deadline, time.monotonic() + 300)
            client_deadline = min(node_deadline, time.monotonic() + 240)
            counters = {'calls': 0, 'controlAttempts': 0, 'retainedBytes': 0}
            for variant, (row, (project, source, artifact)) in enumerate(zip(variants, prepared)):
                stage = 'signed-outside-identity-' + str(variant)
                row['node'] = node.run_http(artifact, native_paths, output / ('node-outside-' + str(variant)),
                    deadline=node_deadline, runtime_profile=runtime_profile, client_kind='outside-card',
                    client_state=counters, client_deadline=client_deadline)
                require(row['node']['status'] == 'passed' and len(row['node']['cases']) == 1
                        and row['node']['client'] == 'outside-card' and row['node']['independentClientCount'] == 0,
                        'c-outside-current-domain-and-retirement-required')
            require(variants[0]['node']['native'] == variants[1]['node']['native'], 'c-outside-same-current-native')
            for captured_project, captured_source, artifact in prepared:
                require(captured_source == inventory(snapshot(captured_project)), 'c-outside-all-inputs-unchanged')
            result.update(sharedClientCounters=counters, outsideCaptureVariants=2,
                catalogueAbsenceQualified=True,
                independentClientCount=0, identityComparison={'sdk': json.loads(sdk_source), 'tools': tools,
                    'nativeTuple': native, 'runtimeInputsDigest': variants[0]['runtimeInputsDigest'],
                    'pairReceiptBorrowed': False, 'pairExecutionAuthenticated': False})
            # Count recorded completed roots; no command-count limit is installed.
            result['completedCommandRoots'] = {'ownerBeforeFinalFence': len(commands.records),
                'builds': [len(read_json(artifact / 'BUILD-COMPLETE.json')['commands']) for _, _, artifact in prepared],
                'nodes': [len(row['node']['commands']) for row in variants]}
        elif expanded:
            installed = {'zig': args.zig.resolve(strict=True), 'wit-bindgen': args.wit_bindgen.resolve(strict=True),
                         'wasm-tools': args.wasm_tools.resolve(strict=True)}
            tools = {name: file_identity(path, 512 * 1024**2) for name, path in installed.items()}
            result['sdkInputsBefore'] = json.loads(sdk_source)
            prepared = []
            result['clients'] = []
            for kind in ('libfetch', 'libucl'):
                stage = 'build-current-' + kind
                project = (fixture.prepare_http_standard(output / ('project-' + kind)) if kind == 'libfetch'
                           else fixture.prepare_libucl(output / ('project-' + kind), output / 'outside-libucl'))
                source = inventory(snapshot(project))
                require(read_json(project / 'sdk-lock.json')['sdk'] == json.loads(sdk_source)
                        and read_json(project / 'capsule-project.json')['runtimeProfile'] == runtime_profile,
                        'c-http-pair-same-complete-sdk-and-normal-profile')
                artifact = c_capsule_build.build(project, output / ('build-' + kind),
                    native_paths['capsule_contracts'], native_paths['package'],
                    'https://github.com/KirilsTurkins/latent-service-fabric',
                    installed=installed, _deadline=parent)
                build = http_build_evidence(artifact, source, runtime_profile=runtime_profile)
                selection = read_json(artifact / 'standard-runtime-selection.json')
                prepared.append((kind, project, source, artifact))
                result['clients'].append({'client': kind, 'build': build,
                    'runtimeProfile': runtime_profile,
                    'runtimeInputsDigest': selection['originalRuntimeInputsDigest']})
            require(len({row['runtimeInputsDigest'] for row in result['clients']}) == 1,
                    'c-http-pair-same-original-runtime-backend')
            node_deadline = min(commands.deadline, time.monotonic() + 300)
            client_deadline = min(node_deadline, time.monotonic() + 240)
            counters = {'calls': 0, 'controlAttempts': 0, 'retainedBytes': 0}
            for row, (kind, project, source, artifact) in zip(result['clients'], prepared):
                stage = 'five-signed-cells-' + kind
                row['node'] = node.run_http(artifact, native_paths, output / ('node-' + kind),
                    deadline=node_deadline, runtime_profile=runtime_profile, client_kind=kind,
                    client_state=counters, client_deadline=client_deadline)
                require(row['node']['status'] == 'passed' and len(row['node']['cases']) == 5
                        and row['node']['runtimeProfile'] == runtime_profile
                        and row['node']['client'] == kind,
                        'c-http-pair-each-current-client-required')
                result['independentClientCount'] += 1
            require(result['independentClientCount'] == 2
                    and [row['client'] for row in result['clients']] == ['libfetch', 'libucl']
                    and result['clients'][0]['node']['native'] == result['clients'][1]['node']['native'],
                    'c-http-pair-both-same-current-native-required')
            for kind, captured_project, captured_source, artifact in prepared:
                require(captured_source == inventory(snapshot(captured_project)),
                        'c-http-pair-all-project-inputs-unchanged')
            result['sharedClientCounters'] = counters
        else:
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
            result['build'] = http_build_evidence(artifact, source, runtime_profile=runtime_profile)
            result['tools'] = tools
            stage = 'five-signed-cells'
            result['node'] = node.run_http(artifact, native_paths, output / 'node',
                                          deadline=commands.deadline, runtime_profile=runtime_profile)
            require(result['node']['status'] == 'passed' and len(result['node']['cases']) == 5,
                    'c-libfetch-five-real-cells-required')
        if expanded:
            result['tools'] = tools
        require(helpers == http_sources(commands, output, capture=False, runtime_profile=runtime_profile)
                and original_source == source_identity(ROOT)
                and source == inventory(snapshot(project))
                and sdk_source == inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
                and ordinary_tuple(receipt, native_paths) == native
                and tools == {name: file_identity(path, 512 * 1024**2) for name, path in installed.items()},
                'c-libfetch-all-original-inputs-unchanged')
        commands.run('libfetch-still-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        require(time.monotonic() < commands.deadline, 'c-libfetch-original-deadline')
        if outside:
            counts = result['completedCommandRoots']
            counts['owner'] = len(commands.records)
            counts['total'] = counts['owner'] + sum(counts['builds']) + sum(counts['nodes'])
        result.update(status='passed', commands=commands.records)
        write_json(output / 'qualified.json', result)
        print(json.dumps({'status': 'passed', 'cells': 2 if outside else 10 if expanded else 5,
                          'independentClientCount': 0 if outside else 2 if expanded else 1, 'full690Qualified': False}))
        return 0
    except BaseException as error:
        result.update(status='failed', stage=stage, reason=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', result)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
