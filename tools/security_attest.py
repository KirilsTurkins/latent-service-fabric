"""Exact source and runtime receipts for the reviewed attest action and wrapper."""
from __future__ import annotations

from pathlib import Path

from tools.security_common import decode_json, digest, read_file, require

REFERENCE = 'KirilsTurkins/lsf-attest@ac3d77bef0ab118e8a29decb53e9f03622ee7299'
WRAPPER_REFERENCE = 'KirilsTurkins/lsf-attest-build-provenance@d67c304058531c46441ba89c83b3bbe075fd9d00'
PROFILE = "attest-six-source-v1"
PREFIX = ".github/security/actions/attest/"
TREE = "02f94d909cefa3fa466bbfa696f25c0e5626a3eb"
WRAPPER_TREE = "9dff91ae9cff4548b3d6a5c5f614c0eb2a4786ba"
ACTION_INPUTS = {'action.yml': ('.github/security/actions/attest/action.yml.snapshot',
                4048,
                '9e4a1b808433f9ec87120b534e11fc35469a039bdbdc62b019441444c9ad0449',
                'f3d593f3020cf14b65d2789e3788d015354475e9'),
 'package.json': ('.github/security/actions/attest/package.json',
                  3707,
                  '0aca1ae0279456064de8ff3e61bf8db2921c1aea54b036690a1f752f0d5bf9ee',
                  '5af7995e7142b1442476dc82fd481e6bf20901fe'),
 'package-lock.json': ('.github/security/actions/attest/package-lock.json',
                       401179,
                       '85c2e5de3af4b1539e89d4bab1a7da6962abafa7dc8c87d7852ef690c004f947',
                       '923cff285fe62ddcb8fb1889023148a24d49c89a'),
 '.lsf-source/README.md': ('.github/security/actions/attest-source/README.md',
                           1808,
                           '3a782037d69fcf7328bfa85b02a82cac872fb7296dd9508dae63dea04c83fe8e',
                           'cceebb0ea4aa93544906be4c4424bb2faef8066a'),
 '.lsf-source/attest-source-files.json': ('.github/security/actions/attest-source/attest-source-files.json',
                                          36261,
                                          '2bba9695beb83b99501e6ac6c58c35d6f7079d59740aa11c94996ca912e3c7fd',
                                          '34e7df7df07571387142c3dfec50aba13dca2bce'),
 '.lsf-source/attest-sources.test.mjs': ('.github/security/actions/attest-source/attest-sources.test.mjs',
                                         6836,
                                         '99f331c5cbe0bc28b0dd3b1bf1e574e89b032c378c6de933821994f50091b2d3',
                                         '1ac8e245492ce26d5114bb94da98acc900a006ae'),
 '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.repair.json': ('.github/security/actions/checkout-source/repair.json',
                                                              3064,
                                                              'e402617d1e791c4bed35768b6c34ba68c370c076551495e738de0731ad2049c7',
                                                              '52602f18647aa2f2bd30f046e05bcce2705a761f'),
 '.lsf-source/deepmerge-4.3.1-lsf-prototype-v1.tar': ('.github/security/actions/checkout-source/deepmerge-4.3.1.repaired.tar',
                                                      51200,
                                                      'c4ca0f4eb3a2464c026bc3dec5d9eaf04544aed24c3fd1d77da95f85e36c369f',
                                                      '30e23fad3a82fd30bc3f08e26704a0c0bc84c704'),
 '.lsf-source/deepmerge-4.3.1.original.tgz': ('.github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz',
                                              8452,
                                              '4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c',
                                              '1d1560e971dfc484bbe0cb9e8c86bde9140e45b5'),
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
 '.lsf-source/glob-13.0.6-lsf-abort-bounds-v1.repair.json': ('.github/security/actions/attest-source/glob-13.0.6-lsf-abort-bounds-v1.repair.json',
                                                             4200,
                                                             'f9c6768faf3d2fc155565a9bde45ebea37f258daba74122abc63d0177497396d',
                                                             '6ad79e266a74a78ee423b4e4348fb629979ebdd3'),
 '.lsf-source/glob-13.0.6-lsf-abort-bounds-v1.tar': ('.github/security/actions/attest-source/glob-13.0.6-lsf-abort-bounds-v1.tar',
                                                     1669120,
                                                     'bbd9a629ee2482c26868f7d362ecdc9d177589f0814db03e462dc6c8c82daea8',
                                                     '67245a7054ee97cb43a92091888c5bca862dd730'),
 '.lsf-source/glob-13.0.6.original.tgz': ('.github/security/actions/attest-source/glob-13.0.6.original.tgz',
                                          364690,
                                          '020f184fa9c4e2905cf33c3d1dbba4b25a58e05f6f785f81cc931394e07b8970',
                                          'c29ffb60f49124ce24f3634d513cb25804b1164c'),
 '.lsf-source/minimatch-10.2.5-lsf-bound-v1.repair.json': ('.github/security/actions/setup-python-minimatch/repair.json',
                                                           2129,
                                                           'b340bb0502087bb0df18c8ec276ee61f58aedc6c54fcc6b022d174817d7d27a9',
                                                           '679352aace8de2eb661a5a9665d6152033833cbb'),
 '.lsf-source/minimatch-10.2.5-lsf-bound-v1.tar': ('.github/security/actions/setup-python-minimatch/minimatch-10.2.5.repaired.tar',
                                                   583680,
                                                   '8ed155c4f29d451728efaaf60bc0ed7249ceb93d21eb81171068342621287a68',
                                                   '93a1d4e2d4c2935624af7aa91fe9a113c56e5932'),
 '.lsf-source/minimatch-10.2.5.original.tgz': ('.github/security/actions/setup-python-minimatch/minimatch-10.2.5.original.tgz',
                                               117062,
                                               'a6cea46915bfc6c3fae60f9bd003ea4f9d6a4233aa59a9ca729474d3824ca9e5',
                                               'dd98b4079e660933500de9f03d0bbbab1f44f295'),
 '.lsf-source/minimatch-10.2.6-lsf-bound-v1.repair.json': ('.github/security/actions/download-artifact-source/minimatch-10.2.6-lsf-bound-v1.repair.json',
                                                           2129,
                                                           'd6ede52113aa8cb2d4b6ee008885fd2de0d37e06d822e444846f6f905f088bf3',
                                                           '42886b2bc898bf44b955fc31ff963bb91a94bcc9'),
 '.lsf-source/minimatch-10.2.6-lsf-bound-v1.tar': ('.github/security/actions/download-artifact-source/minimatch-10.2.6-lsf-bound-v1.tar',
                                                   583680,
                                                   'bb2b80a4759baaee01d49528b2d7d0c05fc29c1cf0d3fea41ec243de04bceedb',
                                                   '2a1f40a7420f3cfb13e5284e433b19ec6db1e145'),
 '.lsf-source/minimatch-10.2.6.original.tgz': ('.github/security/actions/download-artifact-source/minimatch-10.2.6.original.tgz',
                                               117068,
                                               '5a3d2c8074a28229665727e47b8a1090941856a7962905efe05d20d3760355f8',
                                               'cc4d199bec4264ab80b9b228da85f074b045edf5'),
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
 '.lsf-source/verify-attest-sources.mjs': ('.github/security/actions/attest-source/verify-attest-sources.mjs',
                                           6005,
                                           '7bda642599031d8ad5ff6d5a02e268376bcc890a98a795715730b4f020532d82',
                                           'c89158269b2411672f3b6876b76f68b4aebbe061')}
