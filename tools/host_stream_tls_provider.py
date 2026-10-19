"""Authenticate the distinct bounded outbound TLS dependency; enable no provider."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import host_stream_tls_patch as captured
from tools.rust_capsule_project import ROOT, read_file

PROVIDER = "crates/vendor/rustls-outbound"
RECORD = "sdk/host-stream-tls/rustls-0.23.46-bounds/PROVIDER.json"
NAME = "latent-rustls-outbound"
RECORD_SHA256 = "b0c1ba7a2900b849204d6ee531a05697709ab798c6ac566c60c7581045f12070"
UPSTREAM_MANIFEST_SHA256 = "ef983ace35d7ad699e22682ee0ee45211f805b074fc9e84190b62f200259070f"


def derived_manifest(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != UPSTREAM_MANIFEST_SHA256:
        raise ValueError("host-tls-provider-manifest-preimage")
    old = b'\nname = "rustls"\nversion = "0.23.46"\n'
    new = b'\nname = "latent-rustls-outbound"\nversion = "0.23.46"\n'
    if original.count(old) != 1:
        raise ValueError("host-tls-provider-manifest-shape")
    return original.replace(old, new, 1)


def verify(root: Path = ROOT) -> dict:
    raw = read_file(root / RECORD, 128 * 1024)
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise ValueError("host-tls-provider-record-identity")
    record = json.loads(raw)
    source = root / PROVIDER
    if source.is_symlink() or not source.is_dir():
        raise ValueError("host-tls-provider-source-directory")
    actual = {}
    for index, path in enumerate(source.rglob("*")):
        if index >= 512:
            raise ValueError("host-tls-provider-tree-bound")
        if path.is_symlink():
            raise ValueError("host-tls-provider-source-link")
        if path.is_dir():
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("host-tls-provider-source-type")
        name = path.relative_to(source).as_posix()
        data = read_file(path, 4 * 1024 * 1024)
        actual[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    expected = record["files"]
    if len(expected) != 119 or set(actual) != set(expected):
        raise ValueError("host-tls-provider-file-set")
    for name, observed in actual.items():
        if observed != {"sha256": expected[name]["afterSha256"], "bytes": expected[name]["bytes"]}:
            raise ValueError("host-tls-provider-file-identity")
    package = tomllib.loads((source / "Cargo.toml").read_text(encoding="utf-8"))
    selected = tomllib.loads(read_file(root / "crates/latent-streams/Cargo.toml", 65536).decode())
    alias = selected.get("dependencies", {}).get("rustls")
    if alias != {"package": NAME, "path": "../vendor/rustls-outbound", "version": "=0.23.46",
                 "default-features": False, "features": ["ring", "std", "tls12"]}:
        raise ValueError("host-tls-provider-selection")
    workspace = tomllib.loads(read_file(root / "Cargo.toml", 65536).decode())
    if PROVIDER not in workspace.get("workspace", {}).get("exclude", []):
        raise ValueError("host-tls-provider-workspace-isolation")
    if any(name in table for table in workspace.get("patch", {}).values() for name in (NAME, "rustls")):
        raise ValueError("host-tls-provider-global-patch")
    lock = tomllib.loads(read_file(root / "Cargo.lock", 4 * 1024 * 1024).decode())
    local = [p for p in lock["package"] if p["name"] == NAME]
    if local != [{"name": NAME, "version": "0.23.46", "dependencies":
                  ["once_cell", "ring", "rustls-pki-types", "rustls-webpki", "subtle", "zeroize"]}]:
        raise ValueError("host-tls-provider-lock-selection")
    gate = read_file(root / "crates/latent-streams/src/tls.rs", 65536)
    if gate.count(b"pub(crate) const ACCOUNTING_QUALIFIED: bool = false;") != 1:
        raise ValueError("host-tls-provider-accounting-gate")
    if (package["package"]["name"] != NAME or package["package"]["version"] != "0.23.46"
            or package["lib"]["name"] != "rustls"):
        raise ValueError("host-tls-provider-package")
    patch = json.loads(read_file(root / "sdk/host-stream-tls/rustls-0.23.46-bounds/PATCH.json", 65536))
    if record["upstream"] != patch["upstream"] or record["patchSha256"] != patch["patchSha256"]:
        raise ValueError("host-tls-provider-patch-identity")
    for row in patch["files"]:
        if expected[row["path"]]["afterSha256"] != row["afterSha256"]:
            raise ValueError("host-tls-provider-parser-identity")
    changed = {name for name, row in expected.items() if row["beforeSha256"] != row["afterSha256"]}
    if changed != captured.CURRENT_FILES | {"Cargo.toml"}:
        raise ValueError("host-tls-provider-change-set")
    return {"schemaVersion": record["schemaVersion"], "package": record["package"],
            "recordSha256": RECORD_SHA256, "files": actual, "upstream": record["upstream"],
            "licenseFiles": record["licenseFiles"],
            "accountingQualified": False, "installed": False}


def reproduce(archive: Path, output: Path) -> dict:
    checked = verify()
    record = json.loads(read_file(ROOT / RECORD, 128 * 1024))
    derivation = captured.apply_current(archive, output)
    original = {name: row["beforeSha256"] for name, row in record["files"].items()}
    if derivation["allOriginalFiles"] != original:
        raise ValueError("host-tls-provider-upstream-closure")
    manifest = output / "Cargo.toml"
    manifest.write_bytes(derived_manifest(manifest.read_bytes()))
    for name, row in checked["files"].items():
        data = read_file(output / name, 4 * 1024 * 1024)
        if {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} != row:
            raise ValueError("host-tls-provider-reproduction")
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (args.archive is None) != (args.output is None):
        parser.error("archive and fresh output must be supplied together")
    result = reproduce(args.archive, args.output) if args.archive is not None else verify()
    print(json.dumps({"package": result["package"], "files": len(result["files"]),
                      "recordSha256": result["recordSha256"], "sourceReproduced": args.archive is not None,
                      "accountingQualified": False, "installed": False}))


if __name__ == "__main__":
    main()
