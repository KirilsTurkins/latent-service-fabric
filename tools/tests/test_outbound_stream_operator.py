"""Policy RPC sequencing, protected state and exact authority source controls."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import outbound_stream_operator as stream
from tools.dev_workflow import paths, state
from tools.dev_workflow.client import Client
from tools.dev_workflow.common import DevError, digest, encode


class PolicyRpc:
    """Source-level protocol responses; no real node qualification is claimed."""

    def __init__(self, config):
        self.config = config
        self.records = {}
        self.operations = {}
        self.calls = []
        self.uncertain = self.throws = False
        self.inspect_authority = False
        self.expected_config_digest = None
        self.inspection = {
            "capabilities": [{"id": stream.CAPABILITY, "contract": stream.CAPABILITY,
                "provider": stream.PROFILE, "operations": list(stream.OPERATIONS),
                "inspection": {"definitionDigest": None,
                    "providerBinding": {"id": "stream-installed", "revision": "1", "digest": "sha256:" + "c" * 64},
                    "policies": [{"id": "stream-allow", "revision": "1", "digest": "sha256:" + "d" * 64}],
                    "providerProfile": stream.PROFILE, "providerConfigurationDigest": "sha256:" + "a" * 64,
                    "providerConfigurationEpoch": "1", "state": "configured-current"}}],
            "revision": {"deploymentId": "mail-deployment", "revisionId": "revision-v1:sha256:" + "e" * 64,
                "componentDigest": "sha256:" + "f" * 64,
                "publicationId": "publication:sha256:" + "b" * 64,
                "routeGeneration": "1", "catalogTransaction": "1"},
            "nextPageToken": None, "state": "compiled-plan",
            "tenantUsage": {"scope": "tenant", "counters": {}, "unavailable": []},
            "nodeUsage": {"scope": "node", "counters": {}, "unavailable": ["outbound-stream-inspection-unavailable"]}}

    def pin_config(self, expected_digest):
        self.expected_config_digest = expected_digest

    def call(self, *arguments, stdin=None):
        args = list(map(str, arguments))
        self.calls.append(args)
        result = {"outcomeKnown": True, "category": "success", "data": {}}
        if args[0] == "capability":
            result["data"] = {**copy.deepcopy(self.inspection), "executionPermission": self.inspect_authority}
            return result
        if args[1] == "operation":
            operation = args[args.index("--operation-id") + 1]
            result["data"] = {"receipt": copy.deepcopy(self.operations[operation])}
            return result
        kind = args[args.index("--kind") + 1]
        identifier = args[args.index("--id") + 1]
        key = kind + ":" + identifier
        if "get" in args:
            if key not in self.records:
                return {**result, "category": "not-found"}
            result["data"] = {"policy": copy.deepcopy(self.records[key])}
            return result
        assert "apply" in args
        if self.throws:
            raise DevError("operator-transport-disconnected")
        source = args[args.index("--file") + 1]
        if source == "-":
            assert type(stdin) is bytes
            document = json.loads(stdin)
        else:
            assert stdin is None
            document = json.loads(Path(source).read_text())
        expected = args[args.index("--expected-generation") + 1]
        operation = args[args.index("--operation-id") + 1]
        receipt = {"operationId": operation, "tenant": document["tenant"], "id": identifier,
            "recordKind": kind, "generation": str(int(expected) + 1), "contentDigest": digest(encode(document)), "revoked": False}
        self.operations[operation] = receipt
        self.records[key] = {**receipt, "document": document}
        result["data"] = {"receipt": copy.deepcopy(receipt), "policy": copy.deepcopy(self.records[key])}
        if self.uncertain:
            self.uncertain = False
            result.update(outcomeKnown=False, category="transport-failure", requestDispatched=True,
                          error={"code": "rpc-failed", "grpcCode": "unavailable"})
        return result


class StreamOperator(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).absolute()
        self.root.chmod(0o700)
        self.config_root = self.root / "client"
        self.operator_root = self.root / "operator"
        paths.new_directory(self.config_root)
        paths.new_directory(self.operator_root)
        self.config = self.config_root / "config.json"
        paths.write_new(self.config, encode({"profile": "operator", "credential": "PUBLIC-SOURCE-CONTROL-ONLY"}))
        self.client = PolicyRpc(self.config)
        self.options = {"node": "node", "tenant": "examples", "provider": {
            "id": "streams", "tenant": "examples", "service": "stream-host",
            "capability": stream.CAPABILITY, "profile": stream.PROFILE,
            "configurationDigest": "sha256:" + "a" * 64, "configurationEpoch": "1"},
            "consumer": "examples/mail", "publication": "publication:sha256:" + "b" * 64,
            "principal": {"kind": "administrator", "subject": "operator"},
            "destination": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
            "binding_id": "stream-installed", "policy_id": "stream-allow"}

    def operator(self, **changes):
        return stream.StreamOperator(self.operator_root, self.client, **{**self.options, **changes})

    def mutations(self):
        return [args for args in self.client.calls if "apply" in args]

    def test_grant_binds_exact_provider_publication_principal_and_tcp_destination(self):
        result = self.operator().grant()
        self.assertEqual(result, {"capability": stream.CAPABILITY, "policy": "stream-allow"})
        self.assertEqual(len(self.mutations()), 2)
        binding = self.client.records["provider-binding:stream-installed"]["document"]
        policy = self.client.records["policy:stream-allow"]["document"]["rules"][0]
        self.assertEqual(binding["configurationDigest"], self.options["provider"]["configurationDigest"])
        self.assertEqual(binding["configurationEpoch"], 1)
        self.assertEqual(policy["publications"], [self.options["publication"]])
        self.assertEqual(policy["principals"], [self.options["principal"]])
        self.assertEqual(policy["services"], [self.options["consumer"]])
        self.assertEqual(policy["resources"], {"kind": "stream", "endpoints": [self.options["destination"]]})
        self.assertTrue(policy["requireAudit"])
        self.assertEqual(policy["ceiling"], stream.CEILING)

    def test_scoped_ipv6_is_rejected_before_owner_or_policy_mutation(self):
        self.assertEqual(stream.endpoint({"host": "2001:db8::1", "port": 443, "transport": "tcp"})["host"],
                         "2001:db8::1")
        for index, host in enumerate(("fe80::1%eth0", "::1%1", "2001:db8::1%2")):
            with self.subTest(host=host):
                root = self.root / ("scoped-ipv6-" + str(index))
                paths.new_directory(root)
                client = PolicyRpc(self.config)
                destination = {"host": host, "port": 443, "transport": "tcp"}
                with self.assertRaisesRegex(DevError, "stream-operator-noncanonical-host"):
                    stream.StreamOperator(root, client, **{**self.options, "destination": destination})
                self.assertEqual(client.calls, [])
                self.assertFalse((root / "stream-operator-owner.json").exists())
                self.assertFalse((root / "operations.json").exists())

    def test_publication_is_canonical_before_any_owner_or_policy_mutation(self):
        invalid = (
            "publication-v1:sha256:" + "b" * 64,
            "publication:sha256:" + "B" * 64,
            "publication:sha256:" + "b" * 63,
            "publication:sha256:" + "b" * 65,
            "publication:sha256:" + "g" * 64,
            "sha256:" + "b" * 64,
        )
        for index, publication in enumerate(invalid):
            with self.subTest(index=index):
                root = self.root / ("invalid-publication-" + str(index))
                paths.new_directory(root)
                client = PolicyRpc(self.config)
                with self.assertRaisesRegex(DevError, "stream-operator-invalid-publication"):
                    stream.StreamOperator(root, client, **{**self.options, "publication": publication})
                self.assertEqual(client.calls, [])
                self.assertFalse((root / "stream-operator-owner.json").exists())
                self.assertFalse((root / "operations.json").exists())
        root = self.root / "valid-publication"
        paths.new_directory(root)
        canonical = "publication:sha256:" + "0123456789abcdef" * 4
        operator = stream.StreamOperator(root, PolicyRpc(self.config), **{**self.options, "publication": canonical})
        self.assertEqual(operator._policy("allow")["rules"][0]["publications"], [canonical])

    def test_legacy_invalid_publication_can_recover_pending_but_not_start_a_grant(self):
        legacy = "publication-v1:sha256:" + "b" * 64
        with patch.object(stream, "_canonical_publication", return_value=True):
            operator = self.operator(publication=legacy)
            self.client.uncertain = True
            with self.assertRaises(DevError):
                operator.grant()
        pending = operator.journal.read()["pending"]
        self.assertEqual(pending["intent"]["recordKind"], "provider-binding")
        self.assertEqual(len(self.mutations()), 1)
        restarted = self.operator(publication=legacy)
        restarted.recover()
        self.assertIsNone(restarted.journal.read()["pending"])
        self.assertEqual(len(self.mutations()), 1)
        with self.assertRaisesRegex(DevError, "stream-operator-invalid-publication"):
            restarted.grant()
        self.assertEqual(len(self.mutations()), 1)

    def test_policy_dispatch_uses_journaled_bytes_when_selected_file_is_replaced(self):
        for kind in ("provider-binding", "policy"):
            with self.subTest(kind=kind):
                root = self.root / ("input-race-" + kind)
                paths.new_directory(root)
                client = PolicyRpc(self.config)
                operator = stream.StreamOperator(root, client, **self.options)
                expected = operator._binding() if kind == "provider-binding" else operator._policy("allow")
                changed = copy.deepcopy(expected)
                if kind == "provider-binding":
                    changed["configurationDigest"] = "sha256:" + "9" * 64
                else:
                    changed["rules"][0]["principals"].append(
                        {"kind": "service", "subject": "unintended-service"})
                original_call = client.call
                replaced = []

                def race(*arguments, **kwargs):
                    if "apply" in arguments and arguments[arguments.index("--kind") + 1] == kind:
                        (root / "selected-stream-policy.json").write_bytes(encode(changed))
                        replaced.append(True)
                    return original_call(*arguments, **kwargs)

                client.call = race
                failure = None
                try:
                    operator.grant()
                except DevError as error:
                    failure = error
                self.assertEqual(replaced, [True])
                key = kind + ":" + (self.options["binding_id"] if kind == "provider-binding"
                                   else self.options["policy_id"])
                self.assertEqual(client.records[key]["document"], expected)
                self.assertIsNone(failure)
                self.assertIsNone(operator.journal.read()["pending"])

    def test_partial_or_failed_stdin_staging_never_starts_a_child(self):
        from tools.dev_workflow import process

        for mode, code in (("short", "owned-process-stdin-incomplete"),
                           ("write-error", "owned-process-stdin-unavailable"),
                           ("seek-error", "owned-process-stdin-unavailable"),
                           ("open-error", "owned-process-stdin-unavailable")):
            with self.subTest(mode=mode):
                root = self.root / ("stdin-stage-" + mode)
                paths.new_directory(root)
                client = PolicyRpc(self.config)
                operator = stream.StreamOperator(root, client, **self.options)
                actual_client = Client(sys.executable, self.config, root)
                actual_client.pin_config(client.expected_config_digest)
                original_call = client.call

                def bridge(*arguments, **kwargs):
                    if "apply" in arguments:
                        return actual_client.call(*arguments, **kwargs)
                    return original_call(*arguments, **kwargs)

                class BrokenStage:
                    def __enter__(self): return self
                    def __exit__(self, *_args): return False
                    def write(self, data):
                        if mode == "write-error":
                            raise OSError("PRIVATE-STAGING-DETAIL")
                        return len(data) if mode == "seek-error" else len(data) - 1
                    def seek(self, _offset):
                        if mode == "seek-error":
                            raise OSError("PRIVATE-STAGING-DETAIL")
                        raise AssertionError("cannot seek after incomplete write")

                client.call = bridge
                stage = (patch.object(process.tempfile, "TemporaryFile", side_effect=OSError("PRIVATE-STAGING-DETAIL"))
                         if mode == "open-error" else
                         patch.object(process.tempfile, "TemporaryFile", return_value=BrokenStage()))
                with stage, patch.object(process.build_process, "_new_owner") as spawn:
                    with self.assertRaises(DevError) as failure:
                        operator.grant()
                    self.assertEqual(failure.exception.code, code)
                    self.assertTrue(failure.exception.uncertain)
                    self.assertNotIn("PRIVATE-STAGING-DETAIL", str(failure.exception))
                    self.assertIsNotNone(operator.journal.read()["pending"])
                    self.assertEqual(client.records, {})
                    spawn.assert_not_called()
                    with self.assertRaisesRegex(DevError, "recover-original"):
                        operator.grant()
                    spawn.assert_not_called()

    def test_early_child_exit_keeps_original_intent_without_payload_in_arguments(self):
        from tools.dev_workflow import process
        root = self.root / "stdin-early-exit"
        paths.new_directory(root)
        client = PolicyRpc(self.config)
        operator = stream.StreamOperator(root, client, **self.options)
        actual_client = Client(sys.executable, self.config, root)
        actual_client.pin_config(client.expected_config_digest)
        original_call, run = client.call, process.run
        observed = []

        def bridge(*arguments, **kwargs):
            if "apply" in arguments:
                return actual_client.call(*arguments, **kwargs)
            return original_call(*arguments, **kwargs)

        def early_exit(argv, cwd, **kwargs):
            observed.append((list(argv), kwargs["stdin"]))
            return run([sys.executable, "-c", "import sys; sys.exit(17)", *argv[1:]], cwd, **kwargs)

        client.call = bridge
        with patch.object(process, "run", side_effect=early_exit):
            with self.assertRaises(DevError) as failure:
                operator.grant()
            self.assertTrue(failure.exception.uncertain)
            pending = operator.journal.read()["pending"]
            self.assertIsNotNone(pending)
            self.assertEqual(len(observed), 1)
            argv, frame = observed[0]
            self.assertEqual(argv[argv.index("--file") + 1], "-")
            self.assertEqual(frame[:72], (client.expected_config_digest + "\n").encode("ascii"))
            self.assertEqual(frame[72:], encode(pending["intent"]["document"]))
            self.assertNotIn(frame[72:].decode("utf-8"), str(argv))
            self.assertNotIn(client.expected_config_digest, str(argv))
            self.assertNotIn(frame[72:].decode("utf-8"), str(failure.exception))
            with self.assertRaisesRegex(DevError, "recover-original"):
                operator.grant()
            self.assertEqual(len(observed), 1)
            self.assertEqual(operator.journal.read()["pending"], pending)

    def test_local_os_failure_after_journaling_remains_uncertain_and_redacted(self):
        operator = self.operator()
        original_call = self.client.call

        def unavailable(*arguments, **kwargs):
            if "apply" in arguments:
                raise OSError("PRIVATE-MUTATION-DETAIL")
            return original_call(*arguments, **kwargs)

        with patch.object(self.client, "call", side_effect=unavailable):
            with self.assertRaises(DevError) as failure:
                operator.grant()
            self.assertEqual(failure.exception.code, "stream-operator-mutation-unavailable")
            self.assertTrue(failure.exception.uncertain)
            self.assertNotIn("PRIVATE-MUTATION-DETAIL", str(failure.exception))
            pending = operator.journal.read()["pending"]
            self.assertIsNotNone(pending)
            with self.assertRaisesRegex(DevError, "recover-original"):
                operator.grant()
            self.assertEqual(operator.journal.read()["pending"], pending)

    def test_oversized_selected_document_refuses_before_journal_or_dispatch(self):
        operator = self.operator()
        for bound, code in (("MAX_DOCUMENT", "state-byte-limit"),
                            ("MAXIMUM_POLICY_BYTES", "stream-operator-policy-byte-bound")):
            with self.subTest(bound=bound), patch.object(stream, bound, 1):
                with self.assertRaisesRegex(DevError, code):
                    operator.grant()
            self.assertEqual(self.mutations(), [])
            self.assertIsNone(operator.journal.read()["pending"])
            self.assertFalse((self.operator_root / "selected-stream-policy.json").exists())

    def test_uncertain_binding_retains_original_intent_and_prevents_new_mutation(self):
        operator = self.operator()
        self.client.uncertain = True
        with self.assertRaises(DevError) as failure:
            operator.grant()
        self.assertTrue(failure.exception.uncertain)
        pending = operator.journal.read()["pending"]
        self.assertEqual(pending["intent"]["recordKind"], "provider-binding")
        self.assertEqual(len(self.mutations()), 1)
        with self.assertRaises(DevError):
            operator.grant()
        self.assertEqual(operator.journal.read()["pending"], pending)
        self.assertEqual(len(self.mutations()), 1)

    def test_transport_exception_retains_pending_dispatch_without_replay(self):
        operator = self.operator()
        self.client.throws = True
        with self.assertRaises(DevError) as failure:
            operator.grant()
        self.assertTrue(failure.exception.uncertain)
        self.assertIsNotNone(operator.journal.read()["pending"])
        self.assertEqual(len(self.mutations()), 1)

    def test_restart_recovers_only_original_receipt_before_continuing_grant(self):
        self.client.uncertain = True
        with self.assertRaises(DevError):
            self.operator().grant()
        restarted = self.operator()
        operation = restarted.journal.read()["pending"]["id"]
        restarted.recover()
        self.assertIsNone(restarted.journal.read()["pending"])
        self.assertEqual(len(self.mutations()), 1)
        self.assertTrue(any("operation" in args and operation in args for args in self.client.calls))
        restarted.grant()
        self.assertEqual(len(self.mutations()), 2)

    def test_malformed_grant_confirmation_retains_original_dispatch_until_exact_recovery(self):
        original_call = self.client.call
        for ordinal, field in enumerate(("revoked", "configurationEpoch", "formatVersion")):
            root = self.root / ("confirmation-" + str(ordinal))
            paths.new_directory(root)
            operator = stream.StreamOperator(root, self.client, **self.options)
            self.client.records.clear();self.client.operations.clear();self.client.calls.clear()
            owner = copy.deepcopy(operator.owner)

            def malformed(*arguments, **kwargs):
                result = original_call(*arguments, **kwargs)
                if "apply" in arguments:
                    policy = result["data"]["policy"]
                    if field == "revoked": policy[field] = 0
                    else: policy["document"][field] = True if field == "configurationEpoch" else 1.0
                return result

            self.client.call = malformed
            try:
                with self.assertRaisesRegex(DevError, "original-policy-changed") as caught:
                    operator.grant()
                self.assertTrue(caught.exception.uncertain)
                pending = (root / "operations.json").read_bytes()
                self.assertEqual(operator.journal.read()["pending"]["intent"]["recordKind"], "provider-binding")
                self.assertEqual(operator._records(), {})
                self.assertEqual(operator.owner, owner)
                with self.assertRaisesRegex(DevError, "recover-original"):
                    operator.grant()
                self.assertEqual((root / "operations.json").read_bytes(), pending)
                self.assertEqual(len(self.mutations()), 1)
            finally:
                self.client.call = original_call
            operator.recover()
            self.assertEqual(len(self.mutations()), 1)
            operator.grant();operator.grant()
            self.assertEqual(len(self.mutations()), 2)
            self.assertIsNone(operator.journal.read()["pending"])

    def test_revoke_applies_durable_deny_at_owned_policy_generation(self):
        operator = self.operator()
        operator.grant()
        operator.revoke()
        self.assertEqual(len(self.mutations()), 3)
        args = self.mutations()[-1]
        self.assertEqual(args[args.index("--expected-generation") + 1], "1")
        record = self.client.records["policy:stream-allow"]
        self.assertEqual(record["generation"], "2")
        self.assertEqual(record["document"]["rules"][0]["effect"], "deny")
        self.assertIsNone(operator.journal.read()["pending"])

    def test_confirmed_repeat_observes_owned_records_without_reapplying(self):
        operator = self.operator()
        operator.grant(); operator.grant()
        self.assertEqual(len(self.mutations()), 2)

    def test_inspection_refuses_owner_change_during_observation(self):
        operator = self.operator()
        original_call = self.client.call
        def replace_owner(*arguments, stdin=None):
            result = original_call(*arguments, stdin=stdin)
            changed = copy.deepcopy(operator.owner)
            changed['consumer'] = 'examples/other'
            state.atomic(self.operator_root, 'stream-operator-owner.json', changed)
            return result
        self.client.call = replace_owner
        with self.assertRaisesRegex(DevError, 'stream-operator-owner-changed'):
            operator.inspect('mail-deployment')
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.mutations(), [])

    def test_inspection_refuses_client_config_change_during_observation(self):
        operator = self.operator()
        original_call = self.client.call
        def replace_config(*arguments, stdin=None):
            result = original_call(*arguments, stdin=stdin)
            self.config.write_bytes(encode({'profile': 'changed', 'credential': 'PUBLIC-SOURCE-CONTROL-ONLY'}))
            return result
        self.client.call = replace_config
        with self.assertRaisesRegex(DevError, 'stream-operator-client-identity-changed'):
            operator.inspect('mail-deployment')
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.mutations(), [])

    def test_grant_checks_room_for_both_receipts_before_any_mutation(self):
        for count in (stream.MAXIMUM_RECORDS - 1, stream.MAXIMUM_RECORDS):
            with self.subTest(count=count):
                root = self.root / ("full-receipts-" + str(count))
                paths.new_directory(root)
                client = PolicyRpc(self.config)
                operator = stream.StreamOperator(root, client, **self.options)
                records = {"prior:" + str(index): {} for index in range(count)}
                state.atomic(root, "stream-policy-receipts.json", records)
                with self.assertRaisesRegex(DevError, "stream-operator-retained-record-bound"):
                    operator.grant()
                self.assertEqual(client.calls, [])
                self.assertEqual(state.load(root, "stream-policy-receipts.json"), records)
                self.assertIsNone(operator.journal.read()["pending"])
                self.assertFalse((root / "selected-stream-policy.json").exists())

    def test_full_receipt_store_allows_owned_updates_and_one_missing_record(self):
        operator = self.operator()
        with state.lock(self.operator_root, "stream-operator.lock"):
            operator._apply("provider-binding", self.options["binding_id"], operator._binding())
        records = operator._records()
        records.update({"prior:" + str(index): {} for index in range(stream.MAXIMUM_RECORDS - 2)})
        state.atomic(self.operator_root, "stream-policy-receipts.json", records)
        operator.grant()  # One remaining slot admits the missing policy.
        self.assertEqual(len(operator._records()), stream.MAXIMUM_RECORDS)
        self.assertEqual(len(self.mutations()), 2)
        operator.grant()  # A confirmed repeat needs no new slot.
        operator.revoke()  # An existing policy can be updated at capacity.
        self.assertEqual(len(self.mutations()), 3)
        self.assertEqual(self.client.records["policy:stream-allow"]["document"]["rules"][0]["effect"], "deny")
        self.assertIsNone(operator.journal.read()["pending"])

    def test_each_apply_rechecks_capacity_after_an_intervening_state_change(self):
        operator = self.operator()
        records = {"prior:" + str(index): {} for index in range(stream.MAXIMUM_RECORDS - 2)}
        state.atomic(self.operator_root, "stream-policy-receipts.json", records)
        original_call = self.client.call
        def add_unrelated_record(*arguments, stdin=None):
            result = original_call(*arguments, stdin=stdin)
            if "apply" in arguments and "provider-binding" in arguments:
                changed = state.load(self.operator_root, "stream-policy-receipts.json")
                changed["prior:intervening"] = {}
                state.atomic(self.operator_root, "stream-policy-receipts.json", changed)
            return result
        self.client.call = add_unrelated_record
        with self.assertRaisesRegex(DevError, "stream-operator-retained-record-bound"):
            operator.grant()
        self.assertEqual(len(self.mutations()), 1)
        self.assertIn("provider-binding:stream-installed", self.client.records)
        self.assertNotIn("policy:stream-allow", self.client.records)
        self.assertIsNone(operator.journal.read()["pending"])

    def test_foreign_policy_or_changed_owned_record_is_not_overwritten(self):
        operator = self.operator()
        self.client.records["provider-binding:stream-installed"] = {"generation": "999"}
        with self.assertRaises(DevError):
            operator.grant()
        self.assertEqual(len(self.mutations()), 0)
        self.client.records.clear()
        operator.grant()
        self.client.records["policy:stream-allow"]["generation"] = "999"
        with self.assertRaises(DevError):
            operator.revoke()
        self.assertEqual(len(self.mutations()), 2)

    def _pending_recovery_case(self):
        operator = self.operator()
        self.client.uncertain = True
        with self.assertRaises(DevError):
            operator.grant()
        self.assertIsNotNone(operator.journal.read()['pending'])
        self.client.calls.clear()
        return operator

    def test_owner_changed_after_lookup_cannot_settle_original(self):
        operator = self._pending_recovery_case()
        before = (self.operator_root / 'operations.json').read_bytes()
        owner_file = self.operator_root / 'stream-operator-owner.json'
        call = self.client.call
        changed = []
        def race(*args, **kwargs):
            result = call(*args, **kwargs)
            if len(args) > 1 and args[:2] == ('policy', 'operation'):
                foreign = copy.deepcopy(operator.owner)
                foreign['publication'] = 'publication:sha256:' + 'c' * 64
                state.atomic(self.operator_root, owner_file.name, foreign)
                changed.append(owner_file.read_bytes())
            return result
        self.client.call = race
        with self.assertRaises(DevError) as failure:
            operator.recover()
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(owner_file.read_bytes(), changed[0])
        self.assertEqual((self.operator_root / 'operations.json').read_bytes(), before)
        self.assertIsNotNone(operator.journal.read()['pending'])
        self.assertEqual(len([args for args in self.client.calls if 'apply' in args]), 0)

    def test_client_configuration_changed_during_recovery_retains_pending(self):
        operator = self._pending_recovery_case()
        journal = self.operator_root / "operations.json"
        before = journal.read_bytes()
        original = self.config.read_bytes()
        call = self.client.call

        def race(*args, **kwargs):
            result = call(*args, **kwargs)
            if len(args) > 1 and args[:2] == ("policy", "operation"):
                self.config.write_bytes(original + b" ")
            return result

        self.client.call = race
        with self.assertRaisesRegex(DevError, "client-identity-changed") as failure:
            operator.recover()
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(self.config.read_bytes(), original + b" ")
        self.assertEqual(journal.read_bytes(), before)
        self.assertIsNotNone(operator.journal.read()["pending"])
        self.assertEqual(len(self.mutations()), 0)

    def test_type_changed_pending_intent_is_not_overwritten_after_lookup(self):
        operator = self._pending_recovery_case()
        operations = self.operator_root / 'operations.json'
        call = self.client.call
        changed = []
        def race(*args, **kwargs):
            result = call(*args, **kwargs)
            if len(args) > 1 and args[:2] == ('policy', 'operation'):
                value = state.load(self.operator_root, operations.name)
                document = value['pending']['intent']['document']
                self.assertIs(type(document['formatVersion']), int)
                document['formatVersion'] = True
                state.atomic(self.operator_root, operations.name, value)
                changed.append(operations.read_bytes())
            return result
        self.client.call = race
        with self.assertRaises(DevError) as failure:
            operator.recover()
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(operations.read_bytes(), changed[0])
        self.assertIsNotNone(operator.journal.read()['pending'])
        self.assertEqual(len([args for args in self.client.calls if 'apply' in args]), 0)

    def test_invalid_original_request_digest_is_refused_before_remote_read(self):
        operator = self._pending_recovery_case()
        operations = self.operator_root / 'operations.json'
        value = state.load(self.operator_root, operations.name)
        value['pending']['requestDigest'] = 'sha256:' + '0' * 64
        state.atomic(self.operator_root, operations.name, value)
        before = operations.read_bytes()
        with self.assertRaises(DevError) as failure:
            operator.recover()
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(operations.read_bytes(), before)

    def test_incomplete_pending_operation_is_redacted_and_never_looked_up(self):
        operator = self._pending_recovery_case()
        operations = self.operator_root / "operations.json"
        value = state.load(self.operator_root, operations.name)
        del value["pending"]["kind"]
        state.atomic(self.operator_root, operations.name, value)
        before = operations.read_bytes()
        with self.assertRaises(DevError) as failure:
            operator.recover()
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(operations.read_bytes(), before)

    def test_recovery_without_pending_operation_keeps_existing_result(self):
        operator = self.operator()
        with self.assertRaisesRegex(DevError, "no-pending-operation") as failure:
            operator.recover()
        self.assertFalse(failure.exception.uncertain)
        self.assertEqual(self.client.calls, [])

    def test_changed_retained_receipt_during_lookup_is_not_overwritten(self):
        operator = self.operator()
        operator.grant()
        self.client.uncertain = True
        with self.assertRaises(DevError):
            operator.revoke()
        journal = self.operator_root / "operations.json"
        before = journal.read_bytes()
        receipts = self.operator_root / "stream-policy-receipts.json"
        call = self.client.call
        self.client.calls.clear()
        changed = []

        def race(*args, **kwargs):
            result = call(*args, **kwargs)
            if "get" in args and "policy" in args:
                value = state.load(self.operator_root, receipts.name)
                value["policy:" + self.options["policy_id"]]["receipt"]["generation"] = "777"
                state.atomic(self.operator_root, receipts.name, value)
                changed.append(receipts.read_bytes())
            return result

        self.client.call = race
        with self.assertRaises(DevError) as failure:
            operator.recover()
        self.assertTrue(failure.exception.uncertain)
        self.assertEqual(len(changed), 1)
        self.assertEqual(receipts.read_bytes(), changed[0])
        self.assertEqual(journal.read_bytes(), before)
        self.assertIsNotNone(operator.journal.read()["pending"])
        self.assertEqual(len(self.mutations()), 0)

    def test_boolean_port_cannot_impersonate_owned_numeric_port(self):
        destination = {**self.options["destination"], "port": 1}
        operator = self.operator(destination=destination)
        changed = copy.deepcopy(operator.owner)
        changed["endpoint"]["port"] = True
        state.atomic(self.operator_root, "stream-operator-owner.json", changed)
        self.client.calls.clear()
        with self.assertRaisesRegex(DevError, "stream-operator-owner-changed"):
            operator.inspect("mail-deployment")
        self.assertEqual(self.client.calls, [])
        with self.assertRaisesRegex(DevError, "stream-operator-owner-changed"):
            self.operator(destination=destination)
        self.assertEqual(self.client.calls, [])

    def test_changed_private_client_configuration_or_owner_scope_fails_before_rpc(self):
        operator = self.operator()
        state.atomic(self.config_root, "config.json", {"profile": "another"})
        with self.assertRaises(DevError):
            operator.grant()
        self.assertEqual(self.client.calls, [])
        with self.assertRaises(DevError):
            self.operator(publication="another-publication")

    def test_linked_private_client_configuration_is_rejected_before_rpc(self):
        alias = self.config_root / "alias.json"
        os.link(self.config, alias)
        with self.assertRaises(DevError):
            self.operator()
        self.assertEqual(self.client.calls, [])

    def test_oversized_private_configuration_is_rejected_before_rpc(self):
        self.config.write_bytes(b"X" * 65537)
        with self.assertRaises(DevError):
            self.operator()
        self.assertEqual(self.client.calls, [])

    @unittest.skipUnless(os.name == "posix", "POSIX file mode protection; Windows uses maintained ACL checks")
    def test_group_readable_private_configuration_is_rejected_before_rpc(self):
        self.config.chmod(0o640)
        with self.assertRaisesRegex(DevError, "file-protection"):
            self.operator()
        self.assertEqual(self.client.calls, [])

    def test_http_only_cross_tenant_noncanonical_and_host_tls_inputs_cannot_build_grant(self):
        for changes in ({"provider": {**self.options["provider"], "capability": "latent:http/client@0.2.0"}},
                        {"provider": {**self.options["provider"], "tenant": "foreign"}},
                        {"destination": {**self.options["destination"], "host": "127.1"}},
                        {"destination": {**self.options["destination"], "transport": "host-tls"}},
                        {"destination": {**self.options["destination"], "port": True}}):
            with self.assertRaises(DevError):
                self.operator(**changes)
        self.assertEqual(self.client.calls, [])

    def test_inspection_retains_unavailable_counters_without_minting_authority(self):
        operator = self.operator()
        result = operator.inspect("mail-deployment")
        self.assertFalse(result["executionPermission"])
        self.assertEqual(result["nodeUsage"]["counters"], {})
        self.assertEqual(result["nodeUsage"]["unavailable"], ["outbound-stream-inspection-unavailable"])
        self.client.inspect_authority = True
        with self.assertRaises(DevError):
            operator.inspect("mail-deployment")
        self.assertEqual(len(self.mutations()), 0)

    def test_inspection_selects_exact_profile_contract_and_one_page_without_state_mutation(self):
        operator = self.operator()
        before = {path.name: path.read_bytes() for path in self.operator_root.iterdir() if path.is_file()}
        result = operator.inspect("mail-deployment")
        self.assertEqual(self.client.calls, [["capability", "list", "--deployment", "mail-deployment",
            "--provider", stream.PROFILE, "--contract-prefix", stream.CAPABILITY,
            "--include-node-usage", "--page-size", "1"]])
        self.assertEqual(result, {**self.client.inspection, "executionPermission": False})
        self.assertEqual(len(result["capabilities"]), 1)
        self.assertEqual({path.name: path.read_bytes() for path in self.operator_root.iterdir() if path.is_file()}, before)

    def test_inspection_rejects_reused_deployment_with_missing_or_foreign_publication(self):
        operator = self.operator()
        self.client.inspection["revision"]["deploymentId"] = "foreign-deployment"
        with self.assertRaisesRegex(DevError, "inspection-is-not-authority"):
            operator.inspect("mail-deployment")
        self.client.inspection["revision"]["deploymentId"] = "mail-deployment"
        for publication in (None, "publication:sha256:" + "c" * 64):
            self.client.inspection["revision"]["publicationId"] = publication
            with self.assertRaisesRegex(DevError, "inspection-publication-changed"):
                operator.inspect("mail-deployment")
        del self.client.inspection["revision"]["publicationId"]
        with self.assertRaisesRegex(DevError, "inspection-publication-changed"):
            operator.inspect("mail-deployment")
        self.assertEqual(len(self.mutations()), 0)

    def test_inspection_rejects_foreign_contract_profile_and_oversized_page(self):
        operator = self.operator()
        original = copy.deepcopy(self.client.inspection["capabilities"])
        for field, value in (("id", stream.CAPABILITY + "/alternate"),
                             ("contract", stream.CAPABILITY + "/alternate"), ("provider", "foreign-profile")):
            self.client.inspection["capabilities"] = copy.deepcopy(original)
            self.client.inspection["capabilities"][0][field] = value
            with self.assertRaisesRegex(DevError, "inspection-scope-changed"):
                operator.inspect("mail-deployment")
        self.client.inspection["capabilities"] = copy.deepcopy(original)
        self.client.inspection["capabilities"][0]["inspection"]["providerProfile"] = "foreign-profile"
        with self.assertRaisesRegex(DevError, "inspection-scope-changed"):
            operator.inspect("mail-deployment")
        for entries in (original * 2, None, [None]):
            self.client.inspection["capabilities"] = entries
            with self.assertRaisesRegex(DevError, "inspection-scope-changed"):
                operator.inspect("mail-deployment")
        self.assertEqual(len(self.mutations()), 0)

    def test_inspection_preserves_empty_unavailable_and_changed_generation_diagnostics(self):
        operator = self.operator()
        for binding_state in ("policy-changed-or-revoked", "provider-unavailable", "publication-unavailable",
                              "route-changed-or-unavailable", "inspection-indeterminate"):
            binding = self.client.inspection["capabilities"][0]["inspection"]
            binding.update(state=binding_state, providerConfigurationEpoch="2",
                           providerConfigurationDigest="sha256:" + "c" * 64)
            self.client.inspection["nodeUsage"]["counters"] = {"stream_owners": "3", "stream_retired_generations": "1"}
            self.assertEqual(operator.inspect("mail-deployment"),
                             {**self.client.inspection, "executionPermission": False})
        self.client.inspection.update(capabilities=[], state="binding-plan-unavailable")
        self.assertEqual(operator.inspect("mail-deployment"),
                         {**self.client.inspection, "executionPermission": False})
        self.assertEqual(operator.owner["provider"]["configurationEpoch"], "1")
        self.assertEqual(len(self.mutations()), 0)

    def test_explicit_new_descriptor_adoption_keeps_exact_owner_and_applies_no_mutation(self):
        operator = self.operator()
        operator.grant()
        before = copy.deepcopy(operator.owner)
        result = operator.adopt_provider({**self.options["provider"], "configurationEpoch": "2", "configurationDigest": "sha256:" + "c" * 64})
        self.assertFalse(result["executionPermission"])
        self.assertEqual(len(self.mutations()), 2)
        self.assertEqual({key: value for key, value in operator.owner.items() if key != "provider"},
                         {key: value for key, value in before.items() if key != "provider"})
        with self.assertRaisesRegex(DevError, "owner-changed"):
            self.operator()
        restarted = self.operator(provider={**self.options["provider"], "configurationEpoch": "2", "configurationDigest": "sha256:" + "c" * 64})
        restarted.grant()
        self.assertEqual(len(self.mutations()), 3)
        binding = self.client.records["provider-binding:stream-installed"]
        self.assertEqual(binding["generation"], "2")
        self.assertEqual(binding["document"]["configurationEpoch"], 2)
        self.assertEqual(self.client.records["policy:stream-allow"]["document"], operator._policy("allow"))

    def test_provider_adoption_refuses_mid_read_private_state_replacement_without_overwrite(self):
        operator = self.operator()
        operator.grant()
        owner = copy.deepcopy(operator.owner)
        names = ("stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")
        before = {name: (self.operator_root / name).read_bytes() for name in names}
        replacement = {**self.options["provider"], "configurationEpoch": "2",
                       "configurationDigest": "sha256:" + "c" * 64}
        original_call = self.client.call
        for name in names:
            for selected_read in (1, 2):
                self.client.calls.clear()
                reads = 0

                def observed(*arguments):
                    nonlocal reads
                    result = original_call(*arguments)
                    reads += 1
                    if reads == selected_read:
                        (self.operator_root / name).write_bytes(before[name] + b" ")
                    return result

                self.client.call = observed
                try:
                    with self.subTest(name=name, selected_read=selected_read), \
                            self.assertRaisesRegex(DevError, "provider-adoption-state-changed"):
                        operator.adopt_provider(replacement)
                    expected = {**before, name: before[name] + b" "}
                    self.assertEqual({item: (self.operator_root / item).read_bytes() for item in names}, expected)
                    self.assertEqual(operator.owner, owner)
                    self.assertEqual(self.mutations(), [])
                finally:
                    self.client.call = original_call
                    for item, raw in before.items():
                        (self.operator_root / item).write_bytes(raw)

    def test_provider_adoption_refuses_mid_read_client_replacement_without_owner_update(self):
        operator = self.operator()
        operator.grant()
        owner = copy.deepcopy(operator.owner)
        names = ("stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")
        before = {name: (self.operator_root / name).read_bytes() for name in names}
        original_config = self.config.read_bytes()
        replacement = {**self.options["provider"], "configurationEpoch": "2",
                       "configurationDigest": "sha256:" + "c" * 64}
        original_call = self.client.call
        for selected_read in (1, 2):
            self.client.calls.clear()
            reads = 0

            def observed(*arguments):
                nonlocal reads
                result = original_call(*arguments)
                reads += 1
                if reads == selected_read:
                    self.config.write_bytes(original_config + b" ")
                return result

            self.client.call = observed
            try:
                with self.subTest(selected_read=selected_read), \
                        self.assertRaisesRegex(DevError, "client-identity-changed"):
                    operator.adopt_provider(replacement)
                self.assertEqual(self.config.read_bytes(), original_config + b" ")
                self.assertEqual({name: (self.operator_root / name).read_bytes() for name in names}, before)
                self.assertEqual(operator.owner, owner)
                self.assertEqual(self.mutations(), [])
            finally:
                self.client.call = original_call
                self.config.write_bytes(original_config)
                for name, raw in before.items():
                    (self.operator_root / name).write_bytes(raw)

    def test_adoption_rejects_same_stale_foreign_or_unsupported_provider_without_mutation(self):
        operator = self.operator()
        operator.grant()
        before = copy.deepcopy(operator.owner)
        for patch in ({"configurationEpoch": "1"}, {"tenant": "foreign"},
                      {"id": "other"}, {"service": "other"}, {"profile": "host-tls"},
                      {"capability": "latent:http/client@0.2.0"}):
            with self.assertRaises(DevError):
                operator.adopt_provider({**self.options["provider"], "configurationEpoch": "2", "configurationDigest": "sha256:" + "c" * 64, **patch})
            self.assertEqual(operator.owner, before)
        self.assertEqual(len(self.mutations()), 2)

    def test_unknown_outcome_blocks_adoption_without_receipt_replay(self):
        operator = self.operator()
        self.client.uncertain = True
        with self.assertRaises(DevError):
            operator.grant()
        pending = copy.deepcopy(operator.journal.read()["pending"])
        with self.assertRaisesRegex(DevError, "recover-original"):
            operator.adopt_provider({**self.options["provider"], "configurationEpoch": "2", "configurationDigest": "sha256:" + "c" * 64})
        self.assertEqual(operator.journal.read()["pending"], pending)
        self.assertEqual(len(self.mutations()), 1)

    def test_changed_policy_blocks_adoption_and_preserves_private_descriptor(self):
        operator = self.operator()
        operator.grant()
        before = copy.deepcopy(operator.owner)
        self.client.records["policy:stream-allow"]["generation"] = "999"
        with self.assertRaisesRegex(DevError, "policy-changed"):
            operator.adopt_provider({**self.options["provider"], "configurationEpoch": "2", "configurationDigest": "sha256:" + "c" * 64})
        self.assertEqual(operator.owner, before)
        self.assertEqual(len(self.mutations()), 2)

    def test_type_changed_policy_reads_refuse_adoption_and_mutation_without_state_changes(self):
        operator = self.operator()
        operator.grant()
        replacement = {**self.options["provider"], "configurationEpoch": "2",
                       "configurationDigest": "sha256:" + "c" * 64}
        original = copy.deepcopy(self.client.records)
        for kind, change in (
                ("provider-binding", lambda value: value.update(revoked=0)),
                ("provider-binding", lambda value: value["document"].update(configurationEpoch=True)),
                ("policy", lambda value: value["document"]["rules"][0].update(requireAudit=1)),
                ("policy", lambda value: value["document"]["rules"][0]["ceiling"].update(operations=128.0))):
            identifier = self.options["binding_id" if kind == "provider-binding" else "policy_id"]
            self.client.records = copy.deepcopy(original)
            change(self.client.records[kind + ":" + identifier])
            for action in (lambda: operator.adopt_provider(replacement),
                           operator.grant if kind == "provider-binding" else operator.revoke):
                with self.subTest(kind=kind, changed=self.client.records[kind + ":" + identifier], action=action):
                    before = {path.name: path.read_bytes() for path in self.operator_root.iterdir() if path.is_file()}
                    owner = copy.deepcopy(operator.owner)
                    self.client.calls.clear()
                    with self.assertRaisesRegex(DevError, "policy-changed"):
                        action()
                    self.assertEqual(operator.owner, owner)
                    self.assertEqual(self.mutations(), [])
                    self.assertEqual({path.name: path.read_bytes() for path in self.operator_root.iterdir()
                                      if path.is_file()}, before)

    def test_malformed_retained_policy_cannot_match_missing_or_malformed_live_fields(self):
        operator = self.operator()
        operator.grant()
        original = operator._records()
        key = "provider-binding:" + self.options["binding_id"]
        replacement = {**self.options["provider"], "configurationEpoch": "2",
                       "configurationDigest": "sha256:" + "c" * 64}
        for previous in (None, [], {}, {"receipt": None, "document": original[key]["document"]},
                         {"receipt": original[key]["receipt"], "document": None},
                         {"receipt": {field: value for field, value in original[key]["receipt"].items()
                                      if field != "revoked"}, "document": original[key]["document"]},
                         {"receipt": {**original[key]["receipt"], "revoked": 0},
                          "document": original[key]["document"]}):
            records = {**original, key: previous}
            state.atomic(self.operator_root, "stream-policy-receipts.json", records)
            self.client.records[key].pop("revoked", None)
            for action in (operator.grant, lambda: operator.adopt_provider(replacement)):
                with self.subTest(previous=previous, action=action):
                    before = {path.name: path.read_bytes() for path in self.operator_root.iterdir() if path.is_file()}
                    self.client.calls.clear()
                    with self.assertRaisesRegex(DevError, "policy-changed"):
                        action()
                    self.assertEqual(self.mutations(), [])
                    self.assertEqual({path.name: path.read_bytes() for path in self.operator_root.iterdir()
                                      if path.is_file()}, before)

    def test_same_owned_policy_rejects_wrong_stamp_types_in_both_records(self):
        operator = self.operator()
        operator.grant()
        previous = operator._records()["provider-binding:" + self.options["binding_id"]]
        current = self.client.records["provider-binding:" + self.options["binding_id"]]
        self.assertTrue(stream._same_owned_policy(current, previous))
        for field in stream.STAMP_FIELDS:
            for value in (None, False, 0, 1, {}, []):
                if type(value) is type(previous["receipt"][field]):
                    continue
                with self.subTest(field=field, value=value):
                    altered = {**previous, "receipt": {**previous["receipt"], field: value}}
                    self.assertFalse(stream._same_owned_policy({**current, field: value}, altered))
                    self.assertFalse(stream._same_owned_policy(current, altered))
                    self.assertFalse(stream._same_owned_policy({**current, field: value}, previous))

    def test_apply_compares_requested_document_without_bool_number_idempotence(self):
        operator = self.operator()
        operator.grant()
        key = "provider-binding:" + self.options["binding_id"]
        requested = copy.deepcopy(self.client.records[key]["document"])
        requested["configurationEpoch"] = True
        self.client.calls.clear()
        # This internal seam isolates the requested-document comparison; public
        # grant construction continues to supply the original integer epoch.
        operator._apply("provider-binding", self.options["binding_id"], requested)
        self.assertEqual(len(self.mutations()), 1)
        self.assertIs(self.client.records[key]["document"]["configurationEpoch"], True)
        self.assertEqual(self.client.records[key]["generation"], "2")


    def test_malformed_cli_mutation_envelope_keeps_original_intent_for_recovery(self):
        from tools.dev_workflow.client import Client
        for number,category in enumerate(("unrecognized-result", "not-found", ["bad-category"], "success")):
            with self.subTest(category_type=type(category).__name__, category_index=number):
                root=self.root/("response-"+str(number));paths.new_directory(root)
                rpc=PolicyRpc(self.config)
                operator=stream.StreamOperator(root,rpc,**self.options)
                process_client=Client(Path("selected-cli"),self.config,root)
                original=rpc.call
                def malformed(*arguments, **kwargs):
                    actual=original(*arguments, **kwargs) # The source-port backend applies exactly once.
                    if "apply" not in arguments:
                        return actual
                    value={"schemaVersion":"latent.cli.result.v1","category":category,
                           "outcomeKnown":True,"requestDispatched":True,
                           "data":actual["data"] if category=="success" else {}}
                    response=subprocess.CompletedProcess([],4,encode(value),b"")
                    with patch("tools.dev_workflow.client.process.run",return_value=response):
                        return process_client.call(*arguments, **kwargs)
                rpc.call=malformed
                with self.assertRaises(DevError) as caught:
                    operator.grant()
                pending=operator.journal.read()["pending"]
                self.assertIsNotNone(pending,"applied mutation must remain pending for its original receipt")
                self.assertTrue(caught.exception.uncertain,"ambiguous mutation must retain its journal")
                self.assertEqual(pending["intent"]["recordKind"],"provider-binding")
                self.assertEqual(operator._records(),{})
                self.assertEqual(len([args for args in rpc.calls if "apply" in args]),1)
                rpc.call=original
                operator.recover()
                self.assertIsNone(operator.journal.read()["pending"])
                operator.grant()
                applies=[args for args in rpc.calls if "apply" in args]
                self.assertEqual(len(applies),2)
                self.assertEqual(sum(pending["id"] in args for args in applies),1)

    def test_nonobject_cli_response_is_a_redacted_structured_refusal(self):
        from tools.dev_workflow.client import Client
        for value in (None,False,7,"PUBLIC-CANARY-DO-NOT-LOG",["PUBLIC-CANARY-DO-NOT-LOG"]):
            with self.subTest(kind=type(value).__name__):
                observations=[]
                selected=Client(Path("selected-cli"),self.config,self.operator_root,observer=observations.append)
                response=subprocess.CompletedProcess([],4,encode(value),b"private-output")
                with patch("tools.dev_workflow.client.process.run",return_value=response) as invoked:
                    with self.assertRaisesRegex(DevError,"operator-response-format"):
                        selected.call("policy","apply","PUBLIC-CANARY-ARGUMENT")
                self.assertEqual(invoked.call_count,1)
                self.assertEqual(observations[0]["validationCode"],"operator-response-format")
                self.assertNotIn("PUBLIC-CANARY",str(observations))
                self.assertNotIn("private-output",str(observations))


    def test_cli_result_categories_match_the_native_exit_contract(self):
        from tools.dev_workflow.client import Client
        selected=Client(Path("selected-cli"),self.config,self.operator_root)
        categories=(("success",0),("local-error",2),("declared-error",3),
                    ("platform-failure",4),("transport-failure",5),("not-found",6),("interrupted",130))
        for category,status in categories:
            value={"schemaVersion":"latent.cli.result.v1","category":category,
                   "outcomeKnown":True,"requestDispatched":False,"data":{}}
            with self.subTest(category=category):
                response=subprocess.CompletedProcess([],status,encode(value),b"")
                with patch("tools.dev_workflow.client.process.run",return_value=response):
                    self.assertEqual(selected.call("policy","get"),value)
                wrong=5 if status!=5 else 4
                response=subprocess.CompletedProcess([],wrong,encode(value),b"")
                with patch("tools.dev_workflow.client.process.run",return_value=response):
                    with self.assertRaisesRegex(DevError,"operator-response-exit-mismatch"):
                        selected.call("policy","get")


    def test_changed_protected_client_between_observation_and_mutation_refuses(self):
        operator = self.operator()
        original = self.config.read_bytes()
        changed = original + b' '
        original_call = self.client.call
        consumed = []
        changed_once = False

        def call(*args, **kwargs):
            nonlocal changed_once
            if 'apply' in args:
                consumed.append(self.config.read_bytes())
            result = original_call(*args, **kwargs)
            if 'get' in args and not changed_once:
                self.config.write_bytes(changed)
                changed_once = True
            return result

        with patch.object(self.client, 'call', side_effect=call):
            with self.assertRaisesRegex(DevError, 'client-identity-changed'):
                operator.grant()
        self.assertEqual(consumed, [])
        self.assertEqual(self.mutations(), [])
        self.assertEqual(operator._records(), {})

    def test_child_open_refusal_does_not_dispatch_or_repeat_a_policy_mutation(self):
        class GuardedRpc(PolicyRpc):
            def call(inner, *args, **kwargs):
                if 'apply' in args:
                    # Model replacement after the parent's last precheck and
                    # after journal.begin, but before the child opens its file.
                    inner.config.write_bytes(inner.config.read_bytes() + b' ')
                    if digest(inner.config.read_bytes()) != inner.expected_config_digest:
                        return {'outcomeKnown': True, 'requestDispatched': False,
                                'category': 'local-error', 'data': {}}
                return super().call(*args, **kwargs)

        self.client = GuardedRpc(self.config)
        operator = self.operator()
        with self.assertRaisesRegex(DevError, 'operator-request-rejected'):
            operator.grant()
        self.assertEqual(self.client.records, {})
        self.assertEqual(operator._records(), {})
        self.assertEqual(self.mutations(), [])
        self.assertIsNone(operator.journal.read()['pending'])
        self.assertEqual(len(operator.journal.read()['history']), 1)

    def test_dispatched_unknown_stays_pending_if_config_changes_before_recovery(self):
        operator = self.operator()
        original = self.config.read_bytes()
        call = self.client.call
        self.client.uncertain = True

        def dispatch(*args, **kwargs):
            result = call(*args, **kwargs)
            if 'apply' in args:
                self.config.write_bytes(original + b' ')
            return result

        with patch.object(self.client, 'call', side_effect=dispatch), self.assertRaises(DevError) as failure:
            operator.grant()
        self.assertTrue(failure.exception.uncertain)
        pending = operator.journal.read()['pending']
        self.assertIsNotNone(pending)
        with self.assertRaisesRegex(DevError, 'client-identity-changed') as failed_recovery:
            operator.recover()
        self.assertTrue(failed_recovery.exception.uncertain)
        self.assertEqual(operator.journal.read()['pending'], pending)
        self.assertEqual(len(self.mutations()), 1)
        self.config.write_bytes(original)
        operator.recover()
        self.assertIsNone(operator.journal.read()['pending'])
        self.assertEqual(len(self.mutations()), 1)

    def test_owned_process_passes_digest_on_stdin_and_scripted_child_checks_its_open(self):
        import tools.dev_workflow.client as client_module

        original = self.config.read_bytes()
        expected = digest(original)
        selected = Client(sys.executable, self.config, self.operator_root)
        selected.pin_config(expected)
        runner = client_module.process.run
        observed = []
        mutate = False
        script = r'''
import hashlib, json, pathlib, sys
args = sys.argv[1:]
path = pathlib.Path(args[args.index('--config') + 1])
pin = sys.stdin.buffer.read(72)
tail = sys.stdin.buffer.read()
actual = ('sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() + '\n').encode('ascii')
matched = '--expect-config-digest-stdin' in args and pin == actual
print(json.dumps({'schemaVersion':'latent.cli.result.v1', 'outcomeKnown':True,
                  'requestDispatched':False, 'category':'success' if matched else 'local-error',
                  'data':{'matched':matched, 'tailSize':len(tail),
                          'tailDigest':'sha256:' + hashlib.sha256(tail).hexdigest()}}))
sys.exit(0 if matched else 2)
'''

        def run_child(argv, cwd, **kwargs):
            observed.append((list(argv), kwargs['stdin']))
            if mutate:
                self.config.write_bytes(original + b' ')
            return runner([sys.executable, '-c', script, *argv[1:]], cwd, **kwargs)

        payload = encode({'marker': 'synthetic-policy-input-only'})
        with patch.object(client_module.process, 'run', side_effect=run_child):
            self.assertTrue(selected.call('policy', 'get')['data']['matched'])
            mutate = True
            refused = selected.call('policy', 'get')
            self.config.write_bytes(original)
            mutate = False
            delivered = selected.call('policy', 'apply', '--file', '-', stdin=payload)
            controlled = selected.control('typescript', 'deployment', 'apply', '-', stdin=payload)
        self.assertEqual(refused['category'], 'local-error')
        self.assertFalse(refused['requestDispatched'])
        self.assertTrue(delivered['data']['matched'])
        self.assertEqual(delivered['data']['tailSize'], len(payload))
        self.assertEqual(delivered['data']['tailDigest'], digest(payload))
        self.assertTrue(controlled['data']['matched'])
        self.assertEqual(controlled['data']['tailSize'], len(payload))
        self.assertEqual(controlled['data']['tailDigest'], digest(payload))
        self.assertEqual([item[1] for item in observed],
                         [(expected + '\n').encode()] * 2 + [(expected + '\n').encode() + payload] * 2)
        self.assertTrue(all('--expect-config-digest-stdin' in argv for argv, _ in observed))
        self.assertTrue(all(expected not in argv and payload.decode() not in str(argv) for argv, _ in observed))
        with self.assertRaisesRegex(DevError, 'operator-client-already-bound'):
            selected.pin_config(digest(original + b' '))


class StreamConfiguration(unittest.TestCase):
    def setUp(self):
        self.settings = {"budgetProfile": {"mode": "phase3"}, "audit": {"mode": "durable"},
            "capabilityPolicies": {"formatVersion": 1}, "credentials": [{"token": "PUBLIC-CONTROL-ONLY"}],
            "providers": {"formatVersion": 1, "bindings": []}}
        self.installation = {"identity": {"id": "streams", "tenant": "examples", "service": "stream-host", "epoch": 1},
            "configuration": {"formatVersion": 1, "profile": stream.PROFILE,
                "destinations": [{"endpoint": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
                    "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
                    "resolution": {"kind": "static", "addresses": ["127.0.0.1"]}}],
                "limits": {"maximumTransferBytes": 65536, "idleTimeoutMillis": 1000, "absoluteTimeoutMillis": 5000}}}
        self.bindings = [{"name": "mail-stream", "tenant": "examples", "consumerService": "examples/mail",
                          "providerService": "stream-host", "contract": stream.CAPABILITY, "providerBinding": "stream-installed"}]

    def configure(self, **options):
        return stream.configure(self.settings, self.installation, self.bindings, **options)

    def test_configuration_is_explicitly_gated_and_preserves_all_other_node_inputs(self):
        before = copy.deepcopy(self.settings)
        with self.assertRaises(DevError):
            self.configure()
        value = self.configure(development_profile=True)
        self.assertEqual(self.settings, before)
        self.assertEqual(value["credentials"], before["credentials"])
        self.assertEqual(value["audit"], before["audit"])
        self.assertEqual(value["providers"]["outboundStreams"], self.installation)

    def test_cross_scope_and_http_bindings_are_rejected_without_mutating_node(self):
        original = copy.deepcopy(self.settings)
        for field, replacement in (("tenant", "foreign"), ("providerService", "other"),
                                   ("contract", "latent:http/client@0.2.0")):
            self.bindings[0][field] = replacement
            with self.assertRaises(DevError):
                self.configure(development_profile=True)
            self.bindings[0][field] = {"tenant": "examples", "providerService": "stream-host", "contract": stream.CAPABILITY}[field]
        self.assertEqual(self.settings, original)

    def test_installed_provider_requires_live_owner_rotation_and_not_an_input_overwrite(self):
        self.settings["providers"]["outboundStreams"] = copy.deepcopy(self.installation)
        with self.assertRaisesRegex(DevError, "needs-owner-rotation"):
            self.configure(development_profile=True)

    def test_unknown_secret_host_tls_float_and_widened_bounds_fail_with_static_diagnostics(self):
        original = copy.deepcopy(self.installation)
        for patch in ({"clientKey": "PRIVATE-DO-NOT-ECHO"},
                      {"limits": {"maximumTransferBytes": 1048577, "idleTimeoutMillis": 2001, "absoluteTimeoutMillis": 10001}},
                      {"formatVersion": 1.0}):
            self.installation["configuration"].update(patch)
            with self.assertRaises(DevError) as failure:
                self.configure(development_profile=True)
            self.assertNotIn("PRIVATE-DO-NOT-ECHO", str(failure.exception))
            self.installation = copy.deepcopy(original)


if __name__ == "__main__":
    unittest.main()
