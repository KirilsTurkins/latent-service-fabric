"""Exact companion files used by a maintained language-owned build adapter."""
from pathlib import Path
import os
import re
import stat

from . import paths
from .common import HOST_ABI, decode, digest, encode, members, require, sha

MAX_DOCUMENT = 2 * 1024 * 1024
MAX_FILES = 4096
MAX_BYTES = 2 * 1024**3


def validate(value: dict, language: str, owner: int, host: str) -> dict:
    members(value, {"schemaVersion", "language", "ownerIssue", "sourceCommit", "hostAbi", "host", "files", "identity"})
    require(value["schemaVersion"] == "latent.dev.guest-tools.v1" and value["language"] == language
            and value["ownerIssue"] == owner and value["host"] == host and value["hostAbi"] == HOST_ABI,
            "guest-tool-inventory-owner-or-target")
    require(isinstance(value["sourceCommit"], str) and re.fullmatch(r"[a-f0-9]{40}", value["sourceCommit"]),
            "guest-tool-inventory-source")
    require(isinstance(value["files"], list) and 0 < len(value["files"]) <= MAX_FILES, "guest-tool-inventory-limit")
    names, total = set(), 0
    for entry in value["files"]:
        members(entry, {"path", "sha256", "size"})
        name = paths.relative(entry["path"])
        require(paths.alias(name) not in names, "guest-tool-inventory-alias")
        names.add(paths.alias(name))
        sha(entry["sha256"])
        require(type(entry["size"]) is int and 0 <= entry["size"] <= 1024**3, "guest-tool-file-limit")
        total += entry["size"]
    require(total <= MAX_BYTES, "guest-tool-byte-limit")
    require(value["identity"] == digest(encode({key: item for key, item in value.items() if key != "identity"})),
            "guest-tool-inventory-identity")
    return value


def check(root: Path, descriptor: dict, host: str, *, observe=None) -> str | None:
    selected = descriptor["build"].get("inventory")
    if selected is None:
        return None
    raw = paths.read(root, selected["path"], MAX_DOCUMENT)
    require(digest(raw) == selected["sha256"], "guest-tool-inventory-digest")
    value = validate(decode(raw, MAX_DOCUMENT), descriptor["language"], descriptor["template"]["ownerIssue"], host)
    require(value["sourceCommit"] == descriptor["template"]["revision"], "guest-tool-template-revision-mismatch")
    files = {entry["path"]: entry for entry in value["files"]}
    directories = {"/".join(name.split("/")[:index]) for name in files for index in range(1, len(name.split("/")))}
    pending = {name.split("/")[0] for name in files}
    visited = 0
    while pending:
        if observe is not None:
            observe()
        name = pending.pop()
        visited += 1
        require(visited <= MAX_FILES * 8, "guest-tool-directory-limit")
        path = root / name
        metadata = path.lstat()
        require(not stat.S_ISLNK(metadata.st_mode) and not getattr(metadata, "st_file_attributes", 0) & 0x400,
                "guest-tool-link-rejected")
        if stat.S_ISDIR(metadata.st_mode):
            require(name in directories, "guest-tool-unrecorded-directory")
            with paths.directory(path) as anchor, os.scandir(anchor if os.name == "posix" else path) as entries:
                for entry in entries:
                    require(len(pending) + visited < MAX_FILES * 8, "guest-tool-directory-limit")
                    pending.add(name + "/" + entry.name)
        else:
            require(name in files, "guest-tool-unrecorded-file")
    for tool in descriptor["build"]["tools"]:
        require(tool["path"] in files and files[tool["path"]]["sha256"] == tool["sha256"], "recipe-tool-outside-inventory")
    for name, entry in files.items():
        require(paths.digest_file(root, name, 1024**3, check=observe) == (entry["sha256"], entry["size"]),
                "guest-tool-companion-modified")
    return value["identity"]
