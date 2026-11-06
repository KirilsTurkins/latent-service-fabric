"""Exact source and hosted-build receipts for the setup-dotnet minimatch repair.

The scanner reconstructs source as data; the published action retains upstream
package versions and only the exact reviewed advisory revision is credited.
"""
from __future__ import annotations

from pathlib import Path

from tools.security_common import decode_json, digest, read_file, require

PROFILE = 'setup-dotnet-minimatch-action-source-v1'
PREFIX = ".github/security/actions/setup-dotnet/"
REFERENCE = 'KirilsTurkins/lsf-setup-dotnet@258c927924210be905f8908a4be714e5d0daffa8'
ASSETS = {'upstream': {'snapshot': '.github/security/actions/setup-python-minimatch/minimatch-10.2.5.original.tgz',
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
 'tests': {'snapshot': '.github/security/actions/setup-dotnet-minimatch/bounds.test.mjs.snapshot',
           'source': '.lsf-source/minimatch-bounds.test.mjs',
           'bytes': 2854,
           'sha256': 'f65c9af8d0d6b2abfd728d803e223396e746850f564003e93b223c4f084f987b',
           'gitBlob': '9601c04f3210fa02ee4ae91183f2a5538b1e9374'},
 'build': {'snapshot': '.github/security/actions/setup-dotnet-minimatch/fork-build.json',
           'source': 'https://github.com/KirilsTurkins/lsf-setup-dotnet/actions/runs/42023417095',
           'bytes': 3230,
           'sha256': 'a12054c6c2f0b82ec4a7885b26a4941e507ec3363608f709f837c91aefd1498d',
           'gitBlob': '491f1fc1d0633ff047a93d129ee431fc4a5d225e'}}
RUNTIME = {'runtime_setup': {'source': 'dist/setup/index.js',
                   'bytes': 3862594,
                   'sha256': 'fbaaffdb229027601428143fb31a41faf4f1ff8b8d88fb8fe84e39d7cb20dbaf',
                   'gitBlob': 'b8ff05db0b6bd4e8c82d9e297f5d867befbf8220'},
 'runtime_cache': {'source': 'dist/cache-save/index.js',
                   'bytes': 3428734,
                   'sha256': '483385c7bdfa8fd34f7b5b46f465a7f742b43256dfa3f823f124d9ea90a91aa5',
                   'gitBlob': '5cf7135233a3da7bc5cbc9fa013dc4897272f259'}}
SOURCE_SHA256 = {'action.yml': 'c96dc8e11d5e6f64fb48a3221e7b1446821955cdcbecb1bf5697c93e24d4f9f2',
 'package.json': '9be7cb32ee3db4f5b122552fa8522c6ec0802236667094205806f5eabe92d732',
 'package-lock.json': 'f30f154929ab439bd594caad80f151a3b06e480a795c90c9c2513cd2e6d19d6a',
 '.lsf-source/verify-installed-deepmerge.mjs': '55367db845fb579dd45a1a16924bf017c0ddc8f84162d833e368c24a7d629cf7',
 '.lsf-source/verify-installed-minimatch.mjs': '4fcbcba0f46fed80b09c6cdb1a2a54eeff2e0a3690b4d0a5b566762169f1f826',
 '.lsf-source/minimatch-bounds.test.mjs': 'f65c9af8d0d6b2abfd728d803e223396e746850f564003e93b223c4f084f987b'}
ARTIFACT_PAYLOADS = {'bundle-sha256.txt': {'bytes': 177,
                       'sha256': 'd55afeb366c4fea6314b47a19365fe7158e5a1e0494cb621668a9f347449c6ca'},
 'dist-actual.txt': {'bytes': 98,
                     'sha256': '0630ff46bfeccc9ed40b1dd2e67cf7514e9a16feb8d3f2448b6baa91149b27f1'},
 'dist-expected.txt': {'bytes': 98,
                       'sha256': '0630ff46bfeccc9ed40b1dd2e67cf7514e9a16feb8d3f2448b6baa91149b27f1'},
 'jest.json': {'bytes': 237204, 'sha256': '08b8d36f0c39cd491b93c6c017c1e1ff859c7ec34046d73c106c15a598626d51'},
 'npm-ls.txt': {'bytes': 47198, 'sha256': '3abd8c3ab27b2f0163cee14821f5dd81cd799dc9da3402736f9d06b885ed7b46'},
 'reconstruction.json': {'bytes': 632,
                         'sha256': 'ec5d869d9e91334c3f969ab3cb8e6f418f41ab9d76ec3f79939896b098dd9191'},
 'tamper.json': {'bytes': 1993, 'sha256': 'd21d916f015786a516a7b504c2829cbf511b0ed134b5976cb549d1467eb9b4d7'}}

def action_inputs(repo: Path, entry: dict, owner: dict, lock: dict) -> dict:
    """Recognize only the fixed setup-dotnet lock, assets and build commands."""
    from tools import security_npm_sources as sources

    require(entry.get("minimatch_source_repair") == PROFILE
            and entry.get("source_repair") == sources.ACTION_PROFILE
            and entry.get("path") == PREFIX + "package.json"
            and entry.get("lock") == PREFIX + "package-lock.json",
            "unreviewed-minimatch-action-profile")
    policy = decode_json(read_file(sources.POLICY, "minimatch-dotnet-action-source-repairs.json"))
    require(set(policy) == {"schema", "profile", "action", "advisories", "assets", "runtime"}
            and policy["schema"] == 1 and policy["profile"] == PROFILE
            and policy["action"] == REFERENCE and policy["advisories"] == sources.MINIMATCH_ADVISORIES
            and policy["assets"] == ASSETS and policy["runtime"] == RUNTIME,
            "invalid-dotnet-minimatch-action-policy")
    material = {}
    for name, row in ASSETS.items():
        raw = read_file(repo, row["snapshot"])
        require(sources.source_identity(raw) == {key: row[key] for key in ("bytes", "sha256", "gitBlob")},
                "dotnet-minimatch-action-asset-drift")
        material[name] = raw
    require(sources.integrity(material["upstream"]) == sources.MINIMATCH_UPSTREAM
            and sources.integrity(material["archive"]) == sources.MINIMATCH_DERIVED,
            "dotnet-minimatch-action-integrity-drift")
    action = decode_json(read_file(repo, ".github/security/actions.json"))["actions"].get(REFERENCE, {})
    rows = action.get("files", [])
    files = {row.get("source"): row for row in rows}
    require(len(rows) == len(files) and set(files) == set(SOURCE_SHA256),
            "dotnet-minimatch-action-binding-drift")
    for name in ("verifier", "tests"):
        binding = ASSETS[name]
        require(files.get(binding["source"]) == {
                    "snapshot": binding["snapshot"], "source": binding["source"],
                    "sha256": binding["sha256"], "source_sha256": binding["sha256"]},
                "dotnet-minimatch-action-binding-drift")
    require(action.get("metadata", {}).get("sha256") == SOURCE_SHA256["action.yml"],
            "dotnet-minimatch-action-entrypoint-drift")
    commands = owner.get("scripts", {})
    verifiers = ("node .lsf-source/verify-installed-deepmerge.mjs && "
                 "node .lsf-source/verify-installed-minimatch.mjs && ")
    require(commands.get("build") == verifiers + "ncc build -o dist/setup src/setup-dotnet.ts && ncc build -o dist/cache-save src/cache-save.ts"
            and commands.get("test") == verifiers + "node --experimental-vm-modules ./node_modules/jest/bin/jest.js --coverage"
            and commands.get("test:security-source") == "node --test .lsf-source/minimatch-bounds.test.mjs",
            "dotnet-minimatch-action-build-contract-drift")
    matches = [(path, row) for path, row in lock["packages"].items()
               if (row.get("name") or path.rsplit("node_modules/", 1)[-1]) == "minimatch"
               and str(row.get("version", "")).startswith("10.")]
    glob = lock["packages"].get("node_modules/@actions/glob", {})
    require(owner.get("devDependencies", {}).get("minimatch") == sources.MINIMATCH_ARCHIVE
            and owner.get("overrides", {}).get("minimatch@10") == "$minimatch"
            and owner.get("overrides", {}).get("glob@10") == "14.0.2"
            and lock["packages"][""].get("devDependencies", {}).get("minimatch") == sources.MINIMATCH_ARCHIVE
            and len(matches) == 1 and matches[0][0] == "node_modules/minimatch"
            and matches[0][1].get("version") == "10.2.5"
            and matches[0][1].get("resolved") == sources.MINIMATCH_ARCHIVE
            and matches[0][1].get("integrity") == sources.MINIMATCH_DERIVED
            and not matches[0][1].get("dev", False)
            and glob.get("version") == "0.7.0" and not glob.get("dev", False)
            and glob.get("dependencies", {}).get("minimatch") == "^10.2.5"
            and lock["packages"].get("node_modules/glob", {}).get("version") == "14.0.2"
            and lock["packages"]["node_modules/glob"].get("dev") is True,
            "unlocked-dotnet-minimatch-action-source-graph")
    return {"policy": policy, "material": material, "reference": REFERENCE}


def verify_sources(repo: Path, packages: list, configuration: dict, fetch, fetch_runtime=None) -> list[dict]:
    """Independently reconstruct the fixed bytes and bind both published bundles."""
    from tools import security_npm_sources as sources

    receipts = []
    for entry in configuration["manifests"]:
        if entry.get("minimatch_source_repair") != PROFILE or not any(item.path == entry["lock"] for item in packages):
            continue
        owner = decode_json(read_file(repo, entry["path"]))
        lock = decode_json(read_file(repo, entry["lock"]))
        deepmerge = sources.action_source_inputs(repo, entry, owner, lock)
        require(deepmerge is not None, "minimatch-action-base-source-missing")
        selected = action_inputs(repo, entry, owner, lock)
        material = selected["material"]
        for runtime in RUNTIME.values():
            raw = (fetch_runtime or sources.action_runtime)(REFERENCE, runtime["source"])
            require(sources.source_identity(raw) == {key: runtime[key] for key in ("bytes", "sha256", "gitBlob")},
                    "dotnet-minimatch-action-runtime-drift")
        pin = {"name": "minimatch", "version": "10.2.5", "integrity": sources.MINIMATCH_UPSTREAM}
        upstream = fetch(pin)
        require(upstream == material["upstream"] and sources.integrity(upstream) == sources.MINIMATCH_UPSTREAM,
                "dotnet-minimatch-action-upstream-drift")
        original = sources.members(upstream)
        value = sources.manifest(original, "minimatch", "10.2.5", {"brace-expansion": "^5.0.5"})
        require(value.get("license") == "BlueOak-1.0.0"
                and digest(original["package/package.json"][0]) == "4b3a08a7ad20dead8bbe4b4fe97a2746bded7c51d218ef3034eb4e330ad31f08"
                and digest(original["package/LICENSE.md"][0]) == "2c7c5d22ed5a8ee968c64757710979afcd77438c48b4a265b94e615babd8a901",
                "dotnet-minimatch-action-package-identity-drift")
        repair = decode_json(material["repair"])
        require(repair.get("profile") == "minimatch-10.2.5-lsf-bounds-v1",
                "dotnet-minimatch-action-repair-profile")
        repaired = sources.source_repair(original, repair, pin)
        require(sources.distribution(repaired) == material["archive"]
                and sources.integrity(material["archive"]) == sources.MINIMATCH_DERIVED,
                "dotnet-minimatch-action-reconstruction-drift")
        build = decode_json(material["build"])
        artifact = build["artifact"]
        installed = build["installedMinimatch"]
        deep_installed = build["installedDeepmerge"]
        deep_repair = decode_json(deepmerge["material"]["repair"])
        bundle_sums = "".join(f"{row['sha256']}  {row['source']}\n" for row in RUNTIME.values()).encode()
        require(artifact["payloads"].get("bundle-sha256.txt")
                == {"bytes": len(bundle_sums), "sha256": digest(bundle_sums)},
                "dotnet-minimatch-action-bundle-receipt-drift")
        require(build["schema"] == 1 and build["repository"] == "KirilsTurkins/lsf-setup-dotnet"
                and build["publishedRevision"] == REFERENCE.split("@")[1]
                and build["publishedTree"] == build["sourceTree"] == "95a225c1d0707ebd764371b3d2a470bd5ac1271a"
                and build["sourceHead"] == "b5df2c787220be374497e1fbbee09ac583849c80"
                and build["diagnosticHead"] == installed["sourceCommit"] == deep_installed["sourceCommit"]
                    == "02dfed81f2103cf05fd7fecac38141f3813dff97"
                and build["diagnosticTree"] == "1d6dff64b8b80a025524c957c7ee9e667eaf634d"
                and build["diagnosticOnlyPath"] == ".github/workflows/setup-dotnet-security-linux-owner.yml"
                and build["diagnosticWorkflowBlob"] == "2a37150f4cb8f605b3e9548a53f2406b8d41ebc0"
                and build["run"] == 42023417095 and build["job"] == 127231597179
                and build["jobConclusion"] == "success" and build["node"] == installed["node"]
                    == deep_installed["node"] == "24.19.0"
                and build["npm"] == "11.17.0" and build["jestSuites"] == 9 and build["jestTests"] == 242
                and build["focusedTests"] == 2 and build["tamperChecks"] == 15
                and build["jobLogSha256"] == "00dfe776f105229ae41f63b7bbed2ed84b0eb1f781233dc0f1c785c4bbb568a7"
                and artifact["id"] == 13411749303 and artifact["bytes"] == 33194
                and artifact["sha256"] == "5eb17cdd8964f58e84f8793c575b9c8d623bac66a32deeda14b5798de3a7ee56"
                and artifact["members"] == 7 and artifact["crcVerified"] is True
                and artifact["payloads"] == ARTIFACT_PAYLOADS
                and installed["kind"] == "installed-minimatch-source-assertion"
                and installed["version"] == "10.2.5" and installed["repairSha256"] == digest(material["repair"])
                and installed["installedPostimages"] == {row["path"]: row["afterSha256"] for row in repair["files"]}
                and deep_installed["kind"] == "installed-source-assertion"
                and deep_installed["packageVersion"] == "4.3.1"
                and deep_installed["repairSha256"] == digest(deepmerge["material"]["repair"])
                and deep_installed["installedPostimages"] == {row["path"]: row["afterSha256"] for row in deep_repair["files"]},
                "dotnet-minimatch-action-build-evidence-drift")
        receipts.append({"name": pin["name"], "version": pin["version"], "profile": PROFILE,
                         "upstream_integrity": sources.MINIMATCH_UPSTREAM,
                         "derived_integrity": sources.MINIMATCH_DERIVED,
                         "repair_sha256": digest(material["repair"]), "files": len(repair["files"]),
                         "locks": [entry["lock"]], "advisories": sources.MINIMATCH_ADVISORIES,
                         "action": REFERENCE, "source_role": "action-runtime-and-build",
                         "built_tree": build["publishedTree"], "build_run": build["run"]})
    return receipts
