"""Private secret fixture ownership, immutable selection and public receipts."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from tools.dev_workflow import node_fixtures, node_output, paths, secret_fixture, state
from tools.dev_workflow.common import DevError, digest, encode


class SecretFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "test-secrets"
        paths.new_directory(self.root)
        self.selected = {"references": [{"name": "dev-allowed"}, {"name": "dev-expired", "expired": True}]}

    def test_each_workspace_owns_distinct_values_and_only_public_references_are_exported(self):
        actual = secret_fixture.values(self.root, self.selected, create=True)
        self.assertEqual(actual, secret_fixture.values(self.root, self.selected))
        second = self.root.parent / "test-other"
        paths.new_directory(second)
        other = secret_fixture.values(second, self.selected, create=True)
        self.assertFalse(set(actual) & set(other))
        public = encode(secret_fixture.installation(self.root, self.selected))
        for raw in actual:
            self.assertNotIn(raw, public)
            self.assertNotIn(digest(raw).encode(), public)
        self.assertIn(b'"expiresAtUnixMillis":1', public)

    def test_selection_or_value_change_never_silently_recreates_authority(self):
        secret_fixture.values(self.root, self.selected, create=True)
        changed = copy.deepcopy(self.selected)
        changed["references"][0]["expired"] = True
        with self.assertRaisesRegex(DevError, "owner-changed"):
            secret_fixture.values(self.root, changed, create=True)
        state.atomic(self.root / "secret-fixture-private", "dev-allowed", "changed")
        with self.assertRaisesRegex(DevError, "value-changed"):
            secret_fixture.values(self.root, self.selected, create=True)

    def test_incomplete_creation_remains_failed_and_an_ordinary_workspace_is_rejected(self):
        paths.new_directory(self.root / "secret-fixture-private")
        with self.assertRaises((OSError, DevError)):
            secret_fixture.values(self.root, self.selected, create=True)
        self.assertFalse((self.root / "secret-fixture-private/dev-allowed").exists())
        with self.assertRaisesRegex(DevError, "test-workspace"):
            secret_fixture.values(self.root.parent / "ordinary", self.selected, create=True)

    def test_closed_selection_cannot_supply_values_paths_or_ambient_references(self):
        for entry in ({"name": "production"}, {"name": "dev-../escape"},
                      {"name": "dev-test", "value": "private"}, {"name": "dev-test", "environment": "HOME"},
                      {"name": "dev-test", "expired": "yes"}):
            with self.assertRaises(DevError):
                secret_fixture.validate({"references": [entry]})
        for references in ([], [{"name": "dev-test"}] * 2, [{"name": "dev-" + str(i)} for i in range(9)]):
            with self.assertRaises(DevError):
                secret_fixture.validate({"references": references})

    def test_fixture_needs_matching_actual_provider_and_correct_kind(self):
        selected = {"secrets": self.selected}
        raw = encode(selected)
        paths.write_new(self.root / "fixture.json", raw)
        case = {"fixtures": [{"id": "secrets", "kind": "real-provider", "identity": digest(raw), "configuration": "fixture.json"}]}
        actual = {"secrets": {"capability": secret_fixture.PROVIDER[0], "profile": secret_fixture.PROVIDER[1],
                              "service": secret_fixture.SERVICE, "configurationEpoch": "1"}}
        self.assertEqual(node_fixtures.initialized(self.root, [case], selected), set())
        self.assertEqual(node_fixtures.initialized(self.root, [case], selected, providers=actual), {"secrets"})
        case["fixtures"][0]["kind"] = "test-adapter"
        self.assertEqual(node_fixtures.initialized(self.root, [case], selected, providers=actual), set())

    def test_shutdown_does_not_omit_retained_secret_generations_or_invent_missing_counters(self):
        value = {"clean": False, **dict.fromkeys(node_output.PROVIDER_COUNTERS, 0),
                 "secretGenerations": 1, "secretReferences": 0}
        self.assertEqual(node_output.provider_shutdown({"report": {"providers": value}}), value)
        del value["secretReferences"]
        self.assertIsNone(node_output.provider_shutdown({"report": {"providers": value}}))


if __name__ == "__main__":
    unittest.main()
