import copy
from pathlib import Path
import unittest

from tools.maintenance_example import MaintenanceError, ReadOnlySweep, canonical, observe_fixture


class BoundedMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.records = [{"id": f"record-{index:02}", "expiresAtMillis": 1000 + index} for index in range(20)]
        self.sweep = ReadOnlySweep("tests", self.records)
        self.options = dict(authenticated_tenant="tests", allowed_commands={"observe-expiry"}, trusted_now=1005)

    def test_duplicate_overlapping_and_missed_runs_do_not_mutate(self):
        before = copy.deepcopy(self.records)
        first = self.sweep.page(**self.options)
        self.assertEqual(self.sweep.page(**self.options), first)
        self.assertEqual(ReadOnlySweep("tests", self.records).page(**self.options), first)
        late = self.sweep.page(**{**self.options, "trusted_now": 3000})
        self.assertTrue(all(row["expired"] for row in late["records"]))
        self.assertEqual(self.records, before)
        self.assertEqual(first["mutations"], 0)

    def test_cancellation_preserves_observed_prefix_and_restart_cursor(self):
        checks = iter([False, False, True])
        interrupted = self.sweep.page(**self.options, cancelled=lambda: next(checks))
        self.assertEqual(interrupted["disposition"], "interrupted")
        self.assertEqual(len(interrupted["records"]), 2)
        restarted = ReadOnlySweep("tests", self.records).page(**self.options, cursor=interrupted["nextCursor"])
        self.assertEqual(restarted["records"][0]["id"], "record-02")
        self.assertFalse(interrupted["platformDurability"])

    def test_current_authority_is_checked_on_every_page_and_access(self):
        first = self.sweep.page(**self.options)
        for changes in [{"authenticated_tenant": "foreign"}, {"allowed_commands": set()}]:
            with self.assertRaisesRegex(MaintenanceError, "unauthorized"):
                self.sweep.page(**{**self.options, **changes}, cursor=first["nextCursor"])
        with self.assertRaisesRegex(MaintenanceError, "unauthorized"):
            self.sweep.access_allowed("record-00", authenticated_tenant="foreign", trusted_now=1005)

    def test_changed_or_forged_cursor_does_not_refresh_progress(self):
        first = self.sweep.page(**self.options)
        changed = ReadOnlySweep("tests", [{"id": "other", "expiresAtMillis": 1}])
        for cursor in [first["nextCursor"], "page:" + "0" * 64]:
            with self.assertRaisesRegex(MaintenanceError, "stale-or-foreign-cursor"):
                changed.page(**self.options, cursor=cursor)

    def test_expiry_is_enforced_without_any_maintenance_and_clock_restore_is_conservative(self):
        self.assertFalse(self.sweep.access_allowed("record-00", authenticated_tenant="tests", trusted_now=1000))
        self.assertTrue(self.sweep.access_allowed("record-00", authenticated_tenant="tests", trusted_now=999))
        restored = ReadOnlySweep("tests", self.records, last_trusted_time=1005)
        with self.assertRaisesRegex(MaintenanceError, "clock-regression"):
            restored.access_allowed("record-00", authenticated_tenant="tests", trusted_now=999)
        self.assertEqual(len(restored.records), 20)  # Recovery identities are not deleted by expiry.

    def test_record_page_byte_and_work_bounds_are_finite(self):
        with self.assertRaisesRegex(MaintenanceError, "record-bound"):
            ReadOnlySweep("tests", self.records * 4)
        with self.assertRaisesRegex(MaintenanceError, "page-bound"):
            self.sweep.page(**self.options, maximum_records=9)
        page = self.sweep.page(**self.options, maximum_bytes=512)
        self.assertLessEqual(len(canonical(page)), 512)
        self.assertLessEqual(len(page["records"]), 8)
        self.assertEqual(len(page["nextCursor"]), 69)

    def test_maintained_fixture_reports_its_synthetic_execution_boundary(self):
        path = Path(__file__).resolve().parents[2] / "examples/maintenance/read-only.json"
        report = observe_fixture(path, 2000)
        self.assertEqual(report["execution"], "synthetic-read-only")
        self.assertFalse(report["guestExecution"])
        self.assertFalse(report["durableSchedule"])
        self.assertEqual(report["mutations"], 0)
        self.assertEqual(report["pages"][0]["records"], [
            {"id": "example-a", "expired": True}, {"id": "example-b", "expired": True},
            {"id": "example-c", "expired": False}])
