"""Exact source, graph and hosted runtime receipts for deploy-pages."""
from __future__ import annotations

from pathlib import Path
from tools.security_common import decode_json, digest, read_file, require

REFERENCE = "KirilsTurkins/lsf-deploy-pages@e249fe4e7520b3d7aa16ef72f45eeb05de6cf4f6"
PREFIX = ".github/security/actions/deploy-pages/"
DEEP_PROFILE = "deploy-pages-deepmerge-source-v1"
PROFILE = "deploy-pages-glob-minimatch-source-v1"
GUARD = ".lsf-source/apply-verified-sources.cjs"
DEEP_VERIFIER = ".lsf-source/verify-installed-deepmerge.mjs"
TREE = "79d01754bcbda86178d60a411e8256696a265f5c"
RUN = 42116676439
GLOB_ADVISORIES = [{"id": "GHSA-3g3m-2fjr-6pw4", "modified": "2026-10-30T23:15:04.503965Z"}]
MINI_ADVISORIES = [{"id": "GHSA-g3hv-75wg-m249", "modified": "2026-11-04T17:01:25.850114Z"}]
DEEP_ADVISORIES = [{"id": "GHSA-gcqx-w48m-w2h4", "modified": "2026-10-27T21:45:04.256048Z"}]

ACTION_INPUTS = {'action.yml': ('.github/security/actions/deploy-pages/action.yml.snapshot',
                1244,
                '64c44539fba53559a157b5de16c01d3ab91dbc999c1b98b5c0b2fc3528d5d059',
                '9640517bb026e0790a53bd6d35fd13a94617c48e'),
 'package.json': ('.github/security/actions/deploy-pages/package.json',
                  3152,
                  '1f1ba01a30c2f8aa80e60493e6e154bb59e4ff94b1010371447816f609eac771',
                  '290c1789c2fa671677f2c373607dbf465f109d70'),
 'package-lock.json': ('.github/security/actions/deploy-pages/package-lock.json',
                       352898,
                       '88d39a5c99be6e0ba2af6cd8ca6535acd4ef645ee297c51735c64078246513fa',
                       'd15b47b7845bdc35305ff3b86bc44942bc742b8d'),
 '.lsf-source/apply-verified-sources.cjs': ('.github/security/actions/deploy-pages/applied-source-guard.cjs.snapshot',
                                            11309,
                                            '48dc90cb16ed138f1da2672e018bf35602f8bdd22adbde4caf6c7e3e5da9ce6b',
                                            '5ce26529acb6b82aedf2ff49fdaef5603d405b14'),
 '.lsf-source/security-controls.test.cjs': ('.github/security/actions/deploy-pages/security-controls.test.cjs.snapshot',
                                            17298,
                                            '89329f4116bf44f7f0c7b744e1ec51124737b5816c78999005dbee4ef096d948',
                                            'f3fa3304490b4c930fd7bf88fb77b5e420982727'),
 '.lsf-source/verify-installed-deepmerge.mjs': ('.github/security/actions/deploy-pages/installed-verifier.mjs.snapshot',
                                                2422,
                                                'dd16c19390bedda6e22581e7e53f61696c76a7cb5da3ba39d6511dc078a3c269',
                                                'f356447a8ccf49b9b908d9e7b74bc933e48b4573'),
 '.lsf-source/glob-10.5.0-lsf-abort-v1.repair.json': ('.github/security/actions/download-artifact-source/glob-10.5.0-lsf-abort-v1.repair.json',
                                                      1470,
                                                      'beb9c5bed151b7a67f3b7b384e04ae0c01ca52e093795c042b9b3a3542a54e0f',
                                                      '396c3adcb261b1504f361500cf16e0e178ba15cf'),
 '.lsf-source/glob-10.5.0-lsf-abort-v1.tar': ('.github/security/actions/download-artifact-source/glob-10.5.0-lsf-abort-v1.tar',
                                              542720,
                                              'b2f6d5fb3bd7b63df8454989bfb9d812a29ea67bbbbe81cc5e0e2c4c32e06d68',
                                              'b9f322ede35edfb0f22919ad42e66a325b7486f1'),
 '.lsf-source/glob-10.5.0.original.tgz': ('.github/security/actions/download-artifact-source/glob-10.5.0.original.tgz',
                                          74227,
                                          '18b75cb9c66c8c08bab5cacccd09013c31d3182f1e001c19d8815c5bb46e0802',
                                          'ee1534658a09ff7dd850426ccc27187b675be337'),
 '.lsf-source/minimatch-9.0.9-lsf-bound-v1.repair.json': ('.github/security/actions/download-artifact-source/minimatch-9.0.9-lsf-bound-v1.repair.json',
                                                          2126,
                                                          '67f874fd66ff2bbc9930e5a3529cf15fb7eb9fc15bd7e7d82969c0289b12a207',
                                                          '033a35702e8b0723f5cc1e876224f060d7097eff'),
 '.lsf-source/minimatch-9.0.9-lsf-bound-v1.tar': ('.github/security/actions/download-artifact-source/minimatch-9.0.9-lsf-bound-v1.tar',
                                                  522240,
                                                  '66bcb5a384e44e094efb868280fa4607660da97bbd9d0489eb7cc69eb2da93b2',
                                                  'b5bda540f93f99efa6ec3e7f48ec882e8cba564e'),
 '.lsf-source/minimatch-9.0.9.original.tgz': ('.github/security/actions/download-artifact-source/minimatch-9.0.9.original.tgz',
                                              101396,
                                              '7d28c9a3ef17ce542093c78ec191481503e2711d29db1bd1522062303ab40478',
                                              '3037809c7ece9cb78a316dc322ba4dbeb2df52b6'),
 '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.repair.json': ('.github/security/actions/checkout-source/repair.json',
                                                              3064,
                                                              'e402617d1e791c4bed35768b6c34ba68c370c076551495e738de0731ad2049c7',
                                                              '52602f18647aa2f2bd30f046e05bcce2705a761f'),
 '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.source.json': ('.github/security/actions/checkout-source/declaration.json',
                                                              6925,
                                                              'b4b0b79fa2bc84c6f1e1c61ddcc1ab228df629f9fce4b1067d3ac8b3d1c42892',
                                                              '0685ff353f65174eb5a97cfcb385720dd4a5874c'),
 '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar': ('.github/security/actions/checkout-source/deepmerge-4.3.1.repaired.tar',
                                                      51200,
                                                      'c4ca0f4eb3a2464c026bc3dec5d9eaf04544aed24c3fd1d77da95f85e36c369f',
                                                      '30e23fad3a82fd30bc3f08e26704a0c0bc84c704'),
 '.lsf-source/deepmerge-4.3.1.original.tgz': ('.github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz',
                                              8452,
                                              '4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c',
                                              '1d1560e971dfc484bbe0cb9e8c86bde9140e45b5')}

