#!/usr/bin/env python3
"""Validate a maintained Angular build with the existing workspace harnesses."""
import argparse
import json
import os
from pathlib import Path
import sys

if __name__ == '__main__' and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process import run_bounded

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ('crates/latent-packaging/tests/angular_build.rs',
     'actual_angular_build_inputs_have_exact_renderer_assets_and_bound_inventory', 120),
    ('crates/latent-policy/src/lib.rs',
     'supply_chain::tests::web::angular_build::actual_observed_angular_package_authenticates_publisher_builder_sbom_and_restart', 180),
    ('crates/latent-wasmtime/tests/angular_build.rs',
     'actual_built_angular_application_renders_fresh_hydration_and_rejects_excess_data', 600),
)


def harnesses(manifest: Path, target: Path) -> dict[str, Path]:
    found = {source: set() for source, _, _ in SUITES}
    finished, size, count = False, 0, 0
    with manifest.open('rb') as stream:
        while line := stream.readline(1024 * 1024 + 1):
            size += len(line)
            count += 1
            if len(line) > 1024 * 1024 or size > 32 * 1024 * 1024 or count > 100000:
                raise RuntimeError('Angular harness manifest limit exceeded')
            if finished:
                raise RuntimeError('unexpected manifest data after build completion')
            entry = json.loads(line)
            if entry.get('reason') == 'build-finished':
                if entry.get('success') is not True:
                    raise RuntimeError('workspace build did not succeed')
                finished = True
            if entry.get('reason') != 'compiler-artifact' or entry.get('profile', {}).get('test') is not True:
                continue
            if not entry.get('executable'):
                continue
            source = Path(entry['target']['src_path']).resolve()
            for expected in found:
                if source != (ROOT / expected).resolve():
                    continue
                executable = Path(entry['executable']).resolve(strict=True)
                if not executable.is_file() or not executable.is_relative_to(target / 'debug/deps'):
                    raise RuntimeError('Angular test harness is outside the current build target')
                found[expected].add(executable)
    if not finished or any(len(paths) != 1 for paths in found.values()):
        raise RuntimeError('required Angular build test harness is missing or ambiguous')
    return {name: paths.pop() for name, paths in found.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-manifest', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--html', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve(strict=True)
    component = build / 'inputs/server/renderer.wasm'
    if not component.is_file() or not 8 <= component.stat().st_size <= 32 * 1024 * 1024:
        raise RuntimeError('required produced renderer is missing or oversized')
    html = args.html.absolute()
    if html.exists() or not html.parent.is_dir():
        raise RuntimeError('browser test requires a fresh output in its owned directory')
    target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve(strict=True)
    selected = harnesses(args.test_manifest, target)
    environment = dict(os.environ, LSF_ANGULAR_BUILD_DIR=str(build), LSF_ANGULAR_PACKAGE_INPUTS=str(build / 'inputs'),
                       LSF_ANGULAR_COMPONENT=str(component), LSF_ANGULAR_HTML=str(html))
    for source, name, deadline in SUITES:
        executable = str(selected[source])
        listing = run_bounded([executable, name, '--exact', '--ignored', '--list', '--format', 'terse'],
                              ROOT, environment, 30, 65536).stdout.decode('utf-8')
        if listing.splitlines() != [name + ': test']:
            raise RuntimeError('required Angular test is absent or filtered out')
        print('Angular gate: ' + name, flush=True)
        result = run_bounded([executable, name, '--exact', '--ignored', '--nocapture'], ROOT, environment, deadline, 2 * 1024 * 1024)
        output = result.stdout.decode('utf-8')
        if '1 passed; 0 failed; 0 ignored' not in output:
            raise RuntimeError('Angular gate did not execute its required test')
        print(output, end='', flush=True)
    if not html.is_file() or not 0 < html.stat().st_size <= 131072:
        raise RuntimeError('actual generic-cell HTML was not produced within its limit')


if __name__ == '__main__':
    main()
