"""Frozen Phase 2 resource profile and bounded evidence validation."""
from __future__ import annotations

import hashlib
import json
import re

from tools.phase2_operator_process import require
from tools.phase2_operator_scenario import NODE_ID, TOKEN

PROFILE = {
    "id": "phase2-dormant-32-r1", "preparation": "portable", "releases": 32,
    "deployments": 16, "referencedReleases": 2, "invocations": 32,
    "maximumControls": 256, "deadlineSeconds": 300, "shutdownSeconds": 10,
    "osSamples": 12, "samplesPerPhase": 3, "sampleIntervalMillis": 50,
    "settleAttempts": 10, "settleIntervalMillis": 100,
    "maximumReceiptBytes": 262144,
    "maximumFixtureFiles": 2048, "maximumFixtureBytes": 8388608,
    "maximumBinaryBytes": 536870912,
    "proc": {"fileBytes": 65536, "fds": 4096, "tasks": 256,
             "networkBytes": 1048576, "networkRows": 8192, "sampleSeconds": 2},
}
PHASES = ("baseline", "dormant", "reclaimed", "unrouted")
ZERO_ROWS = (
    "execution-cell-leases", "prepared-instance-reservations", "guest-invocations",
    "guest-stores", "guest-host-states", "guest-component-instances",
    "guest-value-buffers", "guest-cancellation-probes", "invocation-cleanup-slots",
    "rollout-control-commands", "canary-observation-windows", "canary-retained-samples",
    "canary-live-samples", "canary-snapshot-owners",
    "resident-service-processes", "resident-service-threads", "resident-service-listeners",
)
OBSERVATION_ROWS = ("accepted-connections", "in-flight-rpcs", "control-jobs")
FIXED_LIVE_ROWS = ("standalone-node", "wasmtime-compiler", "invocation-cleanup-driver",
                   "rollout-coordinator")
FIXED_RUNTIME_ROWS = ("invocation-runtime", "control-runtime")
FIXED_UNKNOWN_ROWS = ("wasmtime-epoch", "grpc-listener")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value),
            "identity-digest")
    return value


def integer(value):
    require(not isinstance(value, bool) and
            (isinstance(value, int) or isinstance(value, str) and
             re.fullmatch(r"0|[1-9][0-9]{0,19}", value)), "counter-shape")
    result = int(value)
    require(0 <= result < 2**64, "counter-range")
    return result


def configuration(tenant):
    return {
        "formatVersion": 1, "dataDirectory": "data", "nodeId": NODE_ID,
        "bind": "127.0.0.1:0", "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2,
                   "maximumMemoryBytes": 67108864}],
        "execution": {"maximumCpuFuel": 10000000000, "maximumWallTimeMillis": 5000,
                      "maximumLogBytes": 16384},
        "cache": {"entries": 2, "preparations": 1},
        "catalogs": {"releaseEntries": 64, "deployments": 32},
        "retention": {"terminalEntries": 32, "terminalTtlMillis": 30000},
        "shutdownGraceMillis": 1000,
        "supplyChain": {"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": 5},
        "audit": {"mode": "durable", "records": 512, "diskBytes": 8388608,
                  "queuedOperations": 8, "queryOwners": 2},
        "rollouts": {"mode": "manual", "active": 2, "retained": 8, "stages": 4,
                     "receipts": 32, "metadataBytes": 1048576, "queuedOperations": 2,
                     "queuedBytes": 262144, "queryOwners": 2,
                     "canary": {"windows": 2, "samplesPerWindow": 32, "totalSamples": 64,
                                "liveSamples": 4, "snapshotOwners": 2}},
        "credentials": [{"token": TOKEN, "subject": "workflow-operator", "tenant": tenant,
                         "role": "operator"}],
    }


