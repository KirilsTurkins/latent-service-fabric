"""Apply one authenticated captured rustls parser patch to a fresh private tree."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import tomllib

from tools.rust_capsule_project import ROOT, read_file, fresh


PATCH_ROOT = ROOT / "sdk/host-stream-tls/rustls-bounds"
CURRENT_PATCH_ROOT = ROOT / "sdk/host-stream-tls/rustls-0.23.46-bounds"
CURRENT_FILES = frozenset({"src/msgs/codec.rs", "src/msgs/handshake.rs",
                           "src/msgs/deframer/handshake.rs", "src/conn.rs", "src/quic.rs"})
CURRENT_BOUNDS = {"genericListElements": 64, "certificateEntries": 8,
                  "certificateAuthorityNames": 16, "ownedCertificateExtensionBytesPerEntry": 4096,
                  "handshakeFragmentSpans": 32, "encryptedHandshakeBytesPerDirection": 32768,
                  "originalConnectionReservationBytes": 262144, "originalTrustReservationBytes": 65536}


def current_upstream() -> dict:
    """Only the exact current provider pin and registry lock select this capture."""
    package = tomllib.loads(read_file(ROOT / "crates/latent-streams/Cargo.toml", 65536).decode("utf-8"))
    lock = tomllib.loads(read_file(ROOT / "Cargo.lock", 4 * 1024 * 1024).decode("utf-8"))
    rows = [row for row in lock.get("package", [])
            if row.get("name") == "rustls" and row.get("version") == "0.23.46"]
    if (package.get("dependencies", {}).get("rustls", {}).get("version") != "=0.23.46"
            or len(rows) != 1
            or rows[0].get("source") != "registry+https://github.com/rust-lang/crates.io-index"
            or re.fullmatch(r"[0-9a-f]{64}", rows[0].get("checksum", "")) is None):
        raise ValueError("host-tls-current-provider-pin")
    return {"crate": "rustls", "version": "0.23.46", "archiveSha256": rows[0]["checksum"],
            "license": "Apache-2.0 OR ISC OR MIT"}


def apply(archive: Path, destination: Path) -> dict:
    return _apply(archive, destination, PATCH_ROOT, "0.23.45")


def apply_current(archive: Path, destination: Path) -> dict:
    return _apply(archive, destination, CURRENT_PATCH_ROOT, "0.23.46", current_upstream())


def _apply(archive: Path, destination: Path, patch_root: Path, version: str,
           selected: dict | None = None) -> dict:
    if version not in {"0.23.45", "0.23.46"}:
        raise ValueError("host-tls-captured-version")
    manifest = json.loads(read_file(patch_root / "PATCH.json", 65536))
    if selected is not None and (manifest.get("upstream") != selected
            or manifest.get("bounds") != CURRENT_BOUNDS
            or manifest.get("accountingQualified") is not False
            or manifest.get("nativeReferenceExecuted") is not False
            or manifest.get("doesNotModifySharedRegistry") is not True
            or not isinstance(manifest.get("patchSha256"), str)):
        raise ValueError("host-tls-current-capture-profile")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError("host-tls-captured-patch-file-bound")
    names = []
    for row in rows:
        name = row.get("path")
        if not isinstance(name, str) or not name.startswith("src/") or not name.endswith(".rs") \
                or Path(name).is_absolute() or any(part in {".", ".."} for part in name.split("/")) \
                or any(token in name for token in ("\\", ":")) or name in names:
            raise ValueError("host-tls-captured-patch-path")
        names.append(name)
    if selected is not None and set(names) != CURRENT_FILES:
        raise ValueError("host-tls-current-capture-files")
    archive_bytes = read_file(archive, 8 * 1024 * 1024)
    identity = hashlib.sha256(archive_bytes).hexdigest()
    if identity != manifest["upstream"]["archiveSha256"]:
        raise ValueError("host-tls-captured-public-archive-mismatch")
    if "patchSha256" in manifest and hashlib.sha256(read_file(
            patch_root / f"rustls-{version}-lsf-bounds.patch", 65536)).hexdigest() != manifest["patchSha256"]:
        raise ValueError("host-tls-captured-patch-identity")
    destination = fresh(destination)
    prefix = f"rustls-{version}/"
    before = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as source:
        members = source.getmembers()
        if len(members) > 1024:
            raise ValueError("host-tls-captured-archive-entry-bound")
        for member in members:
            if member.isdir():
                continue
            if not member.isfile() or not member.name.startswith(prefix):
                raise ValueError("host-tls-captured-archive-type")
            relative = member.name.removeprefix(prefix)
            if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ValueError("host-tls-captured-archive-path")
            if member.size > 4 * 1024 * 1024:
                raise ValueError("host-tls-captured-archive-file-bound")
            total += member.size
            if total > 16 * 1024 * 1024 or relative in before:
                raise ValueError("host-tls-captured-archive-byte-or-duplicate-bound")
            raw = source.extractfile(member).read()
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o755 if member.mode & 0o111 else 0o644)
            before[relative] = hashlib.sha256(raw).hexdigest()
    for row in manifest["files"]:
        path = destination / row["path"]
        if before.get(row["path"]) != row["beforeSha256"]:
            raise ValueError("host-tls-captured-patch-preimage")
        modified = read_file(patch_root / "modified" / row["path"], 4 * 1024 * 1024)
        if hashlib.sha256(modified).hexdigest() != row["afterSha256"]:
            raise ValueError("host-tls-captured-patch-postimage")
        path.write_bytes(modified)
    after = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in before}
    changed = {name for name in before if before[name] != after[name]}
    if changed != {row["path"] for row in manifest["files"]}:
        raise ValueError("host-tls-captured-patch-closure")
    return {"upstreamArchiveSha256": identity, "patch": manifest,
            "allOriginalFiles": before, "allResultFiles": after,
            "sharedRegistryModified": False, "accountingQualified": False}
