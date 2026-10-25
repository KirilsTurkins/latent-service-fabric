"""Reject fixture authority expansion, signature substitution and ambiguous recovery."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.dev_workflow import local_service_fixture as fixture, node_fixtures, node_test_profile, node_test_signing, paths, state, workflow_status
from tools.dev_workflow.common import DevError, digest, encode


class LocalServiceFixture(unittest.TestCase):
    def selection(self):
        return {"service": "examples/callee", "deployment": "dev-callee", "contract": "examples:callee/api@1.0.0",
                "project": "callee", "recipeSha256": "sha256:" + "1" * 64}

    def test_explicit_recipe_and_same_node_target_cannot_select_remote_or_ambient_inputs(self):
        fixture.validate(self.selection())
        for key, value in (("project", "../escape"), ("project", "C:/outside"), ("service", "*"),
                           ("contract", "*"), ("deployment", "../other"), ("recipeSha256", "untrusted"),
                           ("endpoint", "https://foreign-node"), ("tenant", "another-tenant")):
            with self.assertRaises(DevError):
                fixture.validate(dict(self.selection(), **{key: value}))

    def test_provider_scope_and_declared_kind_are_required_for_fixture_initialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = {"localService": self.selection()}
            raw = encode(selected)
            paths.write_new(root / "fixture.json", raw)
            case = {"fixtures": [{"id": "local", "kind": "real-provider", "identity": digest(raw), "configuration": "fixture.json"}]}
            installed = {"localService": {"capability": fixture.PROVIDER[0], "profile": fixture.PROVIDER[1],
                "service": "examples/callee", "configurationEpoch": "1"}}
            self.assertEqual(node_fixtures.initialized(root, [case], selected), set())
            self.assertEqual(node_fixtures.initialized(root, [case], selected, providers=installed), {"local"})
            for key, value in (("service", "examples/foreign"), ("profile", "fake"), ("configurationEpoch", "2")):
                changed = copy.deepcopy(installed)
                changed["localService"][key] = value
                self.assertEqual(node_fixtures.initialized(root, [case], selected, providers=changed), set())
            case["fixtures"][0]["kind"] = "test-adapter"
            self.assertEqual(node_fixtures.initialized(root, [case], selected, providers=installed), set())

    def test_two_cells_and_explicit_child_budget_only_follow_a_selected_local_fixture(self):
        original = {"securityProfile": "local-experimental-v1", "audit": {"mode": "durable"}}
        descriptor = {"language": "rust", "tenant": "examples", "service": "examples/caller"}
        ordinary, _ = node_test_profile.configuration(original, descriptor)
        self.assertNotIn("maximumChildCalls", ordinary["budgetProfile"])
        selected, _ = node_test_profile.configuration(original, descriptor, {"localService": self.selection()}, root=Path("test-local"))
        self.assertEqual(selected["cells"][0]["capacity"], 2)
        self.assertEqual(selected["budgetProfile"]["maximumChildCalls"], 16)
        self.assertEqual(selected["budgetProfile"]["maximumLiveChildren"], 1)
        self.assertNotIn("developmentLocalServiceObservation", selected)
        observed, _ = node_test_profile.configuration(original, descriptor, {"localService": self.selection()},
            root=Path("test-local"), local_service_refusal_observation=True)
        self.assertEqual(observed["developmentLocalServiceObservation"], {"formatVersion": 1, "consent": True,
            "purpose": "disposable-local-service-refusal-observation"})
        self.assertNotIn("developmentLocalServiceObservation", ordinary)
        expected = dict(observed); del expected["developmentLocalServiceObservation"]
        self.assertEqual(encode(expected), encode(selected))
        for flag in (1, "yes", None):
            with self.assertRaises(DevError):
                node_test_profile.configuration(original, descriptor, {"localService": self.selection()},
                    root=Path("test-local"), local_service_refusal_observation=flag)
        for flag in (False, True):
            with self.assertRaises(DevError):
                node_test_profile.configuration(dict(original, developmentLocalServiceObservation={}), descriptor,
                    {"localService": self.selection()}, root=Path("test-local"), local_service_refusal_observation=flag)
        self.assertEqual(selected["providers"]["localService"]["deployment"], "dev-callee")

    @unittest.skipUnless(os.name == "posix", "Linux source-node probe owns the log RPC")
    def test_refusal_probe_option_leaves_ordinary_log_rpc_path_untouched(self):
        from contextlib import ExitStack
        from tools import dev_node_application_probe as probe
        for enabled in (False, True):
            with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                root = Path(temporary) / "test-owned"
                root.mkdir()
                state.atomic(root, "lifecycle.json", {"state": "ready"})
                stack.enter_context(patch.object(probe, "stage_runtime", return_value={}))
                prepare = stack.enter_context(patch.object(probe.node_test_profile, "prepare", return_value={}))
                stack.enter_context(patch.object(probe.service, "start", return_value={}))
                stack.enter_context(patch.object(probe.helper, "deploy", return_value={}))
                stack.enter_context(patch.object(probe.node_scenarios, "run", return_value={"passed": False, "results": []}))
                stack.enter_context(patch.object(probe, "failed_diagnostics", return_value=[]))
                requested = stack.enter_context(patch.object(probe.service, "request", side_effect=lambda _root, operation, **kw:
                    {"logs": ""} if operation == "logs" else {"state": "stopped", "reaped": True, "cleanShutdown": True}))
                with self.assertRaisesRegex(DevError, "source-node-application-scenarios-failed"):
                    probe.run(root, Path(temporary) / "tools", Path(temporary) / "payload",
                        {"language": "rust"}, Path(temporary) / "output", fixtures={"localService": self.selection()},
                        local_service_refusal_observation=enabled)
                self.assertEqual([call.args[1] for call in requested.call_args_list].count("logs"), int(enabled))
                self.assertEqual(prepare.call_args.kwargs.get("local_service_refusal_observation", False), enabled)
                retained = state.load(Path(temporary) / "output", "probe.json")
                self.assertEqual("localServiceRefusals" in retained, enabled)
                self.assertFalse(retained["passed"])

    def refusal_row(self, identity):
        from tools.dev_workflow import local_service_refusals as observed
        return {"schemaVersion": observed.SCHEMA, "activationId": identity, "sampling": observed.SAMPLING,
            "stage": "child-start", "code": "resource-exhausted", "reason": "typed-budget",
            "typedBudget": {"dimension": "memory-bytes", "limit": 1024, "consumed": 900, "requested": 200},
            "remaining": {"cpuFuel": 100, "memoryBytes": 124, "childCalls": 14, "wallTimeLimitMillis": 1000},
            "descendants": {"depth": 0, "liveChildren": 1, "liveDescendants": 1, "reservedMemoryBytes": 8388608,
                            "liveObservedChildMemoryBytes": 1024, "closed": False}}

    def test_refusal_records_bind_the_failed_activation_after_expected_negative_cases(self):
        from tools.dev_workflow import local_service_refusals as observed
        a, b = "dev-" + "1" * 32, "dev-" + "2" * 32
        negative, failed = self.refusal_row(a), self.refusal_row(b)
        negative.update(code="permission-denied", reason="unclassified", typedBudget=None)
        cases = {"results": [{"id": "expected-denial", "activationId": a, "status": "passed"},
                             {"id": "two-fresh-children", "activationId": b, "status": "failed"}]}
        logs = "".join(observed.PREFIX + encode(row).decode() for row in (negative, failed))
        # Exercise the maintained stderr retention implementation, then the same
        # JSON transport encode/decode used by service.logs; no prefix rewriting.
        from tools.dev_workflow.node_output import NodeOutput
        from tools.dev_workflow.common import decode
        import threading
        retained = object.__new__(NodeOutput)
        retained.tokens, retained.retained, retained.lock = [], bytearray(), threading.Lock()
        for line in logs.splitlines(keepends=True):
            retained._line(line.encode(), False)
        transported = decode(encode({"logs": retained.logs()}))["logs"]
        self.assertEqual(transported, logs)
        self.assertTrue(transported.startswith(observed.PREFIX))
        value = observed.observe(transported, cases)
        self.assertEqual(value["cases"][1]["refusal"], failed)
        self.assertEqual(value["cases"][1]["case"], "two-fresh-children")
        self.assertEqual(cases["results"][1]["status"], "failed")
        self.assertEqual(observed.observe("", cases)["cases"][1]["state"], "unknown-no-retained-refusal")
        self.assertEqual(observed.observe(logs + observed.PREFIX + encode(failed).decode(), cases)["state"], "unavailable")

    def test_refusal_reader_rejects_coerced_private_forged_or_foreign_observations(self):
        from tools.dev_workflow import local_service_refusals as observed
        identity = "dev-" + "1" * 32
        row = self.refusal_row(identity)
        cases = {"results": [{"id": "two-fresh-children", "activationId": identity}]}
        mutations = [("stage", "private-stage"), ("code", "private-code"), ("reason", "private-reason"),
                     ("activationId", "dev-" + "2" * 32), ("message", "private-text")]
        for key, value in mutations:
            changed = copy.deepcopy(row); changed[key] = value
            self.assertEqual(observed.observe(observed.PREFIX + encode(changed).decode(), cases)["state"], "unavailable")
        for value in [True, -1, "1024", 18446744073709551616]:
            changed = copy.deepcopy(row); changed["typedBudget"]["limit"] = value
            self.assertEqual(observed.observe(observed.PREFIX + encode(changed).decode(), cases)["state"], "unavailable")
        for malformed in (None, 1, "case", []):
            self.assertEqual(observed.observe("", {"results": [malformed]})["state"], "unavailable")
        duplicated = encode(row).decode().replace('"limit":1024', '"limit":1,"limit":1024')
        self.assertEqual(observed.observe(observed.PREFIX + duplicated, cases)["state"], "unavailable")

    def test_group_signing_binds_both_distinct_component_identities_and_the_entire_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = b"{}\n"
            paths.write_new(root / "policy.json", policy)
            intent = {"component": "sha256:" + "a" * 64, "source": "source-a", "attempt": "attempt-a",
                      "dependencies": [{"component": "sha256:" + "b" * 64, "source": "source-b", "attempt": "attempt-b"}]}
            record = {"schemaVersion": "latent.capsule.demo.v1", "tenant": "examples", "trust": "isolated-short-lived-demo-only",
                "expiresAtUnixSeconds": 1, "policyDigest": digest(policy), "releases": [
                    {"name": "callee", "componentDigest": intent["dependencies"][0]["component"], "packageDigest": "package-b"},
                    {"name": "caller", "componentDigest": intent["component"], "packageDigest": "package-a"}]}
            for name in ("caller", "callee"):
                (root / name).mkdir()
                paths.write_new(root / name / "package.json", encode({"name": name}))
            state.atomic(root, "release-set.json", record)
            selected = node_test_signing._observe(root, intent)
            self.assertEqual(selected["name"], "caller")
            self.assertEqual(selected["dependencyPackages"][0]["name"], "callee")
            (root / "callee/package.json").write_bytes(b"changed")
            self.assertNotEqual(node_test_signing._observe(root, intent)["inventory"], selected["inventory"])
            record["releases"][0]["componentDigest"] = intent["component"]
            state.atomic(root, "release-set.json", record)
            with self.assertRaisesRegex(DevError, "component-mismatch"):
                node_test_signing._observe(root, intent)

    def test_pending_callee_operation_is_visible_and_cannot_be_treated_as_deployed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / fixture.CHILD
            child.mkdir(mode=0o700)
            pending = {"id": "original", "kind": "deployment", "requestDigest": "digest",
                       "node": "owned", "tenant": "examples", "intent": {"deployment": "dev-callee"}}
            state.atomic(child, "operations.json", {"pending": pending})
            state.atomic(root, "local-service-build.json", {})
            self.assertEqual(workflow_status.observe(root)["localService"]["pendingOperation"], pending)
            with patch.object(fixture, "signing_input", return_value=(None, {}, {})):
                with self.assertRaisesRegex(DevError, "recover-original-local-service") as failure:
                    fixture.observe(root, None)
                self.assertTrue(failure.exception.uncertain)
            self.assertEqual(state.load(child, "operations.json")["pending"], pending)

    @unittest.skipUnless(os.name == "posix", "Linux helper owns the callee compiler")
    def test_callee_cancellation_routes_only_to_the_exact_owned_build_identity(self):
        from tools.dev_workflow import helper
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "test-owned"
            child = root / fixture.CHILD
            neighbor = Path(temporary) / "test-neighbor"
            root.mkdir(mode=0o700)
            child.mkdir(mode=0o700)
            neighbor.mkdir(mode=0o700)
            state.atomic(child, "project.json", {})
            for directory, identity in ((child, "a" * 32), (neighbor, "b" * 32)):
                state.atomic(directory, "active-build.json", {"id": identity, "state": "running",
                    "guestInstance": {}, "attempt": None, "reason": None})
            with patch.object(helper, "root_directory", return_value=Path(temporary)), \
                    patch.object(helper.state, "workspace", return_value=root):
                result = helper.dispatch({"operation": "cancel-build", "workspace": "test-owned",
                    "arguments": {"buildId": "b" * 32, "reason": "cancelled"}})
                self.assertFalse(result["accepted"])
                result = helper.dispatch({"operation": "cancel-build", "workspace": "test-owned",
                    "arguments": {"buildId": "a" * 32, "reason": "cancelled"}})
                self.assertTrue(result["accepted"])
            self.assertEqual(state.load(child, "build-cancel.json")["id"], "a" * 32)
            self.assertFalse((root / "build-cancel.json").exists())
            self.assertFalse((neighbor / "build-cancel.json").exists())


if __name__ == "__main__":
    unittest.main()
