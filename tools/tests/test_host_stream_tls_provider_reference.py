"""A real-provider witness cannot substitute a partial or differently built suite."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_host_stream_tls_provider as reference


class BoundedTlsProviderReference(unittest.TestCase):
    def test_real_catalogue_keeps_public_refusal_and_activates_all_four_tls_controls(self):
        row = reference.suite_contract(reference.provider.ROOT)
        self.assertEqual(len(row["expectedCases"]), 26)
        self.assertEqual(row["minimumCases"], 26)
        self.assertEqual(len(reference.TLS_CASES), 4)
        self.assertIn(reference.DENIAL, row["expectedCases"])
        self.assertEqual(row["timeoutSeconds"], 900)
        self.assertEqual(row["expectedIgnored"], [])
        self.assertEqual(row["ignoredLeaves"], [])

    def test_maximum_valid_and_last_physical_trust_owner_cases_are_mandatory(self):
        original = reference.suite_contract(reference.provider.ROOT)
        self.assertEqual(len(reference.ACCOUNTING_CASES), 2)
        self.assertTrue(reference.ACCOUNTING_CASES <= set(original["expectedCases"]))
        for missing in reference.ACCOUNTING_CASES:
            changed = dict(original, expectedCases=[
                "tests::unknown_accounting_substitute" if name == missing else name
                for name in original["expectedCases"]])
            with self.subTest(missing=missing), \
                    patch.object(reference.registry, "load", return_value={"suites": [changed]}), \
                    self.assertRaisesRegex(ValueError, "suite-contract"):
                reference.suite_contract(reference.provider.ROOT)

    def test_kernel_tail_witness_cannot_be_replaced_with_a_logical_drop_substitute(self):
        original = reference.suite_contract(reference.provider.ROOT)
        self.assertIn(reference.KERNEL_CASE, original["expectedCases"])
        changed = dict(original, expectedCases=[
            "tests::unknown_fd_only_substitute" if name == reference.KERNEL_CASE else name
            for name in original["expectedCases"]])
        with patch.object(reference.registry, "load", return_value={"suites": [changed]}), \
                self.assertRaisesRegex(ValueError, "suite-contract"):
            reference.suite_contract(reference.provider.ROOT)

    def test_partial_catalogue_changed_budget_or_ignored_controls_are_refused(self):
        original = reference.suite_contract(reference.provider.ROOT)
        variants = [dict(original, expectedCases=[n for n in original["expectedCases"] if n != reference.DENIAL]),
                    dict(original, minimumCases=19), dict(original, timeoutSeconds=901),
                    dict(original, expectedIgnored=[reference.DENIAL]),
                    dict(original, ignoredLeaves=[reference.DENIAL.rsplit("::", 1)[-1]])]
        for row in variants:
            with self.subTest(row=row), patch.object(reference.registry, "load", return_value={"suites": [row]}), \
                    self.assertRaisesRegex(ValueError, "suite-contract"):
                reference.suite_contract(reference.provider.ROOT)

    def test_only_all_exact_named_zero_filtered_successes_are_evidence(self):
        cases = set(reference.suite_contract(reference.provider.ROOT)["expectedCases"])
        raw = ("\n".join("test " + name + " ... ok" for name in sorted(cases))
               + "\ntest result: ok. 26 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.0s\n").encode()
        self.assertEqual(reference.outcomes(raw, cases), sorted(cases))
        first = sorted(cases)[0].encode()
        for changed in (raw.replace(first, b"unknown"), raw.replace(b" ... ok", b" ... FAILED", 1),
                        raw.replace(b"0 filtered out", b"1 filtered out"),
                        raw.replace(b"0 ignored", b"1 ignored"),
                        raw + b"test duplicate ... ok\n", raw[:raw.index(b"test result")],
                        b"x" * (4 * 1024 * 1024 + 1)):
            with self.subTest(bytes=len(changed)), self.assertRaises(ValueError):
                reference.outcomes(changed, cases)

    def test_exact_bounded_provider_and_separate_upstream_peer_are_both_compiled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            deps = target / "debug/deps"
            deps.mkdir(parents=True)
            records = []
            for label, package, manifest in (
                ("bounded", "path+file:///owned#latent-rustls-outbound@0.23.46", root / reference.provider.PROVIDER / "Cargo.toml"),
                ("peer", "registry+https://github.com/rust-lang/crates.io-index#rustls@0.23.46", root / "registry/rustls/Cargo.toml"),
            ):
                library = deps / ("librustls-" + label + ".rlib")
                library.write_bytes(label.encode())
                records.append({"reason": "compiler-artifact", "package_id": package,
                                "manifest_path": str(manifest), "target": {"name": "rustls", "kind": ["lib"]},
                                "filenames": [str(library)], "features": ["ring", "std", "tls12"]})
            inventory = root / "inventory.jsonl"

            def write(rows):
                inventory.write_bytes(b"".join((json.dumps(row) + "\n").encode() for row in rows))

            write(records)
            result = reference.compiled_tls(root, inventory, target)
            self.assertEqual(set(result), {"boundedProvider", "upstreamPeer"})
            self.assertEqual(result["boundedProvider"]["librarySha256"], hashlib.sha256(b"bounded").hexdigest())
            for kind in ("missing", "duplicate", "old-peer", "local-peer", "unreviewed-feature", "outside-target"):
                changed = copy.deepcopy(records)
                if kind == "missing":
                    changed.pop()
                elif kind == "duplicate":
                    changed.append(changed[0])
                elif kind == "old-peer":
                    changed[1]["package_id"] = changed[1]["package_id"].replace("0.23.46", "0.23.45")
                elif kind == "local-peer":
                    changed[1]["package_id"] = "path+file:///foreign#rustls@0.23.46"
                elif kind == "unreviewed-feature":
                    changed[0]["features"].append("aws_lc_rs")
                else:
                    changed[0]["filenames"] = [str(root / "foreign.rlib")]
                write(changed)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    reference.compiled_tls(root, inventory, target)

    def test_changed_source_identity_fails_before_output_or_any_native_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "not-created"
            with patch.object(reference.artifacts, "require_source"), \
                    patch.object(reference, "snapshot", side_effect=ValueError("changed-selected-source")), \
                    patch.object(reference, "run_owned", side_effect=AssertionError("no process")), \
                    self.assertRaisesRegex(ValueError, "changed-selected-source"):
                reference.qualify(reference.provider.ROOT, output, "a" * 40)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
