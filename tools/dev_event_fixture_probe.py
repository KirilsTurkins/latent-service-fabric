#!/usr/bin/env python3
"""Authored immediate publishes through the real provider and owned TLS peer."""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_node_application_probe import run as run_node
from tools.dev_workflow import build, event_fixture, paths, project, snapshot, state
from tools.dev_workflow.common import decode, digest, encode, require
from tools.dev_workflow.node_output import PROVIDER_COUNTERS

WORLD = """package examples:greeting@1.0.0;
interface api { publish: func(topic: string, invalid: bool) -> u64; }
world service { import latent:events/publisher@0.2.0; export api; }
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all,
        with: {"latent:events/publisher@0.2.0": latent_guest::bindings::events}});
    use latent_guest::events::{self, Event, EventError};
    use core::sync::atomic::{AtomicU32, Ordering};
    static ENTERED: AtomicU32 = AtomicU32::new(0);
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        fn publish(topic: String, invalid: bool) -> u64 {
            assert_eq!(ENTERED.fetch_add(1, Ordering::Relaxed), 0);
            let event = Event {topic, key: None, payload: b"event-dev".to_vec(),
                media_type: "application/octet-stream".into(), attributes: vec![],
                idempotency_key: if invalid {String::new()} else {"probe-event".into()}};
            match events::publish(&event) {
                Ok(receipt) => {
                    assert!(!receipt.event_id.is_empty());
                    assert_eq!(receipt.stream_name, "LSF_DEV");
                    assert!(receipt.sequence > 0 && receipt.accepted_at_unix_millis > 0);
                    if receipt.duplicate {2} else {1}
                },
                Err(EventError::PermissionDenied) => 10,
                Err(EventError::Uncertain) => 11,
                Err(EventError::Unavailable) => 12,
                Err(EventError::InvalidEvent) => 13,
                Err(EventError::InvalidTopic) => 14,
                Err(EventError::BudgetExhausted) => 15,
                Err(EventError::DeadlineExceeded) => 16,
                Err(EventError::Cancelled) => 17,
            }
        }
    }
    export!(Capsule);
}
"""