def quiet(inventory):
    require(inventory["topology"]["available"] and inventory["topology"]["complete"],
            "inventory-topology-unavailable")
    require(inventory["cacheSummary"]["available"], "inventory-cache-unavailable")
    rows = {row["name"]: row for row in inventory["topology"]["entries"]}
    require(len(rows) == len(inventory["topology"]["entries"]), "inventory-duplicate-row")
    require(all(name in rows and rows[name]["activeCount"] is not None
                for name in ZERO_ROWS + OBSERVATION_ROWS), "inventory-row-unavailable")
    require(set(rows) == set(ZERO_ROWS + OBSERVATION_ROWS + FIXED_LIVE_ROWS +
                            FIXED_RUNTIME_ROWS + FIXED_UNKNOWN_ROWS), "inventory-fixed-rows")
    for name in FIXED_LIVE_ROWS + FIXED_RUNTIME_ROWS + FIXED_UNKNOWN_ROWS:
        row = rows[name]
        maximum = 2 if name in FIXED_RUNTIME_ROWS else 1
        require(row["ownership"] == "node-fixed" and integer(row["configuredCount"]) == maximum,
                "inventory-fixed-profile")
        if name in FIXED_UNKNOWN_ROWS:
            # These two native inventory sources intentionally expose no live
            # count. The independently owned OS samples supply that evidence.
            require(row["activeCount"] is None, "inventory-fixed-profile")
        else:
            require(row["activeCount"] is not None
                    and 1 <= integer(row["activeCount"]) <= maximum, "inventory-fixed-unavailable")
    for row in rows.values():
        if row["activeCount"] is not None:
            require(integer(row["activeCount"]) <= integer(row["configuredCount"]),
                    "inventory-resource-limit")
    values = [integer(rows[name]["activeCount"]) for name in ZERO_ROWS]
    # Node.Get observes its own bounded connection/RPC/control slot. This is
    # preserved explicitly; OS snapshots are taken after that caller is reaped.
    observation = all(integer(rows[name]["activeCount"]) <= 1 for name in OBSERVATION_ROWS)
    values += [integer(inventory["queueDepth"])]
    values += [integer(inventory["cacheSummary"][name])
               for name in ("preparing", "preparingSourceBytes", "preparingMetadataBytes")]
    values += [integer(inventory["quotas"]["usage"][name]) for name in (
        "activeActivations", "queuedActivations", "reservedCpuFuel", "reservedMemoryBytes")]
    require(len(inventory["cellCapacity"]) == 1, "inventory-cell-profile")
    cell = inventory["cellCapacity"][0]
    require(cell["observationAvailable"] and cell["total"] == 1, "inventory-cell-unavailable")
    values += [integer(cell[name]) for name in ("active", "quarantined", "queueDepth", "queuedTenants")]
    cache = inventory["cacheSummary"]
    require(integer(cache["entries"]) <= 2 and integer(cache["maximumEntries"]) == 2,
            "inventory-cache-profile")
    for actual, ceiling in (("sourceBytes", "maximumSourceBytes"),
                            ("metadataBytes", "maximumMetadataBytes"),
                            ("compiledImageBytes", "maximumCompiledImageBytes")):
        require(integer(cache[actual]) <= integer(cache[ceiling]), "inventory-cache-bound")
    return observation and not any(values)


def compact_inventory(inventory):
    # Exclude node addresses, arbitrary attributes, endpoint identities and logs.
    require(quiet(inventory), "inventory-not-quiescent")
    return {key: inventory[key] for key in (
        "queueDepth", "routeGeneration", "cacheSummary", "cellCapacity", "quotas", "topology")}


def shutdown_report(report):
    require(report["clean"] and report["telemetryFlushed"] and report["epochHelperJoined"],
            "shutdown-not-clean")
    zero = ("activeConnections", "activeRpcs", "activeControlJobs", "activeActivations",
            "cancellationRegistrations", "observerCorrelations", "quotaReservations",
            "queuedReservations", "reservedCpuFuel", "reservedMemoryBytes", "activeLeases",
            "queuedActivations", "quarantinedCells", "activeBackendInvocations",
            "instanceReservations", "preparingComponents", "preparingSourceBytes",
            "preparingMetadataBytes", "liveStores", "liveHostStates", "liveInstances",
            "liveTemporaryBuffers", "liveCancellationProbes")
    require(all(integer(report[name]) == 0 for name in zero), "shutdown-active-owner")
    compiler = report["compiler"]
    require(not compiler["accepting"] and not compiler["failed"]
            and integer(compiler["workers_joined"]) == integer(compiler["maximum_workers"]) == 1
            and integer(compiler["workers_quiescent"]) == 1,
            "shutdown-compiler-join")
    require(all(integer(compiler[name]) == 0 for name in (
        "assigned_jobs", "running_jobs", "queued_jobs", "waiting_callers",
        "ready_preparations", "ready_metadata_bytes", "ready_compiled_image_bytes",
        "reserved_document_bytes", "workers_live")), "shutdown-compiler-owner")
    cleanup = report["cleanup"]
    require(cleanup["driverJoined"] and not cleanup["driverAlive"]
            and not cleanup["accepting"] and not cleanup["failed"], "shutdown-cleanup-join")
    require(all(integer(cleanup[name]) == 0 for name in (
        "reserved", "queued", "running", "timedOut", "panicked", "fallbacks"))
        and integer(cleanup["handoffs"]) == integer(cleanup["completed"]),
            "shutdown-cleanup-owner")
    audit = report["audit"]
    require(audit["workerJoined"] and not audit["recoveryPending"], "shutdown-audit-join")
    require(all(integer(audit[name]) == 0 for name in (
        "queuedOperations", "queryOwners", "queryBytes", "pendingAttempts",
        "reservedRecords", "stageBytes")), "shutdown-audit-owner")
    rollout = report["rollouts"]
    require(rollout["workerJoined"] and not rollout["workerLive"] and not rollout["failed"],
            "shutdown-rollout-join")
    require(all(integer(rollout[name]) == 0 for name in (
        "queuedCommands", "activeCommands", "retainedRequestBytes",
        "responseOwners", "responseBytes")), "shutdown-rollout-owner")
    require(all(integer(rollout["canary"][name]) == 0 for name in (
        "retainedWindows", "retainedSamples", "liveSamples", "snapshotOwners")),
            "shutdown-canary-owner")
    return report


