"""Exact source and runtime receipts for the reviewed setup-go action."""
from __future__ import annotations

from pathlib import Path

from tools.security_action_rebuild import verify_rebuild
from tools.security_common import decode_json, digest, read_file, require

REFERENCE = 'KirilsTurkins/lsf-setup-go@92a5903f5ff2b45e67c517d23c18501025a55a12'
PREFIX = ".github/security/actions/setup-go/"
DEEP_PROFILE = "setup-go-deepmerge-source-v1"
MINI_PROFILE = "setup-go-minimatch-source-v1"
DEEP_ADVISORIES = [{"id": "GHSA-gcqx-w48m-w2h4", "modified": "2026-10-27T21:45:04.256048Z"}]
MINI_ADVISORIES = [{"id": "GHSA-g3hv-75wg-m249", "modified": "2026-11-04T17:01:25.850114Z"}]
DEEP_VERIFIER = ".lsf-source/verify-installed-deepmerge.mjs"
MINI_VERIFIER = ".lsf-source/verify-installed-minimatch.mjs"
BOUNDS = ".lsf-source/minimatch-bounds.test.mjs"

# Each tuple is a repository snapshot, exact byte count, SHA-256 and Git blob.
ACTION_INPUTS = {'action.yml': ('.github/security/actions/setup-go/action.yml.snapshot',
                2788,
                '216efbacabe9911f4de0714f00f57e45470469c52c2d3e70e8d6165f32939585',
                '79299e5525f5b737d28c7a5ffdcadf91d391f797'),
 'package.json': ('.github/security/actions/setup-go/package.json',
                  2523,
                  '5cd3573fb4e1a6b3cf680b46cf3cd5dbafc293abc2bea4fc078925d89c2ef18e',
                  'd82f4446ea676f4b4f16d00627d3aafa4d549a5b'),
 'package-lock.json': ('.github/security/actions/setup-go/package-lock.json',
                       225454,
                       '0ab055419bedc5c0b561cc30632279aa8d38edd2fdced86d122939457e9e2869',
                       '5ac85cf63c31df0b05825d74280c5e5889f5c46d'),
 '.lsf-source/verify-installed-deepmerge.mjs': ('.github/security/actions/deepmerge-source/installed-verifier.mjs.snapshot',
                                                2381,
                                                '55367db845fb579dd45a1a16924bf017c0ddc8f84162d833e368c24a7d629cf7',
                                                '99d75a2ea3895eb8acc8018984ca9826e4edff51'),
 '.lsf-source/verify-installed-minimatch.mjs': ('.github/security/actions/setup-python-minimatch/installed-verifier.mjs.snapshot',
                                                3386,
                                                '4fcbcba0f46fed80b09c6cdb1a2a54eeff2e0a3690b4d0a5b566762169f1f826',
                                                'ab204a63dd0ddf065b00ae7c3ab0531b35d5d300'),
 '.lsf-source/minimatch-bounds.test.mjs': ('.github/security/actions/setup-go-minimatch/bounds.test.mjs.snapshot',
                                           2854,
                                           'f65c9af8d0d6b2abfd728d803e223396e746850f564003e93b223c4f084f987b',
                                           '9601c04f3210fa02ee4ae91183f2a5538b1e9374')}
