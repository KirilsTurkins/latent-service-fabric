"""Finite resource campaign profiles and fail-closed, population-aware checks."""
from __future__ import annotations

import hashlib
import json
import math
import re

from tools.phase2_operator_process import require


SCHEMA = "latent.phase3.resource-campaign.v2"
PROFILES = {
    "smoke": {"id": "phase3-resource-smoke-v2", "kind": "provider", "dormantSteps": [4, 16], "cells": 1,
              "policyReadOwners": 64,
              "samplesPerPhase": 3, "cycles": 2, "arrivalsPerCycle": 8,
              "arrivalIntervalMillis": 10, "maximumOutstanding": 6, "deadlineSeconds": 240},
    "campaign": {"id": "phase3-resource-manual-v2", "kind": "provider", "dormantSteps": [4, 16, 32], "cells": 2,
                 "policyReadOwners": 96,
                 "samplesPerPhase": 5, "cycles": 8, "arrivalsPerCycle": 24,
                 "arrivalIntervalMillis": 5, "maximumOutstanding": 8, "deadlineSeconds": 900},
    "web-smoke": {"id": "phase3-resource-web-smoke-v1", "kind": "web", "dormantSteps": [2, 4], "cells": 1,
                  "samplesPerPhase": 3, "cycles": 2, "arrivalsPerCycle": 4,
                  "arrivalIntervalMillis": 10, "maximumOutstanding": 5, "deadlineSeconds": 600},
    "web-campaign": {"id": "phase3-resource-web-manual-v1", "kind": "web", "dormantSteps": [2, 4, 8], "cells": 2,
                     "samplesPerPhase": 3, "cycles": 4, "arrivalsPerCycle": 8,
                     "arrivalIntervalMillis": 5, "maximumOutstanding": 6, "deadlineSeconds": 900},
}
LIMITS = {"maximumControls": 1024, "maximumSamples": 2048, "maximumReceiptBytes": 8388608,
          "maximumFixtureFiles": 4096, "maximumFixtureBytes": 134217728,
          "maximumFileBytes": 536870912, "maximumProcBytes": 4194304,
          "maximumProcesses": 16, "maximumTasks": 256, "maximumDescriptors": 4096,
          "maximumNetworkRows": 8192, "sampleSeconds": 2, "shutdownSeconds": 10}
ACTIVE_COUNTERS = ("broker_sessions", "broker_handles", "broker_calls", "broker_results",
                   "broker_buffer_bytes", "pool_active_connections", "pool_connecting_connections",
                   "pool_pending_requests", "pool_running_requests", "pool_workers", "pool_cleanup_jobs",
                   "io_calls", "io_occupied_running_slots", "io_queued_calls", "io_staged_bytes",
                   "io_result_bytes", "io_buffers", "io_streams")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def policy_capacity(profile):
    required = 2 * (profile["dormantSteps"][-1] + 2) + 2
    require(required <= profile["policyReadOwners"] <= 128, "resource-policy-snapshot-capacity")
    return {"configuredReadOwners": profile["policyReadOwners"], "requiredReadOwners": required,
            "basis": "live-and-staged-capability-plans-plus-two-observation-owners",
            "mutationResponseOwnersSeparate": 4}


def integer(value):
    require(type(value) is int or isinstance(value, str) and
            re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is not None, "resource-integer")
    result = int(value)
    require(0 <= result < 2**64, "resource-integer-range")
    return result


def summary(values):
    require(bool(values) and all(type(value) in (int, float) and math.isfinite(value)
                                and value >= 0 for value in values), "resource-empty-distribution")
    ordered = sorted(values)
    return {"count": len(ordered), "minimum": ordered[0], "maximum": ordered[-1],
            "p50": ordered[math.ceil(len(ordered) * 0.5) - 1],
            "p95": ordered[math.ceil(len(ordered) * 0.95) - 1]}


def validate_schedule(rows, expected, interval_ns=None):
    require(len(rows) == expected and expected > 0, "resource-arrival-population")
    require([row["ordinal"] for row in rows] == list(range(expected)), "resource-arrival-identities")
    previous = -1
    for row in rows:
        planned = integer(row["scheduledNanos"])
        require(planned >= previous, "resource-arrival-order")
        previous = planned
        require(interval_ns is None or planned == row["ordinal"] * interval_ns, "resource-arrival-origin")
        require(row["disposition"] in ("completed", "client-shed"), "resource-arrival-unfinished")
        if row["disposition"] == "client-shed":
            require(row["startedNanos"] is None and row["finishedNanos"] is None
                    and row["reason"] == "outstanding-bound", "resource-shed-not-attempt")
        else:
            started, finished = integer(row["startedNanos"]), integer(row["finishedNanos"])
            require(planned <= started <= finished and row["ownerReaped"] is True,
                    "resource-arrival-ownership")
            require(row["result"]["category"] in ("success", "declared-error", "platform-failure",
                                                    "transport-failure", "interrupted"),
                    "resource-arrival-outcome")
    require(any(row["disposition"] == "completed" for row in rows), "resource-no-attempts")
    return True


