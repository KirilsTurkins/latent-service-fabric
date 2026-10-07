"""Apply one authenticated captured rustls parser patch to a fresh private tree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile

from tools.rust_capsule_project import ROOT, read_file, fresh


PATCH_ROOT = ROOT / "sdk/host-stream-tls/rustls-bounds"


def apply(archive: Path, destination: Path) -> dict:
    manifest = json.loads(read_file(PATCH_ROOT / "PATCH.json", 65536))
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
    with archive.open("rb") as source:
        identity = hashlib.file_digest(source, "sha256").hexdigest()
    if identity != manifest["upstream"]["archiveSha256"]:
        raise ValueError("host-tls-captured-public-archive-mismatch")
    destination = fresh(destination)
    prefix = "rustls-0.23.45/"
    before = {}
    total = 0
    with tarfile.open(archive, "r:gz") as source:
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
        modified = read_file(PATCH_ROOT / "modified" / row["path"], 4 * 1024 * 1024)
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