DEEP_MATERIAL = {
    "archive": (".github/security/actions/checkout-source/deepmerge-4.3.1.repaired.tar", 51200, "c4ca0f4eb3a2464c026bc3dec5d9eaf04544aed24c3fd1d77da95f85e36c369f", "30e23fad3a82fd30bc3f08e26704a0c0bc84c704"),
    "repair": (".github/security/actions/checkout-source/repair.json", 3064, "e402617d1e791c4bed35768b6c34ba68c370c076551495e738de0731ad2049c7", "52602f18647aa2f2bd30f046e05bcce2705a761f"),
    "declaration": (".github/security/actions/checkout-source/declaration.json", 6925, "b4b0b79fa2bc84c6f1e1c61ddcc1ab228df629f9fce4b1067d3ac8b3d1c42892", "0685ff353f65174eb5a97cfcb385720dd4a5874c"),
    "upstream": (".github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz", 8452, "4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c", "1d1560e971dfc484bbe0cb9e8c86bde9140e45b5"),
}
MINI_MATERIAL = {'archive': ('.github/security/actions/setup-python-minimatch/minimatch-10.2.5.repaired.tar',
             583680,
             '8ed155c4f29d451728efaaf60bc0ed7249ceb93d21eb81171068342621287a68',
             '93a1d4e2d4c2935624af7aa91fe9a113c56e5932'),
 'repair': ('.github/security/actions/setup-python-minimatch/repair.json',
            2129,
            'b340bb0502087bb0df18c8ec276ee61f58aedc6c54fcc6b022d174817d7d27a9',
            '679352aace8de2eb661a5a9665d6152033833cbb'),
 'upstream': ('.github/security/actions/setup-python-minimatch/minimatch-10.2.5.original.tgz',
              117062,
              'a6cea46915bfc6c3fae60f9bd003ea4f9d6a4233aa59a9ca729474d3824ca9e5',
              'dd98b4079e660933500de9f03d0bbbab1f44f295'),
 'build': ('.github/security/actions/setup-go-minimatch/fork-build.json',
           9459,
           'cd8f6e92ebccbd3ac2e7fb6e07c09aa57fa9c31693c6014e0a8e7db83ba6c75d',
           '33dbb24ca00b2632c71c5b53843a202555fd5e04')}
RUNTIME = {'dist/setup/index.js': {'bytes': 3520107,
                         'sha256': '17484a2d85761ff8c2b1ede7716ec58d235d3a272fbc5fd32ff5785b182eb669',
                         'gitBlob': '8783bf713f49b338b84d3f3d9473d8d0bbed56a6'},
 'dist/cache-save/index.js': {'bytes': 3458655,
                              'sha256': '06a971fbaa132dc7e21d21769c47eb3f929624a867b575168d9965cf3c9afdac',
                              'gitBlob': '4ffddc7e1a98a429357c1dd0029d2ded97ab3c4f'}}


def _material(repo: Path, identities: dict) -> dict:
    from tools import security_npm_sources as sources
    result = {}
    for name, (snapshot, size, sha256, blob) in identities.items():
        raw = read_file(repo, snapshot)
        require(sources.source_identity(raw) == {"bytes": size, "sha256": sha256, "gitBlob": blob},
                "setup-go-source-input-drift")
        result[name] = raw
    return result


def source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    from tools import security_npm_sources as sources
    require(set(entry) == {"kind", "path", "lock", "source_repair", "minimatch_source_repair"}
            and entry["kind"] == "npm" and entry["path"] == PREFIX + "package.json"
            and entry["lock"] == PREFIX + "package-lock.json" and entry["source_repair"] == DEEP_PROFILE
            and entry["minimatch_source_repair"] == MINI_PROFILE, "unreviewed-setup-go-profile")
    inputs = _material(repo, ACTION_INPUTS)
    deep, mini = _material(repo, DEEP_MATERIAL), _material(repo, MINI_MATERIAL)
    require(decode_json(inputs["package.json"]) == owner and decode_json(inputs["package-lock.json"]) == lock,
            "setup-go-parsed-input-drift")
    expected = [{"snapshot": snapshot, "source": source, "sha256": sha256, "source_sha256": sha256}
                for source, (snapshot, _, sha256, _) in ACTION_INPUTS.items()]
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(REFERENCE, {})
    metadata = next(row for row in expected if row["source"] == "action.yml")
    require(action.get("repository") == "KirilsTurkins/lsf-setup-go"
            and action.get("revision") == REFERENCE.split("@")[1] and action.get("kind") == "npm"
            and isinstance(action.get("files"), list)
            and sorted(action["files"], key=lambda row: row["source"]) == sorted(expected, key=lambda row: row["source"])
            and action.get("metadata") == metadata, "setup-go-action-binding-drift")
    node = lock["packages"].get("node_modules/deepmerge", {})
    require(owner.get("devDependencies", {}).get("deepmerge") == sources.CHECKOUT_ARCHIVE
            and "deepmerge" not in owner.get("dependencies", {}) and "deepmerge" not in owner.get("overrides", {})
            and node.get("version") == "4.3.1" and node.get("dev") is True
            and node.get("resolved") == sources.CHECKOUT_ARCHIVE
            and node.get("integrity") == sources.integrity(deep["archive"])
            and [path for path in lock["packages"] if path.rsplit("node_modules/", 1)[-1] == "deepmerge"]
                == ["node_modules/deepmerge"], "unlocked-setup-go-deepmerge")
    mini_nodes = [(path, row) for path, row in lock["packages"].items()
                  if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == "minimatch"
                  and str(row.get("version", "")).startswith("10.")]
    glob = lock["packages"].get("node_modules/@actions/glob", {})
    require(owner.get("devDependencies", {}).get("minimatch") == sources.MINIMATCH_ARCHIVE
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and owner.get("overrides", {}).get("glob@10") == "14.0.2"
            and lock["packages"][""].get("devDependencies", {}).get("minimatch") == sources.MINIMATCH_ARCHIVE
            and len(mini_nodes) == 1 and mini_nodes[0][0] == "node_modules/minimatch"
            and mini_nodes[0][1].get("version") == "10.2.5" and not mini_nodes[0][1].get("dev", False)
            and mini_nodes[0][1].get("resolved") == sources.MINIMATCH_ARCHIVE
            and mini_nodes[0][1].get("integrity") == sources.MINIMATCH_DERIVED
            and glob.get("version") == "0.7.0" and glob.get("dependencies", {}).get("minimatch") == "^10.2.5"
            and not glob.get("dev", False) and lock["packages"].get("node_modules/glob", {}).get("version") == "14.0.2"
            and lock["packages"]["node_modules/glob"].get("dev") is True,
            "unlocked-setup-go-minimatch")
    build = decode_json(mini["build"])
    verify_rebuild(repo, build, REFERENCE, RUNTIME)
    return {"policy": {"advisories": DEEP_ADVISORIES}, "material": deep,
            "reference": REFERENCE, "checkout": False, "setup_go": True, "mini": mini}


