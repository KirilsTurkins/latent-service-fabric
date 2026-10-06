"""A provider marker failure retains its original invocation before cleanup."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import capsule_provider_diagnostics as diagnostic
from tools.phase2_operator_process import Client, WorkflowError
from tools.rust_capsule_cases import rendezvous
from tools.rust_capsule_node import RecordingClient


class ProviderDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.control = self.root / "peer"
        self.control.mkdir()
        (self.control / "mode").write_bytes(b"hold-cancel")
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.commands = []
        self.client = SimpleNamespace(
            evidence=self.evidence, retained=0, deadline=100,
            cancellation=SimpleNamespace(check=Mock()), node=SimpleNamespace(drain=Mock()),
            _control_call=self.control_call,
        )
        self.process = SimpleNamespace(
            authoring_activation="authoring-cancel", authoring_started_unix_millis=5000,
            buffers=[bytearray(b'{"category":"platform-failure","outcomeKnown":true}'), bytearray(b"stderr\n")],
            streams=[None, None], closed=False, drain=Mock(), close=Mock(), complete=Mock(),
            owner=SimpleNamespace(exited=Mock(return_value=True), finished=False,
                                  process=SimpleNamespace(returncode=None)),
        )

    def control_call(self, *arguments, **kwargs):
        self.commands.append((arguments, kwargs))
        self.assertFalse(self.process.closed)
        self.process.close.assert_not_called()
        self.process.complete.assert_not_called()
        return {"schemaVersion": "latent.cli.result.v1", "category": "success",
                "outcomeKnown": True, "data": {"original": list(arguments)}}

    def receipt(self):
        return json.loads((self.evidence / "provider-rendezvous-failure.json").read_text())

    def fail_rendezvous(self):
        with patch("tools.rust_capsule_cases.time.monotonic", side_effect=(0, 3)):
            with self.assertRaisesRegex(WorkflowError, "^authoring-provider-rendezvous$"):
                rendezvous(self.client, self.control, "started-hold-cancel", process=self.process)

    def test_original_deadline_failure_captures_before_cleanup_and_reads_only_same_activation(self):
        self.fail_rendezvous()
        value = self.receipt()
        self.assertEqual(value["activation"], "authoring-cancel")
        self.assertEqual(self.process.drain.call_count, 3)
        self.process.close.assert_not_called()
        self.process.complete.assert_not_called()
        self.assertEqual([arguments for arguments, _ in self.commands], [
            ("activation", "get", "authoring-cancel"),
            ("activation", "tree", "authoring-cancel", "--page-size", "128"),
            ("node", "get", diagnostic.NODE_ID),
            ("capability", "list", "--page-size", "128"),
        ])
        self.assertTrue(all(kwargs == {"codes": diagnostic.CODES} for _, kwargs in self.commands))
        self.assertFalse(value["outcomeInferred"])
        self.assertTrue(value["invocation"]["leaderExitObserved"])
        self.assertIsNone(value["invocation"]["exitCode"])
        self.assertEqual(base64.b64decode(value["invocation"]["stdoutBase64"]), bytes(self.process.buffers[0]))
        self.assertEqual(base64.b64decode(value["invocation"]["stderrBase64"]), b"stderr\n")
        self.assertFalse(value["markers"]["started-hold-cancel"]["present"])

    def test_success_retains_original_marker_oracle_and_performs_no_diagnostic_io(self):
        (self.control / "started-hold-cancel").write_bytes(b"observed\n")
        with patch("tools.rust_capsule_cases.time.monotonic", return_value=0):
            rendezvous(self.client, self.control, "started-hold-cancel", process=self.process)
        self.assertEqual(self.commands, [])
        self.process.drain.assert_not_called()
        self.assertFalse((self.evidence / "provider-rendezvous-failure.json").exists())

    def test_missing_marker_live_process_remains_unknown_without_waiting_or_reaping(self):
        self.process.owner.exited.return_value = False
        self.process.streams = [object(), object()]
        self.process.buffers = [bytearray(), bytearray()]
        self.fail_rendezvous()
        value = self.receipt()["invocation"]
        self.assertFalse(value["leaderExitObserved"])
        self.assertFalse(value["pipesClosed"])
        self.assertFalse(value["processReaped"])
        self.assertIsNone(value["exitCode"])
        self.process.complete.assert_not_called()

    def test_wrong_marker_preserves_original_failure_and_original_observed_bytes(self):
        (self.control / "started-hold-cancel").write_bytes(b"wrong\n")
        with patch("tools.rust_capsule_cases.time.monotonic", return_value=0):
            with self.assertRaisesRegex(WorkflowError, "^authoring-provider-marker$"):
                rendezvous(self.client, self.control, "started-hold-cancel", process=self.process)
        marker = self.receipt()["markers"]["started-hold-cancel"]
        self.assertTrue(marker["present"])
        self.assertFalse(marker["observed"])
        self.assertEqual(marker["bytes"], 6)

    def test_read_failure_preserves_first_failure_and_redacts_exception_text(self):
        self.client._control_call = Mock(side_effect=RuntimeError("private credentials"))
        self.fail_rendezvous()
        value = self.receipt()
        self.assertEqual(value["diagnosticFailure"], "RuntimeError")
        self.assertEqual(value["management"], {})
        self.assertNotIn("private credentials", json.dumps(value))
        self.assertEqual(self.client._control_call.call_count, 1)

    def test_oversized_management_output_is_rejected_without_overwriting_original_snapshot(self):
        self.client._control_call = Mock(return_value={"body": "x" * diagnostic.MAX_BYTES})
        self.fail_rendezvous()
        value = self.receipt()
        self.assertEqual(value["diagnosticFailure"], "WorkflowError")
        self.assertEqual(value["management"], {})
        self.assertLess((self.evidence / "provider-rendezvous-failure.json").stat().st_size, diagnostic.MAX_BYTES)
        self.assertFalse(value["outcomeInferred"])

    def test_process_output_bound_and_foreign_marker_cannot_start_diagnostic_controls(self):
        self.process.buffers[0] = bytearray(b"x" * (diagnostic.MAX_PROCESS_BYTES + 1))
        self.fail_rendezvous()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.receipt()["diagnosticFailure"], "WorkflowError")
        (self.evidence / "provider-rendezvous-failure.json").unlink()
        self.process.buffers[0] = bytearray()
        (self.control / "started-hold-deadline").mkdir()
        self.fail_rendezvous()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.receipt()["diagnosticFailure"], "WorkflowError")

    def test_original_exhausted_control_budget_never_starts_a_management_process(self):
        self.client = RecordingClient("unused", self.root, self.client.cancellation, 100,
                                      evidence=self.root / "bounded-evidence")
        self.client.node = SimpleNamespace(drain=Mock())
        self.client.calls = 384
        self.evidence = self.client.evidence
        with patch.object(Client, "call", side_effect=AssertionError("unexpected process")) as original:
            self.fail_rendezvous()
        original.assert_not_called()
        self.assertEqual(self.client.control_attempts, 0)
        self.assertEqual(self.receipt()["diagnosticFailure"], "WorkflowError")
        self.assertEqual(self.receipt()["management"], {})

    def test_exhausted_original_retention_and_interrupted_diagnostics_never_replace_failure(self):
        self.client.retained = 4 * 1024 * 1024
        self.fail_rendezvous()
        self.assertFalse((self.evidence / "provider-rendezvous-failure.json").exists())
        with patch("tools.capsule_provider_diagnostics.capture", side_effect=KeyboardInterrupt):
            self.fail_rendezvous()

    def test_closed_marker_wait_has_no_invocation_collector(self):
        with patch("tools.rust_capsule_cases.time.monotonic", side_effect=(0, 3)):
            with self.assertRaisesRegex(WorkflowError, "^authoring-provider-rendezvous$"):
                rendezvous(self.client, self.control, "closed-hold-cancel")
        self.assertEqual(self.commands, [])
        self.process.drain.assert_not_called()

    def test_original_peer_exit_is_retained_without_closing_or_reaping_either_owner(self):
        peer = SimpleNamespace(
            buffers=[bytearray(), bytearray(b"sdk-provider-fixture-failed\n")],
            streams=[None, None], closed=False, drain=Mock(), close=Mock(), complete=Mock(),
            owner=SimpleNamespace(exited=Mock(return_value=True), finished=False,
                                  process=SimpleNamespace(returncode=None)),
        )
        with patch("tools.rust_capsule_cases.time.monotonic", side_effect=(0, 3)):
            with self.assertRaisesRegex(WorkflowError, "^authoring-provider-rendezvous$"):
                rendezvous(self.client, self.control, "started-hold-cancel", process=self.process, peer=peer)
        value = self.receipt()["peer"]
        self.assertEqual(base64.b64decode(value["stderrBase64"]), b"sdk-provider-fixture-failed\n")
        self.assertTrue(value["leaderExitObserved"])
        self.assertFalse(value["processReaped"])
        self.assertIsNone(value["exitCode"])
        peer.close.assert_not_called()
        peer.complete.assert_not_called()
        self.process.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
