"""Fail-closed source overlay for the pinned Go Wasm runtime.

Never edits GOROOT, grants a capability, installs WASI in LSF, or substitutes
entropy. The two syscall entry points reuse the runtime bridge so the standard
library cannot bypass the current invocation's clocks or entropy accounting.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREIMAGES = {
    "runtime/os_wasip1.go": "c8ddc4ddc00af788539897f9a75c814d9c7fcfe9416dbf977f896631c158a3ca",
    "runtime/lock_wasip1.go": "720415791179802557117471740f92cddf4b8a8aa0ebfdba1322bbc621e1f62c",
    "syscall/fs_wasip1.go": "5cf5a98b3361c2d839e084b183366849cd276c9585620f04cc3c75e35a371448",
    "syscall/syscall_wasip1.go": "2017243455e2f7f62bdd0c36040be61af3989b5d96ab81d115d24228657ed1b1",
}


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("go-runtime-overlay-contract-drift")
    return text.replace(old, new, 1)


GO_PACKAGE_RUNTIME_SHA256 = "abff1455a417b51e77e83e01da34fe1048330a9fe0e7d607bb5265f2162eb9b5"


def overlay(goroot: Path, destination: Path, go_package: Path | None = None,
            *, sdk: Path | None = None) -> Path:
    goroot, destination = goroot.resolve(), destination.resolve()
    if (destination == goroot or destination in goroot.parents or goroot in destination.parents
            or destination == ROOT or destination in ROOT.parents
            or (ROOT in destination.parents and not destination.is_relative_to(ROOT / "target"))):
        raise ValueError("go-runtime-overlay-overlaps-protected-source")
    if destination.exists():
        raise ValueError("go-runtime-overlay-requires-fresh-directory")
    sources = {}
    for relative, expected in PREIMAGES.items():
        path = goroot / "src" / relative
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"go-runtime-source-drift:{relative}")
        sources[relative] = data.decode("utf-8")
    text = sources["runtime/os_wasip1.go"]
    for declaration in (
        "func clock_time_get(clock_id clockid, precision timestamp, time *timestamp) errno",
        "func random_get(buf *byte, bufLen size) errno",
    ):
        name = declaration.split("(")[0].removeprefix("func ")
        text = replace_once(text, f"//go:wasmimport wasi_snapshot_preview1 {name}\n//go:noescape\n{declaration}", "")
    sdk = sdk or ROOT / "sdk/go-guest"
    text += "\n" + (sdk / "runtime/runtime_bridge.go.in").read_text(encoding="utf-8")
    sources["runtime/os_wasip1.go"] = text
    for relative, name, declaration in (
        ("syscall/fs_wasip1.go", "random_get", "func random_get(buf *byte, bufLen size) Errno"),
        ("syscall/syscall_wasip1.go", "clock_time_get", "func clock_time_get(id clockid, precision timestamp, time *timestamp) Errno"),
    ):
        old = f"//go:wasmimport wasi_snapshot_preview1 {name}\n//go:noescape\n{declaration}"
        new = f"//go:linkname {name} runtime.{name}\n//go:noescape\n{declaration}"
        sources[relative] = replace_once(sources[relative], old, new)
    dependency_source = None
    if go_package is not None:
        dependency_source = go_package.resolve() / "wit/runtime/runtime.go"
        dependency_bytes = dependency_source.read_bytes()
        if hashlib.sha256(dependency_bytes).hexdigest() != GO_PACKAGE_RUNTIME_SHA256:
            raise ValueError("go-package-runtime-source-drift")
        dependency_text = replace_once(
            dependency_bytes.decode("utf-8"),
            "//go:wasmimport wasi_snapshot_preview1 adapter_monotonic_clock_set_paused",
            "//go:linkname adapterMonotonicClockSetPaused runtime.lsfSetClocksPaused")
    destination.mkdir(parents=True)
    replacements = {}
    if dependency_source is not None:
        target = destination / "go_pkg_runtime.go"
        target.write_text(dependency_text, encoding="utf-8")
        replacements[str(dependency_source)] = str(target)
    for relative, text in sources.items():
        if relative == "runtime/lock_wasip1.go":
            continue  # The upstream async scheduler patch is verified, not modified.
        target = destination / relative.replace("/", "_")
        target.write_text(text, encoding="utf-8")
        replacements[str(goroot / "src" / relative)] = str(target)
    path = destination / "overlay.json"
    path.write_text(json.dumps({"Replace": replacements}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
