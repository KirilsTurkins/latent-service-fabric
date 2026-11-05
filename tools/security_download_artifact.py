"""Exact source, lock and hosted runtime receipts for artifact download."""
from __future__ import annotations

from pathlib import Path
from tools import security_setup_go
from tools.security_common import decode_json, digest, read_file, require

REFERENCE = "KirilsTurkins/lsf-download-artifact@dd4ebbadbf12ed34441db2712be7a193490b7fc5"
PREFIX = ".github/security/actions/download-artifact/"
DEEP_PROFILE = "download-artifact-deepmerge-source-v1"
PROFILE = "download-artifact-glob-minimatch-source-v1"
DEEP_VERIFIER = ".lsf-source/verify-installed-deepmerge.mjs"
TREE = "ab1166196538fbdab37cd72ca51557320ae95d35"
RUN = 42113357120
GLOB_ADVISORIES = [{"id": "GHSA-3g3m-2fjr-6pw4", "modified": "2026-10-30T23:15:04.503965Z"}]
MINI_ADVISORIES = [{"id": "GHSA-g3hv-75wg-m249", "modified": "2026-11-04T17:01:25.850114Z"}]

ACTION_INPUTS = {'action.yml': ('.github/security/actions/download-artifact/action.yml.snapshot',
                2635,
                'e98559b7a31ba31be4709f20d22102dc2737fa630f69a339eb89981151e505fe',
                '8b8c65029ccad20750a29fecb438eca5a607fc57'),
 'package.json': ('.github/security/actions/download-artifact/package.json',
                  3068,
                  'e78c659838e884b95965d6f4c611741cdbda89cdc14ba69820a06ca4eab12a9f',
                  'b73a87af8b508ef22313630289a2cf40040772a1'),
 'package-lock.json': ('.github/security/actions/download-artifact/package-lock.json',
                       346889,
                       '8253ed2e30ad4f60d1cad063f5971b0c4c8a2ff5ff8dbd9a5dd4cf31d004a377',
                       'c899f385007adaf40972971ded30af1488c6a678'),
 '.lsf-source/verify-installed-deepmerge.mjs': ('.github/security/actions/deepmerge-source/installed-verifier.mjs.snapshot',
                                                2381,
                                                '55367db845fb579dd45a1a16924bf017c0ddc8f84162d833e368c24a7d629cf7',
                                                '99d75a2ea3895eb8acc8018984ca9826e4edff51'),
 '.lsf-source/verify-download-sources.mjs': ('.github/security/actions/download-artifact/installed-verifier.mjs.snapshot',
                                             3536,
                                             '07f2ee09c6c2fd1f9ec66c86002f97a2fd1cabe4584b54a9d9e7e4c294b78442',
                                             'cba7c91e618d7c25fa6e396042df7f4740cbdcaa'),
 '.lsf-source/download-source.test.mjs': ('.github/security/actions/download-artifact/source.test.mjs.snapshot',
                                          3742,
                                          '082f28d2c9dbb70dfe638c7ef1383a961e6a32ce6c11e0116141ed20006803a0',
                                          'ce104437c6f15160abbcab97c6f183a907918bbb')}