RUNTIME = {'dist/index.js': {'bytes': 5032045,
                   'sha256': '6afca1e03014a24815b1bd07b000af7d409ff50deaeb39336d981fd86dc8317e',
                   'gitBlob': '9739ab7250dc1fd371faa5a990405213b9243900'},
 'dist/index.js.map': {'bytes': 5946146,
                       'sha256': '41100efb5feee01b35d10f4c825e010ea703c79287e773756e2a770402a5cb96',
                       'gitBlob': '1004a34997339803856978e2100a66ab6b8d14fe'},
 'dist/835.index.js': {'bytes': 660750,
                       'sha256': 'ef21ce95aa5da03df4d6f256d2fe6cfe59b38198d6331a12371ae15221e61c02',
                       'gitBlob': '72fe4fa3ffa01eefdb4f2de4f6ce9f43229dc328'},
 'dist/835.index.js.map': {'bytes': 782267,
                           'sha256': 'a07018c68de28b43de69c576b6674b2195379da0c458cf16ecc68e8192328b87',
                           'gitBlob': 'abe24ee659129171cca2322a8af083cfb9418ed7'},
 'dist/licenses.txt': {'bytes': 22765,
                       'sha256': '7a844415f5cd040c903e71f4316cdcdcd70efc31ccf2193cfc5e74a2bcab09ee',
                       'gitBlob': 'f1eea4fc0237f4040c98ad934cc07cf32e459471'},
 'dist/sourcemap-register.js': {'bytes': 41053,
                                'sha256': 'c2a14a81784d12c15b7baeed88c1faae3457e84890d1e5244cbfc0f4455b5e06',
                                'gitBlob': 'cb1fb13627f07ab9250566c7069e0756f882663a'}}

BUILD = ('.github/security/actions/deploy-pages-source/fork-build.json',
 2414,
 '7112a31fcfa232234407846b4c942b039fd8fb5a736cdcac8ec17d7edbddefa9',
 'd44fa67170e40db46cd47612a12aa1c0f94deddf')

