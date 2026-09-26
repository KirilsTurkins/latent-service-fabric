"""Offline checks of the real workflow harness, without child processes."""
from contextlib import contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.phase2_operator_process import (
    Client, WorkflowError, bounded_receipt, diagnostic_code, diagnostic_grpc, failed_call_record, file_digest,
    stopped_record, write_candidate_manifest, write_json, write_selected_deployment,
)
from tools.phase2_operator_scenario import DENIED_TOKEN, TOKEN, configure_node, route_identity
from tools.run_phase2_operator_workflow import build_identity, inventory, registry_profile


class StartupWatchdogTests(unittest.TestCase):
    def test_invalid_startup_budget_never_launches_and_valid_wait_is_globally_capped(self):
        from unittest.mock import Mock, patch
        from types import SimpleNamespace
        from tools.phase2_operator_scenario import connect
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            caller = SimpleNamespace(environment={}, cancellation=Mock(), deadline=40,
                call=Mock(return_value={"data": {"inventory": {"health": {"ready": True}, "node": {
                    "id": "test", "architecture": "x86_64", "operatingSystem": "linux",
                    "cpuFeatures": [], "trustClasses": []}}}}))
            process = Mock()
            process.line.return_value = {"endpoint": "127.0.0.1:12345"}
            with patch("tools.phase2_operator_scenario.Process", return_value=process) as launch, \
                 patch("tools.phase2_operator_scenario.time.monotonic", return_value=10):
                for invalid in (0, 121, True, float("inf")):
                    with self.assertRaises(WorkflowError):
                        connect(caller, Path("latentd"), directory, Path("config"), "tests", 1, startup_timeout=invalid)
                launch.assert_not_called()
                caller.directory = directory
                self.assertIs(connect(caller, Path("latentd"), directory, Path("config"), "tests", 1, startup_timeout=90), process)
                process.line.assert_called_once_with(40)


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
            selected = root / "selected.json"
            publication = "publication:sha256:" + "a" * 64
            self.assertEqual(write_selected_deployment(source, selected, publication), selected)
            self.assertEqual(source.read_bytes(), original_bytes)
            original["spec"]["publication"] = publication
            self.assertEqual(json.loads(selected.read_text()), original)
            for invalid in (None, "", "sha256:" + "a" * 64):
                with self.assertRaisesRegex(WorkflowError, "deployment-publication"):
                    write_selected_deployment(source, root / "invalid.json", invalid)
            self.assertFalse((root / "invalid.json").exists())
            for weight in (1000, 5000):
                destination = root / f"candidate-{weight}.json"
                self.assertEqual(write_candidate_manifest(selected, destination, weight), destination)
                candidate = json.loads(destination.read_text())
                self.assertEqual(candidate["spec"]["route"]["weight"], weight)
                candidate["spec"]["route"]["weight"] = 10000
                self.assertEqual(candidate, original)
                self.assertEqual(source.read_bytes(), original_bytes)
                with self.assertRaises(FileExistsError):
                    write_candidate_manifest(selected, destination, weight)

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


def cli_document(**changes):
    value = {"schemaVersion": "latent.cli.result.v1", "command": "audit query",
             "category": "platform-failure", "data": {}, "outcomeKnown": True,
             "requestDispatched": True, "error": {"code": "resource-exhausted",
             "message": "PRIVATE-MESSAGE", "details": ["PRIVATE-DETAIL"]}}
    return dict(value, **changes)


