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
COHORT = "wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-memory-v6"
RECORD_SHA256 = "123b016146ef6afb59be67dddc2df605b4e47172a1c65b9ca06b20830a324e64"
# Explicit reviewed postimages; the remaining original files use the immutable
# registry inventory. Changing a claimed record or patch cannot authorize bytes.
POSTIMAGES = {
    "README.latent.md": {
        "sha256": "ae9a5ea86241f6c182f8ba6c62a2a23250955969e9b61ceeaf25385783c5755b",
        "bytes": 8836
    },
    "latent-dynamic-memory.patch": {
        "sha256": "3a4cb39f9b454258e0af5351f820cfc5cc358c873f22f5b4516575fc86263f5e",
        "bytes": 164834
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
    "src/runtime/component/instance.rs": {
        "sha256": "3e509517c45b4cb855b3cadfda2df1ee3bd171f6319e1cf13b4ffd9476e17c4c",
        "bytes": 47912
    },
    "src/runtime/component/linker.rs": {
        "sha256": "36336f459595c676c6cd110e26715d2bb022a791cb74c973f6f4664b3d6ea5c2",
        "bytes": 39721
    },
    "src/runtime/component/matching.rs": {
        "sha256": "6f7a6165a8efe819f49de8e6f95d8b6b28dba5c4eaee400f0af70d74a3017f4f",
        "bytes": 9471
    },
    "src/runtime/component/mod.rs": {
        "sha256": "8ed8607bd903d8232685a47d6608554b6824e5638383abc128227d92f7bacc1d",
        "bytes": 32987
    },
    "src/runtime/component/resource_types.rs": {
        "sha256": "4e37f8fb059389b694fec202163830b98a9ae033003be03ef5e3da42641d4988",
        "bytes": 5025
    },
    "src/runtime/component/store.rs": {
        "sha256": "248924cbb1cd3955b8857c106f2284398464e68cf5b5c86992753bf1ee38f6ce",
        "bytes": 23704
    },
    "src/runtime/component/types.rs": {
        "sha256": "3f3a0d08bceb6f2981a92d377a884a5d92c70502d5f1b3c90037fc14574e2b5c",
        "bytes": 43048
    },
    "src/runtime/component/values.rs": {
        "sha256": "05e63166d688ce034b5151b960be030186c4575d6c0ec6eb8db6cba85f7dcc32",
        "bytes": 57284
    },
    "src/runtime/component/values/accounted.rs": {
        "sha256": "6c5c5699f9780139658a9d8b326ac1ba2fe337bdbce76f9fc10284f8fa2b6c09",
        "bytes": 16605
    },
    "src/runtime/func.rs": {
        "sha256": "0cb8b3810aeac6e6d2cef30fe0a5852170395061547e259e23918c7d530d1d22",
        "bytes": 113497
    },
    "src/runtime/instance.rs": {
        "sha256": "e86218a7b6117a5e4c082c6d16f7e5c6ee9ef25bc8d83f9036d4b5baafdb47f7",
        "bytes": 42435
    },
    "src/runtime/limits.rs": {
        "sha256": "4b96030b2134709f1232c5a66ec237e0ab73e7cdb738bfdd23c822c30c5846aa",
        "bytes": 20291
    },
    "src/runtime/linker.rs": {
        "sha256": "41499b3851bdbd98914642ad4e143c6f6bad4282489b400380096f33ca7395b0",
        "bytes": 58811
    },
    "src/runtime/module.rs": {
        "sha256": "7fff202d7ccf20d683f6b8e6a646c6aeae2216a4ca28abdef98c2e6d1d509e14",
        "bytes": 50980
    },
    "src/runtime/module/native_registry.rs": {
        "sha256": "2f638a74b19ab83d1f03b9b3aee8b5f8c10951d933b1d606863bea5f70291469",
        "bytes": 8389
    },
    "src/runtime/module/registry.rs": {
        "sha256": "74d234ddb2bd014b6acd5e7e9c3ac515cd47ab797497c5ffcfa4a51c5450cb04",
        "bytes": 24899
    },
    "src/runtime/native_memory.rs": {
        "sha256": "0670c370bb25265f7236329c0aa91eb7ff357cd2a53b84c052a7487c6b27bdd2",
        "bytes": 11864
    },
    "src/runtime/store.rs": {
        "sha256": "c59a92f8560c8449b96e381d117bba996c11a8f290242e98ab8fdab0cf00fa2d",
        "bytes": 106434
    },
    "src/runtime/store/data.rs": {
        "sha256": "2203688a431803aebf3c227ec5e663e2a7bb42695455ce51920ea9f9240d3b32",
        "bytes": 8766
    },
    "src/runtime/store/func_refs.rs": {
        "sha256": "d587e606ffde4bf61a4fe7cfc8003bac032ee7cd92b67a1cfb5ae8f511d71f41",
        "bytes": 10778
    },
    "src/runtime/store/func_refs/native.rs": {
        "sha256": "045b053a93f9ecd26af08e0c6d56aa871a9591b749bf3ddf4dd941d5079845ce",
        "bytes": 3903
    },
    "src/runtime/vm/component.rs": {
        "sha256": "1a5ef94428a9356e9e6167ed0317683fe23b2db76c468ba10d2897ba04768682",
        "bytes": 44649
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
    "src/runtime/vm/memory.rs": {
        "sha256": "a1e2fcb14ff1583d3f919e83adcc3e9c55da4aa858def138ae99c566f917e0c0",
        "bytes": 31758
    },
    "src/runtime/vm/table.rs": {
        "sha256": "663756ebc9376a46f87eba43369367c1515c720bdf9c21ee11e120944a45e8f9",
        "bytes": 41151
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
    require(len(expected) == 259, "maintained-file-set")
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
