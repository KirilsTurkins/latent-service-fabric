"""Exact dual-source and runtime receipts for the reviewed Rust-cache fork."""
from __future__ import annotations

import re
from pathlib import Path

from tools import security_setup_go as go
from tools.security_common import decode_json, digest, read_file, require

REFERENCE = "KirilsTurkins/lsf-rust-cache@38534d49940bc6c6aef1e8dfd45349a99d37f14e"
PROFILE = "rust-cache-dual-source-v1"
PREFIX = ".github/security/actions/rust-cache/"
BUILD_PATH = ".github/security/actions/rust-cache-source/fork-build.json"
BUILD_IDENTITY = {"bytes": 5509, "sha256": "ec5f4637c8ce3a45aeb87b11a2e276d2cf409e21a4bcc6c5adcd77b84d816640", "gitBlob": "296e24c351a3cd392c88ba82b72714b907c0949b"}
TREE = "9f98acbfd89e15eac6e8614c2a7f394575d3590e"
DEEP_ADVISORIES = [{"id": "GHSA-gcqx-w48m-w2h4", "modified": "2026-10-27T21:45:04.256048Z"}]
MINI_ADVISORIES = [{"id": "GHSA-g3hv-75wg-m249", "modified": "2026-11-04T17:01:25.850114Z"}]

# Each tuple is the snapshot, byte count, SHA-256 and Git blob of the published source.
ACTION_INPUTS = {
    "action.yml": (PREFIX + "action.yml.snapshot", 3246, "0bf18e525796c2e43b4cccbc5c914e745de700a4e56735f53a8f1b0e6504aa2a", "1481945d779f128e201b6aa5498c53fe4ae9632c"),
    "package.json": (PREFIX + "package.json", 2190, "2aba49452ea432f269e679216b426c9e2e9459d1211745b06bbc9692dcab89ff", "84d8f31b759b456e71a67781dc362c12569e675f"),
    "package-lock.json": (PREFIX + "package-lock.json", 112753, "73ab20e6b215286eaf3c3060dfe66c4e9e426b0533ab907299bf9386aa91022a", "703d3fbc2e0decadb810f6decda4bfa8cd42e5a7"),
    ".lsf-source/verify-installed-deepmerge.mjs": (".github/security/actions/deepmerge-source/installed-verifier.mjs.snapshot", 2381, "55367db845fb579dd45a1a16924bf017c0ddc8f84162d833e368c24a7d629cf7", "99d75a2ea3895eb8acc8018984ca9826e4edff51"),
    ".lsf-source/verify-installed-minimatch.mjs": (".github/security/actions/setup-node-minimatch/installed-verifier.mjs.snapshot", 3386, "4af8eaff4b0b6f6b4b084ceeab68932ba8940048c9e49f9ed8fdc400e9e2f72d", "de5fadac0ee90bd532c5683fd4bcb919634a4314"),
    ".lsf-source/minimatch-bounds.test.mjs": (".github/security/actions/setup-node-minimatch/bounds.test.mjs.snapshot", 2854, "4fd2675946ecfa56ccf5a3c59e76ef50a5dc7d84f0a37fefd47e0037c50a4492", "11a4cf916b01dfa3af9af699aa7ec641b39505d3"),
    ".lsf-source/verify-rust-cache-lock.mjs": (".github/security/actions/rust-cache-source/verify-rust-cache-lock.mjs.snapshot", 2211, "93437849b770f19a97251121d354f55705cff9f3771e9faad36db85cd0472841", "d9cdca37d2c5b4c417cde7496a85e7c8f177dc8a"),
    ".lsf-source/rust-cache-lock.test.mjs": (".github/security/actions/rust-cache-source/rust-cache-lock.test.mjs.snapshot", 2387, "4610bfc55e9451600b3acf8ad67639ad6800b86802f3634b5e06afe3d20e6684", "32b758f19fd9ad50cafa0f96929f1190185209ac"),
}
RUNTIME = {
    "dist/cache-DqPewXTO.js": {"bytes": 1728166, "sha256": "07db20548a8d1d06f2a7b9de443858d49a8a313d81078e22c5a170a4974c1878", "gitBlob": "b1af9eab8c5970cbe70dbaab9b53c86ef63f78eb"},
    "dist/cache-Dt0HXnmv.js": {"bytes": 5097394, "sha256": "a56045b2899b9e84b07a4a474c58e4cfba4834e83103fc7d71c326ca5f5e9ed5", "gitBlob": "bb21bf2d76378a180d6a509edcfba2a36c098c2c"},
    "dist/cleanup-BaklJKZS.js": {"bytes": 1266081, "sha256": "c258ac9bdbb42caedc86dee803f24fd1f11687848a903b6ab010d20b44a75317", "gitBlob": "05daf2e05bc5099227e37557cf57df549fd3b3a4"},
    "dist/restore.js": {"bytes": 3218, "sha256": "79132962e0c05a3cf89cd4f4afa9b397e1cb4b3f464596fcb3532e48bc6deed7", "gitBlob": "ff6a978b49030c31d9981beff6aa3e60c5605499"},
    "dist/save.js": {"bytes": 3886, "sha256": "692deadfb87ebc4522b6b478d1f95d10b9861052c53325a5d7dac7fa53254662", "gitBlob": "999256ab23222b71758198d7ddfa96e490c64295"},
    "dist/state-cjs-DX0ePKGg.js": {"bytes": 53327, "sha256": "adf7c2c7259a366203dd55940761d50529982bb61c344f4d389f7c587d6ea04d", "gitBlob": "3d2c29249aa189db9a92c1d087e4df2bc88e27c3"},
}
DEEP_SOURCES = {
    ".lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar": "archive",
    ".lsf-source/deepmerge-4.3.1-lsf-prototype-v1.repair.json": "repair",
    ".lsf-source/deepmerge-4.3.1-lsf-prototype-v1.source.json": "declaration",
}
MINI_SOURCES = {
    ".lsf-source/minimatch-10.2.6.original.tgz": "upstream",
    ".lsf-source/minimatch-10.2.6-lsf-bound-v1.tar": "archive",
    ".lsf-source/minimatch-10.2.6-lsf-bound-v1.repair.json": "repair",
}


