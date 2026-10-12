#!/usr/bin/env python3
"""Prepare ordinary std clock input and run an explicitly authenticated native test.

This bounded infrastructure qualification owns neither production builder trust
nor release publishing. The native case uses its isolated cryptographic fixture;
clock execution does not qualify ordinary threads, executors or HTTP clients.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_standard_sysroot_build as std
from tools.build_observation import build_environment, file_identity
from tools.dev_workflow.common import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import checked_path, digest, fresh, inventory, read_file, write_json

ROOT = std.ROOT
CASE = 'ordinary_std_systemtime_runs_on_signed_current_grants_and_fresh_stores'
SOURCE = b'''wit_bindgen::generate!({path: "wit", world: "service", generate_all});
struct Guest;
impl exports::tests::broker::api::Guest for Guest {
    fn read() -> u64 {
        let _first = std::time::SystemTime::now();
        let second = std::time::SystemTime::now();
        second.duration_since(std::time::UNIX_EPOCH).unwrap().as_millis().try_into().unwrap()
    }
}
export!(Guest);
'''
WIT = b'''package tests:broker@0.1.0;
interface api { read: func() -> u64; }
world service { import latent:clock/wall@0.1.0; export api; }
'''
MANIFEST = b'''[package]
name = "ordinary-std-clock"
version = "0.1.0"
edition = "2024"
[workspace]
[lib]
crate-type = ["cdylib"]
[dependencies]
wit-bindgen = "=0.62.0"
[profile.release]
panic = "abort"
opt-level = "s"
lto = true
codegen-units = 1
'''
RECIPE = ('tools/qualify_rust_standard_clock.py', *std.RECIPE,
          'crates/latent-wasmtime/tests/clock_admission.rs',
          'crates/latent-wasmtime/tests/clock_admission/signed.rs')


def run(archive: Path, output: Path, rust_bin: Path, wasm_tools: Path, *,
        native_test: Path | None = None, native_test_digest: str | None = None):
    require((native_test is None) == (native_test_digest is None), 'rust-std-clock-explicit-test-identity-required')
    rust_bin, wasm_tools = checked_path(rust_bin), checked_path(wasm_tools)
    tools = {name: file_identity(checked_path(rust_bin / name), name) for name in ('cargo', 'rustc')}
    tools['wasm-tools'] = file_identity(wasm_tools, 'wasm-tools')
    inputs = {n: read_file(ROOT / n) for n in dict.fromkeys(RECIPE)}
    if native_test is not None:
        native_test = checked_path(native_test)
        require(file_identity(native_test, 'clock-admission-test')['digest'] == native_test_digest,
                'rust-std-clock-native-test-preimage')
    output = fresh(output)
    started = time.monotonic()
    result = {'schemaVersion': 'latent.rust.std-clock-qualification.v1', 'status': 'in-progress',
              'scope': 'ordinary-SystemTime-owned-sysroot-and-current-cryptographic-test-fixture',
              'productionBuilderTrustQualified': False, 'standardThreadsQualified': False,
              'defaultExecutorsQualified': False, 'httpClientsQualified': False, 'releasePublication': False}
    try:
        built = std.build(archive, output / 'std', rust_bin)
        project = output / 'project'
        files = {'Cargo.toml': MANIFEST, 'src/lib.rs': SOURCE, 'wit/world.wit': WIT,
                 'wit/deps/clock/package.wit': inputs['wit/platform/clock/package.wit']}
        for name, raw in files.items():
            path = project / name; path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream: stream.write(raw)
        environment = build_environment(output)
        environment.update(CARGO_NET_OFFLINE='true', RUSTUP_AUTO_INSTALL='0',
            CARGO_TARGET_DIR=str(output / 'guest-target'), CARGO_INCREMENTAL='0',
            RUSTC=str(rust_bin / 'rustc'))
        (output / 'guest-build').mkdir()
        commands = Commands(project, output / 'guest-build', environment, deadline_seconds=300, command_seconds=180)
        version = commands.run('component-tool-version', wasm_tools, '--version').decode().strip()
        require(version.split()[:2] == ['wasm-tools', '1.254.0'], 'rust-std-clock-component-tool-pin')
        # Capture the fixture's ordinary locked graph separately before compile.
        # This never enables network resolution in the compiler stage.
        commands.run('capture-offline-fixture-lock', rust_bin / 'cargo', 'generate-lockfile', '--offline')
        files['Cargo.lock'] = read_file(project / 'Cargo.lock')
        environment['CARGO_TARGET_WASM32_UNKNOWN_UNKNOWN_RUSTFLAGS'] = '--sysroot=' + str(output / 'std/sysroot')
        commands.run('compile', rust_bin / 'cargo', 'build', '--locked', '--offline', '--release',
                     '--target', std.clock.TARGET)
        core = output / 'guest-target/wasm32-unknown-unknown/release/ordinary_std_clock.wasm'
        component = output / 'component.wasm'
        commands.run('component', wasm_tools, 'component', 'new', core, '-o', component)
        commands.run('validate', wasm_tools, 'validate', component)
        surface = commands.run('surface', wasm_tools, 'component', 'wit', component).decode()
        require('import latent:clock/wall@0.1.0;' in surface and 'export tests:broker/api@0.1.0;' in surface,
                'rust-std-clock-actual-component-surface')
        require({n: read_file(project / n) for n in files} == files, 'rust-std-clock-project-mutated')
        require({n: read_file(ROOT / n) for n in inputs} == inputs, 'rust-std-clock-recipe-mutated')
        for name, record in tools.items():
            path = wasm_tools if name == 'wasm-tools' else rust_bin / name
            require(file_identity(path, name) == record, 'rust-std-clock-tool-mutated')
        raw = read_file(component, 4 * 1024 * 1024)
        marker = {'profile': std.PROFILE, 'compiler': std.clock.RUST, 'target': std.clock.TARGET,
            'sourceInputsDigest': digest(inventory(files)), 'recipeDigest': digest(inventory(inputs)),
            'sysrootIdentity': built['identity'], 'sysrootLibraries': built['libraries'],
            'tools': tools, 'componentDigest': digest(raw), 'componentBytes': len(raw),
            'applicationClockSdkCalled': False, 'defaultBuilderSelection': False,
            'actualSurface': surface, 'commands': commands.records}
        write_json(output / 'clock-guest.json', marker)
        result['component'] = marker
        result['nativeFixture'] = 'not-run'
        if native_test is not None:
            # Receipt directories can be a mounted archive filesystem. Native
            # trust/policy owners require the ordinary Linux temporary root,
            # independently of where the public diagnostics are retained.
            with tempfile.TemporaryDirectory(prefix='lsf-std-clock-runtime-') as directory:
                test_environment = build_environment(Path(directory))
                test_environment['LSF_RUST_STD_CLOCK_GUEST'] = str(output)
                (output / 'native-test').mkdir()
                test = Commands(output, output / 'native-test', test_environment,
                                deadline_seconds=120, command_seconds=60)
                listing = test.run('case-list', native_test, '--list').decode()
                require(CASE + ': test' in listing, 'rust-std-clock-native-case-missing')
                test.run('signed-clock-case', native_test, '--exact', CASE, '--ignored', '--test-threads=1')
            require(file_identity(native_test, 'clock-admission-test')['digest'] == native_test_digest,
                    'rust-std-clock-native-test-mutated')
            result['nativeFixture'] = {'status': 'passed', 'case': CASE,
                                       'testDigest': native_test_digest, 'commands': test.records}
        require(time.monotonic() - started < 900, 'rust-std-clock-overall-deadline')
        result['status'] = 'passed' if native_test is not None else 'component-prepared'
        write_json(output / 'qualification.json', result)
        return result
    except Exception:
        result['status'] = 'failed'
        write_json(output / 'qualification.json', result)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rust-bin', type=Path, required=True)
    parser.add_argument('--wasm-tools', type=Path, required=True)
    parser.add_argument('--clock-admission-test', type=Path)
    parser.add_argument('--clock-admission-test-sha256')
    args = parser.parse_args(argv)
    try:
        result = run(args.source_archive, args.output, args.rust_bin, args.wasm_tools,
                     native_test=args.clock_admission_test, native_test_digest=args.clock_admission_test_sha256)
        print(json.dumps({'status': result['status'], 'scope': result['scope'],
                          'nativeFixture': result['nativeFixture']}))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f'Rust std clock qualification failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
