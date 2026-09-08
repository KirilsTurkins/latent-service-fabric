#!/usr/bin/env python3
"""Run a small controlled historical/current echo experiment on one Linux host.

Build the historical control once with build_phase1_historical_control.sh.
This runner verifies and retains that build, builds the current release collector,
then alternates independent control/candidate processes. The smoke default cannot
complete the comparison gate. No scale, soak, or historical full calibration runs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase1_measurement_environment import build_configuration, capture, host
from tools.run_phase1_conformance import ROOT, bounded_run, digest
from tools.run_phase1_measurements import build, reference, write_json

HISTORICAL_COMMIT = "52ac47542a05c0a1263f78a14c04a5c2e6b761f3"
COLLECTOR = "standalone::measurements::comparison::phase1_comparison_collector"
METHOD = "historical-runtime-productionization-bundle-v1"
HISTORICAL_METHOD_SOURCES = (
    *(f"apps/latentd/src/bin/phase0_baseline/{name}.rs" for name in ("run", "activation", "timing", "definitions")),
    "crates/latent-wasmtime/src/lib.rs", "crates/latent-wasmtime/src/backend.rs",
)


def plan(profile: str, repetition: int = 1) -> dict:
    full = profile == "full"
    return {"schema": "latent.phase1.paired-plan.v1", "profile": profile,
            "repetition": repetition, "warmup_samples": 40 if full else 2,
            "measured_samples": 400 if full else 4,
            "maximum_run_seconds": "600" if full else "120",
            "maximum_output_bytes": "16777216"}


def source_identity(source: Path) -> dict:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(source), *arguments], check=True,
                              capture_output=True, text=True, timeout=15).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
            "cargo_lock_sha256": digest(source / "Cargo.lock")[0]}


def retained_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"required regular input is missing: {source}")
    expected = digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"retained input already exists: {destination}")
    shutil.copy2(source, destination)
    if digest(destination) != expected:
        raise ValueError("input changed while retaining original bytes")


def checked_reference(root: Path, value: dict) -> Path:
    if set(value) != {"path", "sha256", "bytes"}:
        raise ValueError("malformed historical build artifact reference")
    relative = value["path"]
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise ValueError("nonportable historical build artifact path")
    pieces = relative.split("/")
    if any(piece in ("", ".", "..") for piece in pieces):
        raise ValueError("unsafe historical build artifact path")
    candidate = root
    for piece in pieces:
        candidate /= piece
        if candidate.is_symlink():
            raise ValueError("historical build artifact path contains a symbolic link")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("historical build artifact escapes retained root")
    actual = digest(candidate)
    if actual != (value["sha256"], int(value["bytes"])):
        raise ValueError(f"historical build artifact hash/size mismatch: {relative}")
    return candidate


def retain_control(source: Path, bootstrap: Path, output: Path) -> tuple[dict, Path, Path, Path]:
    from phase1_evidence.common import read_json
    receipt_path = bootstrap / "build-receipt.json"
    receipt = read_json(receipt_path)
    if receipt.get("schema") != "latent.phase1.control-build.v1":
        raise ValueError("expected a historical control build receipt")
    observed_source = source_identity(source)
    if observed_source["commit"] != HISTORICAL_COMMIT or observed_source["dirty"]:
        raise ValueError("historical source must be the pristine pinned commit")
    if receipt["source"] != observed_source:
        raise ValueError("historical build source differs from inspected source")
    expected_build = build_configuration("full")
    if digest(source / "tools/phase0_build_environment.sh")[0] != expected_build["overrides"]["recipe_sha256"]:
        raise ValueError("historical and current release recipes differ")
    # The historical executable is an ordinary binary; the current collector
    # includes libtest. This fixed driver difference is retained as treatment.
    historical_build = receipt["build"]
    normalized = json.loads(json.dumps(historical_build))
    normalized["overrides"]["collector_surface"] = "libtest"
    if normalized != expected_build:
        raise ValueError("historical build toolchain/recipe differs from current build")
    retained = output / "reproduction" / "control"
    refs = [receipt[name] for name in ("binary", "component", "capsule")]
    refs.extend(receipt["artifacts"])
    seen = {}
    for value in refs:
        path = checked_reference(bootstrap, value)
        previous = seen.get(value["path"])
        if previous is not None:
            if previous != value:
                raise ValueError("conflicting historical artifact references")
            continue
        seen[value["path"]] = value
        retained_file(path, retained / value["path"])
    retained_file(receipt_path, retained / "build-receipt.json")
    binary = retained / receipt["binary"]["path"]
    component = retained / receipt["component"]["path"]
    capsule = retained / receipt["capsule"]["path"]
    identity = {"schema": "latent.phase1.measurement-identity.v1", "source": observed_source,
                "build": historical_build, "environment": host(),
                "binary": {key: receipt["binary"][key] for key in ("sha256", "bytes")},
                "fixtures": [{"name": "echo", **{key: receipt["component"][key]
                                                    for key in ("sha256", "bytes")}}]}
    return identity, binary, component, capsule


def control_command(binary: Path, capsule: Path, current: Path, selected: dict) -> list[str]:
    # The unmodified targeted historical branch does not read the required CLI
    # probe argument. Keep a nonexistent sentinel; do not fabricate full proof.
    return [str(binary), "--capsule", str(capsule),
            "--executable-harness-probe", str(current / "not-applicable-targeted-probe.json"),
            "--parent-launch-unix-micros", str(time.time_ns() // 1000),
            "--output-json", str(current / "baseline.json"),
            "--output-report", str(current / "BASELINE.md"), "--mode", "full",
            "--profile-workload", "warm-execution", "--warm-samples",
            str(selected["warmup_samples"] + selected["measured_samples"]),
            "--fuel", "10000000000", "--memory-bytes", "16777216",
            "--pool-capacity", "2", "--pool-queue-capacity", "3", "--runtime-workers", "2",
            "--wasmtime-allocator", "on-demand", "--wasmtime-copy-on-write-images", "true",
            "--prepared-cache-enabled", "true"]


def retain_suite(output: Path, suite: dict) -> None:
    # Preserve every attempt and auxiliary receipt; no executable data roots
    # live in this tree. Original measurement/build inputs are never rewritten.
    suite["artifacts"] = [reference(path, output, 1024 * 1024 * 1024)
                          for path in sorted(output.rglob("*")) if path.is_file()
                          and path.stat().st_size and path.name != "suite.json"]
    write_json(output / "suite.json", suite)


def build_candidate_fixture(output: Path, env: dict[str, str]) -> None:
    # A pre-existing target artifact does not prove which guest sources produced
    # it. The maintained builder uses two fresh targets and compares their bytes.
    bounded_run([sys.executable, "tools/build_echo_capsule.py", "--verify-reproducible"],
                output / "candidate-fixture-build.log", 600, env)


def run(profile: str, output: Path, target: Path, control_source: Path, control_build: Path) -> None:
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    candidate_source = source_identity(ROOT)
    if profile == "full" and candidate_source["dirty"]:
        raise ValueError("full controlled comparison requires clean current source")
    control_identity, control_binary, control_component, capsule = retain_control(control_source, control_build, output)
    control_capsule_identity = digest(capsule)
    build_candidate_fixture(output, env)
    candidate_component = target / "capsules/echo/echo-capsule.wasm"
    digest(candidate_component, 16 * 1024 * 1024)
    candidate_binary = build("full", target, output, env)
    policy_log = output / "build-policy.log"
    if policy_log.is_file() and not policy_log.stat().st_size:
        policy_log.write_text("Build policy accepted.\n", encoding="utf-8")
    candidate_identity = capture("full", candidate_binary, {"echo": candidate_component})
    if candidate_identity["source"] != candidate_source:
        raise ValueError("candidate source identity changed during fixture/collector build")
    if profile == "full" and candidate_identity["source"]["dirty"]:
        raise ValueError("full controlled comparison requires clean current source")
    candidate_root = output / "reproduction" / "candidate"
    retained_file(candidate_binary, candidate_root / "collector")
    retained_file(candidate_component, candidate_root / "echo-capsule.wasm")
    for name in ("capsule.json", "contracts.json", "build.json"):
        retained_file(candidate_component.parent / name, candidate_root / name)
    candidate_metadata = [(candidate_root / name, digest(candidate_root / name))
                          for name in ("capsule.json", "contracts.json", "build.json")]
    candidate_binary = candidate_root / "collector"
    candidate_component = candidate_root / "echo-capsule.wasm"
    guest_sources = []
    for name in ("component.rs", "logic.rs"):
        logical = f"tools/toolchain-smoke/examples/echo_capsule/{name}"
        retained_file(ROOT / logical, candidate_root / "sources" / logical)
        guest_sources.append({"path": logical,
                              "artifact": reference(candidate_root / "sources" / logical, output)})
    method_sources = []
    for logical in HISTORICAL_METHOD_SOURCES:
        retained = output / "reproduction/control/method-sources" / logical
        retained_file(control_source / logical, retained)
        method_sources.append({"path": logical, "artifact": reference(retained, output)})
    if source_identity(control_source) != control_identity["source"]:
        raise ValueError("historical source identity changed while retaining method evidence")
    identities = {"control": control_identity, "candidate": candidate_identity}
    binaries = {"control": control_binary, "candidate": candidate_binary}
    components = {"control": control_component, "candidate": candidate_component}
    suite = {"schema": "latent.phase1.paired-suite.v1", "method": METHOD,
             "profile": profile, "plan": plan(profile), "runs": [], "artifacts": [],
             "control_build": reference(output / "reproduction/control/build-receipt.json", output),
             "candidate_guest_sources": guest_sources, "historical_method_sources": method_sources}
    origin = time.monotonic_ns()
    data_parent = target / "phase1-paired-data"
    data_parent.mkdir(parents=True, exist_ok=True)
    for repetition in range(1, (7 if profile == "full" else 1) + 1):
        order = ("control", "candidate") if repetition % 2 else ("candidate", "control")
        for arm in order:
            current = output / f"pair-{repetition:02}" / arm
            current.mkdir(parents=True)
            selected = plan(profile, repetition)
            write_json(current / "plan.json", selected)
            run_identity = {**identities[arm], "environment": host()}
            write_json(current / "identity.json", run_identity)
            # Verify every actual executable/component immediately before use.
            for path, expected in ((binaries[arm], run_identity["binary"]),
                                   (components[arm], run_identity["fixtures"][0])):
                if digest(path) != (expected["sha256"], int(expected["bytes"])):
                    raise ValueError("retained execution input changed between processes")
            if arm == "candidate" and any(digest(path) != expected for path, expected in candidate_metadata):
                raise ValueError("retained candidate fixture metadata changed between processes")
            if arm == "control" and digest(capsule) != control_capsule_identity:
                raise ValueError("retained control capsule changed between processes")
            raw = current / ("baseline.json" if arm == "control" else "candidate.json")
            command = control_command(control_binary, capsule, current, selected) if arm == "control" else [
                str(candidate_binary), "--exact", COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
            row = {"repetition": repetition, "arm": arm, "status": "failed", "reason": "collector-failed",
                   "identity": run_identity, "command": command, "raw": None, "process": None,
                   "cleanup": None, "host_after": None,
                   "started_micros": str((time.monotonic_ns() - origin) // 1000), "finished_micros": "0"}
            suite["runs"].append(row)
            process_receipt: dict = {}
            data_root = None
            print(f"Starting {profile} pair {repetition} {arm}: {current}", flush=True)
            try:
                with tempfile.TemporaryDirectory(prefix=f"pair-{repetition:02}-{arm}-", dir=data_parent) as data_root:
                    run_env = {**env, "LSF_ECHO_COMPONENT": str(candidate_component),
                               "GITHUB_SHA": run_identity["source"]["commit"],
                               "LSF_PHASE1_COMPARISON_PLAN": str(current / "plan.json"),
                               "LSF_PHASE1_COMPARISON_IDENTITY": str(current / "identity.json"),
                               "LSF_PHASE1_COMPARISON_OUTPUT": str(current),
                               "LSF_PHASE1_COMPARISON_DATA_ROOT": data_root}
                    bounded_run(command, current / "collector.log", int(selected["maximum_run_seconds"]),
                                run_env, receipt=process_receipt, cwd=control_source if arm == "control" else ROOT)
                row["raw"] = reference(raw, output, int(selected["maximum_output_bytes"]))
                row.update({"status": "passed", "reason": None})
            except BaseException:
                if raw.is_file() and 0 < raw.stat().st_size <= int(selected["maximum_output_bytes"]):
                    row["raw"] = reference(raw, output, int(selected["maximum_output_bytes"]))
                raise
            finally:
                write_json(current / "process.json", process_receipt)
                write_json(current / "parent-cleanup.json", {"removed": data_root is not None and not Path(data_root).exists()})
                write_json(current / "host-after.json", host())
                row.update({"process": reference(current / "process.json", output),
                            "cleanup": reference(current / "parent-cleanup.json", output),
                            "host_after": reference(current / "host-after.json", output),
                            "finished_micros": str((time.monotonic_ns() - origin) // 1000)})
                if row["status"] != "passed":
                    retain_suite(output, suite)
            print(f"Completed pair {repetition} {arm}", flush=True)
    retain_suite(output, suite)
    bounded_run([sys.executable, "tools/aggregate_phase1_paired.py", "--suite", str(output / "suite.json"),
                 "--output", str(output / "aggregate.json")], output / "validation.log", 120, env)
    print(f"Validated controlled comparison: {output / 'aggregate.json'}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--control-source", type=Path, required=True)
    parser.add_argument("--control-build-dir", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, default=Path(os.environ.get("CARGO_TARGET_DIR", "target")))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("controlled process/resource collection requires Linux")
    target = args.target_root.resolve()
    if args.output is None:
        parent = target / "phase1-paired"
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix=f"{args.profile}-", dir=parent))
    else:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            parser.error("evidence directory must be empty")
    try:
        run(args.profile, output, target, args.control_source.resolve(), args.control_build_dir.resolve())
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        write_json(output / "failure.json", {"schema": "latent.phase1.paired-failure.v1", "profile": args.profile,
                                            "status": "failed", "reason": str(error)})
        print(f"Controlled comparison failed; diagnostics: {output}\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
