"""Capture selected JAR resources as independently verified graph children.

These bytes are package inputs. Standard Java lookup still requires an emitted
component and the selected TeaVM resource implementation to be qualified.
"""
from __future__ import annotations

import copy
from pathlib import Path

from tools import guest_resources
from tools.application_dependencies import Closure, LOCK, MANIFEST, MAX_ARTIFACTS
from tools.application_dependency_store import DependencyError, Store, read_bytes, regular_path
from tools.build_snapshot import canonical, digest
from tools.java_application_dependencies import deterministic_jar, entry_selection, per_jar_metadata
from tools.rust_capsule_project import decode_json

PROFILE = "java-selected-jar-resource-v1"


def require(condition, code: str) -> None:
    if not condition:
        raise DependencyError(code)


def release_profile(release: int) -> None:
    require(type(release) is int and release == 25, "java-release-must-match-pinned-profile")


def jar_artifacts(artifacts: list[dict]) -> list[dict]:
    selected = [item for item in artifacts if item["role"] == "application"
                and item["metadata"].get("assetType") != "maven-resolution-metadata"]
    require(all(item["format"] == "file" and item["mount"].endswith(".jar") for item in selected),
            "java-application-dependency-must-be-captured-jar")
    return selected


def resource_entries(payload: bytes, release: int) -> tuple[dict[str, bytes], list[dict]]:
    selected, origins = entry_selection(payload, release)
    resources = []
    for path, data in selected.items():
        if path.endswith(".class") or per_jar_metadata(path):
            continue
        if path.startswith("META-INF/services/"):
            try:
                lines = data.decode("utf-8").splitlines()
            except UnicodeError:
                raise DependencyError("java-service-provider-encoding") from None
            providers = [line.split("#", 1)[0].strip() for line in lines]
            require(not any(provider and any(not (character.isalnum() or character in "._$")
                                             for character in provider) for provider in providers),
                    "java-service-provider-metadata-invalid")
        guest_resources.name(path)
        resources.append({"path": path, **origins[path], "digest": digest(data), "size": len(data)})
    return selected, resources


def resource_id(parent: str, entry: dict, release: int) -> str:
    return "java-jar-resource:" + digest(canonical({"profile": PROFILE, "jar": parent,
        "path": entry["path"], "originalEntry": entry["originalEntry"], "release": release}))[7:]


def resource_metadata(parent: str, original: str, entry: dict, release: int) -> dict:
    return {"ecosystem": "java-classpath-resource", "profile": PROFILE, "jar": parent,
            "originalJarDigest": original, "release": release, "path": entry["path"],
            "originalEntry": entry["originalEntry"], "selectedVersion": entry["selectedVersion"],
            "encoding": "opaque-bytes"}


def resource_selection(parent: str, original: str, entries: list[dict], release: int) -> dict:
    return {"profile": PROFILE, "originalJarDigest": original, "release": release,
            "entries": [{"artifact": resource_id(parent, entry, release), **entry} for entry in entries]}


def bound_entry(entry: dict, spellings: dict, leaves: set, count: int, total: int) -> tuple[int, int]:
    guest_resources.register(entry["path"], spellings, leaves)
    count, total = count + 1, total + entry["size"]
    require(count <= guest_resources.MAX_COUNT, "java-resource-count-limit")
    require(entry["size"] <= guest_resources.MAX_FILE and total <= guest_resources.MAX_TOTAL,
            "java-resource-byte-limit")
    return count, total


def capture_resources(project: Path, store: Store, artifacts: list[dict], *, release: int = 25) -> list[dict]:
    """Select from captured JAR bytes without loading any application classes."""
    release_profile(release)
    project = regular_path(project)
    result = copy.deepcopy(artifacts)
    parents = jar_artifacts(result)
    require(not any("resourceSelection" in item["metadata"] for item in parents),
            "java-resource-capture-already-selected")
    children, spellings, leaves, observed = [], {}, set(), []
    count = total = 0
    identities = {item["id"] for item in result}
    for item in parents:
        require(set(item["source"]) == {"path"}, "java-resource-capture-requires-local-store")
        source = regular_path(project / item["source"]["path"])
        require(source.is_relative_to(project), "java-resource-capture-source-outside-project")
        original = read_bytes(source)
        original_digest = digest(original)
        require(source == store.path(original_digest), "java-resource-capture-source-not-addressed")
        selected, entries = resource_entries(original, release)
        item["metadata"]["resourceSelection"] = resource_selection(item["id"], original_digest, entries, release)
        observed.append((source, original_digest))
        for entry in entries:
            count, total = bound_entry(entry, spellings, leaves, count, total)
            child_id = resource_id(item["id"], entry, release)
            require(child_id not in identities, "java-resource-artifact-collision")
            identities.add(child_id)
            require(len(identities) <= MAX_ARTIFACTS, "java-resource-graph-limit")
            captured = store.put(selected[entry["path"]])
            require(captured == {"digest": entry["digest"], "size": entry["size"]},
                    "java-resource-capture-integrity")
            children.append({"id": child_id, "role": "resource", "format": "file",
                "mount": "dependencies/java/resources/" + child_id.split(":", 1)[1] + ".bin",
                "source": {"path": store.path(entry["digest"]).relative_to(project).as_posix()},
                "dependencies": [], "metadata": resource_metadata(item["id"], original_digest, entry, release)})
            item["dependencies"].append(child_id)
    require(all(digest(read_bytes(source)) == identity for source, identity in observed),
            "java-resource-capture-jar-mutated")
    return [*result, *children]


