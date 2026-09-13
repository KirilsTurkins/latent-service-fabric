"""Offline checks of the real workflow harness, without child processes."""
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.phase2_operator_process import (
    WorkflowError, bounded_receipt, diagnostic_code, diagnostic_grpc, file_digest,
    stopped_record, write_candidate_manifest, write_json,
)
from tools.phase2_operator_scenario import DENIED_TOKEN, TOKEN, configure_node, route_identity
from tools.run_phase2_operator_workflow import build_identity, inventory, registry_profile


class OperatorWorkflowTests(unittest.TestCase):
    def test_final_receipt_checks_encoded_bytes_including_non_ascii(self):
        self.assertEqual(len(bounded_receipt({"v": "x" * 65528}).encode("utf-8")), 65536)
        for value in ("x" * 65529, "\u00e9" * 32765):
            with self.subTest(value_bytes=len(value.encode("utf-8"))), self.assertRaisesRegex(
                    WorkflowError, "receipt-byte-bound"):
                bounded_receipt({"v": value})

    def test_binary_identity_hashes_exact_bytes_without_retaining_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "private-host-path"
            binary.write_bytes(b"fixed executable fixture")
            cancellation = Mock()
            deadline = time.monotonic() + 5
            first = file_digest(binary, 64, cancellation, deadline)
            self.assertRegex(first, r"\Asha256:[0-9a-f]{64}\Z")
            binary.write_bytes(b"changed executable fixture")
            self.assertNotEqual(file_digest(binary, 64, cancellation, deadline), first)
            with self.assertRaisesRegex(WorkflowError, "identity-file-bound"):
                file_digest(binary, 1, cancellation, deadline)
            with self.assertRaisesRegex(WorkflowError, "workflow-deadline"):
                file_digest(binary, 64, cancellation, time.monotonic() - 1)
            args = SimpleNamespace(cli=binary, node=binary, source_commit=None)
            identity = build_identity(args, cancellation, deadline)
            self.assertNotIn("sourceCommit", identity)
            self.assertNotIn(str(binary), json.dumps(identity))
            args.source_commit = "1" * 40
            self.assertEqual(build_identity(args, cancellation, deadline)["sourceCommit"], "1" * 40)

    def test_invalid_source_commit_rejects_before_fixture_or_process_acquisition(self):
        from tools import run_phase2_operator_workflow as workflow
        for commit in ("short", "A" * 40, "1" * 40 + "\n"):
            arguments = ["workflow", "--cli", "/unused", "--node", "/unused",
                         "--fixture-root", "/unused", "--source-commit", commit]
            with self.subTest(commit=commit), patch.object(workflow.sys, "argv", arguments), \
                    patch.object(workflow, "Client") as client, \
                    self.assertRaisesRegex(WorkflowError, "source-commit"):
                workflow.main()
            client.assert_not_called()

    def test_clean_shutdown_requires_the_actual_message_and_reaped_owner(self):
        record = {"schemaVersion": "latent.standalone.status.v1", "event": "stopped",
                  "clean": True, "report": {"clean": True, "activeActivations": 0}}
        node = SimpleNamespace(buffers=[bytearray(json.dumps(record).encode())], closed=True,
                               owner=SimpleNamespace(finished=True,
                                                     process=SimpleNamespace(returncode=0, pid=42)))
        self.assertEqual(stopped_record(node), {"processId": 42, "reaped": True, "record": record})
        for owner, field, value in ((node, "closed", False), (node.owner, "finished", False),
                                    (node.owner.process, "returncode", None)):
            original = getattr(owner, field)
            setattr(owner, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(WorkflowError, "shutdown-not-clean"):
                stopped_record(node)
            setattr(owner, field, original)
        record["report"]["clean"] = False
        node.buffers[0] = bytearray(json.dumps(record).encode())
        with self.assertRaisesRegex(WorkflowError, "shutdown-not-clean"):
            stopped_record(node)
        node.buffers[0] = bytearray()
        with self.assertRaisesRegex(WorkflowError, "shutdown-record-bound"):
            stopped_record(node)

    def test_candidate_weights_are_explicit_client_copies_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "signed-fixture-deployment.json"
            original = {"kind": "Deployment", "metadata": {"name": "green", "tenant": "tests"},
                        "spec": {"service": "tests/packaging", "release": "sha256:" + "1" * 64,
                                 "route": {"weight": 10000},
                                 "resources": {"memoryBytes": 4194304, "wallTimeLimitMillis": None}}}
            write_json(source, original)
            original_bytes = source.read_bytes()
            for weight in (1000, 5000):
                destination = root / f"candidate-{weight}.json"
                self.assertEqual(write_candidate_manifest(source, destination, weight), destination)
                candidate = json.loads(destination.read_text())
                self.assertEqual(candidate["spec"]["route"]["weight"], weight)
                candidate["spec"]["route"]["weight"] = 10000
                self.assertEqual(candidate, original)
                self.assertEqual(source.read_bytes(), original_bytes)
                with self.assertRaises(FileExistsError):
                    write_candidate_manifest(source, destination, weight)

    def test_both_auth_tokens_pass_local_profile_grammar(self):
        self.assertNotEqual(TOKEN, DENIED_TOKEN)
        for token in (TOKEN, DENIED_TOKEN):
            self.assertGreaterEqual(len(token), 32)
            self.assertLessEqual(len(token), 256)
            self.assertRegex(token, r"\A[A-Za-z0-9_-]+\Z")

    def test_failure_diagnostic_retains_only_bounded_code(self):
        base = {"schemaVersion": "latent.cli.result.v1", "error": {
            "code": "invalid-configuration", "message": "PRIVATE", "details": "PRIVATE"}}
        self.assertEqual(diagnostic_code(base), "invalid-configuration")
        for code in (None, 123, "private\nvalue", "https://private", "x" * 65, {"private": True}):
            value = dict(base, error={"code": code})
            self.assertEqual(diagnostic_code(value), "unavailable")
        self.assertEqual(diagnostic_code(None), "unavailable")
        self.assertEqual(diagnostic_code({"error": base["error"]}), "unavailable")

    def test_grpc_diagnostic_requires_exact_fixed_vocabulary(self):
        for code in ("internal", "resource-exhausted", "deadline-exceeded"):
            value = {"schemaVersion": "latent.cli.result.v1", "error": {"grpcCode": code}}
            self.assertEqual(diagnostic_grpc(value), code)
        for code in (None, "private", "INTERNAL", "internal\n", 7, {"private": True}):
            value = {"schemaVersion": "latent.cli.result.v1", "error": {"grpcCode": code}}
            self.assertEqual(diagnostic_grpc(value), "absent")

    def test_inventory_compares_exact_bytes_and_bounds_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_bytes(b"{}")
            first = inventory(root)
            (root / "manifest.json").write_bytes(b"{ }")
            self.assertNotEqual(first, inventory(root))
            with (root / "large").open("wb") as output:
                output.truncate(4 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(WorkflowError, "fixture-size"):
                inventory(root)

    def test_profile_uses_separate_explicit_fixture_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ca = root / "source.der"
            ca.write_bytes(b"public test certificate")
            profile = registry_profile(root, "https://127.0.0.1:5000", ca)
            value = json.loads(profile.read_text())
            self.assertEqual(value["addresses"], ["127.0.0.1:5000"])
            self.assertEqual(value["credentialFile"], "credential.json")
            self.assertNotIn("password", value)
            self.assertEqual((root / "ca.der").read_bytes(), ca.read_bytes())

    def test_profile_rejects_unowned_endpoint_forms_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for origin in ("http://127.0.0.1:5000", "https://example.com:5000",
                           "https://u:p@127.0.0.1:5000", "https://127.0.0.1:5000/x",
                           "https://127.0.0.1:5000?token=private"):
                with self.subTest(origin=origin), self.assertRaisesRegex(WorkflowError, "registry-origin"):
                    registry_profile(root, origin, root / "absent")
            self.assertEqual(list(root.iterdir()), [])

    def test_node_fixture_enables_shared_owners_and_separate_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, node = root / "fixture", root / "node"
            fixture.mkdir()
            node.mkdir()
            write_json(fixture / "policy.json", {"formatVersion": 1})
            config = json.loads(configure_node(node, fixture, "tests").read_text())
            self.assertEqual(config["supplyChain"]["mode"], "enforced")
            self.assertEqual(config["audit"]["mode"], "durable")
            self.assertEqual(config["rollouts"]["mode"], "manual")
            self.assertEqual(config["dataDirectory"], "data")
            with self.assertRaises(FileExistsError):
                configure_node(node, fixture, "tests")

    def test_route_identity_preserves_versions_and_ignores_diagnostic_clock(self):
        base = {"generation": "7", "services": [], "bindings": [], "policyDigests": [],
                "tenant": "tests", "generatedAtUnixMillis": "1", "snapshotDigest": "old"}
        changed = dict(base, generatedAtUnixMillis="2", snapshotDigest="new")
        self.assertEqual(route_identity(base), route_identity(changed))
        self.assertNotEqual(route_identity(base), route_identity(dict(base, generation="8")))
