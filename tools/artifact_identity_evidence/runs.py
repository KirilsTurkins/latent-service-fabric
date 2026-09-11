"""Replay successful operations without conflating profiler and normal costs."""
from __future__ import annotations

from decimal import Decimal

from tools.optimization_evidence.common import decode
from tools.optimization_evidence.resources import cgroup, clean, process, samples
from .common import MAX_FOLDED_BYTES, digest, fields, folded, folded_limit, integer, require, uint
from .heaptrack import MAX_RECORDS, record_limit, replay
from .identity import helper

BOUNDARIES = {
    "hash": "content-digest-byte-slice-repeated",
    "artifact-open": "directory-artifact-open-including-recovery",
    "catalog-open": "directory-artifact-open-and-deployment-open-including-compilation",
}
EVENT_IDENTITY = "operation boundary process_id size component_digest component_bytes operation_count"


def events(record, fixture, artifacts, iterations):
    ready = artifacts.json(record["ready"], 16384)
    result = artifacts.json(record["result"], 16384)
    fields(ready, "schema event observation_hold_millis " + EVENT_IDENTITY)
    fields(result, "schema event elapsed_nanos outcome code release_count deployment_count route_count route_generation revision_id " + EVENT_IDENTITY)
    require(ready["schema"] == "latent.artifact-identity.ready.v1" and ready["event"] == "ready"
            and ready["observation_hold_millis"] == 100, "invalid-ready-event")
    require(result["schema"] == "latent.artifact-identity.result.v1" and result["event"] == "measurement-complete"
            and result["outcome"] == "passed" and result["code"] is None, "probe-operation-failed")
    expected = {"operation": record["operation"], "boundary": BOUNDARIES[record["operation"]],
                "process_id": record["probe_process"]["process_id"], "size": record["size"],
                "component_digest": fixture["component_digest"], "component_bytes": fixture["component_bytes"],
                "operation_count": str(iterations)}
    require(all(ready[key] == result[key] == value for key, value in expected.items()), "crossed-probe-event")
    require(uint(result["elapsed_nanos"]) > 0, "empty-operation-time")
    oracle = {key: None for key in ("release_count", "deployment_count", "route_count", "route_generation", "revision_id")}
    if record["operation"] != "hash":
        oracle["release_count"] = "1"
    if record["operation"] == "catalog-open":
        oracle.update(deployment_count="1", route_count="2", route_generation=fixture["route_generation"],
                      revision_id=fixture["revision_id"])
    require(all(result[key] == value for key, value in oracle.items()), "probe-semantic-oracle-mismatch")
    observed, count = [], 0
    with artifacts.path(record["log"]).open("rb") as stream:
        while line := stream.readline(65537):
            count += len(line)
            require(count <= 4 * 1024**2 and len(line) <= 65536 and line.endswith(b"\n"), "probe-log-bound")
            if line.startswith(b"{"):
                value = decode(line, 65536)
                if isinstance(value, dict) and "event" in value:
                    observed.append(value)
                    require(len(observed) <= 2, "extra-probe-event")
    require(observed == [ready, result], "events-unbound-to-probe-log")
    return result


def probe_resources(record, binary, tools):
    mode = record["mode"]
    launcher_hash = binary["sha256"] if mode == "normal" else tools["heaptrack"]["sha256"]
    owner = process(record["process"], "identity-" + mode, launcher_hash)
    require(clean(record["process"]), "probe-launcher-not-reaped")
    probe = fields(record["probe_process"], "process_id start_time_ticks executable_sha256 executable_device executable_inode owned_process_group observed_exited reaped_by_runner")
    integer(probe["process_id"], 2, 2**31 - 1)
    require(uint(probe["start_time_ticks"]) > 0 and uint(probe["executable_inode"]) > 0,
            "missing-probe-kernel-identity")
    uint(probe["executable_device"])
    require(probe["executable_sha256"] == binary["sha256"] and probe["owned_process_group"] == owner[0]
            and probe["observed_exited"] is True and probe["reaped_by_runner"] is (mode == "normal"),
            "unowned-or-crossed-probe")
    key = probe["process_id"], probe["start_time_ticks"]
    require((key == owner) is (mode == "normal"), "crossed-profiler-process")
    resources = fields(record["resources"], "probe wrapper cgroup")
    samples(resources["wrapper"], owner)
    cgroup(resources["cgroup"])
    item = fields(resources["probe"], "before completion last_live maximum_observed_rss_bytes kernel_high_water_rss_bytes sample_interval_millis before_semantics scope")
    require(item["sample_interval_millis"] == 100 and item["before_semantics"] == "first-observed-after-ready-not-guaranteed-pre-operation"
            and item["scope"] == ("normal-probe" if mode == "normal" else "heaptrack-instrumented-probe"),
            "changed-resource-boundary")
    maximum, high_water, observed = 0, 0, []
    for name in ("before", "completion", "last_live"):
        row = fields(item[name], "process_id start_time_ticks observed_ns rss_bytes kernel_high_water_rss_bytes cpu_user_ticks cpu_system_ticks threads fd_count read_bytes write_bytes")
        require((row["process_id"], row["start_time_ticks"]) == key, "crossed-probe-resource")
        for counter in ("observed_ns", "rss_bytes", "kernel_high_water_rss_bytes", "cpu_user_ticks", "cpu_system_ticks", "read_bytes", "write_bytes"):
            uint(row[counter])
        integer(row["threads"], 1, 65536)
        integer(row["fd_count"], 0, 4096)
        require(0 < uint(row["rss_bytes"]) <= uint(row["kernel_high_water_rss_bytes"]), "missing-live-probe-rss")
        maximum = max(maximum, uint(row["rss_bytes"]))
        high_water = max(high_water, uint(row["kernel_high_water_rss_bytes"]))
        observed.append(uint(row["observed_ns"]))
    require(observed[0] <= observed[1] and observed[0] <= observed[2] <= observed[1], "resource-observation-order")
    for counter in ("cpu_user_ticks", "cpu_system_ticks", "read_bytes", "write_bytes", "kernel_high_water_rss_bytes"):
        require(uint(item["before"][counter]) <= uint(item["last_live"][counter]) <= uint(item["completion"][counter]),
                "resource-counter-regressed")
    require(uint(item["maximum_observed_rss_bytes"]) >= maximum
            and uint(item["kernel_high_water_rss_bytes"]) >= max(high_water, uint(item["maximum_observed_rss_bytes"])),
            "resource-peak-below-observation")
    return key, item


