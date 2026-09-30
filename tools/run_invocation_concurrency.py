#!/usr/bin/env python3
"""Run issue #695's opt-in actual-component experiment with bounded evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process import BuildProcessError, run_bounded_result

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research/invocation-concurrency"
CASE_NAMES = [
    "sequential-host-waits", "cooperative-host-fanout", "cancel-then-drain",
    "denied-before-dispatch", "task-limit-before-dispatch", "empty-scope",
    "cooperative-rendezvous", "std-thread-spawn", "inline-start-deadlock",
    "epoch-deadline-drain", "partial-error-still-drains", "fresh-store-after-traps",
]
MAX_LOG = 8 * 1024 * 1024
SCHEMA = "latent.research.invocation-concurrency.v1"


def verify_measurements(value: dict) -> None:
    """A successful process with missing/changed cases is not successful evidence."""
    if (value.get("schemaVersion") != SCHEMA or value.get("status") != "passed"
            or value.get("productionQualified") is not False):
        raise ValueError("invalid-runtime-receipt")
    rows = value.get("measurements", [])
    if [row.get("name") for row in rows] != CASE_NAMES:
        raise ValueError("missing-or-duplicate-runtime-case")
    for row in rows:
        if (row.get("hostOperationsAfterStoreDrop") != 0
                or row.get("storeDataDropped") is not True
                or not 0 < row.get("linearMemoryPeakBytes", 0) <= 16 * 1024 * 1024):
            raise ValueError("unretired-or-unmeasured-runtime-owner")
    if (rows[0].get("peakHostOperations") != 1
            or rows[1].get("peakHostOperations") != 8
            or rows[2].get("cancelAcceptedBeforeRetirementWitness") is not True
            or rows[3].get("hostOperationsStarted") != 0
            or rows[4].get("hostOperationsStarted") != 0
            or rows[7].get("outcome") != "unsupported-thread-trap"
            or rows[8].get("outcome") != "out-of-fuel"
            or rows[9].get("outcome") != "epoch-deadline-trap"
            or rows[10].get("expected") != (1 << 32) + 35):
        raise ValueError("runtime-behavior-mismatch")
    pairs = value.get("cpuPairedSamples", [])
    if len(pairs) != 7 or any(
        [row.get("name") for row in pair] != ["cpu-sequential", "cpu-cooperative"]
        or any(row.get("outcome") != "returned" or row.get("expected") != 9216 for row in pair)
        for pair in pairs
    ):
        raise ValueError("incomplete-equal-work-comparison")


def sources() -> dict[str, str]:
    paths = [ROOT / name for name in (
        "Cargo.toml", "Cargo.lock", "rust-toolchain.toml",
        "tools/toolchain-smoke/Cargo.toml", "tools/run_invocation_concurrency.py",
        "tools/build_process.py", "tools/build_process_linux.py", "tools/build_process_signals.py",
    )]
    paths += [path for path in RESEARCH.rglob("*")
              if path.is_file() and path.suffix in {".rs", ".wit", ".py"}]
    result = {}
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError("symlink-source")
        result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def run(output: Path) -> dict:
    if not output.is_absolute() or output.resolve().is_relative_to(ROOT):
        raise ValueError("output-must-be-outside-checkout")
    output = output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    (output / "logs").mkdir()
    receipt = {"schemaVersion": SCHEMA, "status": "failed", "productionQualified": False,
               "stage": "source-capture", "commands": []}
    env = dict(os.environ)
    env.update(CARGO_TARGET_DIR=str(output / "target"), CARGO_BUILD_JOBS="2", CARGO_INCREMENTAL="0")

    def command(name: str, argv: list[str], seconds: int = 60) -> bytes:
        receipt["stage"] = name
        try:
            result = run_bounded_result(argv, ROOT, env, seconds, MAX_LOG)
        except BuildProcessError as error:
            receipt["commands"].append({"name": name, "status": error.reason})
            raise
        (output / "logs" / (name + ".stdout")).write_bytes(result.stdout)
        (output / "logs" / (name + ".stderr")).write_bytes(result.stderr)
        receipt["commands"].append({"name": name, "exitCode": result.returncode})
        if result.returncode:
            raise ValueError("command-exit:" + name)
        return result.stdout

    try:
        receipt["sources"] = sources()
        receipt["testedCommit"] = command("commit", ["git", "rev-parse", "HEAD"]).decode().strip()
        receipt["workingTreeModified"] = bool(command("status", ["git", "status", "--porcelain=v1"]))
        receipt["tools"] = {name: command(name + "-version", [name, "--version"]).decode().strip()
                            for name in ("cargo", "rustc", "wasm-tools")}
        if (not receipt["tools"]["rustc"].startswith("rustc 1.97.1 ")
                or receipt["tools"]["wasm-tools"].split()[:2] != ["wasm-tools", "1.254.0"]):
            raise ValueError("unreviewed-toolchain")
        # Format diagnostic copies, never tracked sources. Retain these even if a
        # later compile fails so reviewers can apply a real rustfmt diff.
        formatted = output / "formatted"
        formatted.mkdir()
        for path in RESEARCH.glob("*.rs"):
            shutil.copyfile(path, formatted / path.name)
        command("format-diagnostics", ["rustfmt", "--edition", "2021",
                *map(str, sorted(formatted.glob("*.rs")))])
        command("scope-tests-build", ["rustc", "--edition", "2021", "--test",
                str(RESEARCH / "scope.rs"), "-o", str(output / "scope-tests")])
        command("scope-tests", [str(output / "scope-tests"), "--test-threads=1"])
        command("guest-build", ["cargo", "build", "--locked", "--release", "-p", "latent-toolchain-smoke",
                "--example", "research-concurrency-guest", "--target", "wasm32-unknown-unknown"], 1200)
        core = output / "target/wasm32-unknown-unknown/release/examples/research_concurrency_guest.wasm"
        component = output / "probe.wasm"
        command("component-build", ["wasm-tools", "component", "new", str(core), "-o", str(component)])
        command("component-validate", ["wasm-tools", "validate", "--features", "all", str(component)])
        (output / "actual.wit").write_bytes(command("component-wit", ["wasm-tools", "component", "wit", str(component)]))
        receipt["componentSha256"] = hashlib.sha256(component.read_bytes()).hexdigest()
        command("host-build", ["cargo", "build", "--locked", "--release", "-p", "latent-toolchain-smoke",
                "--example", "research-concurrency-host"], 1800)
        raw = command("actual-components", [str(output / "target/release/examples/research-concurrency-host"), str(component)], 180)
        runtime = json.loads(raw)
        verify_measurements(runtime)
        (output / "runtime.json").write_text(json.dumps(runtime, indent=2, sort_keys=True) + "\n")
        if sources() != receipt["sources"]:
            raise ValueError("source-changed-during-experiment")
        receipt.update(status="passed", stage="complete", runtime=runtime)
    except (BuildProcessError, ValueError, OSError) as error:
        receipt["reason"] = error.reason if isinstance(error, BuildProcessError) else str(error)[:256]
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.output)
    except (BuildProcessError, ValueError, OSError) as error:
        print("Invocation concurrency experiment failed:", error, file=sys.stderr)
        return 1
    print("Invocation concurrency experiment:", result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
