"""Native-store audit evidence stays distinct from resident prepared-image reuse."""
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

    def test_resident_image_can_have_no_pre_restart_native_store_hits(self):
        record = {"packageDigest": "package", "componentDigest": "component"}
        client = self.client(0)
        self.assertEqual(native_cache_audit(client, record, "cache-hit", allow_empty=True), [])
        self.assertEqual(client.call.call_count, 1)
        found = native_cache_audit(self.client(1), record, "cache-hit")
        self.assertEqual(found[0]["sequence"], "1")

    def test_required_observation_and_original_overflow_limit_stay_fail_closed(self):
        for count, options in ((33, {}), (0, {}), (33, {"allow_empty": True})):
            with self.subTest(count=count), self.assertRaises(WorkflowError):
                native_cache_audit(self.client(count), {"packageDigest": "package", "componentDigest": "component"}, "cache-hit", **options)

    def test_empty_baseline_does_not_waive_component_identity(self):
        with self.assertRaisesRegex(WorkflowError, "source-identity"):
            native_cache_audit(self.client(1), {"packageDigest": "package", "componentDigest": "wrong"}, "cache-hit", allow_empty=True)
