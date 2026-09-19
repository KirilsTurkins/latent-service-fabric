"""Bounded retained-file observations, distinct from RSS and allocator ownership."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import time

from tools.phase2_operator_process import WorkflowError, require
from tools.phase3_resource_profile import digest


def storage_snapshot(root, deadline, maximum_files=8192, maximum_bytes=2 * 1024**3):
    require(root.is_dir() and not root.is_symlink(), "resource-storage-root")
    pending, records, identities, groups, directory_counts = [root], [], set(), {}, {}
    visited = total = allocated = unique_bytes = 0
    began = time.monotonic_ns()
    while pending:
        require(time.monotonic() < deadline, "resource-storage-deadline")
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                visited += 1
                require(visited <= maximum_files and not entry.is_symlink(), "resource-storage-entry-bound")
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    relative = path.relative_to(root)
                    if len(relative.parts) <= 4:
                        parent = relative.parent.as_posix()
                        directory_counts[parent] = directory_counts.get(parent, 0) + 1
                    pending.append(path)
                    continue
                info = entry.stat(follow_symlinks=False)
                require(stat.S_ISREG(info.st_mode), "resource-storage-file-type")
                total += info.st_size
                require(total <= maximum_bytes, "resource-storage-byte-bound")
                relative = path.relative_to(root)
                group = groups.setdefault(relative.parts[0], {"files": 0, "logicalBytes": 0})
                group["files"] += 1
                group["logicalBytes"] += info.st_size
                identity = (info.st_dev, info.st_ino)
                if identity not in identities:
                    identities.add(identity)
                    unique_bytes += info.st_size
                    allocated += getattr(info, "st_blocks", 0) * 512
                records.append({"path": relative.as_posix(), "bytes": info.st_size,
                                "device": info.st_dev, "inode": info.st_ino})
    return {"files": len(records), "uniqueInodes": len(identities), "logicalBytes": total,
            "uniqueInodeLogicalBytes": unique_bytes, "allocatedBytes": allocated if os.name == "posix" else None,
            "groups": groups, "directoryCounts": directory_counts,
            "metadataDigest": digest(sorted(records, key=lambda row: row["path"])),
            "beganMonotonicNanos": str(began), "finishedMonotonicNanos": str(time.monotonic_ns()),
            "consistency": "non-atomic-stat-scan-no-content-or-secret-read",
            "scope": "owned-node-directory-including-durable-audit-not-host-filesystem-dedup"}


def failure_storage(root):
    try:
        return {"available": True, "snapshot": storage_snapshot(root, time.monotonic() + 2)}
    except Exception as error:
        return {"available": False, "reason": str(error) if isinstance(error, WorkflowError) else type(error).__name__}