MATERIAL = {'download-source-files.json': ('.github/security/actions/download-artifact-source/download-source-files.json',
                                25944,
                                '8ecad9f742c58b6fb49ea17c0d5dcc90e5be3b9d7a6f3c5eaa6349f5e2c89f66',
                                'ee65ae6fcd990cb3362551870f18dca42f3bad65'),
 'fork-build.json': ('.github/security/actions/download-artifact-source/fork-build.json',
                     1320,
                     'd36f53916e56cdb9067fbadc2ae8737226c7b8e5b6b5925fdad3610b5845c95f',
                     '91c2ffcc607a76a834399a0d109e1f0fa5916ac3'),
 'glob-10.5.0-lsf-abort-v1.repair.json': ('.github/security/actions/download-artifact-source/glob-10.5.0-lsf-abort-v1.repair.json',
                                          1470,
                                          'beb9c5bed151b7a67f3b7b384e04ae0c01ca52e093795c042b9b3a3542a54e0f',
                                          '396c3adcb261b1504f361500cf16e0e178ba15cf'),
 'glob-10.5.0-lsf-abort-v1.tar': ('.github/security/actions/download-artifact-source/glob-10.5.0-lsf-abort-v1.tar',
                                  542720,
                                  'b2f6d5fb3bd7b63df8454989bfb9d812a29ea67bbbbe81cc5e0e2c4c32e06d68',
                                  'b9f322ede35edfb0f22919ad42e66a325b7486f1'),
 'glob-10.5.0.original.tgz': ('.github/security/actions/download-artifact-source/glob-10.5.0.original.tgz',
                              74227,
                              '18b75cb9c66c8c08bab5cacccd09013c31d3182f1e001c19d8815c5bb46e0802',
                              'ee1534658a09ff7dd850426ccc27187b675be337'),
 'minimatch-10.2.6-lsf-bound-v1.repair.json': ('.github/security/actions/download-artifact-source/minimatch-10.2.6-lsf-bound-v1.repair.json',
                                               2129,
                                               'd6ede52113aa8cb2d4b6ee008885fd2de0d37e06d822e444846f6f905f088bf3',
                                               '42886b2bc898bf44b955fc31ff963bb91a94bcc9'),
 'minimatch-10.2.6-lsf-bound-v1.tar': ('.github/security/actions/download-artifact-source/minimatch-10.2.6-lsf-bound-v1.tar',
                                       583680,
                                       'bb2b80a4759baaee01d49528b2d7d0c05fc29c1cf0d3fea41ec243de04bceedb',
                                       '2a1f40a7420f3cfb13e5284e433b19ec6db1e145'),
 'minimatch-10.2.6.original.tgz': ('.github/security/actions/download-artifact-source/minimatch-10.2.6.original.tgz',
                                   117068,
                                   '5a3d2c8074a28229665727e47b8a1090941856a7962905efe05d20d3760355f8',
                                   'cc4d199bec4264ab80b9b228da85f074b045edf5'),
 'minimatch-9.0.9-lsf-bound-v1.repair.json': ('.github/security/actions/download-artifact-source/minimatch-9.0.9-lsf-bound-v1.repair.json',
                                              2126,
                                              '67f874fd66ff2bbc9930e5a3529cf15fb7eb9fc15bd7e7d82969c0289b12a207',
                                              '033a35702e8b0723f5cc1e876224f060d7097eff'),
 'minimatch-9.0.9-lsf-bound-v1.tar': ('.github/security/actions/download-artifact-source/minimatch-9.0.9-lsf-bound-v1.tar',
                                      522240,
                                      '66bcb5a384e44e094efb868280fa4607660da97bbd9d0489eb7cc69eb2da93b2',
                                      'b5bda540f93f99efa6ec3e7f48ec882e8cba564e'),
 'minimatch-9.0.9.original.tgz': ('.github/security/actions/download-artifact-source/minimatch-9.0.9.original.tgz',
                                  101396,
                                  '7d28c9a3ef17ce542093c78ec191481503e2711d29db1bd1522062303ab40478',
                                  '3037809c7ece9cb78a316dc322ba4dbeb2df52b6')}

RUNTIME = {'dist/index.js': {'bytes': 4683804,
                   'sha256': 'caac8449a3cfb152b39fc3d21c1089a134a235e9ed9fcfd0ed2b5530e9cfc2ab',
                   'gitBlob': 'bab2149e86267e2bed9b887d9a9322150f61861c'}}

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
  'dependencies': {'brace-expansion': '^2.0.2'}},
 {'name': 'minimatch',
  'version': '10.2.6',
  'path': 'node_modules/minimatch',
  'dev': False,
  'profile': 'minimatch-10.2.6-lsf-bounds-v1',
  'archive': 'minimatch-10.2.6-lsf-bound-v1.tar',
  'repair': 'minimatch-10.2.6-lsf-bound-v1.repair.json',
  'upstream': 'minimatch-10.2.6.original.tgz',
  'upstreamIntegrity': 'sha512-vpLQEs+VLCr1nU0BXS07maYoFwlDAH0gngQuuttxIwutDFEMHq2blX+8vpgxDdK3J1PwjCJiep77OitTZ4Ll1A==',
  'derivedIntegrity': 'sha512-d4q29f9UKl/jVXZqsE8JNas2oBfjjDeYRQEzYfbPFlEOx3cNnrJzyS48JO1wCCqcRAjOnDnkQfCKcCXFAyuLow==',
  'dependencies': {'brace-expansion': '^5.0.8'}}]


def _material(repo: Path, identities: dict) -> dict:
    from tools import security_npm_sources as sources
    result = {}
    for name, (snapshot, size, sha256, blob) in identities.items():
        raw = read_file(repo, snapshot)
        require(sources.source_identity(raw) == {"bytes": size, "sha256": sha256, "gitBlob": blob},
                "download-action-source-input-drift")
        result[name] = raw
    return result


