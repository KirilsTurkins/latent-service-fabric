#!/usr/bin/env python3
"""Observe the maintained Angular recipe and emit immutable package + SBOM inputs.

Requires provisioned exact tools. Never runs npm application scripts or signs
evidence. Python 3.13's existing process supervisor owns each tool's descendants.
Builds are bounded trusted builder operations, not a hostile-source OS sandbox.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import time

if __name__ == '__main__' and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.angular_build import build
from tools.angular_build.inputs import capture
from tools.angular_build.tools import BuildTools
from tools.build_process import BuildProcessError
from tools.build_process_signals import owned_cancellation
from tools.build_snapshot import SnapshotError, canonical, owned_child, remove_owned_directory
from tools.build_observation import public_repository


def observed_build(*, input_root: Path, config: str, toolchain: Path, cli: Path,
                   target_root: Path, output: Path, cargo_target: Path,
                   repository: str, verify_reproducible=False) -> dict:
    public_repository(repository)
    target_root = target_root.absolute()
    target_root.mkdir(parents=True, exist_ok=True)
    target_root = target_root.resolve(strict=True)
    output = output.absolute()
    owned_child(output, target_root)
    if output.exists():
        raise SnapshotError('Angular output directory must be fresh')
    input_root = input_root.resolve(strict=True)
    if input_root == target_root or target_root in input_root.parents or input_root in target_root.parents:
        raise SnapshotError('Angular build scratch must be separate from application source')
    cargo_target = cargo_target.absolute()
    cargo_target.mkdir(parents=True, exist_ok=True)
    temporary = result_stage = None
    with owned_cancellation() as cancellation:
        try:
            with cancellation.defer():
                temporary = Path(tempfile.mkdtemp(prefix='.angular-build-', dir=target_root))
                result_stage = Path(tempfile.mkdtemp(prefix='.angular-result-', dir=target_root))
            owned_child(temporary, target_root)
            captured = temporary / 'source'
            selected, inventory = capture(input_root, config, captured)
            scratch = temporary / 'temporary'
            scratch.mkdir()
            started = int(time.time())
            tools = BuildTools(toolchain, cli, scratch, cargo_target, cancellation)
            staged = result_stage
            summary, materials = build.assemble(selected, captured, temporary / 'first', staged, tools, inventory)
            if verify_reproducible:
                repeated = temporary / 'repeat-output'
                repeated.mkdir()
                second, _ = build.assemble(selected, captured, temporary / 'second', repeated, tools, inventory)
                if summary['packageDigest'] != second['packageDigest']:
                    raise SnapshotError('Angular byte reproducibility failed; no package was published')
            tools.verify()
            observation = build.observation(selected, tools, summary, materials, inventory, repository,
                                            started, int(time.time()), verify_reproducible)
            (staged / 'observation.json').write_bytes(canonical(observation))
            (staged / 'build-summary.json').write_bytes(canonical(summary))
            cancellation.check()
            with cancellation.defer():
                remove_owned_directory(temporary, target_root)
                temporary = None
            # Tool owners have completed cleanup before a result becomes visible.
            # The caller-selected destination is never overwritten.
            output.parent.mkdir(parents=True, exist_ok=True)
            owned_child(output, target_root)
            with cancellation.defer():
                if output.exists():
                    raise SnapshotError('Angular output appeared during build')
                staged.rename(output)
                result_stage = None
            return summary
        finally:
            if temporary is not None:
                with cancellation.defer():
                    remove_owned_directory(temporary, target_root)
            if result_stage is not None:
                with cancellation.defer():
                    remove_owned_directory(result_stage, target_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', type=Path, required=True)
    parser.add_argument('--config', default='angular-build.json')
    parser.add_argument('--toolchain-root', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--target-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo-target-dir', type=Path, default=Path(os.environ.get('CARGO_TARGET_DIR', build.ROOT / 'target')))
    parser.add_argument('--repository', required=True, help='Public source label; conveys no repository authentication')
    parser.add_argument('--verify-reproducible', action='store_true', help='Require byte equality of two actual builds; fail without publishing output on mismatch')
    args = parser.parse_args()
    try:
        summary = observed_build(input_root=args.input_root, config=args.config, toolchain=args.toolchain_root, cli=args.cli,
                                 target_root=args.target_root, output=args.output, cargo_target=args.cargo_target_dir,
                                 repository=args.repository, verify_reproducible=args.verify_reproducible)
        print(canonical(summary).decode())
    except (SnapshotError, BuildProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
