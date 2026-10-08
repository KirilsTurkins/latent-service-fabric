"""Synthetic native receipt oracles; these do not qualify a signed Java guest."""
from __future__ import annotations

import copy
import json
import unittest

from tools.java_transaction_qualification import recovery


def observed():
    return {"schemaVersion": "latent.native-transaction-recovery.v1", "operationSucceeded": True,
            "failure": None, "result": {"action": "inspect-namespace"}, "catalogsRetired": True,
            "retirement": {"clean": True, "physicallyRetired": True, "liveWorkers": 0,
                           "acceptedJobs": 0, "threadsJoined": 4}}


class NativeCloseActionOracle(unittest.TestCase):
    @staticmethod
    def close_observation():
        from tools.java_transaction_qualification import configuration as cfg, recovery_close
        selected = {"effectId": "a" * 64, "originalDigest": [1] * 32, "payloadDigest": [2] * 32,
                    "historyDigest": [3] * 32, "originalDisposition": "Uncertain", "originalClockMillis": 1000}
        value = {"schemaVersion": recovery_close.FORMAT, "operatorId": cfg.OPERATOR,
                 "operationId": "original-close", "scope": {"tenant": cfg.TENANT, "namespace": cfg.NAMESPACE, "incarnation": 1},
                 "expectedView": list(b"NV\x02" + bytes([19]) * 32
                     + b"".join(number.to_bytes(8, "little") for number in (1, 2, 3, 4))),
                 "expectedGuard": [7] * 133, "lossWindowDigest": [4] * 32,
                 "reason": "remote fact requires explicit operator closure", "effects": [selected]}
        request = {"action": "inspect-close-effects", "operationId": value["operationId"],
                   "effectIds": [selected["effectId"]], "reason": value["reason"]}
        result = {"action": request["action"], "plan": value, "planDigest": "sha256:" + "b" * 64,
                  "proposedOutcome": recovery_close.OUTCOME, "recoveryRemainsPaused": True}
        return request, result

    def test_existing_native_close_actions_preserve_original_plan_ack_and_paused_outcome(self):
        from tools.java_transaction_qualification import recovery_close
        request, inspected = self.close_observation()
        self.assertIn("inspect-close-effects", recovery.ACTIONS)
        self.assertIn("close-effects", recovery.ACTIONS)
        self.assertIs(recovery_close.result(request, inspected), inspected)
        original = copy.deepcopy(inspected)
        close = {"action": "close-effects", "operationId": request["operationId"],
                 "plan": inspected["plan"], "acknowledgement": inspected["planDigest"]}
        closed = {"action": "close-effects", "recoveryRemainsPaused": True,
                  "providerAcknowledgementInferred": False, "receipt": {"schemaVersion": recovery_close.FORMAT,
                  "outcome": recovery_close.OUTCOME, "plan": close["plan"],
                  "acknowledgement": list(bytes.fromhex(close["acknowledgement"][7:])), "observedAtMillis": 1001}}
        self.assertIs(recovery_close.result(close, closed), closed)
        self.assertEqual(inspected, original)

    def test_native_close_collection_refuses_unknown_actions_grants_and_unbounded_selection(self):
        from tools.java_transaction_qualification import recovery_close
        request, inspected = self.close_observation()
        for changed in ({"action": "retry"}, {"approved": True}, {"grant": True},
                        {"deadline": 1000}, {"reason": "x" * 129}, {"effectIds": ["a" * 64] * 2},
                        {"effectIds": [f"{number:064x}" for number in range(17)]}):
            with self.assertRaises(ValueError):
                recovery_close.request(dict(request, **changed))
        for name, changed in (("operatorId", "foreign-operator"), ("schemaVersion", "unknown"),
                              ("expectedGuard", [7] * 134), ("lossWindowDigest", [0] * 32)):
            invalid = copy.deepcopy(inspected)
            invalid["plan"][name] = changed
            with self.assertRaises(ValueError):
                recovery_close.result(request, invalid)

    def test_native_inspected_close_refuses_changed_scope_operation_identity_and_outcome(self):
        from tools.java_transaction_qualification import recovery_close
        request, inspected = self.close_observation()
        for changed in ({"recoveryRemainsPaused": False}, {"proposedOutcome": "provider-acknowledged"},
                        {"planDigest": "sha256:" + "0" * 64}, {"approved": True}):
            with self.assertRaises(ValueError):
                recovery_close.result(request, dict(inspected, **changed))
        for change in ("operation", "tenant", "effect", "disposition", "clock"):
            invalid = copy.deepcopy(inspected)
            if change == "operation":
                invalid["plan"]["operationId"] = "replacement-operation"
            elif change == "tenant":
                invalid["plan"]["scope"]["tenant"] = "foreign-tenant"
            elif change == "effect":
                invalid["plan"]["effects"][0]["effectId"] = "c" * 64
            elif change == "disposition":
                invalid["plan"]["effects"][0]["originalDisposition"] = "ProviderAcknowledged"
            else:
                invalid["plan"]["effects"][0]["originalClockMillis"] = True
            with self.assertRaises(ValueError):
                recovery_close.result(request, invalid)

    def test_native_close_receipt_cannot_infer_remote_success_refresh_plan_or_advance_original_time(self):
        from tools.java_transaction_qualification import recovery_close
        request, inspected = self.close_observation()
        close = {"action": "close-effects", "operationId": request["operationId"],
                 "plan": inspected["plan"], "acknowledgement": inspected["planDigest"]}
        receipt = {"schemaVersion": recovery_close.FORMAT, "outcome": recovery_close.OUTCOME,
                   "plan": close["plan"], "acknowledgement": [0xbb] * 32, "observedAtMillis": 1001}
        original = {"action": "close-effects", "receipt": receipt, "recoveryRemainsPaused": True,
                    "providerAcknowledgementInferred": False}
        for change in ("ack", "plan", "time", "provider", "resume"):
            invalid = copy.deepcopy(original)
            if change == "ack":
                invalid["receipt"]["acknowledgement"] = [1] * 32
            elif change == "plan":
                invalid["receipt"]["plan"]["reason"] = "changed-after-inspection"
            elif change == "time":
                invalid["receipt"]["observedAtMillis"] = 999
            elif change == "provider":
                invalid["providerAcknowledgementInferred"] = True
            else:
                invalid["recoveryRemainsPaused"] = False
            with self.assertRaises(ValueError):
                recovery_close.result(close, invalid)

