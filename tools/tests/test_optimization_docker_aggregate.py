"""Arithmetic and export boundaries only; these are not recorded or qualifying runs."""
import copy
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.optimization_docker import aggregate, model
from tools.optimization_evidence import attempts
from tools.optimization_evidence.common import EvidenceError, canonical


def pair_rows(before, after):
    rows = []
    for pair, (native, lsf) in enumerate(zip(before, after)):
        for arm, value in (("native", native), ("lsf", lsf)):
            rows.append({"pair": pair, "arm": arm, "group": int((arm == "lsf") == (pair % 2 == 0)),
                         "density": 1, "kind": "measured", "metrics": {"cost": value}})
    return rows


def point_owner(identifier, child_rss, wrapper_rss, memory, cpu):
    def process(rss):
        return {"rss_bytes": rss, "threads": "2", "fd_count": "5", "listener_count": "1",
                "rss_unavailable_reason": "status-field-unavailable" if rss is None else None,
                "threads_unavailable_reason": None, "fd_unavailable_reason": None,
                "listeners_unavailable_reason": None}

    cgroup = {key: "0" for key in aggregate.CGROUP_METRICS}
    cgroup.update({"memory.current": memory, "memory.peak": memory, "pids.current": "2",
                   "cpu_stat": {key: cpu for key in aggregate.CPU_METRICS},
                   "unavailable_reasons": {key: None for key in (*aggregate.CGROUP_METRICS, "cpu.stat")}})
    return {"resources": {"container_id": f"{identifier:064x}", "snapshots": [{"snapshot_index": 1,
                           "child": process(child_rss), "wrapper": process(wrapper_rss), "cgroup": cgroup}]}}


