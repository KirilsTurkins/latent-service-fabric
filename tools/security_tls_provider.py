"""Advisory identity for the single authenticated private outbound TLS package."""
from __future__ import annotations

import json
from pathlib import Path

from tools import host_stream_tls_provider as bounded
from tools.security_common import SecurityError, require

MANIFEST = bounded.PROVIDER + "/Cargo.toml"
LOCK = bounded.PROVIDER + "/Cargo.lock"
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


def origin(repo: Path, paths: list[str]) -> dict | None:
    if not any(path.startswith(bounded.PROVIDER + "/") for path in paths):
        return None
    require({MANIFEST, LOCK} <= set(paths), "partial-bounded-tls-source")
    try:
        checked = bounded.verify(repo)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SecurityError("unreviewed-bounded-tls-source") from error
    return {"name": checked["upstream"]["crate"], "version": checked["upstream"]["version"],
            "checksum": checked["upstream"]["archiveSha256"],
            "privatePackage": bounded.NAME, "recordSha256": checked["recordSha256"],
            "manifestSha256": checked["files"]["Cargo.toml"]["sha256"],
            "sourceEvidenceLockSha256": checked["files"]["Cargo.lock"]["sha256"]}


def advisory_lock(checked: dict) -> bytes:
    # Coordinate input for cargo-audit, not an invented build/dependency lock.
    # The real root and every other tracked Cargo.lock are still scanned intact.
    return ("version = 4\n\n[[package]]\n"
            + "\n".join(key + " = " + json.dumps(value) for key, value in (
                ("name", checked["name"]), ("version", checked["version"]),
                ("source", REGISTRY), ("checksum", checked["checksum"]))) + "\n").encode()


def inventory_record(repo: Path, entry: dict, paths: list[str]) -> tuple[dict, dict]:
    require(entry == {"path": MANIFEST, "kind": "bounded-rustls", "lock": LOCK,
                      "absent_when_directory_missing": bounded.PROVIDER},
            "unreviewed-bounded-tls-inventory")
    checked = origin(repo, paths)
    require(checked is not None, "missing-bounded-tls-source")
    return checked, {"path": MANIFEST, "coverage": "OSV-and-RustSec-authenticated-origin",
                     "buildLock": "Cargo.lock", "packages": 1, **checked,
                     "sourceEvidenceLock": LOCK,
                     "boundary": "The vendored upstream lock is immutable source evidence, not the provider build lock; RustSec still scans it independently."}
