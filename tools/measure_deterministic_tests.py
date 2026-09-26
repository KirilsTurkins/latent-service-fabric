#!/usr/bin/env python3
"""Measure prebuilt deterministic suites; every repetition must pass, never retry.

Use --baseline with a clean checkout of the pre-migration revision to retain
before/after counts and execution times on the same host. Compilation is excluded.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import time

SUITES = (
    ("admission.policy-deadline", "latent-admission", "admission_resamples_time_after_policy_lookup_instead_of_granting_expired_work", 1, 1),
    ("scheduler.fixed-pool-races", "latent-scheduler", "fixed_pool::tests::races::", 3, 7),
)


def command(args: list[str], cwd: Path, timeout: int = 600) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {args!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def test_count(output: str, expected: int) -> int:
    match = re.search(r"test result: ok\. (\d+) passed; 0 failed;", output)
    if not match or int(match[1]) != expected or expected <= 0:
        raise ValueError(f"test count/result mismatch; expected {expected}\n{output}")
    return int(match[1])


def executable(repo: Path, package: str) -> str:
    output = command(["cargo", "test", "-p", package, "--lib", "--locked",
                      "--no-run", "--message-format=json"], repo)
    artifacts = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    binaries = [item["executable"] for item in artifacts
                if item.get("reason") == "compiler-artifact" and item.get("executable")
                and item.get("target", {}).get("name") == package.replace("-", "_")
                and item.get("profile", {}).get("test")]
    if len(binaries) != 1:
        raise ValueError(f"expected one unit-test binary for {package}: {binaries}")
    return binaries[0]


def measure(repo: Path, phase: str, repeats: int, report: dict) -> None:
    revision = command(["git", "rev-parse", "HEAD"], repo).strip()
    dirty = bool(command(["git", "status", "--porcelain", "--untracked-files=no"], repo).strip())
    for identity, package, selector, before_count, after_count in SUITES:
        binary = executable(repo, package)
        expected = before_count if phase == "before" else after_count
        # The admission selector intentionally matches both the old live_ prefix
        # and the migrated name. Listing and executed counts make empty matches fail.
        listing = command([binary, selector, "--list"], repo, 120)
        names = sorted(line.removesuffix(": test") for line in listing.splitlines() if line.endswith(": test"))
        if len(names) != expected:
            raise ValueError(f"{identity}: expected {expected} listed tests, got {names}")
        for threads in (1, 4):
            item = dict(phase=phase, revision=revision, dirty=dirty, suite=identity,
                        package=package, selector=selector, tests=names, count=expected,
                        test_threads=threads, execution_seconds=[])
            report["measurements"].append(item)
            for _ in range(repeats):
                start = time.perf_counter()
                output = command([binary, selector, f"--test-threads={threads}"], repo, 120)
                elapsed = time.perf_counter() - start
                test_count(output, expected)
                item["execution_seconds"].append(elapsed)
            item["median_seconds"] = statistics.median(item["execution_seconds"])
            print(json.dumps(item), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("target/deterministic-tests.json"))
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("--repeats must be between 1 and 100")
    report = dict(schema="latent.deterministic-tests.v1", passed=False, seed=433,
                  platform=platform.platform(), rustc=command(["rustc", "--version"], args.repository).strip(),
                  cargo_target_dir=os.environ.get("CARGO_TARGET_DIR"),
                  timing="prebuilt test process wall time, including process startup; compilation excluded",
                  repeats=args.repeats, measurements=[])
    try:
        if args.baseline:
            measure(args.baseline.resolve(), "before", args.repeats, report)
        measure(args.repository.resolve(), "after", args.repeats, report)
        report["passed"] = True
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.output)


if __name__ == "__main__":
    main()
