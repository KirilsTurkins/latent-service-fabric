"""Synthetic native receipt oracles; these do not qualify a signed Java guest."""
from __future__ import annotations

import copy
import json
import unittest

from tools.java_transaction_qualification import recovery


def observed():
    return {"schemaVersion": "latent.native-transaction-recovery.v1", "operationSucceeded": True,
            "failure": None, "result": {"action": "inspect-namespace"}, "catalogsRetired": True,
            "retirement": {"clean": True, "physicallyRetired": True, "liveWorkers": 0,
                           "acceptedJobs": 0, "threadsJoined": 4}}


class NativeRecoveryOracle(unittest.TestCase):
    def test_absent_client_node_and_elapsed_time_do_not_prove_native_retirement(self):
        from types import SimpleNamespace
        client = SimpleNamespace(node=None)
        node = SimpleNamespace(process=None, shutdown=[])
        with self.assertRaises(ValueError):
            recovery.require_stopped_owner(client, node)
        node.shutdown = [{"reaped": False, "record": {"event": "stopped", "clean": True}}]
        with self.assertRaises(ValueError):
            recovery.require_stopped_owner(client, node)
        node.process = object()
        with self.assertRaises(ValueError):
            recovery.require_stopped_owner(client, node)

    def test_success_receipt_requires_actual_physical_and_catalog_retirement(self):
        value = recovery.report(json.dumps(observed()).encode())
        self.assertEqual(recovery.require_success(value), {"action": "inspect-namespace"})
        for field, changed in (("physicallyRetired", False), ("liveWorkers", 1),
                               ("acceptedJobs", 1), ("threadsJoined", None)):
            invalid = copy.deepcopy(value)
            invalid["retirement"][field] = changed
            with self.assertRaises(ValueError):
                recovery.require_success(invalid)
        value["catalogsRetired"] = False
        with self.assertRaises(ValueError):
            recovery.require_success(value)

    def test_cleanup_failure_preserves_the_original_success_result(self):
        value = observed()
        value["retirement"]["clean"] = False
        value["catalogsRetired"] = False
        actual = recovery.report(json.dumps(value).encode())
        self.assertTrue(actual["operationSucceeded"])
        self.assertEqual(actual["result"], value["result"])
        with self.assertRaises(ValueError):
            recovery.require_success(actual)

    def test_commit_uncertain_is_not_changed_to_known_not_committed_after_retirement(self):
        value = observed()
        value.update(operationSucceeded=False, result=None,
                     failure={"stage": "target", "failure": {"owner": "storage", "reason": "commitUncertain"}})
        actual = recovery.report(json.dumps(value).encode())
        self.assertEqual(actual, value)
        self.assertNotIn("knownNotCommitted", actual)
        with self.assertRaises(ValueError):
            recovery.require_success(actual)

    def test_report_refuses_approval_fields_booleans_as_counts_and_duplicate_json_fields(self):
        for change in ({"approved": True}, {"operationSucceeded": 1}, {"catalogsRetired": 1}):
            value = dict(observed(), **change)
            with self.assertRaises(ValueError):
                recovery.report(json.dumps(value).encode())
        value = observed()
        value["retirement"]["acceptedJobs"] = True
        with self.assertRaises(ValueError):
            recovery.report(json.dumps(value).encode())
        raw = json.dumps(observed())[:-1] + ',"operationSucceeded":false}'
        with self.assertRaises(ValueError):
            recovery.report(raw.encode())
        for changed in ({"owner": "unknown", "reason": "commitUncertain"},
                        {"owner": "storage", "reason": "knownNotCommitted"},
                        {"owner": "storage", "reason": "corrupt", "path": "secret"}):
            value = observed()
            value.update(operationSucceeded=False, result=None,
                         failure={"stage": "target", "failure": changed})
            with self.assertRaises(ValueError):
                recovery.report(json.dumps(value).encode())

    def test_native_view_is_copied_exactly_and_never_reconstructed_as_current(self):
        view = list(b"NV\x02" + bytes([19]) * 32
                    + b"".join(value.to_bytes(8, "little") for value in (1, 2, 3, 4)))
        self.assertEqual(recovery.original_view(view), view)
        for invalid in (view[:-1], [True] + view[1:], [256] + view[1:],
                        view[:35] + [0] * 8 + view[43:]):
            with self.assertRaises(ValueError):
                recovery.original_view(invalid)

    def test_original_digest_refuses_unbounded_changed_encoding_and_zero_identity(self):
        value = "sha256:" + "a" * 64
        self.assertEqual(recovery.original_digest(value), value)
        for invalid in (value + "\n", value.upper(), "sha256:" + "0" * 64, "b3:" + "a" * 64):
            with self.assertRaises(ValueError):
                recovery.original_digest(invalid)

    def test_original_cli_generation_refuses_numeric_zero_unicode_and_overflow(self):
        from tools.java_transaction_qualification import offline_campaign
        self.assertEqual(offline_campaign.generation(str(2**64 - 1)), str(2**64 - 1))
        for value in (True, 1, "0", "01", "١", str(2**64), "1" * 100):
            with self.assertRaises(ValueError):
                offline_campaign.generation(value)

    def test_snapshot_keeps_original_native_manifest_and_refuses_changed_actor_scope_and_approval(self):
        from tools.java_transaction_qualification import configuration as cfg, offline_campaign
        value = {"snapshotDigest": "sha256:" + "a" * 64, "manifestDigest": "sha256:" + "b" * 64,
                 "manifest": {"metadata": {"tenant": cfg.TENANT, "operator_id": cfg.OPERATOR,
                     "operation_id": "original-operation", "runtime_digest": [1] * 32,
                     "decoder_formats": [], "required_artifacts": []}}}
        self.assertIs(offline_campaign.original_snapshot(value, "original-operation"), value)
        for field, changed in (("operator_id", "another-operator"), ("tenant", "foreign"),
                               ("operation_id", "later-operation"), ("approved", True)):
            invalid = copy.deepcopy(value)
            invalid["manifest"]["metadata"][field] = changed
            with self.assertRaises(ValueError):
                offline_campaign.original_snapshot(invalid, "original-operation")

    def test_native_epoch_advance_keeps_original_scope_incarnation_and_other_history(self):
        from tools.java_transaction_qualification import offline_campaign
        original = list(b"NV\x02" + bytes([19]) * 32
                        + b"".join(value.to_bytes(8, "little") for value in (1, 2, 3, 4)))
        changed = original[:51] + list((4).to_bytes(8, "little")) + original[59:]
        offline_campaign.epoch_advanced(original, changed, "schema")
        for invalid in (original, [0] + changed[1:],
                        changed[:35] + list((2).to_bytes(8, "little")) + changed[43:],
                        changed[:59] + list((5).to_bytes(8, "little"))):
            with self.assertRaises(ValueError):
                offline_campaign.epoch_advanced(original, invalid, "schema")
        with self.assertRaises(ValueError):
            offline_campaign.epoch_advanced(original, changed, "grant")

    def test_restored_selection_retains_catalogs_credentials_clock_and_quotas_without_mutating_original(self):
        from pathlib import Path
        import tempfile
        from tools.java_transaction_qualification import offline_campaign
        original = {"dataDirectory": "data", "providers": {"original": "selected"},
                    "credentials": [{"subject": "operator", "token": "synthetic-test"}],
                    "state": {"formatVersion": 1, "clockCheckpoint": "original-clock",
                              "configurationEpoch": 7, "createIfMissing": True,
                              "tenantQuotas": [{"tenant": "original"}], "operations": ["original"]}}
        retained = copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as root:
            selected = offline_campaign.restored_configuration(original, Path(root))
            self.assertEqual(selected["dataDirectory"], "data")
            self.assertEqual(selected["providers"], original["providers"])
            self.assertEqual(selected["credentials"], original["credentials"])
            self.assertFalse(selected["state"].pop("createIfMissing"))
            self.assertEqual(selected["state"].pop("stateRoot"), root)
            expected = dict(original["state"])
            expected.pop("createIfMissing")
            self.assertEqual(selected["state"], expected)
            for invalid in (Path("relative"), Path(root) / "missing", Path(root) / "../other"):
                with self.assertRaises(ValueError):
                    offline_campaign.restored_configuration(original, invalid)
        self.assertEqual(original, retained)

    def test_optional_recovery_tool_requires_paired_exact_original_native_source(self):
        from pathlib import Path
        import tempfile
        from types import SimpleNamespace
        from tools import run_java_transaction_http_qualification as conductor
        source = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-executable-not-invoked"
            path.write_bytes(b"not-runtime-evidence")
            args = SimpleNamespace(recovery_helper=path, recovery_source_commit=source, native_source_commit=source)
            conductor.recovery_input(args)
            for helper, identity in ((None, source), (path, None), (path, "b" * 40)):
                args.recovery_helper, args.recovery_source_commit = helper, identity
                with self.assertRaises(ValueError):
                    conductor.recovery_input(args)


if __name__ == "__main__":
    unittest.main()
