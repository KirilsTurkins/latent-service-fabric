"""Replay all 61 offers and ownership witnesses, including nonrecovering control."""
import copy
import re

from tools.optimization_evidence.common import fields, require, uint
from tools.phase1_evidence.resources import Samples, idle, shutdown
from ..budget import parse as budget
from ..budget.observer import waits
from ..cache.aggregate import resource_summary
from . import attempts, proofs, resources
from .observer import Diagnostic, instant


def parse(value, selected, identity, artifacts, raw_path, component, variant):
    fields(value, "schema plan identity configuration effective_options clock startup fixture configured_runtimes population "
           "diagnostic_limits cleanup_limits initial_waits initial_cleanup initial_node samples status reason elapsed_micros "
           "work diagnostic final_waits before_shutdown cleanup_before_shutdown shutdown data_cleanup runtime_threads_after_join process_cpu")
    require(value["schema"] == "latent.optimization.recovery-arm.v1" and value["plan"] == selected
            and value["identity"] == identity and value["status"] == "passed" and value["reason"] is None, "recovery-arm-not-passed")
    require(value["configuration"]["nodeId"] == "transport-recovery"
            and value["configuration"]["retention"]["terminalEntries"] == 128, "recovery-node-controls")
    compatible = copy.deepcopy(value["configuration"])
    compatible["nodeId"], compatible["retention"]["terminalEntries"] = "budget-lifecycle", 64
    budget.configuration(compatible)
    require(value["population"] == {"invoke_attempts": "61", "maximum_commands": "256", "expected_commands": "125"}
            and value["work"] == {"invoke_attempts": "61", "commands": "125", "budget_exhausted": False}, "recovery-work-population")
    require(value["diagnostic_limits"] == {"identities": "64", "records": "2048", "identifier_bytes": "256"}
            and value["cleanup_limits"] == {"grace_millis": "100", "handoff_ceiling_millis": "200", "observation_millis": "250"},
            "recovery-observer-or-cleanup-bounds")
    require(value["effective_options"] == {"cpu_fuel": "10000000000", "memory_bytes": "67108864", "wall_time_limit_millis": "1000",
            "log_bytes": "16384", "pool_capacity": "4", "queue_capacity": "64", "runtime_workers": "2", "control_workers": "4",
            "prepared_cache_maximum_entries": "4", "allocator": "on_demand", "copy_on_write": True, "prepared_cache_enabled": True,
            "fuel_async_yield_interval": "10000", "maximum_wasm_stack_bytes": "524288", "async_stack_bytes": "2097152", "hostcall_fuel": "131072"},
            "recovery-effective-controls")
    require(value["configured_runtimes"] == {"invocation": 2, "control": 4, "client": 2}
            and value["runtime_threads_after_join"] == {"invocation": 0, "control": 0, "client": 0}, "recovery-runtime-threads-not-joined")
    fields(value["clock"], "unix_origin_nanos clock_anchor_uncertainty_nanos")
    origin = uint(value["clock"]["unix_origin_nanos"])
    uint(value["clock"]["clock_anchor_uncertainty_nanos"])
    startup = fields(value["startup"], "catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    require(startup["excluded"] == ["fixture-loading", "runtime-construction"]
            and startup["comparable_to_historical_startup"] is False, "recovery-startup-boundary")
    for name in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        uint(startup[name])
    release = budget.fixture(value["fixture"], artifacts, raw_path.parent, component)
    rows = value["samples"]
    require(isinstance(rows, list) and len(rows) == 184, "recovery-record-count")
    offers = [row for row in rows if row.get("kind") == "invoke"]
    commands = [row for row in rows if row.get("kind") == "command"]
    checkpoints = [row for row in rows if row.get("kind") == "checkpoint"]
    require(len(offers) == len(checkpoints) == 61 and len(commands) == 62 and rows[-61:] == offers
            and [row["ordinal"] for row in offers] == [str(index) for index in range(61)]
            and [row["ordinal"] for row in checkpoints] == [str(index) for index in range(61)], "recovery-missing-duplicate-or-reordered-offer")
    normalized = [attempts.validate(row, origin, release) for row in offers]
    require(offers[0]["outcome"] == "success", "recovery-prewarm-failed")
    revision = offers[0]["response"]["revision_id"]
    require(re.fullmatch(r"revision-v1:sha256:[0-9a-f]{64}", revision), "recovery-prewarm-revision")
    for offer in offers:
        response = offer["response"]
        if response is not None and response["release_digest"]:
            require(response["revision_id"] == revision and response["release_digest"] == release
                    and response["route_generation"] == "1", "recovery-response-pinned-revision-crossed")
    observer = Diagnostic(value["diagnostic"])
    require(len(observer.identities) == 61 and all(row["diagnostic_token"] is not None for row in offers)
            and {uint(row["diagnostic_token"]) for row in offers} == set(observer.identities), "recovery-incomplete-ingress-population")
    observations = [observer.bind(row, variant) for row in offers]
    cancellation = proofs.commands(commands, offers, observer, variant, revision)
    tracker, previous_waits, previous_cleanup = Samples(), value["initial_waits"], value["initial_cleanup"]
    waits(previous_waits, final=True)
    require(all(previous_waits[name] == "0" for name in ("armed", "completed", "dropped", "live", "maximum_live", "rechecks")), "recovery-waits-already-active")
    resources.cleanup(previous_cleanup, variant, initial=True)
    tracker.check(value["initial_node"])
    idle(value["initial_node"], dormant=True)
    prior = uint(value["initial_node"]["finished_micros"]) * 1000
    coverage = []
    for offer, checkpoint, observation in zip(offers, checkpoints, observations, strict=True):
        fields(checkpoint, "kind ordinal observed_nanos node cleanup waits")
        end = uint(checkpoint["observed_nanos"])
        require(prior <= uint(offer["scheduled_nanos"]) <= uint(offer["completed_nanos"])
                <= uint(offer["retained_observed_nanos"]) <= end
                and end <= uint(checkpoint["node"]["started_micros"]) * 1000 + 999,
                "recovery-offer-or-checkpoint-clock")
        for command in commands:
            if command["target"] == offer["activation_id"]:
                require(prior <= uint(command["started_nanos"]) <= uint(command["finished_nanos"]) <= end, "recovery-command-outside-offer")
        acknowledgement = observer.acknowledgement(offer["acknowledgement"], offer)
        bound = uint(offer["disconnect"]["requested_nanos"]) if offer["disconnect"] is not None else uint(offer["completed_nanos"])
        running = observer.running(offer["running_witness"], offer, uint(offer["dispatch_nanos"]), bound)
        final_running = observer.running(offer["running_witness_final"], offer, uint(offer["completed_nanos"]), uint(offer["acknowledgement"]["started_nanos"]))
        running_records = observer.ran(offer)
        ran = bool(running_records)
        require(final_running or not running and not any(instant(row["observed_at_nanos"]) <= uint(offer["completed_nanos"])
                                                        for row in running_records), "recovery-source-running-witness-erased")
        require(offer["case"] in ("disconnect", "running-disconnect", "positive-cancel") or not running, "recovery-unplanned-running-trigger")
        require(offer["case"] == "positive-cancel" or offer["cancel_response"] is None, "recovery-extra-cancel-command")
        disposition = proofs.cleanup_log(offer["cleanup_log"], offer, ran, variant, origin, checkpoint, revision)
        tracker.check(checkpoint["node"])
        require(checkpoint["node"]["label"] == "recovery-after-offer", "recovery-checkpoint-label")
        cells = resources.node(checkpoint["node"], variant)
        if variant == "candidate":
            idle(checkpoint["node"])
            require(cells == {"total": 4, "available": 4, "active": 0, "quarantined": 0, "queueDepth": 0}, "recovery-candidate-lost-capacity")
            if offer["function"] == "identify":
                require(offer["outcome"] == "success", "recovery-followup-not-successful")
            if offer["case"] == "running-disconnect":
                require(running and offer["outcome"] == "client-disconnected" and observation["transport_handoff"] is not None,
                        "recovery-five-running-disconnects-not-proved")
        waits(checkpoint["waits"], previous_waits, final=True)
        resources.cleanup(checkpoint["cleanup"], variant, previous_cleanup)
        if variant == "candidate":
            index = uint(offer["ordinal"])
            upper = uint(offers[index + 1]["scheduled_nanos"]) if index < 60 else uint(value["before_shutdown"]["started_micros"]) * 1000 + 999
            observer.snapshot(checkpoint["cleanup"], end, upper)
        previous_waits, previous_cleanup = checkpoint["waits"], checkpoint["cleanup"]
        coverage.append({"ordinal": offer["ordinal"], "case": offer["case"], "budget_millis": offer["budget_millis"],
                         "actual_running": ran, "running_at_drop_trigger": running, "disconnect": offer["disconnect"],
                         "acknowledgement": acknowledgement, "native_cleanup": disposition, "cells": cells,
                         "supervisor": checkpoint["cleanup"], **observation})
        prior = uint(checkpoint["node"]["finished_micros"]) * 1000
    waits(value["final_waits"], previous_waits, final=True)
    resources.cleanup(value["cleanup_before_shutdown"], variant, previous_cleanup)
    tracker.check(value["before_shutdown"])
    idle(value["before_shutdown"])
    require(value["before_shutdown"]["work"] == value["work"], "recovery-work-counter-crossed")
    require("compiler" in value["shutdown"] and ("cleanup" in value["shutdown"]) == (variant == "candidate"), "recovery-shutdown-observer-missing")
    shutdown(value["shutdown"], cells=4)
    require(value["data_cleanup"] == {"removed": True}, "recovery-owned-data-not-removed")
    if variant == "candidate":
        require(value["shutdown"]["quarantinedCells"] == 0 and value["shutdown"]["cleanup"]["capacity"] == 68
                and value["shutdown"]["cleanup"]["handoffs"] == len(observer.handoffs), "recovery-final-handoffs-or-cell-capacity")
    return finish(value, identity, normalized, coverage, cancellation, tracker, offers, checkpoints, variant)


