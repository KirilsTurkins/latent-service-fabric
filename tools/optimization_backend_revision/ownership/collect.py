"""Fixed ownership children over one already validated exact-source build graph."""
import os
from pathlib import Path
import platform
import tempfile
import time

from tools.artifact_identity_runner.files import reference
from tools.artifact_identity_runner.helpers import command
from tools.artifact_identity_runner.run import collect as collect_probe
from tools.optimization_cache_lookup.collect import tool
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import read_json
from tools.optimization_revision_runner.build import source
from tools.optimization_revision_runner.collect import write
from tools.optimization_runner.cgroups import cgroup
from tools.phase1_measurement_environment import host
from . import builds, model


def execute(args, repo):
    if platform.system() != "Linux":
        raise ValueError("ownership-collection-requires-linux")
    if any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("ownership-inherited-allocation-override")
    path = args.builds.resolve()
    output = path.parent
    if any(os.path.lexists(output / name) for name in ("suite.json", "aggregate.json", "runs")):
        raise ValueError("ownership-output-already-measured")
    build = read_json(path)
    binaries = {item["executables"]["backend"]["path"] for item in build["builds"].values()}
    builds.validate(build, Artifacts(output, inventory(output), binaries), args.profile)
    initial = source(repo)
    if initial != build["harness"]["source"] or initial["clean"] is not True:
        raise ValueError("ownership-runner-not-clean-harness")
    target = args.target_root.resolve()
    target.mkdir(parents=True, exist_ok=True)
    began = time.monotonic_ns()
    deadline = began + model.STAGE_SECONDS * 10**9
    suite = {"schema": model.SCHEMA, "profile": args.profile, "plan": model.suite_plan(args.profile),
             "builds": reference(path, output), "runner_source": initial, "runner_source_after": None,
             "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0",
             "tools": {}, "symbols": {}, "runs": [], "artifacts": []}
    save = lambda: write(output / "suite.json", suite)
    save()
    try:
        for name in ("heaptrack", "heaptrack_print", "zstd", "nm"):
            suite["tools"][name] = tool(name, output, deadline)
        if "1.4.0" not in suite["tools"]["heaptrack"]["version"]:
            raise ValueError("ownership-unsupported-heaptrack")
        for variant, value in build["builds"].items():
            binary = value["executables"]["backend"]
            proof = {}
            for demangle in (True, False):
                argv = [suite["tools"]["nm"]["path"], "--defined-only", *(["--demangle"] if demangle else []),
                        str(output / binary["path"])]
                log = output / "builds" / variant / ("symbols.log" if demangle else "symbols-raw.log")
                owner = command(argv, log, 120, output, deadline, maximum=16 * 1024**2)
                row = {"command": argv, "process": owner, "log": reference(log, output)}
                if demangle:
                    proof.update(row)
                else:
                    proof["raw"] = row
            suite["symbols"][variant] = proof
        (output / "plans").mkdir()
        (output / "identities").mkdir()
        for repetition, variant, mode, shape in model.population(args.profile):
            if sum(int(row["bytes"]) for row in inventory(output)) + 256 * 1024**2 > model.MAX_TOTAL_BYTES:
                raise ValueError("ownership-output-reservation-bound")
            name = f"pair-{repetition:02}-{variant}-{mode}" + ("-" + shape if shape else "")
            directory = output / "runs" / name
            selected = model.plan(args.profile, repetition, mode, shape)
            plan_path, identity_path = output / "plans" / (name + ".json"), output / "identities" / (name + ".json")
            before = host()
            before["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
            write(plan_path, selected)
            write(identity_path, model.identity(build, variant, before))
            binary = build["builds"][variant]["executables"]["backend"]
            argv = [str(output / binary["path"]), "--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
            if mode == "allocation":
                argv = [suite["tools"]["heaptrack"]["path"], "--output", str(directory / "heaptrack"), *argv]
            row = {"repetition": repetition, "variant": variant, "mode": mode, "shape": shape,
                   "status": "failed", "reason": "collector-failed", "command": argv,
                   "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
                   "plan": reference(plan_path, output), "identity": reference(identity_path, output),
                   "ready": None, "result": None, "raw": None, "process": None, "probe_process": None,
                   "resources": None, "cpu": None, "profile_refs": None, "log": None, "cleanup": None,
                   "host_before": before, "host_after": None, "cgroup_before": cgroup(), "cgroup_after": None}
            suite["runs"].append(row)
            save()
            data = None
            try:
                with tempfile.TemporaryDirectory(prefix="ownership-data-", dir=target) as data:
                    environment = dict(os.environ, LSF_PHASE1_COMPARISON_PLAN=str(plan_path),
                                       LSF_PHASE1_COMPARISON_IDENTITY=str(identity_path),
                                       LSF_PHASE1_COMPARISON_OUTPUT=str(directory), LSF_PHASE1_COMPARISON_DATA_ROOT=data,
                                       LSF_OWNERSHIP_FIXTURES=str(output / "ownership-fixtures.json"))
                    collect_probe(row, directory, binary, None, output, deadline,
                                  suite["tools"]["heaptrack_print"]["path"], suite["tools"]["zstd"]["path"],
                                  environment, normal_timeout=90)
            except BaseException:
                row.update(status="failed", reason="collector-failed")
                raise
            finally:
                if data is not None:
                    write(directory / "parent-cleanup.json", {"removed": not os.path.lexists(data)})
                    row["cleanup"] = reference(directory / "parent-cleanup.json", output)
                row["finished_micros"] = str(time.monotonic_ns() // 1000)
                row["host_after"], row["cgroup_after"] = host(), cgroup()
                row["host_after"]["clock_ticks_per_second"] = os.sysconf("SC_CLK_TCK")
                if (directory / "ownership.json").is_file():
                    row["raw"] = reference(directory / "ownership.json", output)
                save()
        suite.update(status="passed", reason=None)
    except BaseException as error:
        write(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
    finally:
        suite["elapsed_nanos"] = str(time.monotonic_ns() - began)
        suite["runner_source_after"] = source(repo)
        suite["artifacts"] = inventory(output)
        save()
    from .evidence import validate_suite
    aggregate = validate_suite(output / "suite.json")
    write(output / "aggregate.json", aggregate)
    return 0 if aggregate["population_complete"] and aggregate["status"] != "failed" else 1
