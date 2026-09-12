"""Public bounded observations of the selected local build tools and recipe."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil

from tools.build_process import run_bounded
from tools.build_snapshot import SnapshotError, canonical, digest, is_reparse


RECIPE_FILES = (
    "build_provenance.py", "build_observation.py", "build_snapshot.py",
    "build_echo_capsule.py", "build_process.py", "build_process_windows.py", "build_process_linux.py",
    "build_process_signals.py",
    "build_inventory_units.py", "build_inventory_manifests.py", "build_inventory_licenses.py",
    "build_sbom_inputs.py", "data/cyclonedx-1.6/spdx-license-ids.json",
)
MAX_MATERIAL_BYTES = 256 * 1024 * 1024


def public_repository(value: str) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= 512
            or not value.isascii() or not value.startswith("https://")):
        raise SnapshotError("invalid public repository label")
    host, separator, path = value[8:].partition("/")
    labels = host.split(".")
    segments = path.split("/")
    if (not separator or not 1 <= len(host) <= 253
            or any(not 1 <= len(label) <= 63
                   or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                   for label in labels)
            or any(segment in (".", "..")
                   or not re.fullmatch(r"[A-Za-z0-9._-]+", segment) for segment in segments)):
        raise SnapshotError("invalid public repository label")
    return value


def file_identity(path: Path, name: str, maximum: int = MAX_MATERIAL_BYTES) -> dict:
    if is_reparse(path) or not path.is_file():
        raise SnapshotError("build material is not a regular file")
    before = path.stat()
    if not 0 < before.st_size <= maximum:
        raise SnapshotError("build material byte limit exceeded")
    hasher = hashlib.sha256()
    observed = 0
    with path.open("rb") as source:
        while chunk := source.read(min(65536, maximum + 1 - observed)):
            observed += len(chunk)
            if observed > maximum:
                raise SnapshotError("build material byte limit exceeded")
            hasher.update(chunk)
    after = path.stat()
    if (observed != before.st_size or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino):
        raise SnapshotError("build material changed during observation")
    return {"name": name, "digest": "sha256:" + hasher.hexdigest(), "size": observed}


def recipe_identity(tools_root: Path) -> dict:
    rows = []
    for name in RECIPE_FILES:
        record = file_identity(tools_root / name, name, 1024 * 1024)
        rows.append({"path": "tools/" + name, "digest": record["digest"], "size": record["size"]})
    encoded = canonical(sorted(rows, key=lambda row: row["path"]))
    return {"name": "build-recipe", "digest": digest(encoded), "size": len(encoded)}


def build_environment(temporary_root: Path) -> dict[str, str]:
    # Explicit builder host authority. Secrets, wrappers, user flags and arbitrary
    # application environment variables are not inherited by build children.
    approved = {"PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "ComSpec",
                "USERPROFILE", "HOME", "CARGO_HOME", "RUSTUP_HOME", "APPDATA", "LOCALAPPDATA",
                "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
                "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "PROGRAMDATA", "ProgramData",
                "PATHEXT", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}
    result = {key: value for key, value in os.environ.items() if key in approved}
    result.update({"TEMP": str(temporary_root), "TMP": str(temporary_root),
                   "TMPDIR": str(temporary_root), "CARGO_BUILD_JOBS": "2",
                   "CARGO_TERM_COLOR": "never", "LC_ALL": "C", "TZ": "UTC"})
    return result


def _probe(command: list[str], root: Path, environment: dict[str, str]) -> str:
    result = run_bounded(command, cwd=root, env=environment,
                         timeout_seconds=30, max_output_bytes=16 * 1024)
    return result.stdout.decode("utf-8").strip()


def resolve_tools(toolchain: dict, root: Path, environment: dict[str, str]) -> tuple[dict, list[dict]]:
    version = str(toolchain["rust"]["toolchain"])
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise SnapshotError("invalid pinned Rust toolchain")
    rustup = shutil.which("rustup", path=environment.get("PATH"))
    wasm_tools = shutil.which("wasm-tools", path=environment.get("PATH"))
    if not rustup or not wasm_tools:
        raise SnapshotError("required build tools are unavailable")
    paths = {}
    for name in ("cargo", "rustc"):
        selected = _probe([rustup, "which", "--toolchain", version, name], root, environment)
        path = Path(selected)
        if not path.is_absolute() or not path.is_file():
            raise SnapshotError("selected Rust tool is unavailable")
        paths[name] = path.resolve(strict=True)
        reported = _probe([str(paths[name]), "--version"], root, environment)
        if not re.match(rf"{name} {re.escape(version)}(?:\s|$)", reported):
            raise SnapshotError("selected Rust tool version does not match its pin")
    paths["wasm-tools"] = Path(wasm_tools).resolve(strict=True)
    reported = _probe([str(paths["wasm-tools"]), "--version"], root, environment)
    expected = str(toolchain["contracts"]["wasm-tools"])
    if not re.match(rf"wasm-tools {re.escape(expected)}(?:\s|$)", reported):
        raise SnapshotError("selected wasm tool version does not match its pin")
    materials = [file_identity(path, name) for name, path in sorted(paths.items())]
    return paths, materials


def finish_observation(*, repository: str, revision: str, inventory: bytes,
                       component: bytes, materials: list[dict], started: int,
                       finished: int, elapsed: float, reproducible: bool) -> dict:
    if (type(started) is not int or type(finished) is not int or started < 0
            or finished < started or finished - started > 3600 or not 0 <= elapsed <= 3600):
        raise SnapshotError("build observation clock or duration is invalid")
    if not component or len(component) > 64 * 1024 * 1024:
        raise SnapshotError("component output byte limit exceeded")
    materials = [*materials, {"name": "source-snapshot", "digest": digest(inventory), "size": len(inventory)}]
    if len(materials) > 64 or len({item["name"] for item in materials}) != len(materials):
        raise SnapshotError("invalid observed material set")
    result = {
        "formatVersion": 1, "buildType": "https://latent.dev/build/echo-capsule/v1",
        "source": {"repository": public_repository(repository), "revision": revision,
                   "snapshotDigest": digest(inventory), "repositoryTrust": "operator-asserted",
                   "capture": "git-archive-allowlist"},
        "componentDigest": digest(component), "componentSize": len(component),
        "materials": sorted(materials, key=lambda row: row["name"]),
        "parameters": {"cargoPackage": "latent-toolchain-smoke", "cargoExample": "echo-capsule",
                       "target": "wasm32-unknown-unknown", "profile": "release", "locked": True,
                       "incremental": False},
        "startedAt": started, "finishedAt": finished,
        "reproducibility": "two-build-byte-equality" if reproducible else "not-checked",
        "hermetic": False, "dependencyCompleteness": "lockfile-only",
    }
    if len(canonical(result)) > 32768:
        raise SnapshotError("build observation byte limit exceeded")
    return result