RUNTIME = {'dist/50.index.js': {'bytes': 169,
                      'sha256': '45195f12661aeef8aa7ffabfd780d02fffd45c2c37102ff2ecf217a56d6d4f92',
                      'gitBlob': '3fc5a453f0fd544bca59773fe59de2eb00b97a0a'},
 'dist/606.index.js': {'bytes': 7520,
                       'sha256': '629225cc3e937e22ce6b90c21f1d938d1be0716257446593555696bf1d01523e',
                       'gitBlob': 'eaa2ef7f5d8183abab36f475e21def33632d71c7'},
 'dist/index.js': {'bytes': 4931583,
                   'sha256': '0c611191565244227631683833b64bf878751c59b8527c254daceeed43096052',
                   'gitBlob': '1b37a7933fdc645b4f6e51b174a6a257835415a3'},
 'dist/licenses.txt': {'bytes': 2194,
                       'sha256': 'ecaaf3e9799bcf31db16d25584213e1ef190a364d561a82164a5abc5b1327835',
                       'gitBlob': '6cfe240fb47b09b57c3fa74ae6c89befb2c357e3'},
 'dist/package.json': {'bytes': 23,
                       'sha256': '3ca9d4afd21425087cf31893b8f9f63c81b0b8408db5e343ca76e5f8aa26ab9a',
                       'gitBlob': '3dbc1ca591c0557e35b6004aeba250e6a70b56e3'}}
