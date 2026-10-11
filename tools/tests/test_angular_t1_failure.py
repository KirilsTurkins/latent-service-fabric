"""Failure evidence and cleanup controls, not native Angular qualification."""
import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.phase2_operator_process import WorkflowError, failed_call_record
from tools.phase3_web_failure import CURRENTNESS_REASONS, failed_web_call, failure_observation
from tools import run_angular_t1_workflow as workflow


def rejected():
    return {"schemaVersion": "latent.cli.result.v1", "command": "web prepare",
            "category": "platform-failure", "outcomeKnown": False, "requestDispatched": True,
            "error": {"code": "unavailable", "message": "PRIVATE MESSAGE",
                      "details": [{"kind": "admission.currentness",
                                   "fields": {"reason": "admission-authority-busy"}}]}}


class AngularT1FailureTests(unittest.TestCase):
    def test_currentness_vocabulary_matches_original_producer_owned_codes(self):
        source = (Path(__file__).resolve().parents[2] / "crates/latent-core/src/error.rs").read_text(encoding="utf-8")
        block = source.split("pub const ADMISSION_CURRENTNESS_REASONS:", 1)[1].split("];", 1)[0]
        self.assertEqual(tuple(re.findall(r'"([a-z-]+)"', block)), CURRENTNESS_REASONS)

    def test_only_exact_typed_currentness_reason_is_retained_without_error_strings(self):
        value = rejected()
        record = failed_web_call(value, 107, 4)
        self.assertEqual(record["command"], "web prepare")
        self.assertEqual(record["currentnessReason"], "admission-authority-busy")
        self.assertEqual((record["call"], record["exitStatus"], record["publicCode"]), (107, 4, "unavailable"))
        self.assertNotIn("PRIVATE", json.dumps(record))
        self.assertEqual(value["error"]["message"], "PRIVATE MESSAGE")
        for detail in (
            {"kind": "admission.currentness", "fields": {"reason": "PRIVATE"}},
            {"kind": "admission.currentness", "fields": {"reason": "admission-authority-busy", "secret": "PRIVATE"}},
            {"kind": "PRIVATE", "fields": {"reason": "admission-authority-busy"}},
            {"kind": "admission.currentness", "fields": {"reason": ["PRIVATE"]}},
        ):
            value["error"]["details"] = [detail]
            record = failed_web_call(value, 107, 4)
            self.assertEqual(record["currentnessReason"], "unclassified")
            self.assertNotIn("PRIVATE", json.dumps(record))

    def test_duplicate_oversized_or_invalid_error_projection_stays_unclassified(self):
        value = rejected()
        for details in ([value["error"]["details"][0]] * 2, [None] * 17, "PRIVATE"):
            value["error"]["details"] = details
            self.assertEqual(failed_web_call(value, 107, 4)["currentnessReason"], "unclassified")
        for command in ("PRIVATE", [], {"PRIVATE": True}):
            value["command"] = command
            self.assertEqual(failed_web_call(value, 107, 4)["command"], "unclassified")
        value["schemaVersion"] = "unreviewed"
        record = failed_web_call(value, 107, 4)
        self.assertEqual(record["currentnessReason"], "unclassified")
        self.assertEqual(record["outcomeKnown"], "unavailable")

    def test_failed_cli_observation_happens_after_original_process_close_without_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = workflow.QualificationClient("not-executed", Path(temporary),
                SimpleNamespace(check=lambda: None), time.monotonic() + 30)
            client.calls = 106
            value = rejected()
            process = Mock()
            process.complete.return_value = subprocess.CompletedProcess([], 4, json.dumps(value).encode(), b"PRIVATE STDERR")
            with patch("tools.phase2_operator_process.Process", return_value=process) as launch:
                with self.assertRaisesRegex(WorkflowError, "^web-prepare:cli-exit-call-107-status-4-code-unavailable-grpc-absent$"):
                    client.call("web", "prepare", "--publication", "PRIVATE ID")
            launch.assert_called_once()
            process.close.assert_called_once_with()
            self.assertEqual(client.failed_call["currentnessReason"], "admission-authority-busy")
            self.assertEqual(client.failed_call["call"], 107)
            self.assertNotIn("PRIVATE", json.dumps(client.failed_call))
            self.assertEqual(failed_call_record(value, 107, 4)["command"], "unclassified")

    def test_group_retirement_does_not_fabricate_clean_shutdown_or_durable_outcome(self):
        client = SimpleNamespace(calls=107, failed_call=failed_web_call(rejected(), 107, 4),
                                 workflow_stage="selected-lifecycle-and-http-checks-complete", preparation_phase="restart")
        node = SimpleNamespace(closed=True, owner=SimpleNamespace(finished=True, process=SimpleNamespace(returncode=-9)),
                               buffers=[bytearray(b"PRIVATE NODE OUTPUT"), bytearray(b"PRIVATE STDERR")])
        identity = {"cliDigest": "sha256:" + "a" * 64, "compilerDigest": "PRIVATE", "token": "PRIVATE"}
        result = failure_observation(client, identity, [], node)
        self.assertFalse(result["passed"])
        self.assertTrue(result["failedNodeGroupRetired"])
        self.assertIsNone(result["failedNodeCleanShutdown"])
        self.assertFalse(result["identityRechecked"])
        self.assertEqual(result["preparationPhase"], "restart")
        self.assertEqual(result["identity"], {"cliDigest": identity["cliDigest"]})
        self.assertNotIn("PRIVATE", json.dumps(result))
        node.owner.finished = False
        self.assertFalse(failure_observation(client, identity, [], node)["failedNodeGroupRetired"])
        self.assertIsNone(failure_observation(client, identity, [], None)["failedNodeGroupRetired"])

    def test_main_emits_failed_observation_and_preserves_original_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input"
            path.write_bytes(b"source-only input")
            argv = ["run", "--cli", str(path), "--node", str(path), "--compiler", str(path), "--fixture-root", str(path)]
            def fail(args):
                args.failure_observation = {"schemaVersion": "latent.angular.t1.workflow.v1", "passed": False,
                                            "failedCall": failed_web_call(rejected(), 107, 4)}
                raise WorkflowError("original-refusal")
            output = io.StringIO()
            with patch.object(sys, "argv", argv), patch.object(sys, "platform", "linux"), \
                 patch.object(workflow, "run", side_effect=fail), contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(WorkflowError, "^original-refusal$"):
                    workflow.main()
            self.assertIs(json.loads(output.getvalue())["passed"], False)
            self.assertNotIn("PRIVATE", output.getvalue())
            with patch.object(sys, "argv", argv), patch.object(sys, "platform", "linux"), \
                 patch.object(workflow, "run", side_effect=fail), patch("builtins.print", side_effect=OSError("PRIVATE")):
                with self.assertRaisesRegex(WorkflowError, "^original-refusal$"):
                    workflow.main()


if __name__ == "__main__":
    unittest.main()
