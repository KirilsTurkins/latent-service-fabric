#!/usr/bin/env python3
"""Execute an authored signed caller/callee pair through a real node's public APIs."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_node_application_probe import run as run_node
from tools.dev_workflow import build, build_control, local_service_fixture, paths, project, snapshot, state
from tools.dev_workflow.common import decode, digest, encode, require
from tools.dev_workflow.node_output import PROVIDER_COUNTERS

CALLER_WIT = """package examples:greeting@1.0.0;
interface api { run: async func(which: u32) -> u64; }
world service { import latent:service/invoke@0.1.0; export api; }
"""
CALLEE_WIT = """package examples:callee@1.0.0;
interface api { answer: func() -> u32; fail: func() -> result<u32, string>; trap: func() -> u32; }
world service { export api; }
"""
CALLEE = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all});
    use core::sync::atomic::{AtomicU32, Ordering};
    static ENTERED: AtomicU32 = AtomicU32::new(0);
    fn fresh() { assert_eq!(ENTERED.fetch_add(1, Ordering::Relaxed), 0); }
    struct Capsule;
    impl exports::examples::callee::api::Guest for Capsule {
        fn answer() -> u32 { fresh(); 42 }
        fn fail() -> Result<u32, String> { fresh(); Err("expected-local-error".into()) }
        fn trap() -> u32 { fresh(); panic!("expected-local-trap") }
    }
    export!(Capsule);
}
"""
CALLER = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all,
        with: {"latent:service/invoke@0.1.0": latent_guest::bindings::service}});
    use latent_guest::service::{self, CallOptions, InvocationOutcome, PlatformErrorCode, Target};
    use core::sync::atomic::{AtomicU32, Ordering};
    static ENTERED: AtomicU32 = AtomicU32::new(0);
    async fn call(which: u32) -> u64 {
        let outcome = service::call(Target {
            tenant: if which == 3 {Some("foreign".into())} else {None},
            service: if which == 2 {"examples/foreign"} else {"examples/local-callee"}.into(),
            contract: if which == 4 {"examples:foreign/api@1.0.0"} else {"examples:callee/api@1.0.0"}.into(),
            function: match which {1 => "fail", 6 => "unknown", 7 => "trap", _ => "answer"}.into(),
            route: Some(if which == 5 {"foreign"} else {"local-callee"}.into()),
        }, b"[]".to_vec(), "application/vnd.latent.wit-values.v1+json".into(),
        CallOptions {deadline_unix_millis: None, priority: 0, idempotency_key: None, metadata: vec![]}).await;
        match outcome {
            InvocationOutcome::Success(result) => {assert_eq!(result.payload, b"[42]"); 42},
            InvocationOutcome::DeclaredError(error) => {assert!(!error.payload.is_empty()); 10},
            InvocationOutcome::PlatformFailure(error) => match error.code {
                PlatformErrorCode::PermissionDenied => 11,
                PlatformErrorCode::Cancelled => 12,
                PlatformErrorCode::DeadlineExceeded => 13,
                PlatformErrorCode::ResourceExhausted => 14,
                PlatformErrorCode::GuestTrap => 15,
                other => panic!("unexpected child outcome: {other:?}"),
            }
        }
    }
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        async fn run(which: u32) -> u64 {
            assert_eq!(ENTERED.fetch_add(1, Ordering::Relaxed), 0);
            let first = call(which).await;
            if which == 8 {first * 100 + call(0).await} else {first}
        }
    }
    export!(Capsule);
}
"""


def author(payload: Path, destination: Path) -> tuple[dict, dict]:
    entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
    template = payload / entry["path"]
    manifest = decode(paths.read(template, "template.json"))
    require(manifest["project"]["language"] == "rust", "rust-authoring-template-required")
    descriptors = []
    for root, name, world, wit, component, memory in (
            (destination, "local-caller", "examples:greeting/service@1.0.0", CALLER_WIT, CALLER, 33554432),
            (destination / "callee", "local-callee", "examples:callee/service@1.0.0", CALLEE_WIT, CALLEE, 8388608)):
        project.scaffold(template, root, manifest, entry["identity"])
        descriptor = copy.deepcopy(manifest["project"])
        descriptor.update(name=name, service="examples/" + name)
        app = root / "app"
        (app / "src/lib.rs").write_text(component, encoding="utf-8", newline="\n")
        (app / "wit/world.wit").write_text(wit, encoding="utf-8", newline="\n")
        recipe = decode(paths.read(app, "capsule-project.json"))
        original_name = recipe["name"]
        for filename in ("Cargo.toml", "Cargo.lock"):
            cargo = paths.read(app, filename).decode("utf-8")
            old = 'name = "' + original_name + '"'
            require(cargo.count(old) == 1, "exact-authoring-package-name-required")
            (app / filename).write_text(cargo.replace(old, 'name = "' + name + '"'), encoding="utf-8", newline="\n")
        recipe.update(name=name, service=descriptor["service"], world=world)
        recipe["limits"].update(memoryBytes=memory, cpuFuel=1000000000, wallTimeLimitMillis=5000, childCalls=16)
        (app / "capsule-project.json").write_bytes(encode(recipe))
        (root / "latent.project.json").write_bytes(encode(descriptor))
        descriptors.append(descriptor)
    descriptor, callee = descriptors
    child = destination / "callee"
    paths.write_new(child / "tests/local-input.json", b"[]")
    paths.write_new(child / "tests/local-expected.json", b"[42]")
    (child / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [{
        "id": "answer", "service": callee["service"], "contract": "examples:callee/api@1.0.0", "function": "answer",
        "input": "tests/local-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
        "timeoutMillis": 5000, "required": True, "requires": ["fresh-state"], "fixtures": [],
        "expect": {"category": "success", "payload": "tests/local-expected.json"}}]}))
    invocation = destination / "app/wit/deps/invocation"
    invocation.mkdir(parents=True)
    paths.write_new(invocation / "package.wit", paths.read(destination / "app", "vendor/lsf/wit/platform/invocation/package.wit"))
    descriptor["inputRoots"].append("callee")
    fixture = {"service": callee["service"], "deployment": "local-callee", "contract": "examples:callee/api@1.0.0",
               "project": "callee", "recipeSha256": project.trust_identity(callee)}
    fixtures = {"localService": fixture}
    raw = encode(fixtures)
    paths.write_new(destination / "tests/local-fixture.json", raw)
    cases = []
    grants = [local_service_fixture.PROVIDER[0]]
    for name, which, expected in (("cold", 0, "42"), ("warm", 0, "42"), ("declared-error", 1, "10"),
            ("wrong-service", 2, "11"), ("wrong-tenant", 3, "11"), ("wrong-contract", 4, "11"),
            ("wrong-route", 5, "11"), ("wrong-function", 6, "11"), ("policy-denied", 0, "11"),
            ("after-denial", 0, "42"), ("child-trap", 7, "15"), ("after-trap", 0, "42"),
            ("two-fresh-children", 8, "4242"), ("after-two", 0, "42")):
        paths.write_new(destination / f"tests/{name}-input.json", json.dumps([which]).encode())
        paths.write_new(destination / f"tests/{name}-expected.json", json.dumps([expected]).encode())
        cases.append({"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": "run", "input": f"tests/{name}-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
            "timeoutMillis": 5000, "required": True, "requires": ["local-service-fixture", "fresh-state"],
            "expect": {"category": "success", "payload": f"tests/{name}-expected.json"},
            "fixtures": [{"id": "local", "kind": "real-provider", "identity": digest(raw), "configuration": "tests/local-fixture.json"}],
            "execution": {"grants": grants, **({"deniedCapabilities": grants} if name == "policy-denied" else {})}})
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, fixtures


def run(payload: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(), "new-unprivileged-linux-local-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-local-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.local-service-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed"}
    try:
        authored = temporary / "Author spaces-\u00fc"
        descriptor, fixtures = author(payload, authored)
        record, content = snapshot.observe(authored, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        root = temporary / "test-local"
        root.mkdir(mode=0o700)
        (root / "snapshots").mkdir(mode=0o700)
        source = root / "snapshots" / record["identity"][7:]
        snapshot.materialize(source, record, content)
        trust = project.trust_identity(descriptor)
        state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust, "source": str(source), "snapshot": record["identity"]})
        build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
        report["node"] = run_node(root, supplied, payload, descriptor, output / "node", fixtures=fixtures)
        dependency = report["node"]["tests"]["identity"]["fixtureRuntime"]["localService"]
        retained = report["node"]["retained"]["identity"]["fixtureRuntime"]["localService"]
        require(dependency["deployment"] == retained["deployment"], "local-callee-must-survive-restart-without-redeployment")
        report["calleeBuild"] = build_control.status(root / local_service_fixture.CHILD)
        require(report["calleeBuild"]["state"] == "reaped", "local-callee-compiler-cleanup-required")
        for key in ("shutdownBeforeRestart", "shutdown"):
            shutdown = report["node"][key]
            counters = shutdown.get("providerShutdown", {})
            require(shutdown.get("cleanShutdown") is True and counters.get("clean") is True
                    and all(type(counters.get(key)) is int and counters[key] == 0
                            for key in (*PROVIDER_COUNTERS, "secretGenerations", "secretReferences")),
                    "local-service-owned-cleanup-required")
        report.update(passed=True, cleanup="owned-node-and-client-processes-reaped-private-pair-workspace-purged",
                      portable="required-node-local-service-fixture-not-supported", dependency=dependency)
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
