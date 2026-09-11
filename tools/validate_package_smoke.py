#!/usr/bin/env python3
"""Package and inspect small real inputs without compiling or invoking a guest."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target"))
if not TARGET.is_absolute():
    TARGET = ROOT / TARGET


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def copy_input(source: Path, target: Path, maximum: int) -> bytes:
    with source.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise RuntimeError(f"smoke input exceeds {maximum} bytes: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def echo_recipe(directory: Path) -> Path:
    directory.mkdir()
    selections = [
        (TARGET / "capsules/echo/echo-capsule.wasm", "component.wasm", "component", "application/wasm", 64 * 1024 * 1024),
        (ROOT / "examples/echo-contract/capsule.json", "capsule.json", "capsule-manifest", "application/vnd.latent.capsule.manifest.v1+json", 256 * 1024),
        (ROOT / "examples/echo-contract/contracts.json", "contracts.json", "contracts", "application/vnd.latent.contracts.v1+json", 256 * 1024),
    ]
    layers = []
    contracts = b""
    component_digest = ""
    for source, name, role, media_type, maximum in selections:
        data = copy_input(source, directory / name, maximum)
        if role == "contracts":
            contracts = data
        if role == "component":
            component_digest = digest(data)
        if role == "capsule-manifest":
            manifest = json.loads(data)
            manifest["component"]["digest"] = component_digest
            (directory / name).write_text(json.dumps(manifest), encoding="utf-8")
        layers.append({"path": name, "source": name, "role": role, "mediaType": media_type})
    packages = []
    for identity, name, source, dependencies in [
        ("examples:echo@0.1.0", "wit/echo.wit", "examples/echo-contract/wit/echo.wit", ["latent:context@0.1.0", "latent:log@0.1.0"]),
        ("latent:context@0.1.0", "wit/context.wit", "wit/platform/context/package.wit", []),
        ("latent:log@0.1.0", "wit/log.wit", "wit/platform/log/package.wit", []),
    ]:
        data = copy_input(ROOT / source, directory / name, 256 * 1024)
        layers.append({"path": name, "source": name, "role": "asset", "mediaType": "text/plain"})
        packages.append({"id": identity, "sourcePath": name, "digest": digest(data), "dependencies": dependencies})
    lock = {"formatVersion": 1, "world": "examples:echo/service@0.1.0", "contractsDigest": digest(contracts), "packages": packages}
    (directory / "wit-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    layers.append({"path": "wit-lock.json", "source": "wit-lock.json", "role": "wit-lock", "mediaType": "application/vnd.latent.wit-lock.v1+json"})
    recipe = {"formatVersion": 1, "kind": "capsule", "name": "echo-smoke", "version": "0.1.0", "entrypoint": "component.wasm", "annotations": {}, "layers": layers}
    path = directory / "package-source.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    return path


def invoke(executable: Path, *arguments: str | Path) -> dict:
    result = subprocess.run([str(executable), *map(str, arguments)], cwd=ROOT,
                            check=False, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"package smoke command failed: {result.stderr[:4096]}")
    return json.loads(result.stdout)


def main() -> None:
    subprocess.run(["cargo", "build", "-p", "latent-packaging", "--example", "package", "--locked"],
                   cwd=ROOT, check=True, timeout=600)
    executable = TARGET / "debug/examples" / ("package.exe" if os.name == "nt" else "package")
    if not executable.is_file():
        raise RuntimeError("package example executable missing")
    # All smoke packages disappear with this scope, including on a failed command.
    with tempfile.TemporaryDirectory(prefix="lsf-package-smoke-") as temporary:
        output = Path(temporary)
        echo = echo_recipe(output / "echo-input")
        fixtures = [("echo", echo, echo.parent)]
        fixtures.extend((kind, ROOT / f"examples/package-inputs/{kind}/package-source.json",
                         ROOT / f"examples/package-inputs/{kind}") for kind in ("browser", "ssr"))
        for name, recipe, input_root in fixtures:
            first = invoke(executable, "build", recipe, input_root, output / f"{name}-a")
            second = invoke(executable, "build", recipe, input_root, output / f"{name}-b")
            inspected = invoke(executable, "inspect", output / f"{name}-a")
            if first != second or first != inspected:
                raise RuntimeError(f"{name} package build/inspect identity diverged")
            print(f"{name}: {first['packageDigest']} ({first['layers']} layers)")


if __name__ == "__main__":
    main()
