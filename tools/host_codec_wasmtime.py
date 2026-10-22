"""Authenticate only the reviewed pinned Wasmtime value/table/Store allocation fork."""
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
COHORT = "wasmtime-48.0.7-latent-value-table-store-memory-v2"
RECORD_SHA256 = "1f42297615586b8668c0e2683e15e8cfce2039c5f87d615e8bfd23d8e713a9d9"
# Explicit reviewed postimages; the remaining original files use the immutable
# registry inventory. Changing a claimed record or patch cannot authorize bytes.
POSTIMAGES = {
    "README.latent.md": {
        "sha256": "177bf31b2fbe66d8ba48ac81c7be448da6daf2a09b8629be752d7ce869d05468",
        "bytes": 5980
    },
    "latent-dynamic-memory.patch": {
        "sha256": "7174452516ad451c5f7057c75c80b96784a4e69b8a18943ef9a0385bc3ddc26f",
        "bytes": 108391
    },
    "src/runtime.rs": {
        "sha256": "3290f57919f6dc6b6f797ee55cd62504ce31e91500741501e261f2c7e4eac970",
        "bytes": 6393
    },
    "src/runtime/component/concurrent/func.rs": {
        "sha256": "f702bfbbc9b1dae7511eea811bb38b70536e297a23ffbeac2f372f6e0dd224e3",
        "bytes": 21595
    },
    "src/runtime/component/dynamic_memory.rs": {
        "sha256": "70ab7ecf2fba9a29be46f4750e28ef404acc991d36d708939b022bce1872d57d",
        "bytes": 7317
    },
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
    "src/runtime/component/mod.rs": {
        "sha256": "d0d73897629408a9e7e88512461ff818e0624a93243095b08b982e4445b9c331",
        "bytes": 32858
    },
    "src/runtime/component/store.rs": {
        "sha256": "248924cbb1cd3955b8857c106f2284398464e68cf5b5c86992753bf1ee38f6ce",
        "bytes": 23704
    },
    "src/runtime/component/values.rs": {
        "sha256": "05e63166d688ce034b5151b960be030186c4575d6c0ec6eb8db6cba85f7dcc32",
        "bytes": 57284
    },
    "src/runtime/component/values/accounted.rs": {
        "sha256": "6c5c5699f9780139658a9d8b326ac1ba2fe337bdbce76f9fc10284f8fa2b6c09",
        "bytes": 16605
    },
    "src/runtime/limits.rs": {
        "sha256": "0bcebb9240acae85704612e9a7a1e3c41bb2e64d774ce79eb0b75d0a55e0b813",
        "bytes": 19412
    },
    "src/runtime/native_memory.rs": {
        "sha256": "0c897686b3c2a331282195e8660f6bc6d20f9901c6a036b44d47c8d7de411489",
        "bytes": 9270
    },
    "src/runtime/store.rs": {
        "sha256": "de302e728703c7c76c460edb877afcd26622ffce2f9ca4012ca70553c4cd7373",
        "bytes": 105912
    },
    "src/runtime/store/data.rs": {
        "sha256": "2203688a431803aebf3c227ec5e663e2a7bb42695455ce51920ea9f9240d3b32",
        "bytes": 8766
    },
    "src/runtime/vm/component.rs": {
        "sha256": "f3ff8d49543212eba5d0da5d33ae2b950be07b07fe607f139ccb3d5c8bcab37b",
        "bytes": 44845
    },
    "src/runtime/vm/component/resources.rs": {
        "sha256": "7143d4aacd672b4ca8e9d7ee8dadfe033b34be63066aa73e99b158be4066ba2b",
        "bytes": 14638
    },
    "src/runtime/vm/instance.rs": {
        "sha256": "6439cc8b5987b6559b8be5c3df7380689d9257e24226deb8ec95f32e6a8779f8",
        "bytes": 82927
    },
    "src/runtime/vm/instance/allocator.rs": {
        "sha256": "360ad3f4336eaeb39e43815125f9559980f64b458dd0e942f3c7b6eb0b1b5641",
        "bytes": 19538
    },
    "src/runtime/vm/instance/allocator/pooling/table_pool.rs": {
        "sha256": "70a7ee51b01d163536063a61d7204b6725394679b484b63388344a3d2f6cd734",
        "bytes": 13753
    },
    "src/runtime/vm/table.rs": {
        "sha256": "d83c0cafa69da8b7cddd07414db3f337ccc7e1a810d86208c29e493b851ae649",
        "bytes": 41113
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
    require(len(expected) == 256, "maintained-file-set")
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
