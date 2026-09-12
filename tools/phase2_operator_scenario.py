"""Actual authenticated node commands for the separate-process Phase 2 test."""
from __future__ import annotations

import json
import re
import time

from tools.phase2_operator_process import Process, read_json, require, write_candidate_manifest, write_json
from tools.phase2_operator_canary import invoke, positive_canary, rollback_target

TOKEN = "LSF-PUBLIC-OPERATOR-WORKFLOW-TEST-ONLY"
DENIED_TOKEN = "LSF-PUBLIC-WRONG-NODE-TOKEN-TEST-ONLY"
NODE_ID = "operator-workflow-test"


def configure_node(directory, fixture, tenant):
    write_json(directory / "policy.json", read_json(fixture / "policy.json"))
    config = directory / "node.json"
    write_json(config, {
        "formatVersion": 1, "dataDirectory": "data", "nodeId": NODE_ID,
        "bind": "127.0.0.1:0", "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2,
                   "maximumMemoryBytes": 67108864}],
        "execution": {"maximumCpuFuel": 10000000000, "maximumWallTimeMillis": 5000,
                      "maximumLogBytes": 16384},
        "cache": {"entries": 4, "preparations": 1},
        "catalogs": {"releaseEntries": 8, "deployments": 8},
        "retention": {"terminalEntries": 32, "terminalTtlMillis": 30000},
        "shutdownGraceMillis": 1000,
        "supplyChain": {"mode": "enforced", "policyFile": "policy.json", "clockLeaseSeconds": 5},
        "audit": {"mode": "durable", "records": 256, "diskBytes": 4194304,
                  "queuedOperations": 8, "queryOwners": 2},
        "rollouts": {"mode": "manual", "active": 4, "retained": 8, "stages": 4,
                     "receipts": 32, "metadataBytes": 1048576, "queuedOperations": 2,
                     "queuedBytes": 262144, "queryOwners": 2,
                     "canary": {"windows": 4, "samplesPerWindow": 32, "totalSamples": 128,
                                "liveSamples": 8, "snapshotOwners": 4}},
        "credentials": [{"token": TOKEN, "subject": "workflow-operator", "tenant": tenant,
                         "role": "operator"}]
    })
    return config


