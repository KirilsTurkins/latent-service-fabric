"""Explicit dependency capture and verified offline builds for all guest recipes.

The selected native graph is supplied by a language resolver. This module never
selects package versions, executes package hooks or grants guest authority.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.application_dependency_store import (
    DependencyError, Store, MAX_OBJECT, SHA, archive_files, captured_files,
    directory_files, materialize, path_name, read_bytes, regular_path, tree_identity,
)
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import decode_json

MANIFEST = "latent.dependencies.json"
LOCK = "latent.dependencies.lock.json"
LANGUAGES = {"java", "rust", "c", "typescript", "go", "dotnet"}
ROLES = {"application", "sdk", "compiler", "runtime", "build-tool", "resource", "generated"}
MAX_LOCK = 8 * 1024 * 1024
MAX_ARTIFACTS = 1024
MAX_CLOSURE_BYTES = 512 * 1024 * 1024
MAX_CLOSURE_FILES = 32768


def document(path: Path) -> dict:
    value = decode_json(read_bytes(path, MAX_LOCK))
    if not isinstance(value, dict):
        raise DependencyError("dependency-document-invalid")
    return value


def label(value) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_@+./:-]{1,256}", value)
            or "//" in value or ".." in value):
        raise DependencyError("dependency-identity-invalid")
    return value


def metadata(value):
    """Retain arbitrary ecosystem metadata, while rejecting obvious credentials.

    Source URLs and private endpoint configuration are separate resolver inputs.
    This is an input schema safeguard, not a claim that arbitrary source bytes
    cannot contain confidential information.
    """
    if len(canonical(value)) > 256 * 1024:
        raise DependencyError("dependency-metadata-limit")
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or re.search(r"password|secret|token|credential|authorization", key, re.I):
                    raise DependencyError("dependency-credentials-denied")
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            if len(item) > 32768 or "\0" in item:
                raise DependencyError("dependency-metadata-limit")
            if "://" in item:
                parsed = urlsplit(item)
                if parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise DependencyError("dependency-credentials-denied")
        elif item is not None and type(item) not in {bool, int, float}:
            raise DependencyError("dependency-metadata-invalid")
    return value


def validate_manifest(value: dict, language: str | None = None) -> dict:
    if (set(value) != {"formatVersion", "language", "selection", "nativeLocks", "artifacts", "transformations"}
            or type(value["formatVersion"]) is not int or value["formatVersion"] != 1
            or value["language"] not in LANGUAGES or language is not None and value["language"] != language
            or not isinstance(value["selection"], dict)):
        raise DependencyError("dependency-manifest-version-or-language")
    metadata(value["selection"])
    for key in ("nativeLocks", "artifacts", "transformations"):
        if not isinstance(value[key], list) or len(value[key]) > MAX_ARTIFACTS:
            raise DependencyError("dependency-manifest-count")
    if len(set(value["nativeLocks"])) != len(value["nativeLocks"]):
        raise DependencyError("dependency-native-lock-duplicate")
    for path in value["nativeLocks"]:
        path_name(path)
    ids, mounts = set(), set()
    for item in value["artifacts"]:
        if (not isinstance(item, dict) or set(item) != {"id", "role", "format", "mount", "source", "dependencies", "metadata"}
                or item["role"] not in ROLES or item["format"] not in {"file", "directory", "zip", "tar"}
                or not isinstance(item["dependencies"], list) or len(item["dependencies"]) > MAX_ARTIFACTS
                or not isinstance(item["source"], dict) or not isinstance(item["metadata"], dict)):
            raise DependencyError("dependency-artifact-declaration")
        identity, mount = label(item["id"]), path_name(item["mount"])
        if identity in ids or mount.casefold() in mounts:
            raise DependencyError("dependency-artifact-duplicate")
        # SDK originals and source files must never be overwritten by ingestion.
        if mount.split("/")[0] not in {"dependencies", "application-vendor"}:
            raise DependencyError("dependency-mount-reserved")
        ids.add(identity)
        mounts.add(mount.casefold())
        source = item["source"]
        if set(source) == {"path"}:
            if not isinstance(source["path"], str) or not 0 < len(source["path"]) <= 4096 or "\0" in source["path"]:
                raise DependencyError("dependency-local-source-invalid")
        elif set(source) == {"repository", "path", "digest"}:
            label(source["repository"])
            path_name(source["path"])
            if not SHA.fullmatch(source["digest"]):
                raise DependencyError("dependency-remote-digest-required")
            if item["format"] == "directory":
                raise DependencyError("dependency-remote-directory-invalid")
        else:
            raise DependencyError("dependency-source-invalid")
        metadata(item["metadata"])
    for mount in mounts:
        if any(other != mount and other.startswith(mount + "/") for other in mounts):
            raise DependencyError("dependency-mount-collision")
    for item in value["artifacts"]:
        if len(set(item["dependencies"])) != len(item["dependencies"]) or not set(item["dependencies"]) <= ids:
            raise DependencyError("dependency-graph-not-closed")
    for transform in value["transformations"]:
        if (not isinstance(transform, dict) or set(transform) != {"id", "artifact", "inputDigest", "outputDigest", "files", "tool", "selection"}
                or transform["artifact"] not in ids or not SHA.fullmatch(transform["inputDigest"])
                or not SHA.fullmatch(transform["outputDigest"]) or not isinstance(transform["files"], list)
                or not 0 < len(transform["files"]) <= 8192):
            raise DependencyError("dependency-transformation-invalid")
        label(transform["id"])
        metadata(transform["tool"])
        metadata(transform["selection"])
        for row in transform["files"]:
            if set(row) != {"path", "inputDigest", "source", "outputDigest"}:
                raise DependencyError("dependency-transformation-invalid")
            path_name(row["path"])
            if not SHA.fullmatch(row["inputDigest"]) or not SHA.fullmatch(row["outputDigest"]):
                raise DependencyError("dependency-transformation-invalid")
            if not isinstance(row["source"], str) or not 0 < len(row["source"]) <= 4096 or "\0" in row["source"]:
                raise DependencyError("dependency-transformation-invalid")
        if len({row["path"] for row in transform["files"]}) != len(transform["files"]):
            raise DependencyError("dependency-transformation-invalid")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise DependencyError("dependency-registry-redirect-denied")


def fetch(source: dict, repositories: dict) -> bytes:
    """Credentials stay in this separately authorized resolution stage only."""
    config = repositories.get(source["repository"])
    if not isinstance(config, dict) or not {"url"} <= config.keys() or set(config) - {"url", "authorizationEnv"}:
        raise DependencyError("dependency-repository-not-configured")
    parsed = urlsplit(config["url"])
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DependencyError("dependency-repository-invalid")
    headers = {}
    if "authorizationEnv" in config:
        variable = config["authorizationEnv"]
        if not isinstance(variable, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", variable):
            raise DependencyError("dependency-repository-auth-config")
        authorization = os.environ.get(variable)
        if not authorization or any(character in authorization for character in "\r\n\0"):
            raise DependencyError("dependency-repository-auth-unavailable")
        headers["Authorization"] = authorization
    request = Request(config["url"].rstrip("/") + "/" + source["path"], headers=headers)
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            if response.status != 200:
                raise DependencyError("dependency-fetch-failed")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_OBJECT):
                raise DependencyError("dependency-object-limit")
            data = response.read(MAX_OBJECT + 1)
    except DependencyError:
        raise
    except Exception:
        raise DependencyError("dependency-fetch-failed") from None
    if len(data) > MAX_OBJECT or digest(data) != source["digest"]:
        raise DependencyError("dependency-fetch-integrity")
    return data


def capture(project: Path, *, cache: Path | None = None, repositories: dict | None = None) -> dict:
    """Create a reviewable lock candidate; never overwrite a reviewed lock."""
    project = regular_path(project)
    manifest_bytes = read_bytes(project / MANIFEST, MAX_LOCK)
    manifest = validate_manifest(decode_json(manifest_bytes))
    store = Store(cache or project / "dependency-inputs/objects")
    native = [{"path": name, **store.put(read_bytes(project / name))} for name in manifest["nativeLocks"]]
    artifacts = []
    original_sources = []
    total_bytes = total_files = 0
    for item in manifest["artifacts"]:
        source = item["source"]
        files = None
        if "repository" in source:
            data = fetch(source, repositories or {})
            public_source = {"type": "repository", "repository": source["repository"], "path": source["path"]}
        else:
            path = regular_path(project / source["path"])
            public_source = {"type": "captured-local"}
            if item["format"] == "directory":
                files = directory_files(path)
                data = canonical(captured_files(files, store))
            else:
                data = read_bytes(path)
            original_sources.append((path, item["format"], digest(data)))
        original = store.put(data)
        if item["format"] in {"zip", "tar"}:
            files = archive_files(data, item["format"])
        if item["format"] == "file":
            files = {Path(item["mount"]).name: data}
        rows = captured_files(files, store)
        total_files += len(rows)
        total_bytes += sum(row["size"] for row in rows)
        if total_files > MAX_CLOSURE_FILES or total_bytes > MAX_CLOSURE_BYTES:
            raise DependencyError("dependency-closure-limit")
        artifacts.append({key: item[key] for key in ("id", "role", "format", "mount", "dependencies", "metadata")} |
                         {"source": public_source, "original": original, "files": rows, "treeDigest": tree_identity(rows)})
    transformed = []
    for transform in manifest["transformations"]:
        item = next(row for row in artifacts if row["id"] == transform["artifact"])
        if item["treeDigest"] != transform["inputDigest"]:
            raise DependencyError("dependency-patch-preimage-mismatch")
        by_name = {row["path"]: row for row in item["files"]}
        changes = []
        for row in transform["files"]:
            if row["path"] not in by_name or by_name[row["path"]]["digest"] != row["inputDigest"]:
                raise DependencyError("dependency-patch-preimage-mismatch")
            payload = read_bytes(regular_path(project / row["source"]))
            if digest(payload) != row["outputDigest"]:
                raise DependencyError("dependency-patch-output-mismatch")
            output = {"path": row["path"], **store.put(payload)}
            changes.append({"path": row["path"], "original": by_name[row["path"]], "transformed": output})
            by_name[row["path"]] = output
        updated = [by_name[name] for name in sorted(by_name)]
        if tree_identity(updated) != transform["outputDigest"]:
            raise DependencyError("dependency-patch-output-mismatch")
        item["files"], item["treeDigest"] = updated, transform["outputDigest"]
        transformed.append({key: transform[key] for key in ("id", "artifact", "inputDigest", "outputDigest", "tool", "selection")} |
                           {"changes": changes})
    for path, kind, expected in original_sources:
        data = canonical(captured_files(directory_files(path), store)) if kind == "directory" else read_bytes(path)
        if digest(data) != expected:
            raise DependencyError("dependency-input-mutated")
    if read_bytes(project / MANIFEST, MAX_LOCK) != manifest_bytes:
        raise DependencyError("dependency-input-mutated")
    for row in native:
        if digest(read_bytes(project / row["path"])) != row["digest"]:
            raise DependencyError("dependency-input-mutated")
    return {"formatVersion": 1, "language": manifest["language"], "manifestDigest": digest(manifest_bytes),
            "selection": manifest["selection"], "nativeLocks": native, "artifacts": artifacts,
            "transformations": transformed, "completeness": "selected-declared-closure",
            "executableInputs": [row["id"] for row in artifacts if row["role"] == "build-tool"]}


def verify_artifact(item: dict, spec: dict, transforms: list[dict], store: Store) -> None:
    """Reconstruct selection from original bytes and reviewed patch preimages."""
    original = store.get(**item["original"])
    if "digest" in spec["source"] and digest(original) != spec["source"]["digest"]:
        raise DependencyError("dependency-original-artifact-drift")
    if item["format"] == "directory":
        rows = decode_json(original)
        if not isinstance(rows, list):
            raise DependencyError("dependency-file-inventory-invalid")
        files = {}
        for row in rows:
            if set(row) != {"path", "digest", "size"}:
                raise DependencyError("dependency-file-inventory-invalid")
            name = path_name(row["path"])
            if name in files:
                raise DependencyError("dependency-path-collision")
            files[name] = store.get(row["digest"], row["size"])
    elif item["format"] == "file":
        files = {Path(item["mount"]).name: original}
    else:
        files = archive_files(original, item["format"])
    rows = [{"path": name, "digest": digest(data), "size": len(data)} for name, data in sorted(files.items())]
    for transform in transforms:
        if transform["artifact"] != item["id"]:
            continue
        if tree_identity(rows) != transform["inputDigest"]:
            raise DependencyError("dependency-patch-preimage-mismatch")
        by_name = {row["path"]: row for row in rows}
        for changed in transform["files"]:
            before = by_name.get(changed["path"])
            after = next((row for row in item["files"] if row["path"] == changed["path"]), None)
            if before is None or before["digest"] != changed["inputDigest"] or after is None:
                raise DependencyError("dependency-patch-preimage-mismatch")
            # Each intermediate replacement is content addressed; obtain size
            # from the bounded stored object when a later patch changes it again.
            payload = read_bytes(store.path(changed["outputDigest"]))
            if digest(payload) != changed["outputDigest"]:
                raise DependencyError("dependency-patch-output-mismatch")
            by_name[changed["path"]] = {"path": changed["path"], "digest": digest(payload), "size": len(payload)}
        rows = [by_name[name] for name in sorted(by_name)]
        if tree_identity(rows) != transform["outputDigest"]:
            raise DependencyError("dependency-patch-output-mismatch")
    if rows != item["files"] or tree_identity(rows) != item["treeDigest"]:
        raise DependencyError("dependency-transformed-output-mismatch")


@dataclass
class Closure:
    project: Path
    work: Path
    store: Store
    manifest: bytes
    lock_bytes: bytes
    lock: dict

    @property
    def identity(self) -> str:
        return digest(canonical({"manifest": digest(self.manifest), "lock": digest(self.lock_bytes)}))

    @property
    def mounts(self) -> tuple[str, ...]:
        return tuple(row["mount"] for row in self.lock["artifacts"])

    def check_unchanged(self):
        if (read_bytes(self.project / MANIFEST, MAX_LOCK) != self.manifest
                or read_bytes(self.project / LOCK, MAX_LOCK) != self.lock_bytes):
            raise DependencyError("dependency-input-mutated")
        for row in self.lock["nativeLocks"]:
            if read_bytes(self.project / row["path"]) != self.store.get(row["digest"], row["size"]):
                raise DependencyError("dependency-native-lock-mutated")
        for item in self.lock["artifacts"]:
            self.store.get(**item["original"])
            destination = self.work / item["mount"]
            for row in item["files"]:
                target = destination if item["format"] == "file" else destination / row["path"]
                if read_bytes(target) != self.store.get(row["digest"], row["size"]):
                    raise DependencyError("dependency-transformed-output-mutated")
            if item["format"] != "file":
                if {name: digest(data) for name, data in directory_files(destination).items()} != {
                        row["path"]: row["digest"] for row in item["files"]}:
                    raise DependencyError("dependency-unobserved-materialized-input")


@dataclass(frozen=True)
class VerifiedInputs:
    project: Path
    store: Store
    manifest_bytes: bytes
    lock_bytes: bytes
    manifest: dict
    lock: dict

    @property
    def identity(self) -> str:
        return digest(canonical({"manifest": digest(self.manifest_bytes), "lock": digest(self.lock_bytes)}))


def verify_inputs(project: Path, language: str, *, cache: Path | None = None,
                  profile_identity: dict | None = None) -> VerifiedInputs | None:
    """Verify a synced closure without materializing or executing any input.

    Executable-input metadata is allowed for attributable trust review. Its
    presence never authorizes compilation or execution; ``prepare`` denies it.
    """
    if not (project / MANIFEST).exists():
        if (project / LOCK).exists():
            raise DependencyError("dependency-manifest-missing")
        return None
    manifest_bytes = read_bytes(project / MANIFEST, MAX_LOCK)
    manifest = validate_manifest(decode_json(manifest_bytes), language)
    try:
        lock_bytes = read_bytes(project / LOCK, MAX_LOCK)
    except FileNotFoundError:
        raise DependencyError("dependency-lock-missing-resolve-and-review") from None
    lock = decode_json(lock_bytes)
    if (not isinstance(lock, dict) or set(lock) != {"formatVersion", "language", "manifestDigest", "selection", "nativeLocks", "artifacts", "transformations", "completeness", "executableInputs"}
            or lock["formatVersion"] != 1 or lock["language"] != language
            or lock["manifestDigest"] != digest(manifest_bytes) or lock["selection"] != manifest["selection"]
            or lock["completeness"] != "selected-declared-closure"
            or not isinstance(lock["artifacts"], list) or len(lock["artifacts"]) > MAX_ARTIFACTS):
        raise DependencyError("dependency-lock-drift-resolve-and-review")
    expected_tools = [row["id"] for row in manifest["artifacts"] if row["role"] == "build-tool"]
    if lock["executableInputs"] != expected_tools:
        raise DependencyError("dependency-executable-input-drift")
    if profile_identity is not None and lock["selection"] != profile_identity:
        raise DependencyError("dependency-selected-profile-drift")
    store = Store(cache or project / "dependency-inputs/objects", create=False)
    if (not isinstance(lock["nativeLocks"], list) or len(lock["nativeLocks"]) > MAX_ARTIFACTS
            or any(not isinstance(row, dict) or set(row) != {"path", "digest", "size"} for row in lock["nativeLocks"])
            or not isinstance(lock["transformations"], list)
            or len(lock["transformations"]) != len(manifest["transformations"])):
        raise DependencyError("dependency-lock-inventory-invalid")
    for observed, expected in zip(lock["transformations"], manifest["transformations"]):
        if (not isinstance(observed, dict) or set(observed) != {"id", "artifact", "inputDigest", "outputDigest", "tool", "selection", "changes"}
                or any(observed[key] != expected[key] for key in ("id", "artifact", "inputDigest", "outputDigest", "tool", "selection"))):
            raise DependencyError("dependency-transformation-lock-drift")
    declared = {item["id"]: item for item in manifest["artifacts"]}
    if (len(lock["artifacts"]) != len(declared) or {row["id"] for row in lock["artifacts"]} != set(declared)
            or [row["path"] for row in lock["nativeLocks"]] != manifest["nativeLocks"]):
        raise DependencyError("dependency-graph-not-closed")
    for row in lock["nativeLocks"]:
        try:
            native_bytes = read_bytes(project / row["path"])
        except FileNotFoundError:
            raise DependencyError("dependency-native-lock-missing") from None
        if native_bytes != store.get(row["digest"], row["size"]):
            raise DependencyError("dependency-native-lock-drift")
    total_files = total_bytes = 0
    for item in lock["artifacts"]:
        spec = declared[item["id"]]
        if (set(item) != {"id", "role", "format", "mount", "dependencies", "metadata", "source", "original", "files", "treeDigest"}
                or any(item[key] != spec[key] for key in ("role", "format", "mount", "dependencies", "metadata"))
                or tree_identity(item["files"]) != item["treeDigest"]):
            raise DependencyError("dependency-lock-artifact-drift")
        total_files += len(item["files"])
        total_bytes += sum(row["size"] for row in item["files"])
        if total_files > MAX_CLOSURE_FILES or total_bytes > MAX_CLOSURE_BYTES:
            raise DependencyError("dependency-closure-limit")
        verify_artifact(item, spec, manifest["transformations"], store)
        for row in item["files"]:
            store.get(row["digest"], row["size"])
        if item["format"] == "file" and (len(item["files"]) != 1 or item["files"][0]["path"] != Path(item["mount"]).name):
            raise DependencyError("dependency-file-inventory-invalid")
    if (read_bytes(project / MANIFEST, MAX_LOCK) != manifest_bytes
            or read_bytes(project / LOCK, MAX_LOCK) != lock_bytes):
        raise DependencyError("dependency-input-mutated")
    return VerifiedInputs(project, store, manifest_bytes, lock_bytes, manifest, lock)


def prepare(project: Path, work: Path, output: Path, language: str, *, cache: Path | None = None,
            profile_identity: dict | None = None) -> Closure | None:
    verified = verify_inputs(project, language, cache=cache, profile_identity=profile_identity)
    if verified is None:
        return None
    if verified.lock["executableInputs"]:
        raise DependencyError("dependency-executable-tools-require-isolated-stage")
    store, lock = verified.store, verified.lock
    for item in lock["artifacts"]:
        destination = regular_path(work / item["mount"])
        if destination.exists():
            raise DependencyError("dependency-mount-collision")
        if item["format"] == "file":
            if len(item["files"]) != 1 or item["files"][0]["path"] != destination.name:
                raise DependencyError("dependency-file-inventory-invalid")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(store.get(item["files"][0]["digest"], item["files"][0]["size"]))
        else:
            materialize(item["files"], destination, store)
    manifest_bytes, lock_bytes = verified.manifest_bytes, verified.lock_bytes
    closure = Closure(project, work, store, manifest_bytes, lock_bytes, lock)
    closure.check_unchanged()
    receipt = {"formatVersion": 1, "inputIdentity": closure.identity, "language": language,
               "manifestDigest": digest(manifest_bytes), "lockDigest": digest(lock_bytes),
               "selection": lock["selection"], "artifacts": lock["artifacts"], "transformations": lock["transformations"],
               "networkResolution": False, "hermetic": False, "completeness": lock["completeness"],
               "trust": "source-and-build-policy-required", "sbomBoundary": "selected-application-inputs-only"}
    with (output / "application-dependencies.json").open("xb") as stream:
        stream.write(canonical(receipt) + b"\n")
    return closure


def trust_inputs(project: Path) -> dict:
    """Separate attributable lock identity for the dev controller's trust/watch."""
    if not (project / MANIFEST).exists():
        return {}
    manifest = read_bytes(project / MANIFEST, MAX_LOCK)
    value = validate_manifest(decode_json(manifest))
    lock = read_bytes(project / LOCK, MAX_LOCK)
    selected = decode_json(lock)
    if selected.get("manifestDigest") != digest(manifest):
        raise DependencyError("dependency-lock-drift-resolve-and-review")
    return {"applicationManifest": digest(manifest), "applicationLock": digest(lock),
            "selection": value["selection"], "executableInputs": selected.get("executableInputs", [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--repositories", type=Path, help="Private stage configuration; never copied into evidence")
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.candidate.exists():
            raise DependencyError("dependency-candidate-exists")
        repositories = document(args.repositories) if args.repositories else {}
        candidate = capture(args.project, cache=args.cache, repositories=repositories)
        with args.candidate.open("xb") as output:
            output.write(canonical(candidate) + b"\n")
    except (DependencyError, OSError) as error:
        failed = args.candidate.with_name(args.candidate.name + ".failed.json")
        reason = str(error) if isinstance(error, DependencyError) else "dependency-resolution-io-failed"
        if not failed.exists():
            with failed.open("xb") as output:
                output.write(canonical({"formatVersion": 1, "status": "failed", "stage": "resolution-capture", "reason": reason}) + b"\n")
        raise SystemExit(reason) from None
    print("Captured selected inputs. Review the candidate and install as " + LOCK + ".")


if __name__ == "__main__":
    main()
