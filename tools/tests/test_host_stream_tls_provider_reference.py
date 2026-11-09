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
    def test_original_node_epoch_stops_before_each_following_stage(self):
        prefix = 'kernel::native::node_bootstrap::controls::'
        required = {prefix + name for name in (
            'node_epoch_retired_during_open_refuses_attach_and_keeps_original_escrow',
            'node_epoch_retired_during_attach_refuses_prepare_and_keeps_original_escrow',
            'node_epoch_retired_during_prepare_refuses_prefix_and_keeps_original_escrow',
            'node_uncertain_attach_after_retirement_keeps_original_error_and_escrow',
        )}
        self.assertTrue(required <= reference.NODE_CASES <= reference.REQUIRED_CASES)
        for case in required:
            with self.subTest(missing=case), self.assertRaisesRegex(ValueError, 'required-case-missing'):
                reference.validate_obligations(reference.REQUIRED_CASES - {case}, frozenset())
            with self.subTest(ignored=case), self.assertRaisesRegex(ValueError, 'required-case-missing'):
                reference.validate_obligations(reference.REQUIRED_CASES, frozenset({case}))

    def test_real_catalogue_keeps_public_refusal_and_activates_all_four_tls_controls(self):
        row = reference.suite_contract(reference.provider.ROOT)
        self.assertEqual(len(reference.TLS_CASES), 4)
        self.assertIn(reference.DENIAL, reference.REQUIRED_CASES)
        self.assertEqual(row["timeoutSeconds"], 900)
        self.assertEqual(row["expectedIgnored"], [])
        self.assertEqual(row["ignoredLeaves"], [])
        reference.validate_obligations(reference.REQUIRED_CASES | {"ordinary::new"}, frozenset())
        for missing in reference.NATIVE_CLOSE_CASES | reference.NODE_CASES:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "required-case-missing"):
                reference.validate_obligations(reference.REQUIRED_CASES - {missing}, frozenset())

    def test_maximum_valid_and_last_physical_trust_owner_cases_are_mandatory(self):
        for missing in reference.ACCOUNTING_CASES:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "required-case-missing"):
                reference.validate_obligations(reference.REQUIRED_CASES - {missing}, frozenset())

    def test_tcp_and_tls_abort_controls_cannot_be_missing_or_ignored(self):
        required = {
            "tests::sockets::abort_both_wakes_read_and_keeps_the_held_write_owner_until_drop",
            "tests::sockets::abort_both_is_available_after_the_send_half_was_closed",
            "tests::sockets::abort_both_unpolled_reserves_control_and_blocks_new_send_without_dispatch",
            "tests::sockets::abort_both_cancels_an_accepted_send_shutdown_owner",
            "tests::sockets::dropped_write_before_dispatch_keeps_the_same_connection_usable",
            "tests::sockets::dropped_write_after_synthetic_no_progress_keeps_the_same_connection_usable",
            "tests::sockets::dropped_write_during_synthetic_audit_wait_keeps_original_owners_and_never_replays",
            "tests::sockets::synthetic_audit_failure_reports_the_accepted_prefix_once_and_fences_reuse",
            "tests::tls::abort::abort_both_wakes_tls_waiters_and_retains_held_write",
            "tests::tls::abort::abort_both_unpolled_tls_control_releases_slot_without_dispatch",
            "tests::tls::abort::abort_both_after_tls_peer_close_notify_retires_original_owner",
            "tests::tls::abort::abort_both_cancels_tls_ciphertext_flush_under_real_backpressure",
            "tests::tls::abort::dropped_write_with_synthetically_held_tls_ciphertext_retains_original_owners",
        }
        self.assertTrue(required <= reference.ABORT_CASES <= reference.REQUIRED_CASES)
        for missing in reference.ABORT_CASES:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "required-case-missing"):
                reference.validate_obligations(reference.REQUIRED_CASES - {missing}, frozenset())
            with self.subTest(ignored=missing), self.assertRaisesRegex(ValueError, "required-case-missing"):
                reference.validate_obligations(reference.REQUIRED_CASES, frozenset({missing}))

    def test_summary_reports_the_actual_receipt_case_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            arguments = ["qualify", "--output", temporary, "--source-commit", "a" * 40]
            with patch.object(reference.sys, "argv", arguments), \
                    patch.object(reference, "qualify", return_value={"cases": ["one", "two"]}), \
                    patch("builtins.print") as output:
                self.assertEqual(reference.main(), 0)
            output.assert_called_once_with(
                "Actual bounded TLS provider: 2 cases passed; accounting remains unqualified")

    def test_kernel_tail_witness_cannot_be_replaced_with_a_logical_drop_substitute(self):
        with self.assertRaisesRegex(ValueError, "required-case-missing"):
            reference.validate_obligations(reference.REQUIRED_CASES - {reference.KERNEL_CASE}, frozenset())

    def test_partial_catalogue_changed_budget_or_ignored_controls_are_refused(self):
        original = reference.suite_contract(reference.provider.ROOT)
        for row in (dict(original, timeoutSeconds=901), dict(original, expectedIgnored=[reference.DENIAL]),
                    dict(original, ignoredLeaves=[reference.DENIAL.rsplit("::", 1)[-1]])):
            with self.subTest(row=row), patch.object(reference.registry, "load", return_value={"suites": [row]}), \
                    self.assertRaisesRegex(ValueError, "suite-contract"):
                reference.suite_contract(reference.provider.ROOT)
        with self.assertRaisesRegex(ValueError, "required-case-missing"):
            reference.validate_obligations(reference.REQUIRED_CASES, frozenset({reference.DENIAL}))

    def test_only_all_exact_named_zero_filtered_successes_are_evidence(self):
        cases = set(reference.REQUIRED_CASES) | {"ordinary::new"}
        raw = ("\n".join("test " + name + " ... ok" for name in sorted(cases))
               + f"\ntest result: ok. {len(cases)} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.0s\n").encode()
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
