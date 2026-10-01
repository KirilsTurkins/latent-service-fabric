"""Package declared immutable bytes; no filesystem, scratch or runtime authority."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from tools.dev_workflow.common import decode, digest, encode
from tools.rust_capsule_project import inventory, read_file

MANIFEST = "capsule-resources.json"
INDEX = "resource-index.json"
PROFILE = "lsf.packaged-resources.v1"
MAX_COUNT = 256
MAX_NAME = 256
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_DOCUMENT = 256 * 1024
RECIPE = ("tools/guest_resources.py",)
SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
MEDIA = re.compile(r"[A-Za-z0-9!#$&^_.+-]{1,127}/[A-Za-z0-9!#$&^_.+-]{1,127}\Z")
RESERVED = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?\Z", re.I)


class ResourceError(ValueError):
    """Static diagnostics keep absent, malformed, denied and exhausted distinct."""
    def __init__(self, category: str, code: str):
        self.category, self.code = category, code
        super().__init__(code)


def require(condition, code: str, category: str = "malformed") -> None:
    if not condition:
        raise ResourceError(category, code)


def name(value: str, maximum: int = MAX_NAME) -> str:
    require(isinstance(value, str), "resource-name-invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        raise ResourceError("malformed", "resource-name-encoding") from None
    require(0 < len(encoded) <= maximum, "resource-name-limit", "exhausted")
    require(unicodedata.normalize("NFC", value) == value, "resource-name-not-normalized")
    require(not any(ord(character) < 32 or ord(character) == 127 or character in '\\:<>"|?*%'
                    for character in value), "resource-name-unsafe", "denied")
    parts = value.split("/")
    require(len(parts) <= 16 and all(part not in {"", ".", ".."} and not part.endswith((".", " "))
                                   and len(part.encode("utf-8")) <= 128 and not RESERVED.fullmatch(part)
                                   for part in parts), "resource-name-alias-or-traversal", "denied")
    return value


def media(value: str) -> str:
    require(isinstance(value, str) and MEDIA.fullmatch(value), "resource-media-invalid")
    return value


def register(logical: str, spellings: dict, leaves: set) -> None:
    parts = logical.split("/")
    for length in range(1, len(parts) + 1):
        prefix = "/".join(parts[:length])
        alias = prefix.casefold()
        require(spellings.setdefault(alias, prefix) == prefix, "resource-name-collision")
        require(length == len(parts) or alias not in leaves, "resource-file-directory-collision")
    alias = logical.casefold()
    require(alias not in leaves and not any(key.startswith(alias + "/") for key in spellings), "resource-name-collision")
    leaves.add(alias)


def declarations(files: dict[str, bytes]) -> list[dict]:
    if MANIFEST not in files:
        return []
    value = decode(files[MANIFEST], MAX_DOCUMENT, maximum_items=4096)
    require(isinstance(value, dict) and set(value) == {"schemaVersion", "resources"}
            and value["schemaVersion"] == PROFILE, "resource-manifest-schema")
    require(isinstance(value["resources"], list) and len(value["resources"]) <= MAX_COUNT, "resource-count-limit", "exhausted")
    for row in value["resources"]:
        require(isinstance(row, dict) and set(row) == {"path", "source", "mediaType"}, "resource-declaration-schema")
        name(row["path"])
        name(row["source"], 1024)
        media(row["mediaType"])
    return value["resources"]


def dependency_resource(files: dict[str, bytes], row: dict) -> None:
    require(isinstance(row, dict) and set(row) == {"path", "source", "mediaType", "digest", "owner"},
            "resource-dependency-declaration-schema")
    name(row["path"])
    name(row["source"], 1024)
    media(row["mediaType"])
    require(isinstance(row["digest"], str) and SHA.fullmatch(row["digest"]), "resource-dependency-digest")
    require(isinstance(row["owner"], str) and re.fullmatch(r"[A-Za-z0-9_@+./:-]{1,256}", row["owner"])
            and ".." not in row["owner"] and "//" not in row["owner"],
            "resource-dependency-owner")
    require("latent.dependencies.lock.json" in files, "resource-dependency-lock-missing", "missing")
    lock = decode(files["latent.dependencies.lock.json"], 8 * 1024 * 1024)
    require(isinstance(lock, dict) and isinstance(lock.get("artifacts"), list), "resource-dependency-lock-invalid")
    candidates = [item for item in lock["artifacts"] if isinstance(item, dict) and item.get("id") == row["owner"]]
    require(len(candidates) == 1 and isinstance(candidates[0].get("files"), list), "resource-dependency-owner-not-captured", "denied")
    require(row["source"] in files, "resource-source-missing", "missing")
    payload = files[row["source"]]
    require(isinstance(payload, bytes) and digest(payload) == row["digest"], "resource-dependency-bytes-changed", "denied")
    require(any(isinstance(item, dict) and item.get("digest") == row["digest"] and item.get("size") == len(payload)
                for item in candidates[0]["files"]), "resource-dependency-bytes-not-captured", "denied")


@dataclass(frozen=True)
class PackagedResources:
    index: dict
    objects: dict[str, bytes]


def capture(files: dict[str, bytes], component: bytes, source: bytes, *, additional_resources=()) -> PackagedResources | None:
    require(isinstance(additional_resources, (list, tuple)) and len(additional_resources) <= MAX_COUNT,
            "resource-count-limit", "exhausted")
    if MANIFEST not in files and not additional_resources:
        return None
    declared = declarations(files)
    rows = [*declared, *additional_resources]
    require(len(rows) <= MAX_COUNT, "resource-count-limit", "exhausted")
    spellings, leaves, objects, selected = {}, set(), {}, []
    total = 0
    for number, row in enumerate(rows):
        require(isinstance(row, dict), "resource-declaration-schema")
        if number >= len(declared):
            dependency_resource(files, row)
        logical, original = name(row["path"]), name(row["source"], 1024)
        content_type = media(row["mediaType"])
        # Prefix aliases and file/directory collisions are ambiguous too.
        register(logical, spellings, leaves)
        require(original in files, "resource-source-missing", "missing")
        payload = files[original]
        require(isinstance(payload, bytes), "resource-source-bytes-required")
        total += len(payload)
        require(len(payload) <= MAX_FILE and total <= MAX_TOTAL, "resource-byte-limit", "exhausted")
        identity = digest(payload)
        object_path = "resources/objects/" + identity[7:]
        objects[object_path] = payload
        selected.append({"path": logical, "object": object_path, "digest": identity, "size": len(payload),
                         "mediaType": content_type, "origin": "dependency" if "owner" in row else "application",
                         **({"owner": row["owner"]} if "owner" in row else {})})
    base = {"schemaVersion": PROFILE, "sourceDigest": digest(source), "componentDigest": digest(component),
            "manifestDigest": digest(files[MANIFEST]) if MANIFEST in files else None,
            "dependencyLockDigest": digest(files["latent.dependencies.lock.json"]) if "latent.dependencies.lock.json" in files else None,
            "limits": {"count": MAX_COUNT, "nameBytes": MAX_NAME, "fileBytes": MAX_FILE, "totalBytes": MAX_TOTAL},
            "count": len(selected), "bytes": total, "resources": sorted(selected, key=lambda item: item["path"]),
            "runtimeLookup": "language-profile-qualification-required", "scratchStorage": "unsupported"}
    return PackagedResources({**base, "identity": digest(encode(base))}, objects)


def assemble(output: Path, files: dict[str, bytes], component: bytes, *, additional_resources=()) -> list[tuple[str, str, str]]:
    """All six maintained builders call the same exact-byte package assembly."""
    source_path = output / "source-inputs.json"
    source = read_file(source_path) if source_path.exists() else inventory(files)
    packaged = capture(files, component, source, additional_resources=additional_resources)
    if packaged is None:
        return []
    layers = []
    for path, payload in sorted({INDEX: encode(packaged.index), **packaged.objects}.items()):
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(payload)
        content_type = "application/vnd.latent.packaged-resources.v1+json" if path == INDEX else "application/octet-stream"
        layers.append((path, "asset", content_type))
    return layers


def verify(raw: bytes, objects: dict[str, bytes], *, source_digest: str, component_digest: str,
           manifest_digest: str | None = None, dependency_lock_digest: str | None = None) -> dict:
    value = decode(raw, MAX_DOCUMENT, maximum_items=4096)
    fields = {"schemaVersion", "sourceDigest", "componentDigest", "manifestDigest", "dependencyLockDigest", "limits",
              "count", "bytes", "resources", "runtimeLookup", "scratchStorage", "identity"}
    require(isinstance(value, dict) and set(value) == fields and value["schemaVersion"] == PROFILE, "resource-index-schema")
    require(value["limits"] == {"count": MAX_COUNT, "nameBytes": MAX_NAME, "fileBytes": MAX_FILE, "totalBytes": MAX_TOTAL}
            and value["runtimeLookup"] == "language-profile-qualification-required"
            and value["scratchStorage"] == "unsupported", "resource-index-profile")
    for field in ("sourceDigest", "componentDigest", "manifestDigest", "dependencyLockDigest", "identity"):
        require(value[field] is None and field in {"manifestDigest", "dependencyLockDigest"}
                or isinstance(value[field], str) and SHA.fullmatch(value[field]), "resource-index-digest")
    base = {key: item for key, item in value.items() if key != "identity"}
    require(value["identity"] == digest(encode(base)), "resource-index-identity-mismatch", "denied")
    require(value["sourceDigest"] == source_digest and value["componentDigest"] == component_digest
            and value["manifestDigest"] == manifest_digest
            and value["dependencyLockDigest"] == dependency_lock_digest, "resource-index-source-binding-mismatch", "denied")
    require(isinstance(value["resources"], list) and type(value["count"]) is int
            and value["count"] == len(value["resources"]) <= MAX_COUNT, "resource-count-limit", "exhausted")
    require(type(value["bytes"]) is int and 0 <= value["bytes"] <= MAX_TOTAL, "resource-byte-limit", "exhausted")
    total, spellings, paths_seen, object_paths = 0, {}, set(), set()
    for row in value["resources"]:
        require(isinstance(row, dict) and set(row) in ({"path", "object", "digest", "size", "mediaType", "origin"},
                {"path", "object", "digest", "size", "mediaType", "origin", "owner"}), "resource-index-entry-schema")
        logical = name(row["path"])
        media(row["mediaType"])
        register(logical, spellings, paths_seen)
        require(row["origin"] == "application" and "owner" not in row
                or row["origin"] == "dependency" and isinstance(row.get("owner"), str)
                and re.fullmatch(r"[A-Za-z0-9_@+./:-]{1,256}", row["owner"]), "resource-index-origin")
        require(isinstance(row["digest"], str) and SHA.fullmatch(row["digest"])
                and row["object"] == "resources/objects/" + row["digest"][7:], "resource-object-path-invalid")
        require(type(row["size"]) is int and 0 <= row["size"] <= MAX_FILE, "resource-byte-limit", "exhausted")
        require(row["object"] in objects, "resource-object-missing", "missing")
        payload = objects[row["object"]]
        require(isinstance(payload, bytes) and len(payload) == row["size"] and digest(payload) == row["digest"],
                "resource-object-integrity-mismatch", "denied")
        total += row["size"]
        object_paths.add(row["object"])
    require(total == value["bytes"] and set(objects) == object_paths, "resource-index-inventory-mismatch", "denied")
    return value