def author(payload: Path, destination: Path) -> tuple[dict, dict]:
    entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
    template = payload / entry["path"]
    manifest = decode(paths.read(template, "template.json"))
    project.scaffold(template, destination, manifest, entry["identity"])
    descriptor = copy.deepcopy(manifest["project"])
    require(descriptor["language"] == "rust", "rust-authoring-template-required")
    app = destination / "app"
    (app / "src/lib.rs").write_text(COMPONENT, encoding="utf-8", newline="\n")
    (app / "wit/world.wit").write_text(WORLD, encoding="utf-8", newline="\n")
    recipe = decode(paths.read(app, "capsule-project.json"))
    recipe["limits"].update(outboundRequests=8, memoryBytes=16777216, cpuFuel=1000000000, wallTimeLimitMillis=5000)
    (app / "capsule-project.json").write_bytes(encode(recipe))
    events = app / "wit/deps/events-v2"
    events.mkdir(parents=True)
    paths.write_new(events / "package.wit", paths.read(app, "vendor/lsf/wit/platform/events-v2/package.wit"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    fixtures = {"events": {"port": port, "exchanges": [{"topic": "dev." + mode, "mode": mode,
        "payload": base64.b64encode(b"event-dev").decode()} for mode in sorted(event_fixture.MODES)]}}
    raw = encode(fixtures)
    paths.write_new(destination / "tests/event-fixture.json", raw)
    cases = []
    grants = [event_fixture.PROVIDER[0]]
    for name, topic, invalid, expected in (
        ("cold", "dev.ack", False, "1"), ("warm", "dev.ack", False, "1"),
        ("duplicate-receipt", "dev.duplicate", False, "2"),
        ("unknown-topic", "dev.foreign", False, "10"), ("invalid-topic", "dev.*", False, "14"),
        ("invalid-event", "dev.ack", True, "13"), ("policy-denied", "dev.ack", False, "10"),
        ("after-denial", "dev.ack", False, "1"), ("lost-ack-uncertain", "dev.drop-ack", False, "11"),
        ("after-lost-ack", "dev.ack", False, "1"), ("wrong-stream-uncertain", "dev.wrong-stream", False, "11"),
        ("after-wrong-stream", "dev.ack", False, "1"), ("malformed-ack-uncertain", "dev.malformed-ack", False, "11"),
        ("after-malformed", "dev.ack", False, "1"), ("no-responders", "dev.no-responders", False, "12"),
        ("after-no-responders", "dev.ack", False, "1")):
        paths.write_new(destination / f"tests/{name}-input.json", json.dumps([topic, invalid]).encode())
        paths.write_new(destination / f"tests/{name}-expected.json", json.dumps([expected]).encode())
        cases.append({"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": "publish", "input": f"tests/{name}-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
            "timeoutMillis": 5000, "required": True, "requires": ["immediate-event-fixture"],
            "expect": {"category": "success", "payload": f"tests/{name}-expected.json"},
            "fixtures": [{"id": "events", "kind": "controlled-peer", "identity": digest(raw), "configuration": "tests/event-fixture.json"}],
            "execution": {"grants": grants, **({"deniedCapabilities": grants} if name == "policy-denied" else {})}})
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, fixtures


def run(payload: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(), "new-unprivileged-linux-event-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-events-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.event-node-probe.v1", "publisherAuthenticated": False,
              "liveBroker": False, "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed"}
    try:
        descriptor, fixtures = author(payload, temporary / "Author spaces-\u00fc")
        record, content = snapshot.observe(temporary / "Author spaces-\u00fc", descriptor["inputRoots"], tuple(descriptor["exclude"]))
        root = temporary / "test-events"
        root.mkdir(mode=0o700)
        (root / "snapshots").mkdir(mode=0o700)
        source = root / "snapshots" / record["identity"][7:]
        snapshot.materialize(source, record, content)
        trust = project.trust_identity(descriptor)
        state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
            "source": str(source), "snapshot": record["identity"]})
        build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
        report["node"] = run_node(root, supplied, payload, descriptor, output / "node", fixtures=fixtures)
        for key in ("shutdownBeforeRestart", "shutdown"):
            shutdown = report["node"][key]
            counters = shutdown.get("providerShutdown", {})
            peer = shutdown.get("fixtures", {}).get("events", {})
            require(shutdown.get("cleanShutdown") is True and counters.get("clean") is True
                    and all(type(counters.get(key)) is int and counters[key] == 0
                            for key in (*PROVIDER_COUNTERS, "secretGenerations", "secretReferences"))
                    and peer.get("cleanup") == "owned-listener-and-connections-closed"
                    and peer.get("openConnections") == 0, "event-node-resource-reclamation-required")
        before = report["node"]["tests"]["identity"]["fixtureRuntime"]["events"]
        after = report["node"]["tests"]["identity"]["fixtureRuntimeAfter"]["events"]
        require(after["receivedPublishes"] - before["receivedPublishes"] == 12, "denied-or-invalid-events-must-not-contact-peer")
        require(all(after["receivedByTopic"]["dev." + mode] == 1 for mode in
                    ("drop-ack", "wrong-stream", "malformed-ack", "no-responders", "duplicate")),
                "uncertain-publish-must-never-be-replayed")
        for name, raw in event_fixture.material(root, fixtures["events"])[1].items():
            if name in {"key.pem", "authorization"}:
                require(raw not in encode(report) and digest(raw).encode() not in encode(report), "private-event-material-in-public-receipt")
        accepted, _ = build.accepted(root, state.load(root, "project.json"))
        retained = output / "project"
        retained.mkdir(mode=0o700)
        paths.write_new(retained / "latent.project.json", encode(descriptor))
        shutil.copytree(accepted / "tests", retained / "tests")
        shutil.copytree(accepted / "output", retained / "output")
        report.update(passed=True, cleanup="owned-processes-peer-and-private-material-purged",
                      portable="required-linux-event-provider-not-supported")
    finally:
        if report["passed"]:
            shutil.rmtree(temporary)
        else:
            report["retainedPrivateWorkspace"] = str(temporary)
        state.atomic(output, "observation.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "source-node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True), args.output.absolute())
    print(encode({"passed": receipt["passed"], "cleanup": receipt["cleanup"]}).decode())
