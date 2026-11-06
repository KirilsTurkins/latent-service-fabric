"""Adversarial controls for the six attest receipts and wrapper binding."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import security_actions, security_attest as attest, security_npm_sources as sources
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages
from tools.tests.test_sdk_scratch_qualification import historical_security_actions


class AttestSourceRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-attest-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {row[0] for row in attest.ACTION_INPUTS.values()}
        paths |= {attest.BUILD[0], attest.WRAPPER_BUILD[0], attest.WRAPPER_SNAPSHOT[0], ".github/security/actions.json"}
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(ROOT, name))
        self.entry = {"kind": "npm", "path": attest.PREFIX + "package.json", "lock": attest.PREFIX + "package-lock.json",
                      "source_repair": attest.PROFILE}
        self.runtime = {name: ("synthetic attest runtime " + name).encode() for name in attest.RUNTIME}
        identities = {name: sources.source_identity(value) for name, value in self.runtime.items()}
        build_path = self.root / attest.BUILD[0]
        build = json.loads(build_path.read_bytes())
        build["artifact"]["payloads"].update(identities)
        build_path.write_text(json.dumps(build), encoding="utf8")
        wrapper_path = self.root / attest.WRAPPER_BUILD[0]
        wrapper = json.loads(wrapper_path.read_bytes())
        wrapper["childDist"] = {name.removeprefix("dist/"): value for name, value in identities.items()}
        wrapper_path.write_text(json.dumps(wrapper), encoding="utf8")
        def bound(path, old):
            identity = sources.source_identity(path.read_bytes())
            return old[0], identity["bytes"], identity["sha256"], identity["gitBlob"]
        for name, value in (("RUNTIME", identities), ("BUILD", bound(build_path, attest.BUILD)),
                            ("WRAPPER_BUILD", bound(wrapper_path, attest.WRAPPER_BUILD))):
            patcher = patch.object(attest, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []

    def fetch(self, pin):
        pkg = next(row for row in attest.PACKAGES if row["name"] == pin["name"] and row["version"] == pin["version"])
        return read_file(self.root, attest.ACTION_INPUTS[".lsf-source/" + pkg["original"]][0])

    def runtime_fetch(self, reference, name):
        self.assertEqual(reference, attest.REFERENCE)
        self.calls.append(name)
        return self.runtime[name]

    def verify(self, entry=None, runtime=None, fetch=None):
        entry = self.entry if entry is None else entry
        packages = npm_packages(self.root, entry)
        return sources.verify_sources(self.root, packages, {"manifests": [entry]}, fetch or self.fetch,
                                      runtime or self.runtime_fetch)

    def action_graph(self):
        path = self.root / ".github/security/actions.json"
        policy = json.loads(path.read_bytes())
        policy["actions"] = {ref: policy["actions"][ref] for ref in (attest.WRAPPER_REFERENCE, attest.REFERENCE)}
        path.write_text(json.dumps(policy), encoding="utf8")
        workflow = self.root / ".github/workflows/fixture.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("jobs:\n  check:\n    steps:\n      - uses: " + attest.WRAPPER_REFERENCE + "\n", encoding="utf8")
        return security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_six_receipts_bind_both_actions_all_runtime_and_exact_advisory_revisions(self):
        receipts = self.verify()
        self.assertEqual({(row["name"], row["version"]) for row in receipts},
                         {(row["name"], row["version"]) for row in attest.PACKAGES})
        self.assertEqual(set(self.calls), set(attest.RUNTIME))
        self.assertTrue(all(row["action"] == attest.REFERENCE and row["locks"] == [self.entry["lock"]] for row in receipts))
        findings = [finding("osv", row["advisories"][0]["id"], self.entry["lock"],
                            "npm:" + row["name"] + "@" + row["version"]) for row in receipts]
        other = finding("osv", findings[0].finding, ".github/security/actions/other/package-lock.json", findings[0].package)
        observations = [{"advisories": [{"package": Package("npm", row["name"], row["version"], self.entry["lock"]).public(),
                                         **row["advisories"][0]} for row in receipts]}]
        self.assertEqual(sources.resolve_findings(findings + [other], observations, receipts), ([other], findings))
        for index in range(len(receipts)):
            changed = copy.deepcopy(observations)
            changed[0]["advisories"][index]["modified"] = "future-revision"
            self.assertEqual(sources.resolve_findings([findings[index]], changed, receipts), ([findings[index]], []))
        self.assertEqual(len(self.action_graph()), 2)

    def test_all_25_source_inputs_and_both_owner_receipts_refuse_tampering(self):
        inputs = {row[0] for row in attest.ACTION_INPUTS.values()} | {attest.BUILD[0], attest.WRAPPER_BUILD[0], attest.WRAPPER_SNAPSHOT[0]}
        action_path = self.root / ".github/security/actions.json"
        for snapshot in sorted(inputs):
            with self.subTest(snapshot=snapshot):
                target = self.root / snapshot
                before = target.read_bytes(); policy_before = action_path.read_bytes()
                altered = before + b"\n"
                target.write_bytes(altered)
                policy = json.loads(policy_before)
                for action in policy["actions"].values():
                    for row in action["files"]:
                        if row["snapshot"] == snapshot:
                            row["sha256"] = row["source_sha256"] = sources.digest(altered)
                    if action["metadata"]["snapshot"] == snapshot:
                        action["metadata"]["sha256"] = action["metadata"]["source_sha256"] = sources.digest(altered)
                action_path.write_text(json.dumps(policy), encoding="utf8")
                try:
                    with self.assertRaises((SecurityError, ValueError)):
                        self.verify()
                finally:
                    target.write_bytes(before); action_path.write_bytes(policy_before)

    def test_all_five_runtime_files_and_six_upstreams_are_required(self):
        for path in self.runtime:
            with self.subTest(runtime=path):
                def altered(reference, name):
                    raw = self.runtime_fetch(reference, name)
                    return raw + b"drift" if name == path else raw
                with self.assertRaises(SecurityError):
                    self.verify(runtime=altered)
        for pkg in attest.PACKAGES:
            with self.subTest(upstream=(pkg["name"], pkg["version"])), self.assertRaises(SecurityError):
                self.verify(fetch=lambda pin: self.fetch(pin) + (b"drift" if (pin["name"], pin["version"]) == (pkg["name"], pkg["version"]) else b""))
        with self.assertRaises(OSError):
            self.verify(runtime=lambda _ref, _path: (_ for _ in ()).throw(OSError("unavailable")))
        for reference, path in ((attest.REFERENCE, "dist/other.js"),
                                (attest.REFERENCE.replace("ac3d77be", "0c3d77be"), "dist/index.js")):
            with self.assertRaises(SecurityError):
                sources.action_runtime(reference, path)

    def test_duplicate_and_aliased_lock_copies_cannot_be_rebound(self):
        path = self.root / self.entry["lock"]
        action_path = self.root / ".github/security/actions.json"
        original, action_original = path.read_bytes(), action_path.read_bytes()
        for name, version in (("deepmerge", "4.3.1"), ("glob", "13.0.6"), ("minimatch", "10.2.6")):
            for alias in (False, True):
                with self.subTest(package=name, alias=alias):
                    lock = json.loads(original)
                    pkg = next(row for row in attest.PACKAGES if row["name"] == name and row["version"] == version)
                    copy_path = "node_modules/parent/node_modules/" + ("alias" if alias else name)
                    lock["packages"][copy_path] = copy.deepcopy(lock["packages"][pkg["targets"][0]])
                    if alias:
                        lock["packages"][copy_path]["name"] = name
                    path.write_text(json.dumps(lock), encoding="utf8")
                    identity = sources.source_identity(path.read_bytes())
                    bindings = copy.deepcopy(attest.ACTION_INPUTS)
                    bindings["package-lock.json"] = (self.entry["lock"], identity["bytes"], identity["sha256"], identity["gitBlob"])
                    policy = json.loads(action_original)
                    row = next(x for x in policy["actions"][attest.REFERENCE]["files"] if x["source"] == "package-lock.json")
                    row["sha256"] = row["source_sha256"] = identity["sha256"]
                    action_path.write_text(json.dumps(policy), encoding="utf8")
                    try:
                        with patch.object(attest, "ACTION_INPUTS", bindings), self.assertRaisesRegex(SecurityError, "attest-lock-graph-drift|attest-source-duplicate-or-alias"):
                            self.verify()
                    finally:
                        path.write_bytes(original); action_path.write_bytes(action_original)

    def test_glob13_reconstruction_requires_both_minified_entrypoints(self):
        pkg = next(row for row in attest.PACKAGES if (row["name"], row["version"]) == ("glob", "13.0.6"))
        pin = {"name": pkg["name"], "version": pkg["version"], "integrity": pkg["upstreamIntegrity"]}
        original = sources.members(self.fetch(pin))
        repair = json.loads(read_file(self.root, attest.ACTION_INPUTS[".lsf-source/" + pkg["repair"]][0]))
        fixed = attest._reconstruct(original, repair, pin)
        self.assertEqual(sources.distribution(fixed), read_file(self.root, attest.ACTION_INPUTS[".lsf-source/" + pkg["archive"]][0]))
        for removed in ("dist/commonjs/index.min.js", "dist/esm/index.min.js"):
            candidate = copy.deepcopy(repair)
            candidate["files"] = [row for row in candidate["files"] if row["path"] != removed]
            with self.subTest(removed=removed), self.assertRaisesRegex(SecurityError, "attest-repair-file-coverage"):
                attest._reconstruct(original, candidate, pin)

    def test_nested_action_and_wrapper_reject_stale_references_and_wrong_sources(self):
        self.assertEqual(len(self.action_graph()), 2)
        path = self.root / ".github/security/actions.json"
        baseline = json.loads(path.read_bytes())
        for kind in ("source", "stale_child", "stale_wrapper"):
            with self.subTest(kind=kind):
                policy = copy.deepcopy(baseline)
                if kind == "source":
                    policy["actions"][attest.REFERENCE]["files"][-1]["source"] = ".lsf-source/unreviewed"
                elif kind == "stale_child":
                    policy["actions"][attest.REFERENCE]["revision"] = "0" * 40
                else:
                    policy["actions"][attest.WRAPPER_REFERENCE]["revision"] = "0" * 40
                path.write_text(json.dumps(policy), encoding="utf8")
                with self.assertRaises(SecurityError):
                    security_actions.verify(self.root, [".github/workflows/fixture.yml"])

    def test_historical_wrapper_inverse_refuses_stale_mixed_and_future_pins(self):
        current = attest.WRAPPER_REFERENCE
        previous = current.replace("d67c304058531c46441ba89c83b3bbe075fd9d00", "16b356100dfe77222eebe783b5e26a565b76055a")
        future = current.replace("d67c304058531c46441ba89c83b3bbe075fd9d00", "0" * 40)
        for value in (current, current.encode()):
            self.assertEqual(historical_security_actions(value), previous if isinstance(value, str) else previous.encode())
        for value in (previous, current + "\n" + previous, future):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                historical_security_actions(value)


if __name__ == "__main__":
    unittest.main()
