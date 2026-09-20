#!/usr/bin/env python3
"""Owned execution of explicit Cargo artifacts and inventory-registered cases.

This does not run Cargo or compile anything. It composes #427's suite catalogue
with the existing Cargo artifact consumer, rather than finding cached binaries.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

try:
    from . import ci_rust_artifacts as artifacts
    from .test_run import ProcessFailure, TestRun, require
except ImportError:
    import ci_rust_artifacts as artifacts
    from test_run import ProcessFailure, TestRun, require


def wasm(run: TestRun, role: str, path: Path) -> Path:
    run.artifact(role, path)
    with path.open('rb') as source:
        header = source.read(8)
    require(len(header) == 8 and header[:4] == b'\0asm', 'invalid-fixture', 'invalid-wasm-fixture')
    return path.resolve(strict=True)


def execute(run: TestRun, row: dict, manifest: Path, environment: dict[str, str], *,
            selected: list[str], timeout: float = 600, binary: Path | None = None,
            fault: str | None = None) -> None:
    """Validate the exact ignored set, then execute each registered case once.

    An explicit case list prevents a broad filter silently gaining/losing tests.
    All listing/execution, library probes and retirement share the run watchdog.
    """
    expected = row['expectedIgnored']
    require(row['mode'] == 'libtest' and selected and len(selected) == len(set(selected))
            and set(selected) <= set(expected), 'invalid-fixture', 'unregistered-or-empty-case-selection')
    target = Path(environment.get('CARGO_TARGET_DIR', run.repo / 'target'))
    if not target.is_absolute():
        target = run.repo / target
    target = target.resolve(strict=True)
    suite = artifacts.Suite(row['manifest'], row['target'], row['source'], '',
                            frozenset(expected), False, row['kind'])
    run.mark('prepared-artifacts')
    run.artifact('test-manifest', manifest)
    try:
        artifact = artifacts.read_inventory(manifest, run.repo, suite, target=target)
    except (artifacts.ArtifactError, OSError, ValueError, TypeError) as error:
        raise ProcessFailure('invalid-fixture', 'prepared-cargo-artifact-invalid') from error
    require(binary is None or binary.resolve(strict=True) == artifact.executable,
            'invalid-fixture', 'explicit-binary-does-not-match-cargo-inventory')
    run.artifact(row['id'], artifact.executable, 1024 * 1024 * 1024)
    identity = artifact.executable.stat()

    def command(args, **kwargs):
        result = run.command(args, **kwargs)
        return result.returncode, result.output

    try:
        runtime = artifacts.cargo_environment(run.repo, artifact, environment, execute=command, target=target)
    except (artifacts.ArtifactError, OSError, ValueError):
        raise ProcessFailure('unavailable-environment', 'prepared-rust-runtime-unavailable') from None
    runtime.update(TMPDIR=str(run.root), TMP=str(run.root), TEMP=str(run.root))
    run.mark('discovery')
    listed = run.command([str(artifact.executable), '--ignored', '--list'], cwd=artifact.package,
                         env=runtime, timeout=30, maximum=artifacts.MAX_LIST_BYTES)
    try:
        artifacts.validate_listing(listed.output, suite)
    except (artifacts.ArtifactError, UnicodeError):
        raise ProcessFailure('invalid-fixture', 'prepared-ignored-case-set-changed') from None
    run.reproduction.setdefault('cases', []).extend(selected)
    run.reproduction['recipe'] = row['recipe']
    if fault == 'after-discovery':
        raise ProcessFailure('assertion-failure', 'injected-after-discovery')
    for name in selected:
        current = artifact.executable.stat()
        require((identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns, identity.st_ctime_ns)
                == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns),
                'invalid-fixture', 'prepared-executable-changed')
        run.mark('execution')
        result = run.command([str(artifact.executable), name, '--exact', '--ignored',
                              '--nocapture', '--test-threads=1'], cwd=artifact.package, env=runtime,
                             timeout=timeout, maximum=artifacts.MAX_OUTPUT_BYTES)
        summaries = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;',
                               result.output, re.MULTILINE)
        require(summaries == [(b'1', b'0', b'0')], 'assertion-failure', 'selected-test-result-mismatch')
