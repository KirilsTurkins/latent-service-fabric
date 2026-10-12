"""Fail-closed source overlay for the pinned Go Wasm runtime.

Never edits GOROOT, grants a capability, installs WASI in LSF, or substitutes
entropy. The two syscall entry points reuse the runtime bridge so the standard
library cannot bypass the current invocation's clocks or entropy accounting.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_PREIMAGES = {
    "runtime/os_wasip1.go": "c8ddc4ddc00af788539897f9a75c814d9c7fcfe9416dbf977f896631c158a3ca",
    "runtime/lock_wasip1.go": "946dfcba88ee68b89cb936a12a9a60a82f451ba915eef6e0708791cc4fc2981c",
    "syscall/fs_wasip1.go": "5cf5a98b3361c2d839e084b183366849cd276c9585620f04cc3c75e35a371448",
    "syscall/syscall_wasip1.go": "2017243455e2f7f62bdd0c36040be61af3989b5d96ab81d115d24228657ed1b1",
    "runtime/lock_futex.go": "c411429c46c093a5214ceebb3557f66de31056826fc2ab234ebfae70c0a2efb5",
    "runtime/lock_js.go": "b354c0bdb9ac4bbc7ba52361653e81768324a147fca6d3ea42c19e6e3abf1ab6",
    "runtime/lock_sema.go": "75d2a07f05071f1537a1fad231e3397ae33ebac5026c66d09959b7c898f1ea5c",
    "runtime/proc.go": "40d15ce858cf058cff92606001a29ee1689db88c121a2f0c283163a0d64a7375",
}
PREIMAGES = {**UPSTREAM_PREIMAGES,
    "runtime/lock_wasip1.go": "720415791179802557117471740f92cddf4b8a8aa0ebfdba1322bbc621e1f62c",
    "runtime/lock_futex.go": "b0f86c66fc0598546c54e4db32d9e1479b77e66e67539872870fe41a3d413798",
    "runtime/lock_js.go": "32537875a1bae14517f33ca4fa5cb37daa4fb375da655a534d9e8dc6da3dbed8",
    "runtime/lock_sema.go": "284889789238c412c9f2e2c99e10912641fac591523a462659c9ec49ab905239",
    "runtime/proc.go": "64e0822a2f8b8a6ed6e764e5c0f224b392e3a1343a328d30d7b34441ae7c9cef",
}


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("go-runtime-overlay-contract-drift")
    return text.replace(old, new, 1)


GO_PACKAGE_RUNTIME_SHA256 = "abff1455a417b51e77e83e01da34fe1048330a9fe0e7d607bb5265f2162eb9b5"


def checked_roots(goroot: Path, destination: Path) -> tuple[Path, Path]:
    goroot, destination = goroot.resolve(), destination.resolve()
    if (destination == goroot or destination in goroot.parents or goroot in destination.parents
            or destination == ROOT or destination in ROOT.parents
            or (ROOT in destination.parents and not destination.is_relative_to(ROOT / "target"))):
        raise ValueError("go-runtime-overlay-overlaps-protected-source")
    if destination.exists():
        raise ValueError("go-runtime-overlay-requires-fresh-directory")
    return goroot, destination


def checked_sources(goroot: Path, contracts: dict[str, str]) -> dict[str, str]:
    sources = {}
    for relative, expected in contracts.items():
        path = goroot / "src" / relative
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"go-runtime-source-drift:{relative}")
        sources[relative] = data.decode("utf-8")
    return sources


def install_scheduler(sources: dict[str, str]) -> None:
    # Preserve dicej/go's reviewed 676a047d wasiOnIdle scheduler hook on the
    # exact patched upstream toolchain. GOROOT stays immutable; all five source
    # changes are supplied through the same captured compiler overlay.
    for relative in ("runtime/lock_futex.go", "runtime/lock_sema.go"):
        sources[relative] = replace_once(sources[relative],
            "func beforeIdle(int64, int64) (*g, bool)",
            "func beforeIdle(int64, int64, bool) (*g, bool)")
    sources["runtime/lock_js.go"] = replace_once(sources["runtime/lock_js.go"],
        "func beforeIdle(now, pollUntil int64) (gp *g, otherReady bool)",
        "func beforeIdle(now, pollUntil int64, netWaiters bool) (gp *g, otherReady bool)")
    sources["runtime/lock_wasip1.go"] = replace_once(sources["runtime/lock_wasip1.go"],
        "func beforeIdle(int64, int64) (*g, bool) {\n\treturn nil, false\n}",
        "var onIdle = func() bool {\n\treturn false\n}\n\n"
        "func wasiOnIdle(callback func() bool) {\n\tonIdle = callback\n}\n\n"
        "func beforeIdle(now int64, pollUntil int64, netWaiters bool) (*g, bool) {\n"
        "\treturn nil, !netWaiters && onIdle()\n}")
    sources["runtime/proc.go"] = replace_once(sources["runtime/proc.go"],
        "beforeIdle(now, pollUntil)",
        "beforeIdle(now, pollUntil, netpollinited() && netpollAnyWaiters())")


def scheduler_overlay(goroot: Path, destination: Path) -> Path:
    """The upstream WASI comparison gets the same async scheduler, without LSF imports."""
    goroot, destination = checked_roots(goroot, destination)
    contracts = {name: sha for name, sha in PREIMAGES.items()
                 if name.startswith("runtime/lock_") or name == "runtime/proc.go"}
    sources = checked_sources(goroot, contracts)
    destination.mkdir(parents=True)
    replacements = {}
    for relative, text in sources.items():
        target = destination / relative.replace("/", "_")
        target.write_text(text, encoding="utf-8")
        replacements[str(goroot / "src" / relative)] = str(target)
    path = destination / "overlay.json"
    path.write_text(json.dumps({"Replace": replacements}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def prepare_compiler(goroot: Path, destination: Path) -> Path:
    """Assemble one fresh private async toolchain; never edit the upstream input."""
    goroot, destination = checked_roots(goroot, destination)
    if (goroot / "VERSION").read_text().splitlines()[0] != "go1.27.2":
        raise ValueError("go-async-compiler-version-drift")
    sources = checked_sources(goroot, UPSTREAM_PREIMAGES)
    install_scheduler(sources)
    if any(hashlib.sha256(text.encode()).hexdigest() != PREIMAGES[name]
           for name, text in sources.items()):
        raise ValueError("go-async-compiler-postimage-drift")
    shutil.copytree(goroot, destination, ignore=shutil.ignore_patterns("testdata", "*_test.go", ".git"))
    for relative, text in sources.items():
        if UPSTREAM_PREIMAGES[relative] != PREIMAGES[relative]:
            (destination / "src" / relative).write_text(text, encoding="utf-8", newline="\n")
    checked_sources(destination, PREIMAGES)
    return destination


def overlay(goroot: Path, destination: Path, go_package: Path | None = None,
            *, sdk: Path | None = None) -> Path:
    goroot, destination = checked_roots(goroot, destination)
    sources = checked_sources(goroot, PREIMAGES)
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
        target = destination / relative.replace("/", "_")
        target.write_text(text, encoding="utf-8")
        replacements[str(goroot / "src" / relative)] = str(target)
    path = destination / "overlay.json"
    path.write_text(json.dumps({"Replace": replacements}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Stage the verified Go 1.27.2 async compiler profile")
    parser.add_argument("--prepare-compiler", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare_compiler(args.prepare_compiler, args.output)
