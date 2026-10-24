"""Policy RPC sequencing, protected state and exact authority source controls."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from tools import outbound_stream_operator as stream
from tools.dev_workflow import paths, state
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
                "publicationId": "publication-v1:sha256:" + "b" * 64,
                "routeGeneration": "1", "catalogTransaction": "1"},
            "nextPageToken": None, "state": "compiled-plan",
            "tenantUsage": {"scope": "tenant", "counters": {}, "unavailable": []},
            "nodeUsage": {"scope": "node", "counters": {}, "unavailable": ["outbound-stream-inspection-unavailable"]}}

    def call(self, *arguments):
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
        document = json.loads(Path(args[args.index("--file") + 1]).read_text())
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
            "consumer": "examples/mail", "publication": "publication-v1:sha256:" + "b" * 64,
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
        for publication in (None, "publication-v1:sha256:" + "c" * 64):
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
