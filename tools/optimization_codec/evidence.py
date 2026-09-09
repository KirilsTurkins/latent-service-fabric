"""Strict exact-source replay of every declared normal and profiled codec child."""
from decimal import Decimal
from pathlib import Path

from tools.artifact_identity_evidence.runs import allocation, probe_resources
from tools.optimization_cache_lookup.evidence import host_controls, tools
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import fields, hash_file, read_json, require, uint, verify_artifact
from tools.optimization_evidence.resources import cgroup, process
from tools.optimization_revision_evidence.identity import source
from . import allocations, builds, events, model
from .parse import parse


def run(row, selected, suite, build, artifacts):
    binary = build["builds"][row["variant"]]["executables"]["codec"]
    argv = row["command"]
    prefix = 3 if row["mode"] == "allocation" else 0
    require(isinstance(argv, list) and len(argv) == prefix + 6 and all(isinstance(x, str) for x in argv)
            and argv[prefix].endswith("/" + binary["path"])
            and argv[prefix + 1:] == ["--exact", model.COLLECTOR, "--ignored", "--nocapture", "--test-threads=1"],
            "codec-probe-command-crossed")
    if prefix:
        require(argv[:2] == [suite["tools"]["heaptrack"]["path"], "--output"]
                and argv[2] == argv[prefix].removesuffix(binary["path"]) + row["log"]["path"].removesuffix("probe.log") + "heaptrack",
                "codec-profiler-command-crossed")
    key, memory = probe_resources(row, binary, suite["tools"])
    ready, complete = events.parse(row, selected, artifacts)
    supplied = builds.identity(build, row["variant"], row["host_before"])
    result = parse(artifacts.json(row["raw"], model.MAX_DOCUMENT_BYTES), selected, supplied, row, artifacts,
                   build["builds"][row["variant"]]["inputs"][model.TYPE_FIXTURE], ready, complete)
    require(result["process_id"] == key[0], "codec-raw-process-crossed")
    metrics, attribution, whole = {}, None, None
    if row["mode"] == "normal":
        require(row["profile_refs"] is None, "codec-normal-child-profiled")
        cpu = fields(row["cpu"], "scope user_micros system_micros")
        require(cpu["scope"] == "whole-owned-process-rusage-children", "codec-whole-cpu-scope")
        whole_cpu = uint(cpu["user_micros"]) + uint(cpu["system_micros"])
        thread_total = 0
        for timed in result["directions"]:
            label = timed["direction"]
            ticks = uint(timed["cpu"]["after_nanos"]) - uint(timed["cpu"]["before_nanos"])
            thread_total += ticks
            metrics[label + "_elapsed_nanos_per_operation"] = Decimal(timed["elapsed_nanos"]) / selected["measured_iterations"]
            metrics[label + "_thread_cpu_nanos_per_operation"] = Decimal(ticks) / selected["measured_iterations"]
        require(thread_total <= (whole_cpu + 2) * 1000, "codec-thread-cpu-exceeds-owned-child")
        metrics.update(whole_process_cpu_micros=Decimal(whole_cpu),
                       normal_observed_rss_bytes=Decimal(memory["maximum_observed_rss_bytes"]),
                       normal_kernel_high_water_rss_bytes=Decimal(memory["kernel_high_water_rss_bytes"]),
                       normal_completion_rss_bytes=Decimal(memory["completion"]["rss_bytes"]))
    else:
        require(row["cpu"] is None, "codec-instrumented-cpu-is-not-normal")
        whole = allocation(row, suite, artifacts, maximum_folded_bytes=model.MAX_FOLDED_BYTES)
        attribution = allocations.attribute(row, binary, suite["symbols"][row["variant"]], suite["tools"]["nm"], artifacts, whole)
        metrics = {"whole_process_" + name: Decimal(whole[name]) for name in
                   ("allocation_count", "allocated_bytes", "peak_live_bytes", "remaining_live_bytes", "remaining_allocations")}
        if attribution["status"] == "available":
            for label, symbol in zip(("decode", "encode"), model.SYMBOLS, strict=True):
                observed = attribution["frames"][symbol]
                for name in ("allocation_count", "allocated_bytes"):
                    metrics[label + "_frame_" + name + "_per_operation"] = Decimal(observed[name]) / selected["measured_iterations"]
                metrics[label + "_frame_peak_live_bytes"] = Decimal(observed["peak_live_bytes"])
                metrics[label + "_frame_remaining_bytes"] = Decimal(observed["live_bytes"])
            metrics["selected_union_peak_live_bytes"] = Decimal(attribution["union"]["peak_live_bytes"])
    return key, {**{name: result[name] for name in ("validated_codec_operations", "validated_preflight_operations",
                "validated_warmup_operations", "validated_measured_operations")},
                 "metrics": {name: str(value) for name, value in metrics.items()}, "result": result,
                 "allocation_attribution": attribution, "whole_process_allocations": whole,
                 "process_identity": {"process_id": key[0], "start_time_ticks": key[1]}}


