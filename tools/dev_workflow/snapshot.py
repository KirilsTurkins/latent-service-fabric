"""Bounded two-pass observations published as immutable private snapshots."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from . import paths
from .common import MAX_FILES, MAX_SNAPSHOT, decode, digest, encode, members, require, sha


def inventory(root: Path, inputs: list[str], exclusions: tuple[str, ...]) -> list[str]:
    require(0 < len(inputs) <= 64 and len(exclusions) <= 64, "input-root-limit")
    names = set()
    aliases = {}
    visited = 0
    pending = sorted(inputs, reverse=True)
    with paths.directory(root):
        while pending:
            name = paths.relative(pending.pop())
            if paths.excluded(name, exclusions):
                continue
            visited += 1
            require(visited <= MAX_FILES * 4, "source-entry-limit")
            normalized = paths.alias(name)
            require(normalized not in aliases or aliases[normalized] == name, "source-case-or-unicode-collision")
            aliases[normalized] = name
            with paths.directory((root / name).parent):
                metadata = (root / name).lstat()
                require(not stat.S_ISLNK(metadata.st_mode)
                        and not getattr(metadata, "st_file_attributes", 0) & 0x400, "source-link-rejected")
                if stat.S_ISDIR(metadata.st_mode):
                    with paths.directory(root / name), os.scandir(root / name) as entries:
                        for entry in entries:
                            pending.append(name + "/" + entry.name)
                            require(len(pending) <= MAX_FILES * 2, "source-entry-limit")
                else:
                    paths.regular(metadata)
                    names.add(name)
                    require(len(names) <= MAX_FILES, "source-file-count-limit")
    require(names, "empty-source-inputs")
    return sorted(names)


def observe(root: Path, inputs: list[str], exclusions: tuple[str, ...] = ()) -> tuple[dict, dict[str, bytes]]:
    names = inventory(root, inputs, exclusions)
    records, content = [], {}
    total = 0
    for name in names:
        raw = paths.read(root, name)
        total += len(raw)
        require(total <= MAX_SNAPSHOT, "source-total-byte-limit")
        records.append({"path": name, "size": len(raw), "sha256": digest(raw)})
        content[name] = raw
    # Detect changes/deletions/additions across the entire transfer, not just per file.
    require(inventory(root, inputs, exclusions) == names, "source-changed-during-snapshot")
    for record in records:
        require(digest(paths.read(root, record["path"])) == record["sha256"], "source-changed-during-snapshot")
    result = {"schemaVersion": "latent.dev.snapshot.v1", "files": records, "bytes": total}
    result["identity"] = digest(encode(result))
    return result, content


def validate(record: dict) -> None:
    members(record, {"schemaVersion", "files", "bytes", "identity"})
    require(record["schemaVersion"] == "latent.dev.snapshot.v1", "snapshot-version")
    sha(record["identity"])
    require(isinstance(record["files"], list) and 0 < len(record["files"]) <= MAX_FILES, "snapshot-file-count")
    aliases, total = set(), 0
    for entry in record["files"]:
        members(entry, {"path", "size", "sha256"})
        name = paths.relative(entry["path"])
        require(not paths.excluded(name) and paths.alias(name) not in aliases
                and name not in {"snapshot.json", "build-receipt.json"}, "unsafe-snapshot-input")
        aliases.add(paths.alias(name))
        sha(entry["sha256"])
        require(type(entry["size"]) is int and 0 <= entry["size"] <= paths.MAX_FILE, "snapshot-file-size")
        total += entry["size"]
    require(type(record["bytes"]) is int and record["bytes"] == total <= MAX_SNAPSHOT, "snapshot-size")
    require(digest(encode({key: value for key, value in record.items() if key != "identity"}))
            == record["identity"], "snapshot-identity")


def materialize(destination: Path, record: dict, content: dict[str, bytes]) -> None:
    validate(record)
    require(set(content) == {item["path"] for item in record["files"]}, "snapshot-inventory-mismatch")
    for entry in record["files"]:
        raw = content[entry["path"]]
        require(len(raw) == entry["size"] and digest(raw) == entry["sha256"], "snapshot-bytes-mismatch")
    paths.new_directory(destination)
    # The destination is a new private tree; interrupted trees are never build inputs.
    for entry in record["files"]:
        path = destination / entry["path"]
        current = destination
        for part in Path(entry["path"]).parts[:-1]:
            current /= part
            if not current.exists():
                paths.new_directory(current)
        paths.write_new(path, content[entry["path"]])
    paths.write_new(destination / "snapshot.json", encode(record))
