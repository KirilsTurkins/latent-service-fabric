"""Finite evidence and cleanup controls; process doubles confer no runtime qualification."""
from contextlib import nullcontext, redirect_stdout
import io
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import run_java_early_http_qualification as early
from tools import run_java_pending_recovery_qualification as pending
from tools import run_java_transaction_http_qualification as terminal
from tools.build_process_signals import _Cancellation
from tools.java_transaction_qualification import evidence as observations, lifecycle
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient, encoded, native
from tools.java_transaction_qualification.inputs import digest


def cancellation():
    value = _Cancellation()
    value.previous[signal.SIGTERM] = signal.SIG_DFL
    return value


def process_double(stdout, stderr, *, status=0, finished=True, error=None, closing=None):
    instances = []

    class Process:
        def __init__(self, arguments, directory, environment, cancel, *, maximum):
            self.arguments, self.maximum = arguments, maximum
            self.buffers, self.closed = [bytearray(stdout), bytearray(stderr)], False
            self.owner = SimpleNamespace(process=SimpleNamespace(returncode=None), finished=False)
            self.completions, self.close_calls = [], 0
            instances.append(self)

        def complete(self, deadline):
            self.completions.append(deadline)
            if error is not None:
                raise error
            return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=status)

        def line(self, deadline):
            self.completions.append(deadline)
            return {"endpoint": "127.0.0.1:12345"}

        def close(self):
            self.close_calls += 1
            if closing is not None:
                closing(self)
            self.closed, self.owner.finished = True, finished
            self.owner.process.returncode = status

    return Process, instances


def client(root, evidence):
    directory = root / "client"
    directory.mkdir()
    return RecordingClient(Path("fixture-cli"), directory, cancellation(), 200, evidence, phase4=True)


def full_evidence(directory, count=1024):
    evidence = Evidence(directory)
    for ordinal in range(count):
        evidence.write(f"original-{ordinal:04d}.bin", b"x")
    return evidence


def arguments(output):
    return SimpleNamespace(output=output, native_source_commit="1" * 40,
        conductor_source_commit="1" * 40, recovery_source_commit="1" * 40,
        recovery_helper=None, resume_candidate=None, candidate_digest="sha256:" + "2" * 64,
        prepare_authority_only=False, timeout=1200, cli=Path("fixture-cli"),
        selection=Path("fixture-selection.json"), selection_digest="sha256:" + "3" * 64)


