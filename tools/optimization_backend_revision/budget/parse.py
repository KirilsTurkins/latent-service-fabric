"""Strict replay of all 23 offers, source decisions and final owned cleanup."""
import copy

from tools.optimization_evidence.common import fields, integer, read_json, require, uint
from tools.phase1_evidence.resources import Samples, idle, shutdown
from ..cache.aggregate import resource_summary
from ..cold.parse import configuration as cold_configuration
from . import attempts, proofs
from .observer import Diagnostic, waits


def configuration(value):
    require(value["nodeId"] == "budget-lifecycle" and value["retention"]["terminalEntries"] == 64,
            "budget-lifecycle-node-controls")
    projected = copy.deepcopy(value)
    projected["retention"]["terminalEntries"] = 2048
    cold_configuration(projected, "candidate", node_id="budget-lifecycle", entries=4)


def fixture(value, artifacts, parent, component):
    fields(value, "name tenant service contract component_sha256 component_bytes capsule contracts deployment publication")
    require(value["name"] == "generic" and value["tenant"] == "tests" and value["service"] == "measurement-generic"
            and value["contract"] == "tests:generic/values@0.1.0"
            and value["component_sha256"] == component["sha256"] and value["component_bytes"] == component["bytes"],
            "budget-loaded-generic-component-crossed")
    release = component["sha256"]
    require(value["publication"] == {"release_digest": release, "deployment_id": "measurement-generic",
                                       "object_generation": "1", "catalog_generation": "1"}, "budget-publication-stamp")
    documents = {}
    for name in ("capsule", "contracts", "deployment"):
        ref = value[name]
        require(ref["path"] == f"generic-{name}.json" and uint(ref["bytes"]) <= 1024**2, "budget-generic-metadata-bound")
        documents[name] = read_json(artifacts.nested(parent, ref), 1024**2)
    capsule, contracts, deployment = (documents[name] for name in ("capsule", "contracts", "deployment"))
    require(capsule["component"]["digest"] == deployment["spec"]["release"] == release
            and capsule["component"]["world"] == "tests:generic/service@0.1.0"
            and capsule["exports"] == ["tests:generic/alternate@0.1.0", "tests:generic/values@0.1.0"]
            and capsule["imports"] == [] and deployment["spec"]["service"] == "measurement-generic", "budget-generic-semantics")
    for document in (capsule, deployment):
        require(document["metadata"]["tenant"] == "tests" and document["metadata"]["name"] == "measurement-generic", "budget-generic-scope")
    for limit in (capsule["execution"]["limits"], deployment["spec"]["resources"]):
        require(limit["cpuFuel"] == 10_000_000_000 and limit["memoryBytes"] == 67_108_864
                and limit["logBytes"] == 16384 and limit.get("wallTimeLimitMillis") in (None, 1000), "budget-persisted-grant")
    # Typed metadata is retained in full; bind the actual measured exports rather
    # than accepting a crossed Echo table merely because its JSON was rehashed.
    fields(contracts, "format_version contracts")
    require(contracts["format_version"] == 1 and isinstance(contracts["contracts"], list) and len(contracts["contracts"]) == 2
            and [row.get("id") for row in contracts["contracts"]] == ["tests:generic/values@0.1.0", "tests:generic/alternate@0.1.0"],
            "budget-generic-contracts")
    measured = contracts["contracts"][0]["interfaces"]
    require(isinstance(measured, list) and len(measured) == 1 and measured[0]["id"] == "tests:generic/values@0.1.0",
            "budget-generic-measured-interface")
    for name in ("identify", "spin"):
        function = [row for row in measured[0]["functions"] if row.get("id") == name]
        require(len(function) == 1 and function[0]["name"] == name and function[0]["asynchronous"] is False
                and function[0]["parameters"] == []
                and function[0]["results"] == [{"name": "result", "value_type": "U32", "documentation": None}],
                "budget-generic-measured-function")
    return release