def packaged_resources(closure: Closure | None, receipt: dict, files: dict[str, bytes]) -> tuple[tuple[dict, ...], dict[str, bytes]]:
    """Verify JAR selection, child ownership and synced source bytes for assembly."""
    if closure is None:
        require(not receipt.get("resources"), "java-resource-capture-requires-closure")
        return (), {}
    release = receipt.get("release")
    release_profile(release)
    require(files.get(MANIFEST) == closure.manifest and files.get(LOCK) == closure.lock_bytes,
            "java-resource-source-lock-binding")
    require(decode_json(closure.lock_bytes) == closure.lock, "java-resource-lock-mutated")
    manifest = decode_json(closure.manifest)
    declared = {item["id"]: item for item in manifest["artifacts"]}
    locked = {item["id"]: item for item in closure.lock["artifacts"]}
    parents = jar_artifacts(closure.lock["artifacts"])
    require(receipt.get("formatVersion") == 1 and len(receipt.get("artifacts", ())) == len(parents),
            "java-resource-classpath-receipt-drift")
    additional, sources, expected_resources, spellings, leaves, children_seen = [], {}, [], {}, set(), set()
    count = total = 0
    for index, parent in enumerate(parents):
        original = read_bytes(closure.work / parent["mount"])
        selected, entries = resource_entries(original, release)
        original_digest = digest(original)
        require(parent["original"]["digest"] == original_digest
                and parent["original"]["size"] == len(original), "java-resource-original-jar-drift")
        expected_receipt = {"id": parent["id"], "originalDigest": original_digest,
            "selectedDigest": digest(deterministic_jar(selected)),
            "selection": {"release": release, "multiRelease": "highest-version-at-most-release", "classpathOrder": index},
            "entries": [{"path": name, "digest": digest(data), "size": len(data)} for name, data in selected.items()],
            "transformation": "deterministic-selected-jar-v1", "vendorSignature": "original-only"}
        require(receipt["artifacts"][index] == expected_receipt, "java-resource-classpath-receipt-drift")
        selection = parent["metadata"].get("resourceSelection")
        require(not entries or selection is not None, "java-resource-capture-requires-recapture")
        if selection is not None:
            require(selection == resource_selection(parent["id"], original_digest, entries, release),
                    "java-resource-jar-selection-drift")
        for entry in entries:
            count, total = bound_entry(entry, spellings, leaves, count, total)
            child_id = resource_id(parent["id"], entry, release)
            require(child_id in locked and child_id in declared and child_id in parent["dependencies"],
                    "java-resource-child-not-selected")
            child, spec = locked[child_id], declared[child_id]
            require(child["role"] == "resource" and child["format"] == "file"
                    and child["mount"] == "dependencies/java/resources/" + child_id.split(":", 1)[1] + ".bin"
                    and not child["dependencies"]
                    and child["metadata"] == resource_metadata(parent["id"], original_digest, entry, release)
                    and all(child[key] == spec[key] for key in ("role", "format", "mount", "dependencies", "metadata")),
                    "java-resource-child-attribution-drift")
            require(child["original"] == {"digest": entry["digest"], "size": entry["size"]}
                    and child["files"] == [{"path": Path(child["mount"]).name,
                                            "digest": entry["digest"], "size": entry["size"]}],
                    "java-resource-child-bytes-not-captured")
            require(set(spec["source"]) == {"path"}, "java-resource-child-source-not-local")
            source = spec["source"]["path"]
            require(source == closure.store.path(entry["digest"]).relative_to(closure.project).as_posix(),
                    "java-resource-child-source-not-addressed")
            data = selected[entry["path"]]
            require((source not in files or files[source] == data)
                    and read_bytes(closure.work / child["mount"]) == data
                    and closure.store.get(entry["digest"], entry["size"]) == data,
                    "java-resource-child-bytes-changed")
            row = {"path": entry["path"], "source": source, "mediaType": "application/octet-stream",
                   "digest": entry["digest"], "owner": child_id}
            sources[source] = data
            guest_resources.dependency_resource({**files, **sources}, row)
            additional.append(row)
            expected_resources.append({"path": entry["path"], "digest": entry["digest"],
                                       "size": entry["size"], "owner": parent["id"]})
            children_seen.add(child_id)
    require(receipt.get("resources") == expected_resources, "java-resource-classpath-resources-drift")
    require(children_seen == {item["id"] for item in closure.lock["artifacts"]
            if item["metadata"].get("profile") == PROFILE and item["role"] == "resource"},
            "java-resource-unowned-child")
    return tuple(additional), sources