class EvidenceStreams(unittest.TestCase):
    def test_duplicate_empty_streams_never_spend_the_original_file_or_byte_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Evidence(Path(temporary) / "evidence")
            for _ in range(1025):
                self.assertEqual(evidence.stream("same.stderr", b""),
                    {"empty": True, "bytes": 0, "digest": digest(b"")})
            self.assertEqual(evidence.summary(), {"files": [], "bytes": 0, "cases": []})
            self.assertEqual(list(evidence.directory.iterdir()), [])
            self.assertEqual(evidence.stream("same.stderr", b"later")["path"], "same.stderr")

    def test_empty_streams_still_require_safe_names_and_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Evidence(Path(temporary) / "evidence")
            for name in ("", "../escape", "UPPER", "x/child", "a" * 97, None):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    evidence.stream(name, b"")
            for raw in ("", bytearray(), memoryview(b""), None, []):
                with self.subTest(kind=type(raw).__name__), self.assertRaises(ValueError):
                    evidence.stream("safe.stderr", raw)
            self.assertEqual(list(evidence.directory.iterdir()), [])
            self.assertEqual(evidence.total, 0)

    def test_nonempty_streams_keep_raw_bytes_original_names_and_exclusive_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Evidence(Path(temporary) / "evidence")
            raw = b"\x00original\xff\n"
            row = evidence.stream("original.stdout", raw)
            self.assertEqual(row, {"path": "original.stdout", "bytes": len(raw), "digest": digest(raw)})
            self.assertEqual((evidence.directory / row["path"]).read_bytes(), raw)
            with self.assertRaises(FileExistsError):
                evidence.stream("original.stdout", b"replacement")
            self.assertEqual(evidence.summary(), {"files": [row], "bytes": len(raw), "cases": []})

    def test_nonempty_streams_keep_original_one_mib_and_1024_file_caps(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = full_evidence(Path(temporary) / "evidence")
            self.assertEqual(evidence.stream("empty.stderr", b"")["bytes"], 0)
            with self.assertRaisesRegex(ValueError, "original-evidence-byte-bound"):
                evidence.stream("overflow.stdout", b"x")
            self.assertEqual(len(evidence.files), 1024)
            self.assertFalse((evidence.directory / "overflow.stdout").exists())
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Evidence(Path(temporary) / "evidence")
            with self.assertRaisesRegex(ValueError, "original-evidence-byte-bound"):
                evidence.stream("oversize.stdout", b"x" * 1048577)
            self.assertEqual(evidence.files, [])

    def test_cli_records_both_descriptors_only_after_original_process_close(self):
        raw = encoded({"schemaVersion": "latent.cli.result.v1", "category": "success",
                       "outcomeKnown": True, "data": {"observed": True}})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root / "evidence")
            cli = client(root, evidence)
            process, instances = process_double(raw, b"")
            with patch.object(observations, "Process", process), \
                    patch.object(observations.time, "monotonic", return_value=100):
                self.assertEqual(cli.call("node", "get", "not-recorded-argument")["data"], {"observed": True})
            actual = instances[0]
            self.assertEqual((actual.close_calls, actual.completions, actual.maximum), (1, [125], 1048576))
            record = json.loads((evidence.directory / "cli-001-process.json").read_bytes())
            self.assertEqual(record, {"exitStatus": 0, "reaped": True,
                "stdout": {"path": "cli-001.stdout", "bytes": len(raw), "digest": digest(raw)},
                "stderr": {"empty": True, "bytes": 0, "digest": digest(b"")}})
            self.assertEqual((evidence.directory / "cli-001.stdout").read_bytes(), raw)
            self.assertFalse((evidence.directory / "cli-001.stderr").exists())
            self.assertNotIn("not-recorded-argument", encoded(record).decode())

    def test_cli_incomplete_capture_keeps_false_retirement_and_both_empty_descriptors(self):
        original = TimeoutError("original-completion-timeout")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root / "evidence")
            process, instances = process_double(b"", b"", status=-9, finished=False, error=original)
            with patch.object(observations, "Process", process), \
                    patch.object(observations.time, "monotonic", return_value=100):
                with self.assertRaises(TimeoutError) as caught:
                    client(root, evidence).call("node", "get")
            self.assertIs(caught.exception, original)
            record = json.loads((evidence.directory / "cli-001-process.json").read_bytes())
            self.assertEqual((record["exitStatus"], record["reaped"]), (-9, False))
            self.assertEqual(record["stdout"], record["stderr"])
            self.assertTrue(record["stdout"]["empty"])
            self.assertEqual(len(evidence.files), 1)
            self.assertEqual(instances[0].close_calls, 1)

    def test_cli_nonzero_exit_keeps_original_error_and_nonempty_stderr(self):
        raw = encoded({"schemaVersion": "latent.cli.result.v1", "category": "platform",
                       "outcomeKnown": False, "data": {}})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root / "evidence")
            process, _ = process_double(raw, b"original stderr\x00", status=5)
            with patch.object(observations, "Process", process), \
                    patch.object(observations.time, "monotonic", return_value=100):
                with self.assertRaisesRegex(ValueError, "cli-exit-call-1-status-5"):
                    client(root, evidence).call("transaction", "lookup")
            record = json.loads((evidence.directory / "cli-001-process.json").read_bytes())
            self.assertEqual((record["exitStatus"], record["reaped"]), (5, True))
            self.assertEqual((evidence.directory / record["stderr"]["path"]).read_bytes(), b"original stderr\x00")

    def test_native_keeps_binary_outputs_original_deadline_and_actual_retirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root / "evidence")
            cli = client(root, evidence)
            process, instances = process_double(b"\x00native\xff", b"native-stderr")
            with patch.object(observations, "Process", process), \
                    patch.object(observations.time, "monotonic", return_value=100):
                self.assertEqual(native(cli, Path("fixture-helper"), "native-check", "inspect"), b"\x00native\xff")
            record = json.loads((evidence.directory / "native-check-process.json").read_bytes())
            self.assertEqual((record["exitStatus"], record["reaped"]), (0, True))
            for name, raw in (("stdout", b"\x00native\xff"), ("stderr", b"native-stderr")):
                self.assertEqual(record[name]["digest"], digest(raw))
                self.assertEqual((evidence.directory / record[name]["path"]).read_bytes(), raw)
            self.assertEqual((instances[0].completions, instances[0].close_calls), ([160], 1))

    def test_native_timeout_retains_partial_output_and_original_exception(self):
        original = TimeoutError("native-original-timeout")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root / "evidence")
            process, _ = process_double(b"partial", b"", status=-9, error=original)
            with patch.object(observations, "Process", process), \
                    patch.object(observations.time, "monotonic", return_value=100):
                with self.assertRaises(TimeoutError) as caught:
                    native(client(root, evidence), Path("fixture-helper"), "native-check")
            self.assertIs(caught.exception, original)
            record = json.loads((evidence.directory / "native-check-process.json").read_bytes())
            self.assertEqual((record["exitStatus"], record["reaped"]), (-9, True))
            self.assertEqual((evidence.directory / record["stdout"]["path"]).read_bytes(), b"partial")
            self.assertTrue(record["stderr"]["empty"])

    def test_observed_207_cli_triplets_and_403_other_files_leave_inventory_room(self):
        raw = encoded({"schemaVersion": "latent.cli.result.v1", "category": "success",
                       "outcomeKnown": True, "data": {}})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = full_evidence(root / "evidence", 403)
            cli = client(root, evidence)
            process, instances = process_double(raw, b"")
            with patch.object(observations, "Process", process), \
                    patch.object(observations.time, "monotonic", return_value=100):
                for _ in range(207):
                    cli.call("node", "get")
            self.assertEqual((cli.calls, len(instances), len(evidence.files)), (207, 207, 817))
            self.assertTrue(all(value.close_calls == 1 and value.closed and value.owner.finished for value in instances))
            record = {"passed": True, "signedGuestExecutionQualified": True}
            self.assertTrue(terminal.finalize_inventory(record, evidence, "inventory"))
            self.assertEqual(len(evidence.files), 818)
            self.assertEqual(record["evidenceInventory"]["path"], "inventory.json")
            self.assertEqual(Evidence.retain(evidence.directory, evidence.summary()).summary(), evidence.summary())


