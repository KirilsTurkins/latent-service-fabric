"""Exact source, lock and hosted runtime receipts for artifact upload."""
from __future__ import annotations

from pathlib import Path
from tools import security_setup_go
from tools.security_action_rebuild import verify_rebuild
from tools.security_common import decode_json, digest, read_file, require

REFERENCE = 'KirilsTurkins/lsf-upload-artifact@c37718fd4e24a4c372572ce4f21b3969a72ba8dc'
PREFIX = ".github/security/actions/upload-artifact/"
DEEP_PROFILE = "upload-artifact-deepmerge-source-v1"
PROFILE = "upload-artifact-glob-minimatch-source-v1"
DEEP_VERIFIER = ".lsf-source/verify-installed-deepmerge.mjs"
TREE = "671a59ec07208d10b7e56b65c4905a3e5182cbe0"
RUN = 43523231069
GLOB_ADVISORIES = [{"id": "GHSA-3g3m-2fjr-6pw4", "modified": "2026-10-30T23:15:04.503965Z"}]
MINI_ADVISORIES = [{"id": "GHSA-g3hv-75wg-m249", "modified": "2026-11-04T17:01:25.850114Z"}]

ACTION_INPUTS = {'action.yml': ('.github/security/actions/upload-artifact/action.yml.snapshot',
                3603,
                'c5979822866a72362e609844b6ebe77d4b7e759af68cc1c2c425dcf51481fab4',
                '7cb4d1e81db55320b41217e1a78a1a46e3d2baef'),
 'package.json': ('.github/security/actions/upload-artifact/package.json',
                  2922,
                  '81625816f3d06ad20e697c1080c24a9920e434bceb653062e948053194994b99',
                  '33963c8ce0b8ba90d7397300d757b5d4fc763aba'),
 'package-lock.json': ('.github/security/actions/upload-artifact/package-lock.json',
                       352042,
                       'f9ddfd3bac09c291181898b71b52d0f5024bdfdf43169999ca3dd2d76d8166cb',
                       '5cd0bdb369839cdf35da2fe020870b2efe5404d5'),
 '.lsf-source/verify-installed-deepmerge.mjs': ('.github/security/actions/deepmerge-source/installed-verifier.mjs.snapshot',
                                                2381,
                                                '55367db845fb579dd45a1a16924bf017c0ddc8f84162d833e368c24a7d629cf7',
                                                '99d75a2ea3895eb8acc8018984ca9826e4edff51'),
 '.lsf-source/verify-upload-sources.mjs': ('.github/security/actions/upload-artifact/installed-verifier.mjs.snapshot',
                                           3379,
                                           '8f2ea6fbd697895126301d2e52efa1122893c616cae83f68f388cb170a6fba03',
                                           'afae31dc92975b8bd43f097930fdfc2023ecf9d9'),
 '.lsf-source/upload-source.test.mjs': ('.github/security/actions/upload-artifact/source.test.mjs.snapshot',
                                        3482,
                                        '4d459c993e9e80a7f555fbcc05e2fe03cda3cd834b01a21de7eba91bba65bdd0',
                                        '2e43956cff1cdda12a30e36a14be14749865438e')}

