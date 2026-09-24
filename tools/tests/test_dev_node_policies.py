"""Recovery, configuration ownership and public policy association boundaries."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools.dev_workflow import common, effects, journal, node_test_profile, policy_operations, scenarios, state


class PolicyRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "test-policies"
        self.root.mkdir(mode=0o700)
        self.controller = journal.Journal(self.root, "node", "examples",
            settle=lambda operation, result: effects.settle(self.root, operation, result))
        self.document = {"formatVersion": 1, "tenant": "examples", "rules": []}
        self.intent = {"policyId": "test-allow", "recordKind": "policy", "expectedGeneration": "0", "document": self.document}

    def response(self, operation):
        receipt = {"operationId": operation, "tenant": "examples", "id": "test-allow", "recordKind": "policy",
                   "generation": "2", "contentDigest": "sha256:" + "c" * 64, "revoked": False}
        return {"category": "success", "outcomeKnown": True,
            "data": {"receipt": receipt, "policy": {**receipt, "document": self.document}}}

    def test_lost_apply_looks_up_original_and_records_before_clearing_intent(self):
        calls = []
        def lost(operation):
            calls.append(operation)
            raise OSError("lost response")
        with self.assertRaises(OSError):
            self.controller.execute("policy", self.intent, lost)
        with self.assertRaisesRegex(common.DevError, "recover-original"):
            self.controller.execute("policy", self.intent, lost)
        response = self.response(calls[0])
        lookups = []
        def lookup(kind, operation):
            lookups.append((kind, operation))
            return response
        self.controller.recover(lookup)
        self.assertEqual(lookups, [("policy", calls[0])])
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.controller.read()["pending"])
        self.assertEqual(state.load(self.root, "test-policy-receipts.json")["policy:test-allow"], response["data"]["receipt"])
        self.assertFalse((self.root / "last-deployment.json").exists())

    def test_unknown_wrong_scope_and_changed_current_policy_retain_original(self):
        operation = self.controller.begin("policy", self.intent)
        unknown = {"category": "not-found", "outcomeKnown": False,
                   "data": {"operationId": operation["id"], "retained": False, "mutationOutcome": "unknown"}}
        with self.assertRaisesRegex(common.DevError, "unknown-or-expired"):
            self.controller.recover(lambda *_: unknown)
        for mutate in (
            lambda r: r["data"]["receipt"].update(tenant="other"),
            lambda r: r["data"]["receipt"].update(operationId="another-operation"),
            lambda r: r["data"]["receipt"].update(recordKind="provider-binding"),
            lambda r: r["data"]["policy"].update(generation="3"),
            lambda r: r["data"]["policy"].update(document={"rules": ["broader"]}),
            lambda r: r["data"]["receipt"].update(revoked=True),
        ):
            response = copy.deepcopy(self.response(operation["id"]))
            mutate(response)
            with self.assertRaises(common.DevError) as error:
                self.controller.recover(lambda *_: response)
            self.assertTrue(error.exception.uncertain)
            self.assertEqual(self.controller.read()["pending"], operation)

    def test_existing_unowned_or_changed_policy_is_never_applied(self):
        client = Mock()
        client.call.return_value = self.response("unowned")
        with self.assertRaisesRegex(common.DevError, "not-owned-no-overwrite"):
            policy_operations.apply(self.root, client, self.controller, "test-allow", "policy", self.document)
        self.assertEqual(client.call.call_count, 1)
        self.assertIsNone(self.controller.read()["pending"])

    def test_lookup_queries_current_document_only_after_retained_operation(self):
        client = Mock()
        response = self.response("operation")
        client.call.side_effect = [{**response, "data": {"receipt": response["data"]["receipt"]}},
                                  {**response, "data": {"policy": response["data"]["policy"]}}]
        self.assertEqual(policy_operations.lookup(client, "operation"), response)
        self.assertEqual(client.call.call_args_list[0].args, ("policy", "operation", "--operation-id", "operation"))
        self.assertEqual(client.call.call_args_list[1].args, ("policy", "--kind", "policy", "get", "--id", "test-allow"))


class TestProfile(unittest.TestCase):
    def setUp(self):
        signer = patch('tools.dev_workflow.node_test_signing.prepare', return_value={"trust": "isolated-short-lived-demo-only"})
        self.signer = signer.start()
        self.addCleanup(signer.stop)

    def prepare(self, root, descriptor, *, consent):
        return node_test_profile.prepare(root, descriptor, consent=consent, admission="signed-fixture", tool_root=Path("/tools"))

    def fixture(self, root):
        for directory in (root, root / "runtime", root / "runtime/config"):
            directory.mkdir(mode=0o700)
        original = {"securityProfile": "local-experimental-v1", "dataDirectory": str(root / "runtime/data"),
                    "audit": {"mode": "durable"}, "credentials": [{"token": "private-test-canary"}]}
        state.atomic(root / "runtime/config", "node.json", original)
        descriptor = {"language": "go", "tenant": "examples", "service": "examples/my-greeting"}
        return original, descriptor

    def test_profile_requires_explicit_test_scope_and_preserves_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "test-owned"
            original, descriptor = self.fixture(root)
            with self.assertRaisesRegex(common.DevError, "consent"):
                self.prepare(root, descriptor, consent=False)
            selected = self.prepare(root, descriptor, consent=True)
            configured = state.load(root / "runtime/config", "node.json")
            self.assertEqual(configured["credentials"], original["credentials"])
            self.assertEqual(configured["execution"]["maximumCpuFuel"], 10000000000)
            self.assertFalse(selected["capabilitiesGranted"])
            self.assertNotIn(b"private-test-canary", common.encode(selected))
            self.assertEqual(len(configured["providers"]["bindings"]), 3)
            self.assertEqual(self.prepare(root, descriptor, consent=True), selected)
            configured["execution"] = {"maximumWallTimeMillis": 999}
            state.atomic(root / "runtime/config", "node.json", configured)
            with self.assertRaisesRegex(common.DevError, "configuration-changed"):
                self.prepare(root, descriptor, consent=True)

    def test_running_owner_and_existing_provider_configuration_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "test-owned"
            original, descriptor = self.fixture(root)
            with state.lock(root / "runtime", "run.lock"):
                with self.assertRaises((OSError, common.DevError)):
                    self.prepare(root, descriptor, consent=True)
            self.assertEqual(state.load(root / "runtime/config", "node.json"), original)
            original["providers"] = {"existing": True}
            state.atomic(root / "runtime/config", "node.json", original)
            with self.assertRaisesRegex(common.DevError, "existing-providers"):
                self.prepare(root, descriptor, consent=True)
            self.assertEqual(state.load(root / "runtime/config", "node.json"), original)

    def test_interrupted_configuration_resumes_only_exact_before_or_after_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "test-owned"
            _original, descriptor = self.fixture(root)
            atomic = state.atomic
            def interrupt(directory, name, value):
                if name == "node.json":
                    raise OSError("interrupted local configuration write")
                atomic(directory, name, value)
            with patch.object(state, "atomic", interrupt), self.assertRaises(OSError):
                self.prepare(root, descriptor, consent=True)
            result = self.prepare(root, descriptor, consent=True)
            self.assertEqual(result["configurationSha256"], common.digest((root / "runtime/config/node.json").read_bytes()))


class ScenarioTargets(unittest.TestCase):
    def test_preflight_freezes_the_input_and_expected_bytes_used_for_assertions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.json").write_bytes(b"[]")
            (root / "expected.json").write_bytes(b"[]")
            case = {"id": "selected", "service": "examples/test", "contract": "examples:test/api@1.0.0",
                "function": "run", "input": "input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                "expect": {"category": "success", "payload": "expected.json"}, "requires": [],
                "timeoutMillis": 1000, "required": True, "fixtures": []}
            document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [case]}
            prepared, unsupported = scenarios.prepare(document, root, "portable", [], supported=set())
            (root / "input.json").write_bytes(b"changed source")
            (root / "expected.json").write_bytes(b"changed assertion")
            def invoke(_case, raw):
                self.assertEqual(raw, b"[]")
                return {"category": "success", "outcomeKnown": True, "data": {"payload": {
                    "encoding": "base64", "data": "W10=", "byteLength": "2", "mediaType": case["mediaType"]}}}
            result = scenarios.run_prepared(prepared, unsupported, "portable", invoke, {})
            self.assertTrue(result["passed"])
            self.assertEqual(result["results"][0]["inputSha256"], common.digest(b"[]"))

    def test_required_unsupported_case_prevents_all_invocation_and_optional_is_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.json").write_bytes(b"[]")
            case = {"id": "supported", "service": "examples/test", "contract": "examples:test/api@1.0.0",
                "function": "run", "input": "input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                "expect": {"category": "success"}, "requires": [], "timeoutMillis": 1000, "required": True, "fixtures": []}
            unsupported = {**case, "id": "unsupported", "requires": ["restart"]}
            document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [case, unsupported]}
            adapter = Mock(return_value={"category": "success", "outcomeKnown": True, "data": {}})
            result = scenarios.run(document, root, "portable", [], adapter, {}, supported=set())
            adapter.assert_not_called()
            self.assertEqual([row["status"] for row in result["results"]], ["not-run", "unsupported"])
            self.assertFalse(result["passed"])
            unsupported["required"] = False
            result = scenarios.run(document, root, "portable", [], adapter, {}, supported=set())
            adapter.assert_called_once()
            self.assertTrue(result["passed"])

    def test_unknown_or_failed_adapter_stops_subsequent_calls_and_redacts_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.json").write_bytes(b"[]")
            case = {"id": "first", "service": "examples/test", "contract": "examples:test/api@1.0.0",
                "function": "run", "input": "input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                "expect": {"category": "success"}, "requires": [], "timeoutMillis": 1000, "required": True, "fixtures": []}
            document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [case, {**case, "id": "later"}]}
            for adapter in (Mock(side_effect=OSError("private-fixture-credential")),
                            Mock(return_value={"category": "transport-failure", "outcomeKnown": False, "data": {}})):
                result = scenarios.run(document, root, "node", [], adapter, {}, supported=set())
                adapter.assert_called_once()
                self.assertFalse(result["passed"])
                self.assertEqual([row["status"] for row in result["results"]], ["failed", "not-run"])
                self.assertNotIn(b"private-fixture-credential", common.encode(result))

    def test_cold_node_allowance_is_explicit_and_does_not_change_portable_deadline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.json").write_bytes(b"[]")
            case = {"id": "cold", "service": "examples/test", "contract": "examples:test/api@1.0.0",
                "function": "run", "input": "input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                "expect": {"category": "success"}, "requires": [], "timeoutMillis": 5000,
                "nodeTimeoutMillis": 120000, "required": True, "fixtures": []}
            document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [case]}
            for environment, expected in (("node", 120000), ("portable", 5000)):
                def invoke(current, _raw):
                    self.assertEqual(current["timeoutMillis"], expected)
                    return {"category": "success", "outcomeKnown": True, "data": {}}
                result = scenarios.run(document, root, environment, [], invoke, {}, supported=set())
                self.assertTrue(result["passed"])
                self.assertEqual(result["results"][0]["timeoutMillis"], expected)
            case["nodeTimeoutMillis"] = 120001
            with self.assertRaises(common.DevError):
                scenarios.validate(document, "node")

    def test_each_policy_switch_requires_the_current_invocation_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.json").write_bytes(b"[]")
            original = {"publicationId": "publication", "releaseDigest": "sha256:" + "a" * 64,
                        "revisionId": "revision", "routeGeneration": "1"}
            selected = dict(original)
            case = {"id": "allowed", "service": "examples/test", "contract": "examples:test/api@1.0.0",
                "function": "run", "input": "input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
                "expect": {"category": "success"}, "requires": [], "timeoutMillis": 1000,
                "required": True, "fixtures": [], "execution": {"grants": []}}
            document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [case, {**case, "id": "changed"}]}
            def invoke(current, _raw):
                if current["id"] == "changed":
                    selected["routeGeneration"] = "2"
                # A delayed response from the previous deployment must fail.
                return {"category": "success", "outcomeKnown": True, "data": {"resolvedRevision": original}}
            result = scenarios.run(document, root, "node", [], invoke, {}, supported=set(),
                                   execution_controls=lambda current: not current["execution"]["grants"],
                                   expected_revision=lambda: selected)
            self.assertEqual([row["status"] for row in result["results"]], ["passed", "failed"])
            self.assertFalse(result["passed"])
            self.assertFalse(result["results"][1]["targetMatches"])

    def test_elapsed_run_deadline_prevents_another_operator_process(self):
        from tools.dev_workflow.client import Client
        selected = Client(Path("operator"), Path("private-config"), Path("workspace"), deadline=1)
        with patch("tools.dev_workflow.client.time.monotonic", return_value=2), \
                patch("tools.dev_workflow.client.process.run") as execute:
            with self.assertRaisesRegex(common.DevError, "node-test-run-deadline"):
                selected.call("policy", "apply")
            execute.assert_not_called()


class ControllerProvenance(unittest.TestCase):
    def test_actual_packaging_extends_unsigned_observation_and_preserves_compiler_bytes(self):
        from tools.dev_workflow import build_provenance
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir(mode=0o700)
            (output / "component.wasm").write_bytes(b"component")
            cli = root / "operator"
            cli.write_bytes(b"packager")
            descriptor = {"build": {"adapter": {}, "outputRoot": "output"}, "artifacts": {"component": "output/component.wasm"}}
            component, packager = common.digest(b"component"), common.digest(b"packager")
            observation = {"componentDigest": component, "componentSize": 9, "materials": [], "startedAt": 10, "finishedAt": 11}
            raw = common.encode(observation)
            (output / "build-observation.json").write_bytes(raw)
            marker = {"formatVersion": 1, "observationDigest": common.digest(raw), "componentDigest": component, "packageAssembled": False}
            (output / "BUILD-COMPLETE.json").write_bytes(common.encode(marker))
            package = {"componentDigest": component, "packageDigest": "sha256:" + "a" * 64}
            with patch("tools.dev_workflow.build_provenance.time.time", return_value=12):
                build_provenance.complete(root, descriptor, cli, packager, package)
            self.assertEqual((output / "compiler-build-observation.json").read_bytes(), raw)
            joined = common.decode((output / "build-observation.json").read_bytes())
            self.assertEqual(joined["materials"], [{"name": "packager", "digest": packager, "size": 8}])
            self.assertEqual(joined["finishedAt"], 12)
            self.assertEqual(state.load(output, "controller-packaging.json")["authority"], "observed-local-build")
            with self.assertRaisesRegex(common.DevError, "compiler-observation"):
                build_provenance.complete(root, descriptor, cli, packager, package)


class NodePortableComparison(unittest.TestCase):
    def reports(self):
        component = "sha256:" + "a" * 64
        artifacts = {key: component for key in ("component", "capsule", "contracts")}
        revision = {"publicationId": "publication", "releaseDigest": component, "routeGeneration": "1"}
        row = {"id": "greeting", "status": "passed", "required": True, "outcomeKnown": True,
            "category": "success", "inputSha256": component, "payloadSha256": component,
            "platformCode": None, "fixtures": [], "targetMatches": True}
        node = {"schemaVersion": "latent.dev.test-report.v1", "environment": "node", "passed": True,
            "selection": ["greeting"], "results": [{**row, "resolvedRevision": {**revision, "revisionId": "revision"}}],
            "cleanup": "invocation-results-received-node-retained", "pendingOperation": None,
            "identity": {"hostAbi": common.HOST_ABI, "os": "linux", "profile": "local-experimental-v1",
                "admission": "enforced", "artifacts": artifacts, "expectedRevision": revision,
                "runtime": {"engine": {"wasmtimeVersion": "47.0.4"}},
                "package": {"componentDigest": component}, "deployment": {"componentDigest": component}}}
        portable = {**node, "environment": "portable", "results": [{**row, "resolvedRevision": None}],
            "cleanup": "owned-native-host-reaped", "excludedChecks": sorted(scenarios.NODE_ONLY),
            "identity": {"hostAbi": common.HOST_ABI, "productionNode": False, "artifacts": dict(artifacts),
                "runtime": {"execution": "actual-component-production-wasmtime", "runs": [{
                    "schemaVersion": "latent.dev.portable-result.v1", "environment": "portable",
                    "productionNode": False, "os": "windows", "architecture": "x86_64", "component": component,
                    "wasmtime": "47.0.4"}]}}}
        return node, portable

    def test_exact_values_match_with_explicit_node_only_exclusions(self):
        from tools.compare_dev_node_portable import compare
        result = compare(*self.reports())
        self.assertTrue(result["passed"])
        self.assertFalse(result["qualificationComplete"])
        self.assertIn("deployment", result["portableExcludedChecks"])

    def test_native_report_cannot_replace_node_or_change_component_outcome_or_cleanup(self):
        from tools.compare_dev_node_portable import compare
        for mutation in (lambda n, p: n.update(environment="portable"),
                         lambda n, p: p["identity"]["artifacts"].update(component="sha256:" + "b" * 64),
                         lambda n, p: p["results"][0].update(category="declared-error"),
                         lambda n, p: n.update(cleanup="client-cleanup-unconfirmed-node-retained"),
                         lambda n, p: p["results"][0].update(status="unsupported")):
            node, portable = self.reports()
            mutation(node, portable)
            with self.assertRaises(common.DevError):
                compare(node, portable)

    def test_policy_changes_keep_the_expected_revision_for_each_case(self):
        from tools.compare_dev_node_portable import compare
        node, portable = self.reports()
        original = dict(node["identity"]["expectedRevision"])
        node["results"][0]["expectedRevision"] = original
        node["identity"]["expectedRevision"] = {**original, "routeGeneration": "2"}
        self.assertTrue(compare(node, portable)["passed"])
        node["results"][0]["expectedRevision"] = {**original, "routeGeneration": "2"}
        with self.assertRaisesRegex(common.DevError, "selected-revision"):
            compare(node, portable)

    def test_different_denial_policies_cannot_count_as_the_same_scenario(self):
        from tools.compare_dev_node_portable import compare
        node, portable = self.reports()
        node["results"][0]["execution"] = {"grants": ["latent:clock/wall@0.1.0"],
            "deniedCapabilities": ["latent:clock/wall@0.1.0"]}
        portable["results"][0]["execution"] = {"grants": ["latent:clock/wall@0.1.0"]}
        with self.assertRaisesRegex(common.DevError, "typed-result-mismatch"):
            compare(node, portable)


@unittest.skipUnless(os.name == "posix", "Actual node probe uses Linux ownership")
class SourceNodeProbe(unittest.TestCase):
    def test_uncertain_staging_keeps_an_explicit_private_cleanup_record(self):
        from tools import dev_node_application_probe as probe
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "test-owned"
            root.mkdir(mode=0o700)
            other = parent / "another-node"
            other.write_bytes(b"retain")
            host = Mock()
            host.name = "posix"
            host.geteuid.return_value = os.geteuid() or 23001
            with patch.object(probe, "os", host), \
                    patch.object(probe, "stage_runtime", side_effect=common.DevError("owned-process-cleanup-unconfirmed", uncertain=True)), \
                    patch.object(probe.service, "request") as stop, self.assertRaises(common.DevError):
                probe.run(root, parent / "runtime", parent / "tools", {"language": "rust"}, parent / "output")
            stop.assert_not_called()
            report = state.load(root, "source-node-probe.json")
            self.assertFalse(report["passed"])
            self.assertEqual(report["cleanup"], "unconfirmed-private-workspace-retained")
            self.assertEqual(other.read_bytes(), b"retain")


class InvocationRecovery(unittest.TestCase):
    def test_unconfirmed_client_cleanup_retains_intent_and_starts_no_other_process(self):
        from tools.dev_workflow import node_invocation
        with tempfile.TemporaryDirectory() as temporary:
            controller = journal.Journal(Path(temporary), "node", "examples")
            client = Mock()
            invoke = Mock(side_effect=common.DevError("owned-process-cleanup-unconfirmed", uncertain=True))
            result = node_invocation.execute(client, controller, {}, invoke, time.monotonic() + 5)
            invoke.assert_called_once()
            client.call.assert_not_called()
            self.assertEqual(result["data"]["recovery"]["clientCleanup"], "unconfirmed")
            self.assertEqual(result["data"]["activationId"], controller.read()["pending"]["id"])

    def test_lost_result_recovers_original_terminal_without_claiming_typed_output(self):
        from tools.dev_workflow import node_invocation
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = journal.Journal(root, "node", "examples")
            calls = []
            def lost(identity):
                calls.append(identity)
                raise OSError("response lost after execution")
            def lookup(*arguments, **kwargs):
                self.assertEqual(arguments[-3:], ("activation", "get", calls[0]))
                return {"category": "success", "outcomeKnown": True, "data": {
                    "activationId": calls[0], "phase": "terminal", "terminalState": "guest_trap",
                    "terminalOutcome": {"kind": "platform-failure"}, "finalConsumption": {"cpuFuel": "1"}}}
            client = Mock()
            client.call.side_effect = lookup
            result = node_invocation.execute(client, controller, {}, lost, time.monotonic() + 5)
            self.assertEqual(len(calls), 1)
            client.call.assert_called_once()
            self.assertFalse(result["outcomeKnown"])
            self.assertEqual(result["data"]["recovery"]["disposition"], "terminal-receipt-confirmed")
            self.assertEqual(result["data"]["recovery"]["outcome"], "platform-failure")
            self.assertIsNone(controller.read()["pending"])
            self.assertEqual(controller.read()["history"][-1]["category"], "platform-failure")

    def test_unknown_receipt_retains_original_and_forbids_new_invocation(self):
        from tools.dev_workflow import node_invocation
        with tempfile.TemporaryDirectory() as temporary:
            controller = journal.Journal(Path(temporary), "node", "examples")
            client = Mock()
            client.call.return_value = {"category": "not-found", "outcomeKnown": True, "data": {}}
            invoke = Mock(return_value={"category": "transport-failure", "outcomeKnown": False, "data": {}})
            result = node_invocation.execute(client, controller, {}, invoke, time.monotonic() + 5)
            invoke.assert_called_once()
            client.call.assert_called_once()
            original = controller.read()["pending"]
            self.assertEqual(result["data"]["activationId"], original["id"])
            with self.assertRaisesRegex(common.DevError, "recover-original"):
                node_invocation.execute(client, controller, {}, invoke, time.monotonic() + 5)
            invoke.assert_called_once()
            self.assertEqual(controller.read()["pending"], original)

    @unittest.skipUnless(os.name == "posix", "Linux control socket")
    def test_socket_backlog_retries_only_connect_before_sending_one_command(self):
        import struct
        from tools.dev_workflow import service
        with tempfile.TemporaryDirectory() as temporary:
            connection = Mock()
            connection.connect.side_effect = [BlockingIOError(), None]
            connection.getsockopt.return_value = struct.pack("3i", 1, os.geteuid(), os.getegid())
            connection.recv.side_effect = [common.encode({"state": "ready"}), b""]
            manager = Mock()
            manager.__enter__ = Mock(return_value=connection)
            manager.__exit__ = Mock(return_value=False)
            with patch.object(service.socket, "socket", return_value=manager):
                result = service.request(Path(temporary), "status", timeout=1)
            self.assertEqual(result["state"], "ready")
            self.assertEqual(connection.connect.call_count, 2)
            connection.sendall.assert_called_once_with(common.encode({"operation": "status"}))

    @unittest.skipUnless(os.name == "posix", "Linux runtime ownership")
    def test_enforced_restart_requires_confirmed_cleanup_and_observes_clock_lease(self):
        from tools.dev_workflow import service
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runtime").mkdir(mode=0o700)
            config = {"supplyChain": {"mode": "enforced"}}
            for disposition in ({"state": "starting"}, {"state": "stopped", "reaped": False}):
                state.atomic(root, "lifecycle.json", disposition)
                with patch.object(service.time, "sleep") as sleep, self.assertRaisesRegex(
                        common.DevError, "confirm-stopped-owner"):
                    service.wait_for_restart_lease(root, config)
                sleep.assert_not_called()
            state.atomic(root, "lifecycle.json", {"state": "stopped", "reaped": True})
            original = (root / "lifecycle.json").read_bytes()
            clock = [10.0]
            def wait(seconds):
                clock[0] += seconds
            with patch.object(service.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(service.time, "sleep", side_effect=wait):
                service.wait_for_restart_lease(root, config)
            self.assertGreaterEqual(clock[0], 15)
            self.assertEqual((root / "lifecycle.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