def minimatch_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    selected = source_inputs(repo, entry, owner, lock)
    return {"reference": REFERENCE, "material": selected["mini"]}


def verify_minimatch_sources(repo: Path, packages: list, configuration: dict, fetch, fetch_runtime) -> list[dict]:
    from tools import security_npm_sources as sources
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("minimatch_source_repair") != MINI_PROFILE or not any(item.path == entry["lock"] for item in packages):
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        selected = minimatch_inputs(repo, entry, owner, lock)
        for path, identity in RUNTIME.items():
            require(sources.source_identity(fetch_runtime(REFERENCE, path)) == identity,
                    "setup-go-runtime-drift")
        material = selected["material"]
        pin = {"name": "minimatch", "version": "10.2.5", "integrity": sources.MINIMATCH_UPSTREAM}
        upstream = fetch(pin)
        require(upstream == material["upstream"] and sources.integrity(upstream) == sources.MINIMATCH_UPSTREAM,
                "setup-go-minimatch-upstream-drift")
        original = sources.members(upstream)
        value = sources.manifest(original, "minimatch", "10.2.5", {"brace-expansion": "^5.0.5"})
        require(value.get("license") == "BlueOak-1.0.0"
                and digest(original["package/package.json"][0]) == "4b3a08a7ad20dead8bbe4b4fe97a2746bded7c51d218ef3034eb4e330ad31f08"
                and digest(original["package/LICENSE.md"][0]) == "2c7c5d22ed5a8ee968c64757710979afcd77438c48b4a265b94e615babd8a901",
                "setup-go-minimatch-package-identity-drift")
        repair = decode_json(material["repair"])
        require(repair.get("profile") == "minimatch-10.2.5-lsf-bounds-v1", "setup-go-minimatch-repair-profile")
        repaired = sources.source_repair(original, repair, pin)
        require(sources.distribution(repaired) == material["archive"]
                and sources.integrity(material["archive"]) == sources.MINIMATCH_DERIVED,
                "setup-go-minimatch-reconstruction-drift")
        receipts.append({"name": "minimatch", "version": "10.2.5", "profile": MINI_PROFILE,
                         "upstream_integrity": sources.MINIMATCH_UPSTREAM, "derived_integrity": sources.MINIMATCH_DERIVED,
                         "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                         "locks": [entry["lock"]], "advisories": MINI_ADVISORIES, "action": REFERENCE,
                         "source_role": "action-runtime-and-build", "built_tree": "71e010c88065728c2175f28330d8ea5aab035e60",
                         "build_run": 43523168939})
    return receipts
