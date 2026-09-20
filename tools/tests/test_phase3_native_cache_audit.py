"""Bounded pagination for the longer browser/canary workflow, without losing audit identity."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from tools.phase2_operator_process import WorkflowError
from tools.phase3_web_qualification import native_cache_audit

class NativeCacheAuditTests(unittest.TestCase):
    def client(self, count):
        rows = [{"sequence": str(n + 1), "data": {"observation": {
            "cacheKind": "CACHE_KIND_NATIVE", "kind": "CACHE_HIT",
            "identities": {"packageDigest": "package", "componentDigest": "component"}}}} for n in range(count)]
        pages = [{"data": {"records": rows[n:n+32], "page": {"nextPageToken": str(n+32) if n+32 < count else None}}} for n in range(0, max(1, count), 32)]
        return SimpleNamespace(call=Mock(side_effect=pages))

    def test_longer_reference_run_retains_all_current_package_hits(self):
        client = self.client(40)
        found = native_cache_audit(client, {"packageDigest": "package", "componentDigest": "component"}, "cache-hit", maximum_matches=128)
        self.assertEqual(len(found), 40)
        self.assertEqual(found[-1]["sequence"], "40")
        self.assertEqual(client.call.call_count, 2)

    def test_default_bound_missing_and_explicit_overflow_remain_fail_closed(self):
        for count, options in ((33, {}), (0, {}), (129, {"maximum_matches": 128})):
            with self.subTest(count=count), self.assertRaises(WorkflowError):
                native_cache_audit(self.client(count), {"packageDigest": "package", "componentDigest": "component"}, "cache-hit", **options)

    def test_match_bound_and_component_identity_are_not_relaxed(self):
        for bound in (0, 513, True):
            with self.subTest(bound=bound), self.assertRaises(WorkflowError):
                native_cache_audit(self.client(1), {}, "cache-hit", maximum_matches=bound)
        with self.assertRaisesRegex(WorkflowError, "source-identity"):
            native_cache_audit(self.client(1), {"packageDigest": "package", "componentDigest": "wrong"}, "cache-hit", maximum_matches=128)
