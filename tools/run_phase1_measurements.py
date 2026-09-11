#!/usr/bin/env python3
"""Collect opt-in Phase 1 scale, soak and benchmark evidence on Linux.

The default smoke profile validates collectors; it cannot complete a full gate.
Full scale includes 100,000 durable releases/deployments. Full soak performs
100,000 measured Invokes in each of three independent processes. Full benchmark
uses seven independent release-build processes. Fixtures must already be built.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase1_measurement_environment import capture, host
from tools.run_phase1_conformance import ROOT, bounded_run, digest

COLLECTOR = "standalone::measurements::phase1_measurement_collector"
KINDS = ("scale", "soak", "benchmark")
FULL_REPETITIONS = {"scale": 1, "soak": 3, "benchmark": 7}


def plan(profile: str, kind: str, repetition: int = 1) -> dict:
    full = profile == "full"
    return {
        "schema": "latent.phase1.measurement-plan.v1", "profile": profile, "kind": kind,
        "repetition": repetition, "scale_counts": [100, 1000, 10000, 100000] if full else [2, 4],
        "route_samples": 10000 if full else 16, "warmup_invocations": 1000 if full else 4,
        "measured_invocations": 100000 if full else 20, "batch_size": 1000 if full else 20,
        "concurrency": 2, "benchmark_samples": 400 if full else 4,
        "maximum_run_seconds": "21600" if full else "90",
        "maximum_output_bytes": str(128 * 1024 * 1024 if full else 8 * 1024 * 1024),
    }


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write("\n")


def reference(path: Path, output: Path, maximum: int = 128 * 1024 * 1024) -> dict:
    sha, size = digest(path, maximum)
    return {"path": path.relative_to(output).as_posix(), "sha256": sha, "bytes": str(size)}


def repetitions(profile: str, kinds: tuple[str, ...], override: int | None) -> dict[str, int]:
    result = {kind: (FULL_REPETITIONS[kind] if profile == "full" else 1) for kind in kinds}
    if override is not None:
        if not 1 <= override <= 21:
            raise ValueError("repetitions must be between 1 and 21")
        if profile == "full" and any(override < minimum for minimum in result.values()):
            raise ValueError("full profile repetitions cannot be below the selected kind's minimum")
        result = dict.fromkeys(kinds, override)
    return result


def retain_run_artifacts(current: Path, output: Path, suite: dict) -> None:
    for filename in ("plan.json", "identity.json", "collector.log", "host-after.json", "summary.json",
                     "process.json", "parent-cleanup.json"):
        path = current / filename
        if path.is_file() and path.stat().st_size:
            suite["artifacts"].append(reference(path, output))
    for fixture in ("echo", "generic", "capabilities"):
        for kind in ("capsule", "contracts", "deployment"):
            path = current / "fixture-inputs" / f"{fixture}-{kind}.json"
            if path.is_file() and path.stat().st_size:
                suite["artifacts"].append(reference(path, output, 1024 * 1024))


def retain_suite(output: Path, suite: dict) -> None:
    for name in ("identity.json", "build.log", "build-policy.log"):
        if (output / name).stat().st_size == 0:
            # A successful policy check is silent; retain a nonempty receipt.
            (output / name).write_text("Build policy accepted.\n", encoding="utf-8")
        suite["artifacts"].append(reference(output / name, output))
    write_json(output / "suite.json", suite)


def build(profile: str, target: Path, output: Path, env: dict[str, str]) -> Path:
    bounded_run(["bash", "-c", "source tools/phase0_build_environment.sh; "
                 "phase0_reject_inherited_build_overrides && phase0_reject_hidden_cargo_configuration"],
                output / "build-policy.log", 15, env)
    arguments = ["test", "-p", "latentd", "--lib", "--no-run", "--message-format=json", "--locked"]
    if profile == "full":
        # This reuses the retained baseline's pinned release recipe without
        # changing its sources or treating this collector as a Phase 0 run.
        command = ["bash", "-c", 'source tools/phase0_build_environment.sh; phase0_release_cargo "$@"',
                   "phase1-build", *arguments, "--release"]
    else:
        command = ["cargo", *arguments]
    data = bounded_run(command, output / "build.log", 3600, env)
    matches = []
    for line in data.splitlines():
        try:
            row = json.loads(line)
        except (UnicodeError, ValueError):
            continue
        if (row.get("reason") == "compiler-artifact" and row.get("executable")
                and row.get("profile", {}).get("test") and row.get("target", {}).get("name") == "latentd"):
            matches.append(Path(row["executable"]))
    if len(matches) != 1:
        raise RuntimeError("expected exactly one latentd libtest executable from Cargo")
    binary = matches[0].resolve()
    if not binary.is_relative_to(target):
        raise RuntimeError("Cargo returned a collector outside the selected target directory")
    return binary


def run(profile: str, kinds: tuple[str, ...], counts: dict[str, int], output: Path, target: Path) -> None:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    fixtures = {name: target / f"capsules/{name}/{name}-capsule.wasm"
                for name in ("echo", "generic", "capabilities")}
    for path in fixtures.values():
        digest(path, 16 * 1024 * 1024)
    binary = build(profile, target, output, env)
    initial_identity = capture(profile, binary, fixtures)
    write_json(output / "identity.json", initial_identity)
    suite = {"schema": "latent.phase1.measurement-suite.v1", "profile": profile,
             "identity": initial_identity, "plans": {kind: plan(profile, kind) for kind in kinds},
             "runs": [], "artifacts": []}
    for name, path in fixtures.items():
        env[f"LSF_{name.upper()}_COMPONENT"] = str(path)
    for kind in kinds:
        for repetition in range(1, counts[kind] + 1):
            current = output / f"{kind}-{repetition:02}"
            current.mkdir()
            selected = plan(profile, kind, repetition)
            write_json(current / "plan.json", selected)
            run_identity = {**initial_identity, "environment": host()}
            write_json(current / "identity.json", run_identity)
            env.update({"LSF_PHASE1_MEASUREMENT_PLAN": str(current / "plan.json"),
                        "LSF_PHASE1_MEASUREMENT_OUTPUT": str(current),
                        "LSF_PHASE1_MEASUREMENT_IDENTITY": str(current / "identity.json")})
            started = time.monotonic()
            print(f"Starting {profile} {kind} {repetition}/{counts[kind]}: {current}", flush=True)
            raw = current / "measurements.jsonl"
            row = {"kind": kind, "repetition": repetition, "status": "failed",
                   "reason": "collector-failed", "report": None}
            suite["runs"].append(row)
            process_receipt: dict = {}
            data_root = None
            try:
                data_parent = target / "phase1-measurement-data"
                data_parent.mkdir(parents=True, exist_ok=True)
                # This directory is created and owned by this parent, never a
                # caller-supplied data root. Reap the process group before cleanup.
                with tempfile.TemporaryDirectory(prefix=f"{kind}-{repetition:02}-", dir=data_parent) as data_root:
                    env["LSF_PHASE1_MEASUREMENT_DATA_ROOT"] = data_root
                    bounded_run([str(binary), "--exact", COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
                                current / "collector.log", int(selected["maximum_run_seconds"]), env,
                                receipt=process_receipt)
                row["report"] = reference(raw, output, int(selected["maximum_output_bytes"]))
                row.update({"status": "passed", "reason": None})
            except BaseException:
                write_json(current / "process.json", process_receipt)
                write_json(current / "parent-cleanup.json", {"removed": data_root is not None and not Path(data_root).exists()})
                if raw.is_file() and 0 < raw.stat().st_size <= int(selected["maximum_output_bytes"]):
                    row["report"] = reference(raw, output, int(selected["maximum_output_bytes"]))
                write_json(current / "host-after.json", host())
                retain_run_artifacts(current, output, suite)
                retain_suite(output, suite)
                raise
            write_json(current / "process.json", process_receipt)
            write_json(current / "parent-cleanup.json", {"removed": data_root is not None and not Path(data_root).exists()})
            write_json(current / "host-after.json", host())
            retain_run_artifacts(current, output, suite)
            print(f"Completed {kind} {repetition}: {time.monotonic() - started:.3f}s", flush=True)
    retain_suite(output, suite)
    bounded_run([sys.executable, "tools/aggregate_phase1_evidence.py", "--suite", str(output / "suite.json"),
                 "--output", str(output / "aggregate.json")], output / "validation.log", 120, env)
    print(f"Validated {profile} Phase 1 measurements: {output / 'aggregate.json'}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--kind", choices=(*KINDS, "all"), default="all")
    parser.add_argument("--repetitions", type=int, help="independent processes; full minima are scale1/soak3/benchmark7")
    parser.add_argument("--output", type=Path, help="new or empty evidence directory")
    parser.add_argument("--target-root", type=Path, default=Path(os.environ.get("CARGO_TARGET_DIR", "target")))
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("actual process resource measurements require Linux")
    kinds = KINDS if args.kind == "all" else (args.kind,)
    try:
        counts = repetitions(args.profile, kinds, args.repetitions)
    except ValueError as error:
        parser.error(str(error))
    target = args.target_root.resolve()
    if args.output is None:
        parent = target / "phase1-measurements"
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix=f"{args.profile}-", dir=parent))
    else:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            parser.error("evidence directory must be empty; prior results cannot satisfy a new run")
    try:
        run(args.profile, kinds, counts, output, target)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        write_json(output / "failure.json", {"schema": "latent.phase1.measurement-failure.v1",
                   "profile": args.profile, "status": "failed", "reason": str(error)})
        print(f"Measurement run failed; diagnostics: {output}\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