def cpu(value, identity, offers, checkpoints):
    fields(value, "scope clock_ticks_per_second before after")
    require(value["scope"] == "owned-process-diagnostic-population-and-controls"
            and value["clock_ticks_per_second"] == identity["environment"]["clock_ticks_per_second"], "budget-process-cpu-scope")
    frequency = integer(value["clock_ticks_per_second"], 1, 1_000_000)
    for row in (value["before"], value["after"]):
        if row is not None:
            fields(row, "collector_started_nanos collector_finished_nanos pid start_time_ticks user_ticks system_ticks")
            for number in row.values():
                uint(number)
            require(uint(row["collector_started_nanos"]) <= uint(row["collector_finished_nanos"]), "budget-cpu-capture-window")
    if value["before"] is None or value["after"] is None:
        return {"status": "unavailable", "scope": value["scope"], "clock_ticks_per_second": frequency,
                "before": value["before"], "after": value["after"], "user_ticks": None, "system_ticks": None}
    before, after = value["before"], value["after"]
    require((before["pid"], before["start_time_ticks"]) == (after["pid"], after["start_time_ticks"])
            and uint(before["collector_finished_nanos"]) <= min(uint(row["scheduled_nanos"]) for row in offers)
            and uint(after["collector_started_nanos"]) >= uint(checkpoints[-1]["observed_nanos"]), "budget-process-cpu-crossed")
    changes = {}
    for name in ("user_ticks", "system_ticks"):
        require(uint(after[name]) >= uint(before[name]), "budget-process-cpu-regressed")
        changes[name] = str(uint(after[name]) - uint(before[name]))
    return {"status": "available", "scope": value["scope"], "clock_ticks_per_second": frequency,
            "before": before, "after": after, **changes}