BUILD = ('.github/security/actions/attest-source/fork-build.json', 7937, '318d011735ba0d1232bc973498042ae60510debacf1f3826f467a2cba11e2474', 'd463d383ea9d728f4106206b28b528e7d1c1ca17')
WRAPPER_BUILD = ('.github/security/actions/attest-source/wrapper-build.json', 2194, '82dfad200cd01089bcda8eea00af06709dfb4b4195862f4db9068bea59b9c3d8', 'ce32174a360d0bdb88abb9a82e217eef2471e8d6')
WRAPPER_SNAPSHOT = ('.github/security/actions/attest-build-provenance/action.yml.snapshot', 4126, 'ae5bd5400857c281acf70d75e5870e7ada9a6e70b9e5b423ce5170dde84fa880', '6a1710da5d42339cb793bf5f5a7355cb4183e2ca')

PACKAGES = [{'name': 'deepmerge',
  'version': '4.3.1',
  'targets': ['node_modules/deepmerge'],
  'archive': 'deepmerge-4.3.1-lsf-prototype-v1.tar',
  'archiveIntegrity': 'sha512-w9M3UphEGYK/Zn9kkYnPVw7NnQyxE3T7gIcqBv3m4/Fe+LAhnAPZBwgYCqj0/orv2GagYhPGa2OMjqdzp7G0Lg==',
  'original': 'deepmerge-4.3.1.original.tgz',
  'repair': 'deepmerge-4.3.1-lsf-prototype-v1.repair.json',
  'upstreamIntegrity': 'sha512-3sUqbMEc77XqpdNO7FRyRog+eW3ph+GYCbj+rK+uYyRMuwsVy0rMiVtPn+QJlKFvWP/1PYpapqYn0Me2knFn+A==',
  'dependencies': {},
  'license': 'MIT'},
 {'name': 'glob',
  'version': '10.5.0',
  'targets': ['node_modules/glob'],
  'archive': 'glob-10.5.0-lsf-abort-v1.tar',
  'archiveIntegrity': 'sha512-SzArNq3qcBAyFfzD7TaRc3iPuTYPa0fayiCH6PPVPxoNnfZg28F7MYVAeLzc2vpb83CDKRHGzF1PNwacQ/5rlw==',
  'original': 'glob-10.5.0.original.tgz',
  'repair': 'glob-10.5.0-lsf-abort-v1.repair.json',
  'upstreamIntegrity': 'sha512-DfXN8DfhJ7NH3Oe7cFmu3NCu1wKbkReJ8TorzSAFbSKrlNaQSKfIzqYqVY8zlbs2NLBbWpRiU52GX2PbaBVNkg==',
  'dependencies': {'foreground-child': '^3.1.0',
                   'jackspeak': '^3.1.2',
                   'minimatch': '^9.0.4',
                   'minipass': '^7.1.2',
                   'package-json-from-dist': '^1.0.0',
                   'path-scurry': '^1.11.1'},
  'license': 'ISC'},
 {'name': 'glob',
  'version': '13.0.6',
  'targets': ['node_modules/@jest/reporters/node_modules/glob',
              'node_modules/cacache/node_modules/glob',
              'node_modules/jest-config/node_modules/glob',
              'node_modules/jest-runtime/node_modules/glob'],
  'archive': 'glob-13.0.6-lsf-abort-bounds-v1.tar',
  'archiveIntegrity': 'sha512-rGk3xfwcOFnQ2g00ymEHEXfl682b6++Jf+7CIadJCB97mYipEliX7sHWlIiGUjQ/xHyHRPqowXp6cPG+WVXjRw==',
  'original': 'glob-13.0.6.original.tgz',
  'repair': 'glob-13.0.6-lsf-abort-bounds-v1.repair.json',
  'upstreamIntegrity': 'sha512-Wjlyrolmm8uDpm/ogGyXZXb1Z+Ca2B8NbJwqBVg0axK9GbBeoS7yGV6vjXnYdGm6X53iehEuxxbyiKp8QmN4Vw==',
  'dependencies': {'minimatch': '^10.2.2', 'minipass': '^7.1.3', 'path-scurry': '^2.0.2'},
  'license': 'BlueOak-1.0.0'},
 {'name': 'minimatch',
  'version': '9.0.9',
  'targets': ['node_modules/glob/node_modules/minimatch'],
  'archive': 'minimatch-9.0.9-lsf-bound-v1.tar',
  'archiveIntegrity': 'sha512-j4iUvFvT0Ux5eXy2YbJmDXdDCPqJj1hMURp7VvMtvNXMePifDZusaCRqrBgGDDoC0fDZuU1fydoGEiPYberUiA==',
  'original': 'minimatch-9.0.9.original.tgz',
  'repair': 'minimatch-9.0.9-lsf-bound-v1.repair.json',
  'upstreamIntegrity': 'sha512-OBwBN9AL4dqmETlpS2zasx+vTeWclWzkblfZk7KTA5j3jeOONz/tRCnZomUyvNg83wL5Zv9Ss6HMJXAgL8R2Yg==',
  'dependencies': {'brace-expansion': '^2.0.2'},
  'license': 'ISC'},
 {'name': 'minimatch',
  'version': '10.2.5',
  'targets': ['node_modules/@actions/glob/node_modules/minimatch',
              'node_modules/markdownlint-cli/node_modules/minimatch'],
  'archive': 'minimatch-10.2.5-lsf-bound-v1.tar',
  'archiveIntegrity': 'sha512-HQ5eg+B4Pi8hEcfMgmmFULbhwIq3JWt7ixaNqDV+p8+4fxDUUqlA9VLilGLMmx1qXmeg0HzEabCGgfLIaNOkfw==',
  'original': 'minimatch-10.2.5.original.tgz',
  'repair': 'minimatch-10.2.5-lsf-bound-v1.repair.json',
  'upstreamIntegrity': 'sha512-MULkVLfKGYDFYejP07QOurDLLQpcjk7Fw+7jXS2R2czRQzR56yHRveU5NDJEOviH+hETZKSkIk5c+T23GjFUMg==',
  'dependencies': {'brace-expansion': '^5.0.5'},
  'license': 'BlueOak-1.0.0'},
 {'name': 'minimatch',
  'version': '10.2.6',
  'targets': ['node_modules/@jest/reporters/node_modules/minimatch',
              'node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch',
              'node_modules/cacache/node_modules/minimatch',
              'node_modules/jest-config/node_modules/minimatch',
              'node_modules/jest-runtime/node_modules/minimatch',
              'node_modules/test-exclude/node_modules/minimatch'],
  'archive': 'minimatch-10.2.6-lsf-bound-v1.tar',
  'archiveIntegrity': 'sha512-d4q29f9UKl/jVXZqsE8JNas2oBfjjDeYRQEzYfbPFlEOx3cNnrJzyS48JO1wCCqcRAjOnDnkQfCKcCXFAyuLow==',
  'original': 'minimatch-10.2.6.original.tgz',
  'repair': 'minimatch-10.2.6-lsf-bound-v1.repair.json',
  'upstreamIntegrity': 'sha512-vpLQEs+VLCr1nU0BXS07maYoFwlDAH0gngQuuttxIwutDFEMHq2blX+8vpgxDdK3J1PwjCJiep77OitTZ4Ll1A==',
  'dependencies': {'brace-expansion': '^5.0.8'},
  'license': 'BlueOak-1.0.0'}]

