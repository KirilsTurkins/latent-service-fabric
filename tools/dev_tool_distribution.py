"""Stage language-owned SDK recipes, pinned tools and maintained templates."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tarfile
import tomllib

from tools import c_capsule_build, c_capsule_project, java_capsule_build, java_capsule_project, rust_capsule_build, rust_capsule_project
from tools.dotnet_guest import build as dotnet_build, project as dotnet_project
from tools import go_capsule_build, go_capsule_project
from tools.typescript_guest import build as typescript_build, project as typescript_project
from tools.dev_distribution import file_digest
from tools.dev_workflow import paths, project, scenarios, snapshot, tool_inventory
from tools.dev_workflow.common import HOST_ABI, digest, encode, require
from tools.install_guest_bindgen import ARCHIVE_SHA256, VERSION as BINDGEN_VERSION
from tools.rust_capsule_cases import TUTORIAL_CASES

ROOT = Path(__file__).resolve().parents[1]
WASM_VERSION = "1.254.0"
WASM_SHA256 = "d0efb16c9c859137b7ab3e99151c299cd47caee106ed4594561002f7a04945bd"
RUST_VERSION = "1.97.1"


def copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not destination.exists(), "tool-distribution-file-collision")
    shutil.copyfile(source, destination)


def binary_archive(archive: Path, payload: Path, name: str, checksum: str) -> set[str]:
    require(file_digest(archive)[0] == "sha256:" + checksum, "compiler-upstream-archive-digest")
    observed, binary = set(), False
    with tarfile.open(archive, "r:gz") as source:
        for ordinal, member in enumerate(source):
            require(ordinal < 32 and member.size <= 64 * 1024 * 1024, "compiler-upstream-archive-limit")
            if member.isdir():
                continue
            require(member.isfile(), "compiler-upstream-archive-type")
            filename = Path(member.name).name
            if filename == name:
                destination = payload / "sdk/bin" / name
                binary = True
            elif filename.startswith("LICENSE"):
                destination = payload / "licenses" / name / paths.relative(filename)
            else:
                continue
            require(destination not in observed, "compiler-upstream-archive-alias")
            observed.add(destination)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with source.extractfile(member) as data, destination.open("xb") as output:
                shutil.copyfileobj(data, output, length=1024 * 1024)
    require(binary and len(observed) > 1, "compiler-upstream-binary-and-license-required")
    return {"sdk/bin/" + name}


def rust(payload: Path, rustup_home: Path) -> set[str]:
    name = RUST_VERSION + "-x86_64-unknown-linux-gnu"
    source, destination = rustup_home / "toolchains" / name, payload / "sdk/rust"
    shutil.copytree(source / "lib", destination / "lib")
    executables = set()
    for name in ("cargo", "rustc"):
        copy(source / "bin" / name, destination / "bin" / name)
        executables.add((destination / "bin" / name).relative_to(payload).as_posix())
    for path in (destination / "lib/rustlib").glob("*/bin/*"):
        if path.is_file() and os.access(path, os.X_OK):
            executables.add(path.relative_to(payload).as_posix())
    for name in ("COPYRIGHT.html", "COPYRIGHT-library.html"):
        copy(source / "share/doc/rust" / name, payload / "licenses/rust" / name)
    shutil.copytree(source / "share/doc/rust/licenses", payload / "licenses/rust/terms")
    return executables


def python(payload: Path, prefix: Path) -> set[str]:
    require((prefix / "lib/python3.13/os.py").is_file(), "cpython-prefix-required")
    copy(prefix / "bin/python3.13", payload / "sdk/python/bin/python3.13")
    for name in ("libpython3.so", "libpython3.13.so.1.0"):
        copy(prefix / "lib" / name, payload / "sdk/python/lib" / name)
    shutil.copytree(prefix / "lib/python3.13", payload / "sdk/python/lib/python3.13",
        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip"))
    copy(prefix / "lib/python3.13/LICENSE.txt", payload / "licenses/CPython-3.13.5.txt")
    launcher = payload / "sdk/bin/python"
    launcher.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    launcher.write_text('#!/bin/sh\nbase="${0%/*}/../python"\nLD_LIBRARY_PATH="$base/lib" '
        'exec "$base/bin/python3.13" "$@"\n', encoding="utf-8")
    return {"sdk/bin/python", "sdk/python/bin/python3.13"}


def registry(payload: Path, cargo_home: Path) -> None:
    packages = tomllib.loads((ROOT / "tools/rust_capsule.lock").read_text())["package"]
    indexes = list((cargo_home / "registry/index").glob("index.crates.io-*"))
    require(len(indexes) == 1, "one-explicit-cargo-registry-required")
    index = indexes[0]
    copy(index / "config.json", payload / "sdk/registry/index" / index.name / "config.json")
    recorded = set()
    for package in packages:
        if "source" not in package:
            continue
        require(package["source"] == "registry+https://github.com/rust-lang/crates.io-index", "unreviewed-registry-source")
        name, version = package["name"], package["version"]
        source = cargo_home / "registry/cache" / index.name / (name + "-" + version + ".crate")
        require(file_digest(source)[0] == "sha256:" + package["checksum"], "compiler-dependency-lock-checksum")
        copy(source, payload / "sdk/registry/cache" / index.name / source.name)
        segment = name[:2] + "/" + name[2:4] if len(name) >= 4 else "3/" + name[0] if len(name) == 3 else str(len(name))
        relative = segment + "/" + name
        if name not in recorded:
            copy(index / ".cache" / relative, payload / "sdk/registry/index" / index.name / ".cache" / relative)
            recorded.add(name)


def recipe(payload: Path, language: str) -> None:
    owner = {"rust": rust_capsule_build, "c": c_capsule_build, "java": java_capsule_build,
             "dotnet": dotnet_build, "go": go_capsule_build, "typescript": typescript_build}[language]
    names = {*owner.RECIPE, "tools/dev_guest_recipe.py", "tools/dev_guest_tools.py",
             "tools/dev_workflow/__init__.py", "tools/dev_workflow/common.py", "tools/dev_workflow/paths.py",
             "examples/echo-contract/capsule.json", "examples/echo-contract/deployment.json"}
    if language in {"java", "dotnet", "go", "typescript"}:
        names.add("tools/dev_managed_tools.py")
    for name in sorted(names):
        copy(ROOT / name, payload / "recipe" / name)
    (payload / "recipe/tools/__init__.py").write_bytes(b"")


def compiler_inventory(payload: Path, commit: str, language: str) -> dict:
    files = []
    for directory in (payload / "sdk", payload / "recipe"):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                sha, size = file_digest(path)
                files.append({"path": path.relative_to(payload).as_posix(), "sha256": sha, "size": size})
    value = {"schemaVersion": "latent.dev.guest-tools.v1", "language": language, "ownerIssue": project.LANGUAGES[language],
        "sourceCommit": commit, "hostAbi": HOST_ABI, "host": "linux-x86_64", "files": files}
    value["identity"] = digest(encode(value))
    tool_inventory.validate(value, language, project.LANGUAGES[language], "linux-x86_64")
    (payload / "guest-tools.json").write_bytes(encode(value))
    return value


def templates(payload: Path, commit: str, language: str) -> dict:
    creator = {"rust": rust_capsule_project, "c": c_capsule_project, "java": java_capsule_project,
               "dotnet": dotnet_project, "go": go_capsule_project, "typescript": typescript_project}[language]
    tools = [("python", "sdk/bin/python", "3.13.5"), ("recipe", "recipe/tools/dev_guest_recipe.py", "1"),
             ("contracts", "sdk/bin/capsule-contracts", commit),
             ("wasm-tools", "sdk/bin/wasm-tools", WASM_VERSION), ("wit-bindgen", "sdk/bin/wit-bindgen", BINDGEN_VERSION)]
    if language == "rust":
        tools.extend([("cargo", "sdk/rust/bin/cargo", RUST_VERSION), ("rustc", "sdk/rust/bin/rustc", RUST_VERSION)])
    pins = [{"name": name, "path": path, "version": version, "sha256": file_digest(payload / path)[0]}
            for name, path, version in tools]
    selected = {"path": "guest-tools.json", "sha256": file_digest(payload / "guest-tools.json")[0]}
    result = {}
    for name, (function, cases) in TUTORIAL_CASES.items():
        directory = payload / "templates" / language / name
        directory.mkdir(mode=0o700, parents=True)
        app = creator.create(directory / "app", name)
        owner = json.loads((app / "capsule-project.json").read_bytes())
        (directory / "tests").mkdir(mode=0o700)
        entries = []
        for ordinal, (arguments, expected, code) in enumerate(cases):
            for kind, value in (("input", arguments), ("expected", expected)):
                (directory / "tests" / f"{ordinal}-{kind}.json").write_bytes(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
            entries.append({"id": name + "-" + str(ordinal), "service": owner["service"],
                "contract": f"examples:{name}/api@1.0.0", "function": function,
                "input": f"tests/{ordinal}-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                "expect": {"category": "success" if code == 0 else "declared-error", "payload": f"tests/{ordinal}-expected.json"},
                "requires": [], "timeoutMillis": 5000, "required": True, "fixtures": []})
            if language in {"java", "dotnet", "go"}:
                # These capabilities are declared by the maintained language
                # runtime. A node still requires explicit operator policy.
                clocks = ["latent:clock/monotonic@0.1.0"]
                if language in {"java", "go"}:
                    clocks.append("latent:clock/wall@0.1.0")
                if language == "go":
                    clocks.append("latent:random/random@0.1.0")
                entries[-1].update(requires=["clock"], execution={"grants": clocks})
                if language == "go":
                    entries[-1]["requires"].append("random")
        document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": entries}
        scenarios.validate(document, "node")
        (directory / "tests/scenarios.json").write_bytes(encode(document))
        record, _ = snapshot.observe(directory, ["app", "tests"])
        descriptor = {"schemaVersion": "latent.dev.project.v1", "name": owner["name"], "tenant": owner["tenant"],
            "service": owner["service"], "language": language, "hostAbi": HOST_ABI,
            "template": {"ownerIssue": project.LANGUAGES[language], "revision": commit, "sha256": record["identity"]},
            "inputRoots": ["app", "tests"], "exclude": [],
            "build": {"argv": ["python", "-I", "-B", "@tool:recipe", "--language", language, "--project", ".", "--output", "../output"],
                "workingDirectory": "app", "outputRoot": "output", "target": "wasm-component",
                "hostTargets": ["linux-x86_64"], "timeoutSeconds": 900, "maximumOutputBytes": 262144,
                "tools": pins, "inventory": selected, "adapter": {"language": language, "ownerIssue": project.LANGUAGES[language], "version": "1"}},
            "artifacts": {"component": "output/component.wasm", "capsule": "output/capsule.json",
                "contracts": "output/contracts.json", "deployment": "output/deployment.json",
                "packageSource": "output/package-source.json", "packageRoot": "output/package",
                "evidence": "output/build-observation.json"}, "scenarios": ["tests/scenarios.json"]}
        project.validate(descriptor)
        manifest = {"schemaVersion": "latent.dev.template.v1", "project": descriptor, "snapshot": record}
        (directory / "template.json").write_bytes(encode(manifest))
        result[name] = {"path": directory.relative_to(payload).as_posix(), "identity": digest(encode(manifest))}
    (payload / "templates.json").write_bytes(encode({"schemaVersion": "latent.dev.templates.v1", "templates": result}))
    return result
