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
VERSION = "48.0.9"
COHORT = "wasmtime-48.0.9-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-join-state-call-future-pending-continuation-worker-function-queue-nodes-unordered-futures-outer-sync-result-stream-outers-consumer-producer-factories-http-ingress-memory-v30-authenticated-bounded-root-suspension-upstream-security-v31-consumer-poll-factory-v32-host-accept-factory-v33-consumer-inner-future-v34-producer-inner-future-v35-sync-ready-callback-v36-inline-runtime-futures-v37-store-custody-panic-v38-retained-pool-decommit-v39-borrowed-accept-future-v40-producer-future-unwind-v41-upstream-security-v42"
RECORD_SHA256 = "376a3071a2cdfbfc12061b25aacea01cd755537a65f694e442b018b9c4986666"
# Explicit reviewed postimages; the remaining original files use the immutable
# registry inventory. Changing a claimed record or patch cannot authorize bytes.
POSTIMAGES = {'Cargo.lock': {'bytes': 61171, 'sha256': '0108554c7f3c4dbd14837c824ecc6ffd55f84f1f8b834cea7c0042eb2ddb5a96'},
 'Cargo.toml': {'bytes': 11138, 'sha256': 'e2a487c1516ab852b3c16f660aecda7dd8e3eb7d179b7ed1f95969821fa10c2a'},
 'latent-dynamic-memory.patch': {'bytes': 805964,
                                 'sha256': '427fd64cd446424a070c28746c938e0083a535ebb6b30b97a3d77cd215892519'},
 'README.latent.md': {'bytes': 62283,
                      'sha256': '551e3e60dfdbf6cdfd06bdf55c9d6804492e5cf9f3ac34ba077d249b8b080d75'},
 'src/runtime/component/concurrent/abort.rs': {'bytes': 27109,
                                               'sha256': '3e15b4c7493da1e268efdc3979cda4d8db628a7a1bfef308f8d04250d53600ef'},
 'src/runtime/component/concurrent/call_future.rs': {'bytes': 9465,
                                                     'sha256': '555032577499fb6827ff9e79c44aed89d98edb94f6a5a4772caa4cb369be15b0'},
 'src/runtime/component/concurrent/func.rs': {'bytes': 21595,
                                              'sha256': 'f702bfbbc9b1dae7511eea811bb38b70536e297a23ffbeac2f372f6e0dd224e3'},
 'src/runtime/component/concurrent/futures_and_streams/stream_outer_tests.rs': {'bytes': 90052,
                                                                                'sha256': '1b7f5c53096e299ea357f11257886cbe6c5bcc05a067b7a011757a7d92552b2f'},
 'src/runtime/component/concurrent/futures_and_streams.rs': {'bytes': 259302,
                                                             'sha256': 'e5b5b448fd6f952abd8206e2eac065d2657d44dd5a4a43f39ed6487d6d90a903'},
 'src/runtime/component/concurrent/host_futures/abort.rs': {'bytes': 251,
                                                            'sha256': 'bdfece9f91accafd5122be36d628c37c5b219ac0eecec181267840fbb1e95a45'},
 'src/runtime/component/concurrent/host_futures/call_result_channel.rs': {'bytes': 15691,
                                                                          'sha256': '6e2b50b37dbbe9515c2a1c9e79eda6d7562c5687ee30680646d6a5ec3ab91ab0'},
 'src/runtime/component/concurrent/host_futures/LICENSE-APACHE': {'bytes': 10874,
                                                                  'sha256': '275c491d6d1160553c32fd6127061d7f9606c3ea25abfad6ca3f6ed088785427'},
 'src/runtime/component/concurrent/host_futures/LICENSE-MIT': {'bytes': 1094,
                                                               'sha256': '6652c868f35dfe5e8ef636810a4e576b9d663f3a17fb0f5613ad73583e1b88fd'},
 'src/runtime/component/concurrent/host_futures/mod.rs': {'bytes': 2786,
                                                          'sha256': '1ba25ca7993824020374671961551d6f87d3d0f946a07360aeeb2011a975806b'},
 'src/runtime/component/concurrent/host_futures/paid/iter.rs': {'bytes': 5843,
                                                                'sha256': '22ab512e0b07e12f5a45643b4ca1999eab765dddec7b6a08b6b9ad0d7bbb19b7'},
 'src/runtime/component/concurrent/host_futures/paid/mod.rs': {'bytes': 27999,
                                                               'sha256': '21bdf31da0641181a23f9bc52c7ca844e469bd01ec15f0b2e41764d18a8412f6'},
 'src/runtime/component/concurrent/host_futures/paid/ready_to_run_queue.rs': {'bytes': 3692,
                                                                              'sha256': '0e20b4406023c00aeb23c7ed1d6c5eadef33c1cbee3ca1dfaa075eb4919ca20b'},
 'src/runtime/component/concurrent/host_futures/paid/task.rs': {'bytes': 9353,
                                                                'sha256': 'b9736892c67cbf05035d9c6651e3116a3ec303a0fa2665feee8b9f5a738cef22'},
 'src/runtime/component/concurrent/host_futures/paid_arc.rs': {'bytes': 7503,
                                                               'sha256': '6e73d28aa2f7ad007ba926d87edd66063d9e882da66d4ed104025bbe71ee19ad'},
 'src/runtime/component/concurrent/host_futures/tests.rs': {'bytes': 12181,
                                                            'sha256': 'ebc37f82291509b19c1444fc912f27d88dadc90b2d1d166ef725eea017bdcabe'},
 'src/runtime/component/concurrent/inline_future_tests.rs': {'bytes': 13644,
                                                             'sha256': '7e43524326ae99495d1c5436dc66349cb44297b39dccb5f75e7d89da932d28d2'},
 'src/runtime/component/concurrent/pending_future.rs': {'bytes': 13771,
                                                        'sha256': '3daf6c6252f684830bc40b86065096b65e50d2a40fceb8db97c76a6e6a614164'},
 'src/runtime/component/concurrent/sync_result.rs': {'bytes': 15651,
                                                     'sha256': '306ac053b5fb9fdd5b01697ecbd3aaeabbcaf05015b7f447b89c0ccb4ed12f5e'},
 'src/runtime/component/concurrent/work_queue.rs': {'bytes': 17922,
                                                    'sha256': 'b9f2db05b9f27c6e6e88da558651e002101c2228eafd46ea9c2d386c45bf3ad8'},
 'src/runtime/component/concurrent/worker_function.rs': {'bytes': 13734,
                                                         'sha256': '385115039479020f0c648fdbadc0f130d42ef863eeda77ab2fde8d3cc5e7a79e'},
 'src/runtime/component/concurrent.rs': {'bytes': 334979,
                                         'sha256': 'a3091e7907104533241a0f0c4f5e3ef961ccc1a209a3bd53ccc93445a9968c2d'},
 'src/runtime/component/dynamic_memory.rs': {'bytes': 7317,
                                             'sha256': '70ab7ecf2fba9a29be46f4750e28ef404acc991d36d708939b022bce1872d57d'},
 'src/runtime/component/func/host.rs': {'bytes': 53876,
                                        'sha256': '565be85a100d3ffc8436eae8f54b380ef35833d5b11bebebbf372cd851aa8400'},
 'src/runtime/component/func/options.rs': {'bytes': 21116,
                                           'sha256': 'e3ad26a2f114ba5b904e6425894a26eabab49f85a876c94ab5490f95987e05c1'},
 'src/runtime/component/func/typed.rs': {'bytes': 125862,
                                         'sha256': 'b14c2d2d86f277ab6fdd5f1cb2281df3ddccf5d388bb6b5c6fb5ac2bc76a2382'},
 'src/runtime/component/func.rs': {'bytes': 30426,
                                   'sha256': '2960155a7902b0cf22e554fcf26f1ec085e3035942691ed0ca4db998be624f8d'},
 'src/runtime/component/instance.rs': {'bytes': 47912,
                                       'sha256': '3e509517c45b4cb855b3cadfda2df1ee3bd171f6319e1cf13b4ffd9476e17c4c'},
 'src/runtime/component/linker.rs': {'bytes': 42444,
                                     'sha256': '64cfd587747010f281df5192cd50ac8f052ee256e7df9ec100840f8d791f8e75'},
 'src/runtime/component/matching.rs': {'bytes': 9471,
                                       'sha256': '6f7a6165a8efe819f49de8e6f95d8b6b28dba5c4eaee400f0af70d74a3017f4f'},
 'src/runtime/component/mod.rs': {'bytes': 33579,
                                  'sha256': '3751a70fc24bd195d42edd3d88c878e75c53505e4e694287bde0c838a43f78b9'},
 'src/runtime/component/resource_table.rs': {'bytes': 35816,
                                             'sha256': '488174f61d1af70d63012f28cafa305a2558e5d383d947a4abc5420dcc15cc74'},
 'src/runtime/component/resource_types.rs': {'bytes': 5025,
                                             'sha256': '4e37f8fb059389b694fec202163830b98a9ae033003be03ef5e3da42641d4988'},
 'src/runtime/component/store.rs': {'bytes': 23722,
                                    'sha256': 'a80ca7dea6b93c3318d62c0dea7a9bc558af6b0aa55b7a8215a25edc5cb902d0'},
 'src/runtime/component/types.rs': {'bytes': 43048,
                                    'sha256': '3f3a0d08bceb6f2981a92d377a884a5d92c70502d5f1b3c90037fc14574e2b5c'},
 'src/runtime/component/values/accounted.rs': {'bytes': 16605,
                                               'sha256': '6c5c5699f9780139658a9d8b326ac1ba2fe337bdbce76f9fc10284f8fa2b6c09'},
 'src/runtime/component/values.rs': {'bytes': 57284,
                                     'sha256': '05e63166d688ce034b5151b960be030186c4575d6c0ec6eb8db6cba85f7dcc32'},
 'src/runtime/func.rs': {'bytes': 113497,
                         'sha256': '0cb8b3810aeac6e6d2cef30fe0a5852170395061547e259e23918c7d530d1d22'},
 'src/runtime/instance.rs': {'bytes': 42451,
                             'sha256': '27318bf0d9806250a1dd9994f4238d5b909c6fe24b29e2cc987e83f6c5651851'},
 'src/runtime/limits.rs': {'bytes': 23706,
                           'sha256': '31574a4d07197ce56dfc9b22dffd1b479007df865cf29b55c1883858c387dfee'},
 'src/runtime/linker.rs': {'bytes': 58811,
                           'sha256': '41499b3851bdbd98914642ad4e143c6f6bad4282489b400380096f33ca7395b0'},
 'src/runtime/module/native_registry.rs': {'bytes': 8389,
                                           'sha256': '2f638a74b19ab83d1f03b9b3aee8b5f8c10951d933b1d606863bea5f70291469'},
 'src/runtime/module/registry.rs': {'bytes': 26202,
                                    'sha256': 'b489ce99448623ba6c1208076791dae8fe24177359e4d445cde0cd13e8141f9d'},
 'src/runtime/module.rs': {'bytes': 50980,
                           'sha256': '7fff202d7ccf20d683f6b8e6a646c6aeae2216a4ca28abdef98c2e6d1d509e14'},
 'src/runtime/native_memory.rs': {'bytes': 11864,
                                  'sha256': '0670c370bb25265f7236329c0aa91eb7ff357cd2a53b84c052a7487c6b27bdd2'},
 'src/runtime/store/data.rs': {'bytes': 8766,
                               'sha256': '2203688a431803aebf3c227ec5e663e2a7bb42695455ce51920ea9f9240d3b32'},
 'src/runtime/store/func_refs/native.rs': {'bytes': 3903,
                                           'sha256': '045b053a93f9ecd26af08e0c6d56aa871a9591b749bf3ddf4dd941d5079845ce'},
 'src/runtime/store/func_refs.rs': {'bytes': 10778,
                                    'sha256': 'd587e606ffde4bf61a4fe7cfc8003bac032ee7cd92b67a1cfb5ae8f511d71f41'},
 'src/runtime/store.rs': {'bytes': 108574,
                          'sha256': '8bce01af0f30759ade9946c910877c724d25acfdc89a71855902230a32ab9fa6'},
 'src/runtime/vm/component/resources.rs': {'bytes': 14681,
                                           'sha256': '6d61eb899bdc31c2ee2a13fc44bd9dc129685e4a1894b4901d3364940f2079a1'},
 'src/runtime/vm/component.rs': {'bytes': 44649,
                                 'sha256': '1a5ef94428a9356e9e6167ed0317683fe23b2db76c468ba10d2897ba04768682'},
 'src/runtime/vm/cow.rs': {'bytes': 52926,
                           'sha256': 'af6601762a2f489d41f8a0f3ae2dc8dceca378f6ab32ae5605f178c143f7bce8'},
 'src/runtime/vm/instance/allocator/pooling/decommit_queue.rs': {'bytes': 20385,
                                                                 'sha256': '539428a41459250af83e86cee89b4ce81007dc54dd8488a9b36f31efbd00d486'},
 'src/runtime/vm/instance/allocator/pooling/table_pool.rs': {'bytes': 13753,
                                                             'sha256': '70a7ee51b01d163536063a61d7204b6725394679b484b63388344a3d2f6cd734'},
 'src/runtime/vm/instance/allocator/pooling.rs': {'bytes': 37311,
                                                  'sha256': 'bc84d98ad65b8449664832654d910a1bec054476200ce74e05de104002de1d06'},
 'src/runtime/vm/instance/allocator.rs': {'bytes': 19538,
                                          'sha256': '360ad3f4336eaeb39e43815125f9559980f64b458dd0e942f3c7b6eb0b1b5641'},
 'src/runtime/vm/instance.rs': {'bytes': 82927,
                                'sha256': '6439cc8b5987b6559b8be5c3df7380689d9257e24226deb8ec95f32e6a8779f8'},
 'src/runtime/vm/memory.rs': {'bytes': 33126,
                              'sha256': '92fbe4857b4599bec967e43278b6a7b0096b43caadb9ce5cbd6a29d66774c601'},
 'src/runtime/vm/table.rs': {'bytes': 40109,
                             'sha256': '6fb4ebe0d1fbd139073270a5195053b0ca956f787ae18586c5eea7dc2899a14b'},
 'src/runtime/vm/traphandlers/backtrace.rs': {'bytes': 21633,
                                              'sha256': '639c4eee08ad84ba93e45bcd696a1f3cc3238642f932f3f38d6c08a6f161c921'},
 'src/runtime.rs': {'bytes': 6393,
                    'sha256': '3290f57919f6dc6b6f797ee55cd62504ce31e91500741501e261f2c7e4eac970'}}