DEEP_ADVISORIES = [{"id": "GHSA-gcqx-w48m-w2h4", "modified": "2026-10-27T21:45:04.256048Z"}]
GLOB_ADVISORIES = [{"id": "GHSA-3g3m-2fjr-6pw4", "modified": "2026-10-30T23:15:04.503965Z"}]
MINI_ADVISORIES = [{"id": "GHSA-g3hv-75wg-m249", "modified": "2026-11-04T17:01:25.850114Z"}]
REPAIR_PROFILES = {
    ("deepmerge", "4.3.1"): "deepmerge-4.3.1-lsf-prototype-v1",
    ("glob", "10.5.0"): "glob-10.5.0-lsf-abort-v1",
    ("glob", "13.0.6"): "glob-13.0.6-lsf-abort-bounds-v1",
    ("minimatch", "9.0.9"): "minimatch-9.0.9-lsf-bound-v1",
    ("minimatch", "10.2.5"): "minimatch-10.2.5-lsf-bounds-v1",
    ("minimatch", "10.2.6"): "minimatch-10.2.6-lsf-bounds-v1",
}


def _read_bound(repo: Path, identity: tuple) -> bytes:
    from tools import security_npm_sources as sources
    snapshot, size, sha256, blob = identity
    raw = read_file(repo, snapshot)
    require(sources.source_identity(raw) == {"bytes": size, "sha256": sha256, "gitBlob": blob},
            "attest-source-input-drift")
    return raw


