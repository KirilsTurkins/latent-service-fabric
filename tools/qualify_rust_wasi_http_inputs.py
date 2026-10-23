"""Compile ordinary captured WASI HTTP clients and retain their actual imports.

This is a bounded compiler-input control, not an installed HTTP profile or a
signed compatibility programme. Original normal-builder failures stay failures.
No native host, SDK sysroot, runtime adapter or application transport is built.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_wasi_http_fixture as fixture
from tools import wasmtime_48_0_7_native_products as products
from tools.application_dependencies import LOCK, verify_inputs
from tools.build_observation import build_environment, resolve_tools, file_identity as tool_identity
from tools.guest_emitted_code import Budget, CORE, COMPONENT, Reader, limits, value_type
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import source_identity
from tools.rust_capsule_build import Commands, selected_recipe, build
from tools.rust_capsule_project import ROOT, canonical, digest, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = ('tools/qualify_rust_wasi_http_inputs.py', 'tools/rust_wasi_http_fixture.py',
    'tools/guest_emitted_code.py', 'tools/java_replay_materials.py',
    'tools/wasmtime_48_0_7_native_products.py', 'tools/sdk_native_products_reader.py',
    'tools/install_guest_bindgen.py', 'tools/toolchain.toml')


def core_imports(raw: bytes) -> list[dict]:
    """Read import declarations only, after separate pinned-engine validation.

    Do not infer reachable calls, readiness, resource behavior or lifecycle from
    these names. Unknown or excessive encodings refuse this diagnostic.
    """
    require(type(raw) is bytes and 8 <= len(raw) <= 64*1024**2, 'rust-http-input-wasm-byte-bound')
    budget, result = Budget(), []

    def core(data):
        reader = Reader(data, budget)
        require(bytes(reader.take(8)) == CORE, 'rust-http-input-core-header')
        imported, seen = [], False
        while reader.at < len(reader.data):
            kind, section = reader.byte(), reader.child()
            if kind != 2:
                continue
            require(not seen, 'rust-http-input-duplicate-import-section'); seen = True
            for _ in range(section.count(4096)):
                module, name, sort = section.name(), section.name(), section.byte()
                entry = {'module': module, 'name': name, 'kind': sort}
                if sort == 0:
                    entry['typeIndex'] = section.leb()
                elif sort == 1:
                    value_type(section); limits(section)
                elif sort == 2:
                    limits(section)
                elif sort == 3:
                    value_type(section); require(section.byte() in (0, 1), 'rust-http-input-global-mutability')
                elif sort == 4:
                    require(section.byte() == 0, 'rust-http-input-tag-attribute'); section.leb()
                else:
                    raise ValueError('rust-http-input-unknown-import-kind')
                imported.append(entry)
            section.done()
        return {'coreDigest': digest(bytes(data)), 'coreBytes': len(data), 'imports': imported}

    def visit(data, depth):
        require(depth <= 8 and len(result) < 64, 'rust-http-input-module-bound')
        if bytes(data[:8]) == CORE:
            result.append(core(data)); return
        reader = Reader(data, budget)
        require(bytes(reader.take(8)) == COMPONENT, 'rust-http-input-component-header')
        while reader.at < len(reader.data):
            kind, section = reader.byte(), reader.child()
            require(kind <= 12, 'rust-http-input-component-section-kind')
            if kind in (1, 4):
                visit(section.data, depth+1)

    visit(raw, 0)
    require(bool(result), 'rust-http-input-no-compiled-core')
    return result


def execution_request(denied: Path, application: Path) -> dict:
    failed = read_json(denied / 'BUILD-FAILED.json')
    require(failed['stage'] == 'executable-input-approval'
            and not any(row['stage'] == 'compile' for row in failed['commands'])
            and not (denied / 'BUILD-COMPLETE.json').exists(), 'rust-http-input-unapproved-boundary')
    value = read_json(denied / 'executable-input-approval-request.json', 8*1024**2)
    spec = value['specification']
    retained = [row for row in read_json(application / LOCK, 8*1024**2)['artifacts'] if row['role'] == 'build-tool']
    require(value['formatVersion'] == 1 and value['identity'] == digest(canonical(spec))
            and spec['executableInputs'] == retained and bool(retained)
            and spec['network'] == 'denied' and spec['ambientHome'] == 'absent'
            and spec['credentials'] == 'not-inherited'
            and spec['isolationProfile'] == 'linux-captured-compiler-namespaces-v1',
            'rust-http-input-exact-executable-review')
    return value


def qualify(native_directory: Path, output: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'rust-http-input-linux-python313')
    native_directory = native_directory.resolve(strict=True)
    require(output.is_absolute() and output != ROOT and ROOT not in output.parents
            and output != native_directory and native_directory not in output.parents
            and output not in native_directory.parents, 'rust-http-input-separated-output')
    output = fresh(output)
    before = source_identity(ROOT)
    require(before == git_source_identity(products.SOURCE), 'rust-http-input-original-native-source')
    inherited = products.verify_prepared(native_directory)
    binaries = products.native_products(native_directory)
    for path in binaries.values():
        path.chmod(0o700)
    materials = {name: file_identity(ROOT / name) for name in dict.fromkeys((*selected_recipe(ROOT), *MATERIALS,
        'examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json'))}
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    paths, tools = resolve_tools(tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode()), ROOT, commands.environment)
    record = {'schemaVersion': 'latent.rust.wasi-http-input-observation.v1', 'status': 'incomplete',
        'source': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip(),
        'compiledNative': inherited, 'consumerNativeSource': before, 'materials': materials, 'tools': tools,
        'nativeProductsBuilt': 0, 'engineRebuilt': False, 'runtimeBackendInstalled': False,
        'libraryCodePatched': False, 'applicationTransportInjected': False,
        'signedQualification': False, 'fullTicketQualification': False}
    stage = 'normal-developer-source-capture'
    try:
        app, outside, spec = fixture.prepare(output / 'source', secrets.token_hex(8))
        record['capture'] = fixture.capture(app, outside, spec, paths['cargo'])
        captured = inventory(snapshot(app)); record['capturedSourceDigest'] = digest(captured)
        write_json(output / 'capture.json', record['capture'])
        stage = 'unapproved-executable-refusal'
        denied = output / 'approval-required'
        arguments = (binaries['capsule_contracts'], None, 'https://github.com/KirilsTurkins/latent-service-fabric')
        try:
            build(app, denied, *arguments, offline=True)
        except ValueError:
            approval = execution_request(denied, app)
        else:
            raise ValueError('rust-http-input-unapproved-executable-was-accepted')
        record['executableApproval'] = approval
        # This SDK-owned input control approves exactly the retained public
        # executable closure in its isolated test. Normal authoring never infers
        # approval from capture, a package name, or this diagnostic.
        stage = 'one-isolated-offline-compile'
        built = output / 'build'
        failure = None
        try:
            build(app, built, *arguments, offline=True, executable_approval=approval['identity'])
        except ValueError:
            failure = read_json(built / 'BUILD-FAILED.json')
        require(read_json(built / 'executable-input-approval-request.json', 8*1024**2) == approval,
                'rust-http-input-approved-request-changed')
        require(inventory(snapshot(app)) == captured and verify_inputs(app, 'rust') is not None,
                'rust-http-input-source-or-capture-changed')
        record['normalBuilderFailure'] = failure
        require(failure is None or failure['stage'] in ('component', 'compatibility'),
                'rust-http-input-no-actual-compiled-imports')
        target = built / ('raw-core.wasm' if (built / 'raw-core.wasm').exists() else 'component.wasm')
        require(target.exists(), 'rust-http-input-compiler-output-not-retained')
        stage = 'validate-and-read-actual-compiler-imports'
        commands.run('validate-compiler-output', paths['wasm-tools'], 'validate', target,
            '--features', 'cm-async,cm-async-stackful,cm-more-async-builtins')
        raw = read_file(target, 64*1024**2)
        if raw.startswith(CORE):
            require(failure is not None and failure['stage'] == 'component'
                and read_json(built / 'raw-core-observation.json') == {'formatVersion': 1,
                    'stage': 'component', 'sourceDigest': digest(captured), 'coreDigest': digest(raw),
                    'coreBytes': len(raw), 'state': 'retained-original-compiler-output', 'authority': 'none'},
                'rust-http-input-original-retained-core-binding')
        modules = core_imports(raw)
        require(any(row['module'].startswith('wasi:http/') for module in modules for row in module['imports']),
                'rust-http-input-no-linked-wasi-http-calls')
        record['compiledOutput'] = {'name': target.name, **file_identity(target, 64*1024**2), 'coreModules': modules}
        if raw.startswith(COMPONENT):
            graph = commands.run('original-final-component-wit', paths['wasm-tools'], 'component', 'wit', target, '--json')
            (output / 'component-wit.json').write_bytes(graph)
            record['componentWit'] = file_identity(output / 'component-wit.json')
        record['originalBuildSource'] = file_identity(built / 'source-inputs.json')
        require(read_file(built / 'source-inputs.json') == captured
            and read_json(built / 'cargo-inputs.json')['networkResolution'] is False,
            'rust-http-input-ordinary-offline-source-binding')
        recipe = read_json(built / 'recipe-inputs.json')
        for name, expected in recipe.items():
            data = read_file(ROOT / name)
            require(expected == {'digest': digest(data), 'size': len(data)}, 'rust-http-input-compiler-recipe-drift')
        require(source_identity(ROOT) == before and products.verify_prepared(native_directory) == inherited
            and {name: file_identity(ROOT / name) for name in materials} == materials
            and [tool_identity(path, name) for name, path in sorted(paths.items())] == tools
            and time.monotonic() < commands.deadline, 'rust-http-input-final-input-integrity')
        record.update(status='observed', commands=commands.records,
            scope='actual compiler imports only; default HTTP backend, readiness and retirement remain unimplemented')
        write_json(output / 'observation.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', record)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-products', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps({'status': qualify(args.native_products, args.output)['status'], 'signedQualification': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