def source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    from tools import security_npm_sources as sources
    require(set(entry) == {"kind", "path", "lock", "source_repair", "minimatch_source_repair"}
            and entry["kind"] == "npm" and entry["path"] == PREFIX + "package.json"
            and entry["lock"] == PREFIX + "package-lock.json" and entry["source_repair"] == DEEP_PROFILE
            and entry["minimatch_source_repair"] == PROFILE, "unreviewed-download-action-profile")
    inputs = _material(repo, ACTION_INPUTS)
    deep = _material(repo, security_setup_go.DEEP_MATERIAL)
    material = _material(repo, MATERIAL)
    require(decode_json(inputs["package.json"]) == owner and decode_json(inputs["package-lock.json"]) == lock,
            "download-action-parsed-input-drift")
    expected = [{"snapshot": snapshot, "source": source, "sha256": sha256, "source_sha256": sha256}
                for source, (snapshot, _, sha256, _) in ACTION_INPUTS.items()]
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(REFERENCE, {})
    metadata = next(row for row in expected if row["source"] == "action.yml")
    require(action.get("repository") == "KirilsTurkins/lsf-download-artifact"
            and action.get("revision") == REFERENCE.split("@")[1] and action.get("kind") == "npm"
            and isinstance(action.get("files"), list)
            and sorted(action["files"], key=lambda row: row["source"]) == sorted(expected, key=lambda row: row["source"])
            and action.get("metadata") == metadata, "download-action-binding-drift")
    node = lock["packages"].get("node_modules/deepmerge", {})
    require(owner.get("devDependencies", {}).get("deepmerge") == sources.CHECKOUT_ARCHIVE
            and "deepmerge" not in owner.get("dependencies", {}) and "deepmerge" not in owner.get("overrides", {})
            and node.get("version") == "4.3.1" and node.get("dev") is True
            and node.get("resolved") == sources.CHECKOUT_ARCHIVE
            and node.get("integrity") == sources.integrity(deep["archive"])
            and [p for p in lock["packages"] if p.rsplit("node_modules/", 1)[-1] == "deepmerge"]
                == ["node_modules/deepmerge"], "unlocked-download-deepmerge")
    require(owner.get("dependencies", {}).get("minimatch") == "file:.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar"
            and owner.get("devDependencies", {}).get("glob") == "file:.lsf-source/glob-10.5.0-lsf-abort-v1.tar"
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and owner.get("overrides", {}).get("glob@10") == {
                ".": "$glob", "minimatch": "file:../../.lsf-source/minimatch-9.0.9-lsf-bound-v1.tar"}
            and owner.get("overrides", {}).get("@typescript-eslint/typescript-estree") == {
                "minimatch": "file:../../../.lsf-source/minimatch-9.0.9-lsf-bound-v1.tar"},
            "unlocked-download-action-owner")
    commands = owner.get("scripts", {})
    prefix = "node .lsf-source/verify-installed-deepmerge.mjs && node .lsf-source/verify-download-sources.mjs && "
    require(commands.get("build") == prefix + "tsc"
            and commands.get("release") == prefix + "ncc build src/download-artifact.ts && git add -f dist/",
            "download-action-build-contract-drift")
    for pkg in PACKAGES:
        node = lock["packages"].get(pkg["path"], {})
        require(node.get("version") == pkg["version"] and bool(node.get("dev", False)) == pkg["dev"]
                and node.get("resolved") == "file:.lsf-source/" + pkg["archive"]
                and node.get("integrity") == pkg["derivedIntegrity"]
                and sources.integrity(material[pkg["archive"]]) == pkg["derivedIntegrity"],
                "unlocked-download-action-source")
    for name, major, expected_paths in (
            ("glob", "10.", {"node_modules/glob"}),
            ("minimatch", "9.", {"node_modules/glob/node_modules/minimatch",
                                "node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch"}),
            ("minimatch", "10.", {"node_modules/minimatch"})):
        actual = {path for path, row in lock["packages"].items()
                  if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == name
                  and str(row.get("version", "")).startswith(major)}
        require(actual == expected_paths, "unreviewed-download-action-shadow-source")
    build = decode_json(material["fork-build.json"])
    require(build["schema"] == 1 and build["repository"] == "KirilsTurkins/lsf-download-artifact"
            and build["publishedRevision"] == REFERENCE.split("@")[1] and build["publishedTree"] == TREE
            and build["sourceHead"] == "39d52ac2a2c6731c2d836e923b5221ebd0d4d8e9"
            and build["diagnosticHead"] == "b1b184f23784f8b32b6d454764a51b1b87e00e06"
            and build["diagnosticTree"] == "4afa10c0827dde75934dd82621dc44bcf54a192a"
            and build["diagnosticOnlyPath"] == ".github/workflows/lsf-download-security-owner.yml"
            and build["run"] == RUN and build["job"] == 127546428787 and build["jobConclusion"] == "success"
            and build["node"] == "24.19.0" and build["npm"] == "11.17.0"
            and build["jestSuites"] == 1 and build["jestTests"] == 21 and build["sourceControls"] == 3
            and build["rebuiltBundleIdentical"] is True and build["artifactDownloadMatched"] is True
            and build["artifact"] == {"id": 13455382700, "bytes": 1704956,
                "sha256": "9429625c4ca047ce699d6eebefd4d6b7145ca80e5e010a66c77c68872bb33b84",
                "members": 25, "checkedFiles": 24, "crcVerified": True}
            and build["markerArtifact"] == {"id": 13454928092, "bytes": 168,
                "sha256": "41bb45641ad6ea12b6a1f200744c1ce0f815497558f6fdd61cdcf1cfef002fc6", "crcVerified": True}
            and build["bundles"] == RUNTIME, "download-action-build-evidence-drift")
    return {"policy": {"advisories": security_setup_go.DEEP_ADVISORIES}, "material": deep,
            "reference": REFERENCE, "checkout": False, "download_artifact": True, "repaired": material}


