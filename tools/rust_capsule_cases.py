"""Closed application, authority and physical-reclamation acceptance cases."""
from __future__ import annotations

import json
import time

from tools.phase2_operator_process import require, read_json
from tools.rust_capsule_node import (assert_value, call, deploy, finish_call, grant_http,
                                    provider_idle, sample, start_call)

TUTORIAL_CASES = {
    "greeting": ("greet", [(["Ada"], [{"ok": "Hello, Ada!"}], 0),
        ([" Grüße "], [{"ok": "Hello, Grüße!"}], 0), ([" "], [{"err": "Please enter a name."}], 3)]),
    "word-count": ("count", [(["one\t two\nthree"], [{"ok": 3}], 0),
        (["Grüße aus Berlin"], [{"ok": 3}], 0), (["x" * 4097], [{"err": "Use text of at most 4096 bytes."}], 3)]),
    "shipping": ("quote", [([2, False], [{"ok": 650}], 0), ([100, True], [{"ok": 8700}], 0),
        ([0, True], [{"err": "Choose between 1 and 100 items."}], 3)]),
}


def tutorials(client, targets, result):
    for template, (function, cases) in TUTORIAL_CASES.items():
        for ordinal, (arguments, expected, code) in enumerate(cases):
            row = call(client, targets[template], template, function, arguments, f"authoring-{template}-{ordinal}")
            result["invocations"].append(row)
            assert_value(row, expected, code)
        # A byte-identical request must use a fresh activation even when the
        # shared compiled image is warm; record cold and warm timings separately.
        first = cases[0]
        row = call(client, targets[template], template, function, first[0], f"authoring-{template}-warm")
        result["invocations"].append(row)
        assert_value(row, first[1])


def faults(client, target, probe, result, population):
    for ordinal, which in enumerate((0, 1, 0, 2, 0, 3, 0)):
        row = call(client, target, "recovery", "run", [which], f"authoring-fault-{ordinal}")
        result["invocations"].append(row)
        if which == 0:
            assert_value(row, [1])
        else:
            require(row["exitCode"] == 4 and row["response"]["category"] == "platform-failure"
                    and row["response"]["outcomeKnown"], "authoring-fault-not-observed")
            code = row["response"]["error"]["code"]
            expected = "guest-trap" if which == 1 else "resource-exhausted"
            require(code == expected, "authoring-fault-classification")
        require(int(row["response"]["data"]["consumption"]["peakMemoryBytes"]) <= target["budget"]["memoryBytes"],
                "authoring-guest-memory-bound")
        result["samples"].append(sample(client, probe, "after-fault-" + str(which), population))


def mode(control, selected):
    temporary = control / "mode.pending"
    temporary.write_text(selected, encoding="ascii")
    temporary.replace(control / "mode")


def rendezvous(client, control, name):
    deadline = min(client.deadline, time.monotonic() + 3)
    while not (control / name).exists():
        client.cancellation.check()
        client.node.drain()
        require(time.monotonic() < deadline, "authoring-provider-rendezvous")
        time.sleep(0.005)
    require((control / name).read_bytes() == b"observed\n", "authoring-provider-marker")


def http_cases(client, node, fixture, target, publication, port, control, probe, result, population):
    target = grant_http(client, node, fixture, publication, target, port)
    allowed = f"http://localhost:{port}/allowed"
    denied = f"http://localhost:{port}/denied"
    for ordinal, url in enumerate((allowed, denied, allowed)):
        row = call(client, target, "http-status", "check", [url], f"authoring-http-{ordinal}")
        result["invocations"].append(row)
        assert_value(row, [{"err": {"case": "permission-denied"}}] if ordinal == 1 else [{"ok": 201}],
                     3 if ordinal == 1 else 0)
        result["providerIdle"].append(provider_idle(client))
    for kind in ("deadline", "cancel", "disconnect"):
        selected = "hold-" + kind
        mode(control, selected)
        process = start_call(client, target, "http-status", "check", [allowed], "authoring-" + kind,
                             wall=100 if kind == "deadline" else None)
        try:
            rendezvous(client, control, "started-" + selected)
            if kind != "deadline":
                result["samples"].append(sample(client, probe, "active-" + kind, population, active=True))
            if kind == "cancel":
                result["cancellation"] = client.call("activation", "cancel", "authoring-cancel", "--reason", "Rust authoring acceptance")
                require(result["cancellation"]["outcomeKnown"] and result["cancellation"]["data"]["disposition"] == "accepted",
                        "authoring-cancel-not-accepted")
            if kind == "disconnect":
                process.close()
            else:
                row = finish_call(client, process)
                result["invocations"].append(row)
                require(row["exitCode"] == 4 and row["response"]["error"]["code"] ==
                        ("deadline-exceeded" if kind == "deadline" else "cancelled"), "authoring-interruption-kind")
            rendezvous(client, control, "closed-" + selected)
            result["samples"].append(sample(client, probe, "after-" + kind, population))
            result["providerIdle"].append(provider_idle(client))
        finally:
            process.close()
        mode(control, "reply")
        row = call(client, target, "http-status", "check", [allowed], "authoring-after-" + kind)
        result["invocations"].append(row)
        assert_value(row, [{"ok": 201}])
    return target


def population(client, fixture, targets, publications, probe, result):
    names = [target["name"] for target in targets.values()]
    previous = 0
    for count in (0, 4, 12):
        for ordinal in range(previous, count):
            name = f"dormant-{ordinal:02}"
            deploy(client, fixture / "my-greeting/deployment.json", publications["greeting"], name=name)
            names.append(name)
        previous = count
        for _ in range(3):
            result["samples"].append(sample(client, probe, "dormant", len(names)))
    rows = [row["os"]["metrics"] for row in result["samples"] if row["phase"] == "dormant"]
    require(all(row["processes"] == 1 and row["listeners"] == 1 and row["udpSockets"] == 0 for row in rows),
            "authoring-dormant-process-or-listener")
    # Warming of the node's shared bounded pool is not per-service residency.
    # Compare the two added populations, after the first deployment/control work.
    require(max(row["threads"] for row in rows[-3:]) <= max(row["threads"] for row in rows[-6:-3]),
            "authoring-dormant-thread-growth")
    result["dormantCounts"] = [5, 9, 17]
    return names


def stop_peer(peer):
    peer.stop()
    lines = bytes(peer.buffers[0]).splitlines()
    require(len(lines) == 1, "authoring-peer-shutdown")
    counts = json.loads(lines[0])
    require(set(counts) == {"requests", "authorized", "unexpected", "holds", "closedHolds"}
            and all(type(value) is int and 0 <= value <= 32 for value in counts.values())
            and counts["requests"] == counts["authorized"] and counts["unexpected"] == 0
            and counts["holds"] == counts["closedHolds"] == 3, "authoring-peer-reclamation")
    require(peer.closed and peer.owner.finished and peer.owner.process.returncode == 0, "authoring-peer-not-reaped")
    return counts
