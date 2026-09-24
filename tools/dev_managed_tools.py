"""Expand a captured managed compiler into one private, bounded build attempt."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import zipfile

from tools.dev_workflow import paths
from tools.dev_workflow.common import decode, digest, encode, members, require, sha

MAX_FILES = 32768
MAX_BYTES = 3 * 1024**3
MAX_FILE = 512 * 1024**2
MAX_DOCUMENT = 16 * 1024**2


def manifest(value: dict) -> dict:
    members(value, {"schemaVersion", "files", "identity"})
    require(value["schemaVersion"] == "latent.dev.managed-tools.v1", "managed-tool-schema")
    require(isinstance(value["files"], list) and 0 < len(value["files"]) <= MAX_FILES, "managed-tool-file-limit")
    names, total = set(), 0
    for entry in value["files"]:
        members(entry, {"path", "size", "sha256", "executable"})
        name = paths.relative(entry["path"])
        require(paths.alias(name) not in names, "managed-tool-alias")
        names.add(paths.alias(name))
        sha(entry["sha256"])
        require(type(entry["size"]) is int and 0 <= entry["size"] <= MAX_FILE
                and type(entry["executable"]) is bool, "managed-tool-size-or-mode")
        total += entry["size"]
    require(total <= MAX_BYTES, "managed-tool-expanded-limit")
    require(not any(paths.alias("/".join(entry["path"].split("/")[:n])) in names
        for entry in value["files"] for n in range(1, len(entry["path"].split("/")))), "managed-tool-parent-collision")
    require(value["identity"] == digest(encode({k: v for k, v in value.items() if k != "identity"})), "managed-tool-identity")
    return value


def unpack(sdk: Path, destination: Path, check) -> Path:
    require(not destination.exists(), "managed-tool-staging-must-be-fresh")
    value = manifest(decode(paths.read(sdk, "managed-inputs.json", MAX_DOCUMENT), MAX_DOCUMENT,
                            maximum_items=MAX_FILES * 5 + 8))
    destination.mkdir(mode=0o700)
    with paths.opened(sdk, "managed.zip") as descriptor, os.fdopen(os.dup(descriptor), "rb") as source:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            require(len(entries) == len(value["files"]), "managed-tool-archive-count")
            for actual, expected in zip(entries, value["files"], strict=True):
                check()
                mode = actual.external_attr >> 16
                require(actual.filename == expected["path"] and actual.file_size == expected["size"]
                    and stat.S_ISREG(mode) and not actual.flag_bits & 1, "managed-tool-archive-entry")
                target = destination / expected["path"]
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                checksum, copied = hashlib.sha256(), 0
                with archive.open(actual) as incoming, target.open("xb") as output:
                    while raw := incoming.read(1024 * 1024):
                        check()
                        copied += len(raw)
                        require(copied <= expected["size"], "managed-tool-expanded-limit")
                        checksum.update(raw)
                        output.write(raw)
                require(copied == expected["size"] and "sha256:" + checksum.hexdigest() == expected["sha256"],
                        "managed-tool-file-digest")
                target.chmod(0o700 if expected["executable"] else 0o600)
    return destination


def diagnostics(output: Path, language: str) -> None:
    """Forward only bounded source locations mapped by the maintained recipe."""
    import sys
    if not (output / "diagnostic-source.json").exists():
        return
    mapping = decode(paths.read(output, "diagnostic-source.json", 16384))
    prefix = (mapping["capturedSource"] + "/").encode()
    replacement = (mapping["requestedSource"] + "/").encode()
    logs = sorted((output / "compiler-logs").glob("*-java-to-c.log")) if language == "java" else sorted(
        (output / "logs").glob("*-native-aot.*.txt"))
    retained = 0
    for path in logs:
        for line in paths.read(path.parent, path.name, 4 * 1024 * 1024).splitlines():
            if len(line) > 16384 or prefix not in line:
                continue
            raw = line.replace(prefix, replacement).strip() + b"\n"
            retained += len(raw)
            if retained > 128 * 1024:
                return
            sys.stderr.buffer.write(raw)
