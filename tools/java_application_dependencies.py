"""Deterministic, bounded captured JAR selection for the maintained TeaVM recipe."""
from __future__ import annotations

import io
from pathlib import Path
import struct
import zipfile

from tools.application_dependency_store import DependencyError, archive_files, read_bytes
from tools.application_dependencies import Closure
from tools.build_snapshot import canonical, digest


def entry_selection(payload: bytes, release: int) -> tuple[dict[str, bytes], dict[str, dict]]:
    if type(release) is not int or release < 9:
        raise DependencyError("java-release-selection-invalid")
    entries = archive_files(payload, "zip")
    manifest = entries.get("META-INF/MANIFEST.MF", b"").decode("utf-8", "strict")
    multi = any(line.lower().strip() == "multi-release: true" for line in manifest.splitlines())
    selected, versions, origins = {}, {}, {}
    for name, data in entries.items():
        if name.startswith("META-INF/versions/"):
            pieces = name.split("/", 3)
            if len(pieces) != 4 or not pieces[2].isdigit() or int(pieces[2]) < 9:
                raise DependencyError("java-multi-release-entry-invalid")
            version, target = int(pieces[2]), pieces[3]
            if not multi:
                raise DependencyError("java-multi-release-manifest-required")
            if version > release:
                continue  # JVM's explicit selected-release semantics.
        else:
            version, target = 0, name
        if version >= versions.get(target, -1):
            selected[target], versions[target] = data, version
            origins[target] = {"originalEntry": name, "selectedVersion": version}
    for name, data in selected.items():
        if name.startswith("META-INF/services/org.teavm."):
            # TeaVM discovers compiler extension services from its application
            # class loader. They are host executable inputs, not guest services.
            raise DependencyError("java-executable-compiler-provider-requires-isolation")
        if name.endswith(".class"):
            if len(data) < 8 or data[:4] != b"\xca\xfe\xba\xbe":
                raise DependencyError("java-class-bytecode-invalid")
            _minor, major = struct.unpack(">HH", data[4:8])
            if major > release + 44:
                raise DependencyError("java-class-bytecode-newer-than-profile")
            if name.startswith(("java/", "org/teavm/interop/", "dev/latent/guest/", "dev/latent/generated/")):
                raise DependencyError("java-dependency-overrides-platform")
        if name.endswith((".so", ".dll", ".dylib", ".jnilib")):
            # Reachability is not inferred from a filename. Preserve it and let
            # the runtime compatibility report classify reachable JNI use.
            continue
    return dict(sorted(selected.items())), {name: origins[name] for name in sorted(selected)}


def selected_entries(payload: bytes, release: int) -> dict[str, bytes]:
    return entry_selection(payload, release)[0]


def per_jar_metadata(name: str) -> bool:
    return (name == "META-INF/MANIFEST.MF" or name == "module-info.class"
            or name.startswith("META-INF/") and name.endswith((".SF", ".RSA", ".DSA", ".EC"))
            or name.upper().startswith(("META-INF/LICENSE", "META-INF/NOTICE")))


def deterministic_jar(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output.getvalue()


def classpath(closure: Closure | None, destination: Path, *, release: int = 25) -> tuple[tuple[Path, ...], dict]:
    if closure is None:
        return (), {"formatVersion": 1, "release": release, "artifacts": [], "resources": []}
    if type(release) is not int or release != 25:
        raise DependencyError("java-release-must-match-pinned-profile")
    artifacts = [row for row in closure.lock["artifacts"] if row["role"] == "application"
                 and row["metadata"].get("assetType") != "maven-resolution-metadata"]
    if any(row["format"] != "file" or not row["mount"].endswith(".jar") for row in artifacts):
        raise DependencyError("java-application-dependency-must-be-captured-jar")
    destination.mkdir()
    owners, paths, receipts, resources = {}, [], [], []
    for index, item in enumerate(artifacts):
        original = read_bytes(closure.work / item["mount"])
        selected = selected_entries(original, release)
        for name, data in selected.items():
            # Signature/manifest/module metadata identifies its own JAR rather
            # than an application classpath lookup; retain in each artifact.
            per_jar = per_jar_metadata(name)
            if not per_jar:
                if name in owners:
                    raise DependencyError("java-duplicate-class-or-resource")
                owners[name] = item["id"]
            if not name.endswith(".class") and not per_jar:
                if name.startswith("META-INF/services/"):
                    try:
                        lines = data.decode("utf-8").splitlines()
                    except UnicodeError:
                        raise DependencyError("java-service-provider-encoding") from None
                    providers = [line.split("#", 1)[0].strip() for line in lines]
                    if any(provider and any(not (character.isalnum() or character in "._$") for character in provider)
                           for provider in providers):
                        raise DependencyError("java-service-provider-metadata-invalid")
                resources.append({"path": name, "digest": digest(data), "size": len(data), "owner": item["id"]})
        payload = deterministic_jar(selected)
        target = destination / (f"{index:04d}.jar")
        target.write_bytes(payload)
        paths.append(target)
        receipts.append({"id": item["id"], "originalDigest": digest(original), "selectedDigest": digest(payload),
                         "selection": {"release": release, "multiRelease": "highest-version-at-most-release", "classpathOrder": index},
                         "entries": [{"path": name, "digest": digest(data), "size": len(data)} for name, data in selected.items()],
                         "transformation": "deterministic-selected-jar-v1", "vendorSignature": "original-only"})
    return tuple(paths), {"formatVersion": 1, "release": release, "artifacts": receipts, "resources": resources,
                          "duplicatePolicy": "reject-lookup-entries-per-jar-legal-metadata",
                          "serviceProviders": "preserved-no-host-initialization",
                          "resourceEncoding": "opaque-bytes", "shading": "preserve-original-class-names"}