PACKAGES = [{'name': 'glob',
  'version': '10.5.0',
  'path': 'node_modules/glob',
  'dev': False,
  'profile': 'glob-10.5.0-lsf-abort-v1',
  'archive': 'glob-10.5.0-lsf-abort-v1.tar',
  'repair': 'glob-10.5.0-lsf-abort-v1.repair.json',
  'upstream': 'glob-10.5.0.original.tgz',
  'upstreamIntegrity': 'sha512-DfXN8DfhJ7NH3Oe7cFmu3NCu1wKbkReJ8TorzSAFbSKrlNaQSKfIzqYqVY8zlbs2NLBbWpRiU52GX2PbaBVNkg==',
  'derivedIntegrity': 'sha512-SzArNq3qcBAyFfzD7TaRc3iPuTYPa0fayiCH6PPVPxoNnfZg28F7MYVAeLzc2vpb83CDKRHGzF1PNwacQ/5rlw==',
  'dependencies': {'foreground-child': '^3.1.0',
                   'jackspeak': '^3.1.2',
                   'minimatch': '^9.0.4',
                   'minipass': '^7.1.2',
                   'package-json-from-dist': '^1.0.0',
                   'path-scurry': '^1.11.1'}},
 {'name': 'minimatch',
  'version': '9.0.9',
  'path': 'node_modules/glob/node_modules/minimatch',
  'dev': False,
  'profile': 'minimatch-9.0.9-lsf-bound-v1',
  'archive': 'minimatch-9.0.9-lsf-bound-v1.tar',
  'repair': 'minimatch-9.0.9-lsf-bound-v1.repair.json',
  'upstream': 'minimatch-9.0.9.original.tgz',
  'upstreamIntegrity': 'sha512-OBwBN9AL4dqmETlpS2zasx+vTeWclWzkblfZk7KTA5j3jeOONz/tRCnZomUyvNg83wL5Zv9Ss6HMJXAgL8R2Yg==',
  'derivedIntegrity': 'sha512-j4iUvFvT0Ux5eXy2YbJmDXdDCPqJj1hMURp7VvMtvNXMePifDZusaCRqrBgGDDoC0fDZuU1fydoGEiPYberUiA==',
  'dependencies': {'brace-expansion': '^2.0.2'}},
 {'name': 'minimatch',
  'version': '9.0.9',
  'path': 'node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch',
  'dev': True,
  'profile': 'minimatch-9.0.9-lsf-bound-v1',
  'archive': 'minimatch-9.0.9-lsf-bound-v1.tar',
  'repair': 'minimatch-9.0.9-lsf-bound-v1.repair.json',
  'upstream': 'minimatch-9.0.9.original.tgz',
  'upstreamIntegrity': 'sha512-OBwBN9AL4dqmETlpS2zasx+vTeWclWzkblfZk7KTA5j3jeOONz/tRCnZomUyvNg83wL5Zv9Ss6HMJXAgL8R2Yg==',
  'derivedIntegrity': 'sha512-j4iUvFvT0Ux5eXy2YbJmDXdDCPqJj1hMURp7VvMtvNXMePifDZusaCRqrBgGDDoC0fDZuU1fydoGEiPYberUiA==',
  'dependencies': {'brace-expansion': '^2.0.2'}}]


def _read_bound(repo: Path, identity: tuple) -> bytes:
    from tools import security_npm_sources as sources
    snapshot, size, sha256, blob = identity
    raw = read_file(repo, snapshot)
    require(sources.source_identity(raw) == {"bytes": size, "sha256": sha256, "gitBlob": blob},
            "deploy-pages-source-input-drift")
    return raw


