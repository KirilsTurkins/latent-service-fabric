"""Policy RPC sequencing, protected state and exact authority source controls."""
from __future__ import annotations

import copy
import json
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

    def call(self, *arguments):
        args = list(map(str, arguments))
        self.calls.append(args)
        result = {"outcomeKnown": True, "category": "success", "data": {}}
        if args[0] == "capability":
            result["data"] = {"executionPermission": self.inspect_authority,
                "revision": {"deploymentId": args[args.index("--deployment") + 1]},
                "nodeUsage": {"scope": "node", "counters": {}, "unavailable": ["outbound-stream-inspection-unavailable"]}}
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
