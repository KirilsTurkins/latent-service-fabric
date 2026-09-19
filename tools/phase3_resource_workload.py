"""Real provider work, observed cancellation and overload, followed by bounded churn."""
from __future__ import annotations

import time

from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_resource_node import finish, invocation, sample, settled_samples
from tools.phase3_resource_schedule import run_open_loop


def mode(control, kind, ordinal=0):
    temporary = control / "mode.pending.json"
    write_json(temporary, {"kind": kind, "ordinal": ordinal})
    temporary.replace(control / "mode.json")


def wait_marker(client, control, name):
    until = min(client.deadline, time.monotonic() + 3)
    while not (control / name).exists():
        client.cancellation.check()
        client.node.drain()
        require(time.monotonic() < until, "resource-peer-rendezvous-deadline")
        time.sleep(0.005)
    return read_json(control / name)


def one(client, target, activation, arguments, function=None):
    began = time.monotonic_ns()
    process = invocation(client, target, activation, arguments, function)
    result = finish(client, process)
    return {"activation": activation, "elapsedNanos": str(time.monotonic_ns() - began), "result": result}


def success(result, expected):
    require(result["result"]["category"] == "success" and result["result"]["value"] == [str(expected)]
            and result["result"]["outcomeKnown"] is True, "resource-real-provider-output")


def retain(timings, kind, heat, expected, observed):
    row = {"kind": kind, "heat": heat, "expectedOutcome": expected, "outcome": "unclassified", **observed}
    timings.append(row)
    return row


def overload_counts(outcomes):
    require(bool(outcomes), "resource-overload-empty")
    counts = {"platformResourceExhausted": sum(entry["code"] == "resource-exhausted" for entry in outcomes),
              "grpcResourceExhausted": sum(entry["grpcCode"] == "resource-exhausted" for entry in outcomes),
              "unknownOutcomes": sum(entry["outcomeKnown"] is False for entry in outcomes),
              "scope": "gRPC-exhaustion-is-not-proof-of-node-queue-admission-or-known-nonacceptance"}
    require(counts["platformResourceExhausted"] + counts["grpcResourceExhausted"] > 0,
            "resource-overload-empty")
    return counts


def measured_work(client, targets, port, control, probe, profile, result):
    url = f"http://localhost:{port}/allowed"
    dormant = result["catalog"]["dormantPopulations"][-1]["dormantAdded"]
    timings = result["calls"]
    for heat in ("cold", "warm"):
        for kind, expected in (("http", 2201), ("blob", 4)):
            observed = one(client, targets[kind], f"resource-{heat}-{kind}", [0, url if kind == "http" else "", "0"])
            row = retain(timings, kind, heat, "success", observed)
            success(observed, expected)
            row["outcome"] = "success"
    result["samples"] += settled_samples(client, probe, "warm", dormant,
                                         profile["samplesPerPhase"])
    mode(control, "disconnect")
    failure = one(client, targets["http"], "resource-http-failed", [0, url, "0"])
    row = retain(timings, "http", "warm", "failure", failure)
    row["peerDisconnected"] = wait_marker(client, control, "disconnected-0.json")
    require(failure["result"]["category"] != "success" or failure["result"]["value"] == ["11"],
            "resource-http-failure-not-observed")
    row["outcome"] = "failure"
    row["guestTypedUncertain"] = failure["result"]["category"] == "success"
    mode(control, "reply")
    for operation, expected in (("invalid-handle", 10), ("abandon", 1)):
        observed = one(client, targets["blob"], "resource-blob-" + operation,
                       [4 if operation == "invalid-handle" else 1, "", "18446744073709551615"])
        row = retain(timings, "blob", "warm", operation, observed)
        success(observed, expected)
        row["outcome"] = operation
    cancel_http(client, targets["http"], url, control, probe, profile, result)
    overload(client, targets["http"], url, control, probe, profile, result)
    mode(control, "reply")
    for cycle in range(profile["cycles"]):
        cycle_origin = time.monotonic_ns()

        def launch(ordinal):
            kind = "http" if ordinal % 2 == 0 else "blob"
            return invocation(client, targets[kind], f"resource-cycle-{cycle}-{ordinal}",
                              [0, url if kind == "http" else "", "0"])

        rows = run_open_loop(profile["arrivalsPerCycle"], profile["arrivalIntervalMillis"] * 1_000_000,
                             profile["maximumOutstanding"], launch, lambda process: finish(client, process),
                             lambda: (client.cancellation.check(), client.node.drain()),
                             int(client.deadline * 1_000_000_000))
        result["cycles"].append({"ordinal": cycle, "beganMonotonicNanos": str(cycle_origin), "arrivals": rows})
        for row in rows:
            if row["disposition"] == "completed" and row["result"]["category"] == "success":
                expected = 2201 if row["ordinal"] % 2 == 0 else 4
                require(row["result"]["value"] == [str(expected)], "resource-churn-value")
        result["samples"] += settled_samples(client, probe, "recovery", dormant,
                                             profile["samplesPerPhase"])
    for kind, expected in (("http", 2201), ("blob", 4)):
        observed = one(client, targets[kind], "resource-recovered-" + kind, [0, url if kind == "http" else "", "0"])
        row = retain(timings, kind, "warm", "recovery", observed)
        success(observed, expected)
        row["outcome"] = "recovery"


def cancel_http(client, target, url, control, probe, profile, result):
    mode(control, "hold", 0)
    began = time.monotonic_ns()
    process = invocation(client, target, "resource-cancel-http", [0, url, "0"])
    try:
        started = wait_marker(client, control, "started-0.json")
        observed = sample(client, probe, "active", result["catalog"]["dormantPopulations"][-1]["dormantAdded"])
        require(int(observed["capabilities"]["nodeUsage"]["counters"]["broker_calls"]) > 0,
                "resource-no-active-provider-observation")
        result["samples"].append(observed)
        cancellation = client.call("activation", "cancel", "resource-cancel-http", "--reason", "resource-campaign")
        require(cancellation["outcomeKnown"], "resource-cancel-uncertain")
        terminal = finish(client, process)
        row = retain(result["calls"], "http", "warm", "cancellation",
                     {"activation": "resource-cancel-http", "elapsedNanos": str(time.monotonic_ns() - began),
                      "result": terminal, "peerRequest": started["request"], "cancellationControl": cancellation})
        require(terminal["code"] == "cancelled", "resource-cancel-not-observed")
        closed = wait_marker(client, control, "closed-0.json")
        require(started == closed, "resource-cancel-peer-association")
        row.update(outcome="cancellation", peerClosed=True)
    finally:
        process.close()
    mode(control, "reply")


def overload(client, target, url, control, probe, profile, result):
    mode(control, "hold", 1)
    processes = []
    try:
        for ordinal in range(profile["maximumOutstanding"]):
            processes.append(invocation(client, target, f"resource-overload-{ordinal}", [0, url, "0"]))
        wait_marker(client, control, "started-1.json")
        observed = sample(client, probe, "active", result["catalog"]["dormantPopulations"][-1]["dormantAdded"])
        result["samples"].append(observed)
        result["overload"] = [finish(client, process) for process in processes]
        result["overloadClassification"] = overload_counts(result["overload"])
    finally:
        for process in processes:
            process.close()
    mode(control, "reply")