class FailedCallObservationTests(unittest.TestCase):
    def client(self, value, status=4):
        process = Mock()
        process.complete.return_value = subprocess.CompletedProcess(
            [], status, json.dumps(value).encode(), b"PRIVATE-STDERR")
        launch = self.enterContext(patch("tools.phase2_operator_process.Process", return_value=process))
        client = Client("PRIVATE-EXECUTABLE", Path("PRIVATE-DIRECTORY"), Mock(), time.monotonic() + 60)
        return client, process, launch

    def assert_one_process(self, process, launch):
        launch.assert_called_once()
        process.complete.assert_called_once()
        process.close.assert_called_once_with()

    def test_query_and_known_or_unknown_mutation_failures_keep_exact_certainty(self):
        for command, category, status, known, dispatched in (
            ("audit query", "platform-failure", 4, True, True),
            ("deployment delete", "platform-failure", 4, True, True),
            ("deployment apply", "transport-failure", 5, False, True),
            ("deployment apply", "local-error", 2, True, False),
        ):
            with self.subTest(command=command, known=known, dispatched=dispatched):
                value = cli_document(command=command, category=category, outcomeKnown=known,
                                     requestDispatched=dispatched)
                client, process, launch = self.client(value, status)
                with self.assertRaises(WorkflowError) as caught:
                    client.call("PRIVATE-ARGV", "PRIVATE-TOKEN")
                self.assertEqual(str(caught.exception),
                    f"cli-exit-call-1-status-{status}-code-resource-exhausted-grpc-absent")
                self.assertEqual(client.failed_call, {
                    "call": 1, "exitStatus": status, "command": command, "category": category,
                    "publicCode": "resource-exhausted", "grpcCode": "absent",
                    "outcomeKnown": known, "requestDispatched": dispatched})
                self.assertNotIn("PRIVATE", json.dumps(client.failed_call))
                self.assert_one_process(process, launch)

    def test_malformed_schema_and_non_boolean_certainty_never_infer_an_outcome(self):
        for value in (None, [], "PRIVATE", {}, cli_document(schemaVersion="PRIVATE")):
            with self.subTest(value=value):
                record = failed_call_record(value, 1, 4)
                self.assertEqual(record["command"], "unclassified")
                self.assertEqual(record["category"], "unclassified")
                self.assertEqual(record["publicCode"], "unclassified")
                self.assertEqual(record["grpcCode"], "absent")
                self.assertEqual(record["outcomeKnown"], "unavailable")
                self.assertEqual(record["requestDispatched"], "unavailable")
        for value in (None, 0, 1, "true", "false", "PRIVATE", [], {}):
            with self.subTest(certainty=value):
                record = failed_call_record(cli_document(outcomeKnown=value, requestDispatched=value), 1, 4)
                self.assertEqual(record["outcomeKnown"], "unavailable")
                self.assertEqual(record["requestDispatched"], "unavailable")

    def test_projection_has_closed_tokens_and_fixed_numeric_and_byte_bounds(self):
        for private in ("PRIVATE", "deployment delete PRIVATE", "audit query\n", "/private/path",
                        "https://private/?token=secret", "x" * 1048576, [], {}, 1, None):
            with self.subTest(kind=type(private)):
                value = cli_document(command=private, category=private,
                                     error={"code": private, "grpcCode": private})
                record = failed_call_record(value, 2 ** 63, -(2 ** 31) - 1)
                self.assertEqual(record["command"], "unclassified")
                self.assertEqual(record["category"], "unclassified")
                self.assertEqual(record["publicCode"], "unclassified")
                self.assertEqual(record["grpcCode"], "absent")
                self.assertIsNone(record["call"])
                self.assertIsNone(record["exitStatus"])
                self.assertLess(len(json.dumps(record).encode()), 512)
        value = cli_document(error={"code": "rpc-failed", "grpcCode": "deadline-exceeded"})
        record = failed_call_record(value, 2 ** 63 - 1, -9)
        self.assertEqual(record["publicCode"], "rpc-failed")
        self.assertEqual(record["grpcCode"], "deadline-exceeded")
        self.assertEqual(record["exitStatus"], -9)
        record = failed_call_record(value, True, False)
        self.assertIsNone(record["call"])
        self.assertIsNone(record["exitStatus"])

    def test_expected_nonzero_and_success_results_are_forwarded_without_a_failure_record(self):
        for status, value in ((4, cli_document(outcomeKnown=False)),
                              (0, cli_document(category="success", error=None))):
            with self.subTest(status=status):
                client, process, launch = self.client(value, status)
                with patch("tools.phase2_operator_process.json.loads", return_value=value):
                    self.assertIs(client.call("PRIVATE", codes=(status,)), value)
                self.assertIsNone(client.failed_call)
                self.assertEqual(client.calls, 1)
                self.assert_one_process(process, launch)

    def test_original_validation_failures_are_unchanged_and_observed_after_cleanup(self):
        for value, reason in ((None, "cli-result-schema"),
                              (cli_document(outcomeKnown=1), "cli-certainty"),
                              (cli_document(data=[]), "cli-data"),
                              (cli_document(), "cli-success-category")):
            with self.subTest(reason=reason):
                client, process, launch = self.client(value, 0)
                with self.assertRaisesRegex(WorkflowError, "^" + reason + "$"), \
                     patch("tools.phase2_operator_process.failed_call_record", wraps=failed_call_record) as observe:
                    client.call("PRIVATE")
                self.assert_one_process(process, launch)
                observe.assert_called_once_with(value, 1, 0)
                self.assertEqual(client.failed_call["exitStatus"], 0)

    def test_only_first_failed_call_is_retained_without_replaying_any_process(self):
        client, first, launch = self.client(cli_document())
        with self.assertRaises(WorkflowError):
            client.call("PRIVATE-FIRST")
        record = client.failed_call
        second = Mock()
        second.complete.return_value = subprocess.CompletedProcess([], 5,
            json.dumps(cli_document(command="deployment delete", outcomeKnown=False)).encode(), b"")
        launch.return_value = second
        with self.assertRaises(WorkflowError):
            client.call("PRIVATE-SECOND")
        self.assertIs(client.failed_call, record)
        self.assertEqual(client.calls, 2)
        self.assertEqual(launch.call_count, 2)
        for process in (first, second):
            process.complete.assert_called_once()
            process.close.assert_called_once_with()

    def test_process_failure_keeps_the_original_exception_and_runs_one_cleanup(self):
        client, process, launch = self.client(cli_document())
        original = WorkflowError("process-deadline")
        process.complete.side_effect = original
        with self.assertRaises(WorkflowError) as caught:
            client.call("PRIVATE")
        self.assertIs(caught.exception, original)
        self.assertIsNone(client.failed_call)
        self.assert_one_process(process, launch)

    def test_process_cleanup_failure_is_not_relabelled_as_completed_ownership(self):
        client, process, launch = self.client(cli_document())
        original = WorkflowError("owned-process-cleanup")
        process.close.side_effect = original
        with self.assertRaises(WorkflowError) as caught:
            client.call("PRIVATE")
        self.assertIs(caught.exception, original)
        self.assertIsNone(client.failed_call)
        self.assert_one_process(process, launch)

    def test_failed_projection_cannot_replace_the_original_cli_error(self):
        client, process, launch = self.client(cli_document())
        with patch("tools.phase2_operator_process.failed_call_record", side_effect=RuntimeError("PRIVATE")), \
             self.assertRaises(WorkflowError) as caught:
            client.call("PRIVATE")
        self.assertEqual(str(caught.exception),
            "cli-exit-call-1-status-4-code-resource-exhausted-grpc-absent")
        self.assertIsNone(client.failed_call)
        self.assert_one_process(process, launch)


