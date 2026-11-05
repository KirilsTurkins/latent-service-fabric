"""Adversarial fixtures for independent, data-only npm source verification."""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import security_npm_sources as sources
from tools.security_common import POLICY, ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages


def tarball(files: dict, *, linked: str = "") -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:") as archive:
        for name, (raw, mode) in files.items():
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(raw), mode
            archive.addfile(item, io.BytesIO(raw))
        if linked:
            item = tarfile.TarInfo(linked)
            item.type, item.linkname = tarfile.SYMTYPE, "/outside"
            archive.addfile(item)
    return gzip.compress(output.getvalue(), mtime=0)


class NpmSourceRepairTests(unittest.TestCase):
    def repair_fixture(self, name="braces"):
        version, profile, names, dependencies = {
            "braces": ("3.0.3", "braces-3.0.3-lsf-depth-v1",
                ["lib/utils.js", "lib/compile.js", "lib/expand.js", "lib/stringify.js", "lib/parse.js"],
                {"fill-range": "^7.1.1"}),
            "http-cache-semantics": ("4.3.0", "http-cache-semantics-4.3.0-lsf-cache-v1", ["index.js"], {}),
            "deepmerge": ("4.3.1", "deepmerge-4.3.1-lsf-prototype-v1", ["index.js", "dist/cjs.js", "dist/umd.js"], {})
        }[name]
        files = {"package/package.json": (json.dumps({"name": name, "version": version,
                  "dependencies": dependencies, "license": "MIT"}).encode(), 0o644),
                 "package/LICENSE": (b"original license retained", 0o644),
                 "package/unchanged.js": (b"normal compatibility surface", 0o755)}
        files.update({"package/" + path: (b"before exact source\n", 0o644) for path in names})
        pin = {"name": name, "version": version, "integrity": sources.integrity(tarball(files))}
        repair = {"schema": 1, "profile": profile, "name": name, "version": version,
                  "upstreamIntegrity": pin["integrity"], "files": [
                      {"path": path, "beforeSha256": hashlib.sha256(b"before exact source\n").hexdigest(),
                       "afterSha256": hashlib.sha256(b"after bounded source\n").hexdigest(),
                       "edits": [{"before": "before exact source", "after": "after bounded source", "count": 1}]}
                      for path in names]}
        return files, pin, repair

    def test_repair_preserves_identity_graph_license_unchanged_bytes_and_modes(self):
        for name in ("braces", "http-cache-semantics", "deepmerge"):
            with self.subTest(name=name):
                files, pin, repair = self.repair_fixture(name)
                fixed = sources.source_repair(files, repair, pin)
                self.assertEqual(set(fixed), set(files))
                for name in ("package/package.json", "package/LICENSE", "package/unchanged.js"):
                    self.assertEqual(fixed[name], files[name])
                self.assertEqual(json.loads(fixed["package/package.json"][0])["version"], repair["version"])
                for row in repair["files"]:
                    self.assertEqual(fixed["package/" + row["path"]], (b"after bounded source\n", 0o644))

    def test_repair_rejects_missing_walkers_preimage_postimage_edit_and_upstream_drift(self):
        for name in ("braces", "http-cache-semantics", "deepmerge"):
            with self.subTest(name=name):
                files, pin, repair = self.repair_fixture(name)
                changes = [lambda value: value["files"].pop(),
                           lambda value: value["files"][0].update(beforeSha256="0" * 64),
                           lambda value: value["files"][0].update(afterSha256="0" * 64),
                           lambda value: value["files"][0]["edits"][0].update(count=2),
                           lambda value: value.update(upstreamIntegrity="untrusted")]
                for index, change in enumerate(changes):
                    altered = copy.deepcopy(repair)
                    change(altered)
                    with self.subTest(index=index), self.assertRaises(SecurityError):
                        sources.source_repair(files, altered, pin)

    def test_archive_paths_links_duplicate_members_and_hidden_graphs_fail(self):
        for name in ("package/../escape", "/package/absolute", "package/a\\b", "./package/a"):
            with self.subTest(name=name), self.assertRaises(SecurityError):
                sources.members(tarball({name: (b"x", 0o644)}))
        with self.assertRaises(SecurityError):
            sources.members(tarball({"package/a": (b"x", 0o644)}, linked="package/link"))
        with self.assertRaises(SecurityError):
            sources.members(tarball({"package/a": (b"x", 0o644)}, linked="package/a"))
        files, pin, _ = self.repair_fixture()
        for path in ("package/node_modules/shadow/index.js", "package/npm-shrinkwrap.json"):
            altered = {**files, path: (b"{}", 0o644)}
            with self.subTest(path=path), self.assertRaises(SecurityError):
                sources.manifest(altered, pin["name"], pin["version"], {"fill-range": "^7.1.1"})

    def test_only_exact_advisory_revision_verified_version_and_lock_are_remediated(self):
        known = finding("osv", "GHSA-vfj7-8cjw-p6xm", "website/package-lock.json", "npm:braces@3.0.3")
        other = finding("osv", "GHSA-fixture-future", known.path, known.package)
        wrong_version = finding("osv", known.finding, known.path, "npm:braces@3.0.2")
        wrong_path = finding("osv", known.finding, "other/package-lock.json", known.package)
        receipt = {"name": "braces", "version": "3.0.3", "locks": [known.path],
                   "advisories": [{"id": known.finding, "modified": "exact-reviewed-revision"}]}
        observation = [{"advisories": [{"package": Package("npm", "braces", "3.0.3", known.path).public(),
                                       "id": known.finding, "modified": "exact-reviewed-revision"}]}]
        remaining, fixed = sources.resolve_findings([known, other, wrong_version, wrong_path], observation, [receipt])
        self.assertEqual(fixed, [known])
        self.assertEqual(remaining, [other, wrong_version, wrong_path])
        observation[0]["advisories"][0]["modified"] = "changed-advisory"
        self.assertEqual(sources.resolve_findings([known], observation, [receipt]), ([known], []))
        self.assertEqual(sources.resolve_findings([known], observation, []), ([known], []))

        deepmerge = finding("osv", "GHSA-gcqx-w48m-w2h4", "website/package-lock.json", "npm:deepmerge@4.3.1")
        action = finding("osv", deepmerge.finding, ".github/security/actions/checkout/package-lock.json", deepmerge.package)
        revision = "2026-10-27T21:45:04.256048Z"
        receipt = {"name": "deepmerge", "version": "4.3.1", "locks": [deepmerge.path],
            "advisories": [{"id": deepmerge.finding, "modified": revision}]}
        observation = [{"advisories": [{"package": Package("npm", "deepmerge", "4.3.1", deepmerge.path).public(),
            "id": deepmerge.finding, "modified": revision}]}]
        self.assertEqual(sources.resolve_findings([deepmerge, action], observation, [receipt]), ([action], [deepmerge]))
        observation[0]["advisories"][0]["modified"] = "changed-revision"
        self.assertEqual(sources.resolve_findings([deepmerge, action], observation, [receipt]), ([deepmerge, action], []))

    def test_library_allowance_does_not_admit_aliases_or_changed_versions_and_integrities(self):
        configuration = json.loads(read_file(POLICY, "inventory.json"))
        original = next(entry for entry in configuration["manifests"] if entry["path"] == "website/package.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in (original["path"], original["lock"], "website/toolchain/source.json", "website/toolchain/prepare.py"):
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(read_file(ROOT, path).replace(b"\r\n", b"\n"))
            packages = npm_packages(root, original)
            self.assertEqual(len(packages), 1454)
            lock = json.loads(read_file(root, original["lock"]))
            for change in ("alias", "version", "integrity"):
                entry, changed = copy.deepcopy(original), copy.deepcopy(lock)
                row = changed["packages"]["node_modules/braces"]
                if change == "alias":
                    changed["packages"]["node_modules/unapproved"] = {**row, "name": "braces"}
                else:
                    row[change] = "0.0.0" if change == "version" else "untrusted"
                raw = (json.dumps(changed) + "\n").encode()
                (root / entry["lock"]).write_bytes(raw)
                entry["derived_libraries"]["lock_sha256"] = sources.digest(raw)
                with self.subTest(change=change), self.assertRaises(SecurityError):
                    npm_packages(root, entry)

    def verification_fixture(self, root: Path):
        raw_inputs, material, repairs, policy = {}, {}, [], {}
        patches = []
        for name, old, version, dependencies in [
                ("ip-address", "10.5.0", "10.7.2", {}), ("undici", "6.28.0", "6.28.1", {}),
                ("brace-expansion", "5.0.9", "5.0.12", {"balanced-match": "^4.0.2"}),
                ("postcss-selector-parser", "7.1.4", "7.1.6", {"cssesc": "^3.0.0", "util-deprecate": "^1.0.2"})]:
            files = {"package/package.json": (json.dumps({"name": name, "version": version,
                     "dependencies": dependencies}).encode(), 0o644)}
            raw = tarball(files)
            pin = {"name": name, "from": old, "version": version, "integrity": sources.integrity(raw)}
            patches.append(pin)
            material[name], raw_inputs[name] = files, raw
        libraries = []
        for name in ("braces", "http-cache-semantics", "deepmerge"):
            files, pin, repair = self.repair_fixture(name)
            raw_inputs[name] = tarball(files)
            material[name] = sources.source_repair(files, repair, pin)
            encoded = (json.dumps(repair) + "\n").encode()
            path = root / "website/toolchain/repairs" / (name + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encoded)
            repairs.append({"path": "repairs/" + name + ".json", "sha256": sources.digest(encoded)})
            policy[name] = {"version": pin["version"], "profile": repair["profile"],
                            "repair_sha256": sources.digest(encoded),
                            "integrity": sources.integrity(sources.distribution(material[name])), "advisories": []}
            (patches if name == "http-cache-semantics" else libraries).append(
                {**pin, "from": "4.2.0"} if name == "http-cache-semantics" else pin)
        base_files = {"package/package.json": (b'{"name":"npm","version":"11.19.1"}', 0o644),
                      "package/node_modules/balanced-match/package.json": (b'{"name":"balanced-match","version":"4.0.4"}', 0o644),
                      "package/node_modules/cssesc/package.json": (b'{"name":"cssesc","version":"3.0.0"}', 0o644),
                      "package/node_modules/util-deprecate/package.json": (b'{"name":"util-deprecate","version":"1.0.2"}', 0o644)}
        base_files["package/node_modules/glob/package.json"] = (json.dumps({"name": "glob", "version": "13.0.6",
            "dependencies": {"minimatch": "^10.2.2", "minipass": "^7.1.3", "path-scurry": "^2.0.2"}}).encode(), 0o644)
        base_files["package/node_modules/minimatch/package.json"] = (json.dumps({"name": "minimatch", "version": "10.2.5",
            "dependencies": {"brace-expansion": "^5.0.5"}}).encode(), 0o644)
        base_files.update({"package/" + path: (b"fixture original bytes", 0o644) for path in sources.BUNDLE_REPAIR_FILES})
        derived = base_files.copy()
        for pin in patches:
            prefix = "package/node_modules/" + pin["name"] + "/"
            old = {"name": pin["name"], "version": pin["from"]}
            if pin["name"] == "brace-expansion":
                old["dependencies"] = {"balanced-match": "^4.0.2"}
            if pin["name"] == "postcss-selector-parser":
                old["dependencies"] = {"cssesc": "^3.0.0", "util-deprecate": "^1.0.2"}
            base_files[prefix + "package.json"] = json.dumps(old).encode(), 0o644
            derived.update({prefix + name.removeprefix("package/"): value for name, value in material[pin["name"]].items()})
        raw_inputs["npm"] = tarball(base_files)
        base_pin = {"name": "npm", "version": "11.19.1", "integrity": sources.integrity(raw_inputs["npm"])}
        bundle_repair = {"schema": 1, "profile": "npm-11.19.1-lsf-glob-minimatch-source-v1",
            "name": "npm", "version": "11.19.1", "upstreamIntegrity": base_pin["integrity"],
            "files": [{"path": path, "beforeSha256": sources.digest(b"fixture original bytes"),
                       "afterSha256": sources.digest(b"fixture repaired bytes"),
                       "edits": [{"before": "fixture original bytes", "after": "fixture repaired bytes", "count": 1}]}
                      for path in sorted(sources.BUNDLE_REPAIR_FILES)]}
        encoded_bundle = (json.dumps(bundle_repair) + "\n").encode()
        (root / "website/toolchain/repairs/npm-glob-minimatch.json").write_bytes(encoded_bundle)
        derived = sources.bundle_source_repair(derived, bundle_repair, base_pin)
        source = {"schema": 1, "profile": "npm-11.19.1-lsf-bundle-v6", "patches": patches,
                  "libraries": libraries, "repairs": repairs,
                  "base": base_pin,
                  "bundleRepair": {"path": "repairs/npm-glob-minimatch.json", "sha256": sources.digest(encoded_bundle)}}
        source_path = root / "website/toolchain/source.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        builder = root / "website/toolchain/prepare.py"
        builder.write_bytes(b"trusted builder identity; scanner never executes this\n")
        control = {"schema": 1, "source_sha256": sources.digest(source_path.read_bytes()),
                   "builder_sha256": sources.digest(builder.read_bytes()), "repairs": policy,
                   "bundle_repair": {"profile": bundle_repair["profile"], "repair_sha256": sources.digest(encoded_bundle),
                       "advisories": {"glob": [{"id": "GHSA-3g3m-2fjr-6pw4", "modified": "reviewed-glob"}],
                                      "minimatch": [{"id": "GHSA-g3hv-75wg-m249", "modified": "reviewed-minimatch"}]}}}
        (root / "npm-source-repairs.json").write_text(json.dumps(control), encoding="utf-8")
        entries, packages = [], []
        for directory in ("website", "examples/framework-compatibility", "website/toolchain"):
            path = directory + "/package-lock.json"
            lock = {"packages": {}}
            if directory.endswith("toolchain"):
                selected = {"integrity": sources.integrity(sources.distribution(derived))}
                lock["packages"]["node_modules/npm"] = {"integrity": selected["integrity"]}
                for name, version in (("glob", "13.0.6"), ("minimatch", "10.2.5")):
                    lock["packages"]["node_modules/npm/node_modules/" + name] = {"version": version, "inBundle": True}
                kind = "derived_bundle"
            else:
                selected = {"libraries": {name: {"integrity": row["integrity"]} for name, row in policy.items()}}
                lock["packages"] = {"node_modules/" + name: {"integrity": row["integrity"]} for name, row in policy.items()}
                kind = "derived_libraries"
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(lock), encoding="utf-8")
            selected["lock_sha256"] = sources.digest(file.read_bytes())
            entries.append({"path": directory + "/package.json", "lock": path, kind: selected})
            packages.append(Package("npm", "fixture", "1.0.0", path))
        return packages, {"manifests": entries}, lambda pin: raw_inputs[pin["name"]]

    def test_independent_reconstruction_checks_both_libraries_and_complete_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages, config, fetch = self.verification_fixture(root)
            with patch.object(sources, "POLICY", root):
                result = sources.verify_sources(root, packages, config, fetch)
            self.assertEqual({row["name"] for row in result}, {"braces", "http-cache-semantics", "deepmerge", "glob", "minimatch"})
            self.assertEqual({row["name"]: len(row["locks"]) for row in result},
                             {"braces": 2, "http-cache-semantics": 3, "deepmerge": 2, "glob": 1, "minimatch": 1})

    def test_independent_reconstruction_rejects_upstream_source_lock_and_patch_drift(self):
        for change in ("upstream", "source", "lock", "repair", "bundle-repair", "builder"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                packages, config, fetch = self.verification_fixture(root)
                paths = {"source": "website/toolchain/source.json", "lock": "website/package-lock.json",
                         "repair": "website/toolchain/repairs/braces.json", "builder": "website/toolchain/prepare.py",
                         "bundle-repair": "website/toolchain/repairs/npm-glob-minimatch.json"}
                if change == "upstream":
                    fetch = lambda pin: b"unauthenticated replacement"
                else:
                    path = root / paths[change]
                    path.write_bytes(path.read_bytes() + b" ")
                with patch.object(sources, "POLICY", root), self.assertRaises(SecurityError):
                    sources.verify_sources(root, packages, config, fetch)

    def test_bundle_receipts_are_bound_to_exact_versions_locks_and_advisory_revisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages, config, fetch = self.verification_fixture(root)
            with patch.object(sources, "POLICY", root):
                receipts = sources.verify_sources(root, packages, config, fetch)
            selected = [row for row in receipts if row["name"] in {"glob", "minimatch"}]
            known = [finding("osv", row["advisories"][0]["id"], row["locks"][0],
                             f'npm:{row["name"]}@{row["version"]}') for row in selected]
            future = finding("osv", "GHSA-future-test", known[0].path, known[0].package)
            observations = [{"advisories": [{"package": {"name": row["name"], "version": row["version"],
                              "path": row["locks"][0]}, **row["advisories"][0]} for row in selected]}]
            self.assertEqual(sources.resolve_findings(known + [future], observations, selected), ([future], known))
            observations[0]["advisories"][0]["modified"] = "changed-revision"
            remaining, fixed = sources.resolve_findings(known, observations, selected)
            self.assertEqual(remaining, [known[0]])
            self.assertEqual(fixed, [known[1]])
        for change in ("missing", "version", "duplicate"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                packages, config, fetch = self.verification_fixture(root)
                entry = config["manifests"][-1]
                path = root / entry["lock"]
                lock = json.loads(path.read_bytes())
                key = "node_modules/npm/node_modules/glob"
                if change == "missing":
                    del lock["packages"][key]
                elif change == "version":
                    lock["packages"][key]["version"] = "13.0.5"
                else:
                    lock["packages"]["node_modules/glob"] = dict(lock["packages"][key])
                path.write_text(json.dumps(lock), encoding="utf-8")
                entry["derived_bundle"]["lock_sha256"] = sources.digest(path.read_bytes())
                with patch.object(sources, "POLICY", root), self.assertRaisesRegex(SecurityError, "npm-bundle-repair-lock-identity"):
                    sources.verify_sources(root, packages, config, fetch)

    def test_selector_bundle_refuses_changed_or_shadowed_existing_dependencies(self):
        for change in ("version", "graph", "shadow"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                packages, config, original_fetch = self.verification_fixture(root)
                files = sources.members(original_fetch({"name": "npm"}))
                key = "package/node_modules/cssesc/package.json"
                if change == "version":
                    files[key] = b'{"name":"cssesc","version":"3.0.1"}', 0o644
                elif change == "graph":
                    files[key] = b'{"name":"cssesc","version":"3.0.0","dependencies":{"unreviewed":"1.0.0"}}', 0o644
                else:
                    files["package/node_modules/postcss-selector-parser/node_modules/cssesc/index.js"] = b"shadow", 0o644
                raw = tarball(files)
                path = root / "website/toolchain/source.json"
                source = json.loads(path.read_bytes())
                source["base"]["integrity"] = sources.integrity(raw)
                path.write_text(json.dumps(source), encoding="utf-8")
                policy_path = root / "npm-source-repairs.json"
                policy = json.loads(policy_path.read_bytes())
                policy["source_sha256"] = sources.digest(path.read_bytes())
                policy_path.write_text(json.dumps(policy), encoding="utf-8")
                fetch = lambda pin: raw if pin["name"] == "npm" else original_fetch(pin)
                with patch.object(sources, "POLICY", root), self.assertRaisesRegex(
                        SecurityError, "npm-repair-package-graph|npm-repair-shadowed-bundle-dependency"):
                    sources.verify_sources(root, packages, config, fetch)


    def checkout_fixture(self, root):
        policy = json.loads(read_file(POLICY, "action-source-repairs.json"))
        controls = root / "controls"
        controls.mkdir()
        (controls / "action-source-repairs.json").write_text(json.dumps(policy))
        for row in (policy["bindings"] | policy["assets"]).values():
            target = root / row["snapshot"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, row["snapshot"]))
        (root / ".github/security/actions.json").write_bytes(read_file(ROOT, ".github/security/actions.json"))
        entry = {"path": sources.CHECKOUT_PREFIX + "package.json", "kind": "npm",
                 "lock": sources.CHECKOUT_PREFIX + "package-lock.json",
                 "source_repair": sources.CHECKOUT_PROFILE}
        raw = read_file(root, policy["assets"]["upstream"]["snapshot"])
        return controls, entry, lambda pin: raw

    def test_checkout_published_source_reconstructs_and_resolves_only_its_exact_advisory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls, entry, fetch = self.checkout_fixture(root)
            with patch.object(sources, "POLICY", controls):
                packages = npm_packages(root, entry)
                receipts = sources.verify_sources(root, packages, {"manifests": [entry]}, fetch)
            self.assertEqual(len(packages), 581)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]["action"], sources.CHECKOUT_REFERENCE)
            known = finding("osv", "GHSA-gcqx-w48m-w2h4", entry["lock"], "npm:deepmerge@4.3.1")
            foreign = finding("osv", known.finding, ".github/security/actions/setup-node/package-lock.json", known.package)
            observations = [{"advisories": [{"package": {"name": "deepmerge", "version": "4.3.1", "path": known.path},
                                              **receipts[0]["advisories"][0]}]}]
            self.assertEqual(sources.resolve_findings([known, foreign], observations, receipts), ([foreign], [known]))
            observations[0]["advisories"][0]["modified"] = "future-revision"
            self.assertEqual(sources.resolve_findings([known], observations, receipts), ([known], []))

    def test_checkout_source_rejects_graph_revision_source_and_build_drift(self):
        changes = (
            (".github/security/actions.json", lambda value: value.replace(b"4d310727", b"0d310727")),
            (sources.CHECKOUT_PREFIX + "package-lock.json", lambda value: value.replace(b'"license": "MIT"', b'"license": "ISC"', 1)),
            (".github/security/actions/checkout-source/deepmerge-4.3.1.repaired.tar", lambda value: value + b"drift"),
            (".github/security/actions/checkout-source/repair.json", lambda value: value.replace(b"__proto__", b"__other__", 1)),
            (".github/security/actions/checkout-source/declaration.json", lambda value: value.replace(b'"forkBuildVerified": false', b'"forkBuildVerified": true')),
            (".github/security/actions/checkout-source/fork-build.json", lambda value: value.replace(b'"jobConclusion": "success"', b'"jobConclusion": "failure"')))
        for name, mutate in changes:
            with self.subTest(path=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                controls, entry, fetch = self.checkout_fixture(root)
                target = root / name
                before = target.read_bytes()
                after = mutate(before)
                self.assertNotEqual(before, after)
                target.write_bytes(after)
                with patch.object(sources, "POLICY", controls), self.assertRaises(SecurityError):
                    packages = npm_packages(root, entry)
                    sources.verify_sources(root, packages, {"manifests": [entry]}, fetch)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls, entry, fetch = self.checkout_fixture(root)
            with patch.object(sources, "POLICY", controls):
                packages = npm_packages(root, entry)
                with self.assertRaises(SecurityError):
                    sources.verify_sources(root, packages, {"manifests": [entry]}, lambda pin: fetch(pin) + b"drift")

    def test_all_additional_action_sources_bind_exact_revisions_and_resolve_only_their_locks(self):
        inventory = json.loads(read_file(ROOT, ".github/security/inventory.json"))
        entries = [entry for entry in inventory["manifests"]
                   if entry.get("source_repair") == sources.ACTION_PROFILE]
        packages = [package for entry in entries for package in npm_packages(ROOT, entry)]
        upstream = read_file(ROOT, ".github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz")
        with patch.object(sources, "verify_minimatch_action_sources", return_value=[]):
            receipts = sources.verify_sources(ROOT, packages, {"manifests": entries}, lambda pin: upstream)
        self.assertEqual(len(entries), len(receipts), 5)
        self.assertEqual({receipt["action"] for receipt in receipts}, set(sources.ACTION_REFERENCES.values()))
        self.assertEqual({receipt["profile"] for receipt in receipts}, {sources.ACTION_PROFILE})
        advisory = receipts[0]["advisories"][0]
        findings = [finding("osv", advisory["id"], entry["lock"], "npm:deepmerge@4.3.1")
                    for entry in entries]
        observations = [{"advisories": [{"package": {"name": "deepmerge", "version": "4.3.1",
                                                       "path": item.path}, **advisory}]}
                        for item in findings]
        self.assertEqual(sources.resolve_findings(findings, observations, receipts), ([], findings))
        foreign = finding("osv", advisory["id"], ".github/security/actions/attest/package-lock.json",
                          "npm:deepmerge@4.3.1")
        self.assertEqual(sources.resolve_findings([foreign], observations, receipts), ([foreign], []))

    def cache_fixture(self, root):
        controls, _, fetch = self.checkout_fixture(root)
        for name in (sources.CACHE_PREFIX + "package.json", sources.CACHE_PREFIX + "package-lock.json",
                     sources.CACHE_PREFIX + "restore/action.yml.snapshot",
                     sources.CACHE_PREFIX + "save/action.yml.snapshot",
                     ".github/security/actions/deepmerge-source/installed-verifier.mjs.snapshot"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, name))
        entry = {"path": sources.CACHE_PREFIX + "package.json", "kind": "npm",
                 "lock": sources.CACHE_PREFIX + "package-lock.json", "source_repair": sources.ACTION_PROFILE}
        return controls, entry, fetch

    def test_cache_receipt_binds_both_actions_and_only_the_exact_advisory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls, entry, fetch = self.cache_fixture(root)
            with patch.object(sources, "POLICY", controls):
                packages = npm_packages(root, entry)
                receipts = sources.verify_sources(root, packages, {"manifests": [entry]}, fetch)
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]["action"], sources.CACHE_RESTORE_REFERENCE)
            self.assertEqual(receipts[0]["related_actions"], [sources.CACHE_SAVE_REFERENCE])
            advisory = receipts[0]["advisories"][0]
            known = finding("osv", advisory["id"], entry["lock"], "npm:deepmerge@4.3.1")
            foreign = finding("osv", advisory["id"], ".github/security/actions/attest/package-lock.json", known.package)
            observations = [{"advisories": [{"package": {"name": "deepmerge", "version": "4.3.1",
                                                           "path": known.path}, **advisory}]}]
            self.assertEqual(sources.resolve_findings([known, foreign], observations, receipts), ([foreign], [known]))
            observations[0]["advisories"][0]["modified"] = "future-revision"
            self.assertEqual(sources.resolve_findings([known], observations, receipts), ([known], []))
            with patch.object(sources, "POLICY", controls), self.assertRaises(SecurityError):
                npm_packages(root, {key: value for key, value in entry.items() if key != "source_repair"})

    def test_cache_receipt_refuses_entrypoint_revision_and_snapshot_drift(self):
        changes = ("missing-save", "save-revision", "save-metadata", "restore-metadata", "verifier",
                   "duplicate-file", "snapshot")
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                controls, entry, fetch = self.cache_fixture(root)
                registry_path = root / ".github/security/actions.json"
                registry = json.loads(registry_path.read_bytes())
                restore = registry["actions"][sources.CACHE_RESTORE_REFERENCE]
                save = registry["actions"][sources.CACHE_SAVE_REFERENCE]
                if change == "missing-save":
                    del registry["actions"][sources.CACHE_SAVE_REFERENCE]
                elif change == "save-revision":
                    save["revision"] = "0" * 40
                elif change == "save-metadata":
                    save["metadata"]["source"] = "restore/action.yml"
                elif change == "restore-metadata":
                    restore["metadata"]["snapshot"] = sources.CACHE_PREFIX + "save/action.yml.snapshot"
                elif change == "verifier":
                    next(row for row in save["files"] if row["source"] == sources.ACTION_VERIFIER_SOURCE)["sha256"] = "0" * 64
                elif change == "duplicate-file":
                    save["files"].append(copy.deepcopy(save["files"][0]))
                else:
                    target = root / (sources.CACHE_PREFIX + "package.json")
                    payload = target.read_bytes() + b"\n"
                    target.write_bytes(payload)
                    replacement = hashlib.sha256(payload).hexdigest()
                    for action in (restore, save):
                        row = next(row for row in action["files"] if row["source"] == "package.json")
                        row["sha256"] = row["source_sha256"] = replacement
                registry_path.write_text(json.dumps(registry), encoding="utf-8")
                with patch.object(sources, "POLICY", controls), self.assertRaises(SecurityError):
                    packages = npm_packages(root, entry)
                    sources.verify_sources(root, packages, {"manifests": [entry]}, fetch)

    def test_checkout_source_never_admits_unselected_or_registry_graphs_as_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls, entry, fetch = self.checkout_fixture(root)
            with patch.object(sources, "POLICY", controls):
                unselected = {key: value for key, value in entry.items() if key != "source_repair"}
                with self.assertRaises(SecurityError):
                    npm_packages(root, unselected)
                foreign = {**entry, "path": ".github/security/actions/setup-node/package.json"}
                owner = json.loads(read_file(root, entry["path"]))
                lock = json.loads(read_file(root, entry["lock"]))
                with self.assertRaises(SecurityError):
                    sources.action_library_sources(root, foreign, owner, lock)
                del owner["devDependencies"]["deepmerge"]
                del lock["packages"][""]["devDependencies"]["deepmerge"]
                node = lock["packages"]["node_modules/deepmerge"]
                node["resolved"] = "https://registry.npmjs.org/deepmerge/-/deepmerge-4.3.1.tgz"
                node["integrity"] = sources.integrity(fetch({}))
                for name, value in ((entry["path"], owner), (entry["lock"], lock)):
                    (root / name).write_text(json.dumps(value))
                self.assertEqual(sources.action_library_sources(root, entry, owner, lock), {})
                packages = npm_packages(root, entry)
                self.assertEqual(sources.verify_sources(root, packages, {"manifests": [entry]}, fetch), [])


if __name__ == "__main__":
    unittest.main()
