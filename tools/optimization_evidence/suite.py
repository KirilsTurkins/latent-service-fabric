"""Validate retained runs and deterministically aggregate descriptive contrasts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from tools.optimization_runner.plans import SERVICES, TENANT, TOKEN
from . import client, identity, resources
from .artifacts import Artifacts
from .common import DOCUMENT_BYTES, canonical, distribution, fields, hash_file, integer, read_json, require, sha256, text, uint

RUN_FIELDS = ("repetition arm scenario status reason started_micros finished_micros batches "
              "server_process configuration cleanup lifecycle")
BATCH_FIELDS = "id plan readiness attempts summary client_process resources"
ZERO_SHUTDOWN = (
    "activeConnections activeRpcs activeControlJobs activeActivations cancellationRegistrations "
    "observerCorrelations quotaReservations queuedReservations reservedCpuFuel reservedMemoryBytes "
    "activeLeases queuedActivations activeBackendInvocations instanceReservations preparingComponents "
    "preparingSourceBytes preparingMetadataBytes liveStores liveHostStates liveInstances "
    "liveTemporaryBuffers liveCancellationProbes"
).split()


def shutdown(value, arm):
    require(isinstance(value, dict) and value.get("event") == "stopped"
            and value.get("clean") is True, "missing-clean-shutdown")
    if arm == "native":
        fields(value, "event clean implementation")
        require(value["implementation"] == "native-reference", "crossed-shutdown-implementation")
        return
    fields(value, "schemaVersion event clean report")
    require(value["schemaVersion"] == "latent.standalone.status.v1", "invalid-lsf-shutdown-schema")
    report = fields(value["report"], "clean telemetryFlushed epochHelperJoined quarantinedCells telemetryRetainedEntries "
                    + " ".join(ZERO_SHUTDOWN))
    require(report["clean"] is True and report["telemetryFlushed"] is True
            and report["epochHelperJoined"] is True, "unacknowledged-lsf-cleanup")
    for name in ZERO_SHUTDOWN:
        integer(report[name], 0, 0)
    integer(report["quarantinedCells"], 0, 4)
    integer(report["telemetryRetainedEntries"], 0, 1_000_000)


def configuration(value, arm):
    if arm == "native":
        require(value == {"listen": "127.0.0.1:0", "tenant": TENANT, "services": SERVICES,
                          "concurrency": 4, "runtime_workers": 2, "timeout_millis": 5000,
                          "token_kind": "public-local-benchmark-fixture"}, "changed-native-controls")
        return
    fields(value, "formatVersion dataDirectory nodeId bind workers cells execution limits cache catalogs retention "
                  "shutdownGraceMillis credentials")
    text(value["dataDirectory"])
    expected = {
        "formatVersion": 1, "nodeId": "optimization-node", "bind": "127.0.0.1:0",
        "workers": {"runtime": 2, "control": 2},
        "cells": [{"class": "standard", "capacity": 4, "queueCapacity": 64, "maximumMemoryBytes": 67_108_864}],
        "execution": {"maximumCpuFuel": 10_000_000_000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16_384},
        "limits": {"maximumPayloadBytes": 1_048_576, "maximumConnections": 32},
        "cache": {"entries": 4, "preparations": 1},
        "catalogs": {"releaseEntries": 16, "deployments": 16},
        "retention": {"terminalEntries": 1024, "terminalTtlMillis": 30_000},
        "shutdownGraceMillis": 1000,
        "credentials": [{"token": TOKEN, "subject": "optimization-reference", "tenant": TENANT, "role": "operator"}],
    }
    require({key: item for key, item in value.items() if key != "dataDirectory"} == expected,
            "changed-lsf-controls")


def lifecycle(value, arm, duration):
    fields(value, "process_start_to_ready_micros process_start_to_first_response_observed_micros "
                  "ready_to_first_response_observed_micros first_response_observation initial_preparation")
    ready = uint(value["process_start_to_ready_micros"])
    first = uint(value["process_start_to_first_response_observed_micros"])
    following = uint(value["ready_to_first_response_observed_micros"])
    require(0 < ready <= first <= duration and 0 <= first - ready - following <= 1,
            "invalid-first-response-window")
    require(value["first_response_observation"] ==
            "parent-received-client-event-upper-bound-includes-client-startup-and-connect"
            and value["initial_preparation"] == ("included-in-first-call" if arm == "lsf" else "not-applicable"),
            "changed-cold-start-boundary")


def validate_suite(path: Path) -> dict:
    path = Path(path)
    suite_digest = hash_file(path, DOCUMENT_BYTES)
    suite = read_json(path)
    require(hash_file(path, DOCUMENT_BYTES) == suite_digest, "suite-changed-during-read")
    fields(suite, "schema profile plan identity runs artifacts")
    require(suite["schema"] == "latent.optimization.suite.v1", "invalid-suite-schema")
    identity.plan(suite["plan"])
    require(suite["profile"] == suite["plan"]["profile"], "crossed-suite-profile")
    executable_refs = suite["identity"].get("executables", {})
    require(isinstance(executable_refs, dict), "missing-executables")
    artifacts = Artifacts(path.parent, suite["artifacts"],
                          {item["path"] for item in executable_refs.values()})
    require(sum(uint(item["bytes"]) for item in suite["artifacts"]) <= uint(suite["plan"]["maximum_artifact_bytes"]),
            "suite-artifact-budget-exceeded")
    identity.identity(suite["identity"], artifacts, suite["profile"] == "full")
    components = dict(zip(SERVICES, (item["sha256"] for item in suite["identity"]["components"]), strict=True))
    expected = [(rep, arm) for rep in range(1, suite["plan"]["repetitions"] + 1)
                for arm in (("native", "lsf") if rep % 2 else ("lsf", "native"))]
    runs = suite["runs"]
    require(isinstance(runs, list) and len(runs) <= len(expected), "invalid-run-count")
    identities, activation_ids = set(), set()
    result, failed, prior_end, attempts = [], False, 0, 0
    case_templates = suite["plan"]["cases"]
    for ordinal, run in enumerate(runs):
        fields(run, RUN_FIELDS)
        require((run["repetition"], run["arm"]) == expected[ordinal] and run["scenario"] == "cold-restart",
                "changed-pair-order-or-duplicate-run")
        integer(run["repetition"], 1, 7)
        require(run["status"] in ("passed", "failed")
                and run["reason"] == (None if run["status"] == "passed" else "collector-failed"),
                "invalid-run-status")
        start, finish = uint(run["started_micros"]), uint(run["finished_micros"])
        require(prior_end <= start <= finish, "overlapping-independent-runs")
        prior_end = finish
        require(isinstance(run["batches"], list) and len(run["batches"]) <= len(case_templates),
                "invalid-batch-count")
        if run["status"] == "failed":
            failed = True
            # Failed/partial raw artifacts are integrity checked above, and
            # cannot be upgraded into a completed population by aggregation.
            result.append({"repetition": run["repetition"], "arm": run["arm"], "status": "failed",
                           "validated_attempts": "0", "attempt_count_complete": False})
            continue
        require(len(run["batches"]) == len(case_templates), "missing-case")
        receipt = artifacts.json(run["server_process"])
        server_owner = resources.process(receipt, run["arm"] + "-server", executable_refs[run["arm"]]["sha256"])
        require(server_owner not in identities and resources.clean(receipt), "reused-or-unclean-server")
        identities.add(server_owner)
        configuration(artifacts.json(run["configuration"]), run["arm"])
        lifecycle(run["lifecycle"], run["arm"], finish - start)
        replayed, client_receipts = [], []
        for batch, template in zip(run["batches"], case_templates, strict=True):
            fields(batch, BATCH_FIELDS)
            require(batch["id"] == template["id"], "missing-or-reordered-case")
            owner = artifacts.json(batch["client_process"])
            client_owner = resources.process(owner, "load-client", executable_refs["client"]["sha256"])
            require(client_owner not in identities and resources.clean(owner), "reused-or-unclean-client")
            identities.add(client_owner)
            client_receipts.append(owner)
            replay = client.replay(artifacts, batch, template["client_plan"], run["arm"],
                                   server_owner, client_owner, components, activation_ids)
            replay["resources"] = resources.resources(artifacts.json(batch["resources"]), server_owner, client_owner)
            replay["id"] = batch["id"]
            attempts += int(replay["warmup"]["counts"]["attempts"]) + int(replay["measured"]["counts"]["attempts"])
            failed = failed or replay["correctness_failures"] != "0"
            if not batch["id"].startswith(("budget-", "rate-", "concurrency-")):
                failed = failed or replay["measured"]["counts"]["successful"] != replay["measured"]["counts"]["attempts"]
            replayed.append(replay)
        cleanup = artifacts.json(run["cleanup"])
        fields(cleanup, "server clients server_shutdown")
        require(cleanup["server"] == receipt and cleanup["clients"] == client_receipts, "crossed-cleanup-owners")
        shutdown(cleanup["server_shutdown"], run["arm"])
        result.append({"repetition": run["repetition"], "arm": run["arm"], "status": "passed",
                       "lifecycle": run["lifecycle"], "batches": replayed})
    population_complete = len(runs) == len(expected) and all(run["status"] == "passed" for run in runs)
    status = "failed" if failed else ("complete" if population_complete and suite["profile"] == "full" else "incomplete")
    return {
        "schema": "latent.optimization.aggregate.v1", "profile": suite["profile"], "status": status,
        "scope": "standalone-native-code-versus-lsf-productionization-bundle",
        "suite_sha256": suite_digest[0], "plan_sha256": sha256(canonical(suite["plan"])),
        "identity": suite["identity"], "population_complete": population_complete,
        "validated_attempts": str(attempts), "attempt_count_complete": not any(run["status"] == "failed" for run in runs),
        "runs": result, "comparisons": comparisons(result, case_templates),
        "limitations": [
            "Smoke validates collection and replay but is not the full seven-pair reference.",
            "Warmup attempts remain retained and are excluded from measured latency populations.",
            "All offered attempts remain in counts; observed failures and undispatched offers are not deleted.",
            "Throughput uses the whole overlapping batch interval; per-call reciprocals are not throughput.",
            "Cold first-response observation includes client launch and connect; it is not isolated preparation.",
            "Native reference omits LSF routing, admission, sandbox and budget-accounting capabilities.",
            "Native fuel and memory budget consumption is unavailable; it is not a zero-cost comparison.",
            "RSS is the maximum of periodic observations, not an instantaneous peak or isolated runtime memory.",
            "Cgroup counters belong to the shared runner cgroup and cannot be attributed to one server.",
            "Seven repetitions provide descriptive variability, not statistical significance or an SLO.",
        ],
    }


def comparisons(runs, cases):
    indexed = {(run["repetition"], run["arm"]): run for run in runs if run["status"] == "passed"}
    result = []
    for index, case in enumerate(cases):
        pairs = []
        for repetition in range(1, 8):
            if (repetition, "native") not in indexed or (repetition, "lsf") not in indexed:
                continue
            selected = {arm: indexed[repetition, arm]["batches"][index]["measured"] for arm in ("native", "lsf")}
            left, right = (selected[arm]["latency_nanos"] for arm in ("native", "lsf"))
            difference = None if left is None or right is None else str(Decimal(right["median"]) - Decimal(left["median"]))
            pairs.append({"repetition": repetition, "native": selected["native"], "lsf": selected["lsf"],
                          "lsf_minus_native_median_latency_nanos": difference})
        differences = [Decimal(pair["lsf_minus_native_median_latency_nanos"]) for pair in pairs
                       if pair["lsf_minus_native_median_latency_nanos"] is not None]
        result.append({"id": case["id"], "pairs": pairs,
                       "paired_median_latency_differences_nanos": distribution(differences) if differences else None})
    return result
