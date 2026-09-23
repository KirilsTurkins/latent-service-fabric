"""Private durable state and cross-process exclusion; no PID-file adoption."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import time

from . import paths
from .common import MAX_DOCUMENT, MAX_WORKSPACES, decode, encode, identifier, require


def atomic(root: Path, name: str, value: dict) -> None:
    paths.relative(name)
    require("/" not in name, "state-file-must-be-direct-child")
    paths.private_root(root)
    raw = encode(value)
    require(len(raw) <= MAX_DOCUMENT, "state-byte-limit")
    temporary = root / ("pending-" + secrets.token_hex(16))
    paths.write_new(temporary, raw)
    try:
        with paths.directory(root):
            if (root / name).exists():
                paths.read(root, name, MAX_DOCUMENT)
            os.replace(temporary, root / name)
            if os.name != "nt":
                with paths.directory(root) as descriptor:
                    os.fsync(descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def lock(root: Path, name: str = "controller.lock"):
    paths.private_root(root)
    paths.relative(name)
    require("/" not in name, "lock-must-be-direct-child")
    path = root / name
    try:
        paths.write_new(path, b"0")
    except FileExistsError:
        pass
    paths.read(root, name, 1)
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def load(root: Path, name: str) -> dict:
    paths.private_root(root)
    return decode(paths.read(root, name, MAX_DOCUMENT))


def workspace(root: Path, name: str, *, create: bool = False) -> Path:
    identifier(name)
    paths.private_root(root)
    path = root / name
    if create and not path.exists():
        with lock(root, "registry.lock"):
            require(sum(1 for item in root.iterdir() if item.is_dir()) < MAX_WORKSPACES, "workspace-count-limit")
            paths.new_directory(path)
            atomic(path, "owner.json", {"schemaVersion": "latent.dev.owner.v1", "id": name,
                                        "nonce": secrets.token_hex(16)})
    paths.private_root(path)
    owner = load(path, "owner.json")
    require(owner.get("schemaVersion") == "latent.dev.owner.v1" and owner.get("id") == name, "workspace-owner-mismatch")
    return path
