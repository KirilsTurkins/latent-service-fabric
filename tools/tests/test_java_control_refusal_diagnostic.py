from __future__ import annotations

import copy
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
from tools.java_http_composition import qualify as composition_qualify
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


class CanaryPromotionLookupTests(unittest.TestCase):
    @staticmethod
    def failed_response():
        return {"schemaVersion": "latent.cli.result.v1", "category": "platform-failure",
                "requestDispatched": True, "outcomeKnown": False,
                "data": {"recovery": {"family": "rollout", "tenant": "examples",
                    "rolloutId": "java-http-canary", "operationId": "java-canary-promote",
                    "expectedRevision": "1", "targetGeneration": None}}}

    @staticmethod
    def found_response():
        return {"schemaVersion": "latent.cli.result.v1", "category": "success", "outcomeKnown": True,
                "data": {"disposition": "ROLLOUT_OPERATION_LOOKUP_DISPOSITION_FOUND", "receipt": {
                    "tenant": "examples", "rolloutId": "java-http-canary", "operationId": "java-canary-promote",
                    "expectedRevision": "1", "step": 1, "action": "ROLLOUT_ACTION_PROMOTE",
                    "outcome": "ROLLOUT_OPERATION_OUTCOME_COMMITTED", "actor": "private-secret"}}}

    def test_lookup_is_bounded_read_only_and_never_retains_raw_receipt(self):
        found = self.found_response()
        unknown = {"schemaVersion": "latent.cli.result.v1", "category": "success", "outcomeKnown": False,
                   "data": {"disposition": "ROLLOUT_OPERATION_LOOKUP_DISPOSITION_UNKNOWN", "receipt": None}}
        mismatch = json.loads(json.dumps(found))
        mismatch["data"]["receipt"]["operationId"] = "other-operation"
        for response, status in ((found, "matching-committed-promotion"), (unknown, "unknown"),
                                 (mismatch, "inconsistent"), (RuntimeError("private-secret"), "lookup-failed")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                evidence = Path(temporary)
                (evidence / "266.json").write_text(json.dumps(self.failed_response()))
                lookup = mock.Mock(side_effect=response) if isinstance(response, Exception) else mock.Mock(return_value=response)
                client = SimpleNamespace(evidence=evidence, _control_call=lookup)
                composition_qualify._retain_uncertain_promotion_lookup(client, 266, "1", WorkflowError("authoring-control-266-4"))
                lookup.assert_called_once_with("rollout", "operation", "java-http-canary", "java-canary-promote",
                                               codes=(0, 2, 3, 4, 5, 6, 130))
                output = (evidence / "java-canary-promotion-lookup.json").read_text()
                self.assertEqual(json.loads(output), {"qualification": False, "status": status})
                self.assertNotIn("private-secret", output)

    def test_lookup_requires_the_original_uncertain_promotion_identity(self):
        variants = []
        for key, value in (("family", "deployment"), ("tenant", "other"), ("rolloutId", "other"),
                           ("operationId", "other"), ("expectedRevision", "2"), ("targetGeneration", "1")):
            changed = self.failed_response()
            changed["data"]["recovery"][key] = value
            variants.append(changed)
        for key, value in (("requestDispatched", False), ("outcomeKnown", True), ("category", "declared-error")):
            changed = self.failed_response()
            changed[key] = value
            variants.append(changed)
        missing = self.failed_response()
        del missing["data"]["recovery"]["targetGeneration"]
        variants.append(missing)
        for original in variants:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temporary:
                evidence = Path(temporary)
                (evidence / "266.json").write_text(json.dumps(original))
                lookup = mock.Mock()
                client = SimpleNamespace(evidence=evidence, _control_call=lookup)
                composition_qualify._retain_uncertain_promotion_lookup(client, 266, "1", WorkflowError("authoring-control-266-4"))
                lookup.assert_not_called()
                self.assertFalse((evidence / "java-canary-promotion-lookup.json").exists())

    def test_diagnostic_and_retention_failure_cannot_replace_original_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            (evidence / "266.json").write_text(json.dumps(self.failed_response()))
            client = SimpleNamespace(evidence=evidence, _control_call=mock.Mock(side_effect=RuntimeError("private-secret")))
            with mock.patch.object(composition_qualify, "write_json", side_effect=OSError("private-secret")):
                self.assertIsNone(composition_qualify._retain_uncertain_promotion_lookup(
                    client, 266, "1", WorkflowError("authoring-control-266-4")))
            client._control_call.assert_called_once()

    def test_canary_preserves_failed_promotion_after_read_only_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            releases = root / "releases"
            candidate = releases / "java-http-adapter-next"
            candidate.mkdir(parents=True)
            (candidate / "deployment.json").write_text(json.dumps({"metadata": {}, "spec": {"route": {}}}))
            evidence = root / "evidence"
            evidence.mkdir()
            original = self.failed_response()

            class Client:
                directory = root
                deadline = time.monotonic() + 30
                calls = 0
                _control_call = mock.Mock(return_value=self.found_response())

                def __init__(self):
                    self.evidence = evidence
                    self.requests = []

                def call(self, *args, **kwargs):
                    self.calls += 1
                    self.requests.append(args)
                    if args[:2] == ("deployment", "get"):
                        return {"data": {"deployment": {"generation": "1"}}}
                    if args[:2] == ("rollout", "start"):
                        return {"data": {"receipt": {"revision": "1"}}}
                    if args[:2] == ("rollout", "evaluate"):
                        return {"data": {"report": {"assessment": {"verdict": "HEALTHY"},
                                                    "terminal": "16", "live": "0"}}}
                    if args[:2] == ("activation", "get"):
                        return {"data": {"phase": "running"}}
                    if args[:2] == ("rollout", "promote"):
                        number = self.calls
                        (evidence / f"{number:03}.json").write_text(json.dumps(original))
                        self.calls += 7  # Existing audit reads may advance the shared call counter.
                        raise WorkflowError(f"authoring-control-{number}-4")
                    raise AssertionError(args)

            client = Client()
            draining = mock.Mock()
            def observe_lookup(*args, **kwargs):
                self.assertEqual(draining.close.call_count, 0)
                return self.found_response()
            client._control_call.side_effect = observe_lookup
            candidates = [{"publication": {"id": "old"}, "revisionId": "r0"},
                          {"publication": {"id": "new"}, "revisionId": "r1"}]
            observations = [{"selectedRevisionId": None, "candidates": candidates},
                            {"selectedRevisionId": "r0", "candidates": candidates}]
            targets = {"adapter": {"grants": [], "budget": {}}}
            sample = lambda *args, **kwargs: {"data": {"resolvedRevision": {
                "revisionId": "r" + str(int(args[5][-2:]) % 2)}}}
            with mock.patch.object(composition_qualify, "receipt", side_effect=lambda value, _: value["data"]["receipt"]), \
                 mock.patch.object(composition_qualify.inspection, "observe", side_effect=observations), \
                 mock.patch.object(composition_qualify, "rollback_target", return_value="1"), \
                 mock.patch.object(composition_qualify, "invoke", side_effect=sample), \
                 mock.patch.object(composition_qualify, "decoded", return_value=[{"status": 200}]), \
                 mock.patch.object(composition_qualify, "running_adapter", return_value=draining), \
                 mock.patch.object(composition_qualify, "readiness", return_value={}):
                with self.assertRaisesRegex(WorkflowError, "authoring-control-[0-9]+-4"):
                    composition_qualify.canary(client, targets, {"adapter": "old", "adapter-next": "new"},
                                               releases, "localhost")
            self.assertEqual(sum(row[:2] == ("rollout", "promote") for row in client.requests), 1)
            self.assertFalse(any(row[:2] in (("rollout", "rollback"), ("activation", "cancel")) for row in client.requests))
            client._control_call.assert_called_once()
            draining.close.assert_called_once()
            self.assertEqual(json.loads((evidence / "java-canary-promotion-lookup.json").read_text()),
                             {"qualification": False, "status": "matching-committed-promotion"})


def audit_observation(**counters):
    values = {name: "0" for name in (*composition.audit_idle.COUNTERS, *composition.audit_idle.STATES)}
    values.update(counters)
    return {"schemaVersion": "latent.cli.result.v1", "command": "capability list",
        "category": "success", "error": None, "outcomeKnown": True, "requestDispatched": True,
        "data": {"nextPageToken": None, "nodeUsage": {"scope": "node", "unavailable": [], "counters": values}}}


class TriggerAuditSnapshotTests(unittest.TestCase):
    class Client:
        def __init__(self, directory, applied, recovered, *, snapshot_fails=False):
            self.directory = directory
            self.applied = applied
            self.recovered = recovered
            self.snapshot_fails = snapshot_fails
            self.calls = 0
            self.requests = []
            self.deadline = time.monotonic() + 30

        def call(self, *args, **kwargs):
            self.calls += 1
            self.requests.append((args[:2], kwargs))
            command = args[:2]
            if command == ("capability", "list"):
                return audit_observation()
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
                    ("route", "get"), ("deployment", "get"), ("capability", "list"), ("trigger", "get"),
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
            self.assertEqual(len(client.requests), 6)

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


class TriggerAuditDrainTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.sleeps = []
        self.client = SimpleNamespace(deadline=200., call=mock.Mock())
        self.read = ("capability", "list", "--deployment", "java-http-adapter", "--include-node-usage")
        self.enterContext(mock.patch.object(composition.time, "monotonic", side_effect=lambda: self.now))
        self.enterContext(mock.patch.object(composition.time, "sleep", side_effect=self.sleep))

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay

    def wait(self):
        composition.wait_trigger_audit_idle(self.client, "java-http-adapter")

    def test_each_live_owner_delays_audit_idle_without_mutating(self):
        for name in composition.audit_idle.COUNTERS:
            with self.subTest(counter=name):
                self.client.call.reset_mock()
                self.client.call.side_effect = [audit_observation(**{name: "1"}), audit_observation()]
                self.wait()
                self.assertEqual(self.client.call.call_args_list,
                                 [mock.call(*self.read, timeout=1), mock.call(*self.read, timeout=1)])

    def test_busy_audit_has_a_finite_read_bound_and_no_mutation(self):
        self.client.call.return_value = audit_observation(audit_queued_operations="1")
        with self.assertRaisesRegex(RuntimeError, "audit-drain-observation-limit"):
            self.wait()
        self.assertEqual(self.client.call.call_count, composition.audit_idle.MAX_OBSERVATIONS)
        self.assertTrue(all(call.args == self.read for call in self.client.call.call_args_list))
        self.assertEqual(len(self.sleeps), composition.audit_idle.MAX_OBSERVATIONS - 1)
        self.assertLessEqual(self.now, 100 + composition.audit_idle.MAX_SECONDS)

    def test_original_deadline_bounds_reads_and_rejects_late_idle(self):
        self.client.deadline = self.now
        with self.assertRaisesRegex(WorkflowError, "audit-drain-deadline"):
            self.wait()
        self.client.call.assert_not_called()
        self.client.deadline = self.now + .02
        def late(*args, **kwargs):
            self.assertEqual(args, self.read)
            self.assertAlmostEqual(kwargs["timeout"], .02)
            self.now += .03
            return audit_observation()
        self.client.call.side_effect = late
        with self.assertRaisesRegex(WorkflowError, "audit-drain-deadline"):
            self.wait()
        self.client.call.assert_called_once()

    def test_five_second_limit_cannot_extend_the_original_wait(self):
        def slow(*args, **kwargs):
            self.assertEqual(args, self.read)
            self.assertLessEqual(kwargs["timeout"], 1)
            self.now += 1
            return audit_observation(audit_reserved_records="1")
        self.client.call.side_effect = slow
        with self.assertRaisesRegex(WorkflowError, "audit-drain-deadline"):
            self.wait()
        self.assertEqual(self.client.call.call_count, 5)
        self.assertEqual(self.client.deadline, 200.)

    def test_failed_partial_unavailable_and_invalid_observations_fail_closed(self):
        cases = []
        for key, value in (("category", "platform-failure"), ("outcomeKnown", False),
                           ("requestDispatched", False), ("error", {"code": "resource-exhausted"})):
            row = audit_observation()
            row[key] = value
            cases.append(row)
        for mutate in (
                lambda data: data.update(nextPageToken="more"),
                lambda data: data.pop("nodeUsage"),
                lambda data: data["nodeUsage"].update(unavailable=["audit-unavailable"]),
                lambda data: data["nodeUsage"]["counters"].pop("audit_queued_operations"),
                lambda data: data["nodeUsage"]["counters"].update(audit_queued_bytes="-1")):
            row = audit_observation()
            mutate(row["data"])
            cases.append(row)
        cases += [audit_observation(audit_closed="1"), audit_observation(audit_recovery_pending="1")]
        for index, row in enumerate(cases):
            with self.subTest(case=index):
                self.client.call.reset_mock()
                self.client.call.return_value = row
                with self.assertRaises(ValueError):
                    self.wait()
                self.client.call.assert_called_once_with(*self.read, timeout=1)

    def test_read_failure_is_not_retried(self):
        failure = TimeoutError("read-only failure")
        self.client.call.side_effect = failure
        with self.assertRaises(TimeoutError) as raised:
            self.wait()
        self.assertIs(raised.exception, failure)
        self.client.call.assert_called_once_with(*self.read, timeout=1)

    def test_route_waits_before_each_fence_and_preserves_both_single_applies(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = {"operationId": "original"}
            client = TriggerAuditSnapshotTests.Client(Path(temporary),
                {"category": "success", "outcomeKnown": True, "data": {"receipt": receipt}},
                {"outcomeKnown": True, "data": {"receipt": receipt}})
            original = client.call
            calls, documents = [], []
            observations = iter([audit_observation(audit_queued_operations="1"), audit_observation(),
                                 audit_observation(audit_reserved_records="2"), audit_observation()])
            def call(*args, **kwargs):
                calls.append((args, kwargs))
                if args[:2] == ("capability", "list"):
                    client.calls += 1
                    return next(observations)
                if args[:2] == ("trigger", "apply"):
                    documents.append(json.loads(args[2].read_text()))
                return original(*args, **kwargs)
            client.call = call
            target = composition.route(client, "localhost:1234", "publication", path="/original", function="handle")
            self.assertEqual([args[:2] for args, _ in calls], [
                ("route", "get"), ("deployment", "get"),
                ("capability", "list"), ("capability", "list"), ("trigger", "get"),
                ("trigger", "apply"), ("trigger", "operation"),
                ("capability", "list"), ("capability", "list"), ("trigger", "get"),
                ("trigger", "apply"), ("trigger", "operation")])
            applies = [args for args, _ in calls if args[:2] == ("trigger", "apply")]
            lookups = [args for args, _ in calls if args[:2] == ("trigger", "operation")]
            for apply, lookup in zip(applies, lookups, strict=True):
                self.assertEqual(apply[3:], ("--operation-id", lookup[2],
                    "--expected-generation", 0, "--expected-state-version", "3"))
            self.assertEqual([doc["spec"]["configuration"]["method"] for doc in documents], ["GET", "POST"])
            for doc in documents:
                self.assertEqual(doc["spec"]["target"], target)
                self.assertEqual(doc["spec"]["configuration"]["path"], "/original")
            self.assertEqual(target["publication"], "publication")
            self.assertEqual(target["deploymentGeneration"], 3)

    def test_unknown_apply_still_fails_after_idle_and_a_matching_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = {"operationId": "original"}
            applied = {"category": "transport-failure", "outcomeKnown": False, "data": {"receipt": receipt}}
            before = copy.deepcopy(applied)
            client = TriggerAuditSnapshotTests.Client(Path(temporary), applied,
                {"outcomeKnown": True, "data": {"receipt": receipt}})
            with self.assertRaisesRegex(WorkflowError, "java-http-original-trigger-operation-recovery"):
                composition.route(client, "localhost:1234", "publication")
            self.assertEqual(sum(command == ("trigger", "apply") for command, _ in client.requests), 1)
            self.assertEqual(sum(command == ("trigger", "operation") for command, _ in client.requests), 1)
            self.assertEqual(applied, before)


if __name__ == "__main__":
    unittest.main()