def connect(client, binary, directory, config, tenant, ordinal):
    environment = dict(client.environment, HOME=str(directory))
    node = Process([str(binary), "serve", "--config", str(config)], directory,
                   environment, client.cancellation, maximum=262144)
    try:
        started = node.line(min(client.deadline, time.monotonic() + 30))
        endpoint = started.get("endpoint", "")
        require(re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", endpoint), "node-endpoint")
        profile = client.directory / f"client-{ordinal}.json"
        write_json(profile, {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{
            "name": "operator", "endpoint": "http://" + endpoint, "tenant": tenant,
            "token": TOKEN, "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 15000}]})
        client.config, client.node = profile, node
        deadline = min(client.deadline, time.monotonic() + 10)
        while True:
            state = client.call("node", "get", NODE_ID)["data"]
            if state["inventory"]["health"]["ready"]:
                return node
            require(time.monotonic() < deadline, "node-readiness")
            time.sleep(0.025)
    except BaseException:
        client.node = None
        node.close()
        raise


def stop(client, node):
    client.node = None
    node.stop()


def receipt(result, operation):
    require(result["outcomeKnown"], "mutation-uncertain")
    value = result["data"]["receipt"]
    require(value["operationId"] == operation, "operation-association")
    require(result["data"].get("auditAck") is not None, "mutation-audit-missing")
    return value


def route(client):
    return client.call("route", "get")["data"]["snapshot"]


def route_identity(snapshot):
    # Recovery recompiles the same route generation. Its diagnostic compile
    # timestamp is not part of the persisted operator operation identity.
    return {key: snapshot[key] for key in ("generation", "services", "bindings", "policyDigests", "tenant")}


def change(client, action, rollout, revision, operation, *extra, codes=(0,)):
    return client.call("rollout", action, rollout, "--expected-revision", revision,
                       "--operation-id", operation, *extra, codes=codes)


def audit_pages(client, expected_operations):
    token = None
    seen_tokens = set()
    found = set()
    previous = 0
    pages = 0
    for _ in range(64):
        arguments = ["audit", "query", "--scope", "tenant", "--page-size", "2"]
        if token:
            arguments += ["--page-token", token]
        data = client.call(*arguments)["data"]
        require(isinstance(data["coverage"], dict), "audit-coverage")
        for row in data["records"]:
            sequence = int(row["sequence"])
            require(sequence > previous, "audit-page-order")
            previous = sequence
            attempt = row["data"].get("attempt")
            if attempt:
                found.add(attempt["operationId"])
        pages += 1
        token = data["page"]["nextPageToken"]
        if not token:
            break
        require(token not in seen_tokens and len(token) <= 4096, "audit-page-token")
        seen_tokens.add(token)
    require(not token and pages > 1, "audit-pagination-bound")
    require(expected_operations <= found, "audit-operation-coverage")


def node_workflow(client, binary, directory, fixture, outputs, summaries, metadata):
    tenant = metadata["tenant"]
    candidate = write_candidate_manifest(fixture / "green/deployment.json",
                                         client.directory / "candidate-1000.json", 1000)
    config = configure_node(directory, fixture, tenant)
    node = connect(client, binary, directory, config, tenant, 1)
    try:
        # A distinct client configuration carries an invalid public test token.
        valid_config = client.config
        denied = read_json(valid_config)
        denied["profiles"][0]["token"] = DENIED_TOKEN
        denied_path = client.directory / "denied-client.json"
        write_json(denied_path, denied)
        client.config = denied_path
        try:
            denial = client.call("node", "get", NODE_ID, codes=(4,))
            require(denial["category"] == "platform-failure", "node-auth-classification")
        finally:
            client.config = valid_config

        for name in ("blue", "green"):
            arguments = ["release", "publish-package", outputs / (name + "-pulled"),
                         "--evidence", outputs / (name + "-evidence/index.json"),
                         "--operation-id", "publish-" + name, "--expected-generation", "0"]
            result = client.call(*arguments)
            published = result["data"]
            require(result["outcomeKnown"] and published["release"]["digest"] == summaries[name]["componentDigest"],
                    "publication-component")
            operation = client.call("release", "operation", "publish-" + name)["data"]["receipt"]
            require(operation == published["operation"], "publication-receipt")
            replay = client.call(*arguments)["data"]
            require(replay["operation"] == operation, "publication-replay")
            client.call("release", "lifecycle", summaries[name]["componentDigest"])
        first = client.call("release", "list", "--page-size", "1")["data"]
        require(len(first["releases"]) == 1 and first["nextPageToken"], "release-pagination")
        second = client.call("release", "list", "--page-size", "1", "--page-token", first["nextPageToken"])["data"]
        require(len(second["releases"]) == 1 and second["releases"][0]["digest"] != first["releases"][0]["digest"],
                "release-page-disjoint")

        snapshot = client.call("deployment", "get", "blue", "--operation-snapshot", codes=(6,))["data"]
        arguments = ["deployment", "apply", fixture / "blue/deployment.json", "--operation-id", "apply-blue",
                     "--expected-state-version", snapshot["stateVersion"], "--expected-generation", "0"]
        applied = receipt(client.call(*arguments), "apply-blue")
        replay = client.call(*arguments)
        require(replay["data"]["replayed"] and replay["data"]["receipt"] == applied, "deployment-replay")
        require(client.call("deployment", "operation", "apply-blue")["data"]["receipt"] == applied,
                "deployment-operation-lookup")
        input_path = client.directory / "invoke.json"
        write_json(input_path, metadata["input"])
        initial_pin = invoke(client, metadata, input_path, "operator-initial-blue")
        require(initial_pin["releaseDigest"] == summaries["blue"]["componentDigest"]
                and initial_pin["routeGeneration"] == applied["routeGeneration"], "initial-route-selection")
        before = route(client)
        # A distinct operation ID cannot turn a stale create precondition into a retry.
        stale = arguments.copy()
        stale[stale.index("apply-blue")] = "apply-stale"
        client.call(*stale, codes=(4,))
        require(route(client) == before, "stale-apply-mutated-route")

        start = client.call("rollout", "start", "manual", "--base", "blue",
                            "--expected-base-generation", applied["objectGeneration"],
                            "--candidate", candidate, "--weights", "1000,10000",
                            "--operation-id", "manual-start", "--expected-revision", "0")
        current = receipt(start, "manual-start")
        target = rollback_target(client, "manual", current)
        current = receipt(change(client, "pause", "manual", current["revision"], "manual-pause"), "manual-pause")
        current = receipt(change(client, "resume", "manual", current["revision"], "manual-resume"), "manual-resume")
        current = receipt(change(client, "advance", "manual", current["revision"], "manual-next", "--next-step", "1"), "manual-next")
        rollback_args = ("--target-generation", target)
        rolled = receipt(change(client, "rollback", "manual", current["revision"], "manual-rollback", *rollback_args), "manual-rollback")
        require(rolled["state"].endswith("ROLLED_BACK") and int(rolled["routeGeneration"]) > int(target), "rollback-new-generation")
        replay = change(client, "rollback", "manual", current["revision"], "manual-rollback", *rollback_args)
        require(replay["data"]["replayed"] and replay["data"]["receipt"] == rolled, "rollback-replay")

        base = client.call("deployment", "get", "blue")["data"]["deployment"]
        policy = client.directory / "canary.json"
        write_json(policy, {"formatVersion": 1, "observationMillis": 1, "minimumCandidateSamples": 1,
                            "maximumFailureBasisPoints": 0, "latencyThresholdMicros": 10000,
                            "maximumSlowBasisPoints": 0})
        started = receipt(client.call("rollout", "start", "canary", "--base", "blue",
                                      "--expected-base-generation", base["generation"],
                                      "--candidate", candidate, "--weights", "1000,10000",
                                      "--operation-id", "canary-start", "--expected-revision", "0",
                                      "--canary-policy", policy), "canary-start")
        negative_target = rollback_target(client, "canary", started)
        evaluation = client.call("rollout", "evaluate", "canary", "--expected-revision", started["revision"])["data"]["report"]
        require(evaluation["assessment"]["verdict"].endswith("NO_DATA"), "zero-data-verdict")
        before = route(client)
        change(client, "promote", "canary", started["revision"], "canary-denied", "--next-step", "1", codes=(4,))
        require(route(client) == before, "denied-promotion-mutated-route")
        aborted = receipt(change(client, "abort", "canary", started["revision"], "canary-abort"), "canary-abort")
        receipt(change(client, "rollback", "canary", aborted["revision"], "canary-rollback",
                       "--target-generation", negative_target), "canary-rollback")

        canary_counts = positive_canary(client, metadata, input_path, fixture, summaries, receipt, change)

        # An intentionally tiny transport deadline is not a retry policy. Inspect
        # the exact operation afterward whether this machine completed or timed out.
        snapshot = client.call("deployment", "get", "blue", "--operation-snapshot")["data"]
        attempted = client.call("--rpc-timeout-ms", "1", "deployment", "apply", fixture / "blue/deployment.json",
                                "--operation-id", "deadline-inspect", "--expected-state-version", snapshot["stateVersion"],
                                "--expected-generation", snapshot["deployment"]["generation"], codes=(0, 4, 5))
        inspected = client.call("deployment", "operation", "deadline-inspect")
        require(inspected["outcomeKnown"] == (inspected["data"]["receipt"] is not None), "deadline-lookup-certainty")
        # No assertion fabricates a committed or rejected receipt for Unknown.
        require(attempted["category"] in ("success", "platform-failure", "transport-failure"), "deadline-category")

        audit_pages(client, {"publish-blue", "publish-green", "apply-blue", "manual-start",
                             "manual-rollback", "canary-denied", "healthy-promote"})
        stable_route = route(client)
        stop(client, node)
        node = None
        # The enforced authority persists a future clock lease. Restart is
        # intentionally unavailable before that floor; wait the configured
        # maximum from the completed shutdown, without retrying node startup.
        restart_after = time.monotonic() + 5
        while time.monotonic() < restart_after:
            client.cancellation.check()
            time.sleep(min(0.025, max(0, restart_after - time.monotonic())))
        node = connect(client, binary, directory, config, tenant, 2)
        require(route_identity(route(client)) == route_identity(stable_route), "restart-route-identity")
        require(client.call("deployment", "operation", "apply-blue")["data"]["receipt"] == applied, "restart-apply-receipt")
        require(client.call("rollout", "operation", "manual", "manual-rollback")["data"]["receipt"] == rolled,
                "restart-rollback-receipt")
        snapshot = client.call("deployment", "get", "blue", "--operation-snapshot")["data"]
        deletion = ["deployment", "delete", "blue", "--operation-id", "delete-blue",
                    "--expected-state-version", snapshot["stateVersion"],
                    "--expected-generation", snapshot["deployment"]["generation"]]
        client.call(*deletion)
        deleted = client.call("deployment", "operation", "delete-blue")["data"]["receipt"]
        require(deleted["action"].endswith("DELETE"), "delete-receipt-action")
        require(client.call(*deletion)["data"]["operation"]["replayed"], "delete-replay")
        client.call("deployment", "get", "blue", "--operation-snapshot", codes=(6,))
        green = summaries["green"]["componentDigest"]
        lifecycle = client.call("release", "lifecycle", green)["data"]["status"]["record"]
        revoked = client.call("release", "revoke", green, "--operation-id", "revoke-green",
                              "--expected-generation", lifecycle["generation"])["data"]["operation"]
        status = client.call("release", "lifecycle", green)["data"]["status"]
        require(status["record"]["state"].endswith("REVOKED")
                and int(status["record"]["generation"]) == int(lifecycle["generation"]) + 1
                and status["record"]["operationId"] == "revoke-green", "revoke-status")
        require(client.call("release", "operation", "revoke-green")["data"]["receipt"] == revoked,
                "revoke-operation-receipt")
        stop(client, node)
        node = None
        return {"successfulInvocations": 18, "positiveCanary": canary_counts, "revocationVerified": True}
    finally:
        client.node = None
        if node is not None:
            node.close()
