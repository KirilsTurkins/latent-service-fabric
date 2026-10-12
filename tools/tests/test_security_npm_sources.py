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
        version, profile, names, dependencies = (
            ("3.0.3", "braces-3.0.3-lsf-depth-v1",
             ["lib/utils.js", "lib/compile.js", "lib/expand.js", "lib/stringify.js", "lib/parse.js"],
             {"fill-range": "^7.1.1"}) if name == "braces" else
            ("4.3.0", "http-cache-semantics-4.3.0-lsf-cache-v1", ["index.js"], {}))
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
        files, pin, repair = self.repair_fixture()
        fixed = sources.source_repair(files, repair, pin)
        self.assertEqual(set(fixed), set(files))
        for name in ("package/package.json", "package/LICENSE", "package/unchanged.js"):
            self.assertEqual(fixed[name], files[name])
        self.assertEqual(json.loads(fixed["package/package.json"][0])["version"], "3.0.3")
        for row in repair["files"]:
            self.assertEqual(fixed["package/" + row["path"]], (b"after bounded source\n", 0o644))

    def test_repair_rejects_missing_walkers_preimage_postimage_edit_and_upstream_drift(self):
        files, pin, repair = self.repair_fixture()
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
        for name in ("braces", "http-cache-semantics"):
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
            (libraries if name == "braces" else patches).append(pin if name == "braces" else {**pin, "from": "4.2.0"})
        base_files = {"package/package.json": (b'{"name":"npm","version":"11.19.1"}', 0o644),
                      "package/node_modules/balanced-match/package.json": (b'{"name":"balanced-match","version":"4.0.4"}', 0o644),
                      "package/node_modules/cssesc/package.json": (b'{"name":"cssesc","version":"3.0.0"}', 0o644),
                      "package/node_modules/util-deprecate/package.json": (b'{"name":"util-deprecate","version":"1.0.2"}', 0o644)}
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
        source = {"schema": 1, "profile": "npm-11.19.1-lsf-bundle-v4", "patches": patches,
                  "libraries": libraries, "repairs": repairs,
                  "base": {"name": "npm", "version": "11.19.1", "integrity": sources.integrity(raw_inputs["npm"])}}
        source_path = root / "website/toolchain/source.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        builder = root / "website/toolchain/prepare.py"
        builder.write_bytes(b"trusted builder identity; scanner never executes this\n")
        control = {"schema": 1, "source_sha256": sources.digest(source_path.read_bytes()),
                   "builder_sha256": sources.digest(builder.read_bytes()), "repairs": policy}
        (root / "npm-source-repairs.json").write_text(json.dumps(control), encoding="utf-8")
        entries, packages = [], []
        for directory in ("website", "examples/framework-compatibility", "website/toolchain"):
            path = directory + "/package-lock.json"
            lock = {"packages": {}}
            if directory.endswith("toolchain"):
                selected = {"integrity": sources.integrity(sources.distribution(derived))}
                lock["packages"]["node_modules/npm"] = {"integrity": selected["integrity"]}
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
            self.assertEqual({row["name"] for row in result}, {"braces", "http-cache-semantics"})
            self.assertEqual({row["name"]: len(row["locks"]) for row in result},
                             {"braces": 2, "http-cache-semantics": 3})

    def test_independent_reconstruction_rejects_upstream_source_lock_and_patch_drift(self):
        for change in ("upstream", "source", "lock", "repair", "builder"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                packages, config, fetch = self.verification_fixture(root)
                paths = {"source": "website/toolchain/source.json", "lock": "website/package-lock.json",
                         "repair": "website/toolchain/repairs/braces.json", "builder": "website/toolchain/prepare.py"}
                if change == "upstream":
                    fetch = lambda pin: b"unauthenticated replacement"
                else:
                    path = root / paths[change]
                    path.write_bytes(path.read_bytes() + b" ")
                with patch.object(sources, "POLICY", root), self.assertRaises(SecurityError):
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


if __name__ == "__main__":
    unittest.main()