def source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    """Bind the actual in-place applier and every source input to one fork tree."""
    from tools import security_npm_sources as sources
    import yaml

    require(set(entry) == {"kind", "path", "lock", "source_repair", "minimatch_source_repair"}
            and entry["kind"] == "npm" and entry["path"] == PREFIX + "package.json"
            and entry["lock"] == PREFIX + "package-lock.json"
            and entry["source_repair"] == DEEP_PROFILE and entry["minimatch_source_repair"] == PROFILE,
            "unreviewed-deploy-pages-profile")
    inputs = {name: _read_bound(repo, row) for name, row in ACTION_INPUTS.items()}
    require(decode_json(inputs["package.json"]) == owner and decode_json(inputs["package-lock.json"]) == lock,
            "deploy-pages-parsed-input-drift")
    guard = inputs[GUARD].decode("utf-8")
    for source, (_, _, sha256, _) in ACTION_INPUTS.items():
        if source in {"package.json", "package-lock.json"} or source.startswith(
                (".lsf-source/glob-", ".lsf-source/minimatch-", ".lsf-source/deepmerge-")):
            require(guard.count(sha256) == 1, "deploy-pages-applier-input-drift")
    expected = [{"snapshot": snapshot, "source": source, "sha256": sha256, "source_sha256": sha256}
                for source, (snapshot, _, sha256, _) in ACTION_INPUTS.items()]
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(REFERENCE, {})
    require(action.get("repository") == "KirilsTurkins/lsf-deploy-pages"
            and action.get("revision") == REFERENCE.split("@")[1] and action.get("kind") == "npm"
            and isinstance(action.get("files"), list)
            and all(isinstance(row, dict) and set(row) == {"snapshot", "source", "sha256", "source_sha256"}
                    for row in action["files"])
            and sorted(action["files"], key=lambda row: row["source"]) == sorted(expected, key=lambda row: row["source"])
            and action.get("metadata") == next(row for row in expected if row["source"] == "action.yml"),
            "deploy-pages-action-binding-drift")
    metadata = yaml.load(inputs["action.yml"], Loader=yaml.BaseLoader)
    require(metadata.get("runs", {}).get("using") == "node24"
            and metadata.get("runs", {}).get("main") == "dist/index.js", "deploy-pages-entrypoint-drift")
    commands = owner.get("scripts", {})
    prefix = "node .lsf-source/apply-verified-sources.cjs && node .lsf-source/verify-installed-deepmerge.mjs && "
    require(commands.get("prepare") == prefix + "ncc build src/index.js -o dist --source-map --license licenses.txt"
            and commands.get("test") == prefix + "jest"
            and commands.get("test:security-source") == "node --test .lsf-source/security-controls.test.cjs",
            "deploy-pages-build-contract-drift")
    require(len(lock.get("packages", {})) == 701, "deploy-pages-lock-count")
    deep_archive = ".lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar"
    deep = lock["packages"].get("node_modules/deepmerge", {})
    require(owner.get("devDependencies", {}).get("deepmerge") == "file:" + deep_archive
            and "deepmerge" not in owner.get("dependencies", {}) and "deepmerge" not in owner.get("overrides", {})
            and deep.get("version") == "4.3.1" and deep.get("dev") is True
            and deep.get("resolved") == "file:" + deep_archive
            and deep.get("integrity") == sources.integrity(inputs[deep_archive])
            and [path for path in lock["packages"] if path.rsplit("node_modules/", 1)[-1] == "deepmerge"]
                == ["node_modules/deepmerge"], "deploy-pages-deepmerge-graph-drift")
    for pkg in PACKAGES:
        row = lock["packages"].get(pkg["path"], {})
        expected_url = f"https://registry.npmjs.org/{pkg['name']}/-/{pkg['name']}-{pkg['version']}.tgz"
        require(row.get("version") == pkg["version"] and bool(row.get("dev", False)) == pkg["dev"]
                and row.get("resolved") == expected_url and row.get("integrity") == pkg["upstreamIntegrity"]
                and row.get("dependencies", {}) == pkg["dependencies"], "deploy-pages-package-graph-drift")
    for name, version, paths in (
            ("glob", "10.5.0", {"node_modules/glob"}),
            ("minimatch", "9.0.9", {"node_modules/glob/node_modules/minimatch",
                                    "node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch"})):
        actual = {path for path, row in lock["packages"].items()
                  if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == name
                  and row.get("version") == version}
        require(actual == paths, "deploy-pages-shadow-installation")
    require(lock["packages"].get("node_modules/archiver", {}).get("version") == "7.0.1"
            and lock["packages"]["node_modules/archiver"].get("dependencies", {}).get("archiver-utils") == "^5.0.2"
            and lock["packages"].get("node_modules/archiver-utils", {}).get("version") == "5.0.2"
            and lock["packages"]["node_modules/archiver-utils"].get("dependencies", {}).get("glob") == "^10.0.0"
            and lock["packages"].get("node_modules/@typescript-eslint/typescript-estree", {})
                .get("dependencies", {}).get("minimatch") == "^9.0.4", "deploy-pages-consumer-graph-drift")
    build = decode_json(_read_bound(repo, BUILD))
    require(build == {
        "schema": 1, "repository": "KirilsTurkins/lsf-deploy-pages",
        "publishedRevision": REFERENCE.split("@")[1], "publishedTree": TREE,
        "sourceHead": "28eb881c437639997329a63ba203044a1e930cef",
        "diagnosticHead": "cac159f297ebd83907e26e57ad07c139d1f03cf8",
        "diagnosticTree": "3cc77d0178fe62389be42f6a2ef144ad2f39f780",
        "diagnosticOnlyPath": ".github/workflows/deploy-pages-linux-probe.yml",
        "run": RUN, "job": 127558041486, "jobConclusion": "success", "node": "24.19.0", "npm": "11.17.0",
        "sourceControls": 7, "formatPassed": True, "rebuiltFilesIdentical": True,
        "artifact": {"id": 13457066659, "bytes": 2265006,
                     "sha256": "488468c35d1aa563165495cf451e36932ba28c045682a5d3b58fc34593a75157", "crcVerified": True},
        "earlierJest": {"sourceHead": "ce5657b184ecb0534e41b6814f1ef8ce74783319", "run": 42115832424,
                        "job": 127555089232, "tests": 32, "suites": 2,
                        "artifact": {"id": 13456511299, "bytes": 2265002,
                                     "sha256": "949f9976f8103c7b307635293457c928d867e07ff963b3dac80617ecdb46aff3",
                                     "crcVerified": True}},
        "bundles": RUNTIME,
    }, "deploy-pages-build-evidence-drift")
    deep_material = {
        "upstream": inputs[".lsf-source/deepmerge-4.3.1.original.tgz"],
        "archive": inputs[deep_archive],
        "repair": inputs[".lsf-source/deepmerge-4.3.1-lsf-prototype-v1.repair.json"],
        "declaration": inputs[".lsf-source/deepmerge-4.3.1-lsf-prototype-v1.source.json"],
    }
    return {"policy": {"advisories": DEEP_ADVISORIES}, "material": deep_material,
            "reference": REFERENCE, "checkout": False, "deploy_pages": True, "inputs": inputs}


