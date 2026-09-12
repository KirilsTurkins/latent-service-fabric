"""Bounded unit roles from the maintained build's already captured Cargo JSON."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from tools.build_snapshot import SnapshotError, owned_child


@dataclass(frozen=True)
class InventoryLimits:
    max_units: int = 1024
    max_packages: int = 512
    max_record_bytes: int = 64 * 1024
    max_manifest_bytes: int = 256 * 1024
    max_attribution_bytes: int = 8 * 1024 * 1024
    max_document_bytes: int = 256 * 1024

    def validate(self) -> None:
        hard = InventoryLimits()
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= getattr(hard, name):
                raise SnapshotError("invalid dependency inventory limits")


@dataclass(frozen=True)
class CargoUnit:
    package_id: str
    manifest: Path
    role: str
    target_name: str


def _text(value: object, maximum: int = 4096) -> str:
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise SnapshotError("invalid captured Cargo identity")
    return value


def _strings(value: object, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise SnapshotError("invalid captured Cargo list")
    values = tuple(_text(item, 16384) for item in value)
    if len(set(values)) != len(values):
        raise SnapshotError("duplicate captured Cargo list entry")
    return values


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise SnapshotError("duplicate captured Cargo JSON field")
        result[key] = value
    return result


def collect_units(output: str, build_root: Path, limits: InventoryLimits = InventoryLimits()) -> tuple[CargoUnit, ...]:
    """Private paths remain local join/ownership data and must never be exported."""
    limits.validate()
    if not isinstance(output, str) or len(output.encode("utf-8")) > 8 * 1024 * 1024:
        raise SnapshotError("captured Cargo output exceeds its byte limit")
    build_root = build_root.resolve(strict=True)
    units: set[CargoUnit] = set()
    packages: dict[str, Path] = {}
    finished = False
    observed = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > limits.max_record_bytes:
            raise SnapshotError("captured Cargo record exceeds its byte limit")
        try:
            record = json.loads(line, object_pairs_hook=_pairs)
        except (ValueError, RecursionError) as error:
            raise SnapshotError("invalid captured Cargo JSON") from error
        if not isinstance(record, dict):
            raise SnapshotError("invalid captured Cargo record")
        reason = record.get("reason")
        if reason == "build-finished":
            if finished or record.get("success") is not True:
                raise SnapshotError("captured Cargo build did not finish successfully")
            finished = True
            continue
        if reason != "compiler-artifact":
            continue
        if finished:
            raise SnapshotError("captured Cargo artifact follows completion")
        observed += 1
        if observed > limits.max_units:
            raise SnapshotError("captured Cargo unit limit exceeded")
        identity = _text(record.get("package_id"), 16384)
        manifest = Path(_text(record.get("manifest_path"), 16384))
        if not manifest.is_absolute() or manifest.name != "Cargo.toml":
            raise SnapshotError("invalid captured Cargo manifest path")
        previous = packages.setdefault(identity, manifest)
        if previous != manifest or len(packages) > limits.max_packages:
            raise SnapshotError("conflicting or excessive captured Cargo packages")
        target = record.get("target")
        if not isinstance(target, dict):
            raise SnapshotError("invalid captured Cargo target")
        kinds = _strings(target.get("kind"), 8)
        crate_types = _strings(target.get("crate_types"), 8)
        name = _text(target.get("name"), 128)
        domains = set()
        for filename in _strings(record.get("filenames"), 16):
            artifact = Path(filename)
            if not artifact.is_absolute():
                raise SnapshotError("captured Cargo output path is not absolute")
            owned_child(artifact, build_root)
            relative = artifact.relative_to(build_root).parts
            if len(relative) >= 3 and relative[:2] == ("wasm32-unknown-unknown", "release"):
                domains.add("guest")
            elif len(relative) >= 2 and relative[0] == "release":
                domains.add("host")
            else:
                raise SnapshotError("captured Cargo output has an unsupported target domain")
        if len(domains) != 1:
            raise SnapshotError("captured Cargo unit mixes host and guest outputs")
        domain = next(iter(domains))
        if kinds == ("custom-build",):
            role = "build-script"
            if domain != "host":
                raise SnapshotError("build script was reported as a guest unit")
        elif "proc-macro" in kinds or "proc-macro" in crate_types:
            role = "proc-macro"
            if domain != "host":
                raise SnapshotError("procedural macro was reported as a guest unit")
        elif kinds == ("example",):
            if name != "echo-capsule" or domain != "guest":
                raise SnapshotError("captured Cargo example is outside the maintained recipe")
            role = "component"
        elif set(kinds) <= {"lib", "rlib", "dylib", "cdylib", "staticlib"}:
            role = "guest-dependency" if domain == "guest" else "build-dependency"
        else:
            raise SnapshotError("captured Cargo unit kind is unsupported")
        units.add(CargoUnit(identity, manifest, role, name))
    if not finished or not any(unit.role == "component" for unit in units):
        raise SnapshotError("captured Cargo build lacks its selected component")
    return tuple(sorted(units, key=lambda unit: (unit.package_id, unit.role, unit.target_name)))
