"""Independently verify maintained npm source repairs without executing them.

This scanner control does not import the project's archive builder. It reads
fresh authenticated upstream archives as data, checks complete-file preimages
and postimages, and reconstructs the exact deterministic distribution pinned by
every selected lock. Upstream package identities remain in all OSV queries.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath
from time import monotonic

from tools import security_dotnet_minimatch as dotnet_sources
from tools import security_setup_go, security_upload_artifact
from tools.security_common import POLICY, decode_json, digest, read_file, require


def integrity(raw: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("unexpected npm repair registry redirect")


def registry_archive(pin: dict) -> bytes:
    name, version = pin["name"], pin["version"]
    require(re.fullmatch(r"[a-z][a-z0-9-]*", name) is not None
            and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is not None,
            "invalid-npm-repair-upstream-identity")
    url = f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=30) as response:
        require(response.status == 200 and response.url == url, "npm-repair-upstream-unavailable")
        raw = response.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024 and integrity(raw) == pin["integrity"],
            "npm-repair-upstream-integrity")
    return raw


def members(raw: bytes) -> dict[str, tuple[bytes, int]]:
    result, seen, size = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for count, item in enumerate(archive, 1):
            name = item.name.rstrip("/")
            path = PurePosixPath(name)
            require(count <= 6000 and bool(name) and "\\" not in name
                    and not path.is_absolute() and path.parts[0] == "package"
                    and not any(part in {"", ".", ".."} for part in name.split("/"))
                    and name not in seen, "npm-repair-archive-path")
            seen.add(name)
            if item.isdir():
                continue
            require(item.isfile() and 0 <= item.size <= 8 * 1024 * 1024,
                    "npm-repair-archive-member")
            size += item.size
            require(size <= 64 * 1024 * 1024, "npm-repair-expanded-bound")
            stream = archive.extractfile(item)
            require(stream is not None, "npm-repair-missing-member")
            with stream:
                value = stream.read(item.size + 1)
            require(len(value) == item.size, "npm-repair-truncated-member")
            result[name] = value, 0o755 if item.mode & 0o111 else 0o644
    return result


def manifest(files: dict, name: str, version: str, dependencies: dict, prefix="package/") -> dict:
    value = decode_json(files[prefix + "package.json"][0])
    require(value.get("name") == name and value.get("version") == version
            and value.get("dependencies", {}) == dependencies
            and not any(value.get(field) for field in (
                "optionalDependencies", "peerDependencies", "bundleDependencies", "bundledDependencies")),
            "npm-repair-package-graph")
    if prefix == "package/":
        require(not any(key.startswith("package/node_modules/") for key in files)
                and not any(key in files for key in ("package/package-lock.json", "package/npm-shrinkwrap.json")),
                "npm-repair-hidden-package-graph")
    return value


def source_repair(files: dict, repair: dict, pin: dict) -> dict:
    expected = {"braces": {"lib/utils.js", "lib/compile.js", "lib/expand.js", "lib/stringify.js", "lib/parse.js"},
                "http-cache-semantics": {"index.js"},
                "deepmerge": {"index.js", "dist/cjs.js", "dist/umd.js"},
                "minimatch": {"dist/commonjs/index.js", "dist/esm/index.js"},
                "glob": {"dist/commonjs/walker.js", "dist/esm/walker.js"}}
    require(set(repair) == {"schema", "profile", "name", "version", "upstreamIntegrity", "files"}
            and repair["schema"] == 1 and repair["name"] == pin["name"]
            and repair["version"] == pin["version"] and repair["upstreamIntegrity"] == pin["integrity"]
            and isinstance(repair["files"], list), "npm-repair-document-identity")
    rows = repair["files"]
    require(len(rows) == len(expected[pin["name"]])
            and {row["path"] for row in rows} == expected[pin["name"]], "npm-repair-file-coverage")
    output = files.copy()
    for row in rows:
        require(set(row) == {"path", "beforeSha256", "afterSha256", "edits"}
                and all(isinstance(row[field], str) and re.fullmatch(r"[0-9a-f]{64}", row[field])
                        for field in ("beforeSha256", "afterSha256")), "npm-repair-file-identity")
        key = "package/" + row["path"]
        raw, mode = files[key]
        require(digest(raw) == row["beforeSha256"], "npm-repair-preimage-drift")
        edits = row["edits"]
        require(isinstance(edits, list) and 0 < len(edits) <= 8, "npm-repair-edit-bound")
        text = raw.decode("utf-8")
        for edit in edits:
            require(set(edit) == {"before", "after", "count"}
                    and all(isinstance(edit[field], str) and 0 < len(edit[field]) <= 8192
                            for field in ("before", "after"))
                    and edit["before"] != edit["after"] and type(edit["count"]) is int
                    and 0 < edit["count"] <= 4 and text.count(edit["before"]) == edit["count"],
                    "npm-repair-edit-drift")
            text = text.replace(edit["before"], edit["after"])
        patched = text.encode("utf-8")
        require(patched != raw and digest(patched) == row["afterSha256"], "npm-repair-postimage-drift")
        output[key] = patched, mode
    return output


BUNDLE_REPAIR_FILES = {
    "node_modules/minimatch/dist/commonjs/index.js", "node_modules/minimatch/dist/esm/index.js",
    "node_modules/glob/dist/commonjs/walker.js", "node_modules/glob/dist/esm/walker.js",
    "node_modules/glob/dist/commonjs/index.min.js", "node_modules/glob/dist/esm/index.min.js",
}


def bundle_source_repair(files: dict, repair: dict, base: dict) -> dict:
    """Independently reconstruct the fixed npm bundle without executing it."""
    require(set(repair) == {"schema", "profile", "name", "version", "upstreamIntegrity", "files"}
            and repair["schema"] == 1 and repair["profile"] == "npm-11.19.1-lsf-glob-minimatch-source-v1"
            and repair["name"] == base["name"] and repair["version"] == base["version"]
            and repair["upstreamIntegrity"] == base["integrity"], "npm-bundle-repair-identity")
    for name, version, dependencies in (
            ("glob", "13.0.6", {"minimatch": "^10.2.2", "minipass": "^7.1.3", "path-scurry": "^2.0.2"}),
            ("minimatch", "10.2.5", {"brace-expansion": "^5.0.5"})):
        prefix = f"package/node_modules/{name}/"
        manifest(files, name, version, dependencies, prefix)
        require(not any(key.startswith(prefix + "node_modules/") for key in files), "npm-bundle-repair-shadow")
        all_manifests = [key for key in files if key.endswith(f"/node_modules/{name}/package.json")]
        require(all_manifests == [prefix + "package.json"], "npm-bundle-repair-extra-member")
    rows = repair["files"]
    require(isinstance(rows, list) and len(rows) == len(BUNDLE_REPAIR_FILES)
            and {row.get("path") for row in rows} == BUNDLE_REPAIR_FILES, "npm-bundle-repair-coverage")
    output = files.copy()
    for row in rows:
        require(set(row) == {"path", "beforeSha256", "afterSha256", "edits"}
                and all(isinstance(row[field], str) and re.fullmatch(r"[0-9a-f]{64}", row[field])
                        for field in ("beforeSha256", "afterSha256")), "npm-bundle-repair-file-identity")
        key = "package/" + row["path"]
        raw, mode = files[key]
        require(digest(raw) == row["beforeSha256"], "npm-bundle-repair-preimage")
        edits = row["edits"]
        require(isinstance(edits, list) and 0 < len(edits) <= 8, "npm-bundle-repair-edit-bound")
        value = raw.decode("utf-8")
        for edit in edits:
            require(set(edit) == {"before", "after", "count"}
                    and all(isinstance(edit[field], str) and 0 < len(edit[field]) <= 8192
                            for field in ("before", "after"))
                    and edit["before"] != edit["after"] and type(edit["count"]) is int
                    and 0 < edit["count"] <= 4 and value.count(edit["before"]) == edit["count"],
                    "npm-bundle-repair-edit")
            value = value.replace(edit["before"], edit["after"])
        patched = value.encode("utf-8")
        require(patched != raw and digest(patched) == row["afterSha256"], "npm-bundle-repair-postimage")
        output[key] = patched, mode
    return output


def distribution(files: dict) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, (raw, mode) in sorted(files.items()):
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(raw), mode
            item.mtime = item.uid = item.gid = 0
            archive.addfile(item, io.BytesIO(raw))
    return output.getvalue()


CHECKOUT_PROFILE = "checkout-deepmerge-source-v1"
CHECKOUT_REFERENCE = "KirilsTurkins/lsf-checkout@4d310727149d3abacc52b5dcb0a1c4d18b345d13"
CHECKOUT_PREFIX = ".github/security/actions/checkout/"
CHECKOUT_ARCHIVE = "file:.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar"
ACTION_PROFILE = "deepmerge-action-source-v1"
ACTION_VERIFIER_SOURCE = ".lsf-source/verify-installed-deepmerge.mjs"
BCA_PROFILE = "bytecodealliance-deepmerge-source-v1"
BCA_PREFIX = ".github/security/actions/bytecodealliance-actions/"
BCA_REFERENCE = ("KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup@"
                 "1ce6e3461b7d83b4b5a5a6557870b4fdfd4386ce")
BCA_ADVISORIES = [{"id": "GHSA-gcqx-w48m-w2h4", "modified": "2026-10-27T21:45:04.256048Z"}]
# The nested entrypoint has its own exact profile. It must not extend the
# root-action selector or make another action eligible for this receipt.
BCA_INPUTS = {
    "package.json": (BCA_PREFIX + "package.json", 2852,
        "830926dc4fc6b8357b85ee84855aa6c8dbd42569884bbadf932fb54401a22e7e", "b24f80bbef887b238195755763773aeeef42d5f0"),
    "package-lock.json": (BCA_PREFIX + "package-lock.json", 308458,
        "a4d4e4834d16cc2655b73066144923018ec59f38497b7d37d549fa22ecd1d424", "0a0ee9b804ca36240ae28185ab2b4b010345a0e5"),
    "wasm-tools/setup/action.yml": (BCA_PREFIX + "wasm-tools/setup/action.yml.snapshot", 585,
        "69066705f008bae4cc14ad69328d6e7d87562e6651b8ae713ff45be2ff1eb5b1", "12a645b94d14643b2e4d80b49c1768cd71e686b9"),
    ACTION_VERIFIER_SOURCE: (".github/security/actions/deepmerge-source/installed-verifier.mjs.snapshot", 2381,
        "55367db845fb579dd45a1a16924bf017c0ddc8f84162d833e368c24a7d629cf7", "99d75a2ea3895eb8acc8018984ca9826e4edff51"),
}
BCA_MATERIAL = {
    "archive": (".github/security/actions/checkout-source/deepmerge-4.3.1.repaired.tar", 51200,
        "c4ca0f4eb3a2464c026bc3dec5d9eaf04544aed24c3fd1d77da95f85e36c369f", "30e23fad3a82fd30bc3f08e26704a0c0bc84c704"),
    "repair": (".github/security/actions/checkout-source/repair.json", 3064,
        "e402617d1e791c4bed35768b6c34ba68c370c076551495e738de0731ad2049c7", "52602f18647aa2f2bd30f046e05bcce2705a761f"),
    "declaration": (".github/security/actions/checkout-source/declaration.json", 6925,
        "b4b0b79fa2bc84c6f1e1c61ddcc1ab228df629f9fce4b1067d3ac8b3d1c42892", "0685ff353f65174eb5a97cfcb385720dd4a5874c"),
    "upstream": (".github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz", 8452,
        "4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c", "1d1560e971dfc484bbe0cb9e8c86bde9140e45b5"),
    "build": (BCA_PREFIX + "fork-build.json", 1904,
        "c1a5e4e6e8802d173f2e2badee53d489bc4569e1d6766c36828ed49e8dfa374f", "180edbd64e2609ac8d30c69b58987097398d77b1"),
}
CACHE_PREFIX = ".github/security/actions/cache/"
CACHE_RESTORE_REFERENCE = "KirilsTurkins/lsf-cache/restore@ec176dce9471270c8a9be1289040c0a8fd6aa708"
CACHE_SAVE_REFERENCE = "KirilsTurkins/lsf-cache/save@ec176dce9471270c8a9be1289040c0a8fd6aa708"
CACHE_SOURCE_SHA256 = {
    "package.json": "8e8b46d08a417276c9c979e66f78f1de5b4e0af637c9e60128c738a65b8b64f8",
    "package-lock.json": "e979985c5b09e89732e1c75abdf62c6f166d8238e4aed768c2fefcf7c44d7131",
    ACTION_VERIFIER_SOURCE: "55367db845fb579dd45a1a16924bf017c0ddc8f84162d833e368c24a7d629cf7",
    "restore/action.yml": "bb552a94cec165255080b7e13fe3d2051c6c79e321e99435b5859dc7de5e9057",
    "save/action.yml": "5da400e1a7551cee617339fd1a5281483d71e6c56d86dd117fbd354f047308ec",
}
ACTION_REFERENCES = {
    CACHE_PREFIX: CACHE_RESTORE_REFERENCE,
    dotnet_sources.PREFIX: dotnet_sources.REFERENCE,
    ".github/security/actions/setup-java/":
        "KirilsTurkins/lsf-setup-java@63c7977881fc344a6ed464f7ed5e242aedc8d56c",
    ".github/security/actions/setup-node/":
        "KirilsTurkins/lsf-setup-node@34275fdec80b5be172c3327cadef76aa2f3b31c6",
    ".github/security/actions/setup-python/":
        "KirilsTurkins/lsf-setup-python@164c4cbba5d1b03a046ac8bc25ae695bee0667a8",
    ".github/security/actions/upload-artifact/":
        "KirilsTurkins/lsf-upload-artifact@d74a697ce553b389f4219545e07c97fb8542c64f",
}


MINIMATCH_PROFILE = "minimatch-action-source-v1"
MINIMATCH_PREFIX = ".github/security/actions/setup-python/"
MINIMATCH_ARCHIVE = "file:.lsf-source/minimatch-10.2.5-lsf-bound-v1.tar"
MINIMATCH_VERIFIER = ".lsf-source/verify-installed-minimatch.mjs"
MINIMATCH_UPSTREAM = "sha512-MULkVLfKGYDFYejP07QOurDLLQpcjk7Fw+7jXS2R2czRQzR56yHRveU5NDJEOviH+hETZKSkIk5c+T23GjFUMg=="
MINIMATCH_DERIVED = "sha512-HQ5eg+B4Pi8hEcfMgmmFULbhwIq3JWt7ixaNqDV+p8+4fxDUUqlA9VLilGLMmx1qXmeg0HzEabCGgfLIaNOkfw=="
MINIMATCH_ADVISORIES = [{"id": "GHSA-g3hv-75wg-m249", "modified": "2026-11-04T17:01:25.850114Z"}]
MINIMATCH_ASSETS = {'upstream': {'snapshot': '.github/security/actions/setup-python-minimatch/minimatch-10.2.5.original.tgz',
              'source': '.lsf-source/minimatch-10.2.5.original.tgz',
              'bytes': 117062,
              'sha256': 'a6cea46915bfc6c3fae60f9bd003ea4f9d6a4233aa59a9ca729474d3824ca9e5',
              'gitBlob': 'dd98b4079e660933500de9f03d0bbbab1f44f295'},
 'archive': {'snapshot': '.github/security/actions/setup-python-minimatch/minimatch-10.2.5.repaired.tar',
             'source': '.lsf-source/minimatch-10.2.5-lsf-bound-v1.tar',
             'bytes': 583680,
             'sha256': '8ed155c4f29d451728efaaf60bc0ed7249ceb93d21eb81171068342621287a68',
             'gitBlob': '93a1d4e2d4c2935624af7aa91fe9a113c56e5932'},
 'repair': {'snapshot': '.github/security/actions/setup-python-minimatch/repair.json',
            'source': '.lsf-source/minimatch-10.2.5-lsf-bound-v1.repair.json',
            'bytes': 2129,
            'sha256': 'b340bb0502087bb0df18c8ec276ee61f58aedc6c54fcc6b022d174817d7d27a9',
            'gitBlob': '679352aace8de2eb661a5a9665d6152033833cbb'},
 'verifier': {'snapshot': '.github/security/actions/setup-python-minimatch/installed-verifier.mjs.snapshot',
              'source': '.lsf-source/verify-installed-minimatch.mjs',
              'bytes': 3386,
              'sha256': '4fcbcba0f46fed80b09c6cdb1a2a54eeff2e0a3690b4d0a5b566762169f1f826',
              'gitBlob': 'ab204a63dd0ddf065b00ae7c3ab0531b35d5d300'},
 'build': {'snapshot': '.github/security/actions/setup-python-minimatch/fork-build.json',
           'source': 'https://github.com/KirilsTurkins/lsf-setup-python/actions/runs/42010605694',
           'bytes': 3036,
           'sha256': '0031441630253140eed878e0be984ab6cfa5dfb6aecea60af6d04f82f35daefb',
           'gitBlob': 'bd169fe4cfba82a9181e7719c6f539cff86fd63f'}}
MINIMATCH_RUNTIME = {'runtime_setup': {'source': 'dist/setup/index.js',
                   'bytes': 3675836,
                   'sha256': 'e3bbbcbb7ab676335857f03b50e89f8e7bf5423f594a4b2212b966dde55fe8b7',
                   'gitBlob': 'aef6783f257e77b06e518b7c6e5a9b2384c62cd2'},
 'runtime_cache': {'source': 'dist/cache-save/index.js',
                   'bytes': 3581654,
                   'sha256': '06f010acee2ff7034243f3dbdac1907923d004f370597501e762b452af26c0f0',
                   'gitBlob': '2c6014773ffb3c51eb8307d36641ce6691c2c4e8'}}
MINIMATCH_RUNTIME_LIMIT = 8 * 1024 * 1024


JAVA_MINIMATCH_PROFILE = 'setup-java-minimatch-action-source-v1'
JAVA_MINIMATCH_PREFIX = '.github/security/actions/setup-java/'
JAVA_MINIMATCH_ARCHIVE = 'file:.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar'
JAVA_MINIMATCH_UPSTREAM = 'sha512-vpLQEs+VLCr1nU0BXS07maYoFwlDAH0gngQuuttxIwutDFEMHq2blX+8vpgxDdK3J1PwjCJiep77OitTZ4Ll1A=='
JAVA_MINIMATCH_DERIVED = 'sha512-d4q29f9UKl/jVXZqsE8JNas2oBfjjDeYRQEzYfbPFlEOx3cNnrJzyS48JO1wCCqcRAjOnDnkQfCKcCXFAyuLow=='
JAVA_MINIMATCH_ASSETS = {'upstream': {'snapshot': '.github/security/actions/setup-java-minimatch/minimatch-10.2.6.original.tgz',
              'source': '.lsf-source/minimatch-10.2.6.original.tgz',
              'bytes': 117068,
              'sha256': '5a3d2c8074a28229665727e47b8a1090941856a7962905efe05d20d3760355f8',
              'gitBlob': 'cc4d199bec4264ab80b9b228da85f074b045edf5'},
 'archive': {'snapshot': '.github/security/actions/setup-java-minimatch/minimatch-10.2.6.repaired.tar',
             'source': '.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar',
             'bytes': 583680,
             'sha256': 'bb2b80a4759baaee01d49528b2d7d0c05fc29c1cf0d3fea41ec243de04bceedb',
             'gitBlob': '2a1f40a7420f3cfb13e5284e433b19ec6db1e145'},
 'repair': {'snapshot': '.github/security/actions/setup-java-minimatch/repair.json',
            'source': '.lsf-source/minimatch-10.2.6-lsf-bound-v1.repair.json',
            'bytes': 2129,
            'sha256': 'd6ede52113aa8cb2d4b6ee008885fd2de0d37e06d822e444846f6f905f088bf3',
            'gitBlob': '42886b2bc898bf44b955fc31ff963bb91a94bcc9'},
 'verifier': {'snapshot': '.github/security/actions/setup-java-minimatch/installed-verifier.mjs.snapshot',
              'source': '.lsf-source/verify-installed-minimatch.mjs',
              'bytes': 3386,
              'sha256': '4af8eaff4b0b6f6b4b084ceeab68932ba8940048c9e49f9ed8fdc400e9e2f72d',
              'gitBlob': 'de5fadac0ee90bd532c5683fd4bcb919634a4314'},
 'tests': {'snapshot': '.github/security/actions/setup-java-minimatch/bounds.test.mjs.snapshot',
           'source': '.lsf-source/minimatch-bounds.test.mjs',
           'bytes': 2854,
           'sha256': '4fd2675946ecfa56ccf5a3c59e76ef50a5dc7d84f0a37fefd47e0037c50a4492',
           'gitBlob': '11a4cf916b01dfa3af9af699aa7ec641b39505d3'},
 'build': {'snapshot': '.github/security/actions/setup-java-minimatch/fork-build.json',
           'source': 'https://github.com/KirilsTurkins/lsf-setup-java/actions/runs/42018824336',
           'bytes': 4502,
           'sha256': '5ef60e180638361b91cccb232626b72cd464ba7b8273853a549337c4ceada659',
           'gitBlob': '3664d7808bde355ab0d81def683c16827bb3bab1'}}
JAVA_MINIMATCH_RUNTIME = {'runtime_setup': {'source': 'dist/setup/index.js',
                   'bytes': 1251705,
                   'sha256': 'ff49684899199004e6e3380d810250c997a7cb048e3745da83fda98f453e9676',
                   'gitBlob': '30825bde03691bc19d0bedf4940502dd88b9eb3c'},
 'runtime_cleanup': {'source': 'dist/cleanup/index.js',
                     'bytes': 1218262,
                     'sha256': 'a80e9a57c660b86e26f33ff4eb9d82dd21fc1b1e9e86f56356a7c81940d74199',
                     'gitBlob': 'ca82b3e3ea8bbb19bffdf17d561d21ebea122737'},
 'runtime_setup_chunk': {'source': 'dist/setup/971.index.js',
                         'bytes': 2110720,
                         'sha256': '9e2349fe3b6710fe498e054cee0fe370c0f890b6797075eb418c78a2ec35ce66',
                         'gitBlob': '6a9586ecbde45df1f4eedae5fab7cec16a644bb4'},
 'runtime_cleanup_chunk': {'source': 'dist/cleanup/767.index.js',
                           'bytes': 2337528,
                           'sha256': '491ce8398cfdd5123602e3765a3f70e7ce559c3f66d831cad7eba78e3ab42f8f',
                           'gitBlob': 'e934099b2849c0ece1ad64514da7b2d3a4f4ce2e'}}

NODE_MINIMATCH_PROFILE = 'setup-node-minimatch-action-source-v1'
NODE_MINIMATCH_PREFIX = '.github/security/actions/setup-node/'
NODE_MINIMATCH_ARCHIVE = 'file:.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar'
NODE_MINIMATCH_UPSTREAM = 'sha512-vpLQEs+VLCr1nU0BXS07maYoFwlDAH0gngQuuttxIwutDFEMHq2blX+8vpgxDdK3J1PwjCJiep77OitTZ4Ll1A=='
NODE_MINIMATCH_DERIVED = 'sha512-d4q29f9UKl/jVXZqsE8JNas2oBfjjDeYRQEzYfbPFlEOx3cNnrJzyS48JO1wCCqcRAjOnDnkQfCKcCXFAyuLow=='
NODE_MINIMATCH_ASSETS = {'upstream': {'snapshot': '.github/security/actions/setup-node-minimatch/minimatch-10.2.6.original.tgz',
              'source': '.lsf-source/minimatch-10.2.6.original.tgz',
              'bytes': 117068,
              'sha256': '5a3d2c8074a28229665727e47b8a1090941856a7962905efe05d20d3760355f8',
              'gitBlob': 'cc4d199bec4264ab80b9b228da85f074b045edf5'},
 'archive': {'snapshot': '.github/security/actions/setup-node-minimatch/minimatch-10.2.6.repaired.tar',
             'source': '.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar',
             'bytes': 583680,
             'sha256': 'bb2b80a4759baaee01d49528b2d7d0c05fc29c1cf0d3fea41ec243de04bceedb',
             'gitBlob': '2a1f40a7420f3cfb13e5284e433b19ec6db1e145'},
 'repair': {'snapshot': '.github/security/actions/setup-node-minimatch/repair.json',
            'source': '.lsf-source/minimatch-10.2.6-lsf-bound-v1.repair.json',
            'bytes': 2129,
            'sha256': 'd6ede52113aa8cb2d4b6ee008885fd2de0d37e06d822e444846f6f905f088bf3',
            'gitBlob': '42886b2bc898bf44b955fc31ff963bb91a94bcc9'},
 'verifier': {'snapshot': '.github/security/actions/setup-node-minimatch/installed-verifier.mjs.snapshot',
              'source': '.lsf-source/verify-installed-minimatch.mjs',
              'bytes': 3386,
              'sha256': '4af8eaff4b0b6f6b4b084ceeab68932ba8940048c9e49f9ed8fdc400e9e2f72d',
              'gitBlob': 'de5fadac0ee90bd532c5683fd4bcb919634a4314'},
 'tests': {'snapshot': '.github/security/actions/setup-node-minimatch/bounds.test.mjs.snapshot',
           'source': '.lsf-source/minimatch-bounds.test.mjs',
           'bytes': 2854,
           'sha256': '4fd2675946ecfa56ccf5a3c59e76ef50a5dc7d84f0a37fefd47e0037c50a4492',
           'gitBlob': '11a4cf916b01dfa3af9af699aa7ec641b39505d3'},
 'build': {'snapshot': '.github/security/actions/setup-node-minimatch/fork-build.json',
           'source': 'https://github.com/KirilsTurkins/lsf-setup-node/actions/runs/42024002011',
           'bytes': 4192,
           'sha256': 'd7ee2d1bbac34657eaff166f41f73241d2f8949ad9d4b66f81dbec9ca2b141a6',
           'gitBlob': '4671842ffc93cb16243f9524b9c42e928d5f5ac6'}}
NODE_MINIMATCH_RUNTIME = {'runtime_setup': {'source': 'dist/setup/index.js',
                   'bytes': 3555939,
                   'sha256': '18ead6d4a193f3fc6fce80fdd43e2c9bf520f3d55e3ec42079fe95f1933a69c5',
                   'gitBlob': '6735142fc160300df2fb85d4bc933fa0a4365804'},
 'runtime_cache': {'source': 'dist/cache-save/index.js',
                   'bytes': 3287509,
                   'sha256': '33f37c286e9765085b6780714206fb1591676cf388b0db9ea9d36670df47aab5',
                   'gitBlob': '68100fddb4b9fc91fe6ba7f1f46e6f29a1dd4bf8'}}

def source_identity(raw: bytes) -> dict:
    return {"bytes": len(raw), "sha256": digest(raw),
            "gitBlob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def bytecodealliance_source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    require(set(entry) == {"kind", "path", "lock", "source_repair"}
            and entry["kind"] == "npm" and entry["source_repair"] == BCA_PROFILE
            and entry["path"] == BCA_PREFIX + "package.json"
            and entry["lock"] == BCA_PREFIX + "package-lock.json", "unreviewed-bytecodealliance-profile")
    material, bound = {}, {}
    for source, (snapshot, size, sha256, blob) in (BCA_INPUTS | BCA_MATERIAL).items():
        raw = read_file(repo, snapshot)
        require(source_identity(raw) == {"bytes": size, "sha256": sha256, "gitBlob": blob},
                "bytecodealliance-source-input-drift")
        if source in BCA_MATERIAL:
            material[source] = raw
        else:
            bound[source] = raw
    require(decode_json(bound["package.json"]) == owner
            and decode_json(bound["package-lock.json"]) == lock,
            "bytecodealliance-parsed-input-drift")
    node = lock["packages"].get("node_modules/deepmerge", {})
    require(owner.get("devDependencies", {}).get("deepmerge") == CHECKOUT_ARCHIVE
            and "deepmerge" not in owner.get("dependencies", {})
            and "deepmerge" not in owner.get("overrides", {})
            and node.get("version") == "4.3.1" and node.get("dev") is True
            and node.get("resolved") == CHECKOUT_ARCHIVE
            and node.get("integrity") == integrity(material["archive"])
            and [path for path in lock["packages"] if path.rsplit("node_modules/", 1)[-1] == "deepmerge"]
                == ["node_modules/deepmerge"], "unlocked-bytecodealliance-source-graph")
    actions = decode_json(read_file(repo, ".github/security/actions.json"))["actions"]
    action = actions.get(BCA_REFERENCE, {})
    expected = [{"snapshot": snapshot, "source": source, "sha256": sha256, "source_sha256": sha256}
                for source, (snapshot, _, sha256, _) in BCA_INPUTS.items()]
    metadata = next(row for row in expected if row["source"] == "wasm-tools/setup/action.yml")
    require(action.get("repository") == "KirilsTurkins/lsf-bytecodealliance-actions"
            and action.get("revision") == BCA_REFERENCE.split("@")[1] and action.get("kind") == "npm"
            and isinstance(action.get("files"), list)
            and sorted(action["files"], key=lambda row: row["source"]) == sorted(expected, key=lambda row: row["source"])
            and action.get("metadata") == metadata, "bytecodealliance-action-binding-drift")
    build = decode_json(material["build"])
    result = build["result"]
    require(build["schema"] == 1 and build["repository"] == "KirilsTurkins/lsf-bytecodealliance-actions"
            and build["publishedRevision"] == BCA_REFERENCE.split("@")[1]
            and build["publishedTree"] == build["builtTree"] == result["sourceTree"] == "578e888fbea3faf619b37e947f749242001b2aa0"
            and build["builtHead"] == result["sourceCommit"] == "60bd0613e09bef8a77464828b6d476147aeb3385"
            and build["buildRun"] == 42020735461 and build["buildJob"] == 127222560199
            and build["buildConclusion"] == "success" and build["diagnosticRun"] == 42021497437
            and build["diagnosticJob"] == 127225111043 and build["diagnosticConclusion"] == "success"
            and result["status"] == "passed"
            and build["diagnosticHead"] == result["diagnosticCommit"] == "86892eb98aa1cb9ef3e2eacace772ce507c5e6a9"
            and build["artifact"] == {"id": 13411193511, "bytes": 707,
                "sha256": "0aa9cc0d447423cf836287a9d378583daf29fab05f8a580b7ff9ed6c68632d0e", "crcVerified": True},
            "bytecodealliance-build-evidence-drift")
    return {"policy": {"advisories": BCA_ADVISORIES}, "material": material,
            "reference": BCA_REFERENCE, "checkout": False, "bytecodealliance": True}


def action_source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict | None:
    """Recognize one published action graph; registry-only historical graphs stay ordinary."""
    if entry.get("source_repair") is None:
        return None
    profile = entry["source_repair"]
    if profile == BCA_PROFILE:
        return bytecodealliance_source_inputs(repo, entry, owner, lock)
    if profile == security_setup_go.DEEP_PROFILE:
        return security_setup_go.source_inputs(repo, entry, owner, lock)
    if profile == security_upload_artifact.DEEP_PROFILE:
        return security_upload_artifact.source_inputs(repo, entry, owner, lock)
    prefixes = [prefix for prefix in ACTION_REFERENCES if entry["path"] == prefix + "package.json"
                and entry["lock"] == prefix + "package-lock.json"]
    require((profile == CHECKOUT_PROFILE
             and entry["path"] == CHECKOUT_PREFIX + "package.json"
             and entry["lock"] == CHECKOUT_PREFIX + "package-lock.json")
            or (profile == ACTION_PROFILE and len(prefixes) == 1),
            "unreviewed-action-source-profile")
    target = lock["packages"].get("node_modules/deepmerge", {})
    if target.get("resolved", "").startswith("https://registry.npmjs.org/"):
        return None
    policy = decode_json(read_file(POLICY, "action-source-repairs.json"))
    require(set(policy) == {"schema", "profile", "action", "source_role", "additional_actions",
                            "bindings", "assets", "advisories", "runtime_bundle"}
            and policy["schema"] == 1 and policy["profile"] == CHECKOUT_PROFILE
            and policy["action"] == CHECKOUT_REFERENCE and policy["source_role"] == "development-build-tool"
            and set(policy["bindings"]) == {"manifest", "lock", "metadata"}
            and set(policy["assets"]) == {"archive", "repair", "declaration", "verifier", "workflow", "upstream", "build"},
            "invalid-action-source-policy")
    material = {}
    rows = policy["bindings"] | policy["assets"] if profile == CHECKOUT_PROFILE else {
        key: policy["assets"][key] for key in ("archive", "repair", "declaration", "upstream")}
    for key, row in rows.items():
        require(set(row) == {"snapshot", "source", "role", "bytes", "sha256", "gitBlob"}
                and row["snapshot"].startswith(CHECKOUT_PREFIX if key in policy["bindings"]
                                               else ".github/security/actions/checkout-source/"),
                "invalid-action-source-input")
        raw = read_file(repo, row["snapshot"])
        require(source_identity(raw) == {field: row[field] for field in ("bytes", "sha256", "gitBlob")},
                "action-source-input-drift")
        material[key] = raw
    require((profile != CHECKOUT_PROFILE
             or (policy["bindings"]["manifest"]["snapshot"] == entry["path"]
                 and policy["bindings"]["lock"]["snapshot"] == entry["lock"]))
            and owner.get("devDependencies", {}).get("deepmerge") == CHECKOUT_ARCHIVE
            and "deepmerge" not in owner.get("overrides", {}) and target.get("version") == "4.3.1"
            and target.get("resolved") == CHECKOUT_ARCHIVE
            and target.get("integrity") == integrity(material["archive"])
            and [path for path in lock["packages"] if path.rsplit("node_modules/", 1)[-1] == "deepmerge"]
                == ["node_modules/deepmerge"], "unlocked-action-source-graph")
    actions = decode_json(read_file(repo, ".github/security/actions.json"))["actions"]
    if profile == CHECKOUT_PROFILE:
        reference = CHECKOUT_REFERENCE
        action = actions.get(reference, {})
        expected = [{"snapshot": row["snapshot"], "source": row["source"],
                     "sha256": row["sha256"], "source_sha256": row["sha256"]}
                    for row in policy["bindings"].values()]
        require(action.get("repository") == "KirilsTurkins/lsf-checkout"
                and action.get("revision") == reference.split("@")[1]
                and action.get("kind") == "npm" and isinstance(action.get("files"), list)
                and sorted(action["files"], key=lambda row: row["source"])
                    == sorted(expected, key=lambda row: row["source"])
                and action.get("metadata") == expected[2], "action-source-revision-drift")
        return {"policy": policy, "material": material, "reference": reference, "checkout": True}

    additional = policy["additional_actions"]
    require(set(additional) == {"profile", "source_role", "references", "verifier"}
            and additional["profile"] == ACTION_PROFILE
            and additional["source_role"] == "development-build-tool"
            and additional["references"] == ACTION_REFERENCES, "invalid-additional-action-source-policy")
    verifier = additional["verifier"]
    require(set(verifier) == {"snapshot", "source", "role", "bytes", "sha256", "gitBlob"}
            and verifier["source"] == ACTION_VERIFIER_SOURCE
            and verifier["role"] == "installed-source-verifier"
            and source_identity(read_file(repo, verifier["snapshot"]))
                == {field: verifier[field] for field in ("bytes", "sha256", "gitBlob")},
            "additional-action-source-verifier-drift")
    prefix = prefixes[0]
    reference = ACTION_REFERENCES[prefix]
    bindings = [(reference, "action.yml", prefix + "action.yml.snapshot")]
    if prefix == CACHE_PREFIX:
        bindings = [(reference, "restore/action.yml", prefix + "restore/action.yml.snapshot"),
                    (CACHE_SAVE_REFERENCE, "save/action.yml", prefix + "save/action.yml.snapshot")]
    for action_reference, metadata_source, metadata_snapshot in bindings:
        action = actions.get(action_reference, {})
        rows = action.get("files", [])
        require(isinstance(rows, list), "action-source-revision-drift")
        files = {row.get("source"): row for row in rows}
        expected_sources = {metadata_source, "package.json", "package-lock.json", ACTION_VERIFIER_SOURCE}
        if entry.get("minimatch_source_repair") is not None:
            require((entry["minimatch_source_repair"] == MINIMATCH_PROFILE and prefix == MINIMATCH_PREFIX)
                    or (entry["minimatch_source_repair"] == JAVA_MINIMATCH_PROFILE
                        and prefix == JAVA_MINIMATCH_PREFIX)
                    or (entry["minimatch_source_repair"] == dotnet_sources.PROFILE
                        and prefix == dotnet_sources.PREFIX)
                    or (entry["minimatch_source_repair"] == NODE_MINIMATCH_PROFILE
                        and prefix == NODE_MINIMATCH_PREFIX),
                    "unreviewed-minimatch-action-profile")
            expected_sources.add(MINIMATCH_VERIFIER)
            if prefix in {JAVA_MINIMATCH_PREFIX, dotnet_sources.PREFIX, NODE_MINIMATCH_PREFIX}:
                expected_sources.add(".lsf-source/minimatch-bounds.test.mjs")
        repository = "/".join(action_reference.split("@", 1)[0].split("/")[:2])
        require(action.get("repository") == repository
                and action.get("revision") == action_reference.split("@")[1]
                and action.get("kind") == "npm" and len(rows) == len(files)
                and set(files) == expected_sources
                and files["package.json"]["snapshot"] == entry["path"]
                and files["package-lock.json"]["snapshot"] == entry["lock"]
                and files[metadata_source]["snapshot"] == metadata_snapshot
                and files[ACTION_VERIFIER_SOURCE] == {
                    "snapshot": verifier["snapshot"], "source": verifier["source"],
                    "sha256": verifier["sha256"], "source_sha256": verifier["sha256"]}
                and action.get("metadata") == files[metadata_source], "action-source-revision-drift")
        for source, row in files.items():
            require(row["sha256"] == row["source_sha256"]
                    and digest(read_file(repo, row["snapshot"])) == row["sha256"]
                    and (prefix != CACHE_PREFIX or row["sha256"] == CACHE_SOURCE_SHA256[source])
                    and (prefix != dotnet_sources.PREFIX or row["sha256"] == dotnet_sources.SOURCE_SHA256[source]),
                    "action-source-binding-drift")
    selected = {"policy": policy, "material": material, "reference": reference, "checkout": False}
    if prefix == CACHE_PREFIX:
        selected["related_actions"] = [CACHE_SAVE_REFERENCE]
    return selected


def minimatch_action_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict | None:
    if entry.get("minimatch_source_repair") is None:
        return None
    if entry["minimatch_source_repair"] == JAVA_MINIMATCH_PROFILE:
        return java_minimatch_action_inputs(repo, entry, owner, lock)
    if entry["minimatch_source_repair"] == dotnet_sources.PROFILE:
        return dotnet_sources.action_inputs(repo, entry, owner, lock)
    if entry["minimatch_source_repair"] == NODE_MINIMATCH_PROFILE:
        return node_minimatch_action_inputs(repo, entry, owner, lock)
    if entry["minimatch_source_repair"] == security_setup_go.MINI_PROFILE:
        return security_setup_go.minimatch_inputs(repo, entry, owner, lock)
    if entry["minimatch_source_repair"] == security_upload_artifact.PROFILE:
        return security_upload_artifact.minimatch_inputs(repo, entry, owner, lock)
    require(entry["minimatch_source_repair"] == MINIMATCH_PROFILE
            and entry.get("source_repair") == ACTION_PROFILE
            and entry["path"] == MINIMATCH_PREFIX + "package.json"
            and entry["lock"] == MINIMATCH_PREFIX + "package-lock.json",
            "unreviewed-minimatch-action-profile")
    policy = decode_json(read_file(POLICY, "minimatch-action-source-repairs.json"))
    reference = ACTION_REFERENCES[MINIMATCH_PREFIX]
    require(set(policy) == {"schema", "profile", "action", "advisories", "assets", "runtime"}
            and policy["schema"] == 1 and policy["profile"] == MINIMATCH_PROFILE
            and policy["action"] == reference and policy["advisories"] == MINIMATCH_ADVISORIES
            and policy["assets"] == MINIMATCH_ASSETS and policy["runtime"] == MINIMATCH_RUNTIME,
            "invalid-minimatch-action-policy")
    material = {}
    for name, row in MINIMATCH_ASSETS.items():
        raw = read_file(repo, row["snapshot"])
        require(source_identity(raw) == {key: row[key] for key in ("bytes", "sha256", "gitBlob")},
                "minimatch-action-asset-drift")
        material[name] = raw
    require(integrity(material["upstream"]) == MINIMATCH_UPSTREAM
            and integrity(material["archive"]) == MINIMATCH_DERIVED,
            "minimatch-action-integrity-drift")
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(reference, {})
    files = {row.get("source"): row for row in action.get("files", [])}
    binding = MINIMATCH_ASSETS["verifier"]
    require(files.get(binding["source"]) == {
                "snapshot": binding["snapshot"], "source": binding["source"],
                "sha256": binding["sha256"], "source_sha256": binding["sha256"]},
            "minimatch-action-verifier-binding-drift")
    require(action.get("metadata", {}).get("sha256") == "0829b3f54d769f8b25cefd4d856c735bc8e097d6597835b838ebb4da497c838d",
            "minimatch-action-entrypoint-drift")
    commands = owner.get("scripts", {})
    expected_build = ("node .lsf-source/verify-installed-deepmerge.mjs && "
                      "node .lsf-source/verify-installed-minimatch.mjs && "
                      "ncc build -o dist/setup src/setup-python.ts && "
                      "ncc build -o dist/cache-save src/cache-save.ts")
    require(commands.get("build") == expected_build and commands.get("release") == expected_build + " && git add -f dist/"
            and commands.get("test:security-source") == "node --test .lsf-source/minimatch-bounds.test.mjs",
            "minimatch-action-build-contract-drift")
    rows = [(path, row) for path, row in lock["packages"].items()
            if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == "minimatch"
            and str(row.get("version", "")).startswith("10.")]
    require(owner.get("devDependencies", {}).get("minimatch") == MINIMATCH_ARCHIVE
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and lock["packages"][""].get("devDependencies", {}).get("minimatch") == MINIMATCH_ARCHIVE
            and len(rows) == 1 and rows[0][0] == "node_modules/minimatch"
            and rows[0][1].get("version") == "10.2.5"
            and rows[0][1].get("resolved") == MINIMATCH_ARCHIVE
            and rows[0][1].get("integrity") == MINIMATCH_DERIVED,
            "unlocked-minimatch-action-source-graph")
    return {"policy": policy, "material": material, "reference": reference}


def java_minimatch_action_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    """Recognize only the reviewed setup-java graph and its immutable source assets."""
    require(entry.get("minimatch_source_repair") == JAVA_MINIMATCH_PROFILE
            and entry.get("source_repair") == ACTION_PROFILE
            and entry["path"] == JAVA_MINIMATCH_PREFIX + "package.json"
            and entry["lock"] == JAVA_MINIMATCH_PREFIX + "package-lock.json",
            "unreviewed-minimatch-action-profile")
    policy = decode_json(read_file(POLICY, "minimatch-java-action-source-repairs.json"))
    reference = ACTION_REFERENCES[JAVA_MINIMATCH_PREFIX]
    require(set(policy) == {"schema", "profile", "action", "advisories", "assets", "runtime"}
            and policy["schema"] == 1 and policy["profile"] == JAVA_MINIMATCH_PROFILE
            and policy["action"] == reference and policy["advisories"] == MINIMATCH_ADVISORIES
            and policy["assets"] == JAVA_MINIMATCH_ASSETS and policy["runtime"] == JAVA_MINIMATCH_RUNTIME,
            "invalid-java-minimatch-action-policy")
    material = {}
    for name, row in JAVA_MINIMATCH_ASSETS.items():
        raw = read_file(repo, row["snapshot"])
        require(source_identity(raw) == {key: row[key] for key in ("bytes", "sha256", "gitBlob")},
                "java-minimatch-action-asset-drift")
        material[name] = raw
    require(integrity(material["upstream"]) == JAVA_MINIMATCH_UPSTREAM
            and integrity(material["archive"]) == JAVA_MINIMATCH_DERIVED,
            "java-minimatch-action-integrity-drift")
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(reference, {})
    files = {row.get("source"): row for row in action.get("files", [])}
    for name in ("verifier", "tests"):
        binding = JAVA_MINIMATCH_ASSETS[name]
        require(files.get(binding["source"]) == {
                    "snapshot": binding["snapshot"], "source": binding["source"],
                    "sha256": binding["sha256"], "source_sha256": binding["sha256"]},
                "java-minimatch-action-verifier-binding-drift")
    require(action.get("metadata", {}).get("sha256") == "503fe82e787d5ff15e17934e2efab346fa2facfad7261a8ea6ed9b05cb14f9e8",
            "java-minimatch-action-entrypoint-drift")
    commands = owner.get("scripts", {})
    expected_build = ("node .lsf-source/verify-installed-deepmerge.mjs && "
                      "node .lsf-source/verify-installed-minimatch.mjs && "
                      "node scripts/patch-is-unsafe.mjs && "
                      "ncc build -o dist/setup src/setup-java.ts && "
                      "ncc build -o dist/cleanup src/cleanup-java.ts")
    require(commands.get("build") == expected_build
            and commands.get("release") == "git add -f dist/setup/*.js dist/setup/package.json dist/cleanup/*.js"
            and commands.get("test:security-source") == "node --test .lsf-source/minimatch-bounds.test.mjs",
            "java-minimatch-action-build-contract-drift")
    rows = [(path, row) for path, row in lock["packages"].items()
            if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == "minimatch"
            and str(row.get("version", "")).startswith("10.")]
    glob = lock["packages"].get("node_modules/@actions/glob", {})
    require(owner.get("devDependencies", {}).get("minimatch") == JAVA_MINIMATCH_ARCHIVE
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and owner.get("overrides", {}).get("glob") == "14.0.2"
            and lock["packages"][""].get("devDependencies", {}).get("minimatch") == JAVA_MINIMATCH_ARCHIVE
            and len(rows) == 1 and rows[0][0] == "node_modules/minimatch"
            and rows[0][1].get("version") == "10.2.6"
            and rows[0][1].get("resolved") == JAVA_MINIMATCH_ARCHIVE
            and rows[0][1].get("integrity") == JAVA_MINIMATCH_DERIVED
            and not rows[0][1].get("dev", False)
            and glob.get("version") == "0.7.0"
            and glob.get("dependencies", {}).get("minimatch") == "^10.2.5"
            and not glob.get("dev", False)
            and lock["packages"].get("node_modules/glob", {}).get("version") == "14.0.2"
            and lock["packages"]["node_modules/glob"].get("dev") is True,
            "unlocked-java-minimatch-action-source-graph")
    return {"policy": policy, "material": material, "reference": reference}


def node_minimatch_action_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    """Recognize only the reviewed setup-node graph and its immutable source assets."""
    require(entry.get("minimatch_source_repair") == NODE_MINIMATCH_PROFILE
            and entry.get("source_repair") == ACTION_PROFILE
            and entry["path"] == NODE_MINIMATCH_PREFIX + "package.json"
            and entry["lock"] == NODE_MINIMATCH_PREFIX + "package-lock.json",
            "unreviewed-minimatch-action-profile")
    policy = decode_json(read_file(POLICY, "minimatch-node-action-source-repairs.json"))
    reference = ACTION_REFERENCES[NODE_MINIMATCH_PREFIX]
    require(set(policy) == {"schema", "profile", "action", "advisories", "assets", "runtime"}
            and policy["schema"] == 1 and policy["profile"] == NODE_MINIMATCH_PROFILE
            and policy["action"] == reference and policy["advisories"] == MINIMATCH_ADVISORIES
            and policy["assets"] == NODE_MINIMATCH_ASSETS and policy["runtime"] == NODE_MINIMATCH_RUNTIME,
            "invalid-node-minimatch-action-policy")
    material = {}
    for name, row in NODE_MINIMATCH_ASSETS.items():
        raw = read_file(repo, row["snapshot"])
        require(source_identity(raw) == {key: row[key] for key in ("bytes", "sha256", "gitBlob")},
                "node-minimatch-action-asset-drift")
        material[name] = raw
    require(integrity(material["upstream"]) == NODE_MINIMATCH_UPSTREAM
            and integrity(material["archive"]) == NODE_MINIMATCH_DERIVED,
            "node-minimatch-action-integrity-drift")
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(reference, {})
    files = {row.get("source"): row for row in action.get("files", [])}
    for name in ("verifier", "tests"):
        binding = NODE_MINIMATCH_ASSETS[name]
        require(files.get(binding["source"]) == {
                    "snapshot": binding["snapshot"], "source": binding["source"],
                    "sha256": binding["sha256"], "source_sha256": binding["sha256"]},
                "node-minimatch-action-verifier-binding-drift")
    require(action.get("metadata", {}).get("sha256") == "84cd55863dbadfb83ed786c0bb4336553c2f4ceb52e102fccec01848f1977387",
            "node-minimatch-action-entrypoint-drift")
    commands = owner.get("scripts", {})
    expected_build = ("node .lsf-source/verify-installed-deepmerge.mjs && "
                      "node .lsf-source/verify-installed-minimatch.mjs && "
                      "ncc build -o dist/setup src/setup-node.ts && "
                      "ncc build -o dist/cache-save src/cache-save.ts")
    require(commands.get("build") == expected_build
            and commands.get("pre-checkin") == "npm run format && npm run lint:fix && npm run build && npm test"
            and commands.get("test:security-source") == "node --test .lsf-source/minimatch-bounds.test.mjs",
            "node-minimatch-action-build-contract-drift")
    rows = [(path, row) for path, row in lock["packages"].items()
            if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == "minimatch"
            and str(row.get("version", "")).startswith("10.")]
    glob = lock["packages"].get("node_modules/@actions/glob", {})
    require(owner.get("devDependencies", {}).get("minimatch") == NODE_MINIMATCH_ARCHIVE
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and owner.get("overrides", {}).get("glob@10") == "14.0.2"
            and lock["packages"][""].get("devDependencies", {}).get("minimatch") == NODE_MINIMATCH_ARCHIVE
            and len(rows) == 1 and rows[0][0] == "node_modules/minimatch"
            and rows[0][1].get("version") == "10.2.6"
            and rows[0][1].get("resolved") == NODE_MINIMATCH_ARCHIVE
            and rows[0][1].get("integrity") == NODE_MINIMATCH_DERIVED
            and not rows[0][1].get("dev", False)
            and glob.get("version") == "0.7.0"
            and glob.get("dependencies", {}).get("minimatch") == "^10.2.5"
            and not glob.get("dev", False)
            and lock["packages"].get("node_modules/glob", {}).get("version") == "14.0.2"
            and lock["packages"]["node_modules/glob"].get("dev") is True
            and lock["packages"].get("node_modules/babel-plugin-istanbul/node_modules/glob", {}).get("version") == "7.2.3"
            and lock["packages"].get("node_modules/babel-plugin-istanbul/node_modules/minimatch", {}).get("version") == "3.1.5",
            "unlocked-node-minimatch-action-source-graph")
    return {"policy": policy, "material": material, "reference": reference}


def action_library_sources(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    selected = action_source_inputs(repo, entry, owner, lock)
    libraries = {} if selected is None else {"deepmerge": {
        "version": "4.3.1", "resolved": CHECKOUT_ARCHIVE,
        "integrity": integrity(selected["material"]["archive"])}}
    minimatch = minimatch_action_inputs(repo, entry, owner, lock)
    if minimatch is not None:
        require(selected is not None, "minimatch-action-base-source-missing")
        if entry["minimatch_source_repair"] == security_upload_artifact.PROFILE:
            libraries.update(security_upload_artifact.libraries())
        elif entry["minimatch_source_repair"] == JAVA_MINIMATCH_PROFILE:
            libraries["minimatch"] = {"version": "10.2.6", "resolved": JAVA_MINIMATCH_ARCHIVE,
                                      "integrity": JAVA_MINIMATCH_DERIVED}
        elif entry["minimatch_source_repair"] == NODE_MINIMATCH_PROFILE:
            libraries["minimatch"] = {"version": "10.2.6", "resolved": NODE_MINIMATCH_ARCHIVE,
                                      "integrity": NODE_MINIMATCH_DERIVED}
        else:
            libraries["minimatch"] = {"version": "10.2.5", "resolved": MINIMATCH_ARCHIVE,
                                      "integrity": MINIMATCH_DERIVED}
    return libraries


def verify_action_sources(repo: Path, packages: list, configuration: dict, fetch=registry_archive) -> list[dict]:
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("source_repair") is None or not any(item.path == entry["lock"] for item in packages):
            continue
        selected = action_source_inputs(repo, entry, decode_json(read_file(repo, entry["path"])),
                                        decode_json(read_file(repo, entry["lock"])))
        if selected is None:
            continue
        policy, material = selected["policy"], selected["material"]
        declaration, repair = (decode_json(material[key]) for key in ("declaration", "repair"))
        pin = {"name": "deepmerge", "version": "4.3.1", "integrity": declaration["upstream"]["integrity"]}
        upstream = fetch(pin)
        require(upstream == material["upstream"] and integrity(upstream) == pin["integrity"],
                "action-source-upstream-drift")
        original = members(upstream)
        manifest(original, pin["name"], pin["version"], {})
        repaired = source_repair(original, repair, pin)
        require(distribution(repaired) == material["archive"]
                and declaration["profile"] == repair["profile"]
                and declaration["repair"]["sha256"] == digest(material["repair"])
                and declaration["derived"]["integrity"] == integrity(material["archive"])
                and declaration["forkBuildVerified"] is False
                and declaration["runtimeOrSignedSDKQualified"] is False
                and declaration["notAnUpstreamFixedRelease"] is True,
                "action-source-reconstruction-drift")
        require(len(declaration["fileIdentities"]) == len(original)
                and {row["path"] for row in declaration["fileIdentities"]}
                    == {path.removeprefix("package/") for path in original}, "action-source-file-coverage")
        for row in declaration["fileIdentities"]:
            key = "package/" + row["path"]
            require(row["before"] == source_identity(original[key][0])
                    and row["after"] == source_identity(repaired[key][0])
                    and row["mode"] == oct(original[key][1]) == oct(repaired[key][1]),
                    "action-source-file-drift")
        receipt = {"name": pin["name"], "version": pin["version"],
                   "profile": (security_setup_go.DEEP_PROFILE if selected.get("setup_go") else
                               BCA_PROFILE if selected.get("bytecodealliance") else
                               policy["profile"] if selected["checkout"] else ACTION_PROFILE),
                   "upstream_integrity": pin["integrity"],
                   "derived_integrity": integrity(material["archive"]),
                   "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                   "locks": [entry["lock"]], "advisories": policy["advisories"],
                   "action": selected["reference"], "source_role": "development-build-tool"}
        if selected["checkout"]:
            build = decode_json(material["build"])
            review = build["artifactReview"]
            installed = review["installed"]
            require(build["repository"] == "KirilsTurkins/lsf-checkout"
                    and build["publishedRevision"] == CHECKOUT_REFERENCE.split("@")[1]
                    and build["builtHead"] == installed["sourceCommit"] == "4d310727149d3abacc52b5dcb0a1c4d18b345d13"
                    and build["builtTree"] == build["publishedTree"] == "81dab5f9c6afaf3a60de1d3c46f2629c86f44e94"
                    and build["run"] == 41993289481 and build["job"] == 127130383712
                    and build["jobConclusion"] == "success" and build["node"] == installed["node"] == "24.19.0"
                    and build["npm"] == "11.17.0"
                    and build["existingBuildFormatLintJestAndStrictDistReadmeComparisonPassed"] is True
                    and review["installedSourceVerified"] is True
                    and review["existingJestTestsPassed"] == 128 and review["existingJestSuitesPassed"] == 10
                    and installed["repairSha256"] == digest(material["repair"])
                    and installed["installedPostimages"]
                        == {row["path"]: row["afterSha256"] for row in repair["files"]},
                    "action-source-build-evidence-drift")
            require(policy["runtime_bundle"] == {
                        "source": "dist/index.js", "bytes": 1465687,
                        "sha256": "116aa6f7b8efa570e95179673c8d067b39069df63915f0b805a413723b798cac",
                        "gitBlob": "8f3d1593c2f1b48addb8c63595f6ea2f1d188b85"},
                    "action-source-runtime-identity-drift")
            for name, source in (("manifest", "package.json"), ("lock", "package-lock.json"),
                                 ("runtime_bundle", "dist/index.js")):
                binding = policy[name] if name == "runtime_bundle" else policy["bindings"][name]
                require(review["payloads"]["lsf-checkout/lsf-checkout/" + source]
                        == {field: binding[field] for field in ("bytes", "sha256")},
                        "action-source-built-input-drift")
            receipt.update({"built_tree": build["builtTree"], "build_run": build["run"]})
        elif selected.get("setup_go"):
            receipt.update({"verifier_sha256": security_setup_go.ACTION_INPUTS[security_setup_go.DEEP_VERIFIER][2],
                            "built_tree": "586d487e144d8cf393893459b6678118d0b5dc92", "build_run": 42024368583})
        elif selected.get("upload_artifact"):
            receipt.update({"verifier_sha256": security_upload_artifact.ACTION_INPUTS[security_upload_artifact.DEEP_VERIFIER][2],
                            "built_tree": security_upload_artifact.TREE, "build_run": security_upload_artifact.RUN})
        elif selected.get("bytecodealliance"):
            receipt.update({"verifier_sha256": BCA_INPUTS[ACTION_VERIFIER_SOURCE][2],
                            "built_tree": "578e888fbea3faf619b37e947f749242001b2aa0",
                            "build_run": 42020735461, "diagnostic_run": 42021497437})
        else:
            receipt["verifier_sha256"] = policy["additional_actions"]["verifier"]["sha256"]
            if "related_actions" in selected:
                receipt["related_actions"] = selected["related_actions"]
        receipts.append(receipt)
    return receipts



def action_runtime(reference: str, source: str) -> bytes:
    """Read a bounded committed action bundle without accepting redirects."""
    repository, revision = reference.rsplit("@", 1)
    require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None
            and ((reference == ACTION_REFERENCES[MINIMATCH_PREFIX]
                  and source in {row["source"] for row in MINIMATCH_RUNTIME.values()})
                 or (reference == ACTION_REFERENCES[JAVA_MINIMATCH_PREFIX]
                     and source in {row["source"] for row in JAVA_MINIMATCH_RUNTIME.values()})
                 or (reference == dotnet_sources.REFERENCE
                     and source in {row["source"] for row in dotnet_sources.RUNTIME.values()})
                 or (reference == ACTION_REFERENCES[NODE_MINIMATCH_PREFIX]
                     and source in {row["source"] for row in NODE_MINIMATCH_RUNTIME.values()})
                 or (reference == security_setup_go.REFERENCE and source in security_setup_go.RUNTIME)
                 or (reference == security_upload_artifact.REFERENCE and source in security_upload_artifact.RUNTIME)),
            "invalid-minimatch-action-runtime-source")
    url = f"https://raw.githubusercontent.com/{repository}/{revision}/{source}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    started = monotonic()
    content = bytearray()
    with opener.open(url, timeout=30) as response:
        require(response.status == 200 and response.url == url, "minimatch-action-runtime-unavailable")
        while True:
            require(monotonic() - started <= 30, "minimatch-action-runtime-deadline")
            chunk = response.read1(65536)
            require(monotonic() - started <= 30, "minimatch-action-runtime-deadline")
            if not chunk:
                break
            content.extend(chunk)
            require(len(content) <= MINIMATCH_RUNTIME_LIMIT, "minimatch-action-runtime-size-limit")
    return bytes(content)


def verify_minimatch_action_sources(repo: Path, packages: list, configuration: dict,
                                    fetch=registry_archive, fetch_runtime=None) -> list[dict]:
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("minimatch_source_repair") is None or not any(item.path == entry["lock"] for item in packages):
            continue
        if entry["minimatch_source_repair"] in {JAVA_MINIMATCH_PROFILE, dotnet_sources.PROFILE, NODE_MINIMATCH_PROFILE,
                                                  security_setup_go.MINI_PROFILE, security_upload_artifact.PROFILE}:
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        selected = minimatch_action_inputs(repo, entry, owner, lock)
        material = selected["material"]
        for runtime in MINIMATCH_RUNTIME.values():
            raw = (fetch_runtime or action_runtime)(selected["reference"], runtime["source"])
            require(source_identity(raw) == {key: runtime[key] for key in ("bytes", "sha256", "gitBlob")},
                    "minimatch-action-runtime-drift")
        pin = {"name": "minimatch", "version": "10.2.5", "integrity": MINIMATCH_UPSTREAM}
        upstream = fetch(pin)
        require(upstream == material["upstream"] and integrity(upstream) == MINIMATCH_UPSTREAM,
                "minimatch-action-upstream-drift")
        original = members(upstream)
        value = manifest(original, "minimatch", "10.2.5", {"brace-expansion": "^5.0.5"})
        require(value.get("license") == "BlueOak-1.0.0"
                and digest(original["package/package.json"][0]) == "4b3a08a7ad20dead8bbe4b4fe97a2746bded7c51d218ef3034eb4e330ad31f08"
                and digest(original["package/LICENSE.md"][0]) == "2c7c5d22ed5a8ee968c64757710979afcd77438c48b4a265b94e615babd8a901",
                "minimatch-action-package-identity-drift")
        repair = decode_json(material["repair"])
        require(repair.get("profile") == "minimatch-10.2.5-lsf-bounds-v1",
                "minimatch-action-repair-profile")
        repaired = source_repair(original, repair, pin)
        require(distribution(repaired) == material["archive"]
                and integrity(material["archive"]) == MINIMATCH_DERIVED,
                "minimatch-action-reconstruction-drift")
        build = decode_json(material["build"])
        artifact = build["artifact"]
        installed = build["installed"]
        require(build["schema"] == 1 and build["repository"] == "KirilsTurkins/lsf-setup-python"
                and build["publishedRevision"] == selected["reference"].split("@")[1]
                and build["publishedTree"] == build["sourceTree"] == "bb7f6e0323dbc034b8d11ba691e3c4f3ac76355e"
                and build["sourceHead"] == "cc883652b3ad6f47c0fe0139ef4b0981f50ad59d"
                and build["diagnosticHead"] == installed["sourceCommit"] == "04f6cab165742580f50af5336587b8ddf6ccc063"
                and build["diagnosticTree"] == "5d6209aaa9b89357d4cc7233e46a94d5a1308e51"
                and build["diagnosticOnlyPath"] == ".github/workflows/lsf-setup-python-runtime-owner.yml"
                and build["run"] == 42010605694 and build["job"] == 127188354270
                and build["jobConclusion"] == "success" and build["node"] == installed["node"] == "24.19.0"
                and build["npm"] == "11.17.0" and build["jestSuites"] == 11 and build["jestTests"] == 249
                and build["focusedTests"] == 2
                and artifact["id"] == 13406518961 and artifact["bytes"] == 1817044
                and artifact["sha256"] == "62e0ab9584d507a4217d9d10ce03d3054babd1171c6b6abc0b1ef4fa7e7ee85d"
                and artifact["members"] == 11 and artifact["crcVerified"] is True
                and installed["version"] == "10.2.5" and installed["repairSha256"] == digest(material["repair"])
                and installed["installedPostimages"] == {row["path"]: row["afterSha256"] for row in repair["files"]},
                "minimatch-action-build-evidence-drift")
        expected_payloads = {
            "package.json": source_identity(read_file(repo, entry["path"])),
            "package-lock.json": source_identity(read_file(repo, entry["lock"])),
            **{MINIMATCH_ASSETS[name]["source"]: MINIMATCH_ASSETS[name]
               for name in ("upstream", "archive", "repair", "verifier")},
            **{row["source"]: row for row in MINIMATCH_RUNTIME.values()},
            ".lsf-source/minimatch-bounds.test.mjs": {"bytes": 2854, "sha256": "f65c9af8d0d6b2abfd728d803e223396e746850f564003e93b223c4f084f987b"},
            "installed-minimatch.json": {"bytes": 427, "sha256": "8ac9a2cf9039bfbc29c2f74d85271721259e062e208df9bdc52f9715d3c70337"},
        }
        require(set(artifact["payloads"]) == set(expected_payloads)
                and all(artifact["payloads"][path] == {key: identity[key] for key in ("bytes", "sha256")}
                        for path, identity in expected_payloads.items()),
                "minimatch-action-built-input-drift")
        receipts.append({"name": pin["name"], "version": pin["version"], "profile": MINIMATCH_PROFILE,
                         "upstream_integrity": MINIMATCH_UPSTREAM, "derived_integrity": MINIMATCH_DERIVED,
                         "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                         "locks": [entry["lock"]], "advisories": MINIMATCH_ADVISORIES,
                         "action": selected["reference"], "source_role": "action-runtime-and-build",
                         "built_tree": build["publishedTree"], "build_run": build["run"]})
    return receipts


def verify_java_minimatch_action_sources(repo: Path, packages: list, configuration: dict,
                                         fetch=registry_archive, fetch_runtime=None) -> list[dict]:
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("minimatch_source_repair") != JAVA_MINIMATCH_PROFILE:
            continue
        if not any(item.path == entry["lock"] for item in packages):
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        selected = java_minimatch_action_inputs(repo, entry, owner, lock)
        material = selected["material"]
        deepmerge = action_source_inputs(repo, entry, owner, lock)
        require(deepmerge is not None and deepmerge["reference"] == selected["reference"],
                "java-minimatch-action-base-source-missing")
        for runtime in JAVA_MINIMATCH_RUNTIME.values():
            raw = (fetch_runtime or action_runtime)(selected["reference"], runtime["source"])
            require(source_identity(raw) == {key: runtime[key] for key in ("bytes", "sha256", "gitBlob")},
                    "java-minimatch-action-runtime-drift")
        pin = {"name": "minimatch", "version": "10.2.6", "integrity": JAVA_MINIMATCH_UPSTREAM}
        upstream = fetch(pin)
        require(upstream == material["upstream"] and integrity(upstream) == JAVA_MINIMATCH_UPSTREAM,
                "java-minimatch-action-upstream-drift")
        original = members(upstream)
        value = manifest(original, "minimatch", "10.2.6", {"brace-expansion": "^5.0.8"})
        require(value.get("license") == "BlueOak-1.0.0"
                and digest(original["package/package.json"][0]) == "bb847ba240909c9a36d4eaeb4e0efdc3e31182aeef208c1611259a48f282ea75"
                and digest(original["package/LICENSE.md"][0]) == "2c7c5d22ed5a8ee968c64757710979afcd77438c48b4a265b94e615babd8a901",
                "java-minimatch-action-package-identity-drift")
        repair = decode_json(material["repair"])
        require(repair.get("profile") == "minimatch-10.2.6-lsf-bounds-v1",
                "java-minimatch-action-repair-profile")
        repaired = source_repair(original, repair, pin)
        require(distribution(repaired) == material["archive"]
                and integrity(material["archive"]) == JAVA_MINIMATCH_DERIVED,
                "java-minimatch-action-reconstruction-drift")
        build = decode_json(material["build"])
        artifact, installed = build["artifact"], build["installed"]
        require(build["schema"] == 1 and build["repository"] == "KirilsTurkins/lsf-setup-java"
                and build["publishedRevision"] == selected["reference"].split("@")[1]
                and build["publishedTree"] == build["sourceTree"] == "da1077784074c8a0e949947c4607452c36574dc1"
                and build["sourceHead"] == "10dfad9fb7484f2f1b39c5b50ffa86f9e56d8f63"
                and build["diagnosticHead"] == installed["sourceCommit"] == "eaa32fe679a4d1ab0dbee73cf502e7890ca8a3df"
                and build["diagnosticTree"] == "993c8fb074c123fb8eac870ba992bf2783ba70c2"
                and build["diagnosticOnlyPath"] == ".github/workflows/lsf-setup-java-security-owner.yml"
                and build["run"] == 42018824336 and build["job"] == 127216070011
                and build["jobConclusion"] == "success" and build["node"] == installed["node"] == "24.19.0"
                and build["npm"] == "11.17.0" and build["jestSuites"] == 45 and build["jestTests"] == 1596
                and build["focusedTests"] == 2
                and artifact["id"] == 13411055962 and artifact["bytes"] == 1784025
                and artifact["sha256"] == "b9fc7c65de7bac2b146e09f00f3ef8f9b5e42b4eee9e3f2d4d588a76d3cdce42"
                and artifact["members"] == 25 and artifact["crcVerified"] is True
                and installed["kind"] == "installed-minimatch-source-assertion"
                and installed["version"] == "10.2.6" and installed["repairSha256"] == digest(material["repair"])
                and installed["installedPostimages"] == {row["path"]: row["afterSha256"] for row in repair["files"]},
                "java-minimatch-action-build-evidence-drift")
        deep_policy = deepmerge["policy"]
        deep_assets = [deep_policy["assets"][name] for name in ("archive", "repair", "declaration")]
        deep_assets.append(deep_policy["additional_actions"]["verifier"])
        expected_payloads = {
            "action.yml": source_identity(read_file(repo, JAVA_MINIMATCH_PREFIX + "action.yml.snapshot")),
            "package.json": source_identity(read_file(repo, entry["path"])),
            "package-lock.json": source_identity(read_file(repo, entry["lock"])),
            **{JAVA_MINIMATCH_ASSETS[name]["source"]: JAVA_MINIMATCH_ASSETS[name]
               for name in ("upstream", "archive", "repair", "verifier", "tests")},
            **{row["source"]: row for row in JAVA_MINIMATCH_RUNTIME.values()},
            **{row["source"]: row for row in deep_assets},
            "installed-minimatch.json": {"bytes": 427, "sha256": "54ac8017be7e2e70e951d5da094afa1125e6fafa4be2fa3404c48784d5281266"},
            "installed-deepmerge.json": {"bytes": 524, "sha256": "b4728f29efd94c5698267321d3d838744ea3e47a7f433a1a7b92770ffb1aa362"},
            "source-identities.txt": {"bytes": 123, "sha256": "11fce0fce872b0f3e3e7fd3b4f03c403133d48c4c669e62fc54cf87badd23035"},
        }
        require(set(artifact["payloads"]) == set(expected_payloads)
                and all(artifact["payloads"][path] == {key: identity[key] for key in ("bytes", "sha256")}
                        for path, identity in expected_payloads.items()),
                "java-minimatch-action-built-input-drift")
        receipts.append({"name": pin["name"], "version": pin["version"], "profile": JAVA_MINIMATCH_PROFILE,
                         "upstream_integrity": JAVA_MINIMATCH_UPSTREAM, "derived_integrity": JAVA_MINIMATCH_DERIVED,
                         "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                         "locks": [entry["lock"]], "advisories": MINIMATCH_ADVISORIES,
                         "action": selected["reference"], "source_role": "action-runtime-and-build",
                         "built_tree": build["publishedTree"], "build_run": build["run"]})
    return receipts


def verify_node_minimatch_action_sources(repo: Path, packages: list, configuration: dict,
                                         fetch=registry_archive, fetch_runtime=None) -> list[dict]:
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("minimatch_source_repair") != NODE_MINIMATCH_PROFILE:
            continue
        if not any(item.path == entry["lock"] for item in packages):
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        selected = node_minimatch_action_inputs(repo, entry, owner, lock)
        material = selected["material"]
        deepmerge = action_source_inputs(repo, entry, owner, lock)
        require(deepmerge is not None and deepmerge["reference"] == selected["reference"],
                "node-minimatch-action-base-source-missing")
        for runtime in NODE_MINIMATCH_RUNTIME.values():
            raw = (fetch_runtime or action_runtime)(selected["reference"], runtime["source"])
            require(source_identity(raw) == {key: runtime[key] for key in ("bytes", "sha256", "gitBlob")},
                    "node-minimatch-action-runtime-drift")
        pin = {"name": "minimatch", "version": "10.2.6", "integrity": NODE_MINIMATCH_UPSTREAM}
        upstream = fetch(pin)
        require(upstream == material["upstream"] and integrity(upstream) == NODE_MINIMATCH_UPSTREAM,
                "node-minimatch-action-upstream-drift")
        original = members(upstream)
        value = manifest(original, "minimatch", "10.2.6", {"brace-expansion": "^5.0.8"})
        require(value.get("license") == "BlueOak-1.0.0"
                and digest(original["package/package.json"][0]) == "bb847ba240909c9a36d4eaeb4e0efdc3e31182aeef208c1611259a48f282ea75"
                and digest(original["package/LICENSE.md"][0]) == "2c7c5d22ed5a8ee968c64757710979afcd77438c48b4a265b94e615babd8a901",
                "node-minimatch-action-package-identity-drift")
        repair = decode_json(material["repair"])
        require(repair.get("profile") == "minimatch-10.2.6-lsf-bounds-v1",
                "node-minimatch-action-repair-profile")
        repaired = source_repair(original, repair, pin)
        require(distribution(repaired) == material["archive"]
                and integrity(material["archive"]) == NODE_MINIMATCH_DERIVED,
                "node-minimatch-action-reconstruction-drift")
        build = decode_json(material["build"])
        artifact, installed = build["artifact"], build["installed"]
        require(build["schema"] == 1 and build["repository"] == "KirilsTurkins/lsf-setup-node"
                and build["publishedRevision"] == selected["reference"].split("@")[1]
                and build["publishedTree"] == build["sourceTree"] == "b1591bf1668591f5e54cfac62c28b70304661927"
                and build["sourceHead"] == "213657803ca67186bcfee4e67e0f466d76429ec5"
                and build["diagnosticHead"] == installed["sourceCommit"] == "58d8ccfb60ec5f8f0d1e8bb0f6e066c3a1755345"
                and build["diagnosticTree"] == "ba58d4e2da95e7b681428ae05eaa97d1e506d9fc"
                and build["diagnosticOnlyPath"] == ".github/workflows/lsf-setup-node-security-owner.yml"
                and build["run"] == 42024002011 and build["job"] == 127233536085
                and build["jobConclusion"] == "success" and build["node"] == installed["node"] == "24.19.0"
                and build["npm"] == "11.17.0" and build["jestSuites"] == 11 and build["jestTests"] == 235
                and build["focusedTests"] == 2
                and artifact["id"] == 13412972464 and artifact["bytes"] == 1690846
                and artifact["sha256"] == "a321014ab2ece7b01175ca8362c97af218cda5c284470ebc6601f6af9e1a7a52"
                and artifact["members"] == 23 and artifact["crcVerified"] is True
                and installed["kind"] == "installed-minimatch-source-assertion"
                and installed["version"] == "10.2.6" and installed["repairSha256"] == digest(material["repair"])
                and installed["installedPostimages"] == {row["path"]: row["afterSha256"] for row in repair["files"]},
                "node-minimatch-action-build-evidence-drift")
        deep_policy = deepmerge["policy"]
        deep_assets = [deep_policy["assets"][name] for name in ("archive", "repair", "declaration")]
        deep_assets.append(deep_policy["additional_actions"]["verifier"])
        expected_payloads = {
            "action.yml": source_identity(read_file(repo, NODE_MINIMATCH_PREFIX + "action.yml.snapshot")),
            "package.json": source_identity(read_file(repo, entry["path"])),
            "package-lock.json": source_identity(read_file(repo, entry["lock"])),
            **{NODE_MINIMATCH_ASSETS[name]["source"]: NODE_MINIMATCH_ASSETS[name]
               for name in ("upstream", "archive", "repair", "verifier", "tests")},
            **{row["source"]: row for row in NODE_MINIMATCH_RUNTIME.values()},
            **{row["source"]: row for row in deep_assets},
            "installed-minimatch.json": {"bytes": 427, "sha256": "2dff1c036d311a0b9988fc0f14bad2bf5dfdea1bb542ff2dd4719d39ab50b6c3"},
            "installed-deepmerge.json": {"bytes": 524, "sha256": "93dd39de82cac77a040c0541e1e5450a921f368b14376717260487d627d69e9c"},
            "source-identities.txt": {"bytes": 123, "sha256": "043f5017b6e3bfe2e7a6251ed269ef5fd078548b778d5724f048aa80fb016180"},
        }
        require(set(artifact["payloads"]) == set(expected_payloads)
                and all(artifact["payloads"][path] == {key: identity[key] for key in ("bytes", "sha256")}
                        for path, identity in expected_payloads.items()),
                "node-minimatch-action-built-input-drift")
        receipts.append({"name": pin["name"], "version": pin["version"], "profile": NODE_MINIMATCH_PROFILE,
                         "upstream_integrity": NODE_MINIMATCH_UPSTREAM, "derived_integrity": NODE_MINIMATCH_DERIVED,
                         "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                         "locks": [entry["lock"]], "advisories": MINIMATCH_ADVISORIES,
                         "action": selected["reference"], "source_role": "action-runtime-and-build",
                         "built_tree": build["publishedTree"], "build_run": build["run"]})
    return receipts


def verify_sources(repo: Path, packages: list, configuration: dict, fetch=registry_archive, fetch_runtime=None) -> list[dict]:
    """Produce receipts only after every selected source/lock byte is verified."""
    action_receipts = verify_action_sources(repo, packages, configuration, fetch)
    action_receipts += verify_minimatch_action_sources(repo, packages, configuration, fetch, fetch_runtime)
    action_receipts += verify_java_minimatch_action_sources(repo, packages, configuration, fetch, fetch_runtime)
    action_receipts += dotnet_sources.verify_sources(repo, packages, configuration, fetch, fetch_runtime)
    action_receipts += verify_node_minimatch_action_sources(repo, packages, configuration, fetch, fetch_runtime)
    action_receipts += security_setup_go.verify_minimatch_sources(repo, packages, configuration, fetch,
                                                                  fetch_runtime or action_runtime)
    action_receipts += security_upload_artifact.verify_sources(repo, packages, configuration, fetch,
                                                               fetch_runtime or action_runtime)
    selected = [entry for entry in configuration["manifests"]
                if (entry.get("derived_bundle") or entry.get("derived_libraries"))
                and any(package.path == entry["lock"] for package in packages)]
    if not selected:
        return action_receipts
    policy = decode_json(read_file(POLICY, "npm-source-repairs.json"))
    require(set(policy) == {"schema", "source_sha256", "builder_sha256", "repairs", "bundle_repair"}
            and policy["schema"] == 1 and set(policy["repairs"]) == {"braces", "http-cache-semantics", "deepmerge"},
            "npm-repair-policy")
    for path, field in (("website/toolchain/source.json", "source_sha256"),
                        ("website/toolchain/prepare.py", "builder_sha256")):
        require(digest(read_file(repo, path).replace(b"\r\n", b"\n")) == policy[field],
                "npm-repair-control-input-drift")
    source = decode_json(read_file(repo, "website/toolchain/source.json"))
    require(set(source) == {"schema", "profile", "base", "patches", "libraries", "repairs", "bundleRepair"}
            and source["schema"] == 1 and source["profile"] == "npm-11.19.1-lsf-bundle-v6"
            and isinstance(source["patches"], list) and len(source["patches"]) == 5
            and isinstance(source["libraries"], list)
            and [pin.get("name") for pin in source["libraries"]] == ["braces", "deepmerge"], "npm-repair-source-profile")
    pins = source["patches"] + source["libraries"]
    require(len({pin["name"] for pin in pins}) == 7
            and {pin["name"] for pin in pins} == {"ip-address", "undici", "brace-expansion", "http-cache-semantics", "braces", "postcss-selector-parser", "deepmerge"},
            "npm-repair-upstream-coverage")
    material = {}
    for pin in pins:
        raw = fetch(pin)
        require(integrity(raw) == pin["integrity"], "npm-repair-upstream-integrity")
        files = members(raw)
        dependencies = {"balanced-match": "^4.0.2"} if pin["name"] == "brace-expansion" else (
            {"fill-range": "^7.1.1"} if pin["name"] == "braces" else
            {"cssesc": "^3.0.0", "util-deprecate": "^1.0.2"} if pin["name"] == "postcss-selector-parser" else {})
        manifest(files, pin["name"], pin["version"], dependencies)
        material[pin["name"]] = files
    receipts = []
    require(isinstance(source["repairs"], list) and len(source["repairs"]) == 3, "npm-repair-document-coverage")
    for name, reviewed in policy["repairs"].items():
        require(set(reviewed) == {"version", "profile", "repair_sha256", "integrity", "advisories"},
                "npm-repair-policy-fields")
        path = f"website/toolchain/repairs/{name}.json"
        raw = read_file(repo, path).replace(b"\r\n", b"\n")
        require(len(raw) <= 65536 and digest(raw) == reviewed["repair_sha256"]
                and {"path": f"repairs/{name}.json", "sha256": reviewed["repair_sha256"]} in source["repairs"],
                "npm-repair-document-drift")
        repair = decode_json(raw)
        pin = next(pin for pin in pins if pin["name"] == name)
        require((repair["version"], repair["profile"]) == (reviewed["version"], reviewed["profile"]),
                "npm-repair-reviewed-identity")
        material[name] = source_repair(material[name], repair, pin)
        derived = integrity(distribution(material[name]))
        require(derived == reviewed["integrity"], "npm-repair-distribution-drift")
        receipts.append({"name": name, "version": pin["version"], "profile": repair["profile"],
                         "upstream_integrity": pin["integrity"], "derived_integrity": derived,
                         "repair_sha256": digest(raw), "files": len(repair["files"]), "locks": [],
                         "advisories": reviewed["advisories"]})
    base = source["base"]
    require(base["name"] == "npm" and base["version"] == "11.19.1", "npm-repair-bundle-identity")
    raw = fetch(base)
    require(integrity(raw) == base["integrity"], "npm-repair-upstream-integrity")
    bundle = members(raw)
    owner = decode_json(bundle["package/package.json"][0])
    require(owner["name"] == base["name"] and owner["version"] == base["version"]
            and not any(path in bundle for path in ("package/package-lock.json", "package/npm-shrinkwrap.json")),
            "npm-repair-bundle-graph")
    reviewed = policy["bundle_repair"]
    require(set(reviewed) == {"profile", "repair_sha256", "advisories"}
            and reviewed["profile"] == "npm-11.19.1-lsf-glob-minimatch-source-v1"
            and set(reviewed["advisories"]) == {"glob", "minimatch"}, "npm-bundle-repair-policy")
    repair_path = "website/toolchain/repairs/npm-glob-minimatch.json"
    repair_raw = read_file(repo, repair_path).replace(b"\r\n", b"\n")
    require(len(repair_raw) <= 65536 and digest(repair_raw) == reviewed["repair_sha256"]
            and source["bundleRepair"] == {"path": "repairs/npm-glob-minimatch.json", "sha256": reviewed["repair_sha256"]},
            "npm-bundle-repair-document")
    for pin in source["patches"]:
        name = pin["name"]
        prefix = f"package/node_modules/{name}/"
        old = decode_json(bundle[prefix + "package.json"][0])
        require(old["name"] == name and old["version"] == pin["from"], "npm-repair-original-bundle-member")
        if name == "brace-expansion":
            require(old.get("dependencies") == {"balanced-match": "^4.0.2"}
                    and not any(key.startswith(prefix + "node_modules/") for key in bundle),
                    "npm-repair-shadowed-bundle-dependency")
            manifest(bundle, "balanced-match", "4.0.4", {}, "package/node_modules/balanced-match/")
        if name == "postcss-selector-parser":
            require(old.get("dependencies") == {"cssesc": "^3.0.0", "util-deprecate": "^1.0.2"}
                    and not any(key.startswith(prefix + "node_modules/") for key in bundle),
                    "npm-repair-shadowed-bundle-dependency")
            for dependency_name, version in (("cssesc", "3.0.0"), ("util-deprecate", "1.0.2")):
                manifest(bundle, dependency_name, version, {}, "package/node_modules/"+dependency_name+"/")
        bundle = {key: value for key, value in bundle.items() if not key.startswith(prefix)}
        bundle.update({prefix + key.removeprefix("package/"): value for key, value in material[name].items()})
    bundle = bundle_source_repair(bundle, decode_json(repair_raw), base)
    bundle_integrity = integrity(distribution(bundle))
    for entry in selected:
        lock = decode_json(read_file(repo, entry["lock"]))
        profile = entry.get("derived_bundle") or entry["derived_libraries"]
        require(digest(read_file(repo, entry["lock"]).replace(b"\r\n", b"\n")) == profile["lock_sha256"],
                "npm-repair-lock-drift")
        if entry.get("derived_bundle"):
            require(bundle_integrity == profile["integrity"]
                    and lock["packages"]["node_modules/npm"]["integrity"] == bundle_integrity,
                    "npm-repair-bundle-distribution-drift")
            for name, version, advisory_id in (("glob", "13.0.6", "GHSA-3g3m-2fjr-6pw4"),
                                                ("minimatch", "10.2.5", "GHSA-g3hv-75wg-m249")):
                rows = [(key, value) for key, value in lock["packages"].items()
                        if key.rsplit("node_modules/", 1)[-1] == name]
                require(len(rows) == 1 and rows[0][0] == f"node_modules/npm/node_modules/{name}"
                        and rows[0][1].get("version") == version and rows[0][1].get("inBundle") is True
                        and not rows[0][1].get("resolved"), "npm-bundle-repair-lock-identity")
                advisories = reviewed["advisories"][name]
                require(isinstance(advisories, list) and len(advisories) == 1
                        and set(advisories[0]) == {"id", "modified"} and advisories[0]["id"] == advisory_id
                        and isinstance(advisories[0]["modified"], str), "npm-bundle-repair-advisory")
                receipts.append({"name": name, "version": version, "profile": reviewed["profile"],
                                 "upstream_integrity": base["integrity"], "derived_integrity": bundle_integrity,
                                 "repair_sha256": reviewed["repair_sha256"], "files": len(BUNDLE_REPAIR_FILES),
                                 "locks": [entry["lock"]], "advisories": advisories})
            for receipt in receipts:
                if receipt["name"] == "http-cache-semantics":
                    receipt["locks"].append(entry["lock"])
            continue
        for receipt in receipts:
            pinned = profile["libraries"][receipt["name"]]
            rows = [row for path, row in lock["packages"].items()
                    if path.rsplit("node_modules/", 1)[-1] == receipt["name"]]
            require(pinned["integrity"] == receipt["derived_integrity"] and bool(rows)
                    and all(row.get("integrity") == receipt["derived_integrity"] for row in rows),
                    "npm-repair-library-distribution-drift")
            receipt["locks"].append(entry["lock"])
    return receipts + action_receipts


def resolve_findings(findings: list, observations: list[dict], receipts: list[dict]) -> tuple[list, list]:
    """Resolve an exact reviewed advisory revision only for verified fixed bytes."""
    observed = {(row["package"]["name"], row["package"]["version"], row["package"]["path"], row["id"], row["modified"])
                for batch in observations for row in batch.get("advisories", [])}
    fixed = set()
    for receipt in receipts:
        for advisory in receipt["advisories"]:
            require(set(advisory) == {"id", "modified"}, "npm-repair-advisory-policy")
            for path in receipt["locks"]:
                identity = (receipt["name"], receipt["version"], path, advisory["id"], advisory["modified"])
                if identity in observed:
                    fixed.add((advisory["id"], path, f"npm:{receipt['name']}@{receipt['version']}"))
    remaining, remediated = [], []
    for item in findings:
        key = (item.finding, item.path, item.package)
        (remediated if item.scanner == "osv" and key in fixed else remaining).append(item)
    return remaining, remediated
