"""Scheduler archive dispatch preserves the existing bounded publication gate."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import validate_phase1_archive as archive


class SchedulerArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="scheduler-archive-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.complete = {
            "schema": "latent.optimization.scheduler-aggregate.v1",
            "profile": "full", "status": "complete",
            "completed_paired_run": True, "acceptance_qualified": True,
            "full_population_completed": True,
        }
        (self.root / "suite.json").write_text("{}\n", encoding="utf-8")
        self.retain(self.complete)

    def retain(self, aggregate):
        (self.root / "aggregate.json").write_text(json.dumps(aggregate), encoding="utf-8")

    def test_scheduler_uses_original_archive_limits(self):
        self.assertEqual(archive.evidence_kind(self.root), "scheduler")
        self.assertEqual(archive.archive_bounds("scheduler"), (1024**3, 1024**3))

    def test_complete_replay_is_called_with_retained_suite(self):
        with patch.object(archive, "validate_scheduler_suite", return_value=self.complete) as replay:
            archive.verify_scheduler(self.root)
        replay.assert_called_once_with(self.root / "suite.json")

    def test_replay_change_rejects_even_a_complete_outer_aggregate(self):
        changed = dict(self.complete, logical_offers="9127")
        with patch.object(archive, "validate_scheduler_suite", return_value=changed):
            with self.assertRaisesRegex(ValueError, "differs from replayed"):
                archive.verify_scheduler(self.root)

    def test_incomplete_or_wrong_population_cannot_publish(self):
        for field, value in (("schema", "latent.optimization.catalog-aggregate.v1"),
                             ("profile", "smoke"), ("status", "failed"),
                             ("completed_paired_run", False), ("acceptance_qualified", False),
                             ("full_population_completed", False),
                             ("full_population_completed", 1)):
            with self.subTest(field=field, value=value):
                changed = dict(self.complete, **{field: value})
                self.retain(changed)
                with patch.object(archive, "validate_scheduler_suite", return_value=changed):
                    with self.assertRaisesRegex(ValueError, "qualified complete full population"):
                        archive.verify_scheduler(self.root)


if __name__ == "__main__":
    unittest.main()