def quiescent(sample):
    inventory = sample["inventory"]
    cells = inventory["cellCapacity"]
    require(bool(cells) and all(cell["observationAvailable"] is True for cell in cells),
            "resource-cells-unobservable")
    counts = [integer(inventory["queueDepth"])]
    counts += [integer(cell[key]) for cell in cells for key in ("active", "quarantined", "queueDepth")]
    cache = inventory["cacheSummary"]
    require(cache["available"] is True, "resource-cache-unobservable")
    counts += [integer(cache[key]) for key in ("preparing", "preparingSourceBytes", "preparingMetadataBytes")]
    if sample["capabilities"] is not None:
        usage = sample["capabilities"]["nodeUsage"]
        require(not usage["unavailable"], "resource-provider-unobservable")
        require(all(key in usage["counters"] for key in ACTIVE_COUNTERS), "resource-provider-counters")
        counts += [integer(usage["counters"][key]) for key in ACTIVE_COUNTERS]
    return not any(counts)


def validate_receipt(value):
    require(value["schemaVersion"] == SCHEMA and value["status"] == "checkpoint-passed",
            "resource-receipt-not-passed")
    profile = value["profile"]
    require(profile in PROFILES.values() and value["profileDigest"] == digest(profile), "resource-profile")
    require(value["ticketAcceptance"] == "pending" and value["limits"] == LIMITS,
            "resource-scope-escalation")
    require(value["configurationDigest"] == digest(value["configuration"]), "resource-configuration-digest")
    require(value["build"]["binaries"] == value["observedBinaries"], "resource-binary-association")
    if profile["kind"] == "provider":
        require(value["policyCapacity"] == policy_capacity(profile), "resource-policy-capacity-evidence")
    else:
        from tools.phase3_resource_web import validate_web
        return validate_web(value)
    samples = value["samples"]
    require(0 < len(samples) <= LIMITS["maximumSamples"], "resource-sample-population")
    phases = {sample["phase"] for sample in samples}
    require({"fixed", "dormant", "warm", "active", "recovery", "unrouted"} <= phases,
            "resource-missing-phase")
    for phase in ("fixed", "dormant", "warm", "recovery", "unrouted"):
        selected = [sample for sample in samples if sample["phase"] == phase]
        require(len(selected) >= profile["samplesPerPhase"] and all(quiescent(sample) for sample in selected),
                "resource-phase-not-quiescent")
    for sample in samples:
        require(sample["os"]["identity"] == value["nodeIdentity"], "resource-sample-owner")
        require(integer(sample["os"]["metrics"]["processes"]) >= 1, "resource-empty-process-population")
        require(sample["os"]["metrics"]["rssBytes"] is not None, "resource-rss-unobservable")
    for cycle in value["cycles"]:
        validate_schedule(cycle["arrivals"], profile["arrivalsPerCycle"], profile["arrivalIntervalMillis"] * 1_000_000)
    require(len(value["cycles"]) == profile["cycles"], "resource-cycle-population")
    require(value["shutdown"]["reaped"] is True and value["shutdown"]["record"]["clean"] is True,
            "resource-node-not-reaped")
    require(value["peerShutdown"]["reaped"] is True and value["temporaryOutputsRemoved"] is True,
            "resource-runner-not-reaped")
    require(value["fixtureUnchanged"] is True, "resource-fixture-changed")
    from tools.phase3_resource_analysis import analyze
    from tools.phase3_resource_workload import overload_counts
    declared = value["checks"].copy()
    analyze(value)
    require(value["checks"] == declared and all(type(check) is bool and check for check in declared.values()),
            "resource-checks-incomplete")
    require(value["overloadClassification"] == overload_counts(value["overload"]), "resource-overload-evidence")
    for requested in profile["dormantSteps"]:
        require(sum(sample["phase"] == "dormant" and sample["dormantDeployments"] == requested
                    for sample in samples) == profile["samplesPerPhase"], "resource-density-sample-population")
    require(sum(sample["phase"] == "recovery" for sample in samples)
            == profile["cycles"] * profile["samplesPerPhase"], "resource-recovery-sample-population")
    require(len(canonical(value)) <= LIMITS["maximumReceiptBytes"], "resource-receipt-bound")
    return True
