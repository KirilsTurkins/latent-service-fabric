"""Compose existing bounded clients, builders and replay with explicit revisions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import time

from tools import run_optimization_benchmarks as legacy
from tools.optimization_evidence.common import canonical
from tools.optimization_runner import fixtures
from tools.optimization_runner.processes import cgroup
from tools.phase1_measurement_environment import build_configuration, host
from . import build, run
from .model import plan, population


def write(path, value):
    path.write_bytes(canonical(value) + b"\n")


def execute(args, repo: Path) -> int:
    if platform.system() != "Linux":
        raise ValueError("revision-comparison-requires-linux")
    refs = {name: getattr(args, name + "_ref") for name in ("control", "candidate", "harness")}
    build.validate_refs(refs, args.profile)
    runner_source = build.source(repo)
    if runner_source["commit"] != refs["harness"]:
        raise ValueError("executed-runner-must-match-clean-harness-ref")
    if any(os.environ.get(name) for name in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("inherited-runtime-allocation-override")
    output, target = args.output.resolve(), args.target_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    target.mkdir(parents=True, exist_ok=True)
    selected, began = plan(args.profile), time.monotonic_ns()
    suite = {"schema": "latent.optimization.revision-suite.v1", "profile": args.profile, "plan": selected,
             "requested_refs": refs, "status": "failed", "reason": "collection-incomplete",
             "elapsed_nanos": "0", "measurement_elapsed_nanos": "0",
             "identity": {"runner_source": runner_source, "runner_source_after": None,
                          "build": build_configuration("full"), "builds": {}, "components": [],
                          "publications": [], "harness_sources": {}, "environment": host(), "cgroup": cgroup()},
             "cleanup": {"owned_worktree_removed": False}, "runs": [], "artifacts": []}
    suite["identity"]["build"]["overrides"]["collector_surface"] = "separate-standalone-server-and-load-client"
    save = lambda: write(output / "suite.json", suite)
    save()
    measured_start = None
    try:
        backend_output = args.backend_build_output.resolve() if args.backend_build_output else None
        if backend_output is not None and (backend_output == output or backend_output.is_relative_to(output)
                                           or output.is_relative_to(backend_output)):
            raise ValueError("backend-output-must-be-a-separate-directory")
        build.collect(repo, refs, output, target, began + int(selected["maximum_build_seconds"]) * 10**9,
                      suite, save, backend_output)
        legacy._limits = legacy.Limits(output, selected)
        measured_start = time.monotonic_ns()
        harness = suite["identity"]["builds"]["harness"]
        publications = fixtures.materialize(output / harness["component"]["path"], output / "fixtures")
        for package in publications:
            suite["identity"]["publications"].append({name: legacy.ref(path, output) for name, path in package.items()})
        suite["identity"]["components"] = [legacy.ref(item["component"], output) for item in publications]
        # Retain the executed Python method and all reused helper sources, not an uncommitted overlay.
        tracked = build.git(repo, "ls-files").splitlines()
        names = [name for name in tracked if name.startswith("tools/") and name.endswith(".py")]
        if not 1 <= len(names) <= 1024:
            raise ValueError("revision-harness-source-bound")
        suite["identity"]["harness_sources"] = {
            name: legacy.retain(repo / name, output, "harness-source/" + name) for name in names}
        binaries = {variant: output / suite["identity"]["builds"][variant]["executables"]["server"]["path"]
                    for variant in ("control", "candidate")}
        binaries.update({name: output / row["path"] for name, row in harness["executables"].items()})
        for repetition, variant in population(args.profile):
            current = {"repetition": repetition, "variant": variant, "arm": "lsf", "scenario": "cold-restart",
                       "status": "failed", "reason": "collector-failed", "batches": [],
                       "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                       "server_process": None, "configuration": None, "cleanup": None, "lifecycle": None,
                       "data_removed": False, "environment_before": host(), "environment_after": None}
            suite["runs"].append(current)
            save()
            try:
                run.collect(repetition, variant, selected, binaries, publications, output, target, current)
            finally:
                current["finished_micros"] = current["finished_micros"] or str(time.monotonic_ns() // 1000)
                current["environment_after"] = host()
                save()
        suite.update(status="passed", reason=None)
    except BaseException as error:
        suite.update(status="failed", reason="collection-failed")
        write(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
    finally:
        suite["elapsed_nanos"] = str(time.monotonic_ns() - began)
        if measured_start is not None:
            suite["measurement_elapsed_nanos"] = str(time.monotonic_ns() - measured_start)
        suite["identity"]["runner_source_after"] = build.source(repo)
        rows = []
        for path in sorted(output.rglob("*")):
            if path.is_symlink():
                raise ValueError("revision-artifact-symlink")
            if path.is_file() and path.name not in ("suite.json", "aggregate.json"):
                rows.append(legacy.ref(path, output))
        suite["artifacts"] = rows
        save()
        legacy._limits = None
    from tools.optimization_revision_evidence import validate_suite
    aggregate = validate_suite(output / "suite.json")
    write(output / "aggregate.json", aggregate)
    return 0 if aggregate["population_complete"] and aggregate["status"] != "failed" else 1
