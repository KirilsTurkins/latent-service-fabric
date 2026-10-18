#!/usr/bin/env python3
"""Acquire pinned infrastructure std sources, then qualify both ordinary clocks.

The resolver downloads one fixed public compiler input. Each delegated compiler
stage is locked and offline. The actual signed test fixture remains distinct
from production publisher/builder authorization and installed target selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_rust_standard_clock as clock
from tools.build_observation import file_identity
from tools.dev_workflow.common import require
from tools.rust_capsule_project import checked_path, decode_json, fresh, read_file, write_json

ROOT = clock.ROOT
URL = 'https://static.rust-lang.org/dist/rust-src-1.97.1.tar.xz'
MAX_SOURCE = 32 * 1024 * 1024


def source_archive(destination: Path):
    deadline = time.monotonic() + 90
    raw = bytearray()
    # No application-selected endpoint, credentials or registry configuration.
    with urllib.request.urlopen(URL, timeout=30) as response:
        while block := response.read(65536):
            raw.extend(block)
            require(len(raw) <= MAX_SOURCE and time.monotonic() < deadline,
                    'rust-std-clock-source-download-bound')
    require(hashlib.sha256(raw).hexdigest() == clock.std.clock.SOURCE_ARCHIVE_SHA256,
            'rust-std-clock-source-download-identity')
    with destination.open('xb') as stream:
        stream.write(raw)


def test_executable(raw: bytes, target: Path):
    """Select only this successful Cargo build's exact integration harness."""
    require(len(raw) <= 4 * 1024 * 1024, 'rust-std-clock-native-inventory-bound')
    target = checked_path(target)
    selected = []
    finished = False
    rows = raw.splitlines()
    require(len(rows) <= 8192, 'rust-std-clock-native-inventory-count')
    for line in rows:
        value = decode_json(line)
        require(isinstance(value, dict) and not finished, 'rust-std-clock-native-inventory-terminal')
        if value.get('reason') == 'build-finished':
            require(value.get('success') is True, 'rust-std-clock-native-build-failed')
            finished = True
        if value.get('reason') != 'compiler-artifact':
            continue
        if value.get('target', {}).get('name') != 'clock_admission':
            continue
        require(value['target'].get('kind') == ['test']
                and value.get('manifest_path') == str(ROOT / 'crates/latent-wasmtime/Cargo.toml')
                and value.get('profile', {}).get('test') is True,
                'rust-std-clock-native-target-identity')
        path = value.get('executable')
        require(isinstance(path, str), 'rust-std-clock-native-executable-missing')
        path = checked_path(Path(path))
        require(path.is_relative_to(target), 'rust-std-clock-native-executable-outside-target')
        selected.append(path)
    require(finished and len(selected) == 1, 'rust-std-clock-native-executable-ambiguous')
    return selected[0]


def run(output: Path, inventory: Path, target: Path, rust_bin: Path, wasm_tools: Path):
    native = test_executable(read_file(checked_path(inventory), 4 * 1024 * 1024), target)
    native_identity = file_identity(native, 'clock-admission-test')
    output = fresh(output)
    summary = {'schemaVersion': 'latent.rust.standard-clocks-gate.v1', 'status': 'in-progress',
               'standardThreadApiQualified': False, 'defaultExecutorsQualified': False,
               'installedCompilerChanged': False, 'automaticBuilderSelection': False,
               'productionPublisherBuilderTrustQualified': False, 'clocks': {}}
    try:
        archive = output / 'rust-src-1.97.1.tar.xz'
        source_archive(archive)
        summary['source'] = file_identity(archive, 'rust-src-1.97.1.tar.xz')
        for kind in ('wall', 'monotonic'):
            result = clock.run(archive, output / kind, rust_bin, wasm_tools,
                               native_test=native, native_test_digest=native_identity['digest'],
                               clock_kind=kind)
            require(result['status'] == 'passed', 'rust-std-clock-native-case-not-passed')
            summary['clocks'][kind] = {'status': result['status'],
                'componentDigest': result['component']['componentDigest'],
                'sysrootIdentity': result['component']['sysrootIdentity'],
                'nativeFixture': result['nativeFixture']}
        require(file_identity(native, 'clock-admission-test') == native_identity,
                'rust-std-clock-native-test-mutated')
        require(file_identity(archive, 'rust-src-1.97.1.tar.xz') == summary['source'],
                'rust-std-clock-source-archive-mutated')
        summary['status'] = 'passed'
        write_json(output / 'report.json', summary)
        return summary
    except Exception:
        summary['status'] = 'failed'
        write_json(output / 'report.json', summary)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo-inventory', type=Path, required=True)
    parser.add_argument('--native-target', type=Path, required=True)
    parser.add_argument('--rust-bin', type=Path, required=True)
    parser.add_argument('--wasm-tools', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.output, args.cargo_inventory, args.native_target,
                     args.rust_bin, args.wasm_tools)
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f'Rust standard clock gate failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