MATERIAL = {'fork-build.json': ('.github/security/actions/upload-artifact-source/fork-build.json',
                     5598,
                     '1d6c450b74b6b6f2d3f5b22ba494055ae140f5c742f193e0947bdeaae77bf8c3',
                     '89cf5da33281e1e3b63dec1cd32461a51b8c85b4'),
 'glob-10.5.0-lsf-abort-v1.repair.json': ('.github/security/actions/upload-artifact-source/glob-10.5.0-lsf-abort-v1.repair.json',
                                          1470,
                                          'beb9c5bed151b7a67f3b7b384e04ae0c01ca52e093795c042b9b3a3542a54e0f',
                                          '396c3adcb261b1504f361500cf16e0e178ba15cf'),
 'glob-10.5.0-lsf-abort-v1.tar': ('.github/security/actions/upload-artifact-source/glob-10.5.0-lsf-abort-v1.tar',
                                  542720,
                                  'b2f6d5fb3bd7b63df8454989bfb9d812a29ea67bbbbe81cc5e0e2c4c32e06d68',
                                  'b9f322ede35edfb0f22919ad42e66a325b7486f1'),
 'glob-10.5.0.original.tgz': ('.github/security/actions/upload-artifact-source/glob-10.5.0.original.tgz',
                              74227,
                              '18b75cb9c66c8c08bab5cacccd09013c31d3182f1e001c19d8815c5bb46e0802',
                              'ee1534658a09ff7dd850426ccc27187b675be337'),
 'minimatch-10.2.4-lsf-bound-v1.repair.json': ('.github/security/actions/upload-artifact-source/minimatch-10.2.4-lsf-bound-v1.repair.json',
                                               2129,
                                               '5e2899aed59a7869398abad36c11a7055270aff2b1ec708cf9aaaf3396243ff7',
                                               'cc7528d6c0c1ae8495fe9a10163e31b7258f8179'),
 'minimatch-10.2.4-lsf-bound-v1.tar': ('.github/security/actions/upload-artifact-source/minimatch-10.2.4-lsf-bound-v1.tar',
                                       583680,
                                       'c49483cedaf913bf8b0d5ecc9076a4480b085249177eb0e0147a2cbb66c2d0b9',
                                       '04ecf9481b0d1e6e0d098e3cbfa442a393956c5d'),
 'minimatch-10.2.4.original.tgz': ('.github/security/actions/upload-artifact-source/minimatch-10.2.4.original.tgz',
                                   116656,
                                   '89d2c40b4596326c5061d95a63a13c5b757f3e03bcad229ab496a66735925529',
                                   '10197a0e2a9aa1eead71a3aed966b6cb0c0f7c83'),
 'minimatch-9.0.8-lsf-bound-v1.repair.json': ('.github/security/actions/upload-artifact-source/minimatch-9.0.8-lsf-bound-v1.repair.json',
                                              2127,
                                              '79721845b1a7cd757a41af8aa026e38e21b368b297fd4c64ae765faec70836c3',
                                              'c5677be690e450376d2cf8a18134b7f3f8775992'),
 'minimatch-9.0.8-lsf-bound-v1.tar': ('.github/security/actions/upload-artifact-source/minimatch-9.0.8-lsf-bound-v1.tar',
                                      522240,
                                      'ecf47ae12fe49e170da5736fd4170dbc21faa7239f68eebd34db17c9667a2d6e',
                                      '60b896f17efbd5bf807ec4be734df0d8c2a02139'),
 'minimatch-9.0.8.original.tgz': ('.github/security/actions/upload-artifact-source/minimatch-9.0.8.original.tgz',
                                  101307,
                                  'a4f44e3da8129504b0c0c085b0d46fd0cf2587d522bd1f93863c611edcd8c1cd',
                                  'dfefa9a570d250e8aeb9b8c7932fd10946f7341d'),
 'upload-source-files.json': ('.github/security/actions/upload-artifact-source/upload-source-files.json',
                              19699,
                              'b991a3713ac8f768f7c794d63dea0b8c9f7ef9b772b606b850c02eb7c15685a7',
                              '975c8dfecb59cdebb2ed6468f89ec882432ddbc6')}

RUNTIME = {'dist/upload/index.js': {'bytes': 4682514,
                          'sha256': 'c0664af834ce822489f7975d46910d2cf88e0afab9e42f3d83cedb85cbd34b56',
                          'gitBlob': 'b62ad93c277fc35ce61ee7a78860601e31768cca'},
 'dist/merge/index.js': {'bytes': 4779783,
                         'sha256': 'afb70515ca97f068d994ad92497e740680c2254f84943e9dc92457e15f2c7903',
                         'gitBlob': '282adc271c5c99c65b28d1ba6652343f987bd49f'}}

