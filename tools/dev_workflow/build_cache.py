"""Owned build attempts, keyed by source, recipe, tools, ABI, host and packager."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat
import time

from . import paths, snapshot, state
from .common import HOST_ABI, digest, encode, members, require, sha

MAX_ATTEMPTS = 4
MAX_ENTRIES = 32768
# A private managed SDK plus compiler scratch must fit without sharing mutable
# tool installations. The four-attempt retention bound remains independent.
MAX_BYTES = 4 * 1024 * 1024 * 1024


def identity(record: dict, descriptor: dict, recipe: str, host: str, packager: str) -> str:
    return digest(encode({"observationProfile": "compiler-and-controller-v1", "source": record["identity"], "recipe": recipe, "tools": descriptor["build"]["tools"],
        "hostAbi": HOST_ABI, "host": host, "target": descriptor["build"]["target"], "packager": packager}))


def owner(directory: Path) -> dict:
    value = members(state.load(directory, "attempt.json"), {"id", "key", "source", "recipe", "state"})
    require(value["id"] == directory.name and len(directory.name) == 32
        and all(c in "0123456789abcdef" for c in directory.name), "unowned-build-attempt")
    for name in ("key", "source", "recipe"):
        sha(value[name])
    require(value["state"] in {"created", "running", "failed", "complete", "uncertain"}, "build-attempt-state")
    return value


def transition(directory: Path, selected: str) -> None:
    record = owner(directory)
    state.atomic(directory, "attempt.json", {**record, "state": selected})


def protected(root: Path) -> tuple[set[str], set[str]]:
    attempts, sources = set(), set()
    if (root / "last-build.json").exists():
        value = state.load(root, "last-build.json")
        attempts.add(value.get("receipt", {}).get("attempt"))
        if not value.get("receipt", {}).get("attempt"):
            sources.add(value.get("receipt", {}).get("source"))
    for name in ("last-deployment.json", "last-publication.json"):
        if (root / name).exists():
            value = state.load(root, name)
            attempts.add(value.get("attempt"))
            if not value.get("attempt"):
                sources.add(value.get("source"))
    if (root / "operations.json").exists():
        pending = state.load(root, "operations.json").get("pending")
        if pending:
            attempts.add(pending["intent"].get("attempt"))
            if not pending["intent"].get("attempt"):
                sources.add(pending["intent"].get("source"))
    return attempts, sources


def allocate(root: Path, source: Path, record: dict, descriptor: dict, recipe: str,
             host: str, packager: str) -> tuple[Path, Path, dict | None]:
    directory = root / "builds"
    if not directory.exists():
        paths.new_directory(directory)
    key = identity(record, descriptor, recipe, host, packager)
    entries = sorted(directory.iterdir(), key=lambda item: item.name)
    require(len(entries) <= MAX_ATTEMPTS, "build-cache-entry-limit")
    owned = [(entry, owner(entry)) for entry in entries]
    for entry, selected in owned:
        if selected["key"] == key and selected["state"] == "complete":
            receipt = state.load(entry / "source", "build-receipt.json")
            require(receipt["buildKey"] == key and receipt["attempt"] == entry.name
                    and receipt["source"] == record["identity"] and receipt["recipe"] == recipe,
                    "cached-build-receipt-mismatch")
            return entry, entry / "source", receipt
    protected_attempts, protected_sources = protected(root)
    for entry, selected in owned:
        if len(entries) < MAX_ATTEMPTS:
            break
        if (entry.name in protected_attempts or selected["source"] in protected_sources
                or selected["state"] in {"running", "uncertain"}):
            continue
        # The helper runs on Linux; removal uses anchored, owner-checked handles.
        require(os.name == "posix" and entry.parent == root / "builds", "build-cache-cleanup-requires-linux")
        from tools.native_runtime import files
        files.remove_tree(entry, maximum=MAX_ENTRIES + 8)
        entries.remove(entry)
    require(len(entries) < MAX_ATTEMPTS, "build-cache-full-retained-or-uncertain-attempts")
    attempt = directory / secrets.token_hex(16)
    paths.new_directory(attempt)
    state.atomic(attempt, "attempt.json", {"id": attempt.name, "key": key, "source": record["identity"],
        "recipe": recipe, "state": "created"})
    content = {item["path"]: paths.read(source, item["path"]) for item in record["files"]}
    snapshot.materialize(attempt / "source", record, content)
    return attempt, attempt / "source", None


def usage(directory: Path) -> tuple[int, int]:
    """Observe retained files, never follow compiler-created links or mounts."""
    pending, count, total = [(directory, 0)], 0, 0
    with paths.directory(directory):
        device = directory.stat().st_dev
        while pending:
            current, depth = pending.pop()
            require(depth <= 64, "build-cache-depth-limit")
            try:
                with paths.directory(current) as anchor, os.scandir(anchor if os.name == "posix" else current) as entries:
                    for entry in entries:
                        count += 1
                        require(count <= MAX_ENTRIES, "build-cache-file-limit")
                        try:
                            # Windows DirEntry.stat deliberately returns st_dev=0.
                            metadata = Path(entry.path).lstat() if os.name == "nt" else entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue  # A compiler may remove its own temporary file.
                        require(not stat.S_ISLNK(metadata.st_mode) and not getattr(metadata, "st_file_attributes", 0) & 0x400
                                and metadata.st_dev == device, "build-cache-link-or-mount-rejected")
                        if stat.S_ISDIR(metadata.st_mode):
                            pending.append((current / entry.name, depth + 1))
                        else:
                            require(stat.S_ISREG(metadata.st_mode), "build-cache-special-file-rejected")
                            total += metadata.st_size
                            require(total <= MAX_BYTES, "build-cache-byte-limit")
            except FileNotFoundError:
                # Temporary directories can disappear between enumeration and open.
                # The attempt itself must remain owned and present.
                if current == directory:
                    raise
    return count, total


def monitor(directory: Path):
    previous = 0.0
    def check():
        nonlocal previous
        now = time.monotonic()
        if now - previous >= 0.5:
            usage(directory)
            # A large retained tree can take longer than the polling interval.
            # Measure the gap from completion so consecutive hash callbacks do
            # not rescan the entire tree and consume the build's finite budget.
            previous = time.monotonic()
    return check
