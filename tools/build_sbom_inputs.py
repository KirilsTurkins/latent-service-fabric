"""Normalized bounded SBOM inputs from an actual maintained echo build.

No CycloneDX, final package identity, dependency-graph closure, archive
verification or publisher authority is asserted by this local producer.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.build_inventory_licenses import license_expression, load_license_ids
from tools.build_inventory_manifests import ManifestReader
from tools.build_inventory_units import InventoryLimits, _pairs, _text, collect_units
from tools.build_snapshot import SnapshotError, canonical, digest, is_reparse, owned_child, portable_path


def cargo_home(environment: dict[str, str]) -> Path:
    selected = environment.get("CARGO_HOME")
    if selected is None:
        home = environment.get("USERPROFILE") or environment.get("HOME")
        if not home:
            raise SnapshotError("approved Cargo home is unavailable")
        selected = str(Path(home) / ".cargo")
    path = Path(selected)
    if not path.is_absolute() or not path.is_dir() or is_reparse(path):
        raise SnapshotError("approved Cargo home is invalid")
    return path.resolve(strict=True)


def _read(path: Path, owner: Path, maximum: int = 256 * 1024) -> bytes:
    owned_child(path, owner)
    if is_reparse(path) or not path.is_file():
        raise SnapshotError("SBOM package input is not a regular file")
    before = path.stat()
    if before.st_size > maximum:
        raise SnapshotError("SBOM package input exceeds its byte limit")
    with path.open("rb") as source:
        data = source.read(maximum + 1)
    after = path.stat()
    if (len(data) != before.st_size or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns or after.st_ino != before.st_ino):
        raise SnapshotError("SBOM package input changed during observation")
    return data


class InventoryCollector:
    """Keep normalized observations, never Cargo's private package IDs/paths."""
    def __init__(self, source_root: Path, source_inventory: bytes, cache: Path,
                 limits: InventoryLimits = InventoryLimits()):
        self.reader = ManifestReader(source_root, source_inventory, cache, limits)
        self.snapshot_digest = digest(source_inventory)
        self.licenses = load_license_ids()
        self.limits = limits
        self.dependencies: list[dict] | None = None
        self.component_attribution: dict | None = None
        self.observations = 0

    def observe(self, cargo_output: str, build_root: Path) -> None:
        units = collect_units(cargo_output, build_root, self.limits)
        selected = self.reader.source_root / "tools/toolchain-smoke/Cargo.toml"
        rows = {}
        for unit in units:
            facts = self.reader.package(unit.manifest)
            if unit.role == "component":
                if unit.manifest != selected or facts.name != "latent-toolchain-smoke":
                    raise SnapshotError("observed component has an unexpected source package")
                attribution = {"source": facts.repository or "urn:lsf:workspace:tools/toolchain-smoke/Cargo.toml"}
                license_value = license_expression(facts.license_expression, self.licenses)
                if license_value is not None:
                    attribution["licenseExpression"] = license_value
                if self.component_attribution is not None and self.component_attribution != attribution:
                    raise SnapshotError("component attribution differs between repeated builds")
                self.component_attribution = attribution
                continue
            # The selected root's library and example are represented by the
            # component row. Build-time roles remain separate if ever present.
            if unit.manifest == selected and unit.role == "guest-dependency":
                continue
            row = {"kind": unit.role, "name": facts.name, "version": facts.version,
                   "origin": facts.source_kind, "manifestDigest": facts.manifest_digest,
                   "manifestSize": facts.manifest_size}
            if facts.archive_digest is None:
                relative = portable_path(unit.manifest.relative_to(self.reader.source_root).as_posix())
                row.update(digest=facts.manifest_digest, digestScope="source-manifest",
                           source=facts.repository or "urn:lsf:workspace:" + relative)
            else:
                row.update(digest=facts.archive_digest, digestScope="registry-archive-declared",
                           source=facts.repository or "urn:lsf:registry:crates.io/" + facts.name)
            license_value = license_expression(facts.license_expression, self.licenses)
            if license_value is not None:
                row["licenseExpression"] = license_value
            _text(row["source"], 512)
            key = (row["kind"], row["name"], row["version"], row["source"])
            if key in rows and rows[key] != row:
                raise SnapshotError("conflicting observed dependency attribution")
            rows[key] = row
        normalized = sorted(rows.values(), key=canonical)
        if len(canonical(normalized)) > self.limits.max_document_bytes:
            raise SnapshotError("observed dependency inventory exceeds its byte limit")
        if self.dependencies is not None and normalized != self.dependencies:
            raise SnapshotError("dependency observations differ between repeated builds")
        self.dependencies = normalized
        self.observations += 1
        if self.observations > 2:
            raise SnapshotError("excessive maintained build observations")

    def finish(self, package_root: Path, toolchain: dict, tools: list[dict],
               *, reproducible: bool) -> bytes:
        if (self.dependencies is None or self.component_attribution is None
                or self.observations != (2 if reproducible else 1)):
            raise SnapshotError("dependency inventory lacks its observed build")
        recipe = json.loads(_read(package_root / "package-source.json", package_root), object_pairs_hook=_pairs)
        lock = json.loads(_read(package_root / "wit-lock.json", package_root), object_pairs_hook=_pairs)
        rows = [*self.dependencies]
        wit = {}
        for package in lock["packages"]:
            name = portable_path(_text(package["sourcePath"], 256))
            if name in wit:
                raise SnapshotError("duplicate WIT source inventory path")
            wit[name] = package
        seen = set()
        for layer in recipe["layers"]:
            name = portable_path(_text(layer["path"], 256))
            source = portable_path(_text(layer["source"], 256))
            if name in seen:
                raise SnapshotError("duplicate package inventory path")
            seen.add(name)
            role = layer["role"]
            if role not in ("component", "renderer", "asset"):
                continue
            data = _read(package_root / source, package_root, 64 * 1024 * 1024)
            row = {"kind": role, "name": name, "path": name, "digest": digest(data),
                   "size": len(data), "digestScope": "output-bytes", "origin": "package-input"}
            if role == "component":
                # These are selected-crate declarations. The Cargo version is
                # not substituted for the separately versioned package output.
                row.update(self.component_attribution)
            if name in wit:
                package = wit.pop(name)
                identifier, separator, version = package["id"].rpartition("@")
                if role != "asset" or not separator or row["digest"] != package["digest"]:
                    raise SnapshotError("WIT source inventory association differs")
                row.update(kind="wit-package", name=_text(identifier, 256),
                           version=_text(version, 128), digestScope="wit-source",
                           source="urn:lsf:wit:" + name, origin="captured-source")
            rows.append(row)
        if wit:
            raise SnapshotError("WIT inventory lacks a package source layer")
        for tool in tools:
            name = tool["name"]
            if name not in ("cargo", "rustc", "wasm-tools"):
                raise SnapshotError("unexpected maintained build tool")
            version = toolchain["contracts"]["wasm-tools"] if name == "wasm-tools" else toolchain["rust"]["toolchain"]
            rows.append({"kind": "build-tool", "name": name, "version": _text(version, 128),
                         "source": "urn:lsf:build-tool:" + name, "digest": tool["digest"],
                         "size": tool["size"], "digestScope": "tool-executable", "origin": "toolchain"})
        if len(tools) != 3 or len({tool["name"] for tool in tools}) != 3:
            raise SnapshotError("maintained build tool inventory is incomplete")
        if len(rows) > self.limits.max_units:
            raise SnapshotError("normalized inventory entry limit exceeded")
        self.reader.verify_unchanged()
        result = {"formatVersion": 1, "packageKind": recipe["kind"],
                  "packageName": recipe["name"], "packageVersion": recipe["version"],
                  "dependencyCompleteness": "observed-units-incomplete",
                  "sourceSnapshotDigest": self.snapshot_digest,
                  "entries": sorted(rows, key=canonical)}
        encoded = canonical(result)
        if len(encoded) > self.limits.max_document_bytes:
            raise SnapshotError("normalized inventory exceeds its byte limit")
        return encoded