def validate_receipt(value):
    require(len(canonical(value)) <= PROFILE["maximumReceiptBytes"], "receipt-bound")
    require(value["schemaVersion"] == "latent.phase2.resource-receipt.v1"
            and value["profile"] == PROFILE and value["profileDigest"] == digest(PROFILE),
            "receipt-profile")
    require(value["passed"] is True and value["syntheticTestEvidence"] is True,
            "receipt-not-passing")
    build = value["build"]
    require(build["schemaVersion"] == "latent.phase2.resource-build.v1"
            and re.fullmatch(r"[0-9a-f]{40}", build["sourceRevision"]), "receipt-build")
    for field in ("cargoLockSha256", "cliSha256", "nodeSha256"):
        sha(build[field])
    require(build["buildProfile"] in ("debug", "release")
            and re.fullmatch(r"rustc [A-Za-z0-9 .()+_-]{1,120}", build["rustcVersion"]),
            "receipt-build-tool")
    for field in ("configurationDigest", "fixtureInventoryDigest", "fixtureMetadataDigest",
                  "policyFileDigest"):
        sha(value[field])
    require(len(value["collectorSources"]) == 12
            and len({row["path"] for row in value["collectorSources"]}) == 12,
            "receipt-collector-identity")
    for row in value["collectorSources"]:
        sha(row["digest"])
    public = configuration("tests")
    expected_digest = digest(public)
    public["credentials"] = [{key: val for key, val in row.items() if key != "token"}
                             for row in public["credentials"]]
    require(value["configuration"] == public and value["configurationDigest"] == expected_digest,
            "receipt-configuration")
    require(value["host"]["system"] == "Linux" and integer(value["host"]["pageSize"]) > 0
            and integer(value["host"]["clockTicks"]) > 0, "receipt-host")
    require(0 < integer(value["controls"]) <= PROFILE["maximumControls"],
            "receipt-control-bound")
    require(integer(value["elapsedMillis"]) <= 310000, "receipt-deadline")
    require(len(value["packages"]) == 32 and len({sha(p["componentDigest"]) for p in value["packages"]}) == 32
            and len({sha(p["packageDigest"]) for p in value["packages"]}) == 32, "receipt-packages")
    invocations = value["invocations"]
    allowed = {p["componentDigest"] for p in value["packages"][:2]}
    require(value["invokeAttempts"] == 32 and len(invocations) == 32
            and all(row["releaseDigest"] in allowed for row in invocations),
            "receipt-invocations")
    require([row["releaseDigest"] for row in invocations[:2]] ==
            [row["componentDigest"] for row in value["packages"][:2]], "receipt-warm-identities")
    samples = value["samples"]
    require(len(samples) == 12 and [s["phase"] for s in samples] ==
            [phase for phase in PHASES for _ in range(3)], "receipt-samples")
    baseline = samples[0]
    fixed = ("threads", "tasks", "fdCount", "socketCount", "listeningTcpSockets", "descendants")
    first_rows = baseline["inventory"]["topology"]["entries"]
    preparation_misses = integer(baseline["inventory"]["cacheSummary"]["misses"])
    require(preparation_misses == 2, "receipt-warm-preparations")
    previous_time = None
    previous_cumulative = None
    for item in samples:
        require(quiet(item["inventory"]), "receipt-active-inventory")
        observed = item["os"]
        require(observed["processId"] == value["process"]["processId"] and
                observed["startTimeTicks"] == value["process"]["startTimeTicks"], "receipt-process")
        for field in ("observedMonotonicNanos", "rssBytes", "kernelHighWaterRssBytes",
                      "cpuUserTicks", "cpuSystemTicks", "readBytes", "writeBytes"):
            integer(observed[field])
        sample_time = integer(observed["observedMonotonicNanos"])
        require(previous_time is None or sample_time - previous_time >=
                PROFILE["sampleIntervalMillis"] * 1000000, "receipt-sample-time")
        previous_time = sample_time
        cumulative = [integer(observed[key]) for key in (
            "cpuUserTicks", "cpuSystemTicks", "readBytes", "writeBytes", "kernelHighWaterRssBytes")]
        require(previous_cumulative is None or all(after >= before for before, after in
                zip(previous_cumulative, cumulative)), "receipt-counter-regression")
        previous_cumulative = cumulative
        require(0 < integer(observed["threads"]) == integer(observed["tasks"]) <= PROFILE["proc"]["tasks"]
                and 0 < integer(observed["socketCount"]) <= integer(observed["fdCount"]) <= PROFILE["proc"]["fds"]
                and 0 < integer(observed["procBytesRead"]) <= 4 * 1024 * 1024, "receipt-proc-bounds")
        require(integer(item["inventory"]["cacheSummary"]["misses"]) == preparation_misses,
                "receipt-unexpected-preparation")
        warm = item["phase"] in ("baseline", "dormant")
        require(integer(item["inventory"]["cellCapacity"][0]["granted"]) == (2 if warm else 32)
                and integer(item["inventory"]["cacheSummary"]["hits"]) == (0 if warm else 30),
                "receipt-phase-invocations")
        expected_route = (invocations[1]["routeGeneration"] if item["phase"] == "baseline" else
                          value["catalog"]["unroutedGeneration"] if item["phase"] == "unrouted" else
                          value["catalog"]["dormantRouteGeneration"])
        require(item["inventory"]["routeGeneration"] == expected_route, "receipt-phase-route")
        require(observed["descendants"] == 0 and observed["listeningTcpSockets"] == 1,
                "receipt-process-topology")
        require(all(observed[key] == baseline["os"][key] for key in fixed),
                "receipt-topology-growth")
        rows = item["inventory"]["topology"]["entries"]
        require(len(rows) == len(first_rows), "receipt-topology-shape")
        for before, after in zip(first_rows, rows):
            require((before["name"], before["configuredCount"], before["ownership"]) ==
                    (after["name"], after["configuredCount"], after["ownership"]), "receipt-topology-shape")
            if before["name"] not in OBSERVATION_ROWS:
                require(before["activeCount"] == after["activeCount"], "receipt-fixed-owner-growth")
    require(value["catalog"]["peakReleases"] == 32 and value["catalog"]["peakDeployments"] == 16
            and value["catalog"]["remainingDeployments"] == 0
            and value["catalog"]["retainedReleases"] == 32, "receipt-catalog")
    require(integer(samples[-1]["os"]["observedMonotonicNanos"]) -
            integer(samples[0]["os"]["observedMonotonicNanos"]) <=
            integer(value["elapsedMillis"]) * 1000000, "receipt-sample-elapsed")
    require(all(row["routeGeneration"] == value["catalog"]["dormantRouteGeneration"]
                for row in invocations[2:]), "receipt-cohort-route")
    require(integer(value["catalog"]["unroutedGeneration"]) >
            integer(value["catalog"]["dormantRouteGeneration"]), "receipt-route-monotonic")
    require(value["process"]["executableDigest"] == build["nodeSha256"]
            and value["process"]["ownedProcessGroup"] == value["process"]["processId"],
            "receipt-executable")
    require(value["process"]["exitedSuccessfully"] and value["process"]["reapedByOwner"]
            and value["temporaryOutputsRemoved"], "receipt-reap")
    shutdown_report(value["shutdown"])
    compiler = value["shutdown"]["compiler"]
    require(integer(compiler["jobs_started"]) == integer(compiler["jobs_completed"]) == 2
            and integer(compiler["jobs_failed"]) == integer(compiler["jobs_abandoned"]) == 0,
            "receipt-compiler-work")
