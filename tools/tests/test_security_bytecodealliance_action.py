"""Exercise the nested action's exact development-only source-repair profile."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import security_actions, security_npm_sources as sources
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages


class BytecodeallianceActionSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-bca-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {row[0] for row in sources.BCA_INPUTS.values()} | {row[0] for row in sources.BCA_MATERIAL.values()}
        paths.add(".github/security/actions.json")
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, name))
        self.entry = {"kind": "npm", "path": sources.BCA_PREFIX + "package.json",
                      "lock": sources.BCA_PREFIX + "package-lock.json", "source_repair": sources.BCA_PROFILE}
        self.upstream = read_file(self.root, sources.BCA_MATERIAL["upstream"][0])

    def verify_source(self, entry=None):
        entry = entry or self.entry
        packages = npm_packages(self.root, entry)
        return sources.verify_sources(self.root, packages, {"manifests": [entry]}, lambda pin: self.upstream)

    def action_graph(self):
        path = self.root / ".github/security/actions.json"
        all_actions = json.loads(path.read_bytes())
        all_actions["actions"] = {sources.BCA_REFERENCE: all_actions["actions"][sources.BCA_REFERENCE]}
        path.write_text(json.dumps(all_actions), encoding="utf-8")
        workflow = self.root / ".github/workflows/fixture.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("jobs:\n  test:\n    steps:\n      - uses: " + sources.BCA_REFERENCE + "\n", encoding="utf-8")
        return security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_exact_graph_resolves_only_the_known_advisory_revision(self):
        receipts = self.verify_source()
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        self.assertEqual(receipt["action"], sources.BCA_REFERENCE)
        self.assertEqual(receipt["profile"], sources.BCA_PROFILE)
        self.assertEqual(receipt["locks"], [self.entry["lock"]])
        self.assertEqual(receipt["build_run"], 42020735461)
        known = finding("osv", "GHSA-gcqx-w48m-w2h4", self.entry["lock"], "npm:deepmerge@4.3.1")
        foreign = finding("osv", known.finding, ".github/security/actions/setup-node/package-lock.json", known.package)
        other = finding("osv", "GHSA-other-advisory", self.entry["lock"], known.package)
        observations = [{"advisories": [{"package": Package("npm", "deepmerge", "4.3.1", self.entry["lock"]).public(),
                                         **receipt["advisories"][0]}]}]
        self.assertEqual(sources.resolve_findings([known, foreign, other], observations, receipts),
                         ([foreign, other], [known]))
        observations[0]["advisories"][0]["modified"] = "future-revision"
        self.assertEqual(sources.resolve_findings([known], observations, receipts), ([known], []))
        self.assertEqual(len(self.action_graph()), 1)

    def test_each_authenticated_input_refuses_even_if_action_row_is_rebound(self):
        for name, (snapshot, _, _, _) in (sources.BCA_INPUTS | sources.BCA_MATERIAL).items():
            with self.subTest(input=name):
                target = self.root / snapshot
                before = target.read_bytes()
                # Whitespace keeps JSON files parseable, so this tests the
                # source identity rather than merely a JSON parse error.
                altered = before + b"\n"
                target.write_bytes(altered)
                action_path = self.root / ".github/security/actions.json"
                action_before = action_path.read_bytes()
                action = json.loads(action_before)
                for row in action["actions"][sources.BCA_REFERENCE]["files"]:
                    if row["snapshot"] == snapshot:
                        row["sha256"] = row["source_sha256"] = hashlib.sha256(altered).hexdigest()
                action_path.write_text(json.dumps(action), encoding="utf-8")
                try:
                    with self.assertRaises(SecurityError):
                        self.verify_source()
                finally:
                    target.write_bytes(before)
                    action_path.write_bytes(action_before)

    def test_nested_identity_cannot_be_rebound_or_used_as_a_root_profile(self):
        action_path = self.root / ".github/security/actions.json"
        baseline = json.loads(action_path.read_bytes())
        for change in ("revision", "repository", "metadata", "verifier", "duplicate", "extra"):
            with self.subTest(change=change):
                policy = copy.deepcopy(baseline)
                row = policy["actions"][sources.BCA_REFERENCE]
                if change == "revision":
                    row["revision"] = "0" * 40
                elif change == "repository":
                    row["repository"] = "owner/foreign"
                elif change == "metadata":
                    row["metadata"]["source"] = "action.yml"
                elif change == "verifier":
                    row["files"] = [item for item in row["files"] if item["source"] != sources.ACTION_VERIFIER_SOURCE]
                elif change == "duplicate":
                    row["files"].append(copy.deepcopy(row["files"][0]))
                else:
                    row["files"].append({"source": "other", "snapshot": "other", "sha256": "0" * 64})
                action_path.write_text(json.dumps(policy), encoding="utf-8")
                with self.assertRaises(SecurityError):
                    self.verify_source()
        action_path.write_text(json.dumps(baseline), encoding="utf-8")
        for entry in ({**self.entry, "source_repair": sources.ACTION_PROFILE},
                      {**self.entry, "path": ".github/security/actions/setup-node/package.json"},
                      {**self.entry, "lock": ".github/security/actions/setup-node/package-lock.json"},
                      {**self.entry, "derived_bundle": "npm"}):
            with self.subTest(entry=entry), self.assertRaises((SecurityError, OSError)):
                self.verify_source(entry)
        unselected = {key: value for key, value in self.entry.items() if key != "source_repair"}
        with self.assertRaises(SecurityError):
            self.verify_source(unselected)
        owner = json.loads(read_file(self.root, self.entry["path"]))
        lock = json.loads(read_file(self.root, self.entry["lock"]))
        foreign_owner = copy.deepcopy(owner)
        foreign_owner["devDependencies"]["deepmerge"] = "4.3.1"
        foreign_lock = copy.deepcopy(lock)
        foreign_lock["packages"]["node_modules/deepmerge"]["dev"] = False
        for candidate_owner, candidate_lock in ((foreign_owner, lock), (owner, foreign_lock)):
            with self.assertRaises(SecurityError):
                sources.action_source_inputs(self.root, self.entry, candidate_owner, candidate_lock)

    def test_runtime_action_graph_refuses_wrong_revision_or_nested_source(self):
        self.assertEqual(len(self.action_graph()), 1)
        action_path = self.root / ".github/security/actions.json"
        baseline = json.loads(action_path.read_bytes())
        for change in ("entrypoint", "verifier", "revision"):
            with self.subTest(change=change):
                policy = copy.deepcopy(baseline)
                row = policy["actions"][sources.BCA_REFERENCE]
                if change == "entrypoint":
                    row["files"][0]["source"] = "action.yml"
                elif change == "verifier":
                    row["files"][-1]["source"] = "other.mjs"
                else:
                    row["revision"] = "0" * 40
                action_path.write_text(json.dumps(policy), encoding="utf-8")
                with self.assertRaises(SecurityError):
                    security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_exact_source_does_not_modify_archived_evidence(self):
        archived = read_file(ROOT, "tools/ci/history/c-guest-closed-filesystem.yml")
        self.assertEqual(hashlib.sha256(archived).hexdigest(),
                         "8fffe0b896cc4709043da9679cb76dc522d7aeb204bccf48e7720c95be2ef3be")
        old = b"KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup@9244ec9f4725400c84054e3e6ec97514cadddf53"
        self.assertIn(old, archived)
        active = [path.read_bytes() for path in (ROOT / ".github/workflows").glob("*.yml")]
        self.assertTrue(any(sources.BCA_REFERENCE.encode() in raw for raw in active))
        self.assertFalse(any(old in raw for raw in active))


if __name__ == "__main__":
    unittest.main()
