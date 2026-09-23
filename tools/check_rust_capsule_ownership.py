#!/usr/bin/env python3
"""Compile actual wasm32 SDK ownership cases; never mistake missing APIs for a pass."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, resolve_tools
from tools.build_process import run_bounded_result
from tools.rust_capsule_project import create, digest, fresh, read_json, snapshot, inventory, write_json

PRELUDE = "#![allow(dead_code)]\nuse latent_guest::{blob, streaming, secrets::Secret};\n"
POSITIVE = """
async fn released_borrows(mut writer: blob::Writer, mut reader: blob::Reader,
                         mut upload: streaming::Upload, mut body: streaming::Body, secret: Secret) {
    let write = writer.write(0, vec![]); drop(write); let _ = writer.close().await;
    let read = reader.read(0, 1); drop(read); let _ = reader.close().await;
    let write = upload.write(vec![]); drop(write); let _ = upload.abort().await;
    let read = body.read(1); drop(read); let _ = body.abort().await;
    let borrowed = secret.bytes(); async {}.await; let _ = borrowed.len(); drop(secret);
}
async fn owned_chunks(blob: blob::Chunk, http: streaming::Chunk) {
    let _owned_guest_bytes = blob.bytes().await;
    let _independent_guest_bytes = http.bytes().await;
}
"""
CASES = {
    "blob-writer-borrow-across-await": ("E0505", "async fn rejected(mut value: blob::Writer) { let pending=value.write(0,vec![]); let _=value.seal().await; drop(pending); }"),
    "blob-reader-borrow-across-close": ("E0505", "async fn rejected(mut value: blob::Reader) { let pending=value.read(0,1); let _=value.close().await; drop(pending); }"),
    "blob-seal-consumes-writer": ("E0382", "async fn rejected(value: blob::Writer) { let _=value.seal().await; let _=value.close().await; }"),
    "blob-close-consumes-reader": ("E0382", "async fn rejected(value: blob::Reader) { let _=value.close().await; let _=value.close().await; }"),
    "blob-chunk-single-owner": ("E0382", "async fn rejected(value: blob::Chunk) { let _=value.bytes().await; let _=value.bytes().await; }"),
    "upload-borrow-across-finish": ("E0505", "async fn rejected(mut value: streaming::Upload) { let pending=value.write(vec![]); let _=value.finish().await; drop(pending); }"),
    "upload-abort-consumes-owner": ("E0382", "async fn rejected(value: streaming::Upload) { let _=value.abort().await; let _=value.finish().await; }"),
    "body-borrow-across-abort": ("E0505", "async fn rejected(mut value: streaming::Body) { let pending=value.read(1); let _=value.abort().await; drop(pending); }"),
    "body-exclusive-pending-reads": ("E0499", "async fn rejected(mut value: streaming::Body) { let first=value.read(1); let second=value.read(1); drop((first,second)); }"),
    "http-chunk-single-owner": ("E0382", "async fn rejected(value: streaming::Chunk) { let _=value.bytes().await; let _=value.bytes().await; }"),
    "secret-bytes-cannot-outlive-owner": ("E0505", "fn rejected(value: Secret) { let borrowed=value.bytes(); drop(value); let _=borrowed.len(); }"),
}


def check(output: Path, *, offline=False):
    output = fresh(output)
    project = create(output / "project", "greeting", "borrow-checks")
    pins = read_json(project / "sdk-lock.json")
    original = snapshot(project)
    environment = build_environment(output)
    if offline:
        environment["CARGO_NET_OFFLINE"] = "true"
    paths, materials = resolve_tools(pins["toolchain"], project, environment)
    environment.update(RUSTC=str(paths["rustc"]), RUSTUP_TOOLCHAIN=pins["toolchain"]["rust"]["toolchain"],
                       CARGO_INCREMENTAL="0", CARGO_TARGET_DIR=str(output / "compiled"))
    deadline = time.monotonic() + 360
    rows = []
    for name, (expected, body) in {"valid-ownership": (None, POSITIVE), **CASES}.items():
        source = (PRELUDE + body + "\n").encode()
        (project / "src/lib.rs").write_bytes(source)
        (output / (name + ".rs")).write_bytes(source)
        remaining = min(180, deadline - time.monotonic())
        if remaining <= 0:
            raise ValueError("ownership compile deadline")
        result = run_bounded_result([str(paths["cargo"]), "check", "--locked", "--lib", "--target", "wasm32-unknown-unknown", "--message-format=json"],
                                    project, environment, timeout_seconds=remaining, max_output_bytes=4 * 1024 * 1024)
        (output / (name + ".jsonl")).write_bytes(result.stdout)
        (output / (name + ".stderr.txt")).write_bytes(result.stderr)
        codes = set()
        for line in result.stdout.splitlines():
            value = json.loads(line)
            if value.get("reason") == "compiler-message" and value["message"]["level"] == "error":
                codes.add((value["message"].get("code") or {}).get("code"))
        if expected is None:
            if result.returncode != 0 or codes:
                raise ValueError("positive wasm32 ownership case failed")
        elif result.returncode != 101 or codes != {expected}:
            raise ValueError("negative ownership case failed for an unexpected reason: " + name)
        rows.append({"name": name, "sourceDigest": digest(source), "exitCode": result.returncode,
                     "expectedDiagnostic": expected, "observedDiagnostics": sorted(codes)})
    (project / "src/lib.rs").write_bytes(original["src/lib.rs"])
    if snapshot(project) != original:
        raise ValueError("ownership input source changed")
    receipt = {"schemaVersion": "latent.rust-capsule.ownership.v1", "status": "passed", "scope": "actual-wasm32-rust-type-checking",
               "projectSourceDigest": digest(inventory(original)), "materials": materials, "cases": rows}
    write_json(output / "ownership.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.output, offline=args.offline)))


if __name__ == "__main__":
    main()
