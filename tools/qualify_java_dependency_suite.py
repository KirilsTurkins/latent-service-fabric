#!/usr/bin/env python3
"""Own one actual private/recovery Java dependency qualification attempt."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import tomllib

sys.dont_write_bytecode = True
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_snapshot import digest
from tools.java_capsule_project import create
from tools.java_guest.compiler import Compiler, read_only_dependency_cache, tool_inventory
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_capsules import inputs
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.qualify_java_server_lifecycle_suite import PRODUCTS, native
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh


def source_inputs(commands):
    names = commands.run('tracked-tool-inputs', 'git', 'ls-files', '-z', '--', 'tools').decode('utf-8').split('\0')
    names = [name for name in names if name]
    require(0 < len(names) <= 8192 and len(set(names)) == len(names)
            and all(name.startswith('tools/') and '..' not in Path(name).parts for name in names),
            'java-dependency-suite-tracked-input-bound')
    tools = {name: file_identity(ROOT / name, 16 * 1024 * 1024) for name in names}
    require(sum(row['bytes'] for row in tools.values()) <= 128 * 1024 * 1024,
            'java-dependency-suite-tool-source-byte-bound')
    return {'maintainedJavaInputs': inputs(), 'trackedTools': tools,
            'scope': 'declared native/Java SDK/WIT/helpers plus every tracked tool file; implicit host inputs not attested'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--wasi-sdk', required=True, type=Path)
    parser.add_argument('--mode', required=True, choices=('private', 'recovery'))
    parser.add_argument('--gradle', default='gradle')
    args = parser.parse_args(argv)
    require(args.output.absolute() != ROOT and ROOT not in args.output.absolute().parents,
            'java-dependency-suite-output-must-be-outside-checkout')
    script = ROOT / ('tools/qualify_java_private_dependencies.py' if args.mode == 'private'
                     else 'tools/qualify_java_dependencies.py')
    require(script.is_file(), 'java-dependency-suite-selected-programme-missing')
    output = fresh(args.output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=900)
    commands.environment.update(CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR', str(ROOT / 'target')),
        CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0', CARGO_INCREMENTAL='0',
        PYTHONDONTWRITEBYTECODE='1')
    if 'JAVA_HOME' in os.environ:
        commands.environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    stage = 'source'
    try:
        before = source_inputs(commands)
        write_json(output / 'source-inputs.json', before)
        stage = 'ordinary-default-native-products'
        directory, receipt = native(commands, output, tomllib.loads((ROOT / 'tools/toolchain.toml').read_text()))
        products = {name: directory / name for name in PRODUCTS}
        selected = ordinary_tuple(receipt, products)
        stage = 'normal-pinned-compiler-acquisition'
        project = create(output / 'compiler-project', 'greeting')
        compiler = Compiler(output / 'compiler', args.wasi_sdk, gradle=args.gradle,
            sdk=project / 'vendor/lsf/sdk/java-guest', platform=project / 'vendor/lsf/wit/platform',
            timeout=min(900, commands.deadline - time.monotonic()))
        component, _bindings = compiler.compile(project / 'src', project / 'wit',
            read_json(project / 'capsule-project.json')['world'], output / 'compiler-component')
        compiler.check_unchanged()
        cache = read_only_dependency_cache(compiler.directory / 'gradle-home/caches/modules-2')
        cache_inputs = tool_inventory({'gradle-cache': cache})
        (output / 'compiler-cache-inputs.json').write_bytes(cache_inputs)
        (output / 'compiler-inputs.json').write_bytes(compiler.compiler_inputs)
        write_json(output / 'compiler-acquisition.json', {'status': 'compiled',
            'scope': 'normal pinned greeting compilation acquires and verifies compiler inputs; no admission claim',
            'component': file_identity(component), 'tools': compiler.materials, 'commands': compiler.records})
        stage = args.mode + '-capture'
        attempt = output / args.mode
        common = ('--output', attempt, '--native-directory', directory, '--native-tuple', receipt,
                  '--gradle', args.gradle)
        commands.run(stage, sys.executable, script, '--resolve-only', *common)
        stage = args.mode + '-offline-component-and-signed-node'
        commands.run(stage, sys.executable, script, '--offline', *common,
                     '--wasi-sdk', args.wasi_sdk, '--read-only-cache', cache)
        result = read_json(attempt / ('private-qualification.json' if args.mode == 'private' else 'qualification.json'))
        require(result['status'] == 'passed', 'java-dependency-suite-selected-programme-not-passed')
        stage = 'final-integrity'
        compiler.check_unchanged()
        require(tool_inventory({'gradle-cache': cache}) == cache_inputs,
                'java-dependency-suite-pinned-compiler-cache-mutated')
        require(ordinary_tuple(receipt, products) == selected, 'java-dependency-suite-native-products-mutated')
        after = source_inputs(commands)
        write_json(output / 'source-inputs-after.json', after)
        require(after == before and time.monotonic() < commands.deadline,
                'java-dependency-suite-source-changed-or-deadline')
        write_json(output / 'qualification.json', {'status': 'passed', 'mode': args.mode,
            'scope': 'actual controlled capture, isolated offline component and ordinary enforced signed-node programme',
            'sourceIdentityDigest': digest((output / 'source-inputs.json').read_bytes()),
            'nativeTuple': selected, 'compilerInputs': file_identity(output / 'compiler-inputs.json'),
            'compilerCacheInputs': file_identity(output / 'compiler-cache-inputs.json'),
            'programmeReceipt': file_identity(attempt / ('private-qualification.json' if args.mode == 'private' else 'qualification.json')),
            'commands': commands.records, 'releasePublication': 'not-performed'})
        print(json.dumps({'status': 'passed', 'mode': args.mode, 'receipt': str(output / 'qualification.json')}))
    except BaseException as error:
        write_json(output / 'FAILED.json', {'status': 'failed', 'mode': args.mode, 'stage': stage,
            'reason': str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__,
            'commands': commands.records})
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
