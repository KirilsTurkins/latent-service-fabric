"""A proc read that spans exit must not become new live benchmark evidence."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from optimization_runner.processes import OwnedProcess


class CompletedSnapshotRaceTests(unittest.TestCase):
    def owner(self):
        owner = object.__new__(OwnedProcess)
        owner.child = SimpleNamespace(pid=123)
        owner.receipt = {"start_time_ticks": "42"}
        owner.after = {"start_time_ticks": "42", "rss_bytes": "1024"}
        owner.last_live = owner.after
        owner.peak_rss = 1024
        owner.last_sample_ns = 100
        owner.completed_resources = None
        return owner

    def test_periodic_read_spanning_exit_keeps_all_previous_evidence(self):
        # Depending on the point of teardown, a torn snapshot may contain
        # either zero RSS or still-resident pages. Neither is a new live sample.
        for rss in ("0", "8192"):
            with self.subTest(rss=rss):
                owner = self.owner()
                previous = owner.after
                with patch.object(owner, "exited", side_effect=[False, True]), \
                     patch("optimization_runner.processes.snapshot", return_value={
                         "start_time_ticks": "42", "rss_bytes": rss}) as probe:
                    self.assertIs(owner.sample(allow_exited=True), previous)
                probe.assert_called_once_with(123)
                self.assertIs(owner.after, previous)
                self.assertIs(owner.last_live, previous)
                self.assertEqual((owner.peak_rss, owner.last_sample_ns), (1024, 100))
                self.assertIsNone(owner.completed_resources)

    def test_required_read_spanning_exit_still_fails_without_new_evidence(self):
        owner = self.owner()
        previous = owner.after
        with patch.object(owner, "exited", side_effect=[False, True]), \
             patch("optimization_runner.processes.snapshot", return_value={
                 "start_time_ticks": "42", "rss_bytes": "8192"}):
            with self.assertRaisesRegex(RuntimeError, "exited during required live"):
                owner.sample()
        self.assertIs(owner.after, previous)
        self.assertIs(owner.last_live, previous)
        self.assertEqual((owner.peak_rss, owner.last_sample_ns), (1024, 100))

    def test_unchanged_live_identity_can_still_advance_observations(self):
        for periodic in (False, True):
            with self.subTest(periodic=periodic):
                owner = self.owner()
                current = {"start_time_ticks": "42", "rss_bytes": "8192"}
                with patch.object(owner, "exited", return_value=False), \
                     patch("optimization_runner.processes.snapshot", return_value=current), \
                     patch("optimization_runner.processes.time.monotonic_ns", return_value=200):
                    self.assertIs(owner.sample(allow_exited=periodic), current)
                self.assertIs(owner.after, current)
                self.assertIs(owner.last_live, current)
                self.assertEqual((owner.peak_rss, owner.last_sample_ns), (8192, 200))

    def test_live_identity_mismatch_is_not_tolerated(self):
        owner = self.owner()
        previous = owner.after
        with patch.object(owner, "exited", return_value=False), \
             patch("optimization_runner.processes.snapshot", return_value={
                 "start_time_ticks": "43", "rss_bytes": "8192"}):
            with self.assertRaisesRegex(ValueError, "identity changed"):
                owner.sample(allow_exited=True)
        self.assertIs(owner.after, previous)
        self.assertEqual((owner.peak_rss, owner.last_sample_ns), (1024, 100))


if __name__ == "__main__":
    unittest.main()
