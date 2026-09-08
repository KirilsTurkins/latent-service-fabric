"""Run only prebuilt lookup probes, reusing the established owned sampler."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import time

from tools.artifact_identity_runner.files import fingerprint, reference
from tools.artifact_identity_runner.helpers import command
from tools.artifact_identity_runner.run import collect as collect_probe
from tools.optimization_revision_runner.build import source
from tools.optimization_revision_runner.collect import write
from tools.optimization_runner.cgroups import cgroup
from tools.phase1_measurement_environment import host
from tools.optimization_evidence.common import read_json
from . import builds, model
from .files import Artifacts, inventory


def tool(name, output, deadline):
    found = shutil.which(name)
    if found is None:
        raise ValueError("lookup-required-tool-missing:" + name)
    executable = Path(found).resolve(strict=True)
    checksum = fingerprint(executable)[0]
    path = output / "tools" / (name + ".log")
    path.parent.mkdir(exist_ok=True)
    owner = command([str(executable), "--version"], path, 15, output, deadline, maximum=65536)
    return {"path": str(executable), "sha256": checksum, "version": path.read_text().strip(),
            "log": reference(path, output), "process": owner}


def execute(args, repo):
    if platform.system() != "Linux":
        raise ValueError("lookup-collection-requires-linux")
    if any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("lookup-inherited-allocation-override")
    path = args.builds.resolve()
    output = path.parent
    if (output / "suite.json").exists() or (output / "runs").exists():
        raise ValueError("lookup-output-already-measured")
    build = read_json(path)
    binaries = {item["executables"]["lookup"]["path"] for item in build["builds"].values()}
    builds.validate(build, Artifacts(output, inventory(output), binaries), args.profile, "lookup")
    initial_source = source(repo)
    if initial_source != build["harness"]["source"] or initial_source["clean"] is not True:
        raise ValueError("lookup-runner-source-is-not-clean-harness")
    began = time.monotonic_ns()
    deadline = began + 3600 * 10**9
    suite = {"schema": "latent.optimization.cache-lookup-suite.v1", "profile": args.profile,
             "plan": model.suite_plan(args.profile), "builds": reference(path, output),
             "runner_source": initial_source, "runner_source_after": None,
             "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0",
             "tools": {}, "symbols": {}, "runs": [], "artifacts": []}
    write(output / "suite.json", suite)
    try:
        for name in ("heaptrack", "heaptrack_print", "zstd", "nm"):
            suite["tools"][name] = tool(name, output, deadline)
        if "1.4.0" not in suite["tools"]["heaptrack"]["version"]:
            raise ValueError("lookup-unsupported-heaptrack-version")
        for variant, value in build["builds"].items():
            binary = value["executables"]["lookup"]
            log = output / "builds" / variant / "symbols.log"
            argv = [suite["tools"]["nm"]["path"], "--defined-only", "--demangle", str(output / binary["path"])]
            owner = command(argv, log, 120, output, deadline, maximum=16 * 1024**2)
            suite["symbols"][variant] = {"command": argv, "process": owner, "log": reference(log, output)}
        (output / "plans").mkdir()
        (output / "identities").mkdir()
        for repetition, variant, mode, capacity, pattern in model.population(args.profile):
            if sum(int(row["bytes"]) for row in inventory(output)) + 256 * 1024**2 > 1024**3:
                raise ValueError("lookup-output-reservation-bound")
            name = f"pair-{repetition:02}-{variant}-{capacity}-{pattern}-{mode}"
            directory = output / "runs" / name
            selected = model.plan(args.profile, repetition, variant, mode, capacity, pattern)
            plan_path, identity_path = output / "plans" / (name + ".json"), output / "identities" / (name + ".json")
            before = host()
            before["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
            identity = builds.identity(build, variant, before)
            write(plan_path, selected)
            write(identity_path, identity)
            binary = build["builds"][variant]["executables"]["lookup"]
            argv = [str(output / binary["path"]), "--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
            if mode == "allocation":
                argv = [suite["tools"]["heaptrack"]["path"], "--output", str(directory / "heaptrack"), *argv]
            row = {"repetition": repetition, "variant": variant, "capacity": capacity, "pattern": pattern, "mode": mode,
                   "status": "failed", "reason": "collector-failed", "command": argv,
                   "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                   "plan": reference(plan_path, output), "identity": reference(identity_path, output),
                   "ready": None, "result": None, "trace": None, "process": None, "probe_process": None,
                   "resources": None, "cpu": None, "profile_refs": None, "log": None,
                   "host_before": before, "host_after": None, "cgroup_before": cgroup(), "cgroup_after": None}
            suite["runs"].append(row)
            write(output / "suite.json", suite)
            try:
                environment = dict(os.environ, LSF_CACHE_LOOKUP_PLAN=str(plan_path),
                                   LSF_CACHE_LOOKUP_IDENTITY=str(identity_path), LSF_CACHE_LOOKUP_OUTPUT=str(directory))
                # Lookup setup is replayed from the strict plan, exact trace and
                # cache snapshots. There is no artifact fixture to warm.
                collect_probe(row, directory, binary, None, output, deadline,
                              suite["tools"]["heaptrack_print"]["path"], suite["tools"]["zstd"]["path"], environment)
            except BaseException:
                row.update(status="failed", reason="collector-failed")
                raise
            finally:
                row.pop("warmup", None)
                row["finished_micros"] = str(time.monotonic_ns() // 1000)
                row["host_after"], row["cgroup_after"] = host(), cgroup()
                row["host_after"]["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
                if (directory / "trace.bin").is_file():
                    row["trace"] = reference(directory / "trace.bin", output)
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
