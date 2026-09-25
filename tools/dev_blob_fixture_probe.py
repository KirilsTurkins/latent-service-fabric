#!/usr/bin/env python3
"""Author and execute immutable-blob ownership cases on a signed separate node."""
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
from tools.dev_workflow import build, paths, project, snapshot, state
from tools.dev_workflow.common import decode, digest, encode, require
from tools.dev_workflow.node_output import PROVIDER_COUNTERS

WORLD = """package examples:greeting@1.0.0;
interface api { run: async func(mode: u32) -> u64; }
world service { import latent:blob/blob@0.2.0; export api; }
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all,
        with: {"latent:blob/blob@0.2.0": latent_guest::bindings::blob}});
    use latent_guest::{bindings::blob as raw, blob::{Reader, Writer}};
    use core::sync::atomic::{AtomicU32, Ordering};
    static ENTERED: AtomicU32 = AtomicU32::new(0);
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        async fn run(mode: u32) -> u64 {
            assert_eq!(ENTERED.fetch_add(1, Ordering::Relaxed), 0);
            probe(mode).await.unwrap_or_else(|(operation, error)| {
                operation * 100 + match error {
                    raw::BlobError::NotFound => 1, raw::BlobError::PermissionDenied => 2,
                    raw::BlobError::InvalidRange => 3, raw::BlobError::InvalidState => 4,
                    raw::BlobError::ChecksumMismatch => 5, raw::BlobError::BudgetExhausted => 6,
                    raw::BlobError::Unavailable => 7, raw::BlobError::Uncertain => 8,
                    raw::BlobError::DeadlineExceeded => 9, raw::BlobError::Cancelled => 10,
                }
            })
        }
    }
    async fn probe(mode: u32) -> Result<u64, (u64, raw::BlobError)> {
        let reference = raw::BlobReference {digest: "sha256:3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7".into(),
            size: 4, media_type: "text/plain".into()};
        if mode == 0 || mode == 2 || mode == 6 {
            let mut writer = Writer::create("text/plain".into(), Some(4)).await.map_err(|e| (1, e))?;
            assert_eq!(writer.write(0, b"data".to_vec()).await.map_err(|e| (2, e))?, 4);
            if mode == 2 { return Ok(1); } // activation owns the unsealed stage and writer
            let sealed = writer.seal().await.map_err(|e| (3, e))?;
            assert_eq!(sealed.digest, reference.digest);
        }
        if mode == 4 {
            let handle = raw::create("text/plain".into(), Some(0)).await.map_err(|e| (1, e))?;
            assert!(raw::close(handle).await.map_err(|e| (4, e))?);
            return match raw::write(handle, 0, vec![]).await {
                Err(raw::BlobError::InvalidState | raw::BlobError::PermissionDenied) => Ok(10),
                Err(e) => Err((2, e)), Ok(_) => panic!("closed writer was reusable"),
            };
        }
        let mut reader = Reader::open(reference).await.map_err(|e| (5, e))?;
        let chunk = reader.read(0, 4).await.map_err(|e| (6, e))?;
        if mode == 5 {
            core::mem::forget(chunk); // component teardown must reclaim the still-owned resource
            return Ok(5); // reader also deliberately remains open
        }
        assert!(reader.close().await.map_err(|e| (4, e))?);
        if mode == 3 { drop(chunk); return Ok(3); }
        let bytes = chunk.bytes().await.map_err(|e| (7, e))?;
        assert_eq!(bytes, b"data");
        Ok(bytes.len() as u64)
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
    recipe["limits"].update(outboundRequests=8, blobReadBytes=65536, blobWriteBytes=65536,
        memoryBytes=16777216, cpuFuel=1000000000, wallTimeLimitMillis=5000)
    (app / "capsule-project.json").write_bytes(encode(recipe))
    blob = app / "wit/deps/blob-v2"
    blob.mkdir(parents=True)
    paths.write_new(blob / "package.wit", paths.read(app, "vendor/lsf/wit/platform/blob-v2/package.wit"))
    fixtures = {"blob": {"namespace": "dev-blobs"}}
    raw = encode(fixtures)
    paths.write_new(destination / "tests/blob-fixture.json", raw)
    cases = []
    grants = ["latent:blob/blob@0.2.0"]
    schedule = [("cold-seal", 0, "4"), ("warm-read", 1, "4"),
            ("abandon-writer", 2, "1"), ("after-writer", 1, "4"), ("closed-writer", 4, "10"),
            ("drop-chunk", 3, "3"), ("abandon-reader-chunk", 5, "5"),
            *[(f"retired-stage-{index}", 2, "1") for index in range(18)],
            ("policy-denied", 6, "102"), ("after-denial", 1, "4")]
    for name, mode, expected in schedule:
        paths.write_new(destination / f"tests/{name}-input.json", json.dumps([mode]).encode())
        paths.write_new(destination / f"tests/{name}-expected.json", json.dumps([expected]).encode())
        cases.append({"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": "run", "input": f"tests/{name}-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
            "timeoutMillis": 5000, "required": True, "requires": ["immutable-blob-fixture"],
            "expect": {"category": "success", "payload": f"tests/{name}-expected.json"},
            "fixtures": [{"id": "blob", "kind": "real-provider", "identity": digest(raw),
                          "configuration": "tests/blob-fixture.json"}],
            "execution": {"grants": grants, **({"deniedCapabilities": grants} if name == "policy-denied" else {})}})
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, fixtures


def run(payload: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-blob-probe-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-blob-fixtures-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "fixture-project-outside-checkout")
    report = {"schemaVersion": "latent.dev.blob-node-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed"}
    try:
        descriptor, fixtures = author(payload, temporary / "Author spaces-\u00fc")
        author_root = temporary / "Author spaces-\u00fc"
        record, content = snapshot.observe(author_root, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        root = temporary / "test-blob"
        root.mkdir(mode=0o700)
        (root / "snapshots").mkdir(mode=0o700)
        source = root / "snapshots" / record["identity"][7:]
        snapshot.materialize(source, record, content)
        trust = project.trust_identity(descriptor)
        state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
            "source": str(source), "snapshot": record["identity"]})
        build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
        report["node"] = run_node(root, supplied, payload, descriptor, output / "node", fixtures=fixtures,
                                  retained_selection=["warm-read"])
        for key in ("shutdownBeforeRestart", "shutdown"):
            shutdown = report["node"][key]
            counters = shutdown.get("providerShutdown", {})
            require(shutdown.get("cleanShutdown") is True and counters.get("clean") is True
                    and all(type(counters.get(key)) is int and counters[key] == 0
                            for key in PROVIDER_COUNTERS if key != "blobStages")
                    and counters.get("blobStages") == 16,
                    "blob-node-resource-reclamation-required")
        accepted, _ = build.accepted(root, state.load(root, "project.json"))
        retained = output / "project"
        retained.mkdir(mode=0o700)
        paths.write_new(retained / "latent.project.json", encode(descriptor))
        shutil.copytree(accepted / "tests", retained / "tests")
        shutil.copytree(accepted / "output", retained / "output")
        report.update(passed=True, cleanup="owned-processes-reaped-live-provider-counters-zero-private-workspace-purged",
                      retainedDurableStages={"count": 16, "limit": 16,
                          "disposition": "charged-until-bounded-reclamation-or-explicit-workspace-purge"},
                      retainedBlobReadWithoutWrite=True, portable="required-linux-blob-provider-not-supported")
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
