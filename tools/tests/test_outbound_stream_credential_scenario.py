"""Focused controller controls; native execution is an explicit separate command."""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import outbound_stream_credential_scenario as scenario
from tools.dev_workflow.common import DevError


class CredentialScenario(unittest.TestCase):
    def client(self):
        return scenario.ObservedClient(Path("native-cli"), Path("private.json"), Path("owner"), deadline=123.0)

    def test_only_successful_selected_apply_is_withheld_once_without_replay(self):
        client = self.client()
        client.withhold_kind = "policy"
        success = {"outcomeKnown": True, "category": "success", "data": {}, "error": None}
        with patch.object(scenario.Client, "call", return_value=success) as native:
            with self.assertRaisesRegex(DevError, "confirmation-withheld") as caught:
                client.call("policy", "--kind", "policy", "apply")
            self.assertTrue(caught.exception.uncertain)
            self.assertTrue(client.withheld)
            self.assertIsNone(client.withhold_kind)
            self.assertEqual(native.call_count, 1)
            self.assertEqual(client.mutations, 1)
            self.assertIs(client.call("policy", "--kind", "policy", "get"), success)
            self.assertEqual(native.call_count, 2)
            self.assertEqual(client.mutations, 1)

    def test_native_failure_cannot_be_relabelled_as_successful_response_loss(self):
        for known, category in ((True, "platform-failure"), (False, "transport-failure")):
            with self.subTest(category=category):
                client = self.client()
                client.withhold_kind = "policy"
                result = {"outcomeKnown": known, "category": category, "data": {},
                          "error": {"code": "unavailable"}}
                with patch.object(scenario.Client, "call", return_value=result) as native:
                    with self.assertRaises(DevError) as caught:
                        client.call("policy", "--kind", "policy", "apply")
                    self.assertNotEqual(caught.exception.code, "credential-scenario-confirmation-withheld")
                    self.assertFalse(client.withheld)
                    self.assertEqual(native.call_count, 1)
                    self.assertEqual(client.last_status, (category, "unavailable", known))

    def test_other_binding_mutation_and_reads_do_not_consume_selected_loss(self):
        client = self.client()
        client.withhold_kind = "policy"
        success = {"outcomeKnown": True, "category": "success", "data": {}}
        with patch.object(scenario.Client, "call", return_value=success):
            self.assertIs(client.call("policy", "--kind", "provider-binding", "apply"), success)
            self.assertIs(client.call("policy", "--kind", "policy", "get"), success)
        self.assertEqual((client.attempts, client.mutations), (2, 1))
        self.assertEqual(client.withhold_kind, "policy")
        self.assertFalse(client.withheld)

    def test_call_limit_refuses_before_another_process_or_mutation(self):
        client = self.client()
        client.attempts = scenario.MAX_CALLS
        with patch.object(scenario.Client, "call") as native:
            with self.assertRaisesRegex(DevError, "call-bound"):
                client.call("policy", "--kind", "policy", "apply")
            native.assert_not_called()
        self.assertEqual(client.mutations, 0)

    def test_management_observation_preserves_not_ready_and_rejects_foreign_identity(self):
        client = self.client()
        inventory = {"node": {"id": scenario.NODE}, "health": {"ready": False}}
        result = {"outcomeKnown": True, "category": "success", "data": {"inventory": inventory}}
        with patch.object(scenario.Client, "call", return_value=result):
            self.assertIs(scenario.inspect_node(client), False)
            inventory["health"]["ready"] = True
            self.assertIs(scenario.inspect_node(client), True)
            for health in (None, 1, "true"):
                inventory["health"]["ready"] = health
                with self.assertRaisesRegex(DevError, "node-identity"):
                    scenario.inspect_node(client)
            inventory["health"]["ready"] = True
            inventory["node"]["id"] = "foreign"
            with self.assertRaisesRegex(DevError, "node-identity"):
                scenario.inspect_node(client)

    def test_missing_refusal_or_known_failure_does_not_qualify_uncertainty(self):
        with self.assertRaisesRegex(DevError, "missing-refusal"):
            scenario.refused(lambda: None)
        with self.assertRaisesRegex(DevError, "wrong-refusal"):
            scenario.refused(lambda: (_ for _ in ()).throw(DevError("known-failure")))
        scenario.refused(lambda: (_ for _ in ()).throw(DevError("original-pending", uncertain=True)),
                         "original-pending")

    def test_no_stream_or_ambient_provider_is_added_to_management_fixture(self):
        value = scenario.configuration("ephemeral-test-value")
        self.assertNotIn("providers", value)
        self.assertNotIn("development", value)
        self.assertNotIn("httpIngress", value)
        self.assertEqual(value["bind"], "127.0.0.1:0")
        self.assertEqual(value["audit"]["mode"], "durable")
        self.assertEqual(value["capabilityPolicies"]["maximumControlJobs"], 2)
        self.assertEqual(scenario.specification()["destination"]["transport"], "tcp")

    def test_new_work_directory_never_overwrites_an_existing_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).absolute()
            marker = root / "retained-owner"
            marker.write_text("original")
            with patch.object(scenario, "start") as native:
                with self.assertRaises(FileExistsError):
                    scenario.run_case("first-binding", Path("node"), Path("cli"), root, None, 123.0)
                native.assert_not_called()
            self.assertEqual(marker.read_text(), "original")

    def test_start_accepts_both_actual_readiness_events_and_rejects_mismatch(self):
        endpoint = "127.0.0.1:31415"
        for ready, event in ((False, "started"), (True, "ready")):
            with self.subTest(ready=ready):
                child = Mock()
                child.line.return_value = {"event": event, "ready": ready, "endpoint": endpoint}
                with patch.object(scenario, "Process", return_value=child):
                    observed, actual = scenario.start(Path("node"), Path("private"), None, 1e20)
                self.assertIs(observed, child)
                self.assertEqual(actual, endpoint)
                child.close.assert_not_called()
        for ready, event in ((True, "started"), (False, "ready"), (None, "started"), (1, "ready")):
            with self.subTest(ready=ready, event=event):
                child = Mock()
                child.line.return_value = {"event": event, "ready": ready, "endpoint": endpoint}
                with patch.object(scenario, "Process", return_value=child):
                    with self.assertRaisesRegex(DevError, "credential-scenario-node-startup"):
                        scenario.start(Path("node"), Path("private"), None, 1e20)
                child.close.assert_called_once()

    def test_failure_output_never_copies_exception_text_paths_or_credentials(self):
        output = io.StringIO()
        with patch.object(scenario, "run", side_effect=OSError("PRIVATE_TOKEN /private/unsafe-path")), \
                redirect_stderr(output):
            self.assertEqual(scenario.main(["--node", "node", "--cli", "cli", "--work-dir", "work"]), 1)
        value = json.loads(output.getvalue())
        self.assertEqual(value, {"schemaVersion": scenario.SCHEMA, "status": "failed", "productionReadiness": False})
        self.assertNotIn("PRIVATE_TOKEN", output.getvalue())
        self.assertNotIn("/private", output.getvalue())


if __name__ == "__main__":
    unittest.main()
