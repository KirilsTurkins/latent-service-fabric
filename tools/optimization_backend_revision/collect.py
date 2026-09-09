"""Consume already built exact-source inputs and supervise each diagnostic process."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import tempfile
import time

from tools import run_optimization_benchmarks as legacy
from tools.artifact_identity_runner.helpers import DirectoryLimits, command
from tools.optimization_evidence.common import read_json
from tools.optimization_revision_runner.collect import write
from tools.optimization_revision_runner.build import source
from tools.optimization_runner.processes import cgroup
from tools.phase1_measurement_environment import host
from . import model
from .cold import model as cold_model
from .cache import model as cache_model
from .budget import model as budget_model
from .recovery import model as recovery_model


def execute(args, repo):
    if getattr(args, "experiment", "warm") == "codec":
        from tools.optimization_codec.collect import execute as execute_codec
        return execute_codec(args, repo)
    if getattr(args, "experiment", "warm") == "ownership":
        from .ownership.collect import execute as execute_ownership
        return execute_ownership(args, repo)
    if platform.system() != "Linux":
        raise ValueError("backend-diagnostic-requires-linux")
    build_path = args.builds.resolve()
    output = build_path.parent
    if (output / "suite.json").exists() or (output / "runs").exists():
        raise ValueError("backend-build-directory-already-measured")
    if any(os.environ.get(name) for name in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("backend-inherited-runtime-override")
    builds = read_json(build_path)
    observed_source = source(repo)
    if observed_source["commit"] != builds["requested_refs"]["harness"]:
        raise ValueError("backend-runner-does-not-match-harness-ref")
    target = args.target_root.resolve()
    target.mkdir(parents=True, exist_ok=True)
    # Validate all build identities/hashes before starting any workload.
    from .evidence import artifact_set
    cold = getattr(args, "experiment", "warm") == "cold"
    cache = getattr(args, "experiment", "warm") == "cache"
    budget = getattr(args, "experiment", "warm") == "budget"
    recovery = getattr(args, "experiment", "warm") == "recovery"
    if recovery and not observed_source["clean"]:
        raise ValueError("recovery-runner-requires-clean-executed-harness")
    generic = budget or recovery
    observed = cold or cache or generic
    selected_model = recovery_model if recovery else budget_model if budget else cache_model if cache else cold_model if cold else model
    from .builds import validate_experiment
    if recovery:
        from .builds import validate_recovery
        validate_recovery(builds, artifact_set(output, builds), args.profile)
    elif budget:
        from .builds import validate_budget
        validate_budget(builds, artifact_set(output, builds), args.profile)
    elif cache:
        from tools.optimization_cache_lookup.builds import validate as validate_builds
        from tools.optimization_cache_lookup.files import inventory as cache_inventory
        validate_builds(builds, artifact_set(output, builds), args.profile, "behavior")
    else:
        validate_experiment(builds, artifact_set(output, builds), args.profile,"cold" if cold else "warm")
    began = time.monotonic_ns()
    scan = cache_inventory if cache else inventory
    maximum_bytes = 1024**3 if cache or generic else 2 * 1024**3
    deadline = began + (600 if recovery else (3600 if cache or budget else 4500 if cold else 9000) if args.profile == "full" else (600 if cache else 300)) * 10**9
    suite = {"schema": recovery_model.SCHEMA if recovery else budget_model.SCHEMA if budget else "latent.optimization.cache-behavior-suite.v1" if cache else "latent.optimization.cold-suite.v1" if cold else "latent.optimization.backend-revision-suite.v1", "profile": args.profile,
             "plan": selected_model.plan(args.profile), "builds": legacy.ref(build_path, output),
             "runner_source": observed_source, "runner_source_after": None,
             "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0", "runs": [], "artifacts": []}
    write(output / "suite.json", suite)
    try:
        for repetition, variant in (recovery_model.population if recovery else model.population)(args.profile):
            rows = scan(output)
            if sum(int(row["bytes"]) for row in rows) + 32 * 1024**2 > maximum_bytes:
                raise ValueError("backend-output-reservation-bound")
            current = output / "runs" / f"pair-{repetition:02}-{variant}"
            current.mkdir(parents=True)
            before = host()
            if observed:
                before["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
            supplied = (budget_model.identity if generic else model.identity)(builds, variant, before)
            write(current / "identity.json", supplied)
            selected = selected_model.plan(args.profile, repetition, variant) if observed else model.plan(args.profile, repetition)
            write(current / "plan.json", selected)
            binary = output / builds["builds"][variant]["executables"]["backend"]["path"]
            argv = [str(binary), "--exact", selected_model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
            row = {"repetition": repetition, "variant": variant, "status": "failed", "reason": "collector-failed",
                   "command": argv, "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                   "identity": legacy.ref(current / "identity.json", output), "plan": legacy.ref(current / "plan.json", output),
                   "process": None, "raw": None, "log": None, "cleanup": None,
                   "host_before": before, "host_after": None, "cgroup_before": cgroup(), "cgroup_after": None}
            suite["runs"].append(row)
            write(output / "suite.json", suite)
            try:
                data = None
                try:
                    with tempfile.TemporaryDirectory(prefix="backend-revision-data-owned-", dir=target) as data:
                        env = dict(os.environ, LSF_PHASE1_COMPARISON_PLAN=str(current / "plan.json"),
                                   LSF_PHASE1_COMPARISON_IDENTITY=str(current / "identity.json"),
                                   LSF_PHASE1_COMPARISON_OUTPUT=str(current), LSF_PHASE1_COMPARISON_DATA_ROOT=data)
                        env["LSF_GENERIC_COMPONENT" if generic else "LSF_ECHO_COMPONENT"] = str(output / (
                            builds["harness"]["component"] if generic else builds["harness"]["echo"]["component"])["path"])
                        seconds = selected_model.maximum_seconds(args.profile) if observed else int(selected["maximum_run_seconds"])
                        options = {"maximum": 1024**2, "directory_limits": DirectoryLimits(2, 64, 80, 16 * 1024**2)} if observed else {}
                        command(argv, current / "collector.log", seconds, repo, deadline, env,
                                watched=current, remaining=32 * 1024**2, **options)
                finally:
                    if data is not None:
                        write(current / "parent-cleanup.json", {"removed": not os.path.lexists(data)})
                row.update(status="passed", reason=None)
            finally:
                row["finished_micros"] = str(time.monotonic_ns() // 1000)
                row["host_after"], row["cgroup_after"] = host(), cgroup()
                if observed:
                    row["host_after"]["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
                for name, filename in (("raw", "recovery.json" if recovery else "budget.json" if budget else "cache.json" if cache else "cold.json" if cold else "candidate.json"), ("process", "collector.log.process.json"),
                                       ("log", "collector.log"), ("cleanup", "parent-cleanup.json")):
                    if (current / filename).is_file():
                        row[name] = legacy.ref(current / filename, output)
                write(output / "suite.json", suite)
        suite.update(status="passed", reason=None)
    except BaseException as error:
        write(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
    finally:
        suite["elapsed_nanos"] = str(time.monotonic_ns() - began)
        suite["runner_source_after"] = source(repo)
        suite["artifacts"] = scan(output)
        if generic and sum(int(row["bytes"]) for row in suite["artifacts"]) > maximum_bytes:
            suite.update(status="failed", reason="collection-failed")
        write(output / "suite.json", suite)
    from .evidence import validate_suite
    result = validate_suite(output / "suite.json")
    write(output / "aggregate.json", result)
    return 0 if result["population_complete"] and result["status"] != "failed" else 1


def inventory(output):
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_symlink():
            raise ValueError("backend-evidence-symlink")
        if path.is_file() and path.name not in ("suite.json", "aggregate.json"):
            rows.append(legacy.ref(path, output))
    if len(rows) > 4096 or sum(int(row["bytes"]) for row in rows) > 2 * 1024**3:
        raise ValueError("backend-retained-evidence-bound")
    return rows
