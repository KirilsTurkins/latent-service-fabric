"""Bounded resumable transfer of explicit offline installer inputs; never execute them."""
from __future__ import annotations

import base64
import os
from pathlib import Path

from . import paths, state
from .common import decode, digest, encode, members, require, sha

CHUNK = 1024 * 1024
MAX_ASSET = 536870912
MAX_TOTAL = 805306368
MAX_FILES = 16


def manifest(value: dict) -> dict:
    members(value, {"schemaVersion", "files", "identity"})
    require(value["schemaVersion"] == "latent.dev.inputs.v1", "offline-input-schema")
    require(isinstance(value["files"], list) and 0 < len(value["files"]) <= MAX_FILES, "offline-input-file-limit")
    names, total = set(), 0
    for entry in value["files"]:
        members(entry, {"path", "sha256", "size", "executable"})
        name = paths.relative(entry["path"])
        require(len(name.split("/")) == 2 and name.split("/")[0] in {"release", "trust"}, "offline-input-path")
        require(paths.alias(name) not in names, "offline-input-alias")
        names.add(paths.alias(name))
        require(type(entry["size"]) is int and 0 < entry["size"] <= MAX_ASSET and type(entry["executable"]) is bool,
                "offline-input-size-limit")
        sha(entry["sha256"])
        total += entry["size"]
    require(total <= MAX_TOTAL, "offline-input-total-limit")
    require(digest(encode({key: item for key, item in value.items() if key != "identity"})) == sha(value["identity"]),
            "offline-input-identity")
    return value


def directory(root: Path, identity: str) -> Path:
    return root / "assets" / sha(identity)[7:]


def receive(root: Path, operation: str, arguments: dict) -> dict:
    if operation == "asset-begin":
        value = manifest(arguments)
        cache = root / "assets"
        if not cache.exists():
            paths.new_directory(cache)
        destination = directory(root, value["identity"])
        if not destination.exists():
            require(sum(1 for _ in cache.iterdir()) < 2, "offline-input-cache-full-purge-workspace-explicitly")
            paths.new_directory(destination)
            state.atomic(destination, "transfer.json", value)
        else:
            require(state.load(destination, "transfer.json") == value, "partial-or-different-offline-input")
        return {"identity": value["identity"], "complete": (destination / "complete.json").exists()}
    members(arguments, {"identity"}, {"path", "offset", "bytes"})
    destination = directory(root, arguments["identity"])
    value = manifest(state.load(destination, "transfer.json"))
    if operation == "asset-finish":
        members(arguments, {"identity"})
        for entry in value["files"]:
            require(paths.digest_file(destination, entry["path"], MAX_ASSET) == (entry["sha256"], entry["size"]),
                    "offline-input-content-mismatch")
            if os.name != "nt":
                with paths.opened(destination, entry["path"]) as descriptor:
                    os.fchmod(descriptor, 0o700 if entry["executable"] else 0o600)
        state.atomic(destination, "complete.json", value)
        return {"identity": value["identity"], "directory": str(destination), "complete": True}
    require(operation == "asset-chunk", "offline-input-operation")
    members(arguments, {"identity", "path", "offset", "bytes"})
    entry = next((entry for entry in value["files"] if entry["path"] == arguments["path"]), None)
    require(entry is not None and type(arguments["offset"]) is int and arguments["offset"] >= 0, "offline-input-chunk-path")
    require(isinstance(arguments["bytes"], str) and len(arguments["bytes"]) <= (CHUNK + 2) // 3 * 4, "offline-input-chunk-limit")
    raw = base64.b64decode(arguments["bytes"], validate=True)
    offset = arguments["offset"]
    require(0 < len(raw) <= CHUNK and offset + len(raw) <= entry["size"], "offline-input-chunk-limit")
    parent = destination / entry["path"].split("/")[0]
    if not parent.exists():
        paths.new_directory(parent)
    path = destination / entry["path"]
    if not path.exists():
        require(offset == 0 and not (destination / "complete.json").exists(), "offline-input-gap-or-committed")
        paths.write_new(path, b"")
    # The workspace controller lock serializes chunks. Repeating exactly the same
    # transferred bytes is idempotent; a build/publication/invocation never is.
    with paths.opened(parent, path.name) as descriptor:
        size = os.fstat(descriptor).st_size
        require(size <= entry["size"] and offset <= size, "offline-input-chunk-gap")
        if offset < size or (destination / "complete.json").exists():
            os.lseek(descriptor, offset, os.SEEK_SET)
            require(offset + len(raw) <= size and os.read(descriptor, len(raw)) == raw, "offline-input-conflicting-replay")
            return {"identity": value["identity"], "path": entry["path"], "offset": offset + len(raw)}
    with paths.directory(parent) as anchored:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=anchored)
        with os.fdopen(descriptor, "ab") as stream:
            paths.regular(os.fstat(stream.fileno()))
            require(os.fstat(stream.fileno()).st_size == offset, "offline-input-changed-before-append")
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {"identity": value["identity"], "path": entry["path"], "offset": offset + len(raw)}


