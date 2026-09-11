"""Require observed process identities and product shutdown receipts."""

from __future__ import annotations

from typing import Any

from .common import fields, integer, require, text, uint
try:
    from ..phase1_compiler_shutdown import validate_compiler_shutdown
    from ..phase1_cleanup_shutdown import validate_cleanup_shutdown
except ImportError:
    from phase1_compiler_shutdown import validate_compiler_shutdown
    from phase1_cleanup_shutdown import validate_cleanup_shutdown

ZERO_SHUTDOWN_FIELDS = (
    "activeConnections activeRpcs activeControlJobs activeActivations cancellationRegistrations "
    "observerCorrelations quotaReservations queuedReservations reservedCpuFuel reservedMemoryBytes "
    "activeLeases queuedActivations activeBackendInvocations instanceReservations preparingComponents "
    "preparingSourceBytes preparingMetadataBytes liveStores liveHostStates liveInstances "
    "liveTemporaryBuffers liveCancellationProbes"
).split()


def shutdown(value: Any, cells: int = 2) -> None:
    fields(value, " ".join(ZERO_SHUTDOWN_FIELDS) +
           " clean quarantinedCells telemetryRetainedEntries telemetryFlushed epochHelperJoined", "compiler cleanup")
    if "compiler" in value:
        validate_compiler_shutdown(value["compiler"], require)
    if "cleanup" in value:
        validate_cleanup_shutdown(value["cleanup"], require)
    require(all(value[key] is True for key in ("clean", "telemetryFlushed", "epochHelperJoined")), "unclean-shutdown")
    require(all(type(value[key]) is int and value[key] == 0 for key in ZERO_SHUTDOWN_FIELDS), "live-transient-owners")
    integer(value["quarantinedCells"], 0, cells)
    integer(value["telemetryRetainedEntries"], 0, 65536)


def process_resources(value: Any) -> tuple[int, int]:
    fields(value, "identity process taskCount uniqueSocketCount listeningTcpSocketCount descendants sampleAttempts")
    identity = fields(value["identity"], "processId startTimeTicks")
    pid, start = integer(identity["processId"], 1), uint(identity["startTimeTicks"])
    require(start > 0, "invalid-process-start")
    process = fields(value["process"], "processId residentMemoryBytes threadCount openFileDescriptors socketCount")
    require(process["processId"] == pid and type(process["processId"]) is int, "crossed-process-identity")
    for key in ("residentMemoryBytes", "threadCount", "openFileDescriptors", "socketCount"):
        uint(process[key])
    require(uint(process["residentMemoryBytes"]) > 0 and uint(process["threadCount"]) > 0, "missing-process-observation")
    require(uint(value["taskCount"]) == uint(process["threadCount"]), "incoherent-task-count")
    require(uint(value["uniqueSocketCount"]) <= uint(process["socketCount"]) <= uint(process["openFileDescriptors"]), "incoherent-socket-count")
    require(uint(value["listeningTcpSocketCount"]) <= uint(value["uniqueSocketCount"]), "incoherent-listener-count")
    require(isinstance(value["descendants"], list) and len(value["descendants"]) <= 32, "invalid-descendant-observation")
    seen = {pid}
    for child in value["descendants"]:
        fields(child, "processId startTimeTicks")
        child_pid = integer(child["processId"], 1)
        require(child_pid not in seen and uint(child["startTimeTicks"]) > 0, "invalid-descendant-identity")
        seen.add(child_pid)
    integer(value["sampleAttempts"], 1, 3)
    return pid, start


class Samples:
    def __init__(self) -> None:
        self.identity: tuple[int, int] | None = None
        self.last_finished = 0
        self.values: list[dict[str, Any]] = []

    def check(self, sample: Any) -> None:
        fields(sample, "label started_micros finished_micros resources inventory backend ownership work")
        text(sample["label"], 128)
        started, finished = uint(sample["started_micros"]), uint(sample["finished_micros"])
        require(self.last_finished <= started <= finished, "invalid-sample-window")
        self.last_finished = finished
        identity = process_resources(sample["resources"])
        if self.identity is None:
            self.identity = identity
        require(identity == self.identity, "sample-process-changed")
        require(isinstance(sample["inventory"], dict) and isinstance(sample["backend"], dict)
                and isinstance(sample["work"], dict), "missing-runtime-observation")
        runtime_resources(sample)
        require(len(self.values) < 4096, "resource-sample-limit")
        self.values.append(sample)


