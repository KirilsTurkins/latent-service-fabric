"""Small reusable regressions; synthetic inputs here are not campaign evidence."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, WorkflowError
from tools.phase3_resource_campaign import write_receipt
from tools.phase3_resource_identity import file_identity, inventory
from tools.phase3_resource_node import configure
from tools.phase3_resource_os import Probe, network_counts, proc_stat
from tools.phase3_resource_profile import ACTIVE_COUNTERS, PROFILES, digest, integer, quiescent, summary, validate_schedule
from tools.phase3_resource_schedule import run_open_loop


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += int(seconds * 1_000_000_000)


class Pending:
    def __init__(self, clock, delay):
        self.clock = clock
        self.end = clock.now + delay
        self.owner = self
        self.closed = False
        self.finished = False

    def exited(self):
        return self.clock.now >= self.end

    def drain(self):
        pass

    def close(self):
        self.closed = self.finished = True


def finish(process):
    process.close()
    return {"category": "success"}


def quiet_sample():
    return {"inventory": {"queueDepth": 0, "cellCapacity": [{"observationAvailable": True,
                "active": 0, "quarantined": 0, "queueDepth": 0}],
                "cacheSummary": {"available": True, "preparing": 0, "preparingSourceBytes": 0,
                                 "preparingMetadataBytes": 0}},
            "capabilities": {"nodeUsage": {"unavailable": [], "counters": dict.fromkeys(ACTIVE_COUNTERS, "0")}}}


class ScheduleTests(unittest.TestCase):
    def test_overload_accounts_for_every_scheduled_arrival_without_unbounded_queue(self):
        clock = Clock()
        processes = []

        def launch(_ordinal):
            process = Pending(clock, 10_000_000)
            processes.append(process)
            return process

        rows = run_open_loop(8, 1_000_000, 1, launch, finish, lambda: None, 50_000_000, clock, clock.sleep)
        self.assertEqual([int(row["scheduledNanos"]) for row in rows], list(range(0, 8_000_000, 1_000_000)))
        self.assertEqual(sum(row["disposition"] == "completed" for row in rows), 1)
        self.assertEqual(sum(row["disposition"] == "client-shed" for row in rows), 7)
        self.assertTrue(all(process.closed for process in processes))

    def test_late_launch_does_not_reset_the_arrival_origin(self):
        clock = Clock()

        def launch(_ordinal):
            clock.now += 5_000_000
            return Pending(clock, 5_000_000)

        rows = run_open_loop(4, 1_000_000, 2, launch, finish, lambda: None, 50_000_000, clock, clock.sleep)
        self.assertEqual([int(row["scheduledNanos"]) for row in rows], [0, 1_000_000, 2_000_000, 3_000_000])
        self.assertEqual(rows[1]["startedNanos"], "5000000")
        self.assertEqual(rows[2]["disposition"], "client-shed")

    def test_deadline_closes_every_launched_process(self):
        clock = Clock()
        processes = []

        def launch(_ordinal):
            process = Pending(clock, 1_000_000_000)
            processes.append(process)
            return process

        with self.assertRaisesRegex(WorkflowError, "schedule-deadline"):
            run_open_loop(4, 1_000_000, 2, launch, finish, lambda: None, 5_000_000, clock, clock.sleep)
        self.assertEqual(len(processes), 2)
        self.assertTrue(all(process.closed for process in processes))

    def test_observation_failure_also_reaps_every_owner(self):
        clock = Clock()
        processes = []

        def launch(_ordinal):
            process = Pending(clock, 1_000_000_000)
            processes.append(process)
            return process

        def tick():
            if processes:
                raise RuntimeError("controlled observation failure")

        with self.assertRaisesRegex(RuntimeError, "controlled observation"):
            run_open_loop(4, 1_000_000, 2, launch, finish, tick, 50_000_000, clock, clock.sleep)
        self.assertTrue(all(process.closed for process in processes))

    def test_empty_fake_complete_and_omitted_arrivals_are_rejected(self):
        with self.assertRaises(WorkflowError):
            validate_schedule([], 0)
        clock = Clock()
        rows = run_open_loop(2, 1_000_000, 2, lambda _ordinal: Pending(clock, 1_000_000),
                             finish, lambda: None, 20_000_000, clock, clock.sleep)
        with self.assertRaises(WorkflowError):
            validate_schedule(rows[:1], 2)
        changed = copy.deepcopy(rows)
        changed[0]["ownerReaped"] = False
        with self.assertRaises(WorkflowError):
            validate_schedule(changed, 2)


class EvidenceTests(unittest.TestCase):
    def test_dormant_density_does_not_create_per_deployment_provider_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixtures"
            fixture.mkdir()
            (fixture / "policy.json").write_text("{}", encoding="ascii")
            for name, profile in PROFILES.items():
                directory = root / name
                directory.mkdir()
                _path, settings = configure(directory, fixture, 12345, profile)
                self.assertEqual(len(settings["providers"]["bindings"]), 2)
                self.assertTrue(all("route" not in binding for binding in settings["providers"]["bindings"]))

    def test_unobserved_counters_are_not_treated_as_zero(self):
        sample = quiet_sample()
        self.assertTrue(quiescent(sample))
        del sample["capabilities"]["nodeUsage"]["counters"]["broker_calls"]
        with self.assertRaises(WorkflowError):
            quiescent(sample)

    def test_partial_provider_and_cell_observations_are_rejected(self):
        sample = quiet_sample()
        sample["capabilities"]["nodeUsage"]["unavailable"] = ["provider-io-no-retained-pool-owner"]
        with self.assertRaises(WorkflowError):
            quiescent(sample)
        sample = quiet_sample()
        sample["inventory"]["cellCapacity"][0]["observationAvailable"] = False
        with self.assertRaises(WorkflowError):
            quiescent(sample)

    def test_retained_active_owner_is_not_quiet(self):
        for key in ACTIVE_COUNTERS:
            sample = quiet_sample()
            sample["capabilities"]["nodeUsage"]["counters"][key] = "1"
            self.assertFalse(quiescent(sample), key)

    def test_distribution_requires_nonempty_finite_observations(self):
        for values in ([], [float("nan")], [float("inf")], [-1], [True]):
            with self.assertRaises(WorkflowError):
                summary(values)
        self.assertEqual(summary([2, 1, 4, 3]), {"count": 4, "minimum": 1, "maximum": 4, "p50": 2, "p95": 4})

    def test_counters_reject_null_bool_negative_and_lossy_json_number(self):
        for value in (None, True, -1, 1.0, "-1", "01", str(2**64)):
            with self.assertRaises(WorkflowError):
                integer(value)
        self.assertEqual(integer(str(2**64 - 1)), 2**64 - 1)

    def test_immutable_receipts_bind_exact_bytes_and_refuse_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "receipt.json"
            write_receipt(output, {"actual": "small-regression-fixture"})
            self.assertEqual(output.with_suffix(".json.sha256").read_text().strip(), file_identity(output)["sha256"])
            with self.assertRaises((FileExistsError, PermissionError)):
                write_receipt(output, {"actual": "not-the-original"})
            output.chmod(0o600)

    def test_inventory_is_bounded_nonempty_and_content_addressed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.json").write_text('{"actual":"fixture"}', encoding="ascii")
            observed = inventory(root)
            self.assertEqual(len(observed["files"]), 1)
            self.assertEqual(observed["filesDigest"], digest(observed["files"]))
            with self.assertRaises(WorkflowError):
                inventory(root, maximum_bytes=1)
            with self.assertRaises(WorkflowError):
                inventory(root, maximum_files=0)


class ProcTests(unittest.TestCase):
    def test_network_namespace_rows_must_match_owned_descriptor_inodes(self):
        tables = {"tcp": ["header", "0: local remote 0A queue timer retr uid timeout 101",
                          "1: local remote 01 queue timer retr uid timeout 102",
                          "2: local remote 0A queue timer retr uid timeout 999"],
                  "udp": ["header", "3: local remote 07 queue timer retr uid timeout 103"]}
        self.assertEqual(network_counts(tables, {"101", "102", "103"}),
                         {"listeners": 1, "tcpConnections": 1, "udpSockets": 1})

    def test_stat_uses_final_parenthesis_and_preserves_start_identity(self):
        fields = ["S", "7", "8", "8"] + ["0"] * 15 + ["12345", "0", "0"]
        self.assertEqual(proc_stat("9 (contains ) parentheses) " + " ".join(fields))["startTimeTicks"], "12345")

    @unittest.skipUnless(sys.platform == "linux", "real owned /proc regression")
    def test_real_owned_process_is_measured_then_reaped_not_adopted(self):
        with tempfile.TemporaryDirectory() as temporary, owned_cancellation() as cancellation:
            executable = Path(sys.executable).resolve()
            process = Process([str(executable), "-c", "import time; time.sleep(30)"], Path(temporary),
                              dict(os.environ), cancellation)
            try:
                probe = Probe(process, file_identity(executable))
                observed = probe.sample()
                self.assertGreater(observed["metrics"]["processes"], 0)
                self.assertGreater(observed["metrics"]["threads"], 0)
                self.assertGreater(observed["metrics"]["rssBytes"], 0)
                self.assertIsNone(observed["unavailable"].get("inventedCounter"))
                self.assertIn("rendererHeapBytes", observed["unavailable"])
            finally:
                process.close()
            self.assertTrue(process.owner.finished)
            with self.assertRaises(WorkflowError):
                probe.sample()


if __name__ == "__main__":
    unittest.main()
