"""Original failure attribution remains finite, private and cleanup-aware."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.dev_workflow import common, node_diagnostics as diagnostics, state


def failure():
    return {"category": "platform-failure", "outcomeKnown": True,
            "data": {"consumption": {"cpuFuel": "18446744073709551615", "peakMemoryBytes": "67108864",
                                     "wallTimeMicros": "999", "childCalls": 4294967295}},
            "error": {"code": "guest-trap", "message": "private-provider-message",
                      "details": [{"kind": "activation.guest-trap", "fields": {"code": "guest-runtime-error"}},
                                  {"kind": "admission.currentness", "fields": {"reason": "admission-authority-busy"}}]}}


class Projection(unittest.TestCase):
    def test_original_trap_currentness_and_full_width_consumption_survive_without_secrets(self):
        result = failure()
        result["data"].update(payload={"data": "private-body"}, metadata={"credential": "private-token"})
        result["error"]["details"].append({"kind": "provider-secret", "fields": {"value": "private-secret"}})
        original = copy.deepcopy(result)
        captured = diagnostics.original_result(result)
        self.assertEqual(captured["guestTrapCode"], "guest-runtime-error")
        self.assertEqual(captured["admissionCurrentnessReason"], "admission-authority-busy")
        self.assertEqual(captured["consumption"]["cpuFuel"], str((1 << 64) - 1))
        self.assertEqual(captured["consumption"]["childCalls"], str((1 << 32) - 1))
        self.assertNotIn("private-", json.dumps(captured))
        self.assertEqual(result, original)

    def test_malformed_unsigned_values_are_not_normalized_into_observed_consumption(self):
        for invalid in (True, -1, 1.5, "00", "+1", "1e3", str(1 << 64), "private-token", "9" * 10000):
            result = failure()
            result["data"]["consumption"]["cpuFuel"] = invalid
            captured = diagnostics.original_result(result)
            self.assertNotIn("cpuFuel", captured["consumption"])
            self.assertEqual(captured["invalidConsumptionFields"], ["cpuFuel"])
        for invalid in (True, -1, 1.5, "1", 1 << 32):
            result = failure()
            result["data"]["consumption"]["childCalls"] = invalid
            self.assertNotIn("childCalls", diagnostics.original_result(result)["consumption"])

    def test_unknown_conflicting_and_oversized_trap_details_supply_no_diagnostic_tokens(self):
        for rows in (
                [{"kind": "activation.guest-trap", "fields": {"code": "private-token"}}],
                failure()["error"]["details"] + [{"kind": "activation.guest-trap", "fields": {"code": "guest-trap"}}],
                failure()["error"]["details"] * 9):
            result = failure()
            result["error"]["details"] = rows
            captured = diagnostics.original_result(result)
            self.assertNotIn("guestTrapCode", captured)
            self.assertNotIn("admissionCurrentnessReason", captured)
            self.assertNotIn("private-token", json.dumps(captured))
        result = failure()
        result["error"]["details"][1]["fields"]["reason"] = "private-policy-path"
        self.assertNotIn("admissionCurrentnessReason", diagnostics.original_result(result))

    def test_collection_bound_cannot_hide_a_later_unconfirmed_client_owner(self):
        capture = diagnostics.Capture()
        observe = capture.observer("common-scenarios")
        for index in range(diagnostics.MAX_CASES):
            observe("case-" + str(index), failure(), True)
        later = failure()
        later["data"]["recovery"] = {"clientCleanup": "unconfirmed", "message": "private-token"}
        observe("later", later, False)
        observed = capture.snapshot()
        self.assertTrue(observed["truncated"])
        self.assertEqual(observed["retainedCaseCount"], diagnostics.MAX_CASES)
        self.assertEqual(observed["invocationClientCleanup"], "unconfirmed")
        self.assertLess(len(common.encode(observed)), diagnostics.MAX_BYTES)
        self.assertFalse(diagnostics.process_cleanup({"state": "stopped", "reaped": True,
                                                      "cleanShutdown": True}, observed)["confirmed"])

    def test_scope_exit_missing_reap_and_unclean_shutdown_are_not_physical_cleanup(self):
        capture = diagnostics.Capture()
        capture.observer("common-scenarios")("one", failure(), True)
        observed = capture.snapshot()
        for shutdown in (None, {}, {"state": "stopped", "cleanShutdown": True},
                         {"state": "stopped", "reaped": True, "cleanShutdown": False},
                         {"state": "ready", "reaped": True, "cleanShutdown": True}):
            self.assertFalse(diagnostics.process_cleanup(shutdown, observed)["confirmed"])
        self.assertTrue(diagnostics.process_cleanup({"state": "stopped", "reaped": True,
                                                     "cleanShutdown": True}, observed)["confirmed"])


@unittest.skipUnless(os.name == "posix", "Linux source-node ownership")
class ProbeIntegration(unittest.TestCase):
    def test_concrete_client_retains_failure_only_after_its_real_child_is_reaped(self):
        from tools.dev_workflow.client import Client
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "original-process"
            binary = root / "original-client"
            response = {"schemaVersion": "latent.cli.result.v1", **failure()}
            binary.write_text("#!" + sys.executable + "\n"
                              "import os, pathlib, sys\n"
                              "pathlib.Path(" + repr(str(marker)) + ").write_text(str(os.getpid()))\n"
                              "sys.stdout.write(" + repr(json.dumps(response) + "\n") + ")\n"
                              "sys.exit(3)\n", encoding="utf-8")
            binary.chmod(0o700)
            result = Client(binary, root / "config.json", root).call("invoke", timeout=5)
            with self.assertRaises(ChildProcessError):
                os.waitpid(int(marker.read_text()), os.WNOHANG)
            capture = diagnostics.Capture()
            capture.observer("common-scenarios")("original", result, True)
            observed = capture.snapshot()
            self.assertEqual(observed["cases"][0]["guestTrapCode"], "guest-runtime-error")
            self.assertEqual(observed["invocationClientCleanup"], "owned-client-reaped")
            self.assertNotIn("private-provider-message", json.dumps(observed))

    def test_shared_scenario_observes_the_original_result_without_changing_failed_assertion(self):
        from tools.dev_workflow import node_scenarios
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "test-owned"
            root.mkdir(mode=0o700)
            source = root / "source"
            source.mkdir(mode=0o700)
            current = root / "current"
            current.mkdir(mode=0o700)
            native = root / "native"
            native.mkdir(mode=0o700)
            case = {"id": "word-count-2", "service": "examples/test", "contract": "examples:test/api@1.0.0",
                    "function": "count", "input": "input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                    "expect": {"category": "declared-error"}, "requires": [], "timeoutMillis": 1000,
                    "required": True, "fixtures": []}
            state.atomic(source, "input.json", ["x" * 4097])
            state.atomic(source, "scenarios.json", {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [case]})
            state.atomic(source, "capsule.json", {"execution": {"limits": {"cpuFuel": 1000000000,
                                                                          "memoryBytes": 67108864}}})
            descriptor = {"service": "examples/test", "scenarios": ["scenarios.json"],
                          "hostAbi": "lsf-host-abi-phase3-v4", "artifacts": {"capsule": "capsule.json"}}
            state.atomic(root, "project.json", {"descriptor": descriptor})
            state.atomic(native, "node.json", {"supplyChain": {"mode": "enforced"}, "nodeId": "owned",
                                               "securityProfile": "local-experimental-v1"})
            state.atomic(current, "release-source.json", {"sourceCommit": "captured-producer"})
            revision = {"publicationId": "publication:sha256:" + "a" * 64,
                        "releaseDigest": "sha256:" + "b" * 64, "routeGeneration": "1"}
            result = failure()
            result["data"]["resolvedRevision"] = {**revision, "revisionId": "revision-v1:sha256:" + "c" * 64}
            cli, journal = Mock(), Mock()
            cli.call.return_value = result
            journal.read.return_value = {"pending": None}
            capture = diagnostics.Capture()
            from tools.dev_workflow import helper
            with patch.object(node_scenarios.build, "accepted", return_value=(source, {"source": {}, "artifacts": {}, "package": {}})), \
                    patch.object(helper, "client", return_value=(cli, journal)), \
                    patch.object(helper, "installation", return_value=(SimpleNamespace(node=native / "node.json"), current)), \
                    patch.object(node_scenarios.node_tests, "target", return_value=({"publication": revision["publicationId"]}, revision, None)), \
                    patch.object(node_scenarios.node_invocation, "execute", side_effect=lambda _cli, _journal, _intent, call, _deadline: call("original")):
                report = node_scenarios.run(root, {"environment": "node", "selection": []},
                                            diagnostic_observer=capture.observer("common-scenarios"))
            self.assertFalse(report["passed"])
            cli.call.assert_called_once()
            self.assertEqual(capture.snapshot()["cases"][0]["guestTrapCode"], "guest-runtime-error")
            self.assertEqual(capture.snapshot()["invocationClientCleanup"], "owned-client-reaped")

    def probe_failure(self, *, client_unconfirmed=False):
        from tools import dev_node_application_probe as probe
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "test-owned"
            root.mkdir(mode=0o700)
            state.atomic(root, "lifecycle.json", {})
            fake_os = Mock(name="source-probe-os")
            fake_os.name = "posix"
            fake_os.geteuid.return_value = 10001

            def scenarios(_root, _request, *, deadline, diagnostic_observer):
                result = failure()
                if client_unconfirmed:
                    result["data"]["recovery"] = {"clientCleanup": "unconfirmed"}
                diagnostic_observer("word-count-2", result, not client_unconfirmed)
                if client_unconfirmed:
                    raise ValueError("private-provider-message")
                return {"passed": False, "cleanup": "invocation-results-received-node-retained"}

            with patch.object(probe, "os", fake_os), \
                    patch.object(probe, "stage_runtime", return_value={"sourceCommit": "actual-source-producer"}), \
                    patch.object(probe.node_test_profile, "prepare", return_value={}), \
                    patch.object(probe.service, "start", return_value={}), \
                    patch.object(probe.helper, "deploy"), \
                    patch.object(probe.node_scenarios, "run", side_effect=scenarios), \
                    patch.object(probe.service, "request", return_value={"state": "stopped", "reaped": True,
                                                                         "cleanShutdown": True}), \
                    self.assertRaises((common.DevError, ValueError)):
                probe.run(root, root / "runtime", root / "tools", {"language": "go"}, root / "output")
            report = state.load(root, "source-node-probe.json")
            self.assertEqual(report, state.load(root / "output", "probe.json"))
            self.assertNotIn("private-provider-message", json.dumps(report))
            return report

    def test_failed_case_retains_original_diagnostics_after_positive_node_process_cleanup(self):
        report = self.probe_failure()
        self.assertFalse(report["passed"])
        self.assertEqual(report["runtime"]["sourceCommit"], "actual-source-producer")
        self.assertEqual(report["diagnostics"]["cases"][0]["admissionCurrentnessReason"], "admission-authority-busy")
        self.assertTrue(report["processCleanup"]["confirmed"])

    def test_failure_before_scenario_report_cannot_hide_an_unconfirmed_client_owner(self):
        report = self.probe_failure(client_unconfirmed=True)
        self.assertEqual(report["failure"], "ValueError")
        self.assertEqual(report["cleanup"], "unconfirmed-private-workspace-retained")
        self.assertFalse(report["processCleanup"]["confirmed"])


if __name__ == "__main__":
    unittest.main()