def _material(repo: Path, identities: dict) -> dict:
    from tools import security_npm_sources as sources
    result = {}
    for name, (snapshot, size, sha256, blob) in identities.items():
        raw = read_file(repo, snapshot)
        require(sources.source_identity(raw) == {"bytes": size, "sha256": sha256, "gitBlob": blob},
                "rust-cache-source-input-drift")
        result[name] = raw
    return result


def require_unique_deepmerge(lock: dict) -> None:
    """Independently reject nested/aliased copies, including npm dependency aliases."""
    rows = lock.get("packages")
    require(isinstance(rows, dict), "rust-cache-lock-invalid")
    matches = []
    for path, row in rows.items():
        require(isinstance(path, str) and isinstance(row, dict), "rust-cache-lock-invalid")
        resolved = row.get("resolved", "")
        name = path.rsplit("node_modules/", 1)[-1] if "node_modules/" in path else ""
        if (name == "deepmerge" or row.get("name") == "deepmerge"
                or (isinstance(resolved, str) and re.search(r"(?:^|[/\\:])deepmerge(?:[/\\@-]|$)", resolved, re.I))):
            matches.append(path)
        for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            dependencies = row.get(section, {})
            require(isinstance(dependencies, dict), "rust-cache-lock-invalid")
            for dep, spec in dependencies.items():
                require(dep == "deepmerge" or not (isinstance(spec, str) and re.match(r"^npm:deepmerge(?:@|$)", spec, re.I)),
                        "rust-cache-deepmerge-alias")
    require(matches == ["node_modules/deepmerge"], "rust-cache-deepmerge-duplicate")


