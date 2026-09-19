"""Bounds and fixture identities, not a substitute for real T1 qualification."""
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tools.phase2_operator_process import WorkflowError, read_json, write_json
from tools.phase3_web_scenario import (
    MIB, PREPARATION_MILLIS, budget, configure_angular_node, deployment_manifest,
    fixture_metadata, invocation_arguments, prepare, tree_inventory,
)


def client(root):
    return SimpleNamespace(directory=root, deadline=time.monotonic() + 30,
                           cancellation=SimpleNamespace(check=lambda: None), call=Mock())


class AngularT1WorkflowTests(unittest.TestCase):
    def test_configuration_keeps_external_profile_protected_key_and_independent_compile_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, node = root / "fixture", root / "node"
            fixture.mkdir()
            node.mkdir()
            write_json(fixture / "policy.json", {"formatVersion": 1})
            compiler = root / "compiler"
            compiler.write_bytes(b"bounded approved binary fixture")
            path, configured = configure_angular_node(client(root), node, fixture, compiler)
            self.assertEqual(read_json(path), configured)
            self.assertEqual(configured["securityProfile"], "external-capsule-v1")
            self.assertEqual(configured["supplyChain"]["mode"], "enforced")
            self.assertEqual(configured["rendererProfile"], "angular-ssr-component-v1")
            self.assertEqual(configured["execution"]["maximumWallTimeMillis"], 5000)
            self.assertEqual(configured["isolatedAot"]["process"]["jobTimeoutMillis"], PREPARATION_MILLIS)
            self.assertEqual(configured["isolatedAot"]["keyFile"], "native.key")
            self.assertEqual(len((node / "native.key").read_bytes()), 32)
            self.assertNotIn(bytes([83]) * 32, path.read_bytes())
            self.assertFalse((node / "data").exists())
            self.assertNotIn("providers", configured)
            self.assertEqual(configured["httpIngress"]["authentication"]["mode"], "public-origins")

    def test_prepare_is_one_explicit_call_and_never_claims_execution_authority(self):
        prepared = client(Path("unused"))
        publication = "publication:sha256:" + "a" * 64
        prepared.call.return_value = {"outcomeKnown": True, "data": {
            "prepared": True, "executionAuthorized": False,
            "publication": {"id": publication}, "lifecycleGeneration": "7"}}
        prepare(prepared, publication, 7)
        prepared.call.assert_called_once()
        arguments = prepared.call.call_args
        self.assertEqual(arguments.args[:4], ("--rpc-timeout-ms", str(PREPARATION_MILLIS), "web", "prepare"))
        self.assertEqual(arguments.kwargs["timeout"], 310)
        for field, value in (("executionAuthorized", True), ("prepared", False), ("lifecycleGeneration", "8")):
            changed = copy.deepcopy(prepared.call.return_value)
            changed["data"][field] = value
            prepared.call.return_value = changed
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                prepare(prepared, publication, 7)

    def test_selected_deployment_never_fabricates_a_capsule_or_capability_grant(self):
        record = {"service": "angular-hello", "componentDigest": "sha256:" + "b" * 64}
        selected = "publication:sha256:" + "a" * 64
        manifest = deployment_manifest(record, selected)
        self.assertEqual(manifest["spec"]["publication"], selected)
        self.assertEqual(manifest["spec"]["release"], record["componentDigest"])
        self.assertEqual(manifest["spec"]["grants"], [])
        self.assertEqual(manifest["spec"]["resources"], budget())
        self.assertEqual(budget()["memoryBytes"], 256 * MIB)
        self.assertEqual(budget()["outboundRequests"], 0)

    def test_public_web_invocation_has_no_guest_supplied_actor_or_tenant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = invocation_arguments(client(root), {"service": "angular-hello"}, "/spin", "cancel")
            request = read_json(root / "cancel-input.json")
            self.assertEqual(len(request), 1)
            self.assertNotIn("principal", request[0])
            self.assertNotIn("tenant", request[0])
            self.assertEqual(request[0]["path"], "/spin")
            self.assertEqual(arguments[:3], ["--rpc-timeout-ms", "5000", "invoke"])
            self.assertNotIn("outboundRequests", read_json(root / "cancel-budget.json"))

    def test_inventory_hashes_large_artifacts_incrementally_with_finite_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "image").write_bytes(b"x" * 32768)
            (root / "lock").touch()
            observed = tree_inventory(root, client(root), maximum_bytes=32768)
            self.assertEqual(observed["image"][0], 32768)
            self.assertEqual(observed["lock"], (0, None))
            with self.assertRaisesRegex(WorkflowError, "angular-inventory-bytes"):
                tree_inventory(root, client(root), maximum_bytes=32767)
            expired = client(root)
            expired.deadline = time.monotonic() - 1
            with self.assertRaisesRegex(WorkflowError, "workflow-deadline"):
                tree_inventory(root, expired)

    def test_fixture_requires_actual_observation_and_independent_package_identity(self):
        metadata = {"schemaVersion": "latent.phase3.angular.fixture.v1", "tenant": "tests",
                    "actualAngularBuild": True, "reproducibility": "not-checked",
                    "dependencyCompleteness": "declared-inputs-incomplete", "fixtures": [
                        {"name": name, "packageDigest": "sha256:" + digit * 64,
                         "componentDigest": "sha256:" + "d" * 64}
                        for name, digit in (("angular", "a"), ("alternate", "b"), ("missing-sbom", "c"))]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "fixture.json"
            write_json(path, metadata)
            self.assertEqual(set(fixture_metadata(root)[1]), {"angular", "alternate", "missing-sbom"})
            for field, value in (("actualAngularBuild", False), ("reproducibility", "reproducible"),
                                 ("dependencyCompleteness", "complete")):
                changed = copy.deepcopy(metadata)
                changed[field] = value
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(WorkflowError):
                    fixture_metadata(root)


if __name__ == "__main__":
    unittest.main()
