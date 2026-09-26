"""Production blob namespace authority and truthful resource observations."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tools.dev_workflow import blob_fixture, node_fixtures, node_output, node_test_profile, paths, scenarios
from tools.dev_workflow.common import DevError, digest, encode


class BlobFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "test-blob"
        paths.new_directory(self.root)
        self.selected = {"blob": {"namespace": "dev-test"}}
        raw = encode(self.selected)
        paths.write_new(self.root / "fixture.json", raw)
        self.fixture = {"id": "blob", "kind": "real-provider", "identity": digest(raw), "configuration": "fixture.json"}
        self.providers = {"blob": {"capability": blob_fixture.PROVIDER[0], "profile": blob_fixture.PROVIDER[1],
                                  "service": blob_fixture.SERVICE, "configurationEpoch": "1"}}

    def test_only_explicit_disposable_namespace_is_accepted(self):
        self.assertEqual(node_fixtures.validate(self.selected), self.selected)
        for value in ({"namespace": "production"}, {"namespace": "dev-"}, {"namespace": "dev-../other"},
                      {"namespace": "dev-" + "a" * 33}, {"namespace": "dev-test", "path": "/host/secrets"}):
            with self.assertRaises(DevError):
                blob_fixture.validate(value)

    def test_fixture_requires_actual_matching_provider_and_reports_real_kind(self):
        cases = [{"fixtures": [self.fixture]}]
        self.assertEqual(node_fixtures.initialized(self.root, cases, self.selected), set())
        self.assertEqual(node_fixtures.initialized(self.root, cases, self.selected, providers=self.providers), {"blob"})
        for field, value in (("service", "someone-else"), ("profile", "fake"), ("configurationEpoch", "2")):
            changed = copy.deepcopy(self.providers)
            changed["blob"][field] = value
            self.assertEqual(node_fixtures.initialized(self.root, cases, self.selected, providers=changed), set())
        self.assertEqual(node_fixtures.initialized(self.root, cases, {"blob": {"namespace": "dev-other"}},
                                                  providers=self.providers), set())
        for kind in ("test-adapter", "controlled-peer"):
            self.fixture["kind"] = kind
            self.assertEqual(node_fixtures.initialized(self.root, cases, self.selected, providers=self.providers), set())

    def test_blob_configuration_does_not_collide_with_http_or_grant_authority(self):
        fixtures = {**self.selected, "http": {"port": 45001, "exchanges": [{"method": "GET", "path": "/fixture",
            "requestBody": "", "status": 200, "responseBody": ""}]}}
        original = {"securityProfile": "local-experimental-v1", "audit": {"mode": "durable"}}
        descriptor = {"language": "rust", "tenant": "examples", "service": "greeting"}
        configured, _ = node_test_profile.configuration(original, descriptor, fixtures, root=self.root)
        self.assertEqual(configured["providers"]["blob"]["namespace"], "dev-test")
        self.assertNotEqual(configured["providers"]["http"]["identity"]["service"],
                            configured["providers"]["blob"]["identity"]["service"])
        self.assertNotIn("providers", original)
        self.assertNotIn("policies", configured)

    def test_required_blob_case_cannot_run_in_portable_host(self):
        paths.write_new(self.root / "input.json", b"[]")
        document = {"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [{"id": "blob", "service": "greeting",
            "contract": "examples:greeting/api@1.0.0", "function": "run", "input": "input.json",
            "mediaType": "application/json", "timeoutMillis": 1000, "required": True,
            "requires": ["immutable-blob-fixture"], "fixtures": [self.fixture], "expect": {"category": "success"}}]}
        invoke = Mock()
        report = scenarios.run(document, self.root, "portable", [], invoke, {}, supported=scenarios.PORTABLE,
                               initialized_fixtures={"blob"})
        self.assertFalse(report["passed"])
        invoke.assert_not_called()


class ProviderShutdown(unittest.TestCase):
    def test_preserves_only_closed_public_resource_counters_and_rejects_malformed_numbers(self):
        providers = {"clean": True, **dict.fromkeys(node_output.PROVIDER_COUNTERS, 0), "secret": "private-canary"}
        record = {"report": {"providers": providers, "other": "private-canary"}}
        exported = node_output.provider_shutdown(record)
        self.assertNotIn(b"private-canary", encode(exported))
        self.assertEqual(exported["blobStages"], 0)
        for value in (True, "0", -1, 18446744073709551616, None):
            providers["blobStages"] = value
            self.assertIsNone(node_output.provider_shutdown(record))

    def test_nonzero_counters_are_preserved_and_absent_report_is_not_zero(self):
        providers = {"clean": False, **dict.fromkeys(node_output.PROVIDER_COUNTERS, 0), "blobHandles": 3}
        self.assertEqual(node_output.provider_shutdown({"report": {"providers": providers}}), providers)
        for record in ({}, {"report": None}, {"report": {"providers": {"clean": True}}}):
            self.assertIsNone(node_output.provider_shutdown(record))


if __name__ == "__main__":
    unittest.main()
