"""Closed shared HTTP declarations preserve links and confer no authority."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator
from tools import stateful_reference_deployment as deployment
from tools.stateful_reference_project import create


class StatefulReferenceDeployment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owned = tempfile.TemporaryDirectory()
        cls.project = create(Path(cls.owned.name) / "alice", "c", draft_id="alice")
        cls.companion = (cls.project / "transaction-binding.json").read_bytes()
        cls.published = {"componentDigest": "sha256:" + "a" * 64,
            "publication": "publication:sha256:" + "b" * 64, "revision": "revision-v1:sha256:" + "c" * 64,
            "companionDigest": deployment.digest(cls.companion), "deploymentGeneration": 1}
        cls.schema = json.loads((deployment.ROOT / "schemas/trigger.schema.json").read_bytes())
        cls.validator = Draft202012Validator(cls.schema)

    @classmethod
    def tearDownClass(cls):
        cls.owned.cleanup()

    def derive(self, **changes):
        arguments = dict(entity="alice", incarnation="1", result_policy="alice-results", state_policies=["alice-state"])
        arguments.update(changes)
        return deployment.derive(self.companion, self.published, **arguments)

    def test_real_companion_produces_only_closed_exact_command_query_result_and_ssr_links(self):
        value = self.derive()
        self.assertEqual(value["namespace"], "order-drafts-alice")
        self.assertFalse(value["createsGrants"])
        self.assertFalse(value["signed"])
        self.assertFalse(value["nodeQualified"])
        self.assertEqual(len(value["triggers"]), 4)
        for trigger in value["triggers"]:
            self.validator.validate(trigger)
            self.assertEqual(trigger["spec"]["target"]["publication"], self.published["publication"])
            self.assertEqual(trigger["spec"]["configuration"]["companionDigest"], deployment.digest(self.companion))
            self.assertEqual(trigger["spec"]["configuration"]["pathMatch"], "exact")
        routes = [trigger["spec"]["configuration"] for trigger in value["triggers"]]
        self.assertEqual([(route["transactionMode"], route["method"]) for route in routes],
                         [("command", "POST"), ("query", "GET"), ("result", "GET"), ("query", "GET")])
        self.assertEqual(routes[3]["host"], "alice-read.test:19092")
        self.assertEqual(base64.b64decode(routes[0]["preconditionKey"], validate=True), b"drafts/alice/draft")
        self.assertEqual([(value["function"], value["entity"]) for value in value["stateOperations"]],
                         [("edit", "alice"), ("query", "alice")])

    def test_identity_mismatch_and_non_u64_incarnation_refuse_before_emitting_constraints(self):
        for incarnation in ("0", "01", "+1", "-1", "18446744073709551616", "1\n", 1, True):
            with self.subTest(incarnation=incarnation), self.assertRaises(ValueError):
                self.derive(incarnation=incarnation)
        with self.assertRaisesRegex(ValueError, "another draft"):
            self.derive(entity="bob")
        with self.assertRaisesRegex(ValueError, "companion"):
            published = dict(self.published, companionDigest="sha256:" + "d" * 64)
            deployment.derive(self.companion, published, entity="alice", incarnation="1",
                              result_policy="alice-results", state_policies=["alice-state"])
        self.validator.validate(self.derive(incarnation="18446744073709551615")["triggers"][0])

    def test_shared_profile_rejects_wrong_methods_profiles_links_and_extra_fields(self):
        originals = self.derive()["triggers"]
        for index, method in ((0, "GET"), (1, "POST"), (2, "HEAD")):
            value = copy.deepcopy(originals[index])
            value["spec"]["configuration"]["method"] = method
            self.assertTrue(list(self.validator.iter_errors(value)))
        for key, replacement in (("profile", "transaction-http-v2"), ("companionDigest", "sha256:short"),
                                 ("incarnation", "18446744073709551616"), ("futureAuthority", True)):
            value = copy.deepcopy(originals[0]); value["spec"]["configuration"][key] = replacement
            with self.subTest(field=key):
                self.assertTrue(list(self.validator.iter_errors(value)))
        value = copy.deepcopy(originals[0]); del value["spec"]["target"]["publication"]
        self.assertTrue(list(self.validator.iter_errors(value)))
        value = copy.deepcopy(originals[1]); value["spec"]["configuration"]["preconditionKey"] = "YQ=="
        self.assertTrue(list(self.validator.iter_errors(value)))

    def test_precondition_key_has_an_exact_1024_byte_boundary_and_canonical_bits(self):
        original = self.derive()["triggers"][0]
        for size in (1, 2, 3, 1022, 1023, 1024):
            value = copy.deepcopy(original)
            value["spec"]["configuration"]["preconditionKey"] = base64.b64encode(b"a" * size).decode()
            with self.subTest(size=size):
                self.validator.validate(value)
        for encoded in (base64.b64encode(b"a" * 1025).decode(), "YR==", "YWJ=", "", "YQ", "YQ==="):
            value = copy.deepcopy(original); value["spec"]["configuration"]["preconditionKey"] = encoded
            with self.subTest(encoded=encoded[:12]):
                self.assertTrue(list(self.validator.iter_errors(value)))


if __name__ == "__main__":
    unittest.main()
