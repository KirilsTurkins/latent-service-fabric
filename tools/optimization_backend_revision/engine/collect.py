"""Supervise the fixed five-owner matrix from a verified build-only directory."""
import os
from pathlib import Path
import platform
import tempfile
import time

from tools import run_optimization_benchmarks as legacy
from tools.artifact_identity_runner.helpers import DirectoryLimits, command
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import read_json
from tools.optimization_revision_runner.build import source
from tools.optimization_revision_runner.collect import write
from tools.optimization_runner.processes import cgroup
from tools.phase1_measurement_environment import host
from . import builds, model

RESERVATION_BYTES = 40 * 1024**2


def execute(args, repo):
    if platform.system() != "Linux":
        raise ValueError("engine-collection-requires-linux")
    build_path = args.builds.resolve()
    output = build_path.parent
    if any((output / name).exists() or (output / name).is_symlink()
           for name in ("suite.json", "aggregate.json", "runs")):
        raise ValueError("engine-build-root-already-measured")
    if any(os.environ.get(name) for name in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("engine-inherited-runtime-override")
    build = read_json(build_path)
    runner = source(repo)
    if not runner["clean"] or runner["commit"] != build["requested_refs"]["harness"]:
        raise ValueError("engine-clean-executed-harness-required")
    builds.validate(build, Artifacts(output, inventory(output)), args.profile)
    target = args.target_root.resolve()
    target.mkdir(parents=True, exist_ok=True)
    began = time.monotonic_ns()
    deadline = began + model.SUITE_SECONDS * 10**9
    suite = {"schema": model.SCHEMA, "profile": args.profile, "plan": model.suite_plan(args.profile),
             "builds": legacy.ref(build_path, output), "runner_source": runner, "runner_source_after": None,
             "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0", "runs": [], "artifacts": []}
    write(output / "suite.json", suite)
    try:
        for selection in model.population(args.profile):
            remaining = model.MAX_TOTAL_BYTES - sum(int(row["bytes"]) for row in inventory(output))
            if remaining < RESERVATION_BYTES:
                raise ValueError("engine-next-owner-reservation-bound")
            current = output / "runs" / model.run_id(selection)
            current.mkdir(parents=True, exist_ok=False)
            before = {**host(), "clock_ticks_per_second": os.sysconf("SC_CLK_TCK")}
            supplied = model.identity(build, selection["variant"], before)
            selected = model.plan(args.profile, **selection)
            write(current / "identity.json", supplied)
            write(current / "plan.json", selected)
            binary = output / build["builds"][selection["variant"]]["executables"]["backend"]["path"]
            argv = [str(binary), "--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
            row = {**selection, "status": "failed", "reason": "collector-failed", "command": argv,
                   "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                   "identity": legacy.ref(current / "identity.json", output), "plan": legacy.ref(current / "plan.json", output),
                   "process": None, "raw": None, "log": None, "cleanup": None,
                   "host_before": before, "host_after": None, "cgroup_before": cgroup(), "cgroup_after": None}
            suite["runs"].append(row)
            write(output / "suite.json", suite)
            try:
                data = None
                try:
                    with tempfile.TemporaryDirectory(prefix="engine-data-owned-", dir=target) as data:
                        env = dict(os.environ, LSF_PHASE1_COMPARISON_PLAN=str(current / "plan.json"),
                                   LSF_PHASE1_COMPARISON_IDENTITY=str(current / "identity.json"),
                                   LSF_PHASE1_COMPARISON_OUTPUT=str(current), LSF_PHASE1_COMPARISON_DATA_ROOT=data,
                                   LSF_ENGINE_FIXTURES=str(output / build["fixtures"]["path"]))
                        command(argv, current / "collector.log", model.MAX_SECONDS, repo, deadline, env,
                                maximum=1024**2, watched=current, remaining=RESERVATION_BYTES,
                                directory_limits=DirectoryLimits(2, 64, 80, model.MAX_DOCUMENT_BYTES))
                finally:
                    if data is not None:
                        write(current / "parent-cleanup.json", {"removed": not os.path.lexists(data)})
                row.update(status="passed", reason=None)
            finally:
                row["finished_micros"] = str(time.monotonic_ns() // 1000)
                row["host_after"] = {**host(), "clock_ticks_per_second": os.sysconf("SC_CLK_TCK")}
                row["cgroup_after"] = cgroup()
                for name, filename in (("raw", "engine.json"), ("process", "collector.log.process.json"),
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
        suite["artifacts"] = inventory(output)
        write(output / "suite.json", suite)
    from .evidence import validate_suite
    result = validate_suite(output / "suite.json")
    write(output / "aggregate.json", result)
    return 0 if result["population_complete"] and result["status"] != "failed" else 1
