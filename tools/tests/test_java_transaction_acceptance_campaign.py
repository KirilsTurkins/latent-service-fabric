"""Version/replay and original-bound oracles; frames are synthetic, never execution."""
import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.java_transaction_qualification import acceptance_campaign, acceptance_inputs, http, policies
from tools.tests.test_java_transaction_provision import observation
from tools.tests.test_java_transaction_qualification import result, token


def frame(count, key, *, query=False, generation=2):
    value = result("query" if query else "committed", count)
    body = [{"ok": {"count": count, "view-version": list(token(generation=generation)), "key-version": key}}]
    value["result"]["body-base64"] = base64.b64encode(json.dumps(body).encode()).decode()
    value["state-view"] = base64.b64encode(token(generation=generation)).decode()
    return value


class AcceptanceCampaignTests(unittest.TestCase):
    def test_original_absent_precondition_and_new_query_key_are_distinct_at_unsigned_maximum(self):
        initial = {"key-version": {"none": None}}
        command = frame("18446744073709551615", initial["key-version"])
        query = frame("18446744073709551615", {"some": list(token(b"SV", 3))}, query=True, generation=3)
        observed = acceptance_campaign.value_roundtrip(command, initial, query,
            {"commandCount": "0"}, {"commandCount": "1"}, "18446744073709551615")
        self.assertEqual(observed["count"], "18446744073709551615")
        self.assertEqual(http.aggregate(command)["key-version"], {"none": None})

    def test_wrong_precondition_signed_integer_stale_query_or_extra_commit_cannot_qualify(self):
        initial = {"key-version": {"none": None}}
        command = frame("9223372036854775808", initial["key-version"])
        query = frame("9223372036854775808", {"some": list(token(b"SV", 3))}, query=True, generation=3)
        changed_command = frame("9223372036854775808", {"some": list(token(b"SV", 2))})
        changed_query = frame("9223372036854775808", {"none": None}, query=True)
        signed = frame("-9223372036854775808", initial["key-version"])
        for left, right, count in [(changed_command, query, "1"), (signed, query, "1"),
                                   (command, changed_query, "1"), (command, query, "2")]:
            with self.subTest(count=count), self.assertRaises(ValueError):
                acceptance_campaign.value_roundtrip(left, initial, right, {"commandCount": "0"},
                    {"commandCount": count}, "9223372036854775808")

    def test_single_value_policy_is_explicit_and_cannot_inherit_ordinary_or_diagnostic_scope(self):
        value, operations, _publications = observation()
        value["deferredHttp"] = value["deferredHttp"][:1]
        operations = operations[:1]
        publications = {acceptance_inputs.VALUE: operations[0]["publication"]}
        hosts = policies.ObservedHosts.read(value, operations, acceptance=True)
        proposed = policies.documents(hosts, publications, acceptance=True)
        self.assertEqual(len(proposed["bindings"]), 5)
        self.assertEqual(len(proposed["policies"]), 5)
        self.assertTrue(all(row["publications"] == list(publications.values())
                            for row in proposed["policies"][policies.STATE_POLICY]["rules"]))
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations)
        with self.assertRaises(ValueError):
            policies.documents(hosts, publications)
        with self.assertRaises(ValueError):
            policies.documents(hosts, publications, acceptance=True, diagnostic=True)

    def test_packaging_spends_only_remaining_original_deadline_and_requires_loaded_inputs(self):
        from tools import run_java_transaction_http_qualification as runner
        args = SimpleNamespace(value_child_acceptance_only=True, contracts_tool="contracts", signer="signer")
        with patch.object(runner.time, "monotonic", return_value=100), \
                patch.object(runner.packaging, "package_acceptance", return_value="signed") as package:
            self.assertEqual(runner.package_selected(args, "output", None, 117, acceptance_items=("original",)), "signed")
            self.assertEqual(package.call_args.kwargs["timeout"], 17)
        with self.assertRaisesRegex(ValueError, "loaded-value-child"):
            runner.package_selected(args, "output", None, 117)
