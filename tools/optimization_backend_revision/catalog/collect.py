"""Sequential same-root initial/reopen owners, then sixteen tiny profiles."""
import os
from pathlib import Path
import platform
import tempfile
import time

from tools.artifact_identity_runner.files import reference
from tools.artifact_identity_runner.helpers import DirectoryLimits, command
from tools.artifact_identity_runner.run import collect as collect_probe
from tools.optimization_cache_lookup.collect import tool
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import read_json, require
from tools.optimization_revision_runner.build import source
from tools.optimization_revision_runner.collect import write
from tools.optimization_runner.cgroups import cgroup
from tools.phase1_measurement_environment import host
from . import builds, data, model

NORMAL_RESERVATION = 64 * 1024**2
PROFILE_RESERVATION = 256 * 1024**2


def _host():
    return {**host(), "clock_ticks_per_second": os.sysconf("SC_CLK_TCK")}


def _tools(suite, build, output, deadline):
    for name in ("heaptrack", "heaptrack_print", "zstd", "nm"):
        suite["tools"][name] = tool(name, output, deadline)
    require("1.4.0" in suite["tools"]["heaptrack"]["version"], "catalog-unsupported-heaptrack")
    for variant, value in build["builds"].items():
        binary, proof = value["executables"]["backend"], {}
        for demangle in (True, False):
            argv = [suite["tools"]["nm"]["path"], "--defined-only", *(["--demangle"] if demangle else []),
                    str(output / binary["path"])]
            log = output / "builds" / variant / ("symbols.log" if demangle else "symbols-raw.log")
            owner = command(argv, log, model.REPORT_SECONDS, output, deadline, maximum=16 * 1024**2)
            row = {"command": argv, "process": owner, "log": reference(log, output)}
            if demangle:
                proof.update(row)
            else:
                proof["raw"] = row
        suite["symbols"][variant] = proof