def runtime_resources(sample: dict[str, Any]) -> None:
    inventory = fields(sample["inventory"], "nodeId observedAtUnixMillis queueDepth routeGeneration cellCapacity ready healthy cacheSummary quotas topology")
    text(inventory["nodeId"], 512)
    for key in ("observedAtUnixMillis", "queueDepth", "routeGeneration"):
        uint(inventory[key])
    require(type(inventory["ready"]) is bool and type(inventory["healthy"]) is bool, "invalid-health-observation")
    cells = inventory["cellCapacity"]
    require(isinstance(cells, list) and 1 <= len(cells) <= 5, "invalid-cell-observation")
    classes = set()
    for cell in cells:
        fields(cell, "class total available active quarantined queueDepth queuedTenants queueCapacity accepting granted rejected cancellations expired totalWaitMicros maxWaitMicros")
        require(cell["class"] not in classes and cell["class"] in ("tiny", "small", "standard", "large", "extra-large"), "invalid-cell-class")
        classes.add(cell["class"])
        for key in ("total", "available", "active", "quarantined", "queueDepth", "queuedTenants", "queueCapacity"):
            integer(cell[key])
        require(cell["available"] + cell["active"] + cell["quarantined"] == cell["total"]
                and cell["queuedTenants"] <= cell["queueDepth"] <= cell["queueCapacity"], "incoherent-cell-counts")
        require(type(cell["accepting"]) is bool, "invalid-cell-accepting")
        for key in ("granted", "rejected", "cancellations", "expired", "totalWaitMicros", "maxWaitMicros"):
            uint(cell[key])
    require(sum(cell["queueDepth"] for cell in cells) == uint(inventory["queueDepth"]), "incoherent-queue-depth")
    cache = fields(inventory["cacheSummary"], "available entries maximumEntries sourceBytes maximumSourceBytes metadataBytes maximumMetadataBytes compiledImageBytes maximumCompiledImageBytes preparing maximumConcurrentPreparations preparingSourceBytes preparingMetadataBytes hits misses evictions invalidations")
    require(cache["available"] is True, "missing-cache-observation")
    for key, value in cache.items():
        if key != "available":
            uint(value)
    for current, maximum in (("entries", "maximumEntries"), ("sourceBytes", "maximumSourceBytes"),
                             ("metadataBytes", "maximumMetadataBytes"), ("compiledImageBytes", "maximumCompiledImageBytes"),
                             ("preparing", "maximumConcurrentPreparations")):
        require(uint(cache[current]) <= uint(cache[maximum]), "cache-limit-exceeded")
    quotas = fields(inventory["quotas"], "retainedTenants usage")
    uint(quotas["retainedTenants"])
    usage = fields(quotas["usage"], "activeActivations queuedActivations reservedCpuFuel reservedMemoryBytes")
    integer(usage["activeActivations"])
    integer(usage["queuedActivations"])
    uint(usage["reservedCpuFuel"])
    uint(usage["reservedMemoryBytes"])
    topology = fields(inventory["topology"], "available complete entries")
    require(topology["available"] is True and topology["complete"] is True, "missing-topology-observation")
    require(isinstance(topology["entries"], list) and 1 <= len(topology["entries"]) <= 64, "invalid-topology-entries")
    names = set()
    for entry in topology["entries"]:
        fields(entry, "name kind ownership configuredCount activeCount attributes")
        name = text(entry["name"], 512)
        require(name not in names, "duplicate-topology-entry")
        names.add(name)
        text(entry["kind"], 128)
        require(entry["ownership"] in ("node-fixed", "activation-scoped", "service-resident"), "invalid-topology-ownership")
        uint(entry["configuredCount"])
        if entry["activeCount"] is not None:
            uint(entry["activeCount"])
        require(isinstance(entry["attributes"], dict), "invalid-topology-attributes")
    backend = fields(sample["backend"], "active_invocations live_stores live_host_states live_component_instances live_temporary_buffers live_cancellation_probes stores_created")
    for value in backend.values():
        uint(value)
    ownership = fields(sample["ownership"], "cancellation journal observer sink pipeline")
    required = {
        "cancellation": "active_registrations",
        "journal": "active terminal reserved_bytes retained_bytes evicted begun completed maximum_active maximum_terminal maximum_record_bytes maximum_retained_bytes",
        "observer": "active_correlations maximum_active_correlations received completed guest_logs observations_dropped capacity_drops invalid_records unknown_correlations submission_errors panics",
        "sink": "entries retained_bytes maximum_entries maximum_bytes evicted_entries dropped_oversized",
        "pipeline": "queue_depth queue_capacity accepted exported dropped_queue_full dropped_queue_closed dropped_invalid_record sink_failures sink_timeouts flush_timeouts shutdown_timeouts worker_panics",
    }
    for name, names in required.items():
        fields(ownership[name], names)
        for value in ownership[name].values():
            uint(value)
    for name, current, maximum in (("journal", "active", "maximum_active"), ("journal", "terminal", "maximum_terminal"),
                                   ("journal", "retained_bytes", "maximum_retained_bytes"),
                                   ("observer", "active_correlations", "maximum_active_correlations"),
                                   ("sink", "entries", "maximum_entries"), ("sink", "retained_bytes", "maximum_bytes"),
                                   ("pipeline", "queue_depth", "queue_capacity")):
        require(uint(ownership[name][current]) <= uint(ownership[name][maximum]), "retained-owner-limit-exceeded")
    journal = ownership["journal"]
    require(uint(journal["reserved_bytes"]) + uint(journal["retained_bytes"]) <= uint(journal["maximum_retained_bytes"]),
            "journal-total-limit-exceeded")


