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
from tools.java_http_composition import node as composition
from tools.phase2_operator_process import WorkflowError


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


class TriggerAuditSnapshotTests(unittest.TestCase):
    class Client:
        def __init__(self, directory, applied, recovered, *, snapshot_fails=False):
            self.directory = directory
            self.applied = applied
            self.recovered = recovered
            self.snapshot_fails = snapshot_fails
            self.calls = 0
            self.requests = []

        def call(self, *args, **kwargs):
            self.calls += 1
            self.requests.append((args[:2], kwargs))
            command = args[:2]
            if command == ("route", "get"):
                return {"data": {"snapshot": {"services": [{"service": composition.ADAPTER,
                    "routeId": "java-http-adapter", "revisions": [{"revisionId": "revision"}]}]}}}
            if command == ("deployment", "get"):
                return {"data": {"deployment": {"generation": "3"}}}
            if command == ("trigger", "get"):
                return {"data": {"trigger": None, "stateVersion": "3"}}
            if command == ("trigger", "apply"):
                return self.applied
            if command == ("trigger", "operation"):
                return self.recovered
            if command == ("node", "get"):
                if self.snapshot_fails:
                    raise RuntimeError("read failed")
                return {"category": "success", "data": {}}
            raise AssertionError(command)

    @staticmethod
    def refusal(reason="audit-capacity"):
        return {"category": "platform-failure", "outcomeKnown": True, "data": {"recovery": {}},
                "error": {"code": "resource-exhausted", "details": [
                    {"kind": "audit-journal", "fields": {"reason": reason}}]}}

    def test_known_refusal_keeps_original_lookup_and_one_later_read(self):
        for snapshot_fails in (False, True):
            with self.subTest(snapshot_fails=snapshot_fails), tempfile.TemporaryDirectory() as temporary:
                applied = self.refusal()
                recovered = {"outcomeKnown": False, "data": {"receipt": None}}
                client = self.Client(Path(temporary), applied, recovered, snapshot_fails=snapshot_fails)
                with self.assertRaisesRegex(WorkflowError, "java-http-original-trigger-operation-recovery"):
                    composition.route(client, "localhost:1234", "publication")
                self.assertEqual([command for command, _ in client.requests], [
                    ("route", "get"), ("deployment", "get"), ("trigger", "get"),
                    ("trigger", "apply"), ("trigger", "operation"), ("node", "get")])
                self.assertEqual(client.requests[-1][1]["timeout"], 2)
                self.assertEqual(applied["category"], "platform-failure")
                self.assertFalse(recovered["outcomeKnown"])
                self.assertIsNone(recovered["data"]["receipt"])

    def test_other_refusals_do_not_add_snapshot_or_change_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = self.Client(Path(temporary), self.refusal("audit-busy"),
                {"outcomeKnown": False, "data": {"receipt": None}})
            with self.assertRaisesRegex(WorkflowError, "java-http-original-trigger-operation-recovery"):
                composition.route(client, "localhost:1234", "publication")
            self.assertEqual(client.requests[-1][0], ("trigger", "operation"))
            self.assertEqual(len(client.requests), 5)

    def test_successful_trigger_pair_does_not_read_node_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = {"operationId": "original"}
            client = self.Client(Path(temporary),
                {"category": "success", "outcomeKnown": True, "data": {"receipt": receipt}},
                {"outcomeKnown": True, "data": {"receipt": receipt}})
            composition.route(client, "localhost:1234", "publication")
            self.assertNotIn(("node", "get"), [command for command, _ in client.requests])
            self.assertEqual(sum(command == ("trigger", "apply") for command, _ in client.requests), 2)
            self.assertEqual(sum(command == ("trigger", "operation") for command, _ in client.requests), 2)


if __name__ == "__main__":
    unittest.main()
