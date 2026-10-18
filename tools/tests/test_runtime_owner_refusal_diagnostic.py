from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import runtime_owner_refusal_diagnostic as diagnostic


LINE = b"LSF-RUNTIME-OWNER-REFUSAL-V1 tasks=1 executors=2 queued-work=3 waits=4 timers=5 results=6 native=7\n"


class RuntimeOwnerRefusalTests(unittest.TestCase):
    def test_exact_accounting_buckets_are_bounded_unqualified_observations(self):
        row = diagnostic.observe(LINE)
        self.assertEqual(row["records"], [dict(zip(diagnostic.BUCKETS, range(1, 8)))])
        self.assertTrue(row["tasksIncludesManagedIdleWorkers"])
        self.assertFalse(row["qualification"])
        maximum = LINE.replace(b"tasks=1", b"tasks=8165")
        self.assertEqual(sum(diagnostic.observe(maximum)["records"][0].values()), 8192)
        row = diagnostic.observe(LINE * 100)
        self.assertEqual(len(row["records"]), 4)
        self.assertEqual(row["invalidMarkerCount"], 96)
        self.assertTrue(row["atCaptureLimit"])

    def test_unknown_malformed_overflow_and_private_fields_are_rejected(self):
        malformed = [LINE.replace(b"waits=4", b"foreign=4"), LINE.replace(b"waits=4", b"waits=8193"),
            LINE.replace(b"tasks=1", b"tasks=8192"), LINE.replace(b"tasks=1", b"tasks=01"),
            LINE.replace(b"tasks=1", b"tasks=-1"), LINE.replace(b"tasks=1", b"tasks=true"),
            LINE.rstrip() + b" PRIVATE-/token/path\n", LINE.replace(b"tasks=1", b"tasks=\xff"),
            LINE.replace(b"timers=5", b"timers=5\x00"),
            diagnostic.PREFIX + b" tasks=0 executors=0 queued-work=0 waits=0 timers=0 results=0 native=0\n"]
        row = diagnostic.observe(b"".join(malformed))
        self.assertEqual(row["records"], [])
        self.assertEqual(row["invalidMarkerCount"], len(malformed))
        self.assertNotIn("PRIVATE", json.dumps(row))
        self.assertEqual(diagnostic.observe("not bytes")["status"], "invalid-source")
        self.assertEqual(diagnostic.observe(b"x" * (diagnostic.MAX_STDERR + 1))["status"], "invalid-source")

    def test_only_owned_reaped_node_stderr_can_supply_records(self):
        structured = json.dumps({"message": LINE.decode(), "private": "sentinel"}).encode() + b"\n"
        node = SimpleNamespace(owner=SimpleNamespace(finished=True), buffers=[LINE, structured])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertEqual(diagnostic.retain(node, directory)["records"], [])
            self.assertNotIn("sentinel", (directory / "runtime-owner-refusals.json").read_text())
            node.buffers[1] += LINE
            self.assertEqual(diagnostic.retain(node, directory)["status"], "retention-unavailable")
            self.assertEqual(json.loads((directory / "runtime-owner-refusals.json").read_text())["records"], [])
            fresh = directory / "fresh"; fresh.mkdir()
            self.assertEqual(len(diagnostic.retain(node, fresh)["records"]), 1)
            node.owner.finished = False
            unreaped = directory / "unreaped"; unreaped.mkdir()
            row = diagnostic.retain(node, unreaped)
            self.assertEqual(row["status"], "node-not-reaped")
            self.assertEqual(row["records"], [])

    def test_failed_retention_preserves_original_failure_identity(self):
        original = RuntimeError("original-refusal")
        node = SimpleNamespace(owner=SimpleNamespace(finished=True), buffers=[b"", LINE])
        with mock.patch.object(diagnostic, "write_json", side_effect=OSError("PRIVATE-/secret")):
            with self.assertRaises(RuntimeError) as caught:
                try:
                    raise original
                finally:
                    row = diagnostic.retain(node, Path("unused"))
        self.assertIs(caught.exception, original)
        self.assertEqual(row["status"], "retention-unavailable")
        self.assertNotIn("PRIVATE", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
