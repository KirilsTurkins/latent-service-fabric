"""Actual SDK components against production providers and explicit local fixtures."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import socket

from tools.dev_workflow import paths, portable
from tools.dev_workflow.common import digest, encode, require
from tools.run_portable_dev_tests import call, payload, run


def verify(host: Path, cwd: Path, guests: Path) -> dict:
    builtin_grants = ["latent:context/context@0.1.0", "latent:log/log@0.1.0",
        "latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0"]
    calls = [call("context", "snapshot", grants=builtin_grants), call("clocks", "clocks", grants=builtin_grants),
             call("logs", "log-probe", b'["portable-log",[]]', grants=builtin_grants)]
    for value in calls:
        value["contract"] = "tests:capabilities/api@0.1.0"
    directory = guests / "capabilities"
    builtins = run(host, cwd, (directory / "component.wasm").read_bytes(), (directory / "capsule.json").read_bytes(),
        (directory / "contracts.json").read_bytes(), calls)
    context = json.loads(payload(builtins["results"][0]))[0]
    require(context["activation"] == "context" and context["root"] == "context" and context["parent"] == {"none": None},
        "production-context-and-absence")
    readings = json.loads(payload(builtins["results"][1]))[0]
    require(len(readings) == 3 and all(int(item["wall"]) > 0 for item in readings)
        and [int(item["monotonic"]) for item in readings] == sorted(int(item["monotonic"]) for item in readings),
        "production-monotonic-and-wall-clock")
    logged = json.loads(payload(builtins["results"][2]))[0]
    require(logged["outcome"] == {"ok": True} and int(logged["after"]) < int(logged["before"])
            and len(builtins["results"][2]["logs"]) == 1, "production-log-and-budget-observation")
    def probe(name, which, text="", *, granted=True, cancel=False, denied=False):
        capability = {"random": "latent:random/random@0.1.0", "metrics": "latent:telemetry/custom@0.1.0",
                      "http": "latent:http/client@0.2.0"}[name]
        value = call("probe", "run", encode([which, text, "0"]), grants=[capability] if granted else [],
            fuel="1000000000", memory="16777216", timeout=5000, cancel=cancel)
        value.update(service="generic", contract=f"tests:{name}/api@1.0.0")
        value["deniedCapabilities"] = [capability] if denied else []
        return value

    def execute(name, calls, fixtures):
        directory = guests / name
        for index, value in enumerate(calls):
            value["id"] = f"{name}-{index}"
        return run(host, cwd, (directory / "component.wasm").read_bytes(),
            (directory / "capsule.json").read_bytes(), (directory / "contracts.json").read_bytes(), calls,
            fixtures=fixtures)

    random = execute("random", [probe("random", 0), probe("random", 3), probe("random", 4),
        probe("random", 2), probe("random", 0, granted=False), probe("random", 3), probe("random", 5, denied=True)],
        {"entropy": base64.b64encode(bytes([255]) * 8).decode()})
    values = random["results"]
    require([payload(values[n]) for n in (0, 1, 2, 3, 5)] ==
        [b'["32"]', b'["18446744073709551615"]', b'["18446744073709551615"]', b'["10"]', b'["18446744073709551615"]'],
        "random-exact-unsigned-and-bounded-length")
    require(values[4]["error"]["code"] == "incompatible-contract", "random-missing-binding")
    require(payload(values[6]) == b'["11"]', "random-policy-denial")
    require(random["entropy"] == "fixed-byte-cycle-fixture" and random["fixtures"]["random"], "explicit-entropy-receipt")

    descriptors = [{"name": name, "kind": kind, "unit": "1", "labels": [{"key": "region", "values": ["east", "west"]}],
        "histogramUpperBounds": [0, 10] if kind == "histogram" else []}
        for name, kind in (("requests", "counter"), ("inflight", "up-down-counter"), ("temperature", "gauge"), ("latency", "histogram"))]
    metrics = execute("metrics", [*[probe("metrics", i, name) for i, name in enumerate(("requests", "inflight", "temperature", "latency"))],
        probe("metrics", 2, "requests"), probe("metrics", 0, "requests", granted=False), probe("metrics", 0, "requests"),
        probe("metrics", 0, "requests", denied=True)],
        {"metrics": descriptors})
    values = metrics["results"]
    require(all(payload(values[n]) == b'["1"]' for n in (0, 1, 2, 3, 6)), "actual-metric-kinds")
    require(payload(values[4]) == b'["10"]' and values[5]["error"]["code"] == "incompatible-contract", "metric-validation-and-missing-binding")
    require(payload(values[7]) == b'["12"]', "metric-policy-denial")
    require(metrics["metrics"]["accepted"] == 5 and metrics["metrics"]["invalid"] == 1, "metric-provider-observation")

    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    url = f"http://127.0.0.1:{port}/fixture"
    fixture = {"http": {"port": port, "exchanges": [{"method": method, "path": "/fixture",
        "requestBody": base64.b64encode(b"payload").decode(), "status": 200,
        "responseBody": base64.b64encode(b"portable").decode()} for method in ("GET", "HEAD")]}}
    http = execute("http", [probe("http", 0, url), probe("http", 1, url), probe("http", 0, url + "-denied"),
        probe("http", 0, url, granted=False), probe("http", 0, url, cancel=True), probe("http", 0, url),
        probe("http", 0, url, denied=True)], fixture)
    values = http["results"]
    require([payload(values[n]) for n in (0, 1, 2, 5)] == [b'["8200"]', b'["200"]', b'["10"]', b'["8200"]'],
        "actual-buffered-http-fixture-and-path-denial")
    require(values[3]["error"]["code"] == "incompatible-contract" and values[4]["error"]["code"] == "cancelled", "http-binding-and-cancellation")
    require(payload(values[6]) == b'["10"]', "http-policy-denial")
    require(http["httpFixtureRequests"] == 3, "denied-and-cancelled-http-never-reached-peer")
    # A completed helper must have released its bound port as well as its job.
    with socket.socket() as reclaimed:
        reclaimed.bind(("127.0.0.1", port))
    # Exercise explicit fixture selection through the same scenario adapter used
    # by the packaged CLI; different entropy never leaks into an adjacent case.
    from tools.tests.test_dev_contracts import descriptor
    root = cwd / "fixture-project"
    for path in (root, root / "src", root / "output"):
        paths.new_directory(path)
    selected = descriptor()
    selected["service"] = "tests/random"
    for source, destination in (("component.wasm", "capsule.wasm"), ("capsule.json", "capsule.json"), ("contracts.json", "contracts.json")):
        paths.write_new(root / "output" / destination, (guests / "random" / source).read_bytes())
    paths.write_new(root / "src/input.json", b'[3,"","0"]')
    cases = []
    for index, byte in enumerate((255, 0)):
        fixture = encode({"entropy": base64.b64encode(bytes([byte]) * 8).decode()})
        paths.write_new(root / f"src/fixture-{index}.json", fixture)
        paths.write_new(root / f"src/expected-{index}.json", b'["18446744073709551615"]' if byte else b'["0"]')
        cases.append({"id": f"entropy-{index}", "service": "tests/random", "contract": "tests:random/api@1.0.0",
            "function": "run", "input": "src/input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
            "expect": {"category": "success", "payload": f"src/expected-{index}.json"}, "requires": ["random"],
            "timeoutMillis": 5000, "required": True,
            "fixtures": [{"id": f"fixture-{index}", "kind": "test-adapter", "identity": digest(fixture), "configuration": f"src/fixture-{index}.json"}],
            "execution": {"grants": ["latent:random/random@0.1.0"]}})
    paths.write_new(root / "src/tests.json", encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    shared = portable.execute(host, root, root, selected, [], host_identity={"kind": "explicit-local-test-build"})
    require(shared["passed"] and len(shared["identity"]["runtime"]["runs"]) == 2, "scoped-scenario-fixture-switch")
    return {"builtins": builtins, "random": random, "metrics": metrics, "http": http, "sharedFixtureScenarios": shared}
