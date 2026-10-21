"""Authenticate only the reviewed pinned Wasmtime dynamic-value allocation fork."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import tomllib

from tools.rust_capsule_project import ROOT, read_file

PROVIDER = "crates/vendor/wasmtime"
NAME = "wasmtime"
VERSION = "48.0.7"
COHORT = "wasmtime-48.0.7-latent-dynamic-value-memory-v1"
RECORD_SHA256 = "7af6c6bede1df08512de58715882d1f90ac9aae3368b6b1469538c57f4ba94de"
# Explicit reviewed postimages; the remaining original files use the immutable
# registry inventory. Changing a claimed record or patch cannot authorize bytes.
POSTIMAGES = {
    "src/runtime/component/func.rs": {
        "sha256": "2960155a7902b0cf22e554fcf26f1ec085e3035942691ed0ca4db998be624f8d",
        "bytes": 30426
    },
    "src/runtime/component/func/options.rs": {
        "sha256": "e3ad26a2f114ba5b904e6425894a26eabab49f85a876c94ab5490f95987e05c1",
        "bytes": 21116
    },
    "src/runtime/component/func/typed.rs": {
        "sha256": "1d54e072c057598b9bbe3ba0d00872eb9de0f531cb9cb2656b929c878bbc43ba",
        "bytes": 116904
    },
    "src/runtime/component/concurrent/func.rs": {
        "sha256": "f702bfbbc9b1dae7511eea811bb38b70536e297a23ffbeac2f372f6e0dd224e3",
        "bytes": 21595
    },
    "src/runtime/component/mod.rs": {
        "sha256": "367e2f0e7bc758159f8ce3aa16f4afd4074b0d23e53bd65b10b6c06ceda3907f",
        "bytes": 32854
    },
    "src/runtime/component/values.rs": {
        "sha256": "05e63166d688ce034b5151b960be030186c4575d6c0ec6eb8db6cba85f7dcc32",
        "bytes": 57284
    },
    "src/runtime/component/dynamic_memory.rs": {
        "sha256": "70ab7ecf2fba9a29be46f4750e28ef404acc991d36d708939b022bce1872d57d",
        "bytes": 7317
    },
    "src/runtime/component/values/accounted.rs": {
        "sha256": "6c5c5699f9780139658a9d8b326ac1ba2fe337bdbce76f9fc10284f8fa2b6c09",
        "bytes": 16605
    },
    "README.latent.md": {
        "sha256": "a7f49177ec5ffc9e143395a79eedf1d62492827bcaa5a092edfb891774bea29e",
        "bytes": 2650
    },
    "latent-dynamic-memory.patch": {
        "sha256": "0d07fb2dbcbc463dad2ae65203badc089e8783cf2f8d89c2bb7479a9526493c4",
        "bytes": 40049
    }
}
DEPENDENCY = {"path": PROVIDER, "version": "=48.0.7", "default-features": False,
    "features": ["component-model", "component-model-async", "cranelift",
                 "pooling-allocator", "runtime", "std", "wit-parser"]}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("host-codec-wasmtime-" + reason)


def identity(raw: bytes) -> dict:
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verify(root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    source = root / PROVIDER
    require(source.is_dir() and source.resolve(strict=True) == source,
            "source-directory")
    raw = read_file(source / "UPSTREAM.latent.json", 128 * 1024)
    require(hashlib.sha256(raw).hexdigest() == RECORD_SHA256, "record-identity")
    record = json.loads(raw)
    require(record["schema"] == "latent.pinned-wasmtime.dynamic-memory-source.v1"
            and record["upstreamVersion"] == VERSION and record["nativeCohort"] == COHORT,
            "record-profile")
    original = {row["path"]: {"sha256": row["sha256"], "bytes": row["bytes"]}
                for row in record["originalFiles"]}
    require(len(record["originalFiles"]) == len(original) == 250, "original-file-set")
    expected = {**original, **POSTIMAGES, "UPSTREAM.latent.json": identity(raw)}
    require(len(expected) == 255, "maintained-file-set")
    actual, total = {}, 0
    for ordinal, path in enumerate(source.rglob("*")):
        require(ordinal < 1024 and not path.is_symlink(), "source-tree-bound-or-link")
        if path.is_dir():
            continue
        require(stat.S_ISREG(path.stat().st_mode), "source-type")
        data = read_file(path, 4 * 1024**2)
        total += len(data)
        require(total <= 8 * 1024**2, "source-byte-bound")
        actual[path.relative_to(source).as_posix()] = identity(data)
    require(actual == expected, "source-identity")
    workspace = tomllib.loads(read_file(root / "Cargo.toml", 128 * 1024).decode())
    config = workspace["workspace"]
    require(config.get("dependencies", {}).get(NAME) == DEPENDENCY, "selection")
    require(PROVIDER in config.get("exclude", []) and PROVIDER not in config["members"],
            "workspace-isolation")
    require(not any(NAME in rows for rows in workspace.get("patch", {}).values())
            and not workspace.get("replace"), "global-shadowing")
    lock = tomllib.loads(read_file(root / "Cargo.lock", 4 * 1024**2).decode())
    selected = [row for row in lock["package"] if row["name"] == NAME]
    require(len(selected) == 1 and selected[0]["version"] == VERSION
            and "source" not in selected[0] and "checksum" not in selected[0],
            "lock-selection")
    package = tomllib.loads(read_file(source / "Cargo.toml", 128 * 1024).decode())["package"]
    require(package["name"] == NAME and package["version"] == VERSION
            and package["license"] == "Apache-2.0 WITH LLVM-exception", "package-identity")
    return {"package": NAME, "version": VERSION, "recordSha256": RECORD_SHA256,
            "nativeCohort": COHORT, "upstreamArchive": record["registryArchive"],
            "upstreamSha256": record["registrySha256"],
            "patchSha256": POSTIMAGES["latent-dynamic-memory.patch"]["sha256"],
            "licenseFiles": {"LICENSE": original["LICENSE"]["sha256"]},
            "files": actual}
