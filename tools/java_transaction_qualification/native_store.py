"""Bounded topology observation of the retired native content-addressed store."""
from __future__ import annotations

import hashlib
import os
import re
import stat

from .inputs import require


def identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_nlink, value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode))


def observe(root, node_directory):
    """Require complete internal link groups; never copy or grant native data."""
    relative_node = node_directory.relative_to(root).as_posix()
    require(re.fullmatch(r"[a-z][a-z0-9-]{0,63}", relative_node), "closed-original-node-directory")
    owner = root.stat()
    current = root
    for part in (relative_node, "data", "releases"):
        current /= part
        try:
            value = current.lstat()
        except FileNotFoundError:
            return None
        require(stat.S_ISDIR(value.st_mode) and value.st_uid == owner.st_uid
                and value.st_gid == owner.st_gid, "original-native-store-directory-owner")
    base = current
    base_identity = identity(base.stat())
    pending, files, groups = [base], {}, {}
    directories, logical = 0, 0
    while pending:
        directory = pending.pop()
        directories += 1
        require(directories <= 4096, "candidate-directory-observation-bound")
        for path in sorted(directory.iterdir()):
            require(len(files) + directories < 4096, "candidate-entry-observation-bound")
            relative = path.relative_to(root).as_posix()
            require(len(relative.encode()) <= 512 and len(path.relative_to(root).parts) <= 16
                    and not any(ord(char) < 32 or ord(char) == 127 for char in relative),
                    "candidate-observed-path-bound")
            before = path.lstat()
            require(before.st_uid == owner.st_uid and before.st_gid == owner.st_gid,
                    "original-native-store-file-owner")
            if stat.S_ISDIR(before.st_mode):
                pending.append(path)
                continue
            require(stat.S_ISREG(before.st_mode) and before.st_nlink >= 1,
                    "candidate-single-link-regular-file-required")
            require(before.st_size <= 268435456 and logical + before.st_size <= 1073741824,
                    "candidate-file-observation-bound")
            logical += before.st_size
            files[relative] = {"identity": list(identity(before)), "bytes": before.st_size,
                               "mode": stat.S_IMODE(before.st_mode)}
            groups.setdefault((before.st_dev, before.st_ino), []).append(relative)
    distinct = 0
    prefix = base.relative_to(root).as_posix() + "/"
    for paths in groups.values():
        paths.sort()
        first = files[paths[0]]
        require(len(paths) == first["identity"][4]
                and all(files[name]["identity"] == first["identity"] for name in paths),
                "original-native-store-links-must-be-fully-contained")
        distinct += first["bytes"]
        if len(paths) > 1:
            blobs = [name for name in paths if re.fullmatch(re.escape(prefix) + r"blobs/[0-9a-f]{64}", name)]
            require(len(blobs) == 1 and all(name == blobs[0] or re.fullmatch(
                re.escape(prefix) + r"publications/[0-9a-f]{64}/[^/]+", name) for name in paths),
                "original-native-store-closed-content-links")
            blob = root / blobs[0]
            fd = os.open(blob, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as source:
                require(identity(os.fstat(source.fileno())) == tuple(first["identity"]),
                        "candidate-file-changed-during-observation")
                value, consumed = hashlib.sha256(), 0
                while raw := source.read(1048576):
                    consumed += len(raw)
                    require(consumed <= first["bytes"], "candidate-file-changed-during-observation")
                    value.update(raw)
                require(consumed == first["bytes"] and value.hexdigest() == blob.name,
                        "original-native-store-addressed-content")
                require(identity(os.fstat(source.fileno())) == tuple(first["identity"]),
                        "candidate-file-changed-during-observation")
            require(identity(blob.lstat()) == tuple(first["identity"]), "candidate-file-changed-during-observation")
        for name in paths:
            files[name]["members"] = paths
    require(identity(base.stat()) == base_identity, "original-native-store-root-changed")
    return {"schemaVersion": "latent.native-store.retained-topology.v1",
            "root": base.relative_to(root).as_posix(),
            "rootIdentity": {"device": base_identity[0], "inode": base_identity[1]},
            "logicalPathBytes": logical, "distinctInodeBytes": distinct,
            "fileCount": len(files), "inodeCount": len(groups), "files": dict(sorted(files.items()))}
