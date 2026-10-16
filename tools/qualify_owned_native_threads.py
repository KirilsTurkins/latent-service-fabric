"""Qualify the explicit signed canonical-child mechanism, without a std claim."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import qualify_rust_thread_routing as routing
from tools.build_process import run_bounded_result
from tools.build_observation import file_identity
from tools.dev_workflow.common import require

ROOT = routing.ROOT
CASE = 'runtime::native_threads::signed_canonical_children_use_distinct_original_tasks_and_physical_stack_retirement'
CORE = 'sdk/rust-standard-runtime/owned-child-fixture/core.wat'
WORLD = 'sdk/rust-standard-runtime/owned-child-fixture/world.wit'
RECIPE = tuple(dict.fromkeys(routing.RECIPE + (CORE, WORLD,
    'tools/qualify_owned_native_threads.py',
    'crates/latent-wasmtime/src/component_threading.rs',
    'crates/latent-wasmtime/src/config/engine.rs', 'crates/latent-wasmtime/src/config/profile.rs',
    'crates/latent-wasmtime/src/backend.rs', 'crates/latent-wasmtime/src/backend/admission.rs',
    'crates/latent-wasmtime/src/backend/preparation/compilation.rs',
    'crates/latent-wasmtime/src/backend/preparation_context.rs',
    'crates/latent-wasmtime/src/aot/worker.rs', 'crates/latent-wasmtime/src/aot/loader.rs',
    'crates/latent-wasmtime/src/aot/profile.rs', 'crates/latent-wasmtime/src/aot/supervisor/input.rs',
    'crates/latent-wasmtime/src/native_stacks.rs', 'crates/latent-wasmtime/src/native_stacks/children.rs',
    'crates/latent-wasmtime/src/host/runtime.rs', 'crates/latent-wasmtime/src/host/native.rs',
    'crates/latent-wasmtime/tests/local_service/runtime/native_threads.rs',
    'crates/latent-wasmtime/tests/local_service/fixture.rs',
    'crates/latent-wasmtime/tests/local_service/packages.rs',
    'crates/latent-wasmtime/tests/guest_sdk/runtime.rs')))


def executable(raw: bytes, target: Path):
    require(len(raw) <= 4 * 1024 * 1024 and len(raw.splitlines()) <= 8192,
            'owned-child-native-inventory-bound')
    selected = []
    finished = False
    target = target.resolve(strict=True)
    for line in raw.splitlines():
        value = json.loads(line)
        require(isinstance(value, dict) and not finished, 'owned-child-native-inventory-terminal')
        if value.get('reason') == 'build-finished':
            require(value.get('success') is True, 'owned-child-native-build-failed')
            finished = True
        if value.get('reason') == 'compiler-artifact' and value.get('target', {}).get('name') == 'local_service':
            require(value['target'].get('kind') == ['test']
                    and value.get('manifest_path') == str(ROOT / 'crates/latent-wasmtime/Cargo.toml')
                    and value.get('profile', {}).get('test') is True,
                    'owned-child-native-target-identity')
            path = value.get('executable')
            require(isinstance(path, str), 'owned-child-native-executable-missing')
            path = Path(path).resolve(strict=True)
            require(path.is_relative_to(target), 'owned-child-native-executable-outside-target')
            selected.append(path)
    require(finished and len(selected) == 1, 'owned-child-native-executable-ambiguous')
    return selected[0]


def prepare(output: Path, transformer: Path, wasm_tools: Path):
    require(not output.exists() and not output.is_symlink(), 'owned-child-output-not-fresh')
    source = {name: routing.identity(ROOT / name) for name in RECIPE}
    tools = {'transformer': routing.identity(transformer), 'wasmTools': routing.identity(wasm_tools)}
    output.mkdir(parents=True, mode=0o700)
    deadline = time.monotonic() + 180
    used = 0
    commands = []
    logs = output / 'source-logs'; logs.mkdir()
    def command(argv):
        nonlocal used
        require(time.monotonic() < deadline and used < 2 * 1024 * 1024, 'owned-child-command-bound')
        result = run_bounded_result([str(v) for v in argv], ROOT, os.environ,
            deadline - time.monotonic(), 2 * 1024 * 1024 - used)
        used += len(result.stdout) + len(result.stderr)
        ordinal = len(commands)
        commands.append({'command': str(argv[1]), 'exitCode': result.returncode})
        for stream in ['stdout', 'stderr']:
            (logs / f'{ordinal:02d}.{stream}.txt').write_bytes(getattr(result, stream))
        require(result.returncode == 0, 'owned-child-source-command-failed')
        return result.stdout
    require(command([wasm_tools, '--version']).strip() == b'wasm-tools 1.254.0', 'owned-child-tool-version')
    wit = output / 'wit'; wit.mkdir()
    (output / 'core.wat').write_bytes((ROOT / CORE).read_bytes())
    (output / 'world.wit').write_bytes((ROOT / WORLD).read_bytes())
    (wit / 'world.wit').write_bytes((ROOT / WORLD).read_bytes())
    for kind, name in [('native', 'wit/platform/native-runtime/package.wit'),
                       ('runtime', 'wit/platform/activation-runtime/package.wit')]:
        path = wit / 'deps' / kind / 'package.wit'; path.parent.mkdir(parents=True)
        path.write_bytes((ROOT / name).read_bytes())
    plain = output / 'plain.wasm'
    command([wasm_tools, 'parse', output / 'core.wat', '-o', plain])
    command([transformer, 'transform-core', plain, routing.identity(plain)['digest'], output / 'derived'])
    for name, core in [('owned', output / 'derived/core.wasm'), ('unwrapped', plain)]:
        embedded = output / (name + '-embedded.wasm')
        command([wasm_tools, 'component', 'embed', wit, core, '-o', embedded])
        command([wasm_tools, 'component', 'new', embedded, '-o', output / (name + '.wasm')])
        command([wasm_tools, 'validate', '--features', 'all', output / (name + '.wasm')])
    command([transformer, 'verify-component', output / 'owned.wasm', output / 'routing.json'])
    printed = command([wasm_tools, 'print', output / 'owned.wasm']).decode('utf-8')
    changed = routing.replace(printed, '      call_indirect (type 0)', '      nop\n      call_indirect (type 0)')
    (output / 'modified-shim.wat').write_text(changed, encoding='utf-8')
    command([wasm_tools, 'parse', output / 'modified-shim.wat', '-o', output / 'modified-shim.wasm'])
    command([wasm_tools, 'validate', '--features', 'all', output / 'modified-shim.wasm'])
    require({name: routing.identity(ROOT / name) for name in RECIPE} == source,
            'owned-child-source-mutated')
    return {'schemaVersion': 'latent.owned-canonical-child-qualification.v1', 'status': 'prepared',
        'source': source, 'tools': tools,
        'components': {name: routing.identity(output / (name + '.wasm'))
                       for name in ['owned', 'unwrapped', 'modified-shim']},
        'sourceLanguage': 'explicit WAT mechanism control',
        'rustOrStdExecuted': False, 'standardRuntimeQualified': False,
        'nativeExecutionPassed': False, 'canonicalThreadProfile': 'explicit-only'}


def run(output: Path, transformer: Path, wasm_tools: Path, inventory: Path, target: Path):
    with inventory.open('rb') as stream:
        native = executable(stream.read(4 * 1024 * 1024 + 1), target)
    native_id = file_identity(native, 'local-service-test', 256 * 1024 * 1024)
    report = prepare(output, transformer, wasm_tools)
    report['nativeTest'] = native_id
    try:
        environment = os.environ.copy()
        environment['LSF_OWNED_CHILD_FIXTURE'] = str(output)
        require(not environment.get('LSF_GUEST_SDK_LANGUAGE'), 'owned-child-unrelated-language-profile')
        result = run_bounded_result([str(native), '--exact', CASE, '--ignored', '--test-threads=1', '--nocapture'],
            ROOT, environment, 180, 2 * 1024 * 1024)
        (output / 'native.stdout.txt').write_bytes(result.stdout)
        (output / 'native.stderr.txt').write_bytes(result.stderr)
        require(result.returncode == 0
                and result.stdout.count(b'test result: ok. 1 passed; 0 failed; 0 ignored;') == 1,
                'owned-child-native-case-not-passed')
        require(file_identity(native, 'local-service-test', 256 * 1024 * 1024) == native_id,
                'owned-child-native-test-mutated')
        require({name: routing.identity(ROOT / name) for name in RECIPE} == report['source'],
                'owned-child-source-mutated')
        require({name: routing.identity(output / (name + '.wasm')) for name in report['components']}
                == report['components'], 'owned-child-component-mutated')
        report['nativeExecutionPassed'] = True
        report['status'] = 'passed'
        return report
    finally:
        if report['status'] != 'passed':
            report['status'] = 'failed'
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['output', 'transformer', 'wasm-tools', 'cargo-inventory', 'native-target']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.transformer.resolve(), args.wasm_tools.resolve(),
                 args.cargo_inventory.resolve(), args.native_target.resolve())
    print(json.dumps({'status': result['status'], 'nativeExecutionPassed': result['nativeExecutionPassed'],
                      'standardRuntimeQualified': False}))


if __name__ == '__main__':
    main()