def idle(sample: dict[str, Any], *, dormant: bool = False) -> None:
    inventory, backend = sample["inventory"], sample["backend"]
    require(all(uint(value) == 0 for key, value in backend.items() if key != "stores_created"), "backend-not-idle")
    require(uint(inventory["queueDepth"]) == 0 and all(cell["active"] == 0 and cell["queueDepth"] == 0
            for cell in inventory["cellCapacity"]), "scheduler-not-idle")
    require(all((value == 0 if type(value) is int else uint(value) == 0)
                for value in inventory["quotas"]["usage"].values()), "quota-not-idle")
    cache = inventory["cacheSummary"]
    require(all(uint(cache[key]) == 0 for key in ("preparing", "preparingSourceBytes", "preparingMetadataBytes")), "preparation-not-idle")
    ownership = sample["ownership"]
    require(uint(ownership["cancellation"]["active_registrations"]) == 0 and uint(ownership["journal"]["active"]) == 0
            and uint(ownership["journal"]["reserved_bytes"]) == 0 and uint(ownership["observer"]["active_correlations"]) == 0,
            "activation-owner-not-idle")
    if dormant:
        require(uint(backend["stores_created"]) == 0, "dormant-store-created")
        require(all(uint(cache[key]) == 0 for key in ("entries", "sourceBytes", "metadataBytes", "compiledImageBytes", "hits", "misses")), "dormant-execution-cache")


def fixed_topology(sample: dict[str, Any]) -> dict[str, Any]:
    observed = sample["resources"]
    return {"process_identity": observed["identity"], "tasks": observed["taskCount"],
            "descendants": observed["descendants"], "sockets": observed["uniqueSocketCount"],
            "listeners": observed["listeningTcpSocketCount"],
            "cells": [{key: cell[key] for key in ("class", "total", "queueCapacity")}
                      for cell in sample["inventory"]["cellCapacity"]],
            "ownership": [{key: entry[key] for key in ("name", "kind", "ownership", "configuredCount")}
                          for entry in sample["inventory"]["topology"]["entries"]]}
