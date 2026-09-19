"""Bounded live cancellation and canary/rollback observations, never replayed actions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import sys
import time

from tools.phase2_operator_process import Process, WorkflowError, require, write_json
from tools.phase2_operator_scenario import change, receipt
from tools.phase2_operator_canary import rollback_target, validate_window
from tools.phase3_reference_scenario import decode_render, http, invocation_arguments, invoke, manifest
from tools.phase3_web_scenario import idle_inventory


def signal_owned(process):
    require(not process.closed and not process.owner.exited(), "reference-owned-process-ended")
    os.kill(process.owner.process.pid, signal.SIGUSR1)


def start_peer(client, directory):
    peer = Process([sys.executable, str(Path(__file__).with_name("phase3_reference_peer.py"))],
                   directory, client.environment, client.cancellation, maximum=16384)
    try:
        event = peer.line(min(client.deadline, time.monotonic() + 5))
        require(event == {"event": "ready", "allowedPort": 19090, "deniedPort": 19091}, "reference-peer-ready")
        return peer
    except BaseException:
        peer.close()
        raise


def peer_event(client, peer, expected):
    deadline = min(client.deadline, time.monotonic() + 3)
    for _ in range(32):
        event = peer.line(deadline)
        require(event.get("event") in ("response", "held", "closed", "released"), "reference-peer-event")
        if event["event"] == expected:
            return event
    raise WorkflowError("reference-peer-event-count")


def wait_idle(client):
    deadline = min(client.deadline, time.monotonic() + 3)
    for _ in range(24):
        try:
            return idle_inventory(client)
        except WorkflowError as failure:
            if str(failure) not in ("angular-cells-not-reclaimed", "angular-owner-not-reclaimed"):
                raise
        require(time.monotonic() < deadline, "reference-idle-deadline")
        time.sleep(0.025)
    raise WorkflowError("reference-idle-observation-bound")


def start_render(client, activation):
    arguments = invocation_arguments(client, activation, "/slow")
    process = Process([client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator", *map(str, arguments)],
                      client.directory, client.environment, client.cancellation, maximum=256 * 1024)
    client.calls += 1
    return process


def cancellations(client, node, peer, records, publications):
    observations = []
    for disconnect in (False, True):
        activation = "reference-disconnect" if disconnect else "reference-cancel"
        process = start_render(client, activation)
        try:
            held = peer_event(client, peer, "held")
            state = client.call("activation", "get", activation)["data"]
            require(state["phase"] == "running", "reference-held-render-not-running")
            if disconnect:
                process.close()
            else:
                cancelled = client.call("activation", "cancel", activation, "--reason", "Reference bounded cancellation")
                require(cancelled["outcomeKnown"] and cancelled["data"]["disposition"] == "accepted", "reference-cancellation-uncertain")
                completed = process.complete(min(client.deadline, time.monotonic() + 5))
                result = json.loads(completed.stdout)
                require(completed.returncode == 4 and result["error"]["code"] == "cancelled", "reference-cancellation-result")
            closed = peer_event(client, peer, "closed")
            require(held["ordinal"] == closed["ordinal"], "reference-cancelled-peer-identity")
            idle = wait_idle(client)
            terminal = client.call("activation", "get", activation)["data"]
            require(terminal["terminalState"] == "cancelled", "reference-cancellation-terminal")
            observations.append({"activationId": activation, "disconnect": disconnect,
                                 "terminalState": terminal["terminalState"], "closedPeer": closed["ordinal"], "idle": idle})
        finally:
            process.close()
    address, port = node.startup_record["httpEndpoint"].split(":")
    connection = socket.create_connection((address, int(port)), timeout=3)
    try:
        connection.sendall(f"GET /slow HTTP/1.1\r\nHost: {client.host}\r\nConnection: close\r\n\r\n".encode("ascii"))
        held = peer_event(client, peer, "held")
    finally:
        connection.close()
    closed = peer_event(client, peer, "closed")
    require(held["ordinal"] == closed["ordinal"], "reference-http-disconnect-peer")
    idle = wait_idle(client)
    body, _headers = http(client, node, "/data")
    require(b"Hello from the scoped provider" in body, "reference-http-disconnect-recovery")
    recovery = invoke(client, records, publications, "reference-cancel-recovery")
    return {"grpc": observations, "http": {"closedPeer": closed["ordinal"], "idle": idle}, "recovery": recovery}


def canary(client, node, peer, records, publications):
    candidate = client.directory / "reference-candidate.json"
    write_json(candidate, manifest(records["blue"], publications["blue"], "blue", 5000))
    policy = client.directory / "reference-canary.json"
    write_json(policy, {"formatVersion": 1, "observationMillis": 10000, "minimumCandidateSamples": 1,
                        "maximumFailureBasisPoints": 0, "latencyThresholdMicros": 10000000, "maximumSlowBasisPoints": 0})
    base = client.call("deployment", "get", "green")["data"]["deployment"]
    held = start_render(client, "reference-pinned-before-canary")
    try:
        pending = peer_event(client, peer, "held")
        started_at = time.monotonic()
        started = receipt(client.call("rollout", "start", "reference-canary", "--base", "green",
            "--expected-base-generation", base["generation"], "--candidate", candidate, "--weights", "5000,10000",
            "--operation-id", "reference-canary-start", "--expected-revision", "0", "--canary-policy", policy), "reference-canary-start")
        for name in ("green", "blue"):
            asset = next(asset for asset in records[name]["assets"] if asset["mediaType"] == "text/javascript")
            http(client, node, "/_lsf/assets/" + publications[name] + asset["path"])
        signal_owned(peer)
        released = peer_event(client, peer, "released")
        require(pending["ordinal"] == released["ordinal"], "reference-pinned-peer-association")
        completed = held.complete(min(client.deadline, time.monotonic() + 5))
        require(completed.returncode == 0, "reference-held-render-failed")
        pinned = decode_render(json.loads(completed.stdout), records, publications)
        require(pinned["pin"]["publicationId"] == publications["green"]
                and int(pinned["pin"]["routeGeneration"]) < int(started["routeGeneration"]), "reference-inflight-revision-replaced")
    finally:
        held.close()
    historical = rollback_target(client, "reference-canary", started)
    initial = client.call("rollout", "evaluate", "reference-canary", "--expected-revision", started["revision"])["data"]["report"]
    require(initial["assessment"]["verdict"].endswith("NO_DATA"), "reference-empty-canary-not-no-data")
    rejected = change(client, "promote", "reference-canary", started["revision"], "reference-no-data-promote", "--next-step", "1", codes=(4,))
    require(rejected["outcomeKnown"], "reference-no-data-promotion-uncertain")
    samples = [invoke(client, records, publications, f"reference-canary-{ordinal:02d}", route=None) for ordinal in range(12)]
    while time.monotonic() < started_at + 10:
        client.cancellation.check()
        require(time.monotonic() < client.deadline, "reference-canary-deadline")
        node.drain()
        time.sleep(0.025)
    report = client.call("rollout", "evaluate", "reference-canary", "--expected-revision", started["revision"])["data"]["report"]
    candidate_counts, baseline_counts = validate_window(report, [sample["pin"] for sample in samples], started,
                                                       {"green": records["blue"], "blue": records["green"]})
    promoted = receipt(change(client, "promote", "reference-canary", started["revision"], "reference-promote", "--next-step", "1"), "reference-promote")
    require(promoted["state"].endswith("COMPLETED") and promoted["canaryDecision"]["candidate"] == candidate_counts
            and promoted["canaryDecision"]["baseline"] == baseline_counts, "reference-canary-durable-decision")
    return {"started": started, "pinnedRender": pinned, "emptyEvaluation": initial, "samples": samples,
            "evaluation": report, "promoted": promoted, "historicalGeneration": historical}
