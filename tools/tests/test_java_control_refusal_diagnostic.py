from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import java_control_refusal_diagnostic as diagnostic
from tools import phase2_operator_scenario as scenario


class RefusalTests(unittest.TestCase):
    def test_all_closed_stage_reason_pairs_are_failure_only_observations(self):
        for stage in diagnostic.STAGES:
            for reason in diagnostic.REASONS:
                with self.subTest(stage=stage, reason=reason):
                    row = diagnostic.observe(diagnostic.PREFIX + f" {stage} {reason}\n".encode())
                    self.assertFalse(row["qualification"])
                    self.assertEqual(row["records"], [{"stage": stage, "reason": reason}])
                    self.assertEqual(row["invalidMarkerCount"], 0)

    def test_malformed_unknown_and_secret_sentinels_never_enter_the_projection(self):
        prefix = diagnostic.PREFIX
        malformed = [prefix + b" trigger-request PRIVATE-TOKEN/path", prefix + b" fake http-budget",
                     prefix + b" trigger-request http-budget private-secret", prefix + b"\xff",
                     prefix + b"  trigger-request http-budget", prefix + b" trigger-request 17"]
        row = diagnostic.observe(b"\n".join(malformed))
        self.assertEqual(row["records"], [])
        self.assertEqual(row["invalidMarkerCount"], len(malformed))
        self.assertNotIn("PRIVATE", json.dumps(row))
        self.assertNotIn("private-secret", json.dumps(row))
        self.assertEqual(diagnostic.observe(b"x" * (diagnostic.MAX_STDERR + 1))["status"], "invalid-source")
        self.assertEqual(diagnostic.observe("not bytes")["status"], "invalid-source")

    def test_capture_stays_bounded_and_does_not_invent_complete_coverage(self):
        line = diagnostic.PREFIX + b" trigger-commit audit-capacity\n"
        row = diagnostic.observe(line * 100)
        self.assertEqual(len(row["records"]), 16)
        self.assertEqual(row["invalidMarkerCount"], 84)
        self.assertTrue(row["atCaptureLimit"])
        self.assertFalse(row["qualification"])

    def test_guest_stdout_and_structured_marker_text_are_not_host_records(self):
        line = diagnostic.PREFIX + b" trigger-request http-budget\n"
        structured = json.dumps({"message": line.decode(), "activation": "private"}).encode() + b"\n"
        node = SimpleNamespace(buffers=[line, structured])
        with tempfile.TemporaryDirectory() as temporary:
            row = diagnostic.retain(node, Path(temporary))
            self.assertEqual(row["records"], [])
            self.assertNotIn("private", (Path(temporary) / "management-refusals.json").read_text())
        node.buffers[1] += line
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(diagnostic.retain(node, Path(temporary))["records"],
                             [{"stage": "trigger-request", "reason": "http-budget"}])

    def test_retention_failure_does_not_replace_the_original_refusal(self):
        original = RuntimeError("original-refusal")
        node = SimpleNamespace(buffers=[b"", diagnostic.PREFIX + b" trigger-request http-budget\n"])
        with mock.patch.object(diagnostic, "write_json", side_effect=OSError("PRIVATE-/secret")):
            with self.assertRaises(RuntimeError) as raised:
                try:
                    raise original
                finally:
                    row = diagnostic.retain(node, Path("unused"))
        self.assertIs(raised.exception, original)
        self.assertEqual(row["status"], "retention-unavailable")
        self.assertNotIn("PRIVATE", json.dumps(row))

    def test_only_node_launch_gets_the_explicit_flag_and_client_env_never_changes(self):
        for enabled in (False, True):
            for failing in (False, True):
                with self.subTest(enabled=enabled, failing=failing), tempfile.TemporaryDirectory() as temporary:
                    directory = Path(temporary)
                    original = {"PATH": "/fixed", "HOME": "/original", diagnostic.ENVIRONMENT: "ambient"}
                    client = SimpleNamespace(environment=original, cancellation=object(),
                                             directory=directory, deadline=time.monotonic() + 30, node=None)
                    seen = []

                    def call(*args):
                        self.assertIs(client.environment, original)
                        self.assertEqual(client.environment[diagnostic.ENVIRONMENT], "ambient")
                        return {"data": {"inventory": {"health": {"ready": True}, "node": {
                            key: "fixed" for key in ("id", "architecture", "operatingSystem", "cpuFeatures", "trustClasses")}}}}

                    client.call = call
                    node = SimpleNamespace(close=mock.Mock())
                    node.line = mock.Mock(side_effect=RuntimeError("launch-failed") if failing else None,
                                          return_value={"endpoint": "127.0.0.1:1234"})

                    def process(_argv, _cwd, environment, _cancellation, maximum):
                        self.assertEqual(maximum, 262144)
                        seen.append(environment)
                        return node

                    with mock.patch.object(scenario, "Process", side_effect=process):
                        if failing:
                            with self.assertRaisesRegex(RuntimeError, "launch-failed"):
                                scenario.connect(client, "node", directory, directory / "config", "examples", 1,
                                                 control_refusal_diagnostic=enabled)
                            node.close.assert_called_once()
                        else:
                            self.assertIs(scenario.connect(client, "node", directory, directory / "config", "examples", 1,
                                                           control_refusal_diagnostic=enabled), node)
                    self.assertIs(client.environment, original)
                    self.assertEqual(original, {"PATH": "/fixed", "HOME": "/original", diagnostic.ENVIRONMENT: "ambient"})
                    self.assertEqual(seen[0].get(diagnostic.ENVIRONMENT), "1" if enabled else None)


if __name__ == "__main__":
    unittest.main()
