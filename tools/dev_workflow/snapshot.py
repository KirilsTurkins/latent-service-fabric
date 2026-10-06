"""Bounded two-pass observations published as immutable private snapshots."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from . import paths
from .common import MAX_FILES, MAX_SNAPSHOT, decode, digest, encode, members, require, sha


def inventory(root: Path, inputs: list[str], exclusions: tuple[str, ...], *, captured: bool = False) -> list[str]:
    require(0 < len(inputs) <= 64 and len(exclusions) <= 64, "input-root-limit")
    names = set()
    aliases = {}
    visited = 0
    pending = sorted(inputs, reverse=True)
    with paths.directory(root):
        while pending:
            name = paths.relative(pending.pop())
            if captured and (name == 'dependency-inputs/objects' or name.startswith('dependency-inputs/objects/')):
                continue
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
    from tools import application_dependencies as capture
    from tools.application_dependency_store import Store
    from . import captured_inputs, dependencies
    selected = (root / capture.MANIFEST).exists() and dependencies.covered(dependencies.OBJECTS, inputs)
    domain, objects = captured_inputs.observe(root) if selected else (None, [])
    names = inventory(root, inputs, exclusions, captured=selected)
    records, content = [], {}
    total = 0
    for name in names:
        raw = paths.read(root, name)
        total += len(raw)
        require(total <= MAX_SNAPSHOT, "source-total-byte-limit")
        records.append({"path": name, "size": len(raw), "sha256": digest(raw)})
        content[name] = raw
    # Detect changes/deletions/additions across the entire transfer, not just per file.
    require(inventory(root, inputs, exclusions, captured=selected) == names, "source-changed-during-snapshot")
    for record in records:
        require(digest(paths.read(root, record["path"])) == record["sha256"], "source-changed-during-snapshot")
    separate = domain is not None and (len(records) + len(objects) > MAX_FILES
        or total + domain['objectBytes'] > MAX_SNAPSHOT or any(row['size'] > paths.MAX_FILE for row in objects))
    if domain is not None:
        if not separate:
            store = Store(root / dependencies.OBJECTS, create=False)
            for row in objects:
                name = captured_inputs.object_path(row['digest'])
                content[name] = store.get(row['digest'], row['size'])
                records.append({'path': name, 'size': row['size'], 'sha256': row['digest']})
                total += row['size']
        require(captured_inputs.observe(root)[0] == domain, 'captured-inputs-changed-during-snapshot')
    records.sort(key=lambda item: item['path'])
    result = {"schemaVersion": "latent.dev.snapshot.v2" if separate else "latent.dev.snapshot.v1",
              "files": records, "bytes": total}
    if separate:
        result['capturedInputs'] = domain
    result["identity"] = digest(encode(result))
    return result, content


def validate(record: dict) -> None:
    members(record, {"schemaVersion", "files", "bytes", "identity"}, {'capturedInputs'})
    separate = record['schemaVersion'] == 'latent.dev.snapshot.v2'
    require(record["schemaVersion"] in {"latent.dev.snapshot.v1", "latent.dev.snapshot.v2"}
            and ('capturedInputs' in record) == separate, "snapshot-version")
    if separate:
        from . import captured_inputs
        captured_inputs.validate(record['capturedInputs'])
    sha(record["identity"])
    require(isinstance(record["files"], list) and 0 < len(record["files"]) <= MAX_FILES, "snapshot-file-count")
    aliases, total = set(), 0
    for entry in record["files"]:
        members(entry, {"path", "size", "sha256"})
        name = paths.relative(entry["path"])
        require(not separate or not name.startswith('dependency-inputs/objects/'), 'captured-input-duplicate-domain')
        require(not paths.excluded(name) and paths.alias(name) not in aliases
                and name not in {"snapshot.json", "snapshot-intent.json", "build-receipt.json"}, "unsafe-snapshot-input")
        aliases.add(paths.alias(name))
        sha(entry["sha256"])
        require(type(entry["size"]) is int and 0 <= entry["size"] <= paths.MAX_FILE, "snapshot-file-size")
        total += entry["size"]
    require(type(record["bytes"]) is int and record["bytes"] == total <= MAX_SNAPSHOT, "snapshot-size")
    if separate:
        by_name = {item['path']: item['sha256'] for item in record['files']}
        require(by_name.get('latent.dependencies.json') == record['capturedInputs']['manifestDigest']
                and by_name.get('latent.dependencies.lock.json') == record['capturedInputs']['lockDigest'],
                'captured-input-snapshot-document-binding')
    require(digest(encode({key: value for key, value in record.items() if key != "identity"}))
            == record["identity"], "snapshot-identity")


def materialize(destination: Path, record: dict, content: dict[str, bytes], *, commit: bool = True) -> None:
    validate(record)
    require(set(content) == {item["path"] for item in record["files"]}, "snapshot-inventory-mismatch")
    for entry in record["files"]:
        raw = content[entry["path"]]
        require(len(raw) == entry["size"] and digest(raw) == entry["sha256"], "snapshot-bytes-mismatch")
    paths.new_directory(destination)
    if not commit:
        paths.write_new(destination / 'snapshot-intent.json', encode(record))
    # The destination is a new private tree; interrupted trees are never build inputs.
    for entry in record["files"]:
        path = destination / entry["path"]
        current = destination
        for part in Path(entry["path"]).parts[:-1]:
            current /= part
            if not current.exists():
                paths.new_directory(current)
        paths.write_new(path, content[entry["path"]])
    if commit:
        paths.write_new(destination / "snapshot.json", encode(record))


def commit(destination: Path, record: dict) -> None:
    validate(record)
    require(decode(paths.read(destination, 'snapshot-intent.json')) == record, 'snapshot-owner-intent-drift')
    paths.write_new(destination / 'snapshot.json', encode(record))
    (destination / 'snapshot-intent.json').unlink()
