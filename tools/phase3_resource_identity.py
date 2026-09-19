"""Hash bounded explicit inputs; reject symlinks and changes during observation."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import time

from tools.phase2_operator_process import require
from tools.phase3_resource_profile import LIMITS, digest


def file_identity(path, maximum=LIMITS["maximumFileBytes"]):
    require(path.is_file() and not path.is_symlink(), "resource-identity-file")
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as source:
        before = os.fstat(source.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, "resource-identity-bound")
        while chunk := source.read(min(65536, maximum - size + 1)):
            size += len(chunk)
            require(size <= maximum, "resource-identity-bound")
            hasher.update(chunk)
        after = os.fstat(source.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and size == before.st_size,
            "resource-identity-changed")
    return {"sha256": "sha256:" + hasher.hexdigest(), "bytes": size}


def inventory(root, maximum_files=LIMITS["maximumFixtureFiles"],
              maximum_bytes=LIMITS["maximumFixtureBytes"], deadline=None):
    require(root.is_dir() and not root.is_symlink(), "resource-input-directory")
    pending, rows, total, visited = [root], [], 0, 0
    while pending:
        require(deadline is None or time.monotonic() < deadline, "resource-inventory-deadline")
        parent = pending.pop()
        with os.scandir(parent) as entries:
            for entry in entries:
                visited += 1
                require(visited <= maximum_files and not entry.is_symlink(), "resource-inventory-bound")
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                else:
                    require(entry.is_file(follow_symlinks=False), "resource-inventory-file")
                    row = file_identity(path, maximum_bytes - total)
                    total += row["bytes"]
                    rows.append({"path": path.relative_to(root).as_posix(), **row})
    require(bool(rows), "resource-input-empty")
    rows.sort(key=lambda row: row["path"])
    return {"files": rows, "filesDigest": digest(rows), "bytes": total}


def source_identity(root):
    rows = []
    for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml"):
        rows.append({"path": name, **file_identity(root / name, 1048576)})
    for name in ("apps", "crates", "sdk/rust", "tools/optimization-workloads"):
        scanned = inventory(root / name, maximum_files=8192, maximum_bytes=128 * 1024 * 1024,
                            deadline=time.monotonic() + 60)
        rows += [{**row, "path": name + "/" + row["path"]} for row in scanned["files"]]
    require(len(rows) <= 16384, "resource-source-file-bound")
    rows.sort(key=lambda row: row["path"])
    return {"sha256": digest(rows), "files": len(rows), "bytes": sum(row["bytes"] for row in rows),
            "scope": "explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs",
            "hermetic": False, "implicitCompilerInputs": "not-attested"}
