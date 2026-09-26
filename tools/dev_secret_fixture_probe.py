#!/usr/bin/env python3
"""Execute scoped private-secret disclosure and cleanup on a signed real node."""
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
from tools.dev_workflow import build, paths, project, secret_fixture, snapshot, state
from tools.dev_workflow.common import decode, digest, encode, require
from tools.dev_workflow.node_output import PROVIDER_COUNTERS

WORLD = """package examples:greeting@1.0.0;
interface api { read: func(name: string, abandon: bool) -> u64; }
world service { import latent:secrets/reader@0.1.0; export api; }
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all,
        with: {"latent:secrets/reader@0.1.0": latent_guest::bindings::secrets}});
    use latent_guest::secrets::{Secret, SecretError};
    use core::sync::atomic::{AtomicU32, Ordering};
    static ENTERED: AtomicU32 = AtomicU32::new(0);
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        fn read(name: String, abandon: bool) -> u64 {
            assert_eq!(ENTERED.fetch_add(1, Ordering::Relaxed), 0);
            match Secret::read(&name) {
                Ok(secret) => {
                    let count = secret.bytes().len() as u64;
                    if abandon {core::mem::forget(secret);} else {drop(secret);}
                    count
                },
                Err(SecretError::PermissionDenied) => 10,
                Err(SecretError::NotFound) => 11,
                Err(SecretError::Expired) => 12,
                Err(SecretError::Unavailable) => 13,
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
    secrets = app / "wit/deps/secrets"
    secrets.mkdir(parents=True)
    paths.write_new(secrets / "package.wit", paths.read(app, "vendor/lsf/wit/platform/secrets/package.wit"))
    fixtures = {"secrets": {"references": [{"name": "dev-allowed"}, {"name": "dev-expired", "expired": True}]}}
    raw = encode(fixtures)
    paths.write_new(destination / "tests/secret-fixture.json", raw)
    cases = []
    grants = [secret_fixture.PROVIDER[0]]
    for name, reference, abandon, expected in (("cold-read", "dev-allowed", False, "64"),
            ("warm-read", "dev-allowed", False, "64"), ("abandon-value", "dev-allowed", True, "64"),
            ("after-abandon", "dev-allowed", False, "64"), ("ungranted-reference", "dev-other-workspace", False, "10"),
            ("ungranted-http-reference", "dev-http-peer", False, "10"),
            ("expired", "dev-expired", False, "12"), ("policy-denied", "dev-allowed", False, "10"),
            ("after-denial", "dev-allowed", False, "64")):
        paths.write_new(destination / f"tests/{name}-input.json", json.dumps([reference, abandon]).encode())
        paths.write_new(destination / f"tests/{name}-expected.json", json.dumps([expected]).encode())
        cases.append({"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": "read", "input": f"tests/{name}-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
            "timeoutMillis": 5000, "required": True, "requires": ["scoped-secret-fixture"],
            "expect": {"category": "success", "payload": f"tests/{name}-expected.json"},
            "fixtures": [{"id": "secrets", "kind": "real-provider", "identity": digest(raw),
                          "configuration": "tests/secret-fixture.json"}],
            "execution": {"grants": grants, **({"deniedCapabilities": grants} if name == "policy-denied" else {})}})
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, fixtures


def run(payload: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-secret-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-secret-fixtures-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.secret-node-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed"}
    try:
        author_root = temporary / "Author spaces-\u00fc"
        descriptor, fixtures = author(payload, author_root)
        record, content = snapshot.observe(author_root, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        root = temporary / "test-secrets"
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
            require(shutdown.get("cleanShutdown") is True and counters.get("clean") is True
                    and all(type(counters.get(key)) is int and counters[key] == 0
                            for key in (*PROVIDER_COUNTERS, "secretGenerations", "secretReferences")),
                    "secret-node-resource-reclamation-required")
        for raw in secret_fixture.values(root, fixtures["secrets"]):
            require(raw not in encode(report) and digest(raw).encode() not in encode(report),
                    "private-secret-must-not-enter-public-receipts")
        accepted, _ = build.accepted(root, state.load(root, "project.json"))
        retained = output / "project"
        retained.mkdir(mode=0o700)
        paths.write_new(retained / "latent.project.json", encode(descriptor))
        shutil.copytree(accepted / "tests", retained / "tests")
        shutil.copytree(accepted / "output", retained / "output")
        report.update(passed=True, cleanup="owned-processes-reaped-secret-generations-released-private-workspace-purged",
                      portable="required-linux-secret-provider-not-supported")
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