def finish(value, identity, normalized, coverage, cancellation, tracker, offers, checkpoints, variant):
    elapsed = uint(value["elapsed_micros"])
    require(elapsed <= 180_000_000 and uint(value["diagnostic"]["collector_finished_nanos"]) <= elapsed * 1000 + 999,
            "recovery-child-or-diagnostic-bound")
    for sample in tracker.values:
        resources.node(sample, variant)
        require(uint(sample["finished_micros"]) <= elapsed, "recovery-node-sample-outside-run")
    process_cpu = budget.cpu(value["process_cpu"], identity, offers, checkpoints, scope="owned-process-recovery-population-and-controls")
    before, after = process_cpu["before"], process_cpu["after"]
    if before is not None:
        require(uint(value["initial_node"]["finished_micros"]) * 1000 <= uint(before["collector_started_nanos"]), "recovery-initial-probe-after-cpu-start")
    if after is not None:
        require(uint(after["collector_finished_nanos"]) <= uint(value["before_shutdown"]["started_micros"]) * 1000 + 999, "recovery-final-probe-before-cpu-end")
    for reading in (before, after):
        if reading is not None:
            require((uint(reading["pid"]), uint(reading["start_time_ticks"])) == tracker.identity, "recovery-foreign-process-cpu")
    return {"process_identity": tracker.identity, "samples": "61", "commands": "125", "offers": normalized,
            "coverage": coverage, "cancellation": cancellation, "diagnostic_event_count": str(len(value["diagnostic"]["records"])),
            "waits": {"scope": "manager-owned-deadline-sleep-guards", "initial": value["initial_waits"], "final": value["final_waits"]},
            "process_cpu": process_cpu, "resources": resource_summary(tracker.values), "shutdown": value["shutdown"]}
