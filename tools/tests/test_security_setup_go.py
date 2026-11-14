"""Adversarial controls for setup-go's two source receipts and runtime pins."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import security_actions, security_npm_sources as sources, security_setup_go as go
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages


class SetupGoSourceRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-go-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {row[0] for row in go.ACTION_INPUTS.values()} | {row[0] for row in go.DEEP_MATERIAL.values()}
        paths |= {row[0] for row in go.MINI_MATERIAL.values()} | {".github/security/actions.json"}
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, name))
        self.entry = {"kind": "npm", "path": go.PREFIX + "package.json", "lock": go.PREFIX + "package-lock.json",
                      "source_repair": go.DEEP_PROFILE, "minimatch_source_repair": go.MINI_PROFILE}
        self.runtime = {path: ("synthetic Go runtime " + path).encode() for path in go.RUNTIME}
        identities = {path: sources.source_identity(value) for path, value in self.runtime.items()}
        build_path = self.root / go.MINI_MATERIAL["build"][0]
        evidence = json.loads(build_path.read_bytes())
        evidence["outputs"] = identities
        build_path.write_text(json.dumps(evidence), encoding="utf-8")
        changed = copy.deepcopy(go.MINI_MATERIAL)
        original = changed["build"]
        identity = sources.source_identity(build_path.read_bytes())
        changed["build"] = (original[0], identity["bytes"], identity["sha256"], identity["gitBlob"])
        for name, value in (("RUNTIME", identities), ("MINI_MATERIAL", changed)):
            patcher = patch.object(go, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        self.calls = []

    def fetch(self, pin):
        source = go.DEEP_MATERIAL if pin["name"] == "deepmerge" else go.MINI_MATERIAL
        return read_file(self.root, source["upstream"][0])

    def runtime_fetch(self, reference, name):
        self.assertEqual(reference, go.REFERENCE)
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
        value["actions"] = {go.REFERENCE: value["actions"][go.REFERENCE]}
        path.write_text(json.dumps(value), encoding="utf-8")
        workflow = self.root / ".github/workflows/fixture.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("jobs:\n  check:\n    steps:\n      - uses: " + go.REFERENCE + "\n", encoding="utf-8")
        return security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_both_exact_repairs_require_both_bundles_and_resolve_only_known_findings(self):
        receipts = self.verify()
        self.assertEqual({row["name"] for row in receipts}, {"deepmerge", "minimatch"})
        self.assertEqual(set(self.calls), set(go.RUNTIME))
        self.assertEqual({row["action"] for row in receipts}, {go.REFERENCE})
        self.assertTrue(all(row["locks"] == [self.entry["lock"]] for row in receipts))
        known = [finding("osv", row["advisories"][0]["id"], self.entry["lock"],
                         "npm:" + row["name"] + "@" + row["version"]) for row in receipts]
        foreign = finding("osv", known[0].finding, ".github/security/actions/setup-node/package-lock.json", known[0].package)
        observations = [{"advisories": [{"package": Package("npm", row["name"], row["version"], self.entry["lock"]).public(),
                                         **row["advisories"][0]} for row in receipts]}]
        self.assertEqual(sources.resolve_findings(known + [foreign], observations, receipts), ([foreign], known))
        observations[0]["advisories"][0]["modified"] = "new-revision"
        self.assertEqual(sources.resolve_findings([known[0]], observations, receipts), ([known[0]], []))
        self.assertEqual(len(self.action_graph()), 1)

    def test_every_input_and_build_receipt_refuses_rebinding(self):
        for group in (go.ACTION_INPUTS, go.DEEP_MATERIAL, go.MINI_MATERIAL):
            for name, (snapshot, _, _, _) in group.items():
                with self.subTest(input=name):
                    target = self.root / snapshot
                    before = target.read_bytes(); altered = before + b"\n"; target.write_bytes(altered)
                    action_path = self.root / ".github/security/actions.json"
                    action_before = action_path.read_bytes(); policy = json.loads(action_before)
                    for item in policy["actions"][go.REFERENCE]["files"]:
                        if item["snapshot"] == snapshot:
                            item["sha256"] = item["source_sha256"] = hashlib.sha256(altered).hexdigest()
                    action_path.write_text(json.dumps(policy), encoding="utf-8")
                    try:
                        with self.assertRaises(SecurityError): self.verify()
                    finally:
                        target.write_bytes(before); action_path.write_bytes(action_before)

    def test_both_runtime_bytes_and_upstream_archives_are_required(self):
        for name in self.runtime:
            with self.subTest(runtime=name):
                def wrong(reference, source):
                    value = self.runtime_fetch(reference, source)
                    return value + b"drift" if source == name else value
                with self.assertRaises(SecurityError): self.verify(runtime=wrong)
        for package in ("deepmerge", "minimatch"):
            with self.subTest(upstream=package):
                with self.assertRaises(SecurityError):
                    self.verify(fetch=lambda pin: self.fetch(pin) + (b"drift" if pin["name"] == package else b""))
        for reference, source in ((go.REFERENCE, "dist/other/index.js"),
                                  (go.REFERENCE.replace("92a5903f", "00200427"), "dist/setup/index.js")):
            with self.assertRaises(SecurityError): sources.action_runtime(reference, source)

    def test_profiles_cannot_be_reused_on_other_graphs_or_unselected_sources(self):
        for entry in ({**self.entry, "path": ".github/security/actions/setup-node/package.json"},
                      {**self.entry, "lock": ".github/security/actions/setup-node/package-lock.json"},
                      {**self.entry, "source_repair": sources.ACTION_PROFILE},
                      {**self.entry, "minimatch_source_repair": sources.MINIMATCH_PROFILE},
                      {**self.entry, "derived_bundle": "npm"},
                      {key: value for key, value in self.entry.items() if key != "source_repair"}):
            with self.subTest(entry=entry), self.assertRaises((SecurityError, OSError)):
                self.verify(entry=entry)
        owner = json.loads(read_file(self.root, self.entry["path"]))
        lock = json.loads(read_file(self.root, self.entry["lock"]))
        altered_owner = copy.deepcopy(owner); altered_owner["devDependencies"]["deepmerge"] = "4.3.1"
        altered_lock = copy.deepcopy(lock); altered_lock["packages"]["node_modules/minimatch"]["dev"] = True
        for candidate_owner, candidate_lock in ((altered_owner, lock), (owner, altered_lock)):
            with self.assertRaises(SecurityError): go.source_inputs(self.root, self.entry, candidate_owner, candidate_lock)

    def test_action_graph_rejects_stale_revision_and_unreviewed_sixth_source(self):
        self.assertEqual(len(self.action_graph()), 1)
        path = self.root / ".github/security/actions.json"
        baseline = json.loads(path.read_bytes())
        for change in ("revision", "entrypoint", "verifier", "test"):
            with self.subTest(change=change):
                value = copy.deepcopy(baseline); row = value["actions"][go.REFERENCE]
                if change == "revision": row["revision"] = "0" * 40
                elif change == "entrypoint": row["files"][0]["source"] = "sub/action.yml"
                elif change == "verifier": row["files"][-2]["source"] = "other.mjs"
                else: row["files"][-1]["source"] = "other-test.mjs"
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(SecurityError):
                    security_actions.verify(self.root, [".github/workflows/fixture.yml"])


if __name__ == "__main__":
    unittest.main()