DEPENDENCY = {"path": PROVIDER, "version": "=48.0.9", "default-features": False,
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
        and cache["registryArchive"] == "https://static.crates.io/crates/wasmtime-internal-cache/wasmtime-internal-cache-48.0.9.crate"
        and cache["registrySha256"] == "5e6294e00c31bc4ad09b5354825cf32b08fbcfc19aaa49691fefe705ea088c82",
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
        "version": "=48.0.9", "path": "../wasmtime-cache", "optional": True,
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
    require(len(expected) == 277, "maintained-file-set")
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
    channel = record["callResultChannelUpstream"]
    require(channel["name"] == "futures-channel" and channel["version"] == "0.3.34"
            and channel["registryArchive"] == "https://static.crates.io/crates/futures-channel/futures-channel-0.3.34.crate"
            and channel["registrySha256"] == "b1f9e3d69d39e4862ffed03ed071a76f9a13ba1d9109d355b0f0aa6b15e393c4",
            "call-result-upstream-identity")
    channel_lock = [row for row in lock["package"] if row["name"] == channel["name"]]
    require(len(channel_lock) == 1 and channel_lock[0]["version"] == channel["version"]
            and channel_lock[0].get("checksum") == channel["registrySha256"]
            and channel_lock[0].get("source") == "registry+https://github.com/rust-lang/crates.io-index",
            "call-result-channel-lock")
    cache_backport = verify_cache_dependency(root, record)
    return {"callResultChannelUpstream": channel, "cacheSecurityBackport": cache_backport,
            "package": NAME, "version": VERSION, "recordSha256": RECORD_SHA256,
            "nativeCohort": COHORT, "upstreamArchive": record["registryArchive"],
            "upstreamSha256": record["registrySha256"],
            "patchSha256": POSTIMAGES["latent-dynamic-memory.patch"]["sha256"],
            "licenseFiles": {"LICENSE": original["LICENSE"]["sha256"]},
            "additionalLicenseFiles": {name: POSTIMAGES[name]["sha256"]
                for name in record["additionalUpstream"]["licenseFiles"]},
            "files": actual}