class QualificationCleanup(unittest.TestCase):
    def owners(self, cancel, errors=(None, None), *, cancel_on_node=False):
        events = []
        owners = []
        for name, error in zip(("node", "recipient"), errors):
            def close(name=name, error=error):
                events.append((name, cancel.depth))
                if cancel_on_node and name == "node":
                    cancel.handle(signal.SIGTERM, None)
                if error is not None:
                    raise error
            owners.append(SimpleNamespace(close=close))
        return owners, events

    def test_both_owners_close_and_first_cleanup_error_survives_with_bounded_safe_metadata(self):
        cancel, record = cancellation(), {}
        original = RuntimeError("node-cleanup-refused")
        owners, events = self.owners(cancel, (original, OSError("secret /private/path token=value")))
        with self.assertRaises(RuntimeError) as caught:
            terminal.close_owners(record, cancel, *owners)
        self.assertIs(caught.exception, original)
        self.assertEqual(events, [("node", 1), ("recipient", 1)])
        self.assertEqual(record["cleanupFailures"], [
            {"owner": "node", "failureType": "RuntimeError", "fixedFailureReason": "node-cleanup-refused"},
            {"owner": "recipient", "failureType": "OSError"}])
        self.assertNotIn("secret", encoded(record).decode())

    def test_explicit_body_primary_is_not_replaced_by_cleanup_failures(self):
        cancel, record = cancellation(), {}
        owners, events = self.owners(cancel, (RuntimeError("node-cleanup"), KeyboardInterrupt()))
        original = ValueError("original-body-refusal")
        primary = None
        with self.assertRaises(ValueError) as caught:
            try:
                raise original
            except BaseException as error:
                primary = error
                raise
            finally:
                terminal.close_owners(record, cancel, *owners, primary=primary)
        self.assertIs(caught.exception, original)
        self.assertEqual(len(record["cleanupFailures"]), 2)
        self.assertEqual(events, [("node", 1), ("recipient", 1)])

    def test_unrelated_ambient_except_cannot_suppress_local_cleanup_failure(self):
        cancel = cancellation()
        original = RuntimeError("local-cleanup-refusal")
        owners, events = self.owners(cancel, (original, None))
        try:
            raise ValueError("unrelated-caller-error")
        except ValueError:
            with self.assertRaises(RuntimeError) as caught:
                terminal.close_owners({}, cancel, *owners)
        self.assertIs(caught.exception, original)
        self.assertEqual(len(events), 2)

    def test_pending_signal_delivers_only_after_both_closes_and_metadata(self):
        cancel, record = cancellation(), {}
        owners, events = self.owners(cancel, (RuntimeError("node-cleanup"), OSError("recipient-cleanup")),
                                     cancel_on_node=True)
        with self.assertRaises(SystemExit) as caught:
            terminal.close_owners(record, cancel, *owners)
        self.assertEqual(caught.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(events, [("node", 1), ("recipient", 1)])
        self.assertEqual(len(record["cleanupFailures"]), 2)
        self.assertEqual((cancel.depth, cancel.pending), (0, None))

    def test_original_pending_signal_precedence_over_body_error_is_preserved(self):
        cancel, record = cancellation(), {}
        owners, events = self.owners(cancel, cancel_on_node=True)
        primary = None
        with self.assertRaises(SystemExit) as caught:
            try:
                raise ValueError("body-before-signal")
            except BaseException as error:
                primary = error
                raise
            finally:
                terminal.close_owners(record, cancel, *owners, primary=primary)
        self.assertEqual(caught.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(events, [("node", 1), ("recipient", 1)])

    def test_absent_owners_do_not_swallow_pending_cancellation(self):
        cancel = cancellation()
        cancel.handle(signal.SIGTERM, None)
        with self.assertRaises(SystemExit):
            terminal.close_owners({}, cancel, None, None)

    def test_started_record_failure_clears_node_owner_before_close_and_prevents_duplicate_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = Evidence(root / "evidence")
            cli = SimpleNamespace(environment={}, cancellation=cancellation(), deadline=200,
                directory=root, evidence=evidence, call=Mock(return_value={"data": {"inventory": {"health": {"ready": True}}}}))
            node = lifecycle.Node(cli, Path("fixture-node"), root)
            closed_owners = []
            process, instances = process_double(b"original-node-output", b"",
                closing=lambda _process: closed_owners.append((node.process, cli.node)))
            original_record = evidence.record
            def record(name, value):
                if name == "node-1-started":
                    raise OSError("started-record-write-failed")
                return original_record(name, value)
            with patch.object(lifecycle, "Process", process), patch.object(evidence, "record", side_effect=record), \
                    patch.object(lifecycle.time, "monotonic", return_value=100):
                with self.assertRaisesRegex(OSError, "started-record-write-failed"):
                    node.start(root / "fixture-configuration.json")
                node.close()
            self.assertEqual(closed_owners, [(None, None)])
            self.assertIsNone(node.process)
            self.assertEqual(instances[0].close_calls, 1)
            self.assertEqual((evidence.directory / "node-1-startup.stdout").read_bytes(), b"original-node-output")
            self.assertEqual((evidence.directory / "node-1-startup.stderr").read_bytes(), b"")
            failure = json.loads((evidence.directory / "node-1-startup-failure.json").read_bytes())
            self.assertEqual((failure["exitStatus"], failure["reaped"]), (0, True))


class EvidenceFinalization(unittest.TestCase):
    def test_last_original_file_slot_can_hold_the_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = full_evidence(Path(temporary) / "evidence", 1023)
            record = {"passed": True}
            self.assertTrue(terminal.finalize_inventory(record, evidence, "inventory"))
            self.assertEqual(len(evidence.files), 1024)
            self.assertTrue(record["passed"])
            stored = json.loads((evidence.directory / "inventory.json").read_bytes())
            self.assertEqual(len(stored["files"]), 1023)

    def test_full_inventory_preserves_primary_failure_and_still_serializes_failed_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = full_evidence(root / "evidence")
            record = {"passed": True, "signedGuestExecutionQualified": True,
                "failedStage": "actual-http", "failureType": "ValueError",
                "fixedFailureReason": "original-query-refusal", "evidenceInventory": {"invented": True}}
            self.assertFalse(terminal.finalize_inventory(record, evidence, "inventory"))
            self.assertEqual((record["failedStage"], record["failureType"], record["fixedFailureReason"]),
                             ("actual-http", "ValueError", "original-query-refusal"))
            self.assertEqual(record["evidenceFinalizationFailure"], {"failedStage": "evidence-inventory",
                "failureType": "ValueError", "fixedFailureReason": "original-evidence-byte-bound"})
            self.assertNotIn("evidenceInventory", record)
            self.assertFalse(record["passed"] or record["signedGuestExecutionQualified"])
            terminal.write_json(root / "campaign-receipt.json", record)
            self.assertEqual(json.loads((root / "campaign-receipt.json").read_bytes()), record)

    def test_finalization_failure_has_no_raw_error_or_invented_inventory(self):
        record = {"passed": True, "evidenceInventory": {"stale": True}}
        evidence = SimpleNamespace(summary=lambda: {}, record=Mock(side_effect=OSError("secret /path token=value")))
        self.assertFalse(terminal.finalize_inventory(record, evidence, "inventory"))
        self.assertEqual(record["evidenceFinalizationFailure"],
                         {"failedStage": "evidence-inventory", "failureType": "OSError"})
        self.assertEqual((record["failedStage"], record["failureType"]), ("evidence-inventory", "OSError"))
        self.assertNotIn("evidenceInventory", record)
        self.assertNotIn("secret", encoded(record).decode())

    def failed_entrypoint(self, module, *, early_mode=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = arguments(root / "campaign")
            original = ValueError("original-identity-refusal")
            target = early if early_mode else terminal
            operation = "selection" if early_mode else "tool_identity"
            with patch.object(module, "Evidence", side_effect=full_evidence), \
                    patch.object(module, "owned_cancellation", return_value=nullcontext(cancellation())), \
                    patch.object(terminal.staging, "clock", return_value={"test": "original-clock"}), \
                    patch.object(terminal.staging, "deadline", return_value=200), \
                    patch.object(target, operation, side_effect=original), redirect_stdout(io.StringIO()):
                self.assertEqual(module.run(args), 1)
            record = json.loads((args.output / "campaign-receipt.json").read_bytes())
            self.assertEqual((record["failedStage"], record["failureType"], record["fixedFailureReason"]),
                             ("identity", "ValueError", "original-identity-refusal"))
            self.assertEqual(record["evidenceFinalizationFailure"]["fixedFailureReason"], "original-evidence-byte-bound")
            self.assertNotIn("evidenceInventory", record)
            self.assertFalse(record["passed"])
            self.assertEqual(len(list((args.output / "evidence").iterdir())), 1024)
            return record

    def test_terminal_run_writes_failed_campaign_when_original_inventory_is_full(self):
        self.assertFalse(self.failed_entrypoint(terminal)["signedGuestExecutionQualified"])

    def test_pending_run_writes_failed_campaign_and_keeps_qualification_false(self):
        self.assertFalse(self.failed_entrypoint(pending)["signedPendingRestoreCloseQualified"])

    def test_early_run_writes_failed_campaign_and_keeps_immediate_denial_false(self):
        self.assertFalse(self.failed_entrypoint(early, early_mode=True)["immediateHttpDenialQualified"])

    def test_claimed_resume_writes_failed_receipt_when_retained_original_inventory_is_full(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "retained"
            work.mkdir()
            evidence = full_evidence(work / "evidence")
            args = arguments(work)
            with patch.object(terminal, "tool_identity", return_value={}), \
                    patch.object(terminal, "collector_identity", return_value={}), \
                    patch.object(terminal.staging, "retain", return_value=({"evidence": evidence.summary()}, 200)), \
                    patch.object(terminal, "loaded_inputs", return_value=((), None)), \
                    patch.object(terminal, "recheck_inputs"), patch.object(terminal.staging, "claim") as claim, \
                    patch.object(terminal, "owned_cancellation", return_value=nullcontext(cancellation())), \
                    patch.object(terminal, "RecordingClient", side_effect=ValueError("resume-original-refusal")), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(terminal.resume(args), 1)
            claim.assert_called_once_with(work, args.candidate_digest)
            record = json.loads((work / "campaign-resume-receipt.json").read_bytes())
            self.assertEqual((record["failedStage"], record["fixedFailureReason"]),
                             ("retained-candidate", "resume-original-refusal"))
            self.assertNotIn("evidenceInventory", record)
            self.assertFalse(record["passed"] or record["signedGuestExecutionQualified"])
            self.assertEqual(record["evidenceFinalizationFailure"]["fixedFailureReason"], "original-evidence-byte-bound")