def source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    from tools import security_npm_sources as sources
    require(entry == {"kind": "npm", "path": PREFIX + "package.json", "lock": PREFIX + "package-lock.json",
                      "source_repair": PROFILE}, "unreviewed-rust-cache-profile")
    inputs = _material(repo, ACTION_INPUTS)
    deep = _material(repo, go.DEEP_MATERIAL)
    mini_rows = {name: (row["snapshot"], row["bytes"], row["sha256"], row["gitBlob"])
                 for name, row in sources.NODE_MINIMATCH_ASSETS.items() if name in {"upstream", "archive", "repair"}}
    mini = _material(repo, mini_rows)
    require(decode_json(inputs["package.json"]) == owner and decode_json(inputs["package-lock.json"]) == lock,
            "rust-cache-parsed-input-drift")
    require_unique_deepmerge(lock)
    expected = [{"snapshot": snapshot, "source": source, "sha256": sha256, "source_sha256": sha256}
                for source, (snapshot, _, sha256, _) in ACTION_INPUTS.items()]
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(REFERENCE, {})
    require(action.get("repository") == "KirilsTurkins/lsf-rust-cache"
            and action.get("revision") == REFERENCE.split("@")[1] and action.get("kind") == "npm"
            and isinstance(action.get("files"), list)
            and sorted(action["files"], key=lambda row: row["source"]) == sorted(expected, key=lambda row: row["source"])
            and action.get("metadata") == expected[0], "rust-cache-action-binding-drift")
    require(owner.get("scripts", {}).get("prebuild") ==
            "node .lsf-source/verify-installed-deepmerge.mjs && node .lsf-source/verify-installed-minimatch.mjs && node .lsf-source/verify-rust-cache-lock.mjs && npm run clean"
            and owner["scripts"].get("build") == "tsc && rollup --config .build/rollup.config.js"
            and owner["scripts"].get("prepare") == "npm run build && linefix dist"
            and owner["scripts"].get("test:security-source") == "node --test .lsf-source/minimatch-bounds.test.mjs .lsf-source/rust-cache-lock.test.mjs",
            "rust-cache-build-script-drift")
    deep_node = lock["packages"].get("node_modules/deepmerge", {})
    mini_node = lock["packages"].get("node_modules/minimatch", {})
    ten = [(path, row) for path, row in lock["packages"].items()
           if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == "minimatch"
           and str(row.get("version", "")).startswith("10.")]
    glob = lock["packages"].get("node_modules/@actions/glob", {})
    require(owner.get("devDependencies", {}).get("deepmerge") == sources.CHECKOUT_ARCHIVE
            and "deepmerge" not in owner.get("dependencies", {}) and "deepmerge" not in owner.get("overrides", {})
            and deep_node.get("version") == "4.3.1" and deep_node.get("dev") is True
            and deep_node.get("resolved") == sources.CHECKOUT_ARCHIVE
            and deep_node.get("integrity") == sources.integrity(deep["archive"])
            and owner.get("devDependencies", {}).get("minimatch") == sources.NODE_MINIMATCH_ARCHIVE
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and len(ten) == 1 and ten[0][0] == "node_modules/minimatch"
            and mini_node.get("version") == "10.2.6" and not mini_node.get("dev", False)
            and mini_node.get("resolved") == sources.NODE_MINIMATCH_ARCHIVE
            and mini_node.get("integrity") == sources.NODE_MINIMATCH_DERIVED
            and glob.get("version") == "0.7.0" and glob.get("dependencies", {}).get("minimatch") == "^10.2.5"
            and not glob.get("dev", False), "rust-cache-lock-graph-drift")
    build_raw = read_file(repo, BUILD_PATH)
    require(sources.source_identity(build_raw) == BUILD_IDENTITY, "rust-cache-build-evidence-drift")
    build = decode_json(build_raw)
    artifact = build["artifact"]
    expected_payloads = {name: {"bytes": size, "sha256": sha, "gitBlob": blob}
                         for name, (_, size, sha, blob) in ACTION_INPUTS.items()}
    expected_payloads.update({name: sources.source_identity(deep[key]) for name, key in DEEP_SOURCES.items()})
    expected_payloads.update({name: sources.source_identity(mini[key]) for name, key in MINI_SOURCES.items()})
    expected_payloads.update(RUNTIME)
    require(build["schema"] == 1 and build["repository"] == "KirilsTurkins/lsf-rust-cache"
            and build["publishedRevision"] == REFERENCE.split("@")[1] and build["publishedTree"] == TREE
            and build["sourceHead"] == "2a5441298775042332ac1da9e478ffcce3e075f2" and build["sourceTree"] == TREE
            and build["diagnosticHead"] == "9f57c751fbc99dc4acc824398d68588cf565d59d"
            and build["diagnosticOnlyPath"] == ".github/workflows/lsf-rust-cache-security-owner.yml"
            and build["diagnosticWorkflowBlob"] == "0adb276eddaee72bbe863d5265ffe607ec069131"
            and build["run"] == 42111587240 and build["sourceJob"] == 127540248819
            and build["saveJob"] == 127540495921 and build["restoreJob"] == 127541234496
            and build["conclusion"] == "success" and build["node"] == "24.19.0" and build["npm"] == "11.17.0"
            and build["sourceTests"] == 5 and build["cacheMissSaveHitRestore"] is True
            and artifact["id"] == 13455276891 and artifact["bytes"] == 1920974
            and artifact["sha256"] == "d519344459ab521d725a229bdd7b43ef30350e5c070790fbcb645d9109d7fed2"
            and artifact["members"] == 31 and artifact["checksums"] == 30 and artifact["crcVerified"] is True
            and artifact["payloads"] == expected_payloads, "rust-cache-build-evidence-drift")
    return {"deep": deep, "mini": mini}