def minimatch_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    selected = source_inputs(repo, entry, owner, lock)
    return {"reference": REFERENCE, "material": selected["inputs"]}


def verify_sources(repo: Path, packages: list, configuration: dict, fetch, fetch_runtime) -> list[dict]:
    from tools import security_npm_sources as sources
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("minimatch_source_repair") != PROFILE or not any(item.path == entry["lock"] for item in packages):
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        inputs = source_inputs(repo, entry, owner, lock)["inputs"]
        for path, identity in RUNTIME.items():
            require(sources.source_identity(fetch_runtime(REFERENCE, path)) == identity, "deploy-pages-runtime-drift")
        verified = {}
        for pkg in PACKAGES:
            key = (pkg["name"], pkg["version"])
            pin = {"name": pkg["name"], "version": pkg["version"], "integrity": pkg["upstreamIntegrity"]}
            if key not in verified:
                upstream = fetch(pin)
                require(upstream == inputs[".lsf-source/" + pkg["upstream"]]
                        and sources.integrity(upstream) == pin["integrity"], "deploy-pages-upstream-drift")
                original = sources.members(upstream)
                sources.manifest(original, pkg["name"], pkg["version"], pkg["dependencies"])
                repair_raw = inputs[".lsf-source/" + pkg["repair"]]
                repair = decode_json(repair_raw)
                require(repair.get("profile") == pkg["profile"], "deploy-pages-repair-profile")
                repaired = sources.source_repair(original, repair, pin)
                archive = inputs[".lsf-source/" + pkg["archive"]]
                require(sources.distribution(repaired) == archive
                        and sources.integrity(archive) == pkg["derivedIntegrity"], "deploy-pages-reconstruction-drift")
                verified[key] = repair
        for (name, version), repair in verified.items():
            pkg = next(row for row in PACKAGES if (row["name"], row["version"]) == (name, version))
            receipts.append({"name": name, "version": version, "profile": PROFILE,
                             "upstream_integrity": pkg["upstreamIntegrity"], "derived_integrity": pkg["derivedIntegrity"],
                             "repair_sha256": digest(inputs[".lsf-source/" + pkg["repair"]]),
                             "files": len(repair["files"]), "locks": [entry["lock"]],
                             "advisories": GLOB_ADVISORIES if name == "glob" else MINI_ADVISORIES,
                             "action": REFERENCE, "source_role": "action-runtime-and-build",
                             "built_tree": TREE, "build_run": RUN})
    return receipts
