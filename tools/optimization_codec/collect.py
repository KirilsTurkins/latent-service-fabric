"""Run fixed normal/profiled codec batches with existing owned supervision."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import time

from tools.artifact_identity_runner.files import reference
from tools.artifact_identity_runner.helpers import command
from tools.artifact_identity_runner.run import collect as collect_probe
from tools.optimization_revision_runner.build import source
from tools.optimization_revision_runner.collect import write
from tools.optimization_runner.cgroups import cgroup
from tools.phase1_measurement_environment import host
from tools.optimization_evidence.common import read_json
from . import builds, model
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_cache_lookup.collect import tool


def execute(args, repo):
    if platform.system() != "Linux":
        raise ValueError("codec-collection-requires-linux")
    if any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("codec-inherited-allocation-override")
    path = args.builds.resolve()
    output = path.parent
    if any(os.path.lexists(output / name) for name in ("suite.json", "aggregate.json", "runs")):
        raise ValueError("codec-output-already-measured")
    build = read_json(path)
    binaries = {item["executables"]["codec"]["path"] for item in build["builds"].values()}
    builds.validate(build, Artifacts(output, inventory(output), binaries), args.profile)
    initial_source = source(repo)
    if initial_source != build["harness"]["source"] or initial_source["clean"] is not True:
        raise ValueError("codec-runner-source-is-not-clean-harness")
    began = time.monotonic_ns()
    deadline = began + model.STAGE_SECONDS * 10**9
    suite = {"schema": model.SCHEMA, "profile": args.profile,
             "plan": model.suite_plan(args.profile), "builds": reference(path, output),
             "runner_source": initial_source, "runner_source_after": None,
             "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0",
             "tools": {}, "symbols": {}, "runs": [], "artifacts": []}
    write(output / "suite.json", suite)
    try:
        for name in ("heaptrack", "heaptrack_print", "zstd", "nm"):
            suite["tools"][name] = tool(name, output, deadline)
        if "1.4.0" not in suite["tools"]["heaptrack"]["version"]:
            raise ValueError("codec-unsupported-heaptrack-version")
        for variant, value in build["builds"].items():
            binary = value["executables"]["codec"]
            log = output / "builds" / variant / "symbols.log"
            argv = [suite["tools"]["nm"]["path"], "--defined-only", "--demangle", str(output / binary["path"])]
            owner = command(argv, log, 120, output, deadline, maximum=16 * 1024**2)
            raw_log = output / "builds" / variant / "symbols-raw.log"
            raw_argv = [suite["tools"]["nm"]["path"], "--defined-only", str(output / binary["path"])]
            raw_owner = command(raw_argv, raw_log, 120, output, deadline, maximum=16 * 1024**2)
            suite["symbols"][variant] = {"command": argv, "process": owner, "log": reference(log, output),
                                        "raw": {"command": raw_argv, "process": raw_owner, "log": reference(raw_log, output)}}
        (output / "plans").mkdir()
        (output / "identities").mkdir()
        for repetition, variant, mode, family in model.population(args.profile):
            if sum(int(row["bytes"]) for row in inventory(output)) + 256 * 1024**2 > 1024**3:
                raise ValueError("codec-output-reservation-bound")
            name = f"pair-{repetition:02}-{variant}-{family}-{mode}"
            directory = output / "runs" / name
            selected = model.plan(args.profile, repetition, variant, mode, family)
            plan_path, identity_path = output / "plans" / (name + ".json"), output / "identities" / (name + ".json")
            before = host()
            before["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
            identity = builds.identity(build, variant, before)
            write(plan_path, selected)
            write(identity_path, identity)
            binary = build["builds"][variant]["executables"]["codec"]
            argv = [str(output / binary["path"]), "--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
            if mode == "allocation":
                argv = [suite["tools"]["heaptrack"]["path"], "--output", str(directory / "heaptrack"), *argv]
            row = {"repetition": repetition, "variant": variant, "family": family, "mode": mode,
                   "status": "failed", "reason": "collector-failed", "command": argv,
                   "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                   "plan": reference(plan_path, output), "identity": reference(identity_path, output),
                   "ready": None, "result": None, "raw": None, "process": None, "probe_process": None,
                   "resources": None, "cpu": None, "profile_refs": None, "log": None,
                   "host_before": before, "host_after": None, "cgroup_before": cgroup(), "cgroup_after": None}
            suite["runs"].append(row)
            write(output / "suite.json", suite)
            try:
                environment = dict(os.environ, LSF_CODEC_PLAN=str(plan_path),
                                   LSF_CODEC_IDENTITY=str(identity_path), LSF_CODEC_OUTPUT=str(directory))
                # The collector creates the fixed codec input; no repository fixture is warmed.
                collect_probe(row, directory, binary, None, output, deadline,
                              suite["tools"]["heaptrack_print"]["path"], suite["tools"]["zstd"]["path"], environment,
                              normal_timeout=90, maximum_folded_bytes=model.MAX_FOLDED_BYTES)
            except BaseException:
                row.update(status="failed", reason="collector-failed")
                raise
            finally:
                row.pop("warmup", None)
                row["finished_micros"] = str(time.monotonic_ns() // 1000)
                row["host_after"], row["cgroup_after"] = host(), cgroup()
                row["host_after"]["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
                if (directory / "codec.json").is_file():
                    row["raw"] = reference(directory / "codec.json", output)
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
