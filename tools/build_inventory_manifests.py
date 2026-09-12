"""Observe bounded declared Cargo attribution without exporting host paths."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tomllib

from tools.build_inventory_units import InventoryLimits, _text
from tools.build_observation import public_repository
from tools.build_snapshot import SnapshotError, digest, is_reparse, owned_child, portable_path


CRATES_IO = "registry+https://github.com/rust-lang/crates.io-index"


@dataclass(frozen=True)
class ManifestFacts:
    name: str
    version: str
    origin: str
    source_kind: str
    manifest_digest: str
    manifest_size: int
    archive_digest: str | None
    repository: str | None
    license_expression: str | None


class ManifestReader:
    """Captured source and explicitly approved registry-cache files only.

    Cache declarations remain observed metadata. Their hashes are separate from
    lock-declared archive identities; no archive verification is implied.
    """
    def __init__(self, source_root: Path, source_inventory: bytes, cargo_home: Path,
                 limits: InventoryLimits = InventoryLimits()):
        limits.validate()
        self.limits = limits
        self.source_root = source_root.resolve(strict=True)
        self.cargo_home = cargo_home.resolve(strict=True)
        if len(source_inventory) > 4 * 1024 * 1024:
            raise SnapshotError("captured source inventory exceeds its byte limit")
        rows = json.loads(source_inventory)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
            raise SnapshotError("invalid captured source inventory")
        self.source_files = {}
        for row in rows:
            if not isinstance(row, dict):
                raise SnapshotError("invalid captured source inventory")
            name = portable_path(row["path"])
            if name in self.source_files:
                raise SnapshotError("duplicate captured source inventory path")
            self.source_files[name] = (row["digest"], row["size"])
        self.observed: dict[Path, tuple[str, int]] = {}
        self.used_bytes = 0
        self.packages: dict[Path, ManifestFacts] = {}
        workspace_data = self._toml(self._read(self.source_root / "Cargo.toml", self.source_root))
        workspace = workspace_data.get("workspace", {})
        if not isinstance(workspace, dict):
            raise SnapshotError("invalid captured workspace attribution")
        self.workspace = workspace.get("package", {})
        if not isinstance(self.workspace, dict):
            raise SnapshotError("invalid captured workspace attribution")
        lock_data = self._toml(self._read(self.source_root / "Cargo.lock", self.source_root,
                                         4 * 1024 * 1024))
        self.lock = lock_data.get("package", [])
        if not isinstance(self.lock, list) or not 1 <= len(self.lock) <= 1024:
            raise SnapshotError("invalid or excessive captured dependency lock entries")
        for package in self.lock:
            if not isinstance(package, dict):
                raise SnapshotError("invalid captured dependency lock entry")

    @staticmethod
    def _toml(data: bytes) -> dict:
        try:
            return tomllib.loads(data.decode("utf-8"))
        except (ValueError, RecursionError) as error:
            raise SnapshotError("invalid observed Cargo metadata") from error

    def _read(self, path: Path, owner: Path, maximum: int | None = None) -> bytes:
        maximum = self.limits.max_manifest_bytes if maximum is None else maximum
        owned_child(path, owner)
        if is_reparse(path) or not path.is_file():
            raise SnapshotError("observed attribution is not a regular file")
        path = path.resolve(strict=True)
        before = path.stat()
        if not 0 < before.st_size <= maximum:
            raise SnapshotError("observed attribution file exceeds its byte limit")
        if path not in self.observed:
            self.used_bytes += before.st_size
            if self.used_bytes > self.limits.max_attribution_bytes:
                raise SnapshotError("observed attribution aggregate byte limit exceeded")
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        after = path.stat()
        if (len(data) != before.st_size or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns or after.st_ino != before.st_ino):
            raise SnapshotError("observed attribution changed during capture")
        identity = (digest(data), len(data))
        if self.source_root in path.parents:
            if self.source_files.get(path.relative_to(self.source_root).as_posix()) != identity:
                raise SnapshotError("observed source attribution differs from captured input")
        previous = self.observed.setdefault(path, identity)
        if previous != identity:
            raise SnapshotError("observed attribution changed during build")
        return data

    def _field(self, package: dict, name: str, local: bool) -> str | None:
        value = package.get(name)
        if isinstance(value, dict):
            if not local or value != {"workspace": True}:
                raise SnapshotError("unsupported Cargo workspace attribution inheritance")
            value = self.workspace.get(name)
        return None if value is None else _text(value, 4096)

    def package(self, manifest: Path) -> ManifestFacts:
        if manifest in self.packages:
            return self.packages[manifest]
        if len(self.packages) >= self.limits.max_packages:
            raise SnapshotError("observed Cargo package limit exceeded")
        if not manifest.is_absolute() or manifest.name != "Cargo.toml":
            raise SnapshotError("invalid observed Cargo manifest path")
        local = self.source_root in manifest.parents
        if local:
            owner = self.source_root
            relative = portable_path(manifest.relative_to(owner).as_posix())
            origin = "captured-source:" + relative
        else:
            try:
                parts = manifest.relative_to(self.cargo_home).parts
            except ValueError as error:
                raise SnapshotError("observed Cargo manifest is outside approved roots") from error
            if len(parts) != 5 or parts[:2] != ("registry", "src"):
                raise SnapshotError("unsupported observed Cargo source kind")
            portable_path("/".join(parts))
            owner = manifest.parent
            # Check links all the way from the caller-approved Cargo home, not
            # merely from the package directory which might itself be a link.
            owned_child(manifest, self.cargo_home)
            origin = "cargo-registry:" + CRATES_IO
        data = self._read(manifest, owner)
        package = self._toml(data).get("package")
        if not isinstance(package, dict):
            raise SnapshotError("observed Cargo manifest lacks its package")
        name = self._field(package, "name", local)
        version = self._field(package, "version", local)
        if (name is None or version is None or not name.isascii() or not version.isascii()
                or len(name) > 128 or len(version) > 128):
            raise SnapshotError("invalid observed Cargo package identity")
        candidates = [row for row in self.lock if row.get("name") == name and row.get("version") == version]
        if len(candidates) != 1:
            raise SnapshotError("ambiguous or missing observed Cargo lock identity")
        locked = candidates[0]
        archive_digest = None
        if local:
            if locked.get("source") is not None or locked.get("checksum") is not None:
                raise SnapshotError("observed local package conflicts with lock source")
        else:
            if locked.get("source") != CRATES_IO or manifest.parent.name != f"{name}-{version}":
                raise SnapshotError("observed registry package conflicts with lock source")
            checksum = locked.get("checksum")
            if (not isinstance(checksum, str) or len(checksum) != 64
                    or any(character not in "0123456789abcdef" for character in checksum)):
                raise SnapshotError("observed registry package lacks its declared archive digest")
            archive_digest = "sha256:" + checksum
        repository = self._field(package, "repository", local)
        if repository is not None:
            try:
                public_repository(repository)
            except SnapshotError:
                repository = None
        license_expression = self._field(package, "license", local)
        # A license-file declaration is not an SPDX expression. It remains
        # represented only by the observed manifest hash; no file is followed.
        result = ManifestFacts(name, version, origin, "captured-source" if local else "observed-cache",
            digest(data), len(data), archive_digest, repository, license_expression)
        self.packages[manifest] = result
        return result

    def verify_unchanged(self) -> None:
        for path, expected in tuple(self.observed.items()):
            owner = self.source_root if self.source_root in path.parents else self.cargo_home
            maximum = 4 * 1024 * 1024 if path == self.source_root / "Cargo.lock" else self.limits.max_manifest_bytes
            if (digest(self._read(path, owner, maximum)), path.stat().st_size) != expected:
                raise SnapshotError("observed attribution changed during build")
