"""Strict replay of all normal/profiled lookup attempts and paired controls."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from tools.artifact_identity_evidence.identity import helper
from tools.artifact_identity_evidence.runs import allocation, probe_resources
from tools.optimization_evidence.common import (
    DOCUMENT_BYTES, digest, fields, hash_file, integer, read_json, require, text, uint, verify_artifact,
)
from tools.optimization_evidence.resources import cgroup, process
from tools.optimization_revision_evidence.identity import environment, source
from . import allocations, builds, events, model
from .files import Artifacts, inventory


def tools(value, artifacts, required):
    require(isinstance(value, dict) and set(value) <= {"heaptrack", "heaptrack_print", "zstd", "nm"}, "lookup-tool-set")
    require(not required or len(value) == 4, "lookup-required-tool-missing")
    for name, row in value.items():
        fields(row, "path sha256 version log process")
        require(text(row["path"]).startswith("/"), "lookup-tool-path")
        digest(row["sha256"])
        text(row["version"], 65536)
        helper(row["process"], row["sha256"], row["log"], artifacts)
        require(artifacts.path(row["log"]).read_text().strip() == row["version"], "lookup-tool-version-not-bound")
        if name == "heaptrack":
            require("1.4.0" in row["version"], "lookup-unsupported-profiler")


def host_controls(value):
    require(isinstance(value, dict) and "clock_ticks_per_second" in value, "lookup-missing-host-tick-rate")
    ticks = integer(value["clock_ticks_per_second"], 1, 1_000_000)
    stable = environment({key: item for key, item in value.items() if key != "clock_ticks_per_second"})
    return dict(stable, clock_ticks_per_second=ticks)


def run(row, selected, suite, build, artifacts):
    binary = build["builds"][row["variant"]]["executables"]["lookup"]
    command = row["command"]
    prefix = 3 if row["mode"] == "allocation" else 0
    require(isinstance(command, list) and len(command) == 6 + prefix and all(isinstance(x, str) for x in command),
            "lookup-command-shape")
    require(command[prefix].endswith("/" + binary["path"])
            and command[prefix + 1:] == ["--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
            "lookup-changed-collector-command")
    if prefix:
        require(command[:2] == [suite["tools"]["heaptrack"]["path"], "--output"]
                and command[2] == command[prefix].removesuffix(binary["path"]) + row["log"]["path"].removesuffix("probe.log") + "heaptrack",
                "lookup-crossed-profiler-command")
    key, memory = probe_resources(row, binary, suite["tools"])
    result = events.parse(row, selected, artifacts)
    require(uint(result["elapsed_nanos"]) <= (uint(row["finished_micros"]) - uint(row["started_micros"])) * 1000,
            "lookup-timing-exceeds-owned-process")
    measured = selected["measured_hits"]
    metrics, attribution = {}, None
    if row["mode"] == "normal":
        require(row["profile_refs"] is None, "lookup-profile-in-normal-run")
        cpu = fields(row["cpu"], "scope user_micros system_micros")
        require(cpu["scope"] == "whole-owned-process-rusage-children", "lookup-whole-process-cpu-scope")
        whole_cpu = uint(cpu["user_micros"]) + uint(cpu["system_micros"])
        thread_cpu = uint(result["cpu"]["after_nanos"]) - uint(result["cpu"]["before_nanos"])
        require(thread_cpu <= (whole_cpu + 2) * 1000, "lookup-thread-cpu-exceeds-whole-child")
        metrics = {"batch_elapsed_nanos_per_get": Decimal(result["elapsed_nanos"]) / measured,
                   "batch_thread_cpu_nanos_per_get": Decimal(thread_cpu) / measured,
                   "whole_process_cpu_micros": Decimal(whole_cpu),
                   "normal_kernel_high_water_rss_bytes": Decimal(memory["kernel_high_water_rss_bytes"]),
                   "normal_completion_rss_bytes": Decimal(memory["completion"]["rss_bytes"])}
    else:
        require(row["cpu"] is None, "lookup-profiled-whole-cpu-is-not-normal")
        whole = allocation(row, suite, artifacts)
        attribution = allocations.attribute(row, binary, suite["symbols"][row["variant"]], suite["tools"]["nm"], artifacts, whole)
        metrics = {"whole_process_" + name: Decimal(whole[name]) for name in
                   ("allocation_count", "allocated_bytes", "peak_live_bytes", "remaining_live_bytes", "remaining_allocations")}
        if attribution["status"] == "available":
            metrics["measured_frame_allocations_per_get"] = Decimal(attribution["allocation_count"]) / measured
            metrics["measured_frame_allocated_bytes_per_get"] = Decimal(attribution["allocated_bytes"]) / measured
    return key, {"validated_measured_hits": str(measured), "validated_warmup_hits": str(selected["warmup_hits"]),
                 "metrics": {name: str(value) for name, value in metrics.items()}, "allocation_attribution": attribution,
                 "result": result, "process_identity": {"process_id": key[0], "start_time_ticks": key[1]}}


def validate_suite(path):
    path = Path(path)
    checksum = hash_file(path, DOCUMENT_BYTES)
    suite = read_json(path)
    require(hash_file(path, DOCUMENT_BYTES) == checksum, "lookup-suite-changed-during-read")
    fields(suite, "schema profile plan builds runner_source runner_source_after status reason elapsed_nanos tools symbols runs artifacts")
    require(suite["schema"] == "latent.optimization.cache-lookup-suite.v1"
            and suite["plan"] == model.suite_plan(suite["profile"]), "lookup-suite-schema-or-plan")
    require(suite["status"] in ("passed", "failed")
            and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"), "lookup-suite-status")
    elapsed = uint(suite["elapsed_nanos"])
    require(elapsed <= 3600 * 10**9 + 5 * 10**9, "lookup-suite-wall-bound")
    source(suite["runner_source"])
    require(suite["runner_source"] == suite["runner_source_after"], "lookup-harness-source-changed")
    build = read_json(verify_artifact(path.parent, suite["builds"], DOCUMENT_BYTES))
    binaries = {value["executables"]["lookup"]["path"] for value in build["builds"].values()}
    artifacts = Artifacts(path.parent, suite["artifacts"], binaries)
    artifacts.path(suite["builds"])
    builds.validate(build, artifacts, suite["profile"], "lookup")
    require(build["harness"]["source"] == suite["runner_source"], "lookup-harness-build-crossed")
    actual_files = {item["path"] for item in inventory(path.parent)}
    require(actual_files == set(artifacts.rows), "lookup-unregistered-evidence-file")
    tools(suite["tools"], artifacts, suite["status"] == "passed" or bool(suite["runs"]))
    require(isinstance(suite["symbols"], dict) and set(suite["symbols"]) <= {"control", "candidate"}, "lookup-symbol-proof-set")
    require(not suite["runs"] or set(suite["symbols"]) == {"control", "candidate"}, "lookup-symbol-proof-missing")
    for variant, proof in suite["symbols"].items():
        fields(proof, "command process log raw")
        allocations.symbol_proof(proof, build["builds"][variant]["executables"]["lookup"], suite["tools"]["nm"], artifacts)
    expected = list(model.population(suite["profile"]))
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= len(expected), "lookup-run-count")
    records, owners, previous, stable_host, stable_cgroup = [], set(), 0, None, None
    failed = suite["status"] == "failed"
    for ordinal, row in enumerate(suite["runs"]):
        fields(row, "repetition variant capacity pattern mode status reason command started_micros finished_micros plan identity "
                    "ready result trace process probe_process resources cpu profile_refs log host_before host_after cgroup_before cgroup_after")
        cell = (row["repetition"], row["variant"], row["mode"], row["capacity"], row["pattern"])
        require(cell == expected[ordinal], "lookup-missing-duplicate-or-reordered-cell")
        selected = model.plan(suite["profile"], *cell)
        require(artifacts.json(row["plan"]) == selected, "lookup-run-plan-changed")
        require(artifacts.json(row["identity"]) == builds.identity(build, row["variant"], row["host_before"]), "lookup-run-identity-crossed")
        start, finish = uint(row["started_micros"]), uint(row["finished_micros"])
        require(previous <= start <= finish and (finish - start) * 1000 <= elapsed, "lookup-overlapping-or-unbounded-processes")
        previous = finish
        before, after = host_controls(row["host_before"]), host_controls(row["host_after"])
        stable_host = before if stable_host is None else stable_host
        require(before == after == stable_host, "lookup-host-controls-changed")
        for name in ("cgroup_before", "cgroup_after"):
            cgroup(row[name])
            controls = {key: row[name][key] for key in ("scope", "process_membership", "resolution", "cpu.max", "memory.max")}
            stable_cgroup = controls if stable_cgroup is None else stable_cgroup
            require(controls == stable_cgroup, "lookup-cgroup-controls-changed")
        require(row["status"] in ("passed", "failed") and row["reason"] == (None if row["status"] == "passed" else "collector-failed"),
                "lookup-run-status")
        summary = {key: row[key] for key in ("repetition", "variant", "capacity", "pattern", "mode", "status")}
        if row["status"] == "failed":
            failed = True
            if row["process"] is not None:
                binary = build["builds"][row["variant"]]["executables"]["lookup"]
                executable = binary["sha256"] if row["mode"] == "normal" else suite["tools"]["heaptrack"]["sha256"]
                process(row["process"], "identity-" + row["mode"], executable)
                require(row["process"]["reaped"] is True and row["process"]["output_closed"] is True, "lookup-failed-owner-not-cleaned")
            if all(row[key] is not None for key in ("ready", "result", "trace", "probe_process", "log")):
                observed = events.parse(row, selected, artifacts)
                summary["validated_measured_hits"] = str(observed["measured_hits"])
                summary["validated_warmup_hits"] = str(observed["warmup_hits"])
        else:
            key, result = run(row, selected, suite, build, artifacts)
            require(key not in owners, "lookup-reused-probe-owner")
            owners.add(key)
            summary.update(result)
        records.append(summary)
    complete = len(records) == len(expected) and not failed
    require(suite["status"] != "passed" or complete, "lookup-passed-suite-hides-incomplete-population")
    from .aggregate import aggregate
    return aggregate(suite, checksum[0], build, records, complete, failed)
