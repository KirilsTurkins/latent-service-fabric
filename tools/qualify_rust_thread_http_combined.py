"""Build the explicit diagnostic host and run one signed combined witness."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory as directory_inventory, source_identity
from tools.qualify_host_codec_native import materials as host_materials
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json
from tools.rust_thread_http_combined_package import prepare
from tools.rust_thread_http_combined_node import run


PRODUCTS = {'latent': 'latent', 'latentd': 'latentd', 'package': 'examples/package',
            'capsule_contracts': 'examples/capsule_contracts', 'capsule_authoring': 'examples/capsule_authoring'}
EXTRA_MATERIALS = ('tools/rust_thread_http_combined_package.py', 'tools/rust_thread_http_combined_node.py',
    'tools/rust_combined_http_materials.py', 'tools/qualify_rust_thread_http_combined.py',
    'tools/rust_thread_http_sibling_gate.py', 'tools/rust_thread_http_sibling_node.py',
    'tools/rust_combined_diagnostic_envelope.py', 'tools/rust_original_delta.py')


# Only this diagnostic build opts into optimized source-proof code. Debug
# assertions and overflow checks remain enabled by the owner environment.
VERIFIER_OPTIMIZATION = 'profile.dev.package.latent-component-threading.opt-level=3'


def build_native(commands):
    commands.run('build-current-feature-selected-host', 'cargo',
        '--config', ROOT / '.cargo/managed-guest.toml', '--config', VERIFIER_OPTIMIZATION,
        'build', '--locked', '-p', 'latent', '-p', 'latentd', '--bins',
        '-p', 'latent-packaging', '--example', 'package', '--example', 'capsule_contracts',
        '-p', 'latent-policy', '--example', 'capsule_authoring', '--features',
        'latentd/development-rust-http-combined,latent-packaging/development-rust-http-combined')


def qualify(compiler: Path, output: Path, revision: str) -> dict:
    require(sys.platform == 'linux' and re.fullmatch('[0-9a-f]{40}', revision) is not None,
            'rust-combined-linux-exact-source-required')
    output = fresh(output)
    source, common = source_identity(ROOT), host_materials(ROOT)
    extras = {name: file_identity(ROOT / name, 4 * 1024 * 1024) for name in EXTRA_MATERIALS}
    record = {'schemaVersion': 'latent.rust.combined-http.programme.v1', 'status': 'incomplete',
        'sourceRevision': revision, 'nativeSource': source, 'hostMaterials': common, 'extraMaterials': extras,
        'normalBuilderQualified': False, 'full689Qualified': False, 'full743Qualified': False,
        'physicalVerificationWorkBoundQualified': False}
    environment = build_environment(output)
    target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve()
    environment.update(CARGO_TARGET_DIR=str(target), RUSTUP_TOOLCHAIN='1.97.1',
        CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true')
    commands = Commands(ROOT, fresh(output / 'commands'), environment, deadline_seconds=3600, command_seconds=1800)
    stage = 'current-source-and-compiler'
    try:
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip() == revision,
                'rust-combined-host-checkout-revision')
        version = commands.run('rust-version', 'rustc', '--version').decode().strip()
        require(version.startswith('rustc 1.97.1 ('), 'rust-combined-pinned-host-compiler')
        stage = 'build-current-feature-selected-host'
        build_native(commands)
        native = {name: target / 'debug' / relative for name, relative in PRODUCTS.items()}
        identities = {name: file_identity(path, 512 * 1024 * 1024) for name, path in native.items()}
        require(source == source_identity(ROOT) and common == host_materials(ROOT)
                and extras == {name: file_identity(ROOT / name, 4 * 1024 * 1024) for name in EXTRA_MATERIALS},
                'rust-combined-host-build-source-unchanged')
        record.update(compiler=version, nativeProducts=identities,
            sourceVerifierOptimization=3, hostDebugAssertions=True, hostOverflowChecks=True,
            nativeBuildFeature='latentd/development-rust-http-combined,latent-packaging/development-rust-http-combined')
        write_json(output / 'native-origin.json', record)
        stage = 'assemble-explicit-retained-compiler-projection'
        projected = prepare(compiler, native, output / 'package', commands)
        record['compilerProjection'] = projected
        stage = 'actual-signed-combined-sibling-witness'
        witness = run(output / 'package', native, output / 'node')
        require(witness['status'] == 'passed' and witness['actualSignedSiblingProgress'] is True,
                'rust-combined-signed-witness-required')
        require(source == source_identity(ROOT) and common == host_materials(ROOT)
                and extras == {name: file_identity(ROOT / name, 4 * 1024 * 1024) for name in EXTRA_MATERIALS}
                and identities == {name: file_identity(path, 512 * 1024 * 1024) for name, path in native.items()},
                'rust-combined-final-host-source-and-products')
        record.update(status='passed', signedWitness=witness, commands=commands.records,
                      actualSignedSiblingProgress=True)
        # Refuse a success receipt if the bounded public evidence will not fit.
        final = json.dumps(record, indent=2, ensure_ascii=False).encode() + b'\n'
        require(len(final) < 128 * 1024 * 1024, 'rust-combined-receipt-byte-bound')
        directory_inventory(output, maximum_files=255, maximum_bytes=128 * 1024 * 1024 - len(final))
        with (output / 'witness.json').open('xb') as destination:
            destination.write(final)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__,
                      qualification=False, commands=commands.records)
        try:
            write_json(output / 'FAILED.json', record)
        except BaseException:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler-materials', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.compiler_materials, args.output, args.source_commit)['status']}))