class OptionalRecoveryWorkflowOracle(unittest.TestCase):
    """Explicit selection oracles; helper files and digests grant no authority."""

    @staticmethod
    def arguments(helper, root):
        from types import SimpleNamespace
        return SimpleNamespace(recovery_workflow="unresolved-effect-close", recovery_helper=helper,
            recovery_source_commit="a" * 40, native_source_commit="a" * 40,
            current_selections=root / "selected.json", current_selections_digest="sha256:" + "b" * 64,
            portable=root, prepare_authority_only=False, resume_candidate=None)

    def test_default_workflow_preserves_optional_helper_and_original_candidate_modes(self):
        from types import SimpleNamespace
        from tools import run_java_transaction_http_qualification as runner
        for selected in (SimpleNamespace(), SimpleNamespace(recovery_workflow="schema-terminal"),
                         SimpleNamespace(prepare_authority_only=True), SimpleNamespace(resume_candidate="original")):
            self.assertEqual(runner.validate_recovery_workflow(selected), "schema-terminal")
        for selected in (None, True, "retry", "resume", [], {"approved": True}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                runner.validate_recovery_workflow(SimpleNamespace(recovery_workflow=selected))

    def test_unresolved_workflow_requires_current_inputs_paired_native_source_and_no_retained_candidate(self):
        from pathlib import Path
        import tempfile
        from types import SimpleNamespace
        from tools import run_java_transaction_http_qualification as runner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            helper = root / "observed-helper"
            helper.write_bytes(b"synthetic selection oracle, not a native executable receipt")
            original = self.arguments(helper, root)
            self.assertEqual(runner.validate_recovery_workflow(original), "unresolved-effect-close")
            for changed in ({"recovery_helper": None}, {"recovery_source_commit": None},
                            {"native_source_commit": "c" * 40}, {"current_selections": None},
                            {"current_selections_digest": "sha256:" + "B" * 64},
                            {"current_selections_digest": True}, {"prepare_authority_only": True},
                            {"resume_candidate": root / "historical-candidate"}, {"diagnostic_capture": root}):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    runner.validate_recovery_workflow(SimpleNamespace(**(vars(original) | changed)))

    def test_current_unresolved_selection_refuses_changed_document_schema_and_inferred_approval(self):
        from pathlib import Path
        import tempfile
        from tools import run_java_transaction_http_qualification as runner
        from tools.java_transaction_qualification import current_campaign, inputs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            helper = root / "observed-helper"
            helper.write_bytes(b"synthetic selection oracle, not native execution")
            args = self.arguments(helper, root)
            original = {"schemaVersion": "latent.java.current-campaign-selections.v1", "selections": [
                {"sourceCommit": "a" * 40, "variant": name, "reportDigest": "sha256:" + "b" * 64,
                 "componentDigest": "sha256:" + format(index + 1, "064x"),
                 "compilerInputsDigest": "sha256:" + "c" * 64}
                for index, name in enumerate(current_campaign.NAMES)]}
            raw = json.dumps(original, separators=(",", ":")).encode()
            args.current_selections.write_bytes(raw)
            args.current_selections_digest = inputs.digest(raw)
            runner.current_mode(args)
            self.assertEqual(runner.validate_recovery_workflow(args), "unresolved-effect-close")
            args.current_selections.write_bytes(raw + b" ")
            with self.assertRaises(ValueError):
                runner.current_mode(args)
            for changed in ({"schemaVersion": "unknown"}, {"approved": True},
                            {"selections": original["selections"][:-1]}):
                tampered = json.dumps(original | changed, separators=(",", ":")).encode()
                args.current_selections.write_bytes(tampered)
                args.current_selections_digest = inputs.digest(tampered)
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    runner.current_mode(args)


class InspectionLeaseOracle(unittest.TestCase):
    """Controlled clock/order oracles, never native startup or grant evidence."""

    @staticmethod
    def fixture(root, deadline=100, changed_hosts=False):
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import run_java_transaction_http_qualification as runner
        from tools.java_transaction_qualification import lifecycle
        clock = {"now": 0.0, "restartNotBefore": 0.0}
        events = []
        original_hosts = {"original": "captured-native-profile"}

        def start(_path):
            if clock["now"] < clock["restartNotBefore"]:
                raise AssertionError("restart-before-original-inspection-floor")
            events.append("start")

        def inspect(*_args, **_kwargs):
            events.append("inspection")
            clock["restartNotBefore"] = clock["now"] + 5
            return SimpleNamespace(value={"changed": "profile"} if changed_hosts else original_hosts)

        def sleep(interval):
            events.append("lease")
            clock["now"] += interval

        client = SimpleNamespace(deadline=deadline, cancellation=SimpleNamespace(check=lambda: None),
            evidence=SimpleNamespace(record=lambda *_: None))
        node = SimpleNamespace(start=start, stop=lambda: events.append("stop"))
        configuration = SimpleNamespace(path=root / "bootstrap.json", authority="localhost:1",
            selected=lambda *_args, **_kwargs: root / "full.json")
        args = SimpleNamespace(node=root / "observed-node", peer=SimpleNamespace(incarnation="original-peer"),
                               items=(SimpleNamespace(name="put-once-legacy-v1"),))
        stack = ExitStack()
        stack.enter_context(patch.object(lifecycle.time, "monotonic", lambda: clock["now"]))
        stack.enter_context(patch.object(lifecycle.time, "sleep", sleep))
        stack.enter_context(patch.object(lifecycle, "inspect", inspect))
        stack.enter_context(patch.object(lifecycle, "publish", lambda *_: {"put-once-legacy-v1": "original-publication"}))
        stack.enter_context(patch.object(lifecycle, "create_namespace", lambda *_: None))
        stack.enter_context(patch.object(runner.cfg, "installed", lambda *_: []))
        stack.enter_context(patch.object(runner.policies, "documents", lambda *_args, **_kwargs: {"original": "proposal"}))
        stack.enter_context(patch.object(runner.policies, "apply", lambda *_: {"synthetic": "receipt"}))
        stack.enter_context(patch.object(runner.policies, "apply_retained", lambda *_: {"synthetic": "receipt"}))
        stack.enter_context(patch.object(runner.staging, "catalog", lambda *_: {"original": "catalog"}))
        return stack, runner, client, node, configuration, args, events, clock, original_hosts

    def test_original_provisioning_waits_for_the_new_inspection_floor_before_its_next_start(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            stack, runner, client, node, config, args, events, clock, _ = self.fixture(root)
            with stack:
                runner.provision(client, args, root / "signed", args.items, args.peer, config, node)
            self.assertEqual(events.count("inspection"), 1)
            self.assertEqual(events.count("start"), 3)
            inspected = events.index("inspection")
            following_start = events.index("start", inspected)
            self.assertTrue(all(value == "lease" for value in events[inspected + 1:following_start]))
            self.assertGreaterEqual(clock["now"], clock["restartNotBefore"])

    def test_original_retained_resume_waits_for_inspection_before_reopening_its_same_owner(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            full = root / "full.json"
            full.write_text(json.dumps({"state": {"operations": []}}))
            stack, runner, client, node, config, args, events, clock, hosts = self.fixture(root)
            prepared = {"hosts": hosts, "catalog": {"original": "catalog"},
                        "publications": {}, "proposals": {}, "mutations": {}}
            with stack:
                runner.resume_authority(client, args, config, node, full, prepared)
            self.assertEqual(events[0], "inspection")
            self.assertEqual(events.count("start"), 2)
            self.assertTrue(all(value == "lease" for value in events[1:events.index("start")]))
            self.assertGreaterEqual(clock["now"], clock["restartNotBefore"])

    def test_inspection_lease_refuses_insufficient_original_deadline_without_starting_again(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            stack, runner, client, node, config, args, events, _clock, _ = self.fixture(root, deadline=8)
            with stack, self.assertRaisesRegex(ValueError, "original-admission-lease-interval"):
                runner.provision(client, args, root / "signed", args.items, args.peer, config, node)
            self.assertEqual(events.count("start"), 1)
            self.assertEqual(events[-1], "inspection")
            self.assertEqual(client.deadline, 8)

    def test_changed_retained_inspection_never_uses_elapsed_lease_as_current_authority(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            full = root / "full.json"
            full.write_text(json.dumps({"state": {"operations": []}}))
            stack, runner, client, node, config, args, events, clock, _ = self.fixture(root, changed_hosts=True)
            prepared = {"hosts": {"original": "captured-native-profile"}}
            with stack, self.assertRaisesRegex(ValueError, "original-native-profile-drift"):
                runner.resume_authority(client, args, config, node, full, prepared)
            self.assertEqual(events, ["inspection"])
            self.assertEqual(clock["now"], 0)


class NativeRecoveryOracle(unittest.TestCase):
    def test_absent_client_node_and_elapsed_time_do_not_prove_native_retirement(self):
        from types import SimpleNamespace
        client = SimpleNamespace(node=None)
        node = SimpleNamespace(process=None, shutdown=[])
        with self.assertRaises(ValueError):
            recovery.require_stopped_owner(client, node)
        node.shutdown = [{"reaped": False, "record": {"event": "stopped", "clean": True}}]
        with self.assertRaises(ValueError):
            recovery.require_stopped_owner(client, node)
        node.process = object()
        with self.assertRaises(ValueError):
            recovery.require_stopped_owner(client, node)

    def test_success_receipt_requires_actual_physical_and_catalog_retirement(self):
        value = recovery.report(json.dumps(observed()).encode())
        self.assertEqual(recovery.require_success(value), {"action": "inspect-namespace"})
        for field, changed in (("physicallyRetired", False), ("liveWorkers", 1),
                               ("acceptedJobs", 1), ("threadsJoined", None)):
            invalid = copy.deepcopy(value)
            invalid["retirement"][field] = changed
            with self.assertRaises(ValueError):
                recovery.require_success(invalid)
        value["catalogsRetired"] = False
        with self.assertRaises(ValueError):
            recovery.require_success(value)

    def test_cleanup_failure_preserves_the_original_success_result(self):
        value = observed()
        value["retirement"]["clean"] = False
        value["catalogsRetired"] = False
        actual = recovery.report(json.dumps(value).encode())
        self.assertTrue(actual["operationSucceeded"])
        self.assertEqual(actual["result"], value["result"])
        with self.assertRaises(ValueError):
            recovery.require_success(actual)

    def test_commit_uncertain_is_not_changed_to_known_not_committed_after_retirement(self):
        value = observed()
        value.update(operationSucceeded=False, result=None,
                     failure={"stage": "target", "failure": {"owner": "storage", "reason": "commitUncertain"}})
        actual = recovery.report(json.dumps(value).encode())
        self.assertEqual(actual, value)
        self.assertNotIn("knownNotCommitted", actual)
        with self.assertRaises(ValueError):
            recovery.require_success(actual)

    def test_report_refuses_approval_fields_booleans_as_counts_and_duplicate_json_fields(self):
        for change in ({"approved": True}, {"operationSucceeded": 1}, {"catalogsRetired": 1}):
            value = dict(observed(), **change)
            with self.assertRaises(ValueError):
                recovery.report(json.dumps(value).encode())
        value = observed()
        value["retirement"]["acceptedJobs"] = True
        with self.assertRaises(ValueError):
            recovery.report(json.dumps(value).encode())
        raw = json.dumps(observed())[:-1] + ',"operationSucceeded":false}'
        with self.assertRaises(ValueError):
            recovery.report(raw.encode())
        for changed in ({"owner": "unknown", "reason": "commitUncertain"},
                        {"owner": "storage", "reason": "knownNotCommitted"},
                        {"owner": "storage", "reason": "corrupt", "path": "secret"}):
            value = observed()
            value.update(operationSucceeded=False, result=None,
                         failure={"stage": "target", "failure": changed})
            with self.assertRaises(ValueError):
                recovery.report(json.dumps(value).encode())

    def test_native_view_is_copied_exactly_and_never_reconstructed_as_current(self):
        view = list(b"NV\x02" + bytes([19]) * 32
                    + b"".join(value.to_bytes(8, "little") for value in (1, 2, 3, 4)))
        self.assertEqual(recovery.original_view(view), view)
        for invalid in (view[:-1], [True] + view[1:], [256] + view[1:],
                        view[:35] + [0] * 8 + view[43:]):
            with self.assertRaises(ValueError):
                recovery.original_view(invalid)

    def test_original_digest_refuses_unbounded_changed_encoding_and_zero_identity(self):
        value = "sha256:" + "a" * 64
        self.assertEqual(recovery.original_digest(value), value)
        for invalid in (value + "\n", value.upper(), "sha256:" + "0" * 64, "b3:" + "a" * 64):
            with self.assertRaises(ValueError):
                recovery.original_digest(invalid)

    def test_original_cli_generation_refuses_numeric_zero_unicode_and_overflow(self):
        from tools.java_transaction_qualification import offline_campaign
        self.assertEqual(offline_campaign.generation(str(2**64 - 1)), str(2**64 - 1))
        for value in (True, 1, "0", "01", "١", str(2**64), "1" * 100):
            with self.assertRaises(ValueError):
                offline_campaign.generation(value)

    def test_snapshot_keeps_original_native_manifest_and_refuses_changed_actor_scope_and_approval(self):
        from tools.java_transaction_qualification import configuration as cfg, offline_campaign
        value = {"snapshotDigest": "sha256:" + "a" * 64, "manifestDigest": "sha256:" + "b" * 64,
                 "manifest": {"metadata": {"tenant": cfg.TENANT, "operator_id": cfg.OPERATOR,
                     "operation_id": "original-operation", "runtime_digest": [1] * 32,
                     "decoder_formats": [], "required_artifacts": []}}}
        self.assertIs(offline_campaign.original_snapshot(value, "original-operation"), value)
        for field, changed in (("operator_id", "another-operator"), ("tenant", "foreign"),
                               ("operation_id", "later-operation"), ("approved", True)):
            invalid = copy.deepcopy(value)
            invalid["manifest"]["metadata"][field] = changed
            with self.assertRaises(ValueError):
                offline_campaign.original_snapshot(invalid, "original-operation")

    def test_native_epoch_advance_keeps_original_scope_incarnation_and_other_history(self):
        from tools.java_transaction_qualification import offline_campaign
        original = list(b"NV\x02" + bytes([19]) * 32
                        + b"".join(value.to_bytes(8, "little") for value in (1, 2, 3, 4)))
        changed = original[:51] + list((4).to_bytes(8, "little")) + original[59:]
        offline_campaign.epoch_advanced(original, changed, "schema")
        for invalid in (original, [0] + changed[1:],
                        changed[:35] + list((2).to_bytes(8, "little")) + changed[43:],
                        changed[:59] + list((5).to_bytes(8, "little"))):
            with self.assertRaises(ValueError):
                offline_campaign.epoch_advanced(original, invalid, "schema")
        with self.assertRaises(ValueError):
            offline_campaign.epoch_advanced(original, changed, "grant")

    def test_restored_selection_retains_catalogs_credentials_clock_and_quotas_without_mutating_original(self):
        from pathlib import Path
        import tempfile
        from tools.java_transaction_qualification import offline_campaign
        original = {"dataDirectory": "data", "providers": {"original": "selected"},
                    "credentials": [{"subject": "operator", "token": "synthetic-test"}],
                    "state": {"formatVersion": 1, "clockCheckpoint": "original-clock",
                              "configurationEpoch": 7, "createIfMissing": True,
                              "tenantQuotas": [{"tenant": "original"}], "operations": ["original"]}}
        retained = copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as root:
            selected = offline_campaign.restored_configuration(original, Path(root))
            self.assertEqual(selected["dataDirectory"], "data")
            self.assertEqual(selected["providers"], original["providers"])
            self.assertEqual(selected["credentials"], original["credentials"])
            self.assertFalse(selected["state"].pop("createIfMissing"))
            self.assertEqual(selected["state"].pop("stateRoot"), root)
            expected = dict(original["state"])
            expected.pop("createIfMissing")
            self.assertEqual(selected["state"], expected)
            for invalid in (Path("relative"), Path(root) / "missing", Path(root) / "../other"):
                with self.assertRaises(ValueError):
                    offline_campaign.restored_configuration(original, invalid)
        self.assertEqual(original, retained)

    def test_optional_recovery_tool_requires_paired_exact_original_native_source(self):
        from pathlib import Path
        import tempfile
        from types import SimpleNamespace
        from tools import run_java_transaction_http_qualification as conductor
        source = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-executable-not-invoked"
            path.write_bytes(b"not-runtime-evidence")
            args = SimpleNamespace(recovery_helper=path, recovery_source_commit=source, native_source_commit=source)
            conductor.recovery_input(args)
            for helper, identity in ((None, source), (path, None), (path, "b" * 40)):
                args.recovery_helper, args.recovery_source_commit = helper, identity
                with self.assertRaises(ValueError):
                    conductor.recovery_input(args)


if __name__ == "__main__":
    unittest.main()
