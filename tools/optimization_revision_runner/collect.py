"""Compose existing bounded clients, builders and replay with explicit revisions."""
from __future__ import annotations

import copy
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
    from . import budget
    from tools.optimization_revision_evidence import budget_builds
    is_budget = getattr(args, "experiment", "warm") == "budget"
    build_only = getattr(args, "build_only", False)
    build_path = getattr(args, "builds", None)
    if (build_only or build_path) and not is_budget:
        raise ValueError("build-only-and-prebuilt-require-budget-experiment")
    prebuilt = budget_builds.load(build_path.resolve(), args.profile) if build_path else None
    refs = prebuilt["requested_refs"] if prebuilt else {name: getattr(args, name + "_ref") for name in ("control", "candidate", "harness")}
    build.validate_refs(refs, args.profile)
    runner_source = build.source(repo)
    if runner_source["commit"] != refs["harness"] or (is_budget and not runner_source["clean"]):
        raise ValueError("executed-runner-must-match-clean-harness-ref")
    if any(os.environ.get(name) for name in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("inherited-runtime-allocation-override")
    output, target = (build_path.resolve().parent if prebuilt else args.output.resolve()), args.target_root.resolve()
    if prebuilt:
        if any((output / name).exists() or (output / name).is_symlink() for name in ("suite.json", "aggregate.json", "runs")):
            raise ValueError("budget-prebuilt-root-already-measured")
        allowed = {row["path"] for row in prebuilt["artifacts"]} | {build_path.name}
        if {row["path"] for row in artifact_rows(output)} != allowed:
            raise ValueError("budget-prebuilt-root-is-not-build-only")
    else:
        output.mkdir(parents=True, exist_ok=False)
    target.mkdir(parents=True, exist_ok=True)
    selected, began = (budget.plan if is_budget else plan)(args.profile), time.monotonic_ns()
    suite = {"schema": budget.SCHEMA if is_budget else "latent.optimization.revision-suite.v1", "profile": args.profile, "plan": selected,
             "requested_refs": refs, "status": "failed", "reason": "collection-incomplete",
             "elapsed_nanos": "0", "measurement_elapsed_nanos": "0",
             "identity": {"runner_source": runner_source, "runner_source_after": None,
                          "build": build_configuration("full"), "builds": {}, "components": [],
                          "publications": [], "harness_sources": {}, "environment": host(), "cgroup": cgroup()},
             "cleanup": {"owned_worktree_removed": False}, "runs": [], "artifacts": []}
    suite["identity"]["build"]["overrides"]["collector_surface"] = "separate-standalone-server-and-load-client"
    if is_budget:
        suite["builds"] = None
        suite["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
    if prebuilt:
        suite["identity"] = copy.deepcopy(prebuilt["identity"])
        if suite["identity"]["runner_source"] != runner_source:
            raise ValueError("budget-reused-build-harness-source-changed")
        suite["identity"].update(environment=host(), cgroup=cgroup())
        suite["cleanup"] = prebuilt["cleanup"]
        suite["builds"] = legacy.ref(build_path.resolve(), output)
    save = lambda: write(output / ("revision-builds.json" if build_only else "suite.json"),
                         budget_builds.receipt(suite) if build_only else suite)
    save()
    measured_start = None
    try:
        backend_output = args.backend_build_output.resolve() if args.backend_build_output else None
        if backend_output is not None and (backend_output == output or backend_output.is_relative_to(output)
                                           or output.is_relative_to(backend_output)):
            raise ValueError("backend-output-must-be-a-separate-directory")
        if not prebuilt:
            options = {"selected": budget} if is_budget else {}
            build.collect(repo, refs, output, target, began + int(selected["maximum_build_seconds"]) * 10**9,
                          suite, save, backend_output, **options)
            initialize_inputs(repo, output, suite)
            if is_budget:
                built = budget_builds.receipt(suite)
                built.update(status="passed", reason=None, elapsed_nanos=str(time.monotonic_ns() - began),
                             artifacts=artifact_rows(output, exclude=("revision-builds.json",)))
                built["identity"]["runner_source_after"] = build.source(repo)
                write(output / "revision-builds.json", built)
                budget_builds.load(output / "revision-builds.json", args.profile)
                suite["builds"] = legacy.ref(output / "revision-builds.json", output)
        if build_only:
            suite.update(status="passed", reason=None)
        else:
            measured_start = time.monotonic_ns()
            measure(args, repo, output, target, suite, selected, save, is_budget)
            suite.update(status="passed", reason=None)
    except BaseException as error:
        suite.update(status="failed", reason="collection-failed")
        write(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
    finally:
        suite["elapsed_nanos"] = str(time.monotonic_ns() - began)
        if measured_start is not None:
            suite["measurement_elapsed_nanos"] = str(time.monotonic_ns() - measured_start)
        suite["identity"]["runner_source_after"] = build.source(repo)
        suite["artifacts"] = artifact_rows(output, exclude=("revision-builds.json",) if build_only else ())
        save()
        legacy._limits = None
    if build_only:
        if suite["status"] != "passed":
            return 1
        budget_builds.load(output / "revision-builds.json", args.profile)
        return 0
    from tools.optimization_revision_evidence import validate_suite
    aggregate = validate_suite(output / "suite.json")
    write(output / "aggregate.json", aggregate)
    return 0 if aggregate["population_complete"] and aggregate["status"] != "failed" else 1


def initialize_inputs(repo, output, suite):
    harness = suite["identity"]["builds"]["harness"]
    publications = fixtures.materialize(output / harness["component"]["path"], output / "fixtures")
    for package in publications:
        suite["identity"]["publications"].append({name: legacy.ref(path, output) for name, path in package.items()})
    suite["identity"]["components"] = [legacy.ref(item["component"], output) for item in publications]
    tracked = build.git(repo, "ls-files").splitlines()
    names = [name for name in tracked if name.startswith("tools/") and name.endswith(".py")]
    if not 1 <= len(names) <= 1024:
        raise ValueError("revision-harness-source-bound")
    suite["identity"]["harness_sources"] = {
        name: legacy.retain(repo / name, output, "harness-source/" + name) for name in names}


def measure(args, repo, output, target, suite, selected, save, is_budget):
    from . import budget
    legacy._limits = legacy.Limits(output, selected)
    harness = suite["identity"]["builds"]["harness"]
    publications = [{name: output / row["path"] for name, row in package.items()}
                    for package in suite["identity"]["publications"]]
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
            options = {"configure": budget.node_config} if is_budget else {}
            run.collect(repetition, variant, selected, binaries, publications, output, target, current, **options)
        finally:
            current["finished_micros"] = current["finished_micros"] or str(time.monotonic_ns() // 1000)
            current["environment_after"] = host()
            save()


def artifact_rows(output, exclude=()):
    rows = []
    for count, path in enumerate(output.rglob("*"), 1):
        if count > 8192 or path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("revision-artifact-symlink")
        if path.is_file() and path.name not in ("suite.json", "aggregate.json", *exclude):
            rows.append(legacy.ref(path, output))
    return sorted(rows, key=lambda row: row["path"])
