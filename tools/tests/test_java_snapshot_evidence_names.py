"""Real exclusive evidence/filesystem controls; native snapshot calls are mocked."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tools.java_transaction_qualification import configuration as cfg
from tools.java_transaction_qualification import evidence, offline_campaign, pending_campaign


def stopped_report():
    # Synthetic closed-owner facts exercise the production validator; these
    # source-only controls do not prove physical/native retirement themselves.
    report = {name: 0 for name in (
        "activeConnections", "activeRpcs", "activeControlJobs", "activeActivations",
        "cancellationRegistrations", "observerCorrelations", "quotaReservations", "queuedReservations",
        "reservedCpuFuel", "reservedMemoryBytes", "activeLeases", "queuedActivations", "quarantinedCells",
        "activeBackendInvocations", "instanceReservations", "preparingComponents", "liveStores",
        "liveHostStates", "liveInstances", "liveTemporaryBuffers", "liveCancellationProbes")}
    state = {name: 0 for name in (
        "liveStorageWorkers", "liveStorageOwners", "queuedStorageRetirements", "acceptedStorageJobs",
        "storageRetainedBytes", "ordinaryNativeReservations", "recoveryNativeReservations",
        "ordinaryNativeBytes", "recoveryNativeBytes", "namespaceOwners")}
    state.update(clean=True, quarantined=False, storePhysicallyRetired=True, nativePhysicallyRetired=True)
    report.update(clean=True, state=state)
    return report


class SnapshotEvidenceNames(unittest.TestCase):
    @contextmanager
    def fixture(self, *, pending=False, current=True):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            scope = work / "recovery"
            scope.mkdir(mode=0o700)
            collector = evidence.Evidence(work / "evidence")
            client = SimpleNamespace(evidence=collector, directory=work / "client", node=None,
                deadline=time.monotonic() + 30, cancellation=SimpleNamespace(check=Mock()))
            client.directory.mkdir(mode=0o700)
            node = SimpleNamespace(process=None, shutdown=[{"reaped": True, "record": {
                "event": "stopped", "clean": True, "report": stopped_report()}}])
            cls = pending_campaign.PendingCampaign if pending else offline_campaign.OfflineCampaign
            subject = cls.__new__(cls)
            subject.current_v2, subject.directory, subject.client, subject.node = current, scope, client, node
            def native_shape(request):
                return {"snapshotDigest": "sha256:" + "1" * 64, "manifestDigest": "sha256:" + "2" * 64,
                    "manifest": {"metadata": {"tenant": cfg.TENANT, "operator_id": cfg.OPERATOR,
                        "operation_id": request["operationId"], "runtime_digest": "sha256:" + "3" * 64,
                        "decoder_formats": [], "required_artifacts": []}}}
            subject.action = Mock(side_effect=native_shape)
            yield subject, scope, collector

    def label(self, operation):
        return "snapshot-root-" + hashlib.sha256(operation.encode("ascii")).hexdigest() + ".json"

    def test_two_real_snapshots_keep_distinct_exclusive_records_and_original_operations(self):
        for pending in (False, True):
            with self.subTest(pending=pending), self.fixture(pending=pending) as (subject, scope, collector):
                operations = ("java-schema-checkpoint", "java-restore-checkpoint")
                first, _ = subject.snapshot("schema-checkpoint-v1.snapshot", operations[0])
                original_bytes = (collector.directory / self.label(operations[0])).read_bytes()
                second, _ = subject.snapshot("restore-checkpoint-v2.snapshot", operations[1])
                self.assertEqual((collector.directory / self.label(operations[0])).read_bytes(), original_bytes)
                self.assertEqual(set(p.name for p in collector.directory.iterdir()),
                                 {self.label(operation) for operation in operations})
                self.assertNotEqual(first["root"], second["root"])
                for operation, file in zip(operations, (first, second)):
                    receipt = json.loads((collector.directory / self.label(operation)).read_bytes())
                    self.assertEqual(receipt["operationId"], operation)
                    self.assertEqual(receipt["directoriesCreated"], 1)
                    self.assertEqual(receipt["durableFilesCreated"], 0)
                    self.assertIs(receipt["currentAuthorityInferred"], False)
                    root = Path(file["root"])
                    self.assertEqual(root, scope / ("snapshot-" + operation))
                    self.assertEqual(list(root.iterdir()), [])
                    self.assertTrue(os.name != "posix" or stat.S_IMODE(root.stat().st_mode) == 0o700)
                self.assertEqual(subject.action.call_count, 2)
                self.assertEqual([call.args[0]["operationId"] for call in subject.action.call_args_list], list(operations))
                self.assertEqual(collector.summary()["cases"], [])

    def test_real_evidence_old_fixed_label_cannot_accept_two_snapshot_receipts(self):
        with self.fixture() as (_, _, collector):
            collector.record("snapshot-destination-directory", {"operationId": "java-schema-checkpoint"})
            path = collector.directory / "snapshot-destination-directory.json"
            raw, summary = path.read_bytes(), collector.summary()
            with self.assertRaises(FileExistsError):
                collector.record("snapshot-destination-directory", {"operationId": "java-restore-checkpoint"})
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(collector.summary(), summary)

    def test_repeated_same_operation_refuses_before_a_second_action_or_record(self):
        with self.fixture() as (subject, scope, collector):
            subject.snapshot("one.snapshot", "same-operation")
            summary = collector.summary()
            raw = (collector.directory / self.label("same-operation")).read_bytes()
            with self.assertRaisesRegex(ValueError, "fresh-scoped"):
                subject.snapshot("two.snapshot", "same-operation")
            self.assertEqual(collector.summary(), summary)
            self.assertEqual((collector.directory / self.label("same-operation")).read_bytes(), raw)
            self.assertEqual(list(scope.iterdir()), [scope / "snapshot-same-operation"])
            subject.action.assert_called_once()

    def test_maximum_and_uppercase_operations_preserve_case_within_evidence_cap(self):
        for operation in ("A" * 128, "Upper_Case.Operation-19"):
            with self.subTest(operation=operation), self.fixture() as (subject, _, collector):
                file, _ = subject.snapshot("original.snapshot", operation)
                label = self.label(operation)
                self.assertEqual(len(label), 83)
                self.assertIsNotNone(re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,95}", label))
                self.assertEqual(json.loads((collector.directory / label).read_bytes())["operationId"], operation)
                self.assertEqual(Path(file["root"]).name, "snapshot-" + operation)
                self.assertEqual(subject.action.call_args.args[0]["operationId"], operation)

    def test_malformed_or_overlong_operation_never_writes_or_calls_native(self):
        for operation in ("", "a" * 129, "bad/name", "bad name", "a\n", "\u00e9", "..", True, 1, None):
            with self.subTest(operation=operation), self.fixture() as (subject, scope, collector):
                with self.assertRaisesRegex(ValueError, "snapshot-directory-operation-identity"):
                    subject.snapshot("one.snapshot", operation)
                subject.action.assert_not_called()
                self.assertEqual(list(scope.iterdir()), [])
                self.assertEqual(collector.summary(), {"files": [], "bytes": 0, "cases": []})

    def test_live_or_unreaped_owner_refuses_before_directory_and_evidence(self):
        for kind in ("client", "process", "missing", "unreaped", "unclean", "retained-native"):
            with self.subTest(kind=kind), self.fixture() as (subject, scope, collector):
                if kind == "client":
                    subject.client.node = object()
                elif kind == "process":
                    subject.node.process = object()
                elif kind == "missing":
                    subject.node.shutdown = []
                elif kind == "unreaped":
                    subject.node.shutdown[-1]["reaped"] = False
                elif kind == "unclean":
                    subject.node.shutdown[-1]["record"]["clean"] = False
                else:
                    subject.node.shutdown[-1]["record"]["report"]["state"]["recoveryNativeBytes"] = 1
                with self.assertRaises(ValueError):
                    subject.snapshot("one.snapshot", "operation")
                subject.action.assert_not_called()
                self.assertEqual(list(scope.iterdir()), [])
                self.assertEqual(collector.summary()["files"], [])

    def test_original_cutoff_and_cancellation_refuse_without_new_roots_or_receipts(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled), self.fixture() as (subject, scope, collector):
                if cancelled:
                    subject.client.cancellation.check.side_effect = RuntimeError("cancelled")
                    expected = RuntimeError
                else:
                    subject.client.deadline = time.monotonic() - 1
                    expected = ValueError
                with self.assertRaises(expected):
                    subject.snapshot("one.snapshot", "operation")
                subject.action.assert_not_called()
                self.assertEqual(list(scope.iterdir()), [])
                self.assertEqual(collector.summary()["files"], [])

    def test_existing_hashed_receipt_stays_exclusive_and_empty_failed_root_is_retained(self):
        with self.fixture() as (subject, scope, collector):
            name = self.label("operation")
            collector.write(name, b"original-failed-evidence")
            before = collector.summary()
            with self.assertRaises(FileExistsError):
                subject.snapshot("one.snapshot", "operation")
            self.assertEqual((collector.directory / name).read_bytes(), b"original-failed-evidence")
            self.assertEqual(collector.summary(), before)
            self.assertEqual(list((scope / "snapshot-operation").iterdir()), [])
            subject.action.assert_not_called()

    def test_native_failure_keeps_exact_record_and_never_retries_original_action(self):
        with self.fixture() as (subject, scope, collector):
            subject.action.side_effect = RuntimeError("native mock failed")
            with self.assertRaisesRegex(RuntimeError, "native mock failed"):
                subject.snapshot("one.snapshot", "operation")
            self.assertEqual(len(collector.summary()["files"]), 1)
            self.assertEqual(json.loads((collector.directory / self.label("operation")).read_bytes())["operationId"], "operation")
            self.assertEqual(list((scope / "snapshot-operation").iterdir()), [])
            subject.action.assert_called_once()

    def test_legacy_snapshot_keeps_original_path_without_directory_receipt(self):
        with self.fixture(current=False) as (subject, scope, collector):
            file, _ = subject.snapshot("legacy.snapshot", "legacy-operation")
            self.assertEqual(file, {"root": str(scope), "name": "legacy.snapshot"})
            self.assertEqual(list(scope.iterdir()), [])
            self.assertEqual(collector.summary(), {"files": [], "bytes": 0, "cases": []})
            subject.action.assert_called_once_with({"action": "snapshot", "operationId": "legacy-operation", "file": file})


if __name__ == "__main__":
    unittest.main()
