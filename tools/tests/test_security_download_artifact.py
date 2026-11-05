"""Controls for both runtime artifacts and all download-action source repairs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import security_actions, security_npm_sources as sources, security_setup_go as go
from tools import security_download_artifact as download
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages


class DownloadActionSourceRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-download-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {row[0] for row in download.ACTION_INPUTS.values()} | {row[0] for row in download.MATERIAL.values()}
        paths |= {row[0] for row in go.DEEP_MATERIAL.values()}
        paths |= {".github/security/actions.json"}
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, name))
        self.entry = {"kind": "npm", "path": download.PREFIX + "package.json", "lock": download.PREFIX + "package-lock.json",
                      "source_repair": download.DEEP_PROFILE, "minimatch_source_repair": download.PROFILE}
        self.runtime = {path: ("synthetic download runtime " + path).encode() for path in download.RUNTIME}
        identities = {path: sources.source_identity(value) for path, value in self.runtime.items()}
        build_path = self.root / download.MATERIAL["fork-build.json"][0]
        evidence = json.loads(build_path.read_bytes()); evidence["bundles"] = identities
        build_path.write_text(json.dumps(evidence), encoding="utf-8")
        changed = copy.deepcopy(download.MATERIAL); old = changed["fork-build.json"]
        identity = sources.source_identity(build_path.read_bytes())
        changed["fork-build.json"] = (old[0], identity["bytes"], identity["sha256"], identity["gitBlob"])
        for name, value in (("RUNTIME", identities), ("MATERIAL", changed)):
            patcher = patch.object(download, name, value); patcher.start(); self.addCleanup(patcher.stop)
        self.calls = []

    def fetch(self, pin):
        if pin["name"] == "deepmerge":
            return read_file(self.root, go.DEEP_MATERIAL["upstream"][0])
        pkg = next(p for p in download.PACKAGES if p["name"] == pin["name"] and p["version"] == pin["version"])
        return read_file(self.root, download.MATERIAL[pkg["upstream"]][0])

    def runtime_fetch(self, reference, path):
        self.assertEqual(reference, download.REFERENCE)
        self.calls.append(path)
        return self.runtime[path]

    def verify(self, entry=None, runtime=None, fetch=None):
        entry = self.entry if entry is None else entry
        packages = npm_packages(self.root, entry)
        return sources.verify_sources(self.root, packages, {"manifests": [entry]}, fetch or self.fetch,
                                      runtime or self.runtime_fetch)

    def test_exact_sources_resolve_only_their_matching_known_advisories(self):
        receipts = self.verify()
        self.assertEqual({(r["name"], r["version"]) for r in receipts}, {
            ("deepmerge", "4.3.1"), ("glob", "10.5.0"), ("minimatch", "9.0.9"), ("minimatch", "10.2.6")})
        self.assertEqual(set(self.calls), set(download.RUNTIME))
        known = [finding("osv", r["advisories"][0]["id"], self.entry["lock"],
                         "npm:" + r["name"] + "@" + r["version"]) for r in receipts]
        foreign = finding("osv", known[0].finding, ".github/security/actions/attest/package-lock.json", known[0].package)
        observed = [{"advisories": [{"package": Package("npm", r["name"], r["version"], self.entry["lock"]).public(),
                                     **r["advisories"][0]} for r in receipts]}]
        self.assertEqual(sources.resolve_findings(known + [foreign], observed, receipts), ([foreign], known))
        observed[0]["advisories"][1]["modified"] = "new-revision"
        self.assertEqual(sources.resolve_findings([known[1]], observed, receipts), ([known[1]], []))

    def test_each_source_and_evidence_input_refuses_drift(self):
        for group in (download.ACTION_INPUTS, download.MATERIAL, go.DEEP_MATERIAL):
            for name, (snapshot, _, _, _) in group.items():
                with self.subTest(input=name):
                    target = self.root / snapshot
                    original = target.read_bytes(); target.write_bytes(original + b"\n")
                    try:
                        with self.assertRaises(SecurityError): self.verify()
                    finally: target.write_bytes(original)

    def test_runtime_and_registry_bytes_are_bound_to_the_reviewed_sources(self):
        for path in self.runtime:
            def altered(reference, name):
                value = self.runtime_fetch(reference, name)
                return value + b"drift" if name == path else value
            with self.subTest(runtime=path), self.assertRaises(SecurityError): self.verify(runtime=altered)
        for package, version in (("deepmerge", "4.3.1"), ("glob", "10.5.0"),
                                 ("minimatch", "9.0.9"), ("minimatch", "10.2.6")):
            def altered(pin):
                value = self.fetch(pin)
                return value + b"drift" if (pin["name"], pin["version"]) == (package, version) else value
            with self.subTest(package=package, version=version), self.assertRaises(SecurityError): self.verify(fetch=altered)
        for ref, path in ((download.REFERENCE, "dist/other/index.js"), (download.REFERENCE[:-1] + "0", "dist/index.js")):
            with self.assertRaises(SecurityError): sources.action_runtime(ref, path)

    def test_profile_cannot_bind_another_action_or_lock(self):
        for entry in ({**self.entry, "path": ".github/security/actions/attest/package.json"},
                      {**self.entry, "lock": ".github/security/actions/attest/package-lock.json"},
                      {**self.entry, "source_repair": sources.ACTION_PROFILE},
                      {**self.entry, "minimatch_source_repair": sources.MINIMATCH_PROFILE},
                      {**self.entry, "derived_bundle": "npm"}):
            with self.subTest(entry=entry), self.assertRaises((SecurityError, OSError)):
                self.verify(entry=entry)

    def test_action_graph_requires_the_exact_download_revision_and_sources(self):
        policy_path = self.root / ".github/security/actions.json"
        policy = json.loads(policy_path.read_bytes())
        policy["actions"] = {download.REFERENCE: policy["actions"][download.REFERENCE]}
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        workflow = self.root / ".github/workflows/fixture.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("jobs:\n  check:\n    steps:\n      - uses: " + download.REFERENCE + "\n", encoding="utf-8")
        self.assertEqual(len(security_actions.verify(self.root, [".github/workflows/fixture.yml"])), 1)
        policy["actions"][download.REFERENCE]["files"][-1]["source"] = "unreviewed-test.mjs"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaises(SecurityError): security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_both_minimatch_nine_installations_are_required(self):
        owner = json.loads(read_file(self.root, self.entry["path"]))
        lock = json.loads(read_file(self.root, self.entry["lock"]))
        for path in ("node_modules/glob/node_modules/minimatch", "node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch"):
            changed = copy.deepcopy(lock)
            changed["packages"][path]["resolved"] = "https://registry.npmjs.org/minimatch/-/minimatch-9.0.9.tgz"
            with self.subTest(path=path), self.assertRaises(SecurityError):
                download.source_inputs(self.root, self.entry, owner, changed)


if __name__ == "__main__":
    unittest.main()