def allocation(record, suite, artifacts, *, maximum_folded_bytes=MAX_FOLDED_BYTES,
               maximum_records=MAX_RECORDS):
    maximum_folded_bytes = folded_limit(maximum_folded_bytes)
    maximum_records = record_limit(maximum_records)
    refs = fields(record["profile_refs"], "raw report interpreted allocations peak")
    for ref in refs.values():
        artifacts.path(ref)
    for name, tool in (("report", "heaptrack_print"), ("interpreted", "zstd")):
        receipt = artifacts.rows.get(refs[name]["path"] + ".process.json")
        require(receipt is not None, "missing-profile-helper-receipt")
        helper(artifacts.json(receipt), suite["tools"][tool]["sha256"], refs[name], artifacts)
    for name in ("allocations", "peak"):
        log = artifacts.rows.get(refs[name]["path"].removesuffix(".gz").removesuffix(".folded") + ".log")
        require(log is not None, "missing-folded-helper-log")
        receipt = artifacts.rows.get(log["path"] + ".process.json")
        require(receipt is not None, "missing-folded-helper-receipt")
        helper(artifacts.json(receipt), suite["tools"]["heaptrack_print"]["sha256"], log, artifacts)
    raw = replay(artifacts.path(refs["interpreted"]), maximum_records=maximum_records)
    require(raw["command"] == " ".join(record["command"][3:]), "crossed-allocation-command")
    require(folded(artifacts.path(refs["allocations"]), maximum_bytes=maximum_folded_bytes)["total"] == raw["allocation_count"]
            and folded(artifacts.path(refs["peak"]), maximum_bytes=maximum_folded_bytes)["total"] == raw["peak_live_bytes"],
            "allocation-profile-totals-mismatch")
    return raw


def run(record, suite, artifacts):
    fields(record, "pair arm size operation mode status reason command ready result process probe_process resources cpu profile_refs log warmup")
    require(record["status"] == "passed" and record["reason"] is None, "incomplete-run")
    fixture = suite["fixtures"][record["size"]]
    manifest = fixture["manifest"]
    binary = suite["builds"][record["arm"]]["binary"]
    size = uint(manifest["component_bytes"])
    iterations = max(1, min(4096, 64 * 1024**2 // size)) if suite["profile"] == "full" and record["operation"] == "hash" else 1
    key, memory = probe_resources(record, binary, suite["tools"])
    result = events(record, manifest, artifacts, iterations)
    warm = fields(record["warmup"], "policy files bytes")
    require(warm["policy"] == suite["plan"]["cache_policy"] and warm["files"] == len(fixture["files"])
            and uint(warm["bytes"]) == sum(uint(ref["bytes"]) for ref in fixture["files"].values()), "missing-fixture-warming")
    command = record["command"]
    prefix = 3 if record["mode"] == "allocation" else 0
    require(isinstance(command, list) and len(command) == 8 + prefix and all(isinstance(x, str) for x in command), "invalid-probe-command")
    require(command[prefix].endswith("/" + binary["path"]) and command[prefix + 1:prefix + 4] == ["measure", "--operation", record["operation"]]
            and command[prefix + 4] == "--fixture" and command[prefix + 5].endswith("/" + fixture["root"])
            and command[prefix + 6:] == ["--iterations", str(iterations)], "changed-probe-command")
    root = command[prefix].removesuffix(binary["path"])
    require(command[prefix + 5] == root + fixture["root"]
            and root == fixture["command"][0].removesuffix(suite["builds"]["control"]["binary"]["path"]),
            "crossed-measurement-root")
    if prefix:
        require(command[2] == root + record["log"]["path"].removesuffix("probe.log") + "heaptrack",
                "crossed-profile-output")
    metrics = {}
    if record["mode"] == "normal":
        require(record["profile_refs"] is None, "profiled-normal-run")
        cpu = fields(record["cpu"], "scope user_micros system_micros")
        require(cpu["scope"] == "whole-owned-process-rusage-children", "changed-cpu-boundary")
        metrics.update(operation_nanos_per_call=Decimal(result["elapsed_nanos"]) / iterations,
                       whole_process_cpu_micros=uint(cpu["user_micros"]) + uint(cpu["system_micros"]),
                       whole_process_kernel_high_water_rss_bytes=uint(memory["kernel_high_water_rss_bytes"]),
                       whole_process_sampled_peak_rss_bytes=uint(memory["maximum_observed_rss_bytes"]),
                       completion_live_rss_bytes=uint(memory["completion"]["rss_bytes"]))
    else:
        require(record["cpu"] is None and command[:2] == [suite["tools"]["heaptrack"]["path"], "--output"], "mixed-profiler-cpu-or-command")
        raw = allocation(record, suite, artifacts)
        metrics.update({"whole_process_" + name: uint(raw[name]) for name in
                        ("allocation_count", "allocated_bytes", "peak_live_bytes", "remaining_live_bytes", "remaining_allocations")})
    return key, metrics
