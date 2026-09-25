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
        self.assertEqual(selected["providers"]["localService"]["deployment"], "dev-callee")

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
