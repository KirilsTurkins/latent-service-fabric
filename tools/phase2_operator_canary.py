"""Positive canary evidence from actual, attributed CLI invocation receipts."""
from __future__ import annotations

import base64
from collections import Counter
import json
import re
import time

from tools.phase2_operator_process import require, write_candidate_manifest, write_json

MEDIA = "application/vnd.latent.wit-values.v1+json"


def rollback_target(client, rollout_id, started):
    status = client.call("rollout", "get", rollout_id)["data"]["status"]
    require(isinstance(status, dict) and status["id"] == rollout_id == started["rolloutId"]
            and status["revision"] == started["revision"]
            and status["planDigest"] == started["planDigest"]
            and status["routeGeneration"] == started["routeGeneration"], "rollback-status-association")
    target = status["rollbackTarget"]
    require(isinstance(target, dict) and target["formatVersion"] == 1
            and re.fullmatch(r"sha256:[0-9a-f]{64}", target["manifestDigest"])
            and 0 < int(target["historicalRouteGeneration"]) < int(started["routeGeneration"]),
            "rollback-status-target")
    return target["historicalRouteGeneration"]


def invoke(client, metadata, input_path, activation_id):
    result = client.call("--rpc-timeout-ms", "5000", "invoke", "--service", metadata["service"],
                         "--contract", metadata["contract"], "--function", metadata["function"],
                         "--activation-id", activation_id, "--input", input_path,
                         "--wall-time-ms", "5000", "--cpu-fuel", "1000000",
                         "--memory-bytes", "4194304", "--log-bytes", "1024")
    data = result["data"]
    require(result["outcomeKnown"] and data["activationId"] == activation_id, "invoke-identity")
    payload = data["payload"]
    require(payload["mediaType"] == MEDIA and payload["encoding"] == "base64", "invoke-media")
    require(len(payload["data"]) <= 128, "invoke-result-bound")
    returned = base64.b64decode(payload["data"], validate=True)
    require(int(payload["byteLength"]) == len(returned) and json.loads(returned) == [7], "invoke-result")
    pin = data["resolvedRevision"]
    require(isinstance(pin, dict) and len(pin["revisionId"]) <= 512, "invoke-revision")
    return pin


def validate_window(report, pins, started, summaries):
    require(report["rolloutId"] == "healthy" and report["revision"] == started["revision"]
            and report["routeGeneration"] == started["routeGeneration"], "canary-report-identity")
    require(len(pins) == 16, "canary-sample-count")
    known = {summaries[name]["componentDigest"] for name in ("blue", "green")}
    for pin in pins:
        require(pin["routeGeneration"] == started["routeGeneration"] and pin["releaseDigest"] in known,
                "canary-invoke-attribution")
    selected = Counter(pin["revisionId"] for pin in pins)
    require(len(selected) <= 2, "canary-revision-count")
    for field in ("starts", "selected", "admitted", "terminal"):
        require(int(report[field]) == len(pins), "canary-complete-denominators")
    for field in ("live", "unattributed", "abandoned"):
        require(int(report[field]) == 0, "canary-loss-or-live")
    rows = report["revisions"]
    require(len(rows) == 2 and len({row["revision"] for row in rows}) == 2, "canary-report-cohort")
    candidate = None
    baseline = None
    for row in rows:
        count = selected[row["revision"]]
        require(all(pin["releaseDigest"] == row["componentDigest"]
                    for pin in pins if pin["revisionId"] == row["revision"]), "canary-component-attribution")
        counters = row["counters"]
        for field in ("selected", "admitted", "admittedTerminal", "success"):
            require(int(counters[field]) == count, "canary-attributed-counters")
        for field in ("domainError", "platformError", "deadlineExceeded", "cancelled"):
            require(int(counters[field]) == 0, "canary-failed-invocation")
        require(sum(int(value) for value in counters["latencyBuckets"]) == count, "canary-latency-denominator")
        if row["revision"] == report["candidateRevision"]:
            require(row["componentDigest"] == summaries["green"]["componentDigest"], "canary-candidate-identity")
            candidate = counters
        else:
            require(row["componentDigest"] == summaries["blue"]["componentDigest"], "canary-baseline-identity")
            baseline = counters
    # Deterministic IDs select real routes. Never turn a missing candidate sample
    # into health, and never issue extra invocations until one happens to pass.
    require(candidate is not None and int(candidate["selected"]) > 0, "canary-no-candidate-sample")
    require(baseline is not None, "canary-baseline-missing")
    require(report["assessment"]["verdict"].endswith("HEALTHY"), "canary-not-healthy")
    require(int(report["assessment"]["admittedTerminal"]) == int(candidate["admittedTerminal"]),
            "canary-assessment-denominator")
    return candidate, baseline


def positive_canary(client, metadata, input_path, fixture, summaries, receipt, change):
    base = client.call("deployment", "get", "blue")["data"]["deployment"]
    candidate_manifest = write_candidate_manifest(fixture / "green/deployment.json",
                                                  client.directory / "candidate-5000.json", 5000)
    policy = client.directory / "healthy-canary.json"
    write_json(policy, {"formatVersion": 1, "observationMillis": 5000, "minimumCandidateSamples": 1,
                        "maximumFailureBasisPoints": 0, "latencyThresholdMicros": 10000000,
                        "maximumSlowBasisPoints": 0})
    started = receipt(client.call("rollout", "start", "healthy", "--base", "blue",
                                  "--expected-base-generation", base["generation"],
                                  "--candidate", candidate_manifest, "--weights", "5000,10000",
                                  "--operation-id", "healthy-start", "--expected-revision", "0",
                                  "--canary-policy", policy), "healthy-start")
    target = rollback_target(client, "healthy", started)
    complete_after = time.monotonic() + 5
    pins = [invoke(client, metadata, input_path, f"operator-canary-{index:02d}") for index in range(16)]
    # Bounded observation wait, with no management action or fabricated samples.
    while time.monotonic() < complete_after:
        client.cancellation.check()
        client.node.drain()
        time.sleep(min(0.025, max(0, complete_after - time.monotonic())))
    report = client.call("rollout", "evaluate", "healthy", "--expected-revision", started["revision"])["data"]["report"]
    candidate, baseline = validate_window(report, pins, started, summaries)
    promoted = receipt(change(client, "promote", "healthy", started["revision"], "healthy-promote",
                               "--next-step", "1"), "healthy-promote")
    decision = promoted["canaryDecision"]
    require(promoted["state"].endswith("COMPLETED") and decision["windowEpoch"] == report["windowEpoch"]
            and decision["candidate"] == candidate and decision["baseline"] == baseline,
            "promotion-durable-evidence")
    final_pin = invoke(client, metadata, input_path, "operator-promoted-green")
    require(final_pin["releaseDigest"] == summaries["green"]["componentDigest"]
            and final_pin["routeGeneration"] == promoted["routeGeneration"], "promoted-route-selection")
    rolled = receipt(change(client, "rollback", "healthy", promoted["revision"], "healthy-rollback",
                            "--target-generation", target), "healthy-rollback")
    return {"candidateSamples": int(candidate["selected"]), "baselineSamples": int(baseline["selected"]),
            "evaluation": report, "promotionReceipt": promoted, "rollbackReceipt": rolled,
            "invocationPins": pins, "promotedInvocation": final_pin}
