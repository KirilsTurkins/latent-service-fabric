"""Capture the maintained Go compiler, generator, module cache and notices."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tomllib

from tools import native_runtime_build
from tools.build_observation import build_environment
from tools.dev_distribution import file_digest
from tools.dev_managed_distribution import extract, pack
from tools.dev_workflow.common import encode, require
from tools.rust_capsule_build import Commands

ROOT = Path(__file__).resolve().parents[1]
REVISION = "148dba505f8c6c64ad84db777cfde5e34e25098b"
SOURCES = {
    "go": {"url": "https://github.com/dicej/go/releases/download/go1.27.1-wasi-on-idle/go-linux-amd64-bootstrap.tbz",
        "version": "go1.27.1-wasi-on-idle", "maximum": 63536422,
        "sha256": "sha256:4b4fcbbab5b5b0a45433112aa51c64a54007b24f1efd05b67018ca2cf8633e2c"},
    "componentize-go": {"url": "https://github.com/bytecodealliance/componentize-go/releases/download/v0.4.3/componentize-go-linux-amd64.tar.gz",
        "version": "0.4.3", "maximum": 5068079,
        "sha256": "sha256:1061d845f550df5d9477612a7d458a31b1e2b8bdc95823704e42e5064deb0c52"},
    "componentize-go-source": {"url": "https://codeload.github.com/bytecodealliance/componentize-go/tar.gz/" + REVISION,
        "version": REVISION, "maximum": 136067,
        "sha256": "sha256:a664d9c56573015552b21b9ce753ba16797b3e33dfb31140620dbb950d8310c8"},
}


def generator_inventory(source: Path, commands: Commands, payload: Path, epoch: int) -> dict:
    metadata = json.loads(commands.run("generator-dependency-metadata", "cargo", "metadata", "--locked", "--format-version", "1",
        "--filter-platform", "x86_64-unknown-linux-gnu", "--manifest-path", source / "Cargo.toml"))
    sbom, licenses = native_runtime_build.dependency_inventory(metadata,
        tomllib.loads((source / "Cargo.lock").read_text()), REVISION, epoch,
        json.loads((ROOT / "packaging/linux/license-sources.json").read_bytes()), root_names=frozenset({"componentize-go"}))
    packages = {(item["name"], item["version"]): item for item in metadata["packages"]}
    for item in sbom["packages"]:
        package = packages[(item["name"], item["versionInfo"])]
        origin = package.get("source")
        if origin and origin.startswith("registry+"):
            continue
        if origin is None:
            require(package["name"] == "componentize-go", "unexpected-generator-workspace-package")
            checkout = source
            item["downloadLocation"] = "git+https://github.com/bytecodealliance/componentize-go@" + REVISION
        else:
            require(origin.startswith("git+https://github.com/bytecodealliance/wit-bindgen?")
                and origin.endswith("#4f9a02d74cec9257c14ba9b160fa787a3523fd0b"), "unreviewed-generator-git-dependency")
            directory = Path(package["manifest_path"]).parent
            checkout = Path(commands.run("generator-license-root", "git", "-C", directory, "rev-parse", "--show-toplevel").decode().strip())
            observed = commands.run("generator-license-revision", "git", "-C", checkout, "rev-parse", "HEAD").decode().strip()
            require(observed == origin.rsplit("#", 1)[1], "generator-license-source-revision")
            item["downloadLocation"] = origin
        notices = [path for path in checkout.iterdir() if path.is_file() and not path.is_symlink()
                   and path.name.upper().startswith(("LICENSE", "LICENCE", "NOTICE", "COPYING"))]
        require(notices, "generator-source-license-required")
        for path in notices:
            licenses[f"licenses/{package['name']}-{package['version']}/{path.name}"] = path
    for name, source_file in licenses.items():
        destination = payload / "licenses/go-generator" / name.removeprefix("licenses/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, destination)
    return sbom


def prepare(payload: Path, output: Path, download, epoch: int) -> dict:
    pins = json.loads((ROOT / "sdk/go-guest/toolchain.lock.json").read_bytes())
    require(pins["componentizeGo"]["revision"] == REVISION
        and SOURCES["go"]["sha256"] == "sha256:" + pins["go"]["linuxAmd64"]["sha256"], "Go-owner-pin-drift")
    for name, source in SOURCES.items():
        download(output / (name + ".archive"), source)
    original = extract(output / "go.archive", output / "go-source", "go", source=SOURCES["go"])
    source = extract(output / "componentize-go-source.archive", output / "generator-source", "componentize-go-source",
                     source=SOURCES["componentize-go-source"])
    generator = output / "generator"
    (generator / "bin").mkdir(parents=True)
    archive = output / "componentize-go.archive"
    require(file_digest(archive)[0] == SOURCES["componentize-go"]["sha256"], "generator-upstream-digest")
    with tarfile.open(archive, "r:gz") as package:
        entries = package.getmembers()
        require(len(entries) == 1 and entries[0].name == "componentize-go" and entries[0].isfile()
            and entries[0].size <= 32 * 1024 * 1024, "generator-archive-entry")
        with package.extractfile(entries[0]) as incoming, (generator / "bin/componentize-go").open("xb") as target:
            shutil.copyfileobj(incoming, target, 1024 * 1024)
    (generator / "bin/componentize-go").chmod(0o700)
    # Compiler and standard-library sources are needed; upstream regression test
    # fixtures are not compiler inputs and may intentionally use invalid names.
    go = output / "go-tools"
    shutil.copytree(original, go, ignore=shutil.ignore_patterns("testdata", "*_test.go", ".git"))
    workspace = output / "go-dependencies"
    workspace.mkdir()
    module = workspace / "project"
    module.mkdir()
    for name in ("go.mod", "go.sum", "dependencies.lock.json"):
        shutil.copyfile(ROOT / "sdk/go-guest/runtime-deps" / name, module / name)
    environment = build_environment(workspace)
    environment.update(PATH=str(go / "bin") + os.pathsep + str(generator / "bin") + os.pathsep + environment["PATH"],
        GOTOOLCHAIN="local", GOWORK="off", GOFLAGS="-mod=readonly", GOCACHE=str(workspace / "cache"),
        GOMODCACHE=str(workspace / "modules"))
    commands = Commands(module, workspace, environment)
    require(commands.run("generator-version", generator / "bin/componentize-go", "--version").strip()
        == b"componentize-go 0.4.3", "generator-version")
    commands.run("capture-locked-modules", go / "bin/go", "mod", "download", "all")
    require((module / "go.sum").read_bytes() == (ROOT / "sdk/go-guest/runtime-deps/go.sum").read_bytes(), "Go-lock-changed")
    sbom = generator_inventory(source, commands, payload, epoch)
    pack({"go": go, "generator": generator, "go-cache": workspace / "modules/cache/download"}, payload / "sdk")
    notices = payload / "licenses/go"
    notices.mkdir(parents=True)
    shutil.copyfile(go / "LICENSE", notices / "LICENSE")
    shutil.copyfile(module / "dependencies.lock.json", notices / "dependencies.lock.json")
    shutil.copyfile(source / "Cargo.lock", notices / "generator-Cargo.lock")
    # The module's archive (including its license) is part of the exact captured
    # offline cache. Its h1 content sums remain in go.sum, not mislabeled SHA-256.
    for entry in json.loads((module / "dependencies.lock.json").read_bytes())["modules"]:
        sbom["packages"].append({"SPDXID": "SPDXRef-go-module-" + hashlib.sha256(entry["path"].encode()).hexdigest(),
            "name": entry["path"], "versionInfo": entry["version"], "downloadLocation": "https://proxy.golang.org/" + entry["path"] + "/@v/" + entry["version"] + ".zip",
            "filesAnalyzed": False, "licenseDeclared": "NOASSERTION", "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION",
            "comment": "Go module content sum " + entry["sum"] + "; go.mod content sum " + entry["goModSum"]})
    (notices / "generator.spdx.json").write_bytes(encode(sbom))
    return sbom
