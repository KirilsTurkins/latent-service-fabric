#!/usr/bin/env python3
"""Measure standalone LSF/native processes with a separate persistent RPC client.

Smoke is the default. Full explicitly collects seven alternating matched pairs;
neither profile runs the100k dormant catalog or100k soak workload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.optimization_runner import fixtures
from tools.optimization_runner.plans import plan, SERVICES, TENANT, TOKEN
from tools.optimization_runner.processes import OwnedProcess, cgroup, snapshot
from tools.phase1_measurement_environment import build_configuration, host
from tools.run_phase1_conformance import bounded_run, digest, git


class Limits:
    def __init__(self, output: Path, selected: dict):
        self.output = output
        self.maximum_bytes = int(selected["maximum_artifact_bytes"])
        self.deadline = time.monotonic() + int(selected["maximum_run_seconds"])

    def remaining(self, ceiling: float) -> float:
        remaining = min(ceiling, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("optimization suite wall-time bound")
        return remaining

    def reserve(self, maximum_additional_bytes: int) -> None:
        self.remaining(1)
        paths = [path for path in self.output.rglob("*") if path.is_file()]
        if len(paths) > 4096 or sum(path.stat().st_size for path in paths) + maximum_additional_bytes > self.maximum_bytes:
            raise ValueError("optimization retained-artifact bound")


# This command runs one suite per process. Every child receives the remaining
# shared execution time; reserving a client's entire output cap bounds growth
# between filesystem checks outside measured RPC intervals.
_limits: Limits | None = None


def timeout(ceiling: float) -> float:
    return _limits.remaining(ceiling) if _limits else ceiling


def reserve(maximum: int) -> None:
    if _limits:
        _limits.reserve(maximum)


def overall_deadline() -> int | None:
    return int(_limits.deadline * 1_000_000_000) if _limits else None


def source_identity() -> dict:
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
            "cargo_lock_sha256": digest(ROOT / "Cargo.lock")[0]}


def ref(path: Path, output: Path) -> dict:
    if path.is_file() and path.stat().st_size == 0:
        sha, size = "sha256:" + hashlib.sha256(b"").hexdigest(), 0
    else:
        sha, size = digest(path)
    return {"path": path.relative_to(output).as_posix(), "sha256": sha, "bytes": str(size)}


def retain(path: Path, output: Path, name: str) -> dict:
    reserve(path.stat().st_size)
    target = output / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    return ref(target, output)


def endpoint(event: dict) -> str:
    record = event["record"]
    address = record.get("address", record.get("endpoint"))
    if not isinstance(address, str):
        raise ValueError("server omitted actual bound endpoint")
    return address if address.startswith("http://") else "http://" + address


def cli(binary: Path, config: Path, arguments: list[str], log: Path) -> dict:
    reserve(4 * 1024 * 1024)
    data = bounded_run([str(binary), "--config", str(config), "--output", "json", *arguments],
                       log, timeout(15), os.environ.copy())
    value = json.loads(data)
    if value.get("category") != "success":
        raise RuntimeError("benchmark provision/status command did not succeed")
    return value


def ready_node(binary: Path, config: Path, directory: Path, prefix: str) -> None:
    for attempt in range(30):
        result = cli(binary, config, ["node", "get", "optimization-node"],
                     directory / f"{prefix}-ready-{attempt:02}.log")
        if result["data"]["inventory"]["health"]["ready"] is True:
            return
        time.sleep(0.05)
    raise RuntimeError("LSF did not attest ready state")


def seed(binary: Path, control: Path, config: Path, publications: list[dict], directory: Path) -> None:
    server = OwnedProcess([str(binary), "serve", "--config", str(config)], directory / "seed-server.log",
                          "lsf-seed", timeout(120), ROOT, overall_deadline_ns=overall_deadline())
    stopped = None
    try:
        client_config = fixtures.cli_config(directory, endpoint(server.ready()), "seed-client.json")
        ready_node(control, client_config, directory, "seed")
        for index, package in enumerate(publications):
            cli(control, client_config, ["release", "publish", "--manifest", str(package["manifest"]),
                "--component", str(package["component"]), "--contracts", str(package["contracts"])],
                directory / f"publish-{index}.log")
            cli(control, client_config, ["deployment", "apply", str(package["deployment"])],
                directory / f"deploy-{index}.log")
        stopped = server.stop()
    finally:
        server.close()
        fixtures.write(directory / "seed-cleanup.json", {"server": server.receipt, "server_shutdown": stopped})


def batch(case: dict, run_id: str, arm: str, address: str, server: OwnedProcess,
          client_binary: Path, directory: Path, output: Path) -> tuple[dict, int | None]:
    reserve(case["client_plan"]["maximum_output_bytes"] + 8 * 1024 * 1024)
    directory.mkdir()
    token = directory / "token.txt"
    token.write_text(TOKEN, encoding="utf-8")
    actual = {**case["client_plan"], "run_id": run_id, "arm": arm,
              "server_process_id": server.child.pid, "endpoint": address, "token_file": str(token)}
    plan_path = directory / "plan.json"
    fixtures.write(plan_path, actual)
    client_output = directory / "client"
    client_output.mkdir()
    before_server, before_cgroup = server.sample(), cgroup()
    server.peak_rss = int(before_server["rss_bytes"])
    client = OwnedProcess([str(client_binary), "--plan", str(plan_path), "--output", str(client_output)],
                          directory / "client.log", "load-client", timeout(90), ROOT,
                          overall_deadline_ns=overall_deadline())
    completed = {}
    def capture_completed() -> None:
        server.sample()
        completed.update(server=server.resources(before_server), client=client.completed_resources,
                         cgroup={"before": before_cgroup, "after": cgroup()})
    try:
        client.wait(server, capture_completed)
        if not completed or int(completed["client"]["after"]["rss_bytes"]) <= 0:
            raise RuntimeError("missing live client completion resource observation")
        fixtures.write(directory / "resources.json", completed)
        fixtures.write(directory / "client-process.json", client.receipt)
        result = {"id": case["id"], "plan": ref(plan_path, output),
                  **{name: ref(client_output / f"{name}.json", output) for name in ("readiness", "summary")},
                  "attempts": ref(client_output / "attempts.jsonl", output),
                  "client_process": ref(directory / "client-process.json", output),
                  "resources": ref(directory / "resources.json", output)}
        first = next((event["observed_ns"] for event in client.events
                      if event["record"].get("event") == "first-response"), None)
        return result, first
    finally:
        client.close()
        if not (directory / "client-process.json").exists():
            fixtures.write(directory / "client-process.json", client.receipt)


def run_arm(repetition: int, arm: str, selected: dict, binaries: dict[str, Path],
            publications: list[dict], output: Path, target: Path, result: dict) -> None:
    directory = output / f"pair-{repetition:02}-{arm}"
    directory.mkdir()
    with tempfile.TemporaryDirectory(prefix="optimization-owned-", dir=target) as state:
        if arm == "lsf":
            config = fixtures.node_config(directory, Path(state) / "data")
            seed(binaries["lsf"], binaries["control"], config, publications, directory)
            command = [str(binaries["lsf"]), "serve", "--config", str(config)]
        else:
            config = directory / "native.json"
            fixtures.write(config, {"listen": "127.0.0.1:0", "tenant": TENANT, "services": SERVICES,
                                    "concurrency": 4, "runtime_workers": 2, "timeout_millis": 5000,
                                    "token_kind": "public-local-benchmark-fixture"})
            command = [str(binaries["native"]), "--listen", "127.0.0.1:0", "--token", TOKEN,
                       "--tenant", TENANT, "--services", ",".join(SERVICES), "--concurrency", "4"]
        server = OwnedProcess(command, directory / "server.log", f"{arm}-server", timeout(900), ROOT,
                              overall_deadline_ns=overall_deadline())
        result["started_micros"] = str(server.started_ns // 1000)
        stopped = None
        try:
            address = endpoint(server.ready())
            if arm == "lsf":
                control_config = fixtures.cli_config(directory, address, "measured-client.json")
                ready_node(binaries["control"], control_config, directory, "measured")
            ready_ns = time.monotonic_ns()
            first_ns = None
            for case in selected["cases"]:
                run_id = f"p{repetition:02}-{arm}-{case['id']}"
                current, first = batch(case, run_id, arm, address, server, binaries["client"],
                                       directory / case["id"], output)
                result["batches"].append(current)
                if first_ns is None:
                    first_ns = first
                print(f"pair {repetition} {arm} {case['id']} retained", flush=True)
            if first_ns is None or first_ns < ready_ns:
                raise RuntimeError("client omitted actual first-response observation")
            result["lifecycle"] = {
                "process_start_to_ready_micros": str((ready_ns - server.started_ns) // 1000),
                "process_start_to_first_response_observed_micros": str((first_ns - server.started_ns) // 1000),
                "ready_to_first_response_observed_micros": str((first_ns - ready_ns) // 1000),
                "first_response_observation": "parent-received-client-event-upper-bound-includes-client-startup-and-connect",
                "initial_preparation": "included-in-first-call" if arm == "lsf" else "not-applicable",
            }
            stopped = server.stop()
            result["finished_micros"] = str(time.monotonic_ns() // 1000)
            fixtures.write(directory / "server-process.json", server.receipt)
            clients = [json.loads((output / item["client_process"]["path"]).read_text()) for item in result["batches"]]
            fixtures.write(directory / "cleanup.json", {"server": server.receipt, "clients": clients,
                                                       "server_shutdown": stopped})
            result.update(server_process=ref(directory / "server-process.json", output),
                          cleanup=ref(directory / "cleanup.json", output), configuration=ref(config, output))
            result.update(status="passed", reason=None)
        finally:
            server.close()
            if not (directory / "server-process.json").exists():
                fixtures.write(directory / "server-process.json", server.receipt)
            if not (directory / "cleanup.json").exists():
                receipts = [json.loads(path.read_text()) for path in sorted(directory.glob("*/client-process.json"))]
                fixtures.write(directory / "cleanup.json", {"server": server.receipt, "clients": receipts,
                                                           "server_shutdown": stopped})
            result.update(server_process=ref(directory / "server-process.json", output),
                          cleanup=ref(directory / "cleanup.json", output), configuration=ref(config, output))


def run(profile: str, output: Path, target: Path) -> None:
    global _limits
    selected = plan(profile)
    source = source_identity()
    if profile == "full" and source["dirty"]:
        raise ValueError("full reference requires clean source")
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target)
    bounded_run(["bash", "tools/build_optimization_bench.sh", profile], output / "build.log", 3600, env)
    _limits = Limits(output, selected)
    after_build = source_identity()
    fixtures.write(output / "source-after-build.json", after_build)
    if source != after_build:
        raise ValueError("source changed during benchmark build")
    level = "release" if profile == "full" else "debug"
    binaries = {name: target / level / filename for name, filename in {
        "lsf": "latentd", "control": "latent", "native": "optimization-native", "client": "optimization-client",
    }.items()}
    executable_refs = {name: retain(path, output, f"binaries/{path.name}") for name, path in binaries.items()}
    reserve(80 * 1024 * 1024)
    publications = fixtures.materialize(target / "capsules/optimization/optimization-capsule.wasm", output / "fixtures")
    for package in publications:
        bounded_run(["wasm-tools", "validate", str(package["component"])],
                    output / f"validate-{package['component'].stem}.log", timeout(10), env)
    build = build_configuration(profile)
    build["overrides"]["collector_surface"] = "separate-standalone-server-and-load-client"
    if profile == "smoke":
        build["overrides"].update(recipe="cargo-build-debug-no-debuginfo", debug="0")
    build["overrides"]["optimization_recipe_sha256"] = digest(ROOT / "tools/build_optimization_bench.sh")[0]
    build["overrides"]["recipe_sha256"] = digest(ROOT / "tools/phase0_build_environment.sh")[0]
    source_files = sorted((ROOT / "tools/optimization-workloads").rglob("*.rs"))
    source_files += [ROOT / "tools/toolchain-smoke/examples/optimization_capsule/component.rs",
                     ROOT / "tools/toolchain-smoke/examples/optimization_capsule/world.wit"]
    workload_refs = [retain(path, output, "sources/" + path.relative_to(ROOT).as_posix()) for path in source_files]
    build_inputs = [retain(ROOT / name, output, "sources/" + name) for name in (
        "Cargo.lock", "Cargo.toml", "rust-toolchain.toml", "tools/build_optimization_bench.sh",
        "tools/phase0_build_environment.sh", "tools/optimization-bench/Cargo.toml",
        "tools/optimization-workloads/Cargo.toml", "tools/toolchain-smoke/Cargo.toml",
    )]
    suite = {"schema": "latent.optimization.suite.v1", "profile": profile, "plan": selected,
             "identity": {"source": source, "build": build, "environment": host(),
                          "executables": executable_refs,
                          "components": [ref(package["component"], output) for package in publications],
                          "workload_sources": workload_refs, "build_inputs": build_inputs,
                          "source_checks": [ref(output / "source-after-build.json", output)]},
             "runs": [], "artifacts": []}
    try:
        for repetition in range(1, selected["repetitions"] + 1):
            arms = ("native", "lsf") if repetition % 2 else ("lsf", "native")
            for arm in arms:
                timeout(1)
                current = {"repetition": repetition, "arm": arm, "scenario": "cold-restart",
                           "status": "failed", "reason": "collector-failed", "batches": [],
                           "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                           "server_process": None, "configuration": None, "cleanup": None, "lifecycle": None}
                suite["runs"].append(current)
                try:
                    run_arm(repetition, arm, selected, binaries, publications, output, target, current)
                finally:
                    if current["finished_micros"] is None:
                        current["finished_micros"] = str(time.monotonic_ns() // 1000)
    finally:
        # Every completed attempt/log remains even on an interrupted/failed run.
        fixtures.write(output / "source-after-run.json", source_identity())
        suite["identity"]["source_checks"].append(ref(output / "source-after-run.json", output))
        for path in sorted(output.rglob("*")):
            if path.is_file():
                suite["artifacts"].append(ref(path, output))
        fixtures.write(output / "suite.json", suite)
    from tools.optimization_evidence.suite import validate_suite
    aggregate = validate_suite(output / "suite.json")
    fixtures.write(output / "aggregate.json", aggregate)
    if not aggregate["population_complete"] or aggregate["status"] == "failed":
        raise RuntimeError("optimization population or semantic validation failed")
    print(f"Validated {profile} optimization evidence: {output}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--target-root", type=Path, default=Path(os.environ.get("CARGO_TARGET_DIR", "target")))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("standalone process/resource measurement requires Linux (including a declared Linux container)")
    target = args.target_root.resolve()
    target.mkdir(parents=True, exist_ok=True)
    parent = target / "optimization-benchmarks"
    parent.mkdir(exist_ok=True)
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix=args.profile + "-", dir=parent))
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("output must be a new empty directory")
    try:
        run(args.profile, output, target)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        fixtures.write(output / "failure.json", {"schema": "latent.optimization.runner-failure.v1",
                       "status": "failed", "reason": str(error), "completion": "incomplete"})
        print(f"Optimization profile failed: {error}\nRetained diagnostics: {output}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
