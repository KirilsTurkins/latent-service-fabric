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
from tools.c_standard_facilities_probe import prepare
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.qualify_java_server_lifecycle_suite import native as build_native
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, read_json, write_json

HELPERS = ('tools/c_standard_facilities_probe.py', 'tools/qualify_c_standard_facilities.py',
           'tools/run_rust_capsule_workflow.py', 'tools/rust_capsule_node.py',
           'tools/guest_runtime_profiles.py', 'tools/guest_runtime_grants.py',
           'tools/qualify_java_server_lifecycle.py', 'tools/qualify_java_server_lifecycle_suite.py')
PUBLIC_FIELDS = ('schemaVersion', 'status', 'scope', 'invocations', 'samples', 'providerIdle',
                 'cStandardGrantSteps', 'limits', 'nodeShutdown', 'peerShutdown', 'cliCalls', 'reason', 'peerFailure')


def identity():
    status = subprocess.run(['git', '-c', 'safe.directory=' + str(ROOT), 'status', '--porcelain',
                             '--untracked-files=normal'], cwd=ROOT, capture_output=True, check=True, timeout=15)
    require(not status.stdout, 'c-standard-qualification-requires-clean-recorded-source')
    revision = subprocess.run(['git', '-c', 'safe.directory=' + str(ROOT), 'rev-parse', 'HEAD', 'HEAD^{tree}'],
                              cwd=ROOT, capture_output=True, check=True, timeout=15).stdout.decode().splitlines()
    return {'head': revision[0], 'tree': revision[1], 'helpers': {
        name: file_identity(ROOT / name, 1048576) for name in sorted(set((*c_capsule_build.RECIPE, *HELPERS)))}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('zig', 'wit-bindgen', 'wasm-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--native-directory', type=Path)
    parser.add_argument('--native-tuple', type=Path)
    parser.add_argument('--build-native', action='store_true')
    args = parser.parse_args(argv)
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
                result['capturedStandardLibrary'] = prepare(project)
            build = c_capsule_build.build(project, output / 'builds' / template,
                owned['capsule_contracts'], owned['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', installed=installed)
            result['builds'][template] = read_json(build / 'BUILD-COMPLETE.json')
            builds.append(build)
        stage = 'sign'
        commands.run('demo-sign', owned['capsule_authoring'], 'demo-sign', output / 'releases', *builds)
        stage = 'node'
        observed = run(owned['latent'], owned['latentd'], output / 'releases', output / 'node',
                       language='c', c_standard_facilities=True)
        public = {name: observed[name] for name in PUBLIC_FIELDS if name in observed}
        write_json(output / 'node/public-workflow.json', public)
        require(observed['status'] == 'passed' and len(observed['cStandardGrantSteps']) == 3,
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


if __name__ == '__main__':
    raise SystemExit(main())
