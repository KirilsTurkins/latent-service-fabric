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
RECORD_SHA256 = "e7f8d01b9b61ee9b4bb9868e95f31626e56bdec60a11e92f973b99b900f0cdea"
UPSTREAM_MANIFEST_SHA256 = "ef983ace35d7ad699e22682ee0ee45211f805b074fc9e84190b62f200259070f"
UPSTREAM_LOCK_SHA256 = "8fb66853b333f7bb99c0d1c0cfcecf15d1a08940f09c7ce26eb3626af81ee6fa"
MAINTAINED_LOCK_SHA256 = "52c650e082bdae0a19592b2ae0aa84894d2bc2570f02a198c3a047ca7b08597a"
LOCK_UPDATES = (
    ("rustls-webpki", "0.103.15", "0.103.16",
     "f3c3cf1d8b1e7d4927e2d154c3fcb02979afb9939629c62cd9048d4f07b60ac2",
     "4443b1b6d39d7c663139942cc4558262562d2c84123bb6282ef177009ca8b281"),
    ("webpki-roots", "1.0.9", "1.0.10",
     "7dcd9d09a39985f5344844e66b0c530a33843579125f23e21e9f0f220850f22a",
     "1c1c8e20c8a38fc7d65abfe74eb7280e4aa667e8eec8bc84996d2874810748d9"),
)


def derived_manifest(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != UPSTREAM_MANIFEST_SHA256:
        raise ValueError("host-tls-provider-manifest-preimage")
    old = b'\nname = "rustls"\nversion = "0.23.46"\n'
    new = b'\nname = "latent-rustls-outbound"\nversion = "0.23.46"\n'
    if original.count(old) != 1:
        raise ValueError("host-tls-provider-manifest-shape")
    return original.replace(old, new, 1)


def derived_lock(original: bytes) -> bytes:
    """Reproduce the two precise Cargo updates and the private package identity."""
    if hashlib.sha256(original).hexdigest() != UPSTREAM_LOCK_SHA256:
        raise ValueError("host-tls-provider-lock-preimage")
    header, *blocks = original.split(b"[[package]]\n")
    old = b'name = "rustls"\nversion = "0.23.46"\n'
    selected = [block for block in blocks if block.startswith(old)]
    if len(blocks) != 134 or len(selected) != 1:
        raise ValueError("host-tls-provider-lock-shape")
    blocks.remove(selected[0])
    renamed = selected[0].replace(old, b'name = "latent-rustls-outbound"\nversion = "0.23.46"\n', 1)
    index = next(i for i, block in enumerate(blocks)
                 if tomllib.loads(block.decode())["name"] > NAME)
    blocks.insert(index, renamed)
    for name, before, after, old_checksum, new_checksum in LOCK_UPDATES:
        prefix = (f'name = "{name}"\nversion = "{before}"\n'
                  'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
                  f'checksum = "{old_checksum}"\n').encode()
        replacement = prefix.replace(f'version = "{before}"'.encode(),
                                     f'version = "{after}"'.encode(), 1)
        replacement = replacement.replace(old_checksum.encode(), new_checksum.encode(), 1)
        matches = [i for i, block in enumerate(blocks) if block.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError("host-tls-provider-lock-package")
        blocks[matches[0]] = blocks[matches[0]].replace(prefix, replacement, 1)
    result = header + b"[[package]]\n" + b"[[package]]\n".join(blocks)
    if hashlib.sha256(result).hexdigest() != MAINTAINED_LOCK_SHA256:
        raise ValueError("host-tls-provider-lock-result")
    return result


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
    if workspace.get("replace"):
        raise ValueError("host-tls-provider-global-replacement")
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
    if changed != captured.CURRENT_FILES | {"Cargo.toml", "Cargo.lock"}:
        raise ValueError("host-tls-provider-change-set")
    if (expected["Cargo.lock"]["beforeSha256"] != UPSTREAM_LOCK_SHA256
            or expected["Cargo.lock"]["afterSha256"] != MAINTAINED_LOCK_SHA256):
        raise ValueError("host-tls-provider-lock-derivation")
    derivation = record["lockDerivation"]
    original_lock = derivation["original"].encode()
    if (derivation != {"original": derivation["original"], "originalSha256": UPSTREAM_LOCK_SHA256,
                       "maintainedSha256": MAINTAINED_LOCK_SHA256,
                       "generator": "cargo 1.97.1",
                       "commands": [["cargo", "update", "--manifest-path", "Cargo.toml", "-p", name,
                                     "--precise", after] for name, _, after, _, _ in LOCK_UPDATES]}
            or derived_lock(original_lock) != read_file(source / "Cargo.lock", 65536)):
        raise ValueError("host-tls-provider-lock-derivation")
    return {"schemaVersion": record["schemaVersion"], "package": record["package"],
            "recordSha256": RECORD_SHA256, "files": actual, "upstream": record["upstream"],
            "upstreamLockSha256": UPSTREAM_LOCK_SHA256,
            "maintainedLockSha256": MAINTAINED_LOCK_SHA256,
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
    lock = output / "Cargo.lock"
    lock.write_bytes(derived_lock(lock.read_bytes()))
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