def parse(value, selected, identity, artifacts, raw_path, component, variant):
    fields(value, "schema plan identity configuration effective_options clock startup fixture configured_runtimes population "
           "initial_waits initial_node samples status reason elapsed_micros work diagnostic final_waits before_shutdown shutdown "
           "data_cleanup runtime_threads_after_join process_cpu")
    require(value["schema"] == "latent.optimization.budget-lifecycle-arm.v1" and value["plan"] == selected
            and value["identity"] == identity and value["status"] == "passed" and value["reason"] is None, "budget-lifecycle-arm-not-passed")
    configuration(value["configuration"])
    require(value["population"] == {"invoke_attempts": "23", "maximum_control_commands": "128"}
            and value["work"] == {"invoke_attempts": "23", "commands": "57", "budget_exhausted": False}, "budget-lifecycle-work-population")
    require(value["effective_options"] == {"cpu_fuel": "10000000000", "memory_bytes": "67108864", "wall_time_limit_millis": "1000",
            "log_bytes": "16384", "pool_capacity": "4", "queue_capacity": "64", "runtime_workers": "2", "control_workers": "4",
            "prepared_cache_maximum_entries": "4", "allocator": "on_demand", "copy_on_write": True, "prepared_cache_enabled": True,
            "fuel_async_yield_interval": "10000", "maximum_wasm_stack_bytes": "524288", "async_stack_bytes": "2097152", "hostcall_fuel": "131072"},
            "budget-lifecycle-runtime-controls")
    require(value["configured_runtimes"] == {"invocation": 2, "control": 4, "client": 2}
            and value["runtime_threads_after_join"] == {"invocation": 0, "control": 0, "client": 0}, "budget-runtime-threads-not-joined")
    fields(value["clock"], "unix_origin_nanos clock_anchor_uncertainty_nanos")
    origin = uint(value["clock"]["unix_origin_nanos"])
    uint(value["clock"]["clock_anchor_uncertainty_nanos"])
    startup = fields(value["startup"], "catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    require(startup["excluded"] == ["fixture-loading", "runtime-construction"]
            and startup["comparable_to_historical_startup"] is False, "budget-startup-boundary")
    for name in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        uint(startup[name])
    release = fixture(value["fixture"], artifacts, raw_path.parent, component)
    rows = value["samples"]
    require(isinstance(rows, list) and len(rows) == 61, "budget-lifecycle-record-count")
    offers = [row for row in rows if row.get("kind") == "invoke"]
    commands_rows = [row for row in rows if row.get("kind") == "command"]
    checkpoints = [row for row in rows if row.get("kind") == "checkpoint"]
    require(len(offers) == 23 and rows[-23:] == offers and [row["ordinal"] for row in offers] == [str(index) for index in range(23)],
            "budget-lifecycle-missing-duplicate-or-reordered-offer")
    require(len(commands_rows) == 32 and len(checkpoints) == 6, "budget-lifecycle-control-record-count")
    normalized = [attempts.validate(row, origin, release) for row in offers]
    observer = Diagnostic(value["diagnostic"])
    require(len(observer.identities) == 23 and all(row["diagnostic_token"] is not None for row in offers)
            and {uint(row["diagnostic_token"]) for row in offers} == set(observer.identities), "budget-lifecycle-incomplete-ingress-population")
    observations = [observer.bind(row, variant) for row in offers]
    cancellation = proofs.commands(commands_rows, offers, observer)
    proofs.case_windows(offers, commands_rows, checkpoints)
    coverage = proofs.coverage(offers, observer)
    tracker, previous_waits = Samples(), value["initial_waits"]
    require(all(value["initial_waits"][name] == "0" for name in ("armed", "completed", "dropped", "live", "maximum_live", "rechecks")),
            "budget-waits-already-active")
    waits(previous_waits, final=True)
    tracker.check(value["initial_node"])
    idle(value["initial_node"], dormant=True)
    for row in checkpoints:
        fields(row, "kind label observed_nanos waits node")
        waits(row["waits"], previous_waits, final=True)
        previous_waits = row["waits"]
        tracker.check(row["node"])
        require(row["node"]["label"] == row["label"], "budget-checkpoint-label-crossed")
        require(uint(row["observed_nanos"]) <= uint(row["node"]["started_micros"]) * 1000 + 999,
                "budget-checkpoint-before-node-capture")
        idle(row["node"])
    waits(value["final_waits"], previous_waits, final=True)
    tracker.check(value["before_shutdown"])
    idle(value["before_shutdown"])
    for sample in tracker.values:
        cache = sample["inventory"]["cacheSummary"]
        require(cache["maximumEntries"] == "4" and cache["maximumConcurrentPreparations"] == "4"
                and sample["resources"]["descendants"] == [], "budget-node-observed-controls")
        require(uint(sample["finished_micros"]) <= uint(value["elapsed_micros"]), "budget-node-sample-outside-run")
    require(uint(value["initial_node"]["finished_micros"]) * 1000 <= uint(offers[0]["scheduled_nanos"]),
            "budget-initial-probe-overlaps-offer")
    require(value["before_shutdown"]["work"] == value["work"], "budget-work-counter-crossed")
    require("compiler" in value["shutdown"], "budget-compiler-shutdown-unobserved")
    shutdown(value["shutdown"], cells=4)
    require(value["shutdown"]["quarantinedCells"] == 0 and value["data_cleanup"] == {"removed": True}, "budget-owned-cleanup-failed")
    require(uint(value["elapsed_micros"]) <= 180_000_000
            and uint(value["diagnostic"]["collector_finished_nanos"]) <= uint(value["elapsed_micros"]) * 1000 + 999,
            "budget-diagnostic-child-bound")
    process_cpu = cpu(value["process_cpu"], identity, offers, checkpoints)
    if process_cpu["before"] is not None:
        require(uint(value["initial_node"]["finished_micros"]) * 1000 <= uint(process_cpu["before"]["collector_started_nanos"]),
                "budget-initial-probe-outside-cpu-boundary")
    if process_cpu["after"] is not None:
        require(uint(process_cpu["after"]["collector_finished_nanos"]) <= uint(value["before_shutdown"]["started_micros"]) * 1000 + 999,
                "budget-final-probe-before-cpu-end")
    for reading in (process_cpu["before"], process_cpu["after"]):
        if reading is not None:
            require((uint(reading["pid"]), uint(reading["start_time_ticks"])) == tracker.identity, "budget-foreign-process-cpu")
    return {"process_identity": tracker.identity, "samples": "23", "commands": "57", "offers": normalized,
            "deadline_observations": [{"ordinal": row["ordinal"], "case": row["case"], "budget_millis": row["budget_millis"], **observation}
                                      for row, observation in zip(offers, observations, strict=True)],
            "diagnostic_event_count": str(len(observer.records)), "coverage": coverage, "cancellation": cancellation,
            "waits": {"scope": "manager-owned-deadline-sleep-guards", "initial": value["initial_waits"], "final": value["final_waits"],
                      "checkpoints": [{"label": row["label"], "observed_nanos": row["observed_nanos"], "snapshot": row["waits"]} for row in checkpoints]},
            "process_cpu": process_cpu, "resources": resource_summary(tracker.values), "shutdown": value["shutdown"]}
