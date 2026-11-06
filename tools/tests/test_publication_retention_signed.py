"""Fail-closed selection/receipt controls for the disposable signed-node owner.

These controls do not stand in for running the signed node or stopped restore.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from tools.phase2_operator_process import WorkflowError
from tools.run_publication_retention_signed import (
    assert_hidden, audit_attempts, checked_receipt, copy_stopped_installation, lookup, selected,
)

PUBLICATION = "publication:sha256:" + "1" * 64
FENCE = "ab" * 32
TARGET = {"publication": {"tenant": "tests", "id": PUBLICATION}, "expectedGeneration": "2"}


def mutation():
    return {"category": "success", "outcomeKnown": True, "data": {
        "replay": False, "auditAck": {"status": "AUDIT_ACK_STATUS_DURABLE", "attemptSequence": "7"},
        "receipt": {"tenant": "tests", "actor": {"subject": "workflow-operator"},
                    "stage": "visibility-removed", "command": {
                        "kind": "PUBLICATION_MAINTENANCE_KIND_DELETE",
                        "selection": {"operationId": "delete-green", "catalogFence": FENCE, "targets": [TARGET]}}}}}


class Reply:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def call(self, *arguments):
        self.calls.append(arguments)
        return copy.deepcopy(self.value)


class ControlTests(unittest.TestCase):
    def test_snapshot_requires_one_exact_tenant_publication_generation_and_fence(self):
        data = {"tenant": "tests", "catalogFence": FENCE, "entries": [{"target": TARGET, "pin": None}]}
        client = Reply({"data": data})
        self.assertEqual(selected(client, PUBLICATION), (FENCE, TARGET, None))
        self.assertEqual(client.calls, [("release", "retention", "snapshot", "--publication", PUBLICATION)])
        corruptions = []
        for path, value in (("tenant", "other"), ("catalogFence", "00"), ("entries", [])):
            changed = copy.deepcopy(data)
            changed[path] = value
            corruptions.append(changed)
        for path, value in (("expectedGeneration", "0"), ("expectedGeneration", "18446744073709551616"),
                            ("publication", {"tenant": "other", "id": PUBLICATION})):
            changed = copy.deepcopy(data)
            changed["entries"][0]["target"][path] = value
            corruptions.append(changed)
        for bad in corruptions:
            with self.subTest(bad=bad), self.assertRaises(WorkflowError):
                selected(Reply({"data": bad}), PUBLICATION)

    def test_receipt_requires_original_actor_selection_kind_and_durable_audit(self):
        valid = mutation()
        original = checked_receipt(valid, "delete", "visibility-removed", "delete-green", FENCE, TARGET)
        self.assertEqual(original, valid["data"]["receipt"])
        bad = []
        for parent, field, value in ((valid["data"], "replay", True),
                                     (valid["data"]["auditAck"], "status", "AUDIT_ACK_STATUS_OUTCOME_UNKNOWN"),
                                     (valid["data"]["receipt"]["actor"], "subject", "other"),
                                     (valid["data"]["receipt"]["command"], "kind", "PUBLICATION_MAINTENANCE_KIND_PIN"),
                                     (valid["data"]["receipt"]["command"]["selection"], "catalogFence", "cd" * 32)):
            snapshot = copy.deepcopy(valid)
            try:
                previous = parent[field]
                parent[field] = value
                bad.append(copy.deepcopy(valid))
            finally:
                parent[field] = previous
            self.assertEqual(valid, snapshot)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                checked_receipt(value, "delete", "visibility-removed", "delete-green", FENCE, TARGET)

    def test_original_lookup_rejects_wrong_receipt_unknown_or_automatic_replay(self):
        receipt = mutation()["data"]["receipt"]
        data = {"tenant": "tests", "disposition": "RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND",
                "receipt": receipt, "automaticReplay": False}
        lookup(Reply({"outcomeKnown": True, "data": data}), "delete", "delete-green", receipt)
        for key, value in (("tenant", "other"), ("disposition", "RELEASE_OPERATION_LOOKUP_DISPOSITION_UNKNOWN"),
                           ("receipt", None), ("automaticReplay", True)):
            bad = copy.deepcopy(data)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                lookup(Reply({"outcomeKnown": True, "data": bad}), "delete", "delete-green", receipt)

    def test_removed_publication_must_remain_hidden_like_an_unknown_publication(self):
        class Client:
            def __init__(self, values):
                self.values = iter(values)

            def call(self, *_args, **_kwargs):
                return next(self.values)

        missing = {"category": "not-found", "error": {"code": "not-found"}}
        assert_hidden(Client([missing, missing]), PUBLICATION)
        with self.assertRaises(WorkflowError):
            assert_hidden(Client([{"category": "success"}, missing]), PUBLICATION)
        with self.assertRaises(WorkflowError):
            assert_hidden(Client([{"category": "not-found", "error": {"code": "other"}}, missing]), PUBLICATION)

    def test_restored_audit_requires_each_original_committed_attempt_and_outcome(self):
        expected = {"1": ("pin-blue", "AUDIT_CONTROL_ACTION_PUBLICATION_PIN"),
                    "3": ("delete-green", "AUDIT_CONTROL_ACTION_PUBLICATION_DELETE"),
                    "5": ("delete-green", "AUDIT_CONTROL_ACTION_PUBLICATION_RECLAIM")}
        rows = []
        for sequence, (operation, action) in expected.items():
            rows.append({"sequence": sequence, "actor": {"subject": "workflow-operator"},
                         "data": {"attempt": {"operationId": operation, "action": action, "replay": False}}})
            rows.append({"sequence": str(int(sequence) + 1), "data": {"outcome": {
                "attemptSequence": sequence, "result": "AUDIT_OPERATION_RESULT_COMMITTED", "replay": False}}})

        class Client:
            def __init__(self, records):
                self.records = records

            def call(self, *_args):
                return {"data": {"records": copy.deepcopy(self.records), "page": {"nextPageToken": None}}}

        self.assertEqual(audit_attempts(Client(rows), expected)["committedAttemptSequences"], ["1", "3", "5"])
        for index, field, value in ((0, "action", "AUDIT_CONTROL_ACTION_PUBLICATION_DELETE"),
                                    (1, "result", "AUDIT_OPERATION_RESULT_UNKNOWN"),
                                    (3, "replay", True)):
            bad = copy.deepcopy(rows)
            key = "attempt" if index % 2 == 0 else "outcome"
            bad[index]["data"][key][field] = value
            with self.subTest(index=index), self.assertRaises(WorkflowError):
                audit_attempts(Client(bad), expected)
        with self.assertRaises(WorkflowError):
            audit_attempts(Client(rows[:-1]), expected)


class CoupledCopyTests(unittest.TestCase):
    class Cancellation:
        def check(self):
            pass

    def test_linux_copy_or_explicit_non_linux_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            source, restored = work / "node", work / "restored"
            (source / "data/releases").mkdir(parents=True)
            (source / "data/audit").mkdir()
            client = type("Client", (), {"cancellation": self.Cancellation(), "deadline": time.monotonic() + 10})()
            if sys.platform != "linux":
                with self.assertRaisesRegex(WorkflowError, "restore-requires-linux"):
                    copy_stopped_installation(source, restored, client)
                return
            payload = source / "data/releases/blob"
            payload.write_bytes(b"signed fixture payload")
            payload.chmod(0o600)
            os.link(payload, source / "data/releases/shared")
            (source / "data/audit/record").write_bytes(b"original receipt")
            report, _inventory = copy_stopped_installation(source, restored, client)
            self.assertTrue(report["contentModesAndHardlinksVerified"])
            self.assertEqual((restored / "data/audit/record").read_bytes(), b"original receipt")
            self.assertEqual((restored / "data/releases/blob").stat().st_ino,
                             (restored / "data/releases/shared").stat().st_ino)
            self.assertEqual((restored / "data/releases/blob").stat().st_mode & 0o777, 0o600)

    def test_linux_path_refusals_or_explicit_non_linux_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            source = work / "node"
            source.mkdir()
            client = type("Client", (), {"cancellation": self.Cancellation(), "deadline": time.monotonic() + 10})()
            if sys.platform != "linux":
                with self.assertRaisesRegex(WorkflowError, "restore-requires-linux"):
                    copy_stopped_installation(source, work / "restored", client)
                return
            (source / "target").write_bytes(b"target")
            (source / "link").symlink_to(source / "target")
            with self.assertRaises(WorkflowError):
                copy_stopped_installation(source, work / "restored", client)
            with self.assertRaises(WorkflowError):
                copy_stopped_installation(source, work / "nested" / "restored", client)


if __name__ == "__main__":
    unittest.main()