def libraries(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    from tools import security_npm_sources as sources
    selected = source_inputs(repo, entry, owner, lock)
    return {"deepmerge": {"version": "4.3.1", "resolved": sources.CHECKOUT_ARCHIVE,
                          "integrity": sources.integrity(selected["deep"]["archive"])},
            "minimatch": {"version": "10.2.6", "resolved": sources.NODE_MINIMATCH_ARCHIVE,
                          "integrity": sources.NODE_MINIMATCH_DERIVED}}


def verify_sources(repo: Path, packages: list, configuration: dict, fetch, fetch_runtime) -> list[dict]:
    from tools import security_npm_sources as sources
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("source_repair") != PROFILE or not any(item.path == entry["lock"] for item in packages):
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        selected = source_inputs(repo, entry, owner, lock)
        for path, identity in RUNTIME.items():
            require(sources.source_identity(fetch_runtime(REFERENCE, path)) == identity, "rust-cache-runtime-drift")
        deep, mini = selected["deep"], selected["mini"]
        declaration, deep_repair = (decode_json(deep[key]) for key in ("declaration", "repair"))
        deep_pin = {"name": "deepmerge", "version": "4.3.1", "integrity": declaration["upstream"]["integrity"]}
        upstream = fetch(deep_pin)
        require(upstream == deep["upstream"] and sources.integrity(upstream) == deep_pin["integrity"], "rust-cache-upstream-drift")
        original = sources.members(upstream)
        sources.manifest(original, "deepmerge", "4.3.1", {})
        fixed = sources.source_repair(original, deep_repair, deep_pin)
        require(sources.distribution(fixed) == deep["archive"]
                and declaration["profile"] == deep_repair["profile"]
                and declaration["repair"]["sha256"] == digest(deep["repair"])
                and declaration["derived"]["integrity"] == sources.integrity(deep["archive"])
                and declaration["forkBuildVerified"] is False and declaration["runtimeOrSignedSDKQualified"] is False
                and declaration["notAnUpstreamFixedRelease"] is True
                and len(declaration["fileIdentities"]) == len(original)
                and {row["path"] for row in declaration["fileIdentities"]} == {path.removeprefix("package/") for path in original},
                "rust-cache-deepmerge-reconstruction-drift")
        for row in declaration["fileIdentities"]:
            key = "package/" + row["path"]
            require(row["before"] == sources.source_identity(original[key][0])
                    and row["after"] == sources.source_identity(fixed[key][0])
                    and row["mode"] == oct(original[key][1]) == oct(fixed[key][1]), "rust-cache-deepmerge-file-drift")
        mini_pin = {"name": "minimatch", "version": "10.2.6", "integrity": sources.NODE_MINIMATCH_UPSTREAM}
        upstream = fetch(mini_pin)
        require(upstream == mini["upstream"] and sources.integrity(upstream) == mini_pin["integrity"], "rust-cache-upstream-drift")
        original = sources.members(upstream)
        value = sources.manifest(original, "minimatch", "10.2.6", {"brace-expansion": "^5.0.8"})
        require(value.get("license") == "BlueOak-1.0.0"
                and digest(original["package/package.json"][0]) == "bb847ba240909c9a36d4eaeb4e0efdc3e31182aeef208c1611259a48f282ea75"
                and digest(original["package/LICENSE.md"][0]) == "2c7c5d22ed5a8ee968c64757710979afcd77438c48b4a265b94e615babd8a901",
                "rust-cache-minimatch-package-drift")
        mini_repair = decode_json(mini["repair"])
        require(mini_repair.get("profile") == "minimatch-10.2.6-lsf-bounds-v1", "rust-cache-minimatch-profile-drift")
        fixed = sources.source_repair(original, mini_repair, mini_pin)
        require(sources.distribution(fixed) == mini["archive"] and sources.integrity(mini["archive"]) == sources.NODE_MINIMATCH_DERIVED,
                "rust-cache-minimatch-reconstruction-drift")
        for pin, material, repair, advisory, role in ((deep_pin, deep, deep_repair, DEEP_ADVISORIES, "development-build-tool"),
                                                       (mini_pin, mini, mini_repair, MINI_ADVISORIES, "action-runtime-and-build")):
            receipts.append({"name": pin["name"], "version": pin["version"], "profile": PROFILE,
                             "upstream_integrity": pin["integrity"], "derived_integrity": sources.integrity(material["archive"]),
                             "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                             "locks": [entry["lock"]], "advisories": advisory, "action": REFERENCE,
                             "source_role": role, "built_tree": TREE, "build_run": 42111587240})
    return receipts