class FailedOperatorReceiptTests(unittest.TestCase):
    def setUp(self):
        from tools import run_phase2_operator_workflow as workflow
        self.workflow = workflow
        self.events = []
        self.work = []
        temporary = tempfile.TemporaryDirectory
        self.fixture = Path(self.enterContext(temporary()))
        binary = self.fixture / "fixture-binary"
        binary.write_bytes(b"fixture executable identity, never launched")
        self.args = SimpleNamespace(cli=binary, node=binary, fixture_root=self.fixture,
                                    source_commit="1" * 40, registry_origin=None, registry_ca=None)
        self.enterContext(patch.object(workflow.argparse.ArgumentParser, "parse_args", return_value=self.args))
        self.enterContext(patch.object(workflow.sys, "platform", "linux"))
        self.enterContext(patch.object(workflow.sys, "version_info", (3, 13, 0)))
        self.enterContext(patch.object(workflow, "read_json", return_value={
            "formatVersion": 1, "tenant": "tests", "expiresAtUnixSeconds": time.time() + 600}))
        self.build = {"sourceCommit": "1" * 40, "sourceCommitKind": "supplied-build-identity",
                      "cliDigest": "sha256:" + "2" * 64, "nodeDigest": "sha256:" + "3" * 64}
        self.build_mock = self.enterContext(patch.object(workflow, "build_identity", return_value=self.build))
        self.collectors = {"tools/phase2_operator_process.py": "sha256:" + "4" * 64}
        self.collector_mock = self.enterContext(patch.object(workflow, "collector_identity",
                                                            return_value=self.collectors))
        self.enterContext(patch.object(workflow, "file_digest", return_value="sha256:" + "5" * 64))
        self.enterContext(patch.object(workflow, "registry_profile", return_value=Path("PRIVATE-PROFILE")))
        self.enterContext(patch.object(workflow, "package_workflow", return_value={}))

        @contextmanager
        def owned():
            try:
                yield Mock()
            finally:
                self.events.append("cancellation-exit")

        @contextmanager
        def work_directory(**kwargs):
            try:
                with temporary(**kwargs) as name:
                    self.work.append(Path(name))
                    yield name
            finally:
                self.events.append("temporary-exit")

        @contextmanager
        def registry(*_args):
            try:
                yield "https://127.0.0.1:12345", Path("PRIVATE-CA")
            finally:
                self.events.append("registry-exit")

        self.enterContext(patch.object(workflow, "owned_cancellation", owned))
        self.enterContext(patch.object(workflow.tempfile, "TemporaryDirectory", work_directory))
        self.enterContext(patch.object(workflow, "registry_fixture", registry))
        self.process = Mock()
        self.process.complete.return_value = subprocess.CompletedProcess(
            [], 4, json.dumps(cli_document(command="deployment delete", outcomeKnown=False)).encode(),
            b"PRIVATE-STDERR")
        self.process.close.side_effect = lambda: self.events.append("cli-close")
        self.launch = self.enterContext(patch("tools.phase2_operator_process.Process", return_value=self.process))

        def node(client, *_args):
            try:
                client.call("PRIVATE-ARGV", "PRIVATE-TOKEN")
            finally:
                self.events.append("node-finally")

        self.enterContext(patch.object(workflow, "node_workflow", side_effect=node))
        self.stdout = self.enterContext(redirect_stdout(io.StringIO()))

    def test_failed_receipt_is_after_cleanup_has_identities_and_never_claims_clean_shutdown(self):
        def render(value):
            self.assertEqual(self.events, ["cli-close", "node-finally", "registry-exit",
                                           "temporary-exit", "cancellation-exit"])
            self.assertTrue(self.work and not any(path.exists() for path in self.work))
            return bounded_receipt(value)

        with patch.object(self.workflow, "bounded_receipt", side_effect=render), \
             self.assertRaisesRegex(WorkflowError, "^node-management:cli-exit-call-1-status-4-"):
            self.workflow.main()
        value = json.loads(self.stdout.getvalue())
        self.assertIs(value["passed"], False)
        self.assertEqual(value["stage"], "node-management")
        self.assertEqual(value["failedCall"]["command"], "deployment delete")
        self.assertIs(value["failedCall"]["outcomeKnown"], False)
        self.assertEqual(value["build"], self.build)
        self.assertEqual(value["collectorDigests"], self.collectors)
        self.assertIs(value["identityRechecked"], False)
        self.assertEqual(value["nodeShutdown"], "unverified")
        for excluded in ("PRIVATE", "clean", "temporaryOutputsRemoved", "processId", "packages"):
            self.assertNotIn(excluded, self.stdout.getvalue())
        self.assertLess(len(self.stdout.getvalue().encode()), 4096)
        self.launch.assert_called_once()
        self.process.complete.assert_called_once()
        self.process.close.assert_called_once_with()
        self.build_mock.assert_called_once()
        self.collector_mock.assert_called_once()

    def test_failure_before_client_acquisition_retains_only_completed_identity_capture(self):
        self.collector_mock.side_effect = RuntimeError("PRIVATE-EXCEPTION")
        with self.assertRaisesRegex(WorkflowError, "^acquire:fixture-or-process-error$"):
            self.workflow.main()
        value = json.loads(self.stdout.getvalue())
        self.assertIs(value["passed"], False)
        self.assertIsNone(value["failedCall"])
        self.assertEqual(value["build"], self.build)
        self.assertIsNone(value["collectorDigests"])
        self.assertIsNone(value["policyFileDigest"])
        self.assertIsNone(value["fixtureMetadataDigest"])
        self.assertNotIn("PRIVATE", self.stdout.getvalue())
        self.launch.assert_not_called()
        self.assertEqual(self.events, ["cancellation-exit"])

    def test_receipt_sink_failure_does_not_replace_the_original_nonzero_failure(self):
        with patch("builtins.print", side_effect=OSError("PRIVATE-SINK")), \
             self.assertRaises(WorkflowError) as caught:
            self.workflow.main()
        self.assertEqual(str(caught.exception),
            "node-management:cli-exit-call-1-status-4-code-resource-exhausted-grpc-absent")
        self.assertEqual(self.events[-3:], ["registry-exit", "temporary-exit", "cancellation-exit"])
        self.launch.assert_called_once()
        self.process.complete.assert_called_once()
        self.process.close.assert_called_once_with()

    def test_interrupts_remain_authoritative_after_a_failed_receipt_and_existing_cleanup(self):
        for original in (SystemExit(143), KeyboardInterrupt()):
            with self.subTest(kind=type(original)), \
                 patch.object(self.workflow, "node_workflow", side_effect=original), \
                 self.assertRaises(type(original)) as caught:
                self.workflow.main()
            self.assertIs(caught.exception, original)
            value = json.loads(self.stdout.getvalue())
            self.assertIs(value["passed"], False)
            self.assertIsNone(value["failedCall"])
            self.assertEqual(value["nodeShutdown"], "unverified")
            self.assertEqual(self.events[-3:], ["registry-exit", "temporary-exit", "cancellation-exit"])
            self.launch.assert_not_called()
            self.stdout.seek(0)
            self.stdout.truncate()