def source_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    from tools import security_npm_sources as sources, workflow_action_yaml
    require(entry == {"kind": "npm", "path": PREFIX + "package.json", "lock": PREFIX + "package-lock.json",
                      "source_repair": PROFILE}, "unreviewed-attest-profile")
    inputs = {name: _read_bound(repo, identity) for name, identity in ACTION_INPUTS.items()}
    require(decode_json(inputs["package.json"]) == owner and decode_json(inputs["package-lock.json"]) == lock,
            "attest-parsed-input-drift")
    expected = [{"snapshot": snapshot, "source": source, "sha256": sha, "source_sha256": sha}
                for source, (snapshot, _, sha, _) in ACTION_INPUTS.items()]
    actions = decode_json(read_file(repo, ".github/security/actions.json"))["actions"]
    action = actions.get(REFERENCE, {})
    require(action.get("repository") == "KirilsTurkins/lsf-attest"
            and action.get("revision") == REFERENCE.split("@")[1] and action.get("kind") == "npm"
            and isinstance(action.get("files"), list)
            and sorted(action["files"], key=lambda row: row["source"]) == sorted(expected, key=lambda row: row["source"])
            and action.get("metadata") == expected[0], "attest-action-binding-drift")
    wrapper_raw = _read_bound(repo, WRAPPER_SNAPSHOT)
    wrapper = actions.get(WRAPPER_REFERENCE, {})
    wraprow = {"snapshot": WRAPPER_SNAPSHOT[0], "source": "action.yml", "sha256": WRAPPER_SNAPSHOT[2],
               "source_sha256": WRAPPER_SNAPSHOT[2]}
    require(wrapper.get("repository") == "KirilsTurkins/lsf-attest-build-provenance"
            and wrapper.get("revision") == WRAPPER_REFERENCE.split("@")[1] and wrapper.get("kind") == "composite"
            and wrapper.get("files") == [wraprow] and wrapper.get("metadata") == wraprow
            and [row.value for row in workflow_action_yaml.references(wrapper_raw.decode())] == [REFERENCE],
            "attest-wrapper-binding-drift")
    scripts = owner.get("scripts", {})
    guard = "node .lsf-source/verify-attest-sources.mjs"
    require(scripts.get("prepare") == guard + " --runtime-install"
            and scripts.get("prepackage") == guard and scripts.get("pretest") == guard
            and scripts.get("test:security-source") == "node --test .lsf-source/attest-sources.test.mjs"
            and scripts.get("package") == "ncc build src/index.ts --license licenses.txt",
            "attest-build-script-drift")
    manifest = decode_json(inputs[".lsf-source/attest-source-files.json"])
    require(set(manifest) == {"schema", "packages"} and manifest["schema"] == 1
            and isinstance(manifest["packages"], list) and len(manifest["packages"]) == len(PACKAGES),
            "attest-source-inventory-drift")
    require(isinstance(lock.get("packages"), dict) and len(lock["packages"]) == 782,
            "attest-lock-graph-drift")
    for pkg, declared in zip(PACKAGES, manifest["packages"], strict=True):
        require(all(declared.get(key) == pkg[key] for key in ("name", "version", "targets", "archive", "archiveIntegrity", "original", "repair"))
                and set(declared) == {"name", "version", "targets", "archive", "archiveSha256", "archiveIntegrity",
                                      "original", "originalSha256", "repair", "repairSha256", "files"},
                "attest-source-inventory-drift")
        for key, field in (("archive", "archiveSha256"), ("original", "originalSha256"), ("repair", "repairSha256")):
            require(digest(inputs[".lsf-source/" + pkg[key]]) == declared[field], "attest-source-asset-drift")
        require(sources.integrity(inputs[".lsf-source/" + pkg["archive"]]) == pkg["archiveIntegrity"],
                "attest-source-archive-drift")
        targets = [path for path, row in lock["packages"].items()
                   if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == pkg["name"]
                   and row.get("version") == pkg["version"]]
        require(targets == pkg["targets"], "attest-source-duplicate-or-alias")
        for path in targets:
            node = lock["packages"][path]
            require(not node.get("link") and node.get("resolved") == "file:.lsf-source/" + pkg["archive"]
                    and node.get("integrity") == pkg["archiveIntegrity"], "attest-source-lock-drift")
    build = decode_json(_read_bound(repo, BUILD))
    wrapper_build = decode_json(_read_bound(repo, WRAPPER_BUILD))
    payloads = {source: {"bytes": size, "sha256": sha, "gitBlob": blob}
                for source, (_, size, sha, blob) in ACTION_INPUTS.items()} | RUNTIME
    artifact = build["artifact"]
    require(build["repository"] == "KirilsTurkins/lsf-attest" and build["publishedRevision"] == REFERENCE.split("@")[1]
            and build["publishedTree"] == build["sourceTree"] == TREE
            and build["sourceHead"] == "a14b919576ae22963f0579cb8e9710b8a254448b"
            and build["diagnosticHead"] == "38b14e5cec672163c08cb54d0babd959cf7f2e7c"
            and build["diagnosticTree"] == "e3591e48386129bb425728e5a87e112ba51755d0"
            and build["diagnosticOnlyPath"] == ".github/workflows/lsf-attest-security-owner.yml"
            and build["diagnosticWorkflowSha256"] == "8a215d0a5fc0c2fe4892b049080d04cc1810ac1d018466166ae37764069ccacc"
            and build["run"] == 42118781914 and build["job"] == 127565340178 and build["jobConclusion"] == "success"
            and build["node"] == "24.19.0" and build["npm"] == "11.17.0"
            and build["fullCopies"] == 15 and build["productionCopies"] == 5 and build["securityTests"] == 5
            and build["jestSuites"] == 11 and build["jestTests"] == 237 and build["rebuiltDistExact"] is True
            and artifact["id"] == 13456948362 and artifact["bytes"] == 3149943
            and artifact["sha256"] == "1cdf87a2c45bd16410561c3a1db56d6b8fc469eaa05dd036ade6fc2841d9fcee"
            and artifact["members"] == 43 and artifact["checksums"] == 42 and artifact["crcVerified"] is True
            and artifact["payloads"] == payloads, "attest-build-evidence-drift")
    wat = wrapper_build["artifact"]
    require(wrapper_build["repository"] == "KirilsTurkins/lsf-attest-build-provenance"
            and wrapper_build["publishedRevision"] == WRAPPER_REFERENCE.split("@")[1]
            and wrapper_build["publishedTree"] == wrapper_build["sourceTree"] == WRAPPER_TREE
            and wrapper_build["sourceHead"] == "b01d99f97fc67eb9a250c06f57087cb1c967e777"
            and wrapper_build["diagnosticHead"] == "06a4fa4fccee622ae683d6307f0c035a13fcd962"
            and wrapper_build["diagnosticTree"] == "a582960579075d21c384edb07919318feb712eac"
            and wrapper_build["workflowSha256"] == "0155d28e0fee9e0744fcf3a904a51b86a4b887e8c2ed899079ae20431afa0203"
            and wrapper_build["run"] == 42119738981 and wrapper_build["job"] == 127568652788
            and wrapper_build["jobConclusion"] == "success" and wrapper_build["childHead"] == REFERENCE.split("@")[1]
            and wrapper_build["childTree"] == TREE and wrapper_build["exactSingleReplacement"] is True
            and wrapper_build["wrapperBeforeSha256"] == "7162930617686fed2e72fb90c8ac795abd4a13d8481e59b01524ab0a8c033261"
            and wrapper_build["wrapperAfterSha256"] == WRAPPER_SNAPSHOT[2]
            and wrapper_build["childDist"] == {name.removeprefix("dist/"): identity for name, identity in RUNTIME.items()}
            and wat == {"id": 13458225631, "bytes": 1355788,
                        "sha256": "dbc8e0d0ffee235da9d65c67fa8ce8d140668c90bfcf41c19cbbee4e35c5b752",
                        "members": 11, "checksums": 10, "crcVerified": True}, "attest-wrapper-build-evidence-drift")
    return {"inputs": inputs, "manifest": manifest}