def minimatch_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    selected = source_inputs(repo, entry, owner, lock)
    return {"reference": REFERENCE, "material": selected["repaired"]}


def libraries() -> dict:
    rows = {(pkg["name"], pkg["version"]): {"version": pkg["version"],
             "resolved": "file:.lsf-source/" + pkg["archive"], "integrity": pkg["derivedIntegrity"]} for pkg in PACKAGES}
    return {"glob": rows[("glob", "10.5.0")], "minimatch": [rows[("minimatch", "9.0.9")], rows[("minimatch", "10.2.6")]]}


def verify_sources(repo: Path, packages: list, configuration: dict, fetch, fetch_runtime) -> list[dict]:
    from tools import security_npm_sources as sources
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("minimatch_source_repair") != PROFILE or not any(item.path == entry["lock"] for item in packages):
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        selected = source_inputs(repo, entry, owner, lock)
        for path, identity in RUNTIME.items():
            require(sources.source_identity(fetch_runtime(REFERENCE, path)) == identity, "download-action-runtime-drift")
        material = selected["repaired"]
        manifest = decode_json(material["download-source-files.json"])
        require(set(manifest) == {"schema", "packages"} and manifest["schema"] == 1
                and isinstance(manifest["packages"], list) and len(manifest["packages"]) == len(PACKAGES),
                "download-action-installed-manifest-drift")
        verified = {}
        for pkg in PACKAGES:
            key = (pkg["name"], pkg["version"])
            pin = {"name": pkg["name"], "version": pkg["version"], "integrity": pkg["upstreamIntegrity"]}
            if key not in verified:
                upstream = fetch(pin)
                require(upstream == material[pkg["upstream"]] and sources.integrity(upstream) == pin["integrity"],
                        "download-action-upstream-drift")
                original = sources.members(upstream)
                sources.manifest(original, pkg["name"], pkg["version"], pkg["dependencies"])
                repair = decode_json(material[pkg["repair"]])
                require(repair.get("profile") == pkg["profile"], "download-action-repair-profile")
                repaired = sources.source_repair(original, repair, pin)
                require(sources.distribution(repaired) == material[pkg["archive"]]
                        and sources.integrity(material[pkg["archive"]]) == pkg["derivedIntegrity"],
                        "download-action-reconstruction-drift")
                verified[key] = (upstream, repair, repaired)
            upstream, repair, repaired = verified[key]
            installed = [row for row in manifest["packages"]
                         if (row.get("name"), row.get("version"), row.get("target")) == (pkg["name"], pkg["version"], pkg["path"])]
            require(len(installed) == 1 and installed[0] == {
                "name": pkg["name"], "version": pkg["version"], "target": pkg["path"],
                "archive": pkg["archive"], "archiveSha256": digest(material[pkg["archive"]]),
                "original": pkg["upstream"], "originalSha256": digest(upstream),
                "repair": pkg["repair"], "repairSha256": digest(material[pkg["repair"]]),
                "files": {path.removeprefix("package/"): digest(value[0]) for path, value in sorted(repaired.items())}},
                "download-action-installed-manifest-drift")
        for name, version in verified:
            pkg = next(p for p in PACKAGES if (p["name"], p["version"]) == (name, version))
            _, repair, _ = verified[(name, version)]
            receipts.append({"name": name, "version": version, "profile": PROFILE,
                "upstream_integrity": pkg["upstreamIntegrity"], "derived_integrity": pkg["derivedIntegrity"],
                "repair_sha256": digest(material[pkg["repair"]]), "files": len(repair["files"]),
                "locks": [entry["lock"]], "advisories": GLOB_ADVISORIES if name == "glob" else MINI_ADVISORIES,
                "action": REFERENCE, "source_role": "action-runtime-and-build", "built_tree": TREE, "build_run": RUN})
    return receipts