def _child(selection, args, repo, build, suite, output, root, group, marker_ref, deadline, save,
           reopen_ref=None):
    current = output / "runs" / model.run_id(selection)
    current.mkdir(parents=True, exist_ok=False)
    selected = model.plan(args.profile, **selection)
    before = _host()
    write(current / "plan.json", selected)
    write(current / "identity.json", model.identity(build, selection["variant"], before))
    binary = build["builds"][selection["variant"]]["executables"]["backend"]
    argv = [str(output / binary["path"]), "--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"]
    profiled = selection["mode"] == "allocation"
    if profiled:
        argv = [suite["tools"]["heaptrack"]["path"], "--output", str(current / "heaptrack"), *argv]
    row = {**selection, "status": "failed", "reason": "collector-failed", "command": argv,
           "started_micros": str(time.monotonic_ns() // 1000), "finished_micros": None,
           "plan": reference(current / "plan.json", output), "identity": reference(current / "identity.json", output),
           "data_owner": marker_ref, "reopen_input": reopen_ref, "post_exit": None, "cleanup": None,
           "process": None, "raw": None, "log": None, "ready": None, "result": None,
           "probe_process": None, "resources": None, "cpu": None, "profile_refs": None,
           "host_before": before, "host_after": None, "cgroup_before": cgroup(), "cgroup_after": None}
    suite["runs"].append(row)
    save()
    env = dict(os.environ, LSF_PHASE1_COMPARISON_PLAN=str(current / "plan.json"),
               LSF_PHASE1_COMPARISON_IDENTITY=str(current / "identity.json"),
               LSF_PHASE1_COMPARISON_OUTPUT=str(current), LSF_PHASE1_COMPARISON_DATA_ROOT=str(root),
               LSF_ECHO_COMPONENT=str(output / build["harness"]["echo"]["component"]["path"]))
    env.pop("LSF_CATALOG_REOPEN_RECEIPT", None)
    if reopen_ref is not None:
        env["LSF_CATALOG_REOPEN_RECEIPT"] = str(output / reopen_ref["path"])
    remaining = model.MAX_TOTAL_BYTES - sum(int(item["bytes"]) for item in inventory(output))
    require(remaining >= (PROFILE_RESERVATION if profiled else NORMAL_RESERVATION), "catalog-next-owner-reservation-bound")
    try:
        if profiled:
            # The common profile owner creates its output directory itself.
            # Retained plan/identity stay in this already-created directory, so
            # use a child containing only the bounded profiler/raw outputs.
            probe_dir = current / "probe"
            row["command"][2] = str(probe_dir / "heaptrack")
            env["LSF_PHASE1_COMPARISON_OUTPUT"] = str(probe_dir)
            collect_probe(row, probe_dir, binary, None, output, deadline,
                          suite["tools"]["heaptrack_print"]["path"], suite["tools"]["zstd"]["path"], env,
                          normal_timeout=90, maximum_folded_bytes=model.MAX_FOLDED_BYTES)
        else:
            row["process"] = command(argv, current / "collector.log", model.run_seconds(args.profile, selection["mode"]),
                repo, deadline, env, maximum=model.MAX_LOG_BYTES, watched=current, remaining=NORMAL_RESERVATION,
                directory_limits=DirectoryLimits(1, 32, 40, model.MAX_DOCUMENT_BYTES))
            row.update(status="passed", reason=None)
    finally:
        row["finished_micros"] = str(time.monotonic_ns() // 1000)
        row["host_after"], row["cgroup_after"] = _host(), cgroup()
        raw_dir = current / "probe" if profiled else current
        if (raw_dir / "catalog.json").is_file():
            row["raw"] = reference(raw_dir / "catalog.json", output)
        if not profiled:
            for key, filename in (("process", "collector.log.process.json"), ("log", "collector.log")):
                if (current / filename).is_file():
                    row[key] = read_json(current / filename) if key == "process" else reference(current / filename, output)
        save()
    if selection["mode"] == "initial":
        require(row["raw"] is not None and row["process"] is not None, "catalog-initial-receipt-missing")
        receipt = data.post_exit(root, read_json(output / marker_ref["path"]), row["process"], row["raw"])
        write(group / "initial-post-exit.json", receipt)
        row["post_exit"] = reference(group / "initial-post-exit.json", output)
        save()
    return row


def _group(selections, args, repo, build, suite, output, target, deadline, save):
    first = selections[0]
    group = output / "data-owners" / model.run_id(first)
    group.mkdir(parents=True, exist_ok=False)
    value = data.marker(first, build["builds"][first["variant"]]["source"]["commit"])
    write(group / "owner.json", value)
    marker_ref = reference(group / "owner.json", output)
    previous_count = len(suite["runs"])
    root = identity = None
    closed = None
    try:
        root = Path(tempfile.mkdtemp(prefix="catalog-data-owned-", dir=target))
        identity = data.create(root, value)
        write(group / "filesystem-reserve.json", data.reserve(root, args.profile == "full" and first["mode"] == "initial"))
        reopen_ref = None
        for selection in selections:
            row = _child(selection, args, repo, build, suite, output, root, group, marker_ref, deadline, save, reopen_ref)
            require(data.identity(root, value) == identity, "catalog-data-root-replaced")
            if selection["mode"] == "initial":
                reopen_ref = row["post_exit"]
    finally:
        if root is not None:
            try:
                closed = data.close_tree(root)
                data.remove_owned(root, target, identity)
            finally:
                write(group / "cleanup.json", {"removed": not os.path.lexists(root), "data_identity": identity,
                    "sequence_ordinals": [row["sequence_ordinal"] for row in selections], "close_walk": closed,
                    "filesystem_reserve": reference(group / "filesystem-reserve.json", output)
                    if (group / "filesystem-reserve.json").is_file() else None})
                ref = reference(group / "cleanup.json", output)
                for row in suite["runs"][previous_count:]:
                    row["cleanup"] = ref
        save()


def execute(args, repo):
    if platform.system() != "Linux":
        raise ValueError("catalog-collection-requires-linux")
    require(not any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")),
            "catalog-inherited-runtime-override")
    path = args.builds.resolve()
    output = path.parent
    require(not any(os.path.lexists(output / name) for name in ("suite.json", "aggregate.json", "runs", "data-owners")),
            "catalog-build-root-already-measured")
    build = read_json(path)
    binaries = {item["executables"]["backend"]["path"] for item in build["builds"].values()}
    builds.validate(build, Artifacts(output, inventory(output), binaries), args.profile)
    initial = source(repo)
    require(initial == build["harness"]["source"] and initial["clean"] is True, "catalog-clean-executed-harness-required")
    target = args.target_root.resolve()
    target.mkdir(parents=True, exist_ok=True)
    began = time.monotonic_ns()
    suite = {"schema": model.SCHEMA, "profile": args.profile, "plan": model.suite_plan(args.profile),
             "builds": reference(path, output), "runner_source": initial, "runner_source_after": None,
             "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0",
             "normal_elapsed_nanos": "0", "allocation_elapsed_nanos": "0", "tools": {}, "symbols": {},
             "runs": [], "artifacts": []}
    save = lambda: write(output / "suite.json", suite)
    save()
    allocation_began = None
    try:
        rows = model.population(args.profile)
        ordinary = [row for row in rows if row["mode"] != "allocation"]
        normal_deadline = began + model.normal_seconds(args.profile) * 10**9
        for offset in range(0, len(ordinary), 2):
            _group(ordinary[offset:offset + 2], args, repo, build, suite, output, target, normal_deadline, save)
        suite["normal_elapsed_nanos"] = str(time.monotonic_ns() - began)
        allocation_began = time.monotonic_ns()
        allocation_deadline = allocation_began + model.ALLOCATION_SECONDS * 10**9
        _tools(suite, build, output, allocation_deadline)
        for selection in rows[len(ordinary):]:
            _group([selection], args, repo, build, suite, output, target, allocation_deadline, save)
        suite.update(status="passed", reason=None)
    except BaseException as error:
        write(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
    finally:
        ended = time.monotonic_ns()
        if allocation_began is None:
            suite["normal_elapsed_nanos"] = str(ended - began)
        else:
            suite["allocation_elapsed_nanos"] = str(ended - allocation_began)
        suite["elapsed_nanos"] = str(ended - began)
        suite["runner_source_after"] = source(repo)
        suite["artifacts"] = inventory(output)
        save()
    from .evidence import validate_suite
    result = validate_suite(output / "suite.json")
    write(output / "aggregate.json", result)
    return 0 if result["population_complete"] and result["status"] != "failed" else 1