def libraries(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    source_inputs(repo, entry, owner, lock)
    result = {}
    for pkg in PACKAGES:
        result.setdefault(pkg["name"], []).append({"version": pkg["version"], "resolved": "file:.lsf-source/" + pkg["archive"],
                                                    "integrity": pkg["archiveIntegrity"]})
    return result


def _reconstruct(original: dict, repair: dict, pin: dict) -> dict:
    import re
    name, version = pin["name"], pin["version"]
    require(set(repair) == {"schema", "profile", "name", "version", "upstreamIntegrity", "files"}
            and repair["schema"] == 1 and repair["profile"] == REPAIR_PROFILES[(name, version)]
            and repair["name"] == name and repair["version"] == version and repair["upstreamIntegrity"] == pin["integrity"]
            and isinstance(repair["files"], list), "attest-repair-document-drift")
    if name == "deepmerge":
        expected = {"index.js", "dist/cjs.js", "dist/umd.js"}
    elif name == "minimatch":
        expected = {"dist/commonjs/index.js", "dist/esm/index.js"}
    else:
        expected = {"dist/commonjs/walker.js", "dist/esm/walker.js"}
        if version == "13.0.6":
            expected |= {"dist/commonjs/index.min.js", "dist/esm/index.min.js"}
    rows = repair["files"]
    require(len(rows) == len(expected) and {row["path"] for row in rows} == expected, "attest-repair-file-coverage")
    output = original.copy()
    for row in rows:
        require(set(row) == {"path", "beforeSha256", "afterSha256", "edits"}
                and all(isinstance(row[field], str) and re.fullmatch(r"[0-9a-f]{64}", row[field])
                        for field in ("beforeSha256", "afterSha256")), "attest-repair-file-identity")
        key = "package/" + row["path"]
        raw, mode = original[key]
        require(digest(raw) == row["beforeSha256"], "attest-repair-preimage-drift")
        edits = row["edits"]
        require(isinstance(edits, list) and 0 < len(edits) <= 8, "attest-repair-edit-bound")
        value = raw.decode("utf8")
        for edit in edits:
            require(set(edit) == {"before", "after", "count"}
                    and all(isinstance(edit[field], str) and 0 < len(edit[field]) <= 8192 for field in ("before", "after"))
                    and edit["before"] != edit["after"] and type(edit["count"]) is int and 0 < edit["count"] <= 4
                    and value.count(edit["before"]) == edit["count"], "attest-repair-edit-drift")
            value = value.replace(edit["before"], edit["after"])
        raw = value.encode("utf8")
        require(digest(raw) == row["afterSha256"], "attest-repair-postimage-drift")
        output[key] = raw, mode
    return output


def verify_sources(repo: Path, packages: list, configuration: dict, fetch, fetch_runtime) -> list[dict]:
    from tools import security_npm_sources as sources
    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("source_repair") != PROFILE or not any(item.path == entry["lock"] for item in packages):
            continue
        owner, lock = (decode_json(read_file(repo, entry[key])) for key in ("path", "lock"))
        selected = source_inputs(repo, entry, owner, lock)
        inputs = selected["inputs"]
        for path, identity in RUNTIME.items():
            require(sources.source_identity(fetch_runtime(REFERENCE, path)) == identity, "attest-runtime-drift")
        for pkg, declared in zip(PACKAGES, selected["manifest"]["packages"], strict=True):
            pin = {"name": pkg["name"], "version": pkg["version"], "integrity": pkg["upstreamIntegrity"]}
            upstream = fetch(pin)
            require(upstream == inputs[".lsf-source/" + pkg["original"]] and sources.integrity(upstream) == pin["integrity"],
                    "attest-source-upstream-drift")
            original = sources.members(upstream)
            manifest = sources.manifest(original, pkg["name"], pkg["version"], pkg["dependencies"])
            require(manifest.get("license") == pkg["license"], "attest-source-package-drift")
            repair_raw = inputs[".lsf-source/" + pkg["repair"]]
            repair = decode_json(repair_raw)
            fixed = _reconstruct(original, repair, pin)
            require(sources.distribution(fixed) == inputs[".lsf-source/" + pkg["archive"]]
                    and {name.removeprefix("package/"): digest(raw) for name, (raw, _) in fixed.items()} == declared["files"],
                    "attest-source-reconstruction-drift")
            advisories = DEEP_ADVISORIES if pkg["name"] == "deepmerge" else GLOB_ADVISORIES if pkg["name"] == "glob" else MINI_ADVISORIES
            receipts.append({"name": pkg["name"], "version": pkg["version"], "profile": PROFILE,
                             "upstream_integrity": pin["integrity"], "derived_integrity": pkg["archiveIntegrity"],
                             "repair_sha256": digest(repair_raw), "files": len(repair["files"]),
                             "locks": [entry["lock"]], "advisories": advisories, "action": REFERENCE,
                             "source_role": "development-build-tool" if pkg["name"] == "deepmerge" else "action-runtime-and-build",
                             "built_tree": TREE, "build_run": 42118781914})
    return receipts
