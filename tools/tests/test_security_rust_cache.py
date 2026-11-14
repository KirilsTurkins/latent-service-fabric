"""Fail-closed source, runtime and historical controls for Rust-cache."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import security_actions, security_npm_sources as sources, security_rust_cache as cache, security_setup_go as go
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages
from tools.tests.test_sdk_scratch_qualification import historical_security_actions


class RustCacheSourceRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-rust-cache-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {row[0] for row in cache.ACTION_INPUTS.values()} | {row[0] for row in go.DEEP_MATERIAL.values()}
        paths |= {sources.NODE_MINIMATCH_ASSETS[name]["snapshot"] for name in ("upstream", "archive", "repair")}
        paths |= {cache.BUILD_PATH, ".github/security/actions.json"}
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, name))
        self.entry = {"kind": "npm", "path": cache.PREFIX + "package.json", "lock": cache.PREFIX + "package-lock.json",
                      "source_repair": cache.PROFILE}
        self.runtime = {path: ("synthetic Rust cache runtime " + path).encode() for path in cache.RUNTIME}
        identities = {path: sources.source_identity(value) for path, value in self.runtime.items()}
        build_path = self.root / cache.BUILD_PATH
        evidence = json.loads(build_path.read_bytes())
        evidence["outputs"].update(identities)
        build_path.write_text(json.dumps(evidence), encoding="utf-8")
        for name, value in (("RUNTIME", identities), ("BUILD_IDENTITY", sources.source_identity(build_path.read_bytes()))):
            patcher = patch.object(cache, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []

    def fetch(self, pin):
        source = go.DEEP_MATERIAL["upstream"][0] if pin["name"] == "deepmerge" else sources.NODE_MINIMATCH_ASSETS["upstream"]["snapshot"]
        return read_file(self.root, source)

    def runtime_fetch(self, reference, name):
        self.assertEqual(reference, cache.REFERENCE)
        self.calls.append(name)
        return self.runtime[name]

    def verify(self, entry=None, runtime=None, fetch=None):
        entry = self.entry if entry is None else entry
        packages = npm_packages(self.root, entry)
        return sources.verify_sources(self.root, packages, {"manifests": [entry]}, fetch or self.fetch,
                                      runtime or self.runtime_fetch)

    def action_graph(self):
        path = self.root / ".github/security/actions.json"
        value = json.loads(path.read_bytes())
        value["actions"] = {cache.REFERENCE: value["actions"][cache.REFERENCE]}
        path.write_text(json.dumps(value), encoding="utf-8")
        workflow = self.root / ".github/workflows/fixture.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("jobs:\n  check:\n    steps:\n      - uses: " + cache.REFERENCE + "\n", encoding="utf-8")
        return security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_both_repairs_bind_all_six_bundles_and_only_exact_advisories(self):
        receipts = self.verify()
        self.assertEqual({row["name"] for row in receipts}, {"deepmerge", "minimatch"})
        self.assertEqual(set(self.calls), set(cache.RUNTIME))
        self.assertTrue(all(row["action"] == cache.REFERENCE and row["locks"] == [self.entry["lock"]] for row in receipts))
        known = [finding("osv", row["advisories"][0]["id"], self.entry["lock"],
                         "npm:" + row["name"] + "@" + row["version"]) for row in receipts]
        foreign = finding("osv", known[0].finding, ".github/security/actions/setup-node/package-lock.json", known[0].package)
        observations = [{"advisories": [{"package": Package("npm", row["name"], row["version"], self.entry["lock"]).public(),
                                         **row["advisories"][0]} for row in receipts]}]
        self.assertEqual(sources.resolve_findings(known + [foreign], observations, receipts), ([foreign], known))
        observations[0]["advisories"][0]["modified"] = "new-revision"
        self.assertEqual(sources.resolve_findings([known[0]], observations, receipts), ([known[0]], []))
        self.assertEqual(len(self.action_graph()), 1)

    def test_every_source_and_evidence_rejects_tampering_even_if_policy_is_rehashed(self):
        material = {row[0] for row in cache.ACTION_INPUTS.values()} | {row[0] for row in go.DEEP_MATERIAL.values()}
        material |= {sources.NODE_MINIMATCH_ASSETS[name]["snapshot"] for name in ("upstream", "archive", "repair")}
        material.add(cache.BUILD_PATH)
        for snapshot in sorted(material):
            with self.subTest(snapshot=snapshot):
                target = self.root / snapshot
                before = target.read_bytes()
                action_path = self.root / ".github/security/actions.json"
                action_before = action_path.read_bytes()
                altered = before + b"\n"
                target.write_bytes(altered)
                policy = json.loads(action_before)
                for item in policy["actions"][cache.REFERENCE]["files"]:
                    if item["snapshot"] == snapshot:
                        item["sha256"] = item["source_sha256"] = sources.digest(altered)
                action_path.write_text(json.dumps(policy), encoding="utf-8")
                try:
                    with self.assertRaises((SecurityError, ValueError)):
                        self.verify()
                finally:
                    target.write_bytes(before)
                    action_path.write_bytes(action_before)

    def test_each_runtime_and_upstream_is_required_and_unavailable_fails(self):
        for name in self.runtime:
            with self.subTest(runtime=name):
                def wrong(reference, source):
                    value = self.runtime_fetch(reference, source)
                    return value + b"drift" if source == name else value
                with self.assertRaises(SecurityError):
                    self.verify(runtime=wrong)
        for package in ("deepmerge", "minimatch"):
            with self.subTest(upstream=package), self.assertRaises(SecurityError):
                self.verify(fetch=lambda pin: self.fetch(pin) + (b"drift" if pin["name"] == package else b""))
        with self.assertRaises(OSError):
            self.verify(runtime=lambda _ref, _path: (_ for _ in ()).throw(OSError("unavailable")))
        for reference, path in ((cache.REFERENCE, "dist/other.js"),
                                (cache.REFERENCE.replace("65397265", "08534d49"), "dist/save.js")):
            with self.assertRaises(SecurityError):
                sources.action_runtime(reference, path)

    def test_graph_rejects_nested_named_resolved_and_dependency_aliases(self):
        lock = json.loads(read_file(self.root, self.entry["lock"]))
        cache.require_unique_deepmerge(lock)
        variants = []
        nested = copy.deepcopy(lock); nested["packages"]["node_modules/example/node_modules/deepmerge"] = copy.deepcopy(nested["packages"]["node_modules/deepmerge"]); variants.append(nested)
        named = copy.deepcopy(lock); named["packages"]["node_modules/example"] = {"name": "deepmerge"}; variants.append(named)
        resolved = copy.deepcopy(lock); resolved["packages"]["node_modules/example"] = {"resolved": "https://registry.npmjs.org/deepmerge/-/deepmerge-4.3.1.tgz"}; variants.append(resolved)
        aliased = copy.deepcopy(lock); aliased["packages"]["node_modules/example"] = {"dependencies": {"alias": "npm:deepmerge@4.3.1"}}; variants.append(aliased)
        for variant in variants:
            with self.subTest(variant=variants.index(variant)), self.assertRaises(SecurityError):
                cache.require_unique_deepmerge(variant)
        altered = self.root / self.entry["lock"]
        altered.write_bytes(altered.read_bytes() + b"\n")
        with self.assertRaises(SecurityError):
            self.verify()

    def test_action_graph_only_admits_exact_eight_sources_and_revision(self):
        self.assertEqual(len(self.action_graph()), 1)
        policy = self.root / ".github/security/actions.json"
        baseline = json.loads(policy.read_bytes())
        for change in ("revision", "missing", "guard", "test"):
            with self.subTest(change=change):
                value = copy.deepcopy(baseline); row = value["actions"][cache.REFERENCE]
                if change == "revision": row["revision"] = "0" * 40
                elif change == "missing": row["files"].pop()
                elif change == "guard": row["files"][-2]["source"] = "other.mjs"
                else: row["files"][-1]["source"] = "other-test.mjs"
                policy.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(SecurityError):
                    security_actions.verify(self.root, [".github/workflows/fixture.yml"])
        workflow = self.root / ".github/workflows/fixture.yml"
        for stale in (cache.REFERENCE.replace("653972653a76770ab9b45cca67e4db8221bed334", "0" * 40),
                      cache.REFERENCE.replace("lsf-rust-cache", "other-action")):
            with self.subTest(stale=stale):
                value = copy.deepcopy(baseline)
                row = value["actions"].pop(cache.REFERENCE)
                row["repository"], row["revision"] = stale.rsplit("@", 1)
                value["actions"][stale] = row
                policy.write_text(json.dumps(value), encoding="utf-8")
                workflow.write_text("jobs:\n  check:\n    steps:\n      - uses: " + stale + "\n", encoding="utf-8")
                with self.assertRaisesRegex(SecurityError, "unreviewed-additional-action-source"):
                    security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_historical_inverse_refuses_stale_mixed_and_future_pins(self):
        current = cache.REFERENCE
        previous = current.replace("653972653a76770ab9b45cca67e4db8221bed334", "476b290465f7c84db317df6e6a6e2d3c12ea3477")
        future = current.replace("653972653a76770ab9b45cca67e4db8221bed334", "0" * 40)
        for value in (current, current.encode()):
            self.assertEqual(historical_security_actions(value), previous if isinstance(value, str) else previous.encode())
        for value in (previous, current + "\n" + previous, future):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                historical_security_actions(value)


if __name__ == "__main__":
    unittest.main()
