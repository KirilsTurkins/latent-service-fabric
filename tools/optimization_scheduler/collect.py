"""Fixed scheduler probes using the existing owned process and Heaptrack helpers."""
import os
import platform
from pathlib import Path
import time

from tools.artifact_identity_runner.files import reference
from tools.artifact_identity_runner.helpers import command
from tools.artifact_identity_runner.run import collect as collect_probe
from tools.optimization_cache_lookup.collect import tool
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import canonical, read_json, require
from tools.optimization_revision_runner.build import source
from tools.optimization_revision_runner.collect import write
from tools.optimization_runner.cgroups import cgroup
from tools.phase1_measurement_environment import host
from . import builds, model


def execute(args, repo):
    require(platform.system() == "Linux", "scheduler-collection-requires-linux")
    require(not any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")),
            "scheduler-inherited-allocation-override")
    path = args.builds.resolve()
    output = path.parent
    require(not any((output / name).exists() for name in ("suite.json", "aggregate.json", "runs", "plans", "identities")),
            "scheduler-output-already-measured")
    build = builds.validate(read_json(path), Artifacts(output, inventory(output)), args.profile)
    initial = source(repo)
    require(initial == build["harness"]["source"] and initial["clean"] is True, "scheduler-runner-not-clean-harness")
    began = time.monotonic_ns()
    deadline = began + model.suite_plan(args.profile)["suite_timeout_seconds"] * 10**9
    suite = {"schema": model.PREFIX + "suite.v1", "profile": args.profile, "plan": model.suite_plan(args.profile),
             "builds": reference(path, output), "runner_source": initial, "runner_source_after": None,
             "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0", "tools": {},
             "symbols": {}, "runs": [], "artifacts": []}
    write(output / "suite.json", suite)
    try:
        for name in ("heaptrack", "heaptrack_print", "zstd", "nm"):
            suite["tools"][name] = tool(name, output, deadline)
        require("1.4.0" in suite["tools"]["heaptrack"]["version"], "scheduler-unsupported-heaptrack-version")
        for variant, value in build["builds"].items():
            binary = value["executables"]["scheduler"]
            log = output / "builds" / variant / "symbols.log"
            argv = [suite["tools"]["nm"]["path"], "--defined-only", "--demangle", str(output / binary["path"])]
            owner = command(argv, log, 120, output, deadline, maximum=16 * 1024**2)
            raw_log = log.with_name("symbols-raw.log")
            raw_argv = [suite["tools"]["nm"]["path"], "--defined-only", str(output / binary["path"])]
            raw_owner = command(raw_argv, raw_log, 120, output, deadline, maximum=16 * 1024**2)
            suite["symbols"][variant] = {"command": argv, "process": owner, "log": reference(log, output),
                                        "raw": {"command": raw_argv, "process": raw_owner, "log": reference(raw_log, output)}}
        (output / "plans").mkdir()
        (output / "identities").mkdir()
        for ordinal, selected in enumerate(model.population(args.profile)):
            require(sum(int(row["bytes"]) for row in inventory(output)) + 256 * 1024**2 <= model.MAX_TOTAL_BYTES,
                    "scheduler-output-reservation-bound")
            variant, mode = selected["variant"], selected["mode"]
            name = model.run_id(ordinal, selected)
            directory = output / "runs" / name
            plan_path, identity_path = output / "plans" / (name + ".json"), output / "identities" / (name + ".json")
            before = host()
            before["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
            write(plan_path, selected)
            write(identity_path, builds.identity(build, variant, before))
            binary = build["builds"][variant]["executables"]["scheduler"]
            argv = [str(output / binary["path"]), "--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
            if mode == "allocation":
                argv = [suite["tools"]["heaptrack"]["path"], "--output", str(directory / "heaptrack"), *argv]
            row = {"ordinal": ordinal, "variant": variant, "case": selected["case"], "mode": mode,
                   "status": "failed", "reason": "collector-failed", "command": argv,
                   "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                   "plan": reference(plan_path, output), "identity": reference(identity_path, output),
                   "ready": None, "result": None, "raw": None, "process": None, "probe_process": None,
                   "resources": None, "cpu": None, "profile_refs": None, "log": None,
                   "host_before": before, "host_after": None, "cgroup_before": cgroup(), "cgroup_after": None}
            suite["runs"].append(row)
            write(output / "suite.json", suite)
            try:
                environment = dict(os.environ, LSF_SCHEDULER_PLAN=str(plan_path), LSF_SCHEDULER_IDENTITY=str(identity_path),
                                   LSF_SCHEDULER_OUTPUT=str(directory))
                collect_probe(row, directory, binary, None, output, deadline, suite["tools"]["heaptrack_print"]["path"],
                              suite["tools"]["zstd"]["path"], environment, normal_timeout=60,
                              maximum_folded_bytes=model.MAX_FOLDED_BYTES)
            except BaseException:
                row.update(status="failed", reason="collector-failed")
                raise
            finally:
                row.pop("warmup", None)
                row["finished_micros"] = str(time.monotonic_ns() // 1000)
                row["host_after"], row["cgroup_after"] = host(), cgroup()
                row["host_after"]["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
                raw = directory / "scheduler.json"
                if raw.is_file():
                    require(raw.stat().st_size <= model.MAX_RAW_BYTES, "scheduler-raw-byte-bound")
                    row["raw"] = reference(raw, output)
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
    require(len(canonical(result)) + 1 <= model.MAX_AGGREGATE_BYTES, "scheduler-aggregate-byte-bound")
    write(output / "aggregate.json", result)
    return 0 if result["completed_paired_run"] and (args.profile == "smoke" or result["acceptance_qualified"]) else 1