PACKAGES = [{'name': 'glob',
  'version': '10.5.0',
  'path': 'node_modules/glob',
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
  'version': '9.0.8',
  'path': 'node_modules/glob/node_modules/minimatch',
  'profile': 'minimatch-9.0.8-lsf-bounds-v1',
  'archive': 'minimatch-9.0.8-lsf-bound-v1.tar',
  'repair': 'minimatch-9.0.8-lsf-bound-v1.repair.json',
  'upstream': 'minimatch-9.0.8.original.tgz',
  'upstreamIntegrity': 'sha512-reYkDYtj/b19TeqbNZCV4q9t+Yxylf/rYBsLb42SXJatTv4/ylq5lEiAmhA/IToxO7NI2UzNMghHoHuaqDkAjw==',
  'derivedIntegrity': 'sha512-9zT+MseFKtqTn4C3cr89FhtfjlMHdedifOZgFHtxVf+cew8ChbwImWWGYdRSTprMnDXH63dLiCPADic1aQxIOQ==',
  'dependencies': {'brace-expansion': '^5.0.2'}},
 {'name': 'minimatch',
  'version': '10.2.4',
  'path': 'node_modules/minimatch',
  'profile': 'minimatch-10.2.4-lsf-bounds-v1',
  'archive': 'minimatch-10.2.4-lsf-bound-v1.tar',
  'repair': 'minimatch-10.2.4-lsf-bound-v1.repair.json',
  'upstream': 'minimatch-10.2.4.original.tgz',
  'upstreamIntegrity': 'sha512-oRjTw/97aTBN0RHbYCdtF1MQfvusSIBQM0IZEgzl6426+8jSC0nF1a/GmnVLpfB9yyr6g6FTqWqiZVbxrtaCIg==',
  'derivedIntegrity': 'sha512-D+2DH1bFDW0dGn00ZhGpLKHwNAVjowmmWXci7T7IZlik1rluDJvYEEg/HL1BQ5WCmDH9INdBLf73sl0c6jkdlg==',
  'dependencies': {'brace-expansion': '^5.0.2'}}]


def _material(repo: Path, identities: dict) -> dict:
    from tools import security_npm_sources as sources
    result = {}
    for name, (snapshot, size, sha256, blob) in identities.items():
        raw = read_file(repo, snapshot)
        require(sources.source_identity(raw) == {"bytes": size, "sha256": sha256, "gitBlob": blob},
                "upload-action-source-input-drift")
        result[name] = raw
    return result


def source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    from tools import security_npm_sources as sources
    require(set(entry) == {"kind", "path", "lock", "source_repair", "minimatch_source_repair"}
            and entry["kind"] == "npm" and entry["path"] == PREFIX + "package.json"
            and entry["lock"] == PREFIX + "package-lock.json" and entry["source_repair"] == DEEP_PROFILE
            and entry["minimatch_source_repair"] == PROFILE, "unreviewed-upload-action-profile")
    inputs = _material(repo, ACTION_INPUTS)
    deep = _material(repo, security_setup_go.DEEP_MATERIAL)
    material = _material(repo, MATERIAL)
    require(decode_json(inputs["package.json"]) == owner and decode_json(inputs["package-lock.json"]) == lock,
            "upload-action-parsed-input-drift")
    expected = [{"snapshot": snapshot, "source": source, "sha256": sha256, "source_sha256": sha256}
                for source, (snapshot, _, sha256, _) in ACTION_INPUTS.items()]
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(REFERENCE, {})
    metadata = next(row for row in expected if row["source"] == "action.yml")
    require(action.get("repository") == "KirilsTurkins/lsf-upload-artifact"
            and action.get("revision") == REFERENCE.split("@")[1] and action.get("kind") == "npm"
            and isinstance(action.get("files"), list)
            and sorted(action["files"], key=lambda row: row["source"]) == sorted(expected, key=lambda row: row["source"])
            and action.get("metadata") == metadata, "upload-action-binding-drift")
    deep_node = lock["packages"].get("node_modules/deepmerge", {})
    require(owner.get("devDependencies", {}).get("deepmerge") == sources.CHECKOUT_ARCHIVE
            and "deepmerge" not in owner.get("dependencies", {}) and "deepmerge" not in owner.get("overrides", {})
            and deep_node.get("version") == "4.3.1" and deep_node.get("dev") is True
            and deep_node.get("resolved") == sources.CHECKOUT_ARCHIVE
            and deep_node.get("integrity") == sources.integrity(deep["archive"])
            and [p for p in lock["packages"] if p.rsplit("node_modules/", 1)[-1] == "deepmerge"]
                == ["node_modules/deepmerge"], "unlocked-upload-deepmerge")
    require(owner.get("dependencies", {}).get("minimatch") == "file:.lsf-source/minimatch-10.2.4-lsf-bound-v1.tar"
            and owner.get("devDependencies", {}).get("glob") == "file:.lsf-source/glob-10.5.0-lsf-abort-v1.tar"
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and owner.get("overrides", {}).get("glob@10") == {
                ".": "$glob", "minimatch": "file:../../.lsf-source/minimatch-9.0.8-lsf-bound-v1.tar"},
            "unlocked-upload-action-owner")
    commands = owner.get("scripts", {})
    prefix = "node .lsf-source/verify-installed-deepmerge.mjs && node .lsf-source/verify-upload-sources.mjs && "
    require(commands.get("build") == prefix + "tsc"
            and commands.get("release") == prefix + "ncc build src/upload/index.ts -o dist/upload && ncc build src/merge/index.ts -o dist/merge",
            "upload-action-build-contract-drift")
    for pkg in PACKAGES:
        node = lock["packages"].get(pkg["path"], {})
        require(node.get("version") == pkg["version"] and not node.get("dev", False)
                and node.get("resolved") == "file:.lsf-source/" + pkg["archive"]
                and node.get("integrity") == pkg["derivedIntegrity"]
                and sources.integrity(material[pkg["archive"]]) == pkg["derivedIntegrity"],
                "unlocked-upload-action-source")
    for name, major, expected_paths in (
            ("glob", "10.", {"node_modules/glob"}),
            ("minimatch", "9.", {"node_modules/glob/node_modules/minimatch"}),
            ("minimatch", "10.", {"node_modules/minimatch"})):
        actual = {path for path, row in lock["packages"].items()
                  if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == name
                  and str(row.get("version", "")).startswith(major)}
        require(actual == expected_paths, "unreviewed-upload-action-shadow-source")
    build = decode_json(material["fork-build.json"])
    verify_rebuild(repo, build, REFERENCE, RUNTIME)
    return {"policy": {"advisories": security_setup_go.DEEP_ADVISORIES}, "material": deep,
            "reference": REFERENCE, "checkout": False, "upload_artifact": True, "repaired": material}


