"""Strict full graph replay through the existing source/process/profile validators."""
from pathlib import Path

from tools.artifact_identity_evidence.runs import allocation, probe_resources
from tools.optimization_cache_lookup.evidence import host_controls, tools
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import DOCUMENT_BYTES, fields, hash_file, integer, read_json, require, uint, verify_artifact
from tools.optimization_evidence.resources import cgroup, process
from tools.optimization_revision_evidence.identity import source
from . import allocations, builds, events, model


def run(row, selected, suite, build, artifacts):
    binary = build["builds"][row["variant"]]["executables"]["scheduler"]
    command = row["command"]
    prefix = 3 if row["mode"] == "allocation" else 0
    require(isinstance(command, list) and len(command) == 6 + prefix and all(isinstance(item, str) for item in command),
            "scheduler-command-shape")
    require(command[prefix].endswith("/" + binary["path"])
            and command[prefix + 1:] == ["--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
            "scheduler-collector-command")
    if prefix:
        require(command[:2] == [suite["tools"]["heaptrack"]["path"], "--output"]
                and command[2] == command[prefix].removesuffix(binary["path"]) + row["log"]["path"].removesuffix("probe.log") + "heaptrack",
                "scheduler-crossed-profiler-command")
    key, memory = probe_resources(row, binary, suite["tools"])
    ready, complete = events.parse(row, selected, artifacts)
    from .parse import parse
    summary = parse(artifacts.json(row["raw"], model.MAX_RAW_BYTES), selected, artifacts.json(row["identity"]),
                    row["probe_process"]["process_id"], row["plan"]["sha256"], row["identity"]["sha256"])
    require(uint(ready["elapsed_nanos"]) + 100_000_000 <= uint(summary["started_nanos"])
            <= uint(summary["finished_nanos"]) <= uint(complete["elapsed_nanos"]), "scheduler-raw-event-clock")
    metrics, attribution = {}, None
    if row["mode"] == "normal":
        require(row["profile_refs"] is None, "scheduler-profile-in-normal-run")
        cpu = fields(row["cpu"], "scope user_micros system_micros")
        require(cpu["scope"] == "whole-owned-process-rusage-children", "scheduler-whole-process-cpu-scope")
        metrics = {"whole_process_cpu_micros": str(uint(cpu["user_micros"]) + uint(cpu["system_micros"])),
                   "normal_kernel_high_water_rss_bytes": str(uint(memory["kernel_high_water_rss_bytes"])),
                   "normal_completion_rss_bytes": str(uint(memory["completion"]["rss_bytes"])),
                   "normal_maximum_observed_rss_bytes": str(uint(memory["maximum_observed_rss_bytes"]))}
    else:
        require(row["cpu"] is None, "scheduler-profiled-cpu-is-not-normal")
        whole = allocation(row, suite, artifacts)
        attribution = allocations.attribute(row, binary, suite["symbols"][row["variant"]], suite["tools"]["nm"], artifacts, whole)
        metrics = {"whole_process_" + name: whole[name] for name in
                   ("allocation_count", "allocated_bytes", "peak_live_bytes", "remaining_live_bytes", "remaining_allocations")}
        if attribution["status"] == "available":
            metrics["selected_frame"] = attribution["statistics"]
    return key, {"raw_summary": summary, "metrics": metrics, "allocation_attribution": attribution,
                 "raw": row["raw"], "process_identity": {"process_id": key[0], "start_time_ticks": key[1]}}


def validate_suite(path):
    path = Path(path)
    checksum = hash_file(path, DOCUMENT_BYTES)
    suite = read_json(path)
    require(hash_file(path, DOCUMENT_BYTES) == checksum, "scheduler-suite-changed-during-read")
    fields(suite, "schema profile plan builds runner_source runner_source_after status reason elapsed_nanos tools symbols runs artifacts")
    require(suite["schema"] == model.PREFIX + "suite.v1" and suite["plan"] == model.suite_plan(suite["profile"]),
            "scheduler-suite-schema-or-plan")
    # Canonical comparison closes bool/int equality in the fixed plan.
    from tools.optimization_evidence.common import canonical
    require(canonical(suite["plan"]) == canonical(model.suite_plan(suite["profile"])), "scheduler-suite-plan-types")
    require(suite["status"] in ("passed", "failed")
            and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"), "scheduler-suite-status")
    elapsed = uint(suite["elapsed_nanos"])
    require(elapsed <= (suite["plan"]["suite_timeout_seconds"] + 5) * 10**9, "scheduler-suite-wall-bound")
    source(suite["runner_source"])
    require(suite["runner_source"] == suite["runner_source_after"], "scheduler-harness-source-changed")
    build = read_json(verify_artifact(path.parent, suite["builds"], DOCUMENT_BYTES))
    artifacts = Artifacts(path.parent, suite["artifacts"])
    artifacts.path(suite["builds"])
    builds.validate(build, artifacts, suite["profile"])
    require(build["harness"]["source"] == suite["runner_source"], "scheduler-harness-build-crossed")
    require({row["path"] for row in inventory(path.parent)} == set(artifacts.rows), "scheduler-unregistered-evidence-file")
    tools(suite["tools"], artifacts, suite["status"] == "passed" or bool(suite["runs"]))
    require(isinstance(suite["symbols"], dict) and set(suite["symbols"]) <= set(model.VARIANTS), "scheduler-symbol-proof-set")
    require(not suite["runs"] or set(suite["symbols"]) == set(model.VARIANTS), "scheduler-symbol-proof-missing")
    for variant, proof in suite["symbols"].items():
        allocations.symbol_proof(proof, build["builds"][variant]["executables"]["scheduler"], suite["tools"]["nm"], artifacts)
    expected = list(model.population(suite["profile"]))
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= len(expected), "scheduler-run-count")
    records, owners, previous, stable_host, stable_cgroup = [], set(), 0, None, None
    failed = False
    for ordinal, row in enumerate(suite["runs"]):
        fields(row, "ordinal variant case mode status reason command started_micros finished_micros plan identity ready result raw "
                    "process probe_process resources cpu profile_refs log host_before host_after cgroup_before cgroup_after")
        require(integer(row["ordinal"], 0, 13) == ordinal, "scheduler-run-ordinal")
        selected = expected[ordinal]
        require(all(row[key] == selected[key] for key in ("variant", "case", "mode")), "scheduler-missing-duplicate-or-reordered-cell")
        require(canonical(artifacts.json(row["plan"])) == canonical(selected), "scheduler-run-plan-changed")
        require(artifacts.json(row["identity"]) == builds.identity(build, row["variant"], row["host_before"]), "scheduler-run-identity-crossed")
        start, finish = uint(row["started_micros"]), uint(row["finished_micros"])
        require(previous <= start <= finish and (finish - start) * 1000 <= elapsed, "scheduler-overlapping-or-unbounded-processes")
        previous = finish
        before, after = host_controls(row["host_before"]), host_controls(row["host_after"])
        stable_host = before if stable_host is None else stable_host
        require(before == after == stable_host, "scheduler-host-controls-changed")
        for name in ("cgroup_before", "cgroup_after"):
            cgroup(row[name])
            controls = {key: row[name][key] for key in ("scope", "process_membership", "resolution", "cpu.max", "memory.max")}
            stable_cgroup = controls if stable_cgroup is None else stable_cgroup
            require(controls == stable_cgroup, "scheduler-cgroup-controls-changed")
        require(row["status"] in ("passed", "failed") and row["reason"] == (None if row["status"] == "passed" else "collector-failed"),
                "scheduler-run-status")
        summary = {key: row[key] for key in ("ordinal", "variant", "case", "mode", "status")}
        if row["status"] == "failed":
            failed = True
            summary["raw"] = row["raw"]
            if row["raw"] is not None:
                require(uint(row["raw"]["bytes"]) <= model.MAX_RAW_BYTES, "scheduler-failed-raw-bound")
                artifacts.path(row["raw"])
            if row["process"] is not None:
                binary = build["builds"][row["variant"]]["executables"]["scheduler"]
                executable = binary["sha256"] if row["mode"] == "normal" else suite["tools"]["heaptrack"]["sha256"]
                process(row["process"], "identity-" + row["mode"], executable)
                require(row["process"]["reaped"] is True and row["process"]["output_closed"] is True, "scheduler-failed-owner-not-cleaned")
        else:
            require(not failed, "scheduler-attempt-after-failed-child")
            key, result = run(row, selected, suite, build, artifacts)
            require(key not in owners, "scheduler-reused-probe-owner")
            owners.add(key)
            summary.update(result)
        records.append(summary)
    failed = failed or suite["status"] == "failed"
    complete = len(records) == len(expected) and not failed
    require(suite["status"] != "passed" or complete, "scheduler-passed-suite-hides-incomplete-population")
    from .aggregate import aggregate
    return aggregate(suite, checksum[0], build, records, complete, failed)