class DockerAggregateTests(unittest.TestCase):
    def test_pairs_are_differenced_before_medians_and_keep_order_strata(self):
        rows = pair_rows(["0", "100", "101"], ["50", "51", "200"])
        result, = aggregate.comparisons(rows, ("density", "kind"), {"cost": "ns"})
        self.assertEqual(result["native"]["median"], "100")
        self.assertEqual(result["lsf"]["median"], "51")
        self.assertEqual(result["paired_difference"]["median"], "50")
        self.assertEqual(result["paired_difference"]["minimum"], "-49")
        self.assertEqual(result["paired_difference"]["maximum"], "99")
        self.assertEqual((result["lower"], result["equal"], result["higher"]), (1, 0, 2))
        self.assertEqual(len(result["pairs"]), 3)
        self.assertIsNone(result["pairs"][0]["percent_of_native"])
        self.assertEqual(result["order_strata"]["lsf"]["paired_difference"]["median"], "-49")
        self.assertEqual(result["order_strata"]["native"]["pair_count"], 2)

    def test_missing_pair_metric_stays_unavailable_and_zero_stays_zero(self):
        rows = pair_rows(["4", None, "0"], ["4", "7", None])
        result, = aggregate.comparisons(rows, ("density", "kind"), {"cost": "bytes"})
        self.assertEqual((result["available_pairs"], result["unavailable_pairs"]), (1, 2))
        self.assertEqual(result["paired_difference"]["median"], "0")
        self.assertEqual(result["equal"], 1)
        self.assertIsNone(result["pairs"][1]["lsf_minus_native"])
        self.assertEqual(result["pairs"][2]["native"], "0")

    def test_duplicate_or_unmatched_arms_are_rejected(self):
        rows = pair_rows(["1"], ["2"])
        with self.assertRaises(EvidenceError):
            aggregate.comparisons(rows + [rows[0]], ("density",), {"cost": "ns"})
        with self.assertRaises(EvidenceError):
            aggregate.comparisons(rows[:1], ("density",), {"cost": "ns"})

    def test_first_warmup_and_measured_are_separate_populations(self):
        rows = pair_rows(["1"], ["2"])
        for kind, value in (("first", "100"), ("warmup", "10")):
            for row in copy.deepcopy(rows[:2]):
                row["kind"], row["metrics"]["cost"] = kind, value
                rows.append(row)
        result = aggregate.comparisons(rows, ("density", "kind"), {"cost": "ns"})
        self.assertEqual({row["kind"]: row["paired_difference"]["median"] for row in result},
                         {"first": "0", "warmup": "0", "measured": "1"})

    def test_children_wrappers_and_each_leaf_cgroup_are_distinct_sums(self):
        owners = [point_owner(1, "17", "5", "100", "3"), point_owner(2, "23", "7", "200", "5")]
        result, units = aggregate._resource_point(owners, 0)
        self.assertEqual(result["metrics"]["child.rss_bytes"], "40")
        self.assertEqual(result["metrics"]["wrapper.rss_bytes"], "12")
        self.assertEqual(result["metrics"]["cgroup.memory_current_bytes"], "300")
        self.assertEqual(result["metrics"]["cgroup.cpu.usage_usec"], "8")
        self.assertEqual(units["cgroup.cpu.usage_usec"], "us")
        self.assertEqual(len(result["leaf_cgroup_container_ids"]), 2)
        with self.assertRaises(EvidenceError):
            aggregate._resource_point([owners[0], owners[0]], 0)

    def test_one_missing_component_does_not_become_partial_cohort_total(self):
        owners = [point_owner(1, "17", "5", "100", "3"), point_owner(2, None, "7", "200", "5")]
        owners[1]["resources"]["snapshots"][0]["cgroup"]["cpu_stat"] = None
        owners[1]["resources"]["snapshots"][0]["cgroup"]["unavailable_reasons"]["cpu.stat"] = "read-failed"
        result, _ = aggregate._resource_point(owners, 0)
        self.assertIsNone(result["metrics"]["child.rss_bytes"])
        self.assertIsNone(result["metrics"]["cgroup.cpu.usage_usec"])
        self.assertEqual(result["metrics"]["wrapper.rss_bytes"], "12")
        self.assertEqual(result["unavailable_components"]["child.rss_bytes"][0]["container_id"], f"{2:064x}")
        self.assertEqual(result["unavailable_components"]["cgroup.cpu.usage_usec"][0]["reason"], "read-failed")

    def test_phase_throughput_uses_each_actual_denominator(self):
        samples = [{"scheduled_nanos": "10", "dispatch_nanos": "10", "completed_nanos": "30", "latency_nanos": "20"},
                   {"scheduled_nanos": "40", "dispatch_nanos": "40", "completed_nanos": "70", "latency_nanos": "30"}]
        for sample in samples:
            sample.update(outcome="success", semantic_match=True, rpc_received=True, dispatch_lag_nanos="0", overshoot_nanos="0")
        phase = {"ordinal": 0, "name": "first", "kind": "first", "function": "echo", "concurrency": 1}
        rows, _ = aggregate.phase_rows([{"evidence": {"pair": 0, "phases": [{"group": 0, "arm": "native", "density": 1,
                                          "phase": phase, "metrics": attempts.metrics(samples), "phase_elapsed_nanos": "100"}]}}])
        row, = rows
        self.assertEqual(row["metrics"]["successes_per_second"], "33333333.333333")
        self.assertEqual(row["metrics"]["phase_span_successes_per_second"], "20000000")
        self.assertEqual(row["metrics"]["successful_response_latency_nanos.median"], "25")
        self.assertEqual(row["counts"]["outcomes"], {"success": "2"})
        self.assertEqual(row["phase_kind"], "first")

    def test_lifecycle_uses_parent_clock_and_keeps_sequential_provisioning(self):
        parents = []
        for identifier, start, ready in ((1, "100", "150"), (2, "200", "300")):
            parents.append({"parent": {"container_id": f"{identifier:064x}", "owner_ref": f"owner-{identifier}",
                            "app_process_id": 2, "start": {"started_nanos": start, "finished_nanos": str(int(start) + 10)},
                            "event_observations": [{"sequence": 1, "observed_nanos": ready}]}})
        command = {"command": "phase", "group": 0, "phase": 0}
        client = {"evidence": {"pair": 0, "first_responses": [{"group": 0, "owner_ref": "owner-1",
                               "response_session_nanos": "99999999"}]},
                  "parent": {"commands": [{"line": (canonical(command) + b"\n").decode(), "sent_nanos": "400"}],
                             "acknowledgements": [{"ack": {"event": "first-response", "command_ordinal": 0}, "received_nanos": "500"}]}}
        owners, cohorts = aggregate.lifecycle_rows([{"pair": 0, "group": 0, "arm": "native", "density": 2,
                                                    "owners": parents}], [client])
        self.assertEqual(owners[0]["start_to_ready_observed_upper_nanos"], "50")
        self.assertEqual(cohorts[0]["metrics"]["cohort_first_start_to_last_ready_observed_upper_nanos"], "200")
        self.assertEqual(cohorts[0]["metrics"]["first_target_start_to_first_response_observed_upper_nanos"], "400")
        self.assertEqual(cohorts[0]["metrics"]["first_phase_command_to_first_response_ack_nanos"], "100")

    def test_stats_missing_and_boolean_values_do_not_become_cpu_zeroes(self):
        self.assertIsNone(aggregate._stats_number({}, "cpu_stats", "cpu_usage", "total_usage"))
        self.assertEqual(aggregate._stats_number({"usage": 0}, "usage"), "0")
        with self.assertRaises(EvidenceError):
            aggregate._stats_number({"usage": False}, "usage")

    def test_csv_preserves_large_decimal_strings_nulls_and_nested_outcomes(self):
        data = aggregate._csv_bytes([{"pair": 0, "metrics": {"nanos": "18446744073709551615", "rss": None},
                                      "outcomes": {"success": "2"}}])
        row, = csv.DictReader(io.StringIO(data.decode()))
        self.assertEqual(row["metric.nanos"], "18446744073709551615")
        self.assertEqual(row["metric.rss"], "null")
        self.assertEqual(row["outcomes"], '{"success":"2"}')

    def test_unvalidated_input_rejected_before_publication(self):
        with self.assertRaises(EvidenceError):
            aggregate.aggregate({"status": "failed"})

    def test_writer_never_overwrites_an_existing_directory(self):
        tables = ("phase_rows", "phase_comparisons", "resource_points", "resource_comparisons", "idle_windows",
                  "idle_window_comparisons", "lifecycle_owners", "lifecycle_cohorts", "lifecycle_comparisons",
                  "client_resource_points", "client_intervals", "client_cpu_comparisons")
        # Mock only the writer's input boundary, without fabricating a replayable graph.
        document = {key: [] for key in tables}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / "original"
            marker.write_bytes(b"retain")
            with patch.object(aggregate, "aggregate", return_value=document):
                with self.assertRaises(FileExistsError):
                    aggregate.write({}, directory)
            self.assertEqual(list(directory.iterdir()), [marker])
            self.assertEqual(marker.read_bytes(), b"retain")


if __name__ == "__main__":
    unittest.main()
