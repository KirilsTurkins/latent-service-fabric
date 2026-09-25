#!/usr/bin/env python3
"""Author a capsule and compare authenticated production HTTP on node/native hosts."""
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

from tools.compare_dev_node_portable import compare
from tools.dev_node_application_probe import run as run_node
from tools.dev_workflow import build, paths, portable, project, snapshot, state
from tools.dev_workflow.common import decode, digest, encode, require

WORLD = """package examples:greeting@1.0.0;
interface api { send: async func(head: bool, url: string) -> u64; }
world service { import latent:http/client@0.2.0; export api; }
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all,
        with: {"latent:http/client@0.2.0": latent_guest::bindings::http}});
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        async fn send(head: bool, url: String) -> u64 {
            use latent_guest::http::{self, HttpError, Method, Request};
            match http::send(Request {method: if head {Method::Head} else {Method::Get}, url,
                headers: vec![], body: Some(b"payload".to_vec()), body_media_type: Some("text/plain".into()),
                idempotency_key: None, timeout_millis: Some(1000)}).await {
                Ok(response) => u64::from(response.status) + 1000 * response.body.len() as u64,
                Err(HttpError::PermissionDenied) => 10,
                Err(HttpError::BudgetExhausted) => 18,
                Err(HttpError::DeadlineExceeded) => 16,
                Err(HttpError::ConnectionFailed) => 21,
                Err(_) => 99,
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
    recipe["limits"].update(outboundRequests=1, memoryBytes=16777216, cpuFuel=1000000000, wallTimeLimitMillis=5000)
    (app / "capsule-project.json").write_bytes(encode(recipe))
    http = app / "wit/deps/http-v2"
    http.mkdir(parents=True)
    paths.write_new(http / "package.wit", paths.read(app, "vendor/lsf/wit/platform/http-v2/package.wit"))
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    fixtures = {"http": {"port": port, "exchanges": [{"method": method, "path": "/fixture",
        "requestBody": base64.b64encode(b"payload").decode(), "status": 200,
        "responseBody": base64.b64encode(b"http-dev").decode()} for method in ("GET", "HEAD")]}}
    raw = encode(fixtures)
    paths.write_new(destination / "tests/http-fixture.json", raw)
    cases = []
    grants = ["latent:http/client@0.2.0"]
    for name, head, suffix, expected in (("cold", False, "", "8200"), ("warm", False, "", "8200"),
            ("head", True, "", "200"), ("path-denied", False, "-denied", "10"),
            ("policy-denied", False, "", "10"), ("after-denial", False, "", "8200")):
        paths.write_new(destination / f"tests/{name}-input.json", json.dumps([head, f"http://127.0.0.1:{port}/fixture{suffix}"]).encode())
        paths.write_new(destination / f"tests/{name}-expected.json", json.dumps([expected], separators=(",", ":")).encode())
        cases.append({"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": "send", "input": f"tests/{name}-input.json",
            "mediaType": "application/vnd.latent.wit-values.v1+json", "timeoutMillis": 5000,
            "required": True, "requires": ["buffered-http-fixture"],
            "expect": {"category": "success", "payload": f"tests/{name}-expected.json"},
            "fixtures": [{"id": "http", "kind": "controlled-peer", "identity": digest(raw),
                          "configuration": "tests/http-fixture.json"}],
            "execution": {"grants": grants, **({"deniedCapabilities": grants} if name == "policy-denied" else {})}})
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, fixtures


def run(payload: Path, supplied: Path, portable_host: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-http-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-http-fixtures-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.http-node-portable-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed"}
    try:
        author_root = temporary / "Author spaces-\u00fc"
        descriptor, fixtures = author(payload, author_root)
        record, content = snapshot.observe(author_root, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        root = temporary / "test-http"
        root.mkdir(mode=0o700)
        (root / "snapshots").mkdir(mode=0o700)
        source = root / "snapshots" / record["identity"][7:]
        snapshot.materialize(source, record, content)
        trust = project.trust_identity(descriptor)
        state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
            "source": str(source), "snapshot": record["identity"]})
        build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
        report["node"] = run_node(root, supplied, payload, descriptor, output / "node", fixtures=fixtures)
        accepted, _ = build.accepted(root, state.load(root, "project.json"))
        native = portable.execute(portable_host, accepted, accepted, descriptor, [], host_identity={"kind": "explicit-local-test-build"})
        report.update(portable=native, comparison=compare(report["node"]["tests"], native, native_os="linux"))
        before = report["node"]["tests"]["identity"]["fixtureRuntime"]["http"]
        after = report["node"]["tests"]["identity"]["fixtureRuntimeAfter"]["http"]
        require(after["completedRequests"] - before["completedRequests"] == 4
                and native["identity"]["runtime"]["runs"][0]["httpFixtureRequests"] == 4,
                "denied-http-cases-must-not-contact-peer")
        shutdown = report["node"]["shutdown"].get("fixtures", {}).get("http", {})
        require(shutdown.get("cleanup") == "owned-listener-and-connections-closed"
                and shutdown.get("openConnections") == 0, "http-node-fixture-cleanup-required")
        state.atomic(output, "shared-node.json", report["node"]["tests"])
        state.atomic(output, "portable.json", native)
        retained = output / "project"
        retained.mkdir(mode=0o700)
        paths.write_new(retained / "latent.project.json", encode(descriptor))
        shutil.copytree(accepted / "tests", retained / "tests")
        shutil.copytree(accepted / "output", retained / "output")
        report.update(passed=True, cleanup="owned-node-peer-and-portable-processes-reaped")
    finally:
        if report["passed"]:
            shutil.rmtree(temporary)
        else:
            report["retainedPrivateWorkspace"] = str(temporary)
        state.atomic(output, "observation.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "source-node", "portable-host", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True),
                  args.portable_host.resolve(strict=True), args.output.absolute())
    print(encode({"passed": receipt["passed"], "cleanup": receipt["cleanup"]}).decode())
