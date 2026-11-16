"""Fail-closed coverage for the deploy-pages guarded source repairs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import security_actions, security_deploy_pages as deploy, security_npm_sources as sources
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages


class DeployPagesSourceRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-deploy-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {row[0] for row in deploy.ACTION_INPUTS.values()}
        paths |= {deploy.BUILD[0], ".github/security/actions.json"}
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, name))
        self.entry = {"kind": "npm", "path": deploy.PREFIX + "package.json", "lock": deploy.PREFIX + "package-lock.json",
                      "source_repair": deploy.DEEP_PROFILE, "minimatch_source_repair": deploy.PROFILE}
        self.runtime = {name: ("synthetic deploy runtime " + name).encode() for name in deploy.RUNTIME}
        identities = {name: sources.source_identity(value) for name, value in self.runtime.items()}
        build_path = self.root / deploy.BUILD[0]
        build = json.loads(build_path.read_bytes())
        build["outputs"] = identities
        build_path.write_text(json.dumps(build), encoding="utf-8")
        build_identity = sources.source_identity(build_path.read_bytes())
        replacement = (deploy.BUILD[0], build_identity["bytes"], build_identity["sha256"], build_identity["gitBlob"])
        for name, value in (("RUNTIME", identities), ("BUILD", replacement)):
            patcher = patch.object(deploy, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []

    def fetch(self, pin):
        if pin["name"] == "deepmerge":
            source = ".lsf-source/deepmerge-4.3.1.original.tgz"
        else:
            package = next(row for row in deploy.PACKAGES
                           if (row["name"], row["version"]) == (pin["name"], pin["version"]))
            source = ".lsf-source/" + package["upstream"]
        return read_file(self.root, deploy.ACTION_INPUTS[source][0])

    def runtime_fetch(self, reference, path):
        self.assertEqual(reference, deploy.REFERENCE)
        self.calls.append(path)
        return self.runtime[path]

    def verify(self, entry=None, runtime=None, fetch=None):
        entry = self.entry if entry is None else entry
        packages = npm_packages(self.root, entry)
        return sources.verify_sources(self.root, packages, {"manifests": [entry]}, fetch or self.fetch,
                                      runtime or self.runtime_fetch)

    def test_raw_inventory_retains_all_paths_and_only_exact_advisories_are_repaired(self):
        packages = npm_packages(self.root, self.entry)
        self.assertEqual(len(packages), 700)
        self.assertEqual(sum((p.name, p.version) == ("minimatch", "9.0.9") for p in packages), 2)
        receipts = self.verify()
        self.assertEqual({(r["name"], r["version"]) for r in receipts},
                         {("deepmerge", "4.3.1"), ("glob", "10.5.0"), ("minimatch", "9.0.9")})
        self.assertEqual(set(self.calls), set(deploy.RUNTIME))
        known = [finding("osv", r["advisories"][0]["id"], self.entry["lock"],
                         "npm:" + r["name"] + "@" + r["version"]) for r in receipts]
        foreign = finding("osv", known[0].finding, ".github/security/actions/attest/package-lock.json", known[0].package)
        future_version = finding("osv", "GHSA-3g3m-2fjr-6pw4", self.entry["lock"], "npm:glob@10.5.1")
        observed = [{"advisories": [{"package": Package("npm", r["name"], r["version"], self.entry["lock"]).public(),
                                     **r["advisories"][0]} for r in receipts]}]
        self.assertEqual(sources.resolve_findings(known + [foreign], observed, receipts), ([foreign], known))
        self.assertEqual(sources.resolve_findings([future_version], observed, receipts), ([future_version], []))
        for index in range(len(receipts)):
            altered = copy.deepcopy(observed)
            altered[0]["advisories"][index]["modified"] = "future-revision"
            self.assertEqual(sources.resolve_findings([known[index]], altered, receipts), ([known[index]], []))

    def test_all_fork_inputs_and_owner_evidence_refuse_drift(self):
        inputs = {row[0] for row in deploy.ACTION_INPUTS.values()} | {deploy.BUILD[0]}
        for name in sorted(inputs):
            with self.subTest(input=name):
                target = self.root / name
                original = target.read_bytes()
                target.write_bytes(original + b"\n")
                try:
                    with self.assertRaises(SecurityError):
                        self.verify()
                finally:
                    target.write_bytes(original)

    def test_each_runtime_and_original_registry_archive_is_required(self):
        for selected in self.runtime:
            def altered(reference, path):
                value = self.runtime_fetch(reference, path)
                return value + b"drift" if path == selected else value
            with self.subTest(runtime=selected), self.assertRaises(SecurityError):
                self.verify(runtime=altered)
        for package in ("deepmerge", "glob", "minimatch"):
            def altered(pin):
                value = self.fetch(pin)
                return value + b"drift" if pin["name"] == package else value
            with self.subTest(package=package), self.assertRaises(SecurityError):
                self.verify(fetch=altered)
        for reference, path in ((deploy.REFERENCE, "dist/unreviewed.js"),
                                (deploy.REFERENCE[:-1] + "0", "dist/index.js")):
            with self.assertRaises(SecurityError):
                sources.action_runtime(reference, path)

    def test_unreviewed_profile_and_package_graph_are_rejected(self):
        for entry in ({**self.entry, "path": ".github/security/actions/attest/package.json"},
                      {**self.entry, "lock": ".github/security/actions/attest/package-lock.json"},
                      {**self.entry, "source_repair": sources.ACTION_PROFILE},
                      {**self.entry, "minimatch_source_repair": sources.MINIMATCH_PROFILE},
                      {**self.entry, "derived_bundle": "npm"}):
            with self.subTest(entry=entry), self.assertRaises((SecurityError, OSError)):
                self.verify(entry=entry)
        owner = json.loads(read_file(self.root, self.entry["path"]))
        lock = json.loads(read_file(self.root, self.entry["lock"]))
        for path in ("node_modules/glob", "node_modules/glob/node_modules/minimatch",
                     "node_modules/@typescript-eslint/typescript-estree/node_modules/minimatch"):
            changed = copy.deepcopy(lock)
            changed["packages"][path]["integrity"] = "sha512-foreign"
            with self.subTest(path=path), self.assertRaises(SecurityError):
                deploy.source_inputs(self.root, self.entry, owner, changed)

    def test_applier_cannot_be_rebound_to_a_forged_lock_or_script(self):
        policy_path = self.root / ".github/security/actions.json"
        policy = json.loads(policy_path.read_bytes())
        owner = json.loads(read_file(self.root, self.entry["path"]))
        lock = json.loads(read_file(self.root, self.entry["lock"]))
        changed = copy.deepcopy(lock)
        changed["packages"]["node_modules/glob/node_modules/minimatch"]["version"] = "9.0.8"
        snapshot = self.root / self.entry["lock"]
        snapshot.write_text(json.dumps(changed), encoding="utf-8")
        identity = sources.source_identity(snapshot.read_bytes())
        bindings = copy.deepcopy(deploy.ACTION_INPUTS)
        bindings["package-lock.json"] = (self.entry["lock"], identity["bytes"], identity["sha256"], identity["gitBlob"])
        for row in policy["actions"][deploy.REFERENCE]["files"]:
            if row["source"] == "package-lock.json":
                row["sha256"] = row["source_sha256"] = identity["sha256"]
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        with patch.object(deploy, "ACTION_INPUTS", bindings), self.assertRaisesRegex(SecurityError, "applier-input-drift"):
            deploy.source_inputs(self.root, self.entry, owner, changed)

    def test_graph_binds_the_applier_and_all_sixteen_fork_inputs(self):
        policy_path = self.root / ".github/security/actions.json"
        policy = json.loads(policy_path.read_bytes())
        policy["actions"] = {deploy.REFERENCE: policy["actions"][deploy.REFERENCE]}
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        workflow = self.root / ".github/workflows/fixture.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("jobs:\n  check:\n    steps:\n      - uses: " + deploy.REFERENCE + "\n", encoding="utf-8")
        self.assertEqual(len(security_actions.verify(self.root, [".github/workflows/fixture.yml"])), 1)
        rows = policy["actions"][deploy.REFERENCE]["files"]
        for mutated in (rows[:-1], rows + [rows[-1]], [{**row, "source": "unreviewed"} if row["source"] == deploy.GUARD else row for row in rows]):
            policy["actions"][deploy.REFERENCE]["files"] = mutated
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.subTest(inputs=len(mutated)), self.assertRaises(SecurityError):
                security_actions.verify(self.root, [".github/workflows/fixture.yml"])


if __name__ == "__main__":
    unittest.main()