def install_inputs(connection, value: dict) -> dict:
    from tools.native_runtime.verify import TARGET, version
    members(value, {"schemaVersion", "releaseDirectory", "version", "publisherPolicy", "trustedRoot", "verifier",
                   "verifierSha256", "profile", "allowCandidate", "consent", "port"}, {"trustPolicy", "resume"})
    require(value["schemaVersion"] == "latent.dev.install-inputs.v1" and value["consent"] is True,
            "explicit-offline-install-inputs-required")
    selected_version = version(value["version"])
    release = paths.absolute(Path(value["releaseDirectory"]))
    sources = {"release/" + name: release / name for name in (
        "release.json", "lsf-install.pyz", "SHA256SUMS", "SHA256SUMS.sigstore.json", f"lsf-{selected_version}-{TARGET}.tar.gz")}
    for key, name in (("publisherPolicy", "publisher-policy.json"), ("trustedRoot", "trusted_root.jsonl"), ("verifier", "gh")):
        sources["trust/" + name] = paths.absolute(Path(value[key]))
    if value.get("trustPolicy"):
        sources["trust/capsule-policy.json"] = paths.absolute(Path(value["trustPolicy"]))
    require(paths.digest_file(sources["trust/gh"].parent, sources["trust/gh"].name, MAX_ASSET)[0] == sha(value["verifierSha256"]),
            "independent-linux-verifier-digest-mismatch")
    entries = []
    for name, path in sorted(sources.items()):
        checksum, size = paths.digest_file(path.parent, path.name, MAX_ASSET)
        entries.append({"path": name, "sha256": checksum, "size": size, "executable": name == "trust/gh"})
    record = {"schemaVersion": "latent.dev.inputs.v1", "files": entries}
    record["identity"] = digest(encode(record))
    manifest(record)
    observation = connection.call("asset-begin", record)
    require(observation["identity"] == record["identity"], "offline-input-response-identity")
    if not observation["complete"]:
        for entry in entries:
            path = sources[entry["path"]]
            offset = 0
            with paths.opened(path.parent, path.name) as descriptor:
                while raw := os.read(descriptor, CHUNK):
                    response = connection.call("asset-chunk", {"identity": record["identity"], "path": entry["path"],
                        "offset": offset, "bytes": base64.b64encode(raw).decode()})
                    offset += len(raw)
                    require(response == {"identity": record["identity"], "path": entry["path"], "offset": offset},
                            "offline-input-response-identity")
                require(offset == entry["size"], "offline-input-changed-during-transfer")
    completed = connection.call("asset-finish", {"identity": record["identity"]}, timeout=90)
    require(completed["identity"] == record["identity"] and completed["complete"] is True, "offline-input-transfer-unconfirmed")
    guest = completed["directory"]
    require(isinstance(guest, str) and guest.startswith("/") and ".." not in guest.split("/"), "offline-input-backend-path")
    result = {key: value[key] for key in ("version", "profile", "allowCandidate", "consent", "port")}
    result.update(releaseDirectory=guest + "/release", publisherPolicy=guest + "/trust/publisher-policy.json",
                  trustedRoot=guest + "/trust/trusted_root.jsonl", verifier=guest + "/trust/gh")
    if "trustPolicy" in value:
        result["trustPolicy"] = guest + "/trust/capsule-policy.json"
    if "resume" in value:
        require(type(value["resume"]) is bool, "explicit-installer-resume-required")
        result["resume"] = value["resume"]
    return result