def minimatch_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    selected = source_inputs(repo, entry, owner, lock)
    return {"reference": REFERENCE, "material": selected["repaired"]}


def libraries() -> dict:
    rows = [{"version": pkg["version"], "resolved": "file:.lsf-source/" + pkg["archive"],
             "integrity": pkg["derivedIntegrity"]} for pkg in PACKAGES]
    return {"glob": rows[0], "minimatch": rows[1:]}


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
            require(sources.source_identity(fetch_runtime(REFERENCE, path)) == identity, "upload-action-runtime-drift")
        material = selected["repaired"]
        manifest = decode_json(material["upload-source-files.json"])
        require(set(manifest) == {"schema", "packages"} and manifest["schema"] == 1
                and isinstance(manifest["packages"], list) and len(manifest["packages"]) == len(PACKAGES),
                "upload-action-installed-manifest-drift")
        for pkg in PACKAGES:
            pin = {"name": pkg["name"], "version": pkg["version"], "integrity": pkg["upstreamIntegrity"]}
            upstream = fetch(pin)
            require(upstream == material[pkg["upstream"]] and sources.integrity(upstream) == pin["integrity"],
                    "upload-action-upstream-drift")
            original = sources.members(upstream)
            sources.manifest(original, pkg["name"], pkg["version"], pkg["dependencies"])
            repair = decode_json(material[pkg["repair"]])
            require(repair.get("profile") == pkg["profile"], "upload-action-repair-profile")
            repaired = sources.source_repair(original, repair, pin)
            require(sources.distribution(repaired) == material[pkg["archive"]]
                    and sources.integrity(material[pkg["archive"]]) == pkg["derivedIntegrity"],
                    "upload-action-reconstruction-drift")
            installed = [row for row in manifest["packages"]
                         if (row.get("name"), row.get("version")) == (pkg["name"], pkg["version"])]
            require(len(installed) == 1 and installed[0] == {
                "name": pkg["name"], "version": pkg["version"], "target": pkg["path"],
                "archive": pkg["archive"], "archiveSha256": digest(material[pkg["archive"]]),
                "original": pkg["upstream"], "originalSha256": digest(upstream),
                "repair": pkg["repair"], "repairSha256": digest(material[pkg["repair"]]),
                "files": {path.removeprefix("package/"): digest(value[0]) for path, value in sorted(repaired.items())}},
                "upload-action-installed-manifest-drift")
            receipts.append({"name": pkg["name"], "version": pkg["version"], "profile": PROFILE,
                "upstream_integrity": pin["integrity"], "derived_integrity": pkg["derivedIntegrity"],
                "repair_sha256": digest(material[pkg["repair"]]), "files": len(repair["files"]),
                "locks": [entry["lock"]], "advisories": GLOB_ADVISORIES if pkg["name"] == "glob" else MINI_ADVISORIES,
                "action": REFERENCE, "source_role": "action-runtime-and-build", "built_tree": TREE, "build_run": RUN})
    return receipts
