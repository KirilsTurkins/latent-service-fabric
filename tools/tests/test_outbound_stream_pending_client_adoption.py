"""Pending-operation credential handoff; explicit RPC doubles, real private state."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from tools import outbound_stream_operator as stream
from tools.dev_workflow import paths, state
from tools.dev_workflow.common import DevError, digest, encode
from tools.tests import test_outbound_stream_client_adoption as fixtures


class PendingClientAdoption(unittest.TestCase):
    setUp = fixtures.ClientAdoption.setUp
    snapshot = fixtures.ClientAdoption.snapshot
    write_candidate = fixtures.ClientAdoption.write_candidate

    def pending(self, stage="revoke"):
        # Start a separate protected owner for every scenario; never delete or
        # repair the production journal to make an unresolved request retryable.
        root = self.root / ("pending-" + str(len(list(self.root.iterdir()))))
        paths.new_directory(root)
        self.operator_root = root
        self.client = fixtures.PolicyRpc(self.config)
        self.client.binary, self.client.directory, self.client.deadline = root / "selected-latent", root, 12345.0
        self.operator = stream.StreamOperator(root, self.client, **self.options)
        if stage == "revoke":
            self.operator.grant()
        original = self.client.call

        def dispatch(*arguments):
            if "apply" in arguments:
                kind = arguments[arguments.index("--kind") + 1]
                self.client.uncertain = kind == ("provider-binding" if stage == "binding" else "policy")
            return original(*arguments)

        with patch.object(self.client, "call", side_effect=dispatch), self.assertRaises(DevError):
            (self.operator.revoke if stage == "revoke" else self.operator.grant)()
        self.replacement = fixtures.ReplacementRpc(self.candidate, self.client.records, root)
        self.replacement.operations = copy.deepcopy(self.client.operations)
        self.client.calls.clear()
        return copy.deepcopy(self.operator.journal.read()["pending"])

    def adopt(self):
        return self.operator.adopt_client(self.replacement, preserve_pending=True)

    def assert_refused(self):
        before, owner = self.snapshot(), copy.deepcopy(self.operator.owner)
        with self.assertRaises(DevError) as caught:
            self.adopt()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.operator.owner, owner)
        self.assertIs(self.operator.client, self.client)
        self.assertEqual(self.client.calls, [])
        self.assertFalse(any("apply" in call for call in self.replacement.calls))

    def test_revoke_handoff_preserves_original_intent_until_explicit_restart_recovery(self):
        pending = self.pending()
        before, owner = self.snapshot(), copy.deepcopy(self.operator.owner)
        result = self.adopt()
        self.assertEqual(result, {"executionPermission": False, "recoveryRequired": True,
            "outcome": "client-token-adopted-original-operation-pending"})
        self.assertEqual(self.replacement.calls, [["node", "get", "node"],
            ["policy", "operation", "--operation-id", pending["id"]],
            ["policy", "--kind", "provider-binding", "get", "--id", "stream-installed"],
            ["policy", "--kind", "policy", "get", "--id", "stream-allow"]])
        owner["clientConfigurationDigest"] = digest(self.candidate.read_bytes())
        self.assertEqual(self.operator.owner, owner)
        after = self.snapshot()
        self.assertEqual({key: value for key, value in before.items() if key != "stream-operator-owner.json"},
                         {key: value for key, value in after.items() if key != "stream-operator-owner.json"})
        self.assertEqual(self.operator.journal.read()["pending"], pending)
        self.assertEqual(self.client.calls, [])
        with self.assertRaisesRegex(DevError, "owner-changed"):
            stream.StreamOperator(self.operator_root, self.client, **self.options)
        restarted = stream.StreamOperator(self.operator_root, self.replacement, **self.options)
        with self.assertRaisesRegex(DevError, "recover-original"):
            restarted.grant()
        with self.assertRaisesRegex(DevError, "recover-original"):
            restarted.revoke()
        self.replacement.calls.clear()
        restarted.recover()
        self.assertIsNone(restarted.journal.read()["pending"])
        self.assertEqual(self.replacement.calls, [["policy", "operation", "--operation-id", pending["id"]],
            ["policy", "--kind", "policy", "get", "--id", "stream-allow"]])
        restarted.revoke()
        self.assertFalse(any("apply" in call for call in self.replacement.calls))
        self.assertEqual(restarted._records()["policy:stream-allow"]["document"]["rules"][0]["effect"], "deny")

    def test_first_binding_and_first_policy_can_handoff_without_inventing_missing_receipts(self):
        for stage in ("binding", "policy"):
            with self.subTest(stage=stage):
                pending = self.pending(stage)
                before = self.snapshot()
                self.adopt()
                self.assertEqual(self.snapshot()["operations.json"], before["operations.json"])
                self.assertEqual(self.snapshot().get("stream-policy-receipts.json"),
                                 before.get("stream-policy-receipts.json"))
                self.assertEqual(self.operator.journal.read()["pending"], pending)
                self.operator.recover()
                self.assertFalse(any("apply" in call for call in self.replacement.calls))
                self.operator.grant()
                applies = [call for call in self.replacement.calls if "apply" in call]
                self.assertEqual(len(applies), 1 if stage == "binding" else 0)
                if applies:
                    self.assertIn("policy", applies[0])
                    self.assertNotIn(pending["id"], applies[0])

    def test_pending_handoff_is_opt_in_and_requires_an_original_operation(self):
        self.assert_refused()
        self.assertEqual(self.replacement.calls, [])
        self.pending()
        before = self.snapshot()
        with self.assertRaisesRegex(DevError, "recover-original-operation-before-client-adoption"):
            self.operator.adopt_client(self.replacement)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.replacement.calls, [])
        for value in (1, "true", None):
            with self.assertRaisesRegex(DevError, "pending-adoption-option"):
                self.operator.adopt_client(self.replacement, preserve_pending=value)

    def test_unknown_expired_denied_and_malformed_receipts_never_release_the_owner(self):
        self.pending()
        original = self.replacement.call
        responses = [None, {}, {"outcomeKnown": True, "category": "success", "data": None},
            {"outcomeKnown": False, "category": "transport-failure", "data": {}},
            {"outcomeKnown": True, "category": "not-found", "data": {}},
            {"outcomeKnown": True, "category": "success", "data": {"mutationOutcome": "unknown"}},
            {"outcomeKnown": True, "category": "success", "data": {"receipt": None}}]
        for response in responses:
            def observed(*arguments):
                return copy.deepcopy(response) if "operation" in arguments else original(*arguments)
            with self.subTest(response=response), patch.object(self.replacement, "call", side_effect=observed):
                self.assert_refused()

    def test_receipt_identity_generation_types_and_original_document_are_checked(self):
        pending = self.pending()
        original = copy.deepcopy(self.replacement.operations[pending["id"]])
        for field, value in (("operationId", "dev-" + "f" * 32), ("tenant", "foreign"),
                             ("id", "other"), ("recordKind", "provider-binding"), ("revoked", True),
                             ("revoked", 0), ("generation", "1"), ("generation", "02"),
                             ("generation", "18446744073709551616"), ("contentDigest", "not-a-digest")):
            with self.subTest(field=field, value=value):
                self.replacement.operations[pending["id"]] = {**original, field: value}
                self.assert_refused()
        self.replacement.operations[pending["id"]] = original
        key = "policy:stream-allow"
        record = copy.deepcopy(self.replacement.records[key])
        for change in (lambda doc: doc["rules"][0].update(effect="allow"),
                       lambda doc: doc["rules"][0].update(publications=["foreign-publication"]),
                       lambda doc: doc["rules"][0].update(requireAudit=1),
                       lambda doc: doc["rules"][0]["resources"]["endpoints"][0].update(port=32124),
                       lambda doc: doc["rules"][0]["ceiling"].update(operations=128.0)):
            self.replacement.records[key] = copy.deepcopy(record)
            change(self.replacement.records[key]["document"])
            self.assert_refused()

    def test_foreign_node_or_changed_other_owned_policy_blocks_handoff(self):
        self.pending()
        self.replacement.node = "foreign"
        self.assert_refused()
        self.replacement.node = "node"
        key = "provider-binding:stream-installed"
        original = copy.deepcopy(self.replacement.records[key])
        for field, value in (("generation", "99"), ("revoked", 0), ("document", {"formatVersion": True})):
            self.replacement.records[key] = {**original, field: value}
            self.assert_refused()

    def test_initial_binding_requires_authenticated_absence_of_the_not_yet_owned_policy(self):
        self.pending("binding")
        self.replacement.records["policy:stream-allow"] = {"document": {"foreign": True}}
        self.assert_refused()
        del self.replacement.records["policy:stream-allow"]
        original = self.replacement.call
        def uncertain_absence(*arguments):
            result = original(*arguments)
            if result["category"] == "not-found":
                result["outcomeKnown"] = False
            return result
        with patch.object(self.replacement, "call", side_effect=uncertain_absence):
            self.assert_refused()

    def test_missing_owned_binding_cannot_be_replaced_by_a_pending_policy(self):
        self.pending("policy")
        state.atomic(self.operator_root, "stream-policy-receipts.json", {})
        self.assert_refused()
        self.assertEqual(self.replacement.calls, [])

    def test_foreign_or_corrupt_pending_intents_fail_before_any_replacement_rpc(self):
        self.pending()
        original = self.operator.journal.read()
        changes = [lambda p: p.update(kind="invoke"), lambda p: p.update(node="foreign"),
            lambda p: p.update(tenant="foreign"), lambda p: p.update(state="completed"),
            lambda p: p.update(id="arbitrary"), lambda p: p.update(requestDigest="sha256:" + "f" * 64),
            lambda p: p["intent"].update(policyId="foreign"),
            lambda p: p["intent"].update(recordKind="http"),
            lambda p: p["intent"].update(expectedGeneration="0"),
            lambda p: p["intent"].update(expectedGeneration="2"),
            lambda p: p["intent"].update(expectedGeneration=True),
            lambda p: p["intent"].update(expectedGeneration="01"),
            lambda p: p["intent"].update(expectedGeneration="18446744073709551616"),
            lambda p: p["intent"]["document"]["rules"][0].update(publications=["foreign"]),
            lambda p: p["intent"]["document"]["rules"][0].update(capability="latent:http/client@0.2.0")]
        for change in changes:
            value = copy.deepcopy(original)
            change(value["pending"])
            # Rebind the local checksum to ensure scope checks do not rely on
            # just a self-supplied digest; the explicit bad digest remains bad.
            if value["pending"]["requestDigest"] == original["pending"]["requestDigest"]:
                value["pending"]["requestDigest"] = digest(encode(value["pending"]["intent"]))
            state.atomic(self.operator_root, "operations.json", value)
            self.assert_refused()
            self.assertEqual(self.replacement.calls, [])

    def test_handoff_preserves_receipts_after_a_crash_between_local_settlement_and_journal_finish(self):
        pending = self.pending()
        current = self.replacement.records["policy:stream-allow"]
        self.operator._settle(pending, {"category": "success", "data": {"receipt": {
            key: value for key, value in current.items() if key != "document"}}})
        before = self.snapshot()
        self.adopt()
        self.assertEqual(self.snapshot()["stream-policy-receipts.json"], before["stream-policy-receipts.json"])
        self.assertEqual(self.snapshot()["operations.json"], before["operations.json"])
        self.operator.recover()
        self.assertFalse(any("apply" in call for call in self.replacement.calls))

    def test_token_only_and_protected_input_rules_also_apply_to_pending_handoff(self):
        self.pending()
        for field, value in (("tenant", "foreign"), ("endpoint", "http://127.0.0.1:32124"),
                             ("rpcTimeoutMillis", 1001)):
            candidate = copy.deepcopy(self.replacement_document)
            candidate["profiles"][0][field] = value
            self.write_candidate(candidate)
            self.assert_refused()
        self.write_candidate(self.replacement_document)
        alias = self.config_root / "linked.json"
        os.link(self.candidate, alias)
        self.assert_refused()
        alias.unlink()
        self.candidate.write_bytes(b"X" * 65537)
        self.assert_refused()
        self.write_candidate(self.replacement_document)
        self.config.unlink()
        self.assert_refused()
        self.assertEqual(self.replacement.calls, [])

    def test_edits_at_each_read_boundary_are_rechecked_before_local_commit(self):
        self.pending()
        before = self.snapshot()
        targets = [self.config, self.candidate] + [self.operator_root / name for name in (
            "stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")]
        originals = {path: path.read_bytes() for path in targets}
        for index in range(1, 5):
            for target in targets:
                self.replacement.calls.clear()
                def replace():
                    if len(self.replacement.calls) == index:
                        target.write_bytes(originals[target] + b" ")
                self.replacement.hook = replace
                try:
                    with self.subTest(read=index, target=target.name), self.assertRaises(DevError) as caught:
                        self.adopt()
                    self.assertTrue(caught.exception.uncertain)
                    self.assertEqual(target.read_bytes(), originals[target] + b" ")
                    self.assertIs(self.operator.client, self.client)
                    self.assertEqual(self.operator.owner["clientConfigurationDigest"], digest(originals[self.config]))
                    for path in targets:
                        if path != target:
                            self.assertEqual(path.read_bytes(), originals[path])
                finally:
                    for path, raw in originals.items():
                        path.write_bytes(raw)
        self.replacement.hook = None
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any("apply" in call for call in self.replacement.calls))

    def test_transport_failure_and_atomic_write_failure_keep_the_original_pending_owner(self):
        self.pending()
        for exception in (DevError("owned-process-command-deadline"), OSError("private-error-detail")):
            with patch.object(self.replacement, "call", side_effect=exception):
                self.assert_refused()
        with patch.object(state, "atomic", side_effect=OSError("private-write-detail")):
            self.assert_refused()

    def test_uncertain_local_commit_can_restart_with_visible_new_owner_without_losing_intent(self):
        self.pending()
        before = self.snapshot()
        original = state.atomic
        def committed_then_failed(*arguments):
            original(*arguments)
            raise OSError("private-durability-detail")
        with patch.object(state, "atomic", side_effect=committed_then_failed), self.assertRaises(DevError) as caught:
            self.adopt()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.snapshot()["operations.json"], before["operations.json"])
        self.assertEqual(self.snapshot()["stream-policy-receipts.json"], before["stream-policy-receipts.json"])
        restarted = stream.StreamOperator(self.operator_root, self.replacement, **self.options)
        restarted.recover()
        self.assertIsNone(restarted.journal.read()["pending"])
        self.assertFalse(any("apply" in call for call in self.replacement.calls))

    def test_later_recovery_revalidates_remote_state_instead_of_using_the_handoff_observation(self):
        self.pending()
        self.adopt()
        before = self.snapshot()
        self.replacement.records["policy:stream-allow"]["document"]["rules"][0]["effect"] = "allow"
        with self.assertRaises(DevError) as caught:
            self.operator.recover()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any("apply" in call for call in self.replacement.calls))

    def test_command_exposes_pending_handoff_and_redacts_both_success_and_failure(self):
        self.pending()
        specification = {key: value for key, value in self.options.items() if key not in {"binding_id", "policy_id"}}
        specification.update(bindingId=self.options["binding_id"], policyId=self.options["policy_id"])
        source = self.config_root / "specification.json"
        paths.write_new(source, encode(specification))
        arguments = ["adopt-client", "--cli", str(self.client.binary), "--client-config", str(self.config),
            "--state-dir", str(self.operator_root), "--specification", str(source),
            "--replacement-client-config", str(self.candidate), "--preserve-pending"]
        stdout, stderr = io.StringIO(), io.StringIO()
        before = self.snapshot()
        self.replacement.failure = "denied"
        with patch("tools.dev_workflow.client.Client", side_effect=[self.client, self.replacement]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(stream.main(arguments), 1)
        self.assertTrue(json.loads(stderr.getvalue())["uncertain"])
        self.assertEqual(self.snapshot(), before)
        self.replacement.failure = None
        with patch("tools.dev_workflow.client.Client", side_effect=[self.client, self.replacement]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(stream.main(arguments), 0)
        self.assertTrue(json.loads(stdout.getvalue())["result"]["recoveryRequired"])
        public = stdout.getvalue() + stderr.getvalue()
        for secret in (str(self.config), str(self.candidate), str(source),
                       self.document["profiles"][0]["token"], self.replacement_document["profiles"][0]["token"]):
            self.assertNotIn(secret, public)
        self.assertEqual(self.snapshot()["operations.json"], before["operations.json"])

    def test_pending_command_failure_before_owner_construction_retains_uncertainty(self):
        self.pending()
        before = self.snapshot()
        arguments = ["adopt-client", "--cli", str(self.client.binary), "--client-config", str(self.config),
            "--state-dir", str(self.operator_root), "--specification", str(self.config_root / "missing.json"),
            "--replacement-client-config", str(self.candidate), "--preserve-pending"]
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(stream.main(arguments), 1)
        self.assertTrue(json.loads(output.getvalue())["uncertain"])
        self.assertNotIn(str(self.config_root), output.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_pending_option_is_rejected_for_every_other_command_before_file_access(self):
        for command in ("grant", "revoke", "recover", "inspect", "adopt", "prepare", "prepare-rotation"):
            output = io.StringIO()
            with self.subTest(command=command), contextlib.redirect_stderr(output):
                self.assertEqual(stream.main([command, "--preserve-pending"]), 1)
            self.assertEqual(json.loads(output.getvalue())["code"], "stream-operator-preserve-pending-only-for-client-adoption")


if __name__ == "__main__":
    unittest.main()
