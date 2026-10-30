"""Protected management-token handoff controls; RPCs are explicit protocol doubles."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import outbound_stream_operator as stream
from tools.dev_workflow import paths, state
from tools.dev_workflow.common import DevError, digest, encode
from tools.tests.test_outbound_stream_operator import PolicyRpc


class ReplacementRpc(PolicyRpc):
    def __init__(self, config, records, directory):
        super().__init__(config)
        self.records = copy.deepcopy(records)
        self.binary, self.directory, self.deadline = directory / "selected-latent", directory, 12345.0
        self.node = "node"
        self.hook = None
        self.failure = None

    def call(self, *arguments):
        if arguments[0] == "node":
            self.calls.append(list(map(str, arguments)))
            result = {"outcomeKnown": True, "category": "success", "data": {"inventory": {"node": {"id": self.node}}}}
        else:
            result = super().call(*arguments)
        if self.hook:
            self.hook()
        if self.failure:
            return {"outcomeKnown": self.failure != "uncertain", "category": "transport-failure", "data": {}}
        return result


class ClientAdoption(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).absolute()
        self.root.chmod(0o700)
        self.config_root, self.operator_root = self.root / "client", self.root / "operator"
        paths.new_directory(self.config_root)
        paths.new_directory(self.operator_root)
        self.config, self.candidate = self.config_root / "old.json", self.config_root / "new.json"
        self.document = {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{
            "name": "operator", "endpoint": "http://127.0.0.1:32123", "tenant": "examples",
            "token": "PUBLIC_SOURCE_CONTROL_OLD_TOKEN_0000000000", "rpcTimeoutMillis": 1000,
            "limits": {"maximumResponseBytes": 1048576}}]}
        self.replacement_document = copy.deepcopy(self.document)
        self.replacement_document["profiles"][0]["token"] = "PUBLIC_SOURCE_CONTROL_NEW_TOKEN_0000000000"
        paths.write_new(self.config, encode(self.document))
        paths.write_new(self.candidate, encode(self.replacement_document))
        self.client = PolicyRpc(self.config)
        self.client.binary, self.client.directory, self.client.deadline = self.operator_root / "selected-latent", self.operator_root, 12345.0
        self.options = {"node": "node", "tenant": "examples", "provider": {
            "id": "streams", "tenant": "examples", "service": "stream-host",
            "capability": stream.CAPABILITY, "profile": stream.PROFILE,
            "configurationDigest": "sha256:" + "a" * 64, "configurationEpoch": "1"},
            "consumer": "examples/mail", "publication": "publication-v1:sha256:" + "b" * 64,
            "principal": {"kind": "administrator", "subject": "operator"},
            "destination": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
            "binding_id": "stream-installed", "policy_id": "stream-allow"}
        self.operator = stream.StreamOperator(self.operator_root, self.client, **self.options)
        self.operator.grant()
        self.client.calls.clear()
        self.replacement = ReplacementRpc(self.candidate, self.client.records, self.operator_root)

    def snapshot(self):
        return {path.name: path.read_bytes() for path in self.operator_root.iterdir() if path.is_file()}

    def write_candidate(self, value):
        state.atomic(self.config_root, self.candidate.name, value)

    def test_token_handoff_reads_only_three_owned_records_and_restart_matches_new_owner(self):
        before, owner = self.snapshot(), copy.deepcopy(self.operator.owner)
        old, new = self.config.read_bytes(), self.candidate.read_bytes()
        result = self.operator.adopt_client(self.replacement)
        self.assertEqual(result, {"executionPermission": False, "outcome": "client-token-adopted-original-grants-retained"})
        self.assertEqual(self.replacement.calls, [["node", "get", "node"],
            ["policy", "--kind", "provider-binding", "get", "--id", "stream-installed"],
            ["policy", "--kind", "policy", "get", "--id", "stream-allow"]])
        self.assertEqual(self.client.calls, [])
        owner["clientConfigurationDigest"] = digest(new)
        self.assertEqual(self.operator.owner, owner)
        after = self.snapshot()
        self.assertEqual({name: raw for name, raw in after.items() if name != "stream-operator-owner.json"},
                         {name: raw for name, raw in before.items() if name != "stream-operator-owner.json"})
        self.assertEqual((self.config.read_bytes(), self.candidate.read_bytes()), (old, new))
        self.assertIs(self.operator.client, self.replacement)
        restarted = stream.StreamOperator(self.operator_root, self.replacement, **self.options)
        self.assertEqual(restarted.owner, owner)
        with self.assertRaisesRegex(DevError, "owner-changed"):
            stream.StreamOperator(self.operator_root, self.client, **self.options)
        self.assertNotIn(self.replacement_document["profiles"][0]["token"], json.dumps(after["stream-operator-owner.json"].decode()))
        self.assertNotIn(str(self.candidate), after["stream-operator-owner.json"].decode())

    def test_non_token_profile_endpoint_tenant_timeout_and_limit_changes_refuse_before_rpc(self):
        before = self.snapshot()
        for field, value in (("endpoint", "http://127.0.0.1:32124"), ("tenant", "foreign"),
                             ("name", "foreign"), ("rpcTimeoutMillis", 1001),
                             ("limits", {"maximumResponseBytes": 1024}),
                             ("token", self.document["profiles"][0]["token"])):
            candidate = copy.deepcopy(self.replacement_document)
            candidate["profiles"][0][field] = value
            self.write_candidate(candidate)
            with self.subTest(field=field), self.assertRaises(DevError):
                self.operator.adopt_client(self.replacement)
            self.assertEqual(self.replacement.calls, [])
            self.assertEqual(self.snapshot(), before)

    def test_profile_resolution_duplicates_unknown_fields_and_finite_bounds(self):
        for transform in (
                lambda v: v.update(profiles=v["profiles"] * 2),
                lambda v: v.update(profiles=v["profiles"] * 17),
                lambda v: v.update(defaultProfile="missing"),
                lambda v: v.update(formatVersion=True),
                lambda v: v.update(unreviewed=True),
                lambda v: v["profiles"][0].update(token=True),
                lambda v: v["profiles"][0].update(token="private"),
                lambda v: v["profiles"][0].update(rpcTimeoutMillis=True),
                lambda v: v["profiles"][0].update(limits={"maximumPayloadBytes": 1048577})):
            candidate = copy.deepcopy(self.replacement_document)
            transform(candidate)
            self.write_candidate(candidate)
            with self.assertRaises(DevError):
                self.operator.adopt_client(self.replacement)
        raw = encode(self.replacement_document).replace(b'"formatVersion":1', b'"formatVersion":1,"formatVersion":1')
        self.candidate.write_bytes(raw)
        with self.assertRaisesRegex(DevError, "duplicate-field"):
            self.operator.adopt_client(self.replacement)
        self.assertEqual(self.replacement.calls, [])
        single = copy.deepcopy(self.replacement_document)
        del single["defaultProfile"]
        masked, _ = stream._client_adoption_document(encode(single), "examples")
        self.assertIsNone(masked["profiles"][0]["token"])
        other = copy.deepcopy(single["profiles"][0]);other["name"] = "other"
        single["profiles"].append(other)
        with self.assertRaisesRegex(DevError, "profile-selection"):
            stream._client_adoption_document(encode(single), "examples")
        single["defaultProfile"] = "other"
        masked, _ = stream._client_adoption_document(encode(single), "examples")
        self.assertIsNone(masked["profiles"][1]["token"])
        self.assertEqual(masked["profiles"][0]["token"], single["profiles"][0]["token"])

    def test_pending_original_operation_blocks_before_replacement_reads(self):
        pending = self.operator.journal.begin("policy", {"original": "unresolved"})
        before = self.snapshot()
        with self.assertRaisesRegex(DevError, "recover-original-operation-before-client-adoption"):
            self.operator.adopt_client(self.replacement)
        self.assertEqual(self.operator.journal.read()["pending"], pending)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.replacement.calls, [])

    def test_foreign_node_changed_policy_stamp_and_document_refuse_without_local_commit(self):
        before = self.snapshot()
        self.replacement.node = "foreign"
        with self.assertRaisesRegex(DevError, "client-node-changed"):
            self.operator.adopt_client(self.replacement)
        self.replacement.node = "node"
        for key in ("provider-binding:stream-installed", "policy:stream-allow"):
            wrong_document = {**self.client.records[key]["document"], "formatVersion": True}
            for field, value in (("generation", "999"), ("document", {"unowned": True}),
                                 ("revoked", 0), ("document", wrong_document)):
                self.replacement.records = copy.deepcopy(self.client.records)
                self.replacement.records[key][field] = value
                with self.subTest(key=key, field=field), self.assertRaisesRegex(DevError, "policy-changed"):
                    self.operator.adopt_client(self.replacement)
                self.assertEqual(self.snapshot(), before)
        self.assertFalse(any("apply" in call for call in self.replacement.calls))

    def test_denied_or_uncertain_replacement_read_preserves_original_owner(self):
        before = self.snapshot()
        for failure in ("denied", "uncertain"):
            self.replacement.failure = failure
            self.replacement.calls.clear()
            with self.subTest(failure=failure), self.assertRaises(DevError) as caught:
                self.operator.adopt_client(self.replacement)
            self.assertEqual(caught.exception.uncertain, failure == "uncertain")
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.replacement.calls, [["node", "get", "node"]])
            self.assertEqual(self.client.calls, [])
        for malformed in ({"outcomeKnown": True, "data": {}},
                          {"outcomeKnown": True, "category": "success", "data": None}, None):
            with patch.object(self.replacement, "call", return_value=malformed), \
                    self.assertRaisesRegex(DevError, "client-observation-unavailable"):
                self.operator.adopt_client(self.replacement)
            self.assertEqual(self.snapshot(), before)

    def test_input_and_local_state_changes_during_read_window_refuse_byte_exactly(self):
        before, original, candidate = self.snapshot(), self.config.read_bytes(), self.candidate.read_bytes()
        targets = [self.config, self.candidate] + [self.operator_root / name for name in (
            "stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")]
        for target in targets:
            self.replacement.calls.clear()
            self.replacement.hook = lambda: target.write_bytes(target.read_bytes() + b" ")
            try:
                with self.subTest(target=target.name), self.assertRaises(DevError):
                    self.operator.adopt_client(self.replacement)
                # The helper never overwrites a concurrent private-file edit.
                self.assertTrue(target.read_bytes().endswith(b" "))
                self.assertEqual(self.operator.owner["clientConfigurationDigest"], digest(original))
            finally:
                self.config.write_bytes(original);self.candidate.write_bytes(candidate)
                for name, raw in before.items(): (self.operator_root / name).write_bytes(raw)

    def test_protected_replacement_links_size_and_mode_refuse_before_rpc(self):
        alias = self.config_root / "alias.json"
        os.link(self.candidate, alias)
        with self.assertRaises(DevError): self.operator.adopt_client(self.replacement)
        alias.unlink()
        candidate = self.candidate.read_bytes()
        self.candidate.write_bytes(b"X" * 65537)
        with self.assertRaisesRegex(DevError, "file-byte-bound"):
            self.operator.adopt_client(self.replacement)
        self.candidate.write_bytes(candidate)
        if os.name == "posix":
            self.candidate.chmod(0o640)
            with self.assertRaisesRegex(DevError, "file-protection"):
                self.operator.adopt_client(self.replacement)
        self.assertEqual(self.replacement.calls, [])

    def test_missing_old_file_and_unowned_receipts_cannot_create_a_new_owner(self):
        before = self.snapshot()
        self.config.unlink()
        with self.assertRaises((DevError, OSError)):
            self.operator.adopt_client(self.replacement)
        paths.write_new(self.config, encode(self.document))
        state.atomic(self.operator_root, "stream-policy-receipts.json", {})
        with self.assertRaisesRegex(DevError, "no-owned-grant"):
            self.operator.adopt_client(self.replacement)
        self.assertEqual(self.replacement.calls, [])
        self.assertEqual(self.operator.owner["clientConfigurationDigest"], digest(encode(self.document)))
        self.assertEqual(self.snapshot()["stream-operator-owner.json"], before["stream-operator-owner.json"])

    def test_existing_frontend_entrypoint_constructs_same_binary_client_and_redacts_refusals(self):
        specification = {k: v for k, v in self.options.items() if k not in {"binding_id", "policy_id"}}
        specification.update(bindingId=self.options["binding_id"], policyId=self.options["policy_id"])
        path = self.config_root / "spec.json"
        paths.write_new(path, encode(specification))
        arguments = ["adopt-client", "--cli", str(self.client.binary), "--client-config", str(self.config),
            "--state-dir", str(self.operator_root), "--specification", str(path),
            "--replacement-client-config", str(self.candidate)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("tools.dev_workflow.client.Client", side_effect=[self.client, self.replacement]) as clients, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(stream.main(arguments), 0)
        self.assertEqual(clients.call_args_list[1].args, (self.client.binary, self.candidate, self.operator_root))
        self.assertEqual(clients.call_args_list[1].kwargs, {"deadline": self.client.deadline})
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["command"], "adopt-client")
        self.assertFalse(result["result"]["executionPermission"])
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(stream.main(["grant", "--replacement-client-config", str(self.candidate)]), 1)
        public = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(str(self.candidate), public)
        self.assertNotIn(self.replacement_document["profiles"][0]["token"], public)


if __name__ == "__main__":
    unittest.main()