def validate_suite(path):
    path = Path(path)
    checksum = hash_file(path, model.MAX_DOCUMENT_BYTES)
    suite = read_json(path)
    require(hash_file(path, model.MAX_DOCUMENT_BYTES) == checksum, "codec-suite-changed-during-read")
    fields(suite, "schema profile plan builds runner_source runner_source_after status reason elapsed_nanos tools symbols runs artifacts")
    require(suite["schema"] == model.SCHEMA
            and suite["plan"] == model.suite_plan(suite["profile"]), "codec-suite-schema-or-plan")
    require(suite["status"] in ("passed", "failed")
            and suite["reason"] == (None if suite["status"] == "passed" else "collection-failed"), "codec-suite-status")
    elapsed = uint(suite["elapsed_nanos"])
    require(elapsed <= model.STAGE_SECONDS * 10**9, "codec-suite-wall-bound")
    source(suite["runner_source"])
    require(suite["runner_source"] == suite["runner_source_after"], "codec-harness-source-changed")
    build = read_json(verify_artifact(path.parent, suite["builds"], model.MAX_DOCUMENT_BYTES))
    binaries = {value["executables"]["codec"]["path"] for value in build["builds"].values()}
    artifacts = Artifacts(path.parent, suite["artifacts"], binaries)
    artifacts.path(suite["builds"])
    builds.validate(build, artifacts, suite["profile"])
    require(build["harness"]["source"] == suite["runner_source"], "codec-harness-build-crossed")
    actual_files = {item["path"] for item in inventory(path.parent)}
    require(actual_files == set(artifacts.rows), "codec-unregistered-evidence-file")
    tools(suite["tools"], artifacts, suite["status"] == "passed" or bool(suite["runs"]))
    require(isinstance(suite["symbols"], dict) and set(suite["symbols"]) <= {"control", "candidate"}, "codec-symbol-proof-set")
    require(not suite["runs"] or set(suite["symbols"]) == {"control", "candidate"}, "codec-symbol-proof-missing")
    for variant, proof in suite["symbols"].items():
        fields(proof, "command process log raw")
        allocations.proofs(proof, build["builds"][variant]["executables"]["codec"], suite["tools"]["nm"], artifacts)
    expected = list(model.population(suite["profile"]))
    require(isinstance(suite["runs"], list) and len(suite["runs"]) <= len(expected), "codec-run-count")
    records, owners, previous, stable_host, stable_cgroup = [], set(), 0, None, None
    failed = suite["status"] == "failed"
    for ordinal, row in enumerate(suite["runs"]):
        fields(row, "repetition variant family mode status reason command started_micros finished_micros plan identity "
                    "ready result raw process probe_process resources cpu profile_refs log host_before host_after cgroup_before cgroup_after")
        cell = (row["repetition"], row["variant"], row["mode"], row["family"])
        require(cell == expected[ordinal], "codec-missing-duplicate-or-reordered-cell")
        selected = model.plan(suite["profile"], *cell)
        require(artifacts.json(row["plan"]) == selected, "codec-run-plan-changed")
        require(artifacts.json(row["identity"]) == builds.identity(build, row["variant"], row["host_before"]), "codec-run-identity-crossed")
        start, finish = uint(row["started_micros"]), uint(row["finished_micros"])
        require(previous <= start <= finish and (finish - start) * 1000 <= elapsed, "codec-overlapping-or-unbounded-processes")
        previous = finish
        before, after = host_controls(row["host_before"]), host_controls(row["host_after"])
        stable_host = before if stable_host is None else stable_host
        require(before == after == stable_host, "codec-host-controls-changed")
        for name in ("cgroup_before", "cgroup_after"):
            cgroup(row[name])
            controls = {key: row[name][key] for key in ("scope", "process_membership", "resolution", "cpu.max", "memory.max")}
            stable_cgroup = controls if stable_cgroup is None else stable_cgroup
            require(controls == stable_cgroup, "codec-cgroup-controls-changed")
        require(row["status"] in ("passed", "failed") and row["reason"] == (None if row["status"] == "passed" else "collector-failed"),
                "codec-run-status")
        summary = {key: row[key] for key in ("repetition", "variant", "family", "mode", "status")}
        if row["status"] == "failed":
            failed = True
            if row["process"] is not None:
                binary = build["builds"][row["variant"]]["executables"]["codec"]
                executable = binary["sha256"] if row["mode"] == "normal" else suite["tools"]["heaptrack"]["sha256"]
                key = process(row["process"], "identity-" + row["mode"], executable)
                require(key not in owners, "codec-reused-failed-owner")
                owners.add(key)
                require(row["process"]["reaped"] is True and row["process"]["output_closed"] is True, "codec-failed-owner-not-cleaned")
            if row["raw"] is not None:
                artifacts.path(row["raw"])
            summary.update(raw_retained=row["raw"] is not None, attempt_count_complete=False,
                           validated_codec_operations="0", operation_coverage="unavailable-failed-child")
        else:
            key, result = run(row, selected, suite, build, artifacts)
            require(key not in owners, "codec-reused-probe-owner")
            owners.add(key)
            summary.update(result)
        records.append(summary)
    complete = len(records) == len(expected) and not failed
    require(suite["status"] != "passed" or complete, "codec-passed-suite-hides-incomplete-population")
    from .aggregate import aggregate
    return aggregate(suite, checksum[0], build, records, complete, failed)
