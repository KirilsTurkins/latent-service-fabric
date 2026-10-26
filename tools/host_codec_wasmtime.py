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
COHORT = "wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-join-state-call-future-pending-continuation-worker-function-queue-nodes-unordered-futures-outer-sync-result-stream-outers-consumer-producer-memory-v19-cache-repair"
RECORD_SHA256 = "2c5174cb36b59fc3ccc79ad5505db0c547db572c419e41da389d69879b9c3409"
# Explicit reviewed postimages; the remaining original files use the immutable
# registry inventory. Changing a claimed record or patch cannot authorize bytes.
POSTIMAGES = {
    "Cargo.lock": {
        "sha256": "cd4732cd7667ff9352408a5f59aeb37ead9df5937b7aef61bc2089edaf5cb24b",
        "bytes": 60344
    },
    "Cargo.toml": {
        "sha256": "4d254730af81af4ab955e07e6ddaf541b96c4644d02cd59c17abc587d348697c",
        "bytes": 11138
    },
    "src/runtime.rs": {
        "sha256": "3290f57919f6dc6b6f797ee55cd62504ce31e91500741501e261f2c7e4eac970",
        "bytes": 6393
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
    "src/runtime/native_memory.rs": {
        "sha256": "0670c370bb25265f7236329c0aa91eb7ff357cd2a53b84c052a7487c6b27bdd2",
        "bytes": 11864
    },
    "src/runtime/store.rs": {
        "sha256": "c59a92f8560c8449b96e381d117bba996c11a8f290242e98ab8fdab0cf00fa2d",
        "bytes": 106434
    },
    "src/runtime/component/concurrent.rs": {
        "sha256": "e2e776c92875ea95b1a04e46afa3b51117d868bb85e9aa0cd439a60af1a9f85c",
        "bytes": 242539
    },
    "src/runtime/component/dynamic_memory.rs": {
        "sha256": "70ab7ecf2fba9a29be46f4750e28ef404acc991d36d708939b022bce1872d57d",
        "bytes": 7317
    },
    "src/runtime/component/func.rs": {
        "sha256": "2960155a7902b0cf22e554fcf26f1ec085e3035942691ed0ca4db998be624f8d",
        "bytes": 30426
    },
    "src/runtime/component/instance.rs": {
        "sha256": "3e509517c45b4cb855b3cadfda2df1ee3bd171f6319e1cf13b4ffd9476e17c4c",
        "bytes": 47912
    },
    "src/runtime/component/linker.rs": {
        "sha256": "9b0f1d69b58b637a17c61f9adf00008fd0cc211d4206c76d3970b255766aed58",
        "bytes": 40717
    },
    "src/runtime/component/matching.rs": {
        "sha256": "6f7a6165a8efe819f49de8e6f95d8b6b28dba5c4eaee400f0af70d74a3017f4f",
        "bytes": 9471
    },
    "src/runtime/component/mod.rs": {
        "sha256": "4a9e0dfa4854a1170ab67b8b4d354849da25358d355b02d5b79534598123e49e",
        "bytes": 33048
    },
    "src/runtime/component/resource_types.rs": {
        "sha256": "4e37f8fb059389b694fec202163830b98a9ae033003be03ef5e3da42641d4988",
        "bytes": 5025
    },
    "src/runtime/component/store.rs": {
        "sha256": "a80ca7dea6b93c3318d62c0dea7a9bc558af6b0aa55b7a8215a25edc5cb902d0",
        "bytes": 23722
    },
    "src/runtime/component/types.rs": {
        "sha256": "3f3a0d08bceb6f2981a92d377a884a5d92c70502d5f1b3c90037fc14574e2b5c",
        "bytes": 43048
    },
    "src/runtime/component/values.rs": {
        "sha256": "05e63166d688ce034b5151b960be030186c4575d6c0ec6eb8db6cba85f7dcc32",
        "bytes": 57284
    },
    "src/runtime/module/native_registry.rs": {
        "sha256": "2f638a74b19ab83d1f03b9b3aee8b5f8c10951d933b1d606863bea5f70291469",
        "bytes": 8389
    },
    "src/runtime/module/registry.rs": {
        "sha256": "74d234ddb2bd014b6acd5e7e9c3ac515cd47ab797497c5ffcfa4a51c5450cb04",
        "bytes": 24899
    },
    "src/runtime/store/data.rs": {
        "sha256": "2203688a431803aebf3c227ec5e663e2a7bb42695455ce51920ea9f9240d3b32",
        "bytes": 8766
    },
    "src/runtime/store/func_refs.rs": {
        "sha256": "d587e606ffde4bf61a4fe7cfc8003bac032ee7cd92b67a1cfb5ae8f511d71f41",
        "bytes": 10778
    },
    "src/runtime/vm/component.rs": {
        "sha256": "1a5ef94428a9356e9e6167ed0317683fe23b2db76c468ba10d2897ba04768682",
        "bytes": 44649
    },
    "src/runtime/vm/instance.rs": {
        "sha256": "6439cc8b5987b6559b8be5c3df7380689d9257e24226deb8ec95f32e6a8779f8",
        "bytes": 82927
    },
    "src/runtime/vm/memory.rs": {
        "sha256": "a1e2fcb14ff1583d3f919e83adcc3e9c55da4aa858def138ae99c566f917e0c0",
        "bytes": 31758
    },
    "src/runtime/vm/table.rs": {
        "sha256": "663756ebc9376a46f87eba43369367c1515c720bdf9c21ee11e120944a45e8f9",
        "bytes": 41151
    },
    "src/runtime/vm/component/resources.rs": {
        "sha256": "7143d4aacd672b4ca8e9d7ee8dadfe033b34be63066aa73e99b158be4066ba2b",
        "bytes": 14638
    },
    "src/runtime/vm/instance/allocator.rs": {
        "sha256": "360ad3f4336eaeb39e43815125f9559980f64b458dd0e942f3c7b6eb0b1b5641",
        "bytes": 19538
    },
    "src/runtime/vm/instance/allocator/pooling/table_pool.rs": {
        "sha256": "70a7ee51b01d163536063a61d7204b6725394679b484b63388344a3d2f6cd734",
        "bytes": 13753
    },
    "src/runtime/store/func_refs/native.rs": {
        "sha256": "045b053a93f9ecd26af08e0c6d56aa871a9591b749bf3ddf4dd941d5079845ce",
        "bytes": 3903
    },
    "src/runtime/component/concurrent/abort.rs": {
        "sha256": "3e15b4c7493da1e268efdc3979cda4d8db628a7a1bfef308f8d04250d53600ef",
        "bytes": 27109
    },
    "src/runtime/component/concurrent/call_future.rs": {
        "sha256": "555032577499fb6827ff9e79c44aed89d98edb94f6a5a4772caa4cb369be15b0",
        "bytes": 9465
    },
    "src/runtime/component/concurrent/func.rs": {
        "sha256": "f702bfbbc9b1dae7511eea811bb38b70536e297a23ffbeac2f372f6e0dd224e3",
        "bytes": 21595
    },
    "src/runtime/component/concurrent/futures_and_streams.rs": {
        "sha256": "4d5b0c94a4c1fc94ecec50fd9caf3168a0377de208066f768d0503db1dfe5cd8",
        "bytes": 234585
    },
    "src/runtime/component/concurrent/pending_future.rs": {
        "sha256": "3daf6c6252f684830bc40b86065096b65e50d2a40fceb8db97c76a6e6a614164",
        "bytes": 13771
    },
    "src/runtime/component/concurrent/sync_result.rs": {
        "sha256": "306ac053b5fb9fdd5b01697ecbd3aaeabbcaf05015b7f447b89c0ccb4ed12f5e",
        "bytes": 15651
    },
    "src/runtime/component/concurrent/worker_function.rs": {
        "sha256": "385115039479020f0c648fdbadc0f130d42ef863eeda77ab2fde8d3cc5e7a79e",
        "bytes": 13734
    },
    "src/runtime/component/concurrent/work_queue.rs": {
        "sha256": "b9f2db05b9f27c6e6e88da558651e002101c2228eafd46ea9c2d386c45bf3ad8",
        "bytes": 17922
    },
    "src/runtime/component/func/host.rs": {
        "sha256": "e5f91e592d1f8f58744cbfacb9b56c88edbaf9ac4f804eb88e288d97f698a0be",
        "bytes": 37004
    },
    "src/runtime/component/func/options.rs": {
        "sha256": "e3ad26a2f114ba5b904e6425894a26eabab49f85a876c94ab5490f95987e05c1",
        "bytes": 21116
    },
    "src/runtime/component/func/typed.rs": {
        "sha256": "1d54e072c057598b9bbe3ba0d00872eb9de0f531cb9cb2656b929c878bbc43ba",
        "bytes": 116904
    },
    "src/runtime/component/values/accounted.rs": {
        "sha256": "6c5c5699f9780139658a9d8b326ac1ba2fe337bdbce76f9fc10284f8fa2b6c09",
        "bytes": 16605
    },
    "src/runtime/component/concurrent/futures_and_streams/stream_outer_tests.rs": {
        "sha256": "4b1c346e24c373955876d1899626c708df34da25d50ef15af5d2f946b843ffca",
        "bytes": 40506
    },
    "src/runtime/component/concurrent/host_futures/abort.rs": {
        "sha256": "bdfece9f91accafd5122be36d628c37c5b219ac0eecec181267840fbb1e95a45",
        "bytes": 251
    },
    "src/runtime/component/concurrent/host_futures/LICENSE-APACHE": {
        "sha256": "275c491d6d1160553c32fd6127061d7f9606c3ea25abfad6ca3f6ed088785427",
        "bytes": 10874
    },
    "src/runtime/component/concurrent/host_futures/LICENSE-MIT": {
        "sha256": "6652c868f35dfe5e8ef636810a4e576b9d663f3a17fb0f5613ad73583e1b88fd",
        "bytes": 1094
    },
    "src/runtime/component/concurrent/host_futures/mod.rs": {
        "sha256": "bcf0a25ac5907ef9e6347b792dc5bf325bd8e3aefa7428509f3b1ca6433db84a",
        "bytes": 2750
    },
    "src/runtime/component/concurrent/host_futures/paid_arc.rs": {
        "sha256": "6e73d28aa2f7ad007ba926d87edd66063d9e882da66d4ed104025bbe71ee19ad",
        "bytes": 7503
    },
    "src/runtime/component/concurrent/host_futures/tests.rs": {
        "sha256": "ebc37f82291509b19c1444fc912f27d88dadc90b2d1d166ef725eea017bdcabe",
        "bytes": 12181
    },
    "src/runtime/component/concurrent/host_futures/paid/iter.rs": {
        "sha256": "22ab512e0b07e12f5a45643b4ca1999eab765dddec7b6a08b6b9ad0d7bbb19b7",
        "bytes": 5843
    },
    "src/runtime/component/concurrent/host_futures/paid/mod.rs": {
        "sha256": "21bdf31da0641181a23f9bc52c7ca844e469bd01ec15f0b2e41764d18a8412f6",
        "bytes": 27999
    },
    "src/runtime/component/concurrent/host_futures/paid/ready_to_run_queue.rs": {
        "sha256": "0e20b4406023c00aeb23c7ed1d6c5eadef33c1cbee3ca1dfaa075eb4919ca20b",
        "bytes": 3692
    },
    "src/runtime/component/concurrent/host_futures/paid/task.rs": {
        "sha256": "b9736892c67cbf05035d9c6651e3116a3ec303a0fa2665feee8b9f5a738cef22",
        "bytes": 9353
    },
    "README.latent.md": {
        "sha256": "b7fab677020c641f251857d658651ed268d2bd7f9b380b88b01f73e568a64c0e",
        "bytes": 34317
    },
    "latent-dynamic-memory.patch": {
        "sha256": "14a13879e32bb5e55a26b00c7ba473c5be43f7e7eaeb640137f5caf97fe43a1e",
        "bytes": 511917
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


CACHE_PROVIDER = "crates/vendor/wasmtime-cache"


def verify_cache_dependency(root: Path, record: dict) -> dict:
    # Exact manifest-only backport of the published cache. Its Rust, build script,
    # original manifest and all tests remain in this closed fourteen-file set.
    cache = record["cacheSecurityBackport"]
    require(set(cache) == {"schema", "name", "version", "provider", "registryArchive",
        "registrySha256", "originalFiles", "postimages", "fixedRegistryPackages"}
        and cache["schema"] == "latent.wasmtime-cache-zstd-backport.v1"
        and cache["name"] == "wasmtime-internal-cache" and cache["version"] == VERSION
        and cache["provider"] == CACHE_PROVIDER
        and cache["registryArchive"] == "https://static.crates.io/crates/wasmtime-internal-cache/wasmtime-internal-cache-48.0.7.crate"
        and cache["registrySha256"] == "b11ca8945aa341f944558622db59845dffa1435971f318d5fce2f2d9765a69b0",
        "cache-backport-profile")
    original = {row["path"]: {"sha256": row["sha256"], "bytes": row["bytes"]}
        for row in cache["originalFiles"]}
    require(len(original) == len(cache["originalFiles"]) == 14
        and set(cache["postimages"]) == {"Cargo.toml", "Cargo.lock"}, "cache-backport-files")
    expected = {**original, **cache["postimages"]}
    directory = root / CACHE_PROVIDER
    require(directory.is_dir() and directory.resolve(strict=True) == directory,
        "cache-source-directory")
    actual = {}
    for ordinal, path in enumerate(directory.rglob("*")):
        require(ordinal < 128 and not path.is_symlink(), "cache-source-bound-or-link")
        if path.is_dir():
            continue
        require(stat.S_ISREG(path.stat().st_mode), "cache-source-type")
        actual[path.relative_to(directory).as_posix()] = identity(read_file(path, 4 * 1024**2))
    require(actual == expected, "cache-source-identity")
    manifest = tomllib.loads(read_file(directory / "Cargo.toml", 128 * 1024).decode())
    require(manifest.get("workspace") == {}
        and manifest["package"]["name"] == cache["name"]
        and manifest["package"]["version"] == VERSION
        and manifest["package"]["license"] == "Apache-2.0 WITH LLVM-exception"
        and manifest["dependencies"]["zstd"] == {"version": "0.14.3", "default-features": False},
        "cache-patched-manifest")
    parent = tomllib.loads(read_file(root / PROVIDER / "Cargo.toml", 128 * 1024).decode())
    require(parent["dependencies"]["wasmtime-cache"] == {
        "version": "=48.0.7", "path": "../wasmtime-cache", "optional": True,
        "package": "wasmtime-internal-cache"}, "cache-local-selection")
    workspace = tomllib.loads(read_file(root / "Cargo.toml", 128 * 1024).decode())["workspace"]
    require(CACHE_PROVIDER in workspace.get("exclude", [])
        and CACHE_PROVIDER not in workspace["members"], "cache-workspace-isolation")
    fixed = {
        "zstd": {"version": "0.14.3", "checksum": "db3ae9bf90af6e40197bef767eeefc46ad6397420fe873830bd85e5fbbfb3c70"},
        "zstd-safe": {"version": "8.2.0", "checksum": "ded520f16b29e1a9b771c722221b2b0a0398c2316d9bb3c42b458a5414d7434b"},
        "zstd-sys": {"version": "2.1.2+zstd.1.5.7", "checksum": "481ada9c543b2323cbb7bbdbb5249177fbf0188ed959ed2c15e4b22421c84ed3"},
    }
    require(cache["fixedRegistryPackages"] == fixed, "cache-fixed-registry-pins")
    for provider in (PROVIDER, CACHE_PROVIDER):
        lock = tomllib.loads(read_file(root / provider / "Cargo.lock", 4 * 1024**2).decode())
        for name, pin in fixed.items():
            entries = [row for row in lock["package"] if row["name"] == name]
            require(len(entries) == 1 and entries[0]["version"] == pin["version"]
                and entries[0].get("checksum") == pin["checksum"]
                and entries[0].get("source") == "registry+https://github.com/rust-lang/crates.io-index",
                "cache-patched-lock-package")
        local = [row for row in lock["package"] if row["name"] == cache["name"]]
        require(len(local) == 1 and local[0]["version"] == VERSION
            and "source" not in local[0] and "checksum" not in local[0], "cache-patched-lock-source")
    return {"package": cache["name"], "version": VERSION, "provider": CACHE_PROVIDER,
        "upstreamArchive": cache["registryArchive"], "upstreamSha256": cache["registrySha256"],
        "fixedRegistryPackages": fixed, "files": actual,
        "licenseFiles": {"LICENSE": original["LICENSE"]["sha256"]}}


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
    require(len(expected) == 275, "maintained-file-set")
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
    cache_backport = verify_cache_dependency(root, record)
    return {"cacheSecurityBackport": cache_backport,
            "package": NAME, "version": VERSION, "recordSha256": RECORD_SHA256,
            "nativeCohort": COHORT, "upstreamArchive": record["registryArchive"],
            "upstreamSha256": record["registrySha256"],
            "patchSha256": POSTIMAGES["latent-dynamic-memory.patch"]["sha256"],
            "licenseFiles": {"LICENSE": original["LICENSE"]["sha256"]},
            "additionalLicenseFiles": {name: POSTIMAGES[name]["sha256"]
                for name in record["additionalUpstream"]["licenseFiles"]},
            "files": actual}
