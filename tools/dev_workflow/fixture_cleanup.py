"""Bounded preflight for private fixture material in an explicitly purged owner."""
from __future__ import annotations

import os
from pathlib import Path
import re

from . import paths
from .common import decode, digest, require

DIRECTORIES = {
    "http-fixture-private": ("disposable-http-fixture", {"authorization", "owner.json"}, 3),
    "event-fixture-private": ("disposable-event-peer", {"authorization", "ca.der", "server.pem", "key.pem", "owner.json"}, 6),
    "secret-fixture-private": ("disposable-guest-secrets", {"owner.json"}, 10),
}


def plan(root: Path) -> dict:
    paths.private_root(root)
    result = {}
    for name, (purpose, fixed, maximum) in DIRECTORIES.items():
        directory = root / name
        # Include broken links in preflight. They must never masquerade as absent.
        if not os.path.lexists(directory):
            continue
        require(root.name.startswith("test-"), "test-fixture-purge-owner-required")
        paths.private_root(directory)
        identity = directory.stat()
        observed, pending = {}, 0
        with os.scandir(directory) as entries:
            for entry in entries:
                require(len(observed) < maximum, "test-fixture-purge-entry-limit")
                temporary = re.fullmatch(r"pending-[0-9a-f]{32}", entry.name) is not None
                pending += temporary
                allowed_secret = name == "secret-fixture-private" and re.fullmatch(r"dev-[a-z0-9-]{1,60}", entry.name)
                require((entry.name in fixed or allowed_secret or temporary) and pending <= 1,
                        "unrecognized-test-fixture-purge-entry")
                with paths.opened(directory, entry.name) as descriptor:
                    metadata = os.fstat(descriptor)
                    if os.name != "nt":
                        require(metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o077,
                                "private-test-fixture-purge-file-required")
                raw = paths.read(directory, entry.name, 16384)
                if entry.name == "owner.json":
                    owner = decode(raw, 16384)
                    require(isinstance(owner, dict) and owner.get("purpose") == purpose,
                            "test-fixture-purge-purpose-mismatch")
                observed[entry.name] = digest(raw)
        # Partial preparation can lack owner.json. Its fixed private directory,
        # names, file types, owner and bounds still need this same preflight.
        result[name] = {"device": identity.st_dev, "inode": identity.st_ino, "files": observed}
    return result


def purge(root: Path, selected: dict) -> list[str]:
    from tools.native_runtime.files import remove_tree
    require(plan(root) == selected, "test-fixture-purge-input-changed")
    removed = []
    for name in selected:
        remove_tree(root / name, maximum=DIRECTORIES[name][2])
        removed.append(name)
    return removed
