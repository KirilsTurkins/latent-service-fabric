"""Aggregation arithmetic only, without fabricated qualifying campaign evidence."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.optimization_evidence import attempts
from tools.optimization_evidence.common import EvidenceError, canonical
from tools.optimization_kubernetes import aggregate, model


def population(*, start=100, elapsed=100):
    return attempts.counts([{"scheduled_nanos": str(start), "dispatch_nanos": str(start),
        "completed_nanos": str(start + elapsed), "rpc_received": True,
        "outcome": "success", "semantic_match": True} for _ in range(4)])


def rows(values, *, kind="measured"):
    return [{"pair": pair, "arm": "native", "group": pair % 2, "density": 1,
             "phase_kind": kind, "counts": population(), "metrics": {"cost": value}}
            for pair, value in enumerate(values)]


def contrast(before, after):
    return aggregate.platform_comparisons(after, before, ("arm", "density", "phase_kind"),
                                          {"cost": "ns"}, family="phase")


class KubernetesAggregateTests(unittest.TestCase):
    def test_platform_population_preserves_independent_clocks_and_throughput(self):
        before, after = rows(["40000000"]), rows(["20000000"])
        after[0]["counts"] = population(start=500, elapsed=200)
        for key in ("first_scheduled_nanos", "last_completed_nanos", "elapsed_nanos"):
            self.assertNotEqual(before[0]["counts"][key], after[0]["counts"][key])
        self.assertNotEqual(before[0]["counts"]["throughput"]["elapsed_nanos"],
                            after[0]["counts"]["throughput"]["elapsed_nanos"])
        for row in before + after:
            row["metrics"] = {"successes_per_second": row["metrics"]["cost"]}
        original = copy.deepcopy((before, after))
        result, = aggregate.platform_comparisons(after, before, ("arm", "density", "phase_kind"),
                                                 {"successes_per_second": "responses/s"}, family="phase")
        self.assertEqual((before, after), original)
        self.assertEqual(result["pairs"][0]["docker"], "40000000")
        self.assertEqual(result["pairs"][0]["kubernetes"], "20000000")
        self.assertEqual(result["pairs"][0]["kubernetes_minus_docker"], "-20000000")

    def test_platform_population_rejects_each_changed_outcome_or_numerator(self):
        before, after = rows(["1"]), rows(["2"])
        paths = [(name,) for name in ("attempts", "dispatched", "undispatched", "received", "successful",
                                      "semantic_mismatches", "outcomes")]
        paths += [("throughput", name) for name in ("completed_attempts", "successful_responses")]
        for path in paths:
            changed = copy.deepcopy(after)
            count = changed[0]["counts"]
            for name in path[:-1]:
                count = count[name]
            count[path[-1]] = {"success": "3", "invalid-response": "1"} if path == ("outcomes",) else "9"
            with self.subTest(path=path), self.assertRaisesRegex(EvidenceError, "platform-outcome-population"):
                contrast(before, changed)

    def test_requested_and_effective_cpu_caps_remain_distinct(self):
        def owner(requested, effective):
            limits = {"requested_cpu": {"quota": str(requested), "period": "100000"},
                      "effective_cpu": {"quota": str(effective), "period": "100000"},
                      "effective_cpu_matches_requested": requested == effective}
            return {"resources": {"snapshots": [
                {"provider": {"cgroup": copy.deepcopy(limits)}} for _ in range(6)]}}
        groups = [{"pair": 0, "group": 4, "arm": "lsf", "density": 32,
                   "owners": [owner(400000, 400000)]},
                  {"pair": 0, "group": 5, "arm": "native", "density": 32,
                   "owners": [owner(12500, 13000) for _ in range(32)]}]
        unchanged = copy.deepcopy(groups)
        lsf, native = aggregate.cpu_limit_cohorts(groups)
        self.assertEqual(groups, unchanged)
        self.assertTrue(lsf["effective_cpu_matches_requested"])
        self.assertFalse(native["effective_cpu_matches_requested"])
        self.assertEqual(native["requested_millicpus"], "4000")
        self.assertEqual(native["effective_millicpus"], "4160")
        self.assertEqual(native["effective_minus_requested_millicpus"], "160")
        self.assertEqual(native["percent_above_requested"], "4")
        self.assertEqual(native["scope"], "sum-of-owner-effective-caps-not-cpu-usage")
        limits = groups[1]["owners"][0]["resources"]["snapshots"][5]["provider"]["cgroup"]
        limits["effective_cpu"]["quota"] = "14000"
        with self.assertRaisesRegex(EvidenceError, "cpu-limit-changed"):
            aggregate.cpu_limit_cohorts(groups)

    def test_seven_pairs_are_differenced_before_summaries(self):
        before = rows(["0", "0", "100", "100", "100", "101", "101"])
        after = rows(["50", "50", "51", "51", "51", "200", "200"])
        original = copy.deepcopy((before, after))
        result, = contrast(before, after)
        self.assertEqual((before, after), original)
        self.assertEqual(result["pair_count"], 7)
        self.assertEqual(result["docker"]["median"], "100")
        self.assertEqual(result["kubernetes"]["median"], "51")
        self.assertEqual(result["paired_difference"]["median"], "50")
        self.assertEqual(result["paired_difference"]["minimum"], "-49")
        self.assertEqual(result["paired_difference"]["maximum"], "99")
        self.assertEqual((result["lower"], result["equal"], result["higher"]), (3, 0, 4))
        self.assertIsNone(result["pairs"][0]["percent_of_docker"])
        self.assertEqual([row["pair"] for row in result["pairs"]], list(range(7)))

    def test_null_pairs_and_observed_zero_remain_distinct(self):
        result, = contrast(rows(["4", None, "0"]), rows(["4", "7", None]))
        self.assertEqual((result["available_pairs"], result["unavailable_pairs"]), (1, 2))
        self.assertEqual(result["paired_difference"]["median"], "0")
        self.assertEqual(result["pairs"][2]["docker"], "0")
        self.assertIsNone(result["pairs"][2]["kubernetes_minus_docker"])
        empty, = contrast(rows([None]), rows(["0"]))
        self.assertIsNone(empty["paired_difference"])
        self.assertEqual(empty["unavailable_pairs"], 1)

    def test_cross_campaign_rows_require_exact_population_order_and_unique_pair(self):
        before, after = rows(["1", "2"]), rows(["3", "4"])
        mutations = [after[:1], after + [after[0]], copy.deepcopy(after), copy.deepcopy(after)]
        mutations[2][0]["group"] = 1
        mutations[3][0]["counts"]["attempts"] = "8"
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(EvidenceError):
                contrast(before, changed)
        changed = copy.deepcopy(after)
        changed[0]["pair"] = False
        with self.assertRaises(EvidenceError):
            contrast(before, changed)

    def test_first_warmup_and_measured_are_not_pooled(self):
        before = rows(["1"]) + rows(["10"], kind="warmup") + rows(["100"], kind="first")
        after = rows(["3"]) + rows(["15"], kind="warmup") + rows(["109"], kind="first")
        result = contrast(before, after)
        self.assertEqual({row["phase_kind"]: row["paired_difference"]["median"] for row in result},
                         {"first": "9", "warmup": "5", "measured": "2"})

    def test_lifecycle_uses_only_parent_bounds_and_preserves_pod_boundary(self):
        owners = [{"parent": {"owner_ref": "owner-" + str(index), "container_id": str(index), "app_process_id": 2,
                    "pod_ready": {"metadata": {"uid": "pod-" + str(index)}},
                    "event_observations": [{"sequence": 1, "observed_nanos": str(250 + index * 2)}]},
                   "lifecycle": {"create_started_nanos": str(100 + index * 10),
                                 "create_finished_nanos": str(102 + index * 10)}} for index in range(8)]
        group = {"pair": 0, "group": 0, "arm": "native", "density": 8, "owners": owners,
                 "graph_ready_nanos": "300", "proxy_ready_nanos": "325"}
        command = {"command": "phase", "group": 0, "phase": 0}
        client = {"evidence": {"pair": 0, "first_responses": [{"group": 0, "owner_ref": "owner-0",
                    "response_session_nanos": "999999999999"}]}, "parent": {
                "commands": [{"line": canonical(command).decode() + "\n", "sent_nanos": "400"}],
                "acknowledgements": [{"ack": {"event": "first-response", "command_ordinal": 0}, "received_nanos": "500"}]}}
        actual_owners, cohorts = aggregate.lifecycle_rows([group], [client])
        self.assertEqual(actual_owners[0]["create_to_ready_observed_upper_nanos"], "150")
        self.assertEqual(cohorts[0]["metrics"]["cohort_first_request_to_first_response_observed_upper_nanos"], "400")
        self.assertEqual(cohorts[0]["metrics"]["first_phase_command_to_first_response_ack_nanos"], "100")
        self.assertEqual(cohorts[0]["start_boundary"], "parent-begin-Pod-create-API")
        self.assertEqual(cohorts[0]["metrics"]["cohort_first_request_to_service_graph_ready_nanos"], "200")
        self.assertEqual(cohorts[0]["metrics"]["cohort_first_request_to_service_forwarding_ready_nanos"], "225")
        for invalid in ("299", "401"):
            group["proxy_ready_nanos"] = invalid
            with self.assertRaises(EvidenceError):
                aggregate.lifecycle_rows([group], [client])
        group["proxy_ready_nanos"] = "325"
        owners[0]["lifecycle"]["create_finished_nanos"] = "900"
        with self.assertRaises(EvidenceError):
            aggregate.lifecycle_rows([group], [client])

    def test_client_keeps_distinct_cri_timestamps_and_working_set(self):
        resources = []
        for index, stage in enumerate(["ready"] + [f"group-{group}-{stage}" for group in range(6)
                                                    for stage in ("ready", "served", "final")]):
            resources.append({"stage": stage, "observed_nanos": str(100 + index), "unavailable_reason": None,
                "derived_stats": {"container_id": "a" * 64, "cpu_usage_nanos": str(index * 10),
                    "memory_working_set_bytes": "500", "cpu_timestamp_nanos": "9999999",
                    "memory_timestamp_nanos": "8888888"}})
        client = {"evidence": {"profile": "smoke", "pair": 0}, "resources": resources}
        points, intervals = aggregate.client_rows([client])
        self.assertEqual(points[0]["cpu_timestamp_nanos"], "9999999")
        self.assertEqual(points[0]["memory_timestamp_nanos"], "8888888")
        self.assertEqual(intervals[0]["parent_observation_elapsed_nanos"], "1")
        self.assertEqual(intervals[0]["metrics"], {"cpu_total_nanos": "10"})
        self.assertNotIn("memory_usage_bytes", points[0]["metrics"])
        resources[2]["derived_stats"]["cpu_usage_nanos"] = None
        resources[2]["unavailable_reason"] = "actual-field-absent"
        _, unavailable = aggregate.client_rows([client])
        self.assertIsNone(unavailable[0]["metrics"]["cpu_total_nanos"])
        client["parent"] = {"final": {"observation": {"container_id": "a" * 64}}}
        resources.append({"stage": "final", "observed_nanos": "200", "derived_stats": None,
                          "unavailable_reason": "container-exited-cgroup-stats-unavailable"})
        points, _ = aggregate.client_rows([client])
        self.assertIsNone(points[-1]["metrics"]["memory_working_set_bytes"])
        self.assertEqual(points[-1]["container_id"], "a" * 64)

    def test_nodes_are_separate_nonadditive_observations(self):
        background = []
        for stage, counter in (("before", 10), ("after", 15)):
            background.append({"stage": stage, "observations": [
                {"role": role, "container_id": role, "observed_nanos": str(counter),
                 "stats": {"cpu_stats": {"cpu_usage": {"total_usage": counter * factor}},
                           "memory_stats": {"usage": factor * 100}}}
                for role, factor in (("worker", 2), ("control-plane", 3))]})
        points, intervals = aggregate.node_rows(background)
        self.assertEqual(len(points), 4)
        self.assertEqual({row["role"]: row["metrics"]["cpu_total_nanos"] for row in intervals},
                         {"worker": "10", "control-plane": "15"})
        self.assertTrue(all(set(row["metrics"]) == {"cpu_total_nanos", "memory_usage_bytes"} for row in points))
        background[1]["observations"][0]["container_id"] = "replaced"
        with self.assertRaises(EvidenceError):
            aggregate.node_rows(background)

    def test_node_cpu_is_a_uint64_counter_not_a_32_bit_duration(self):
        self.assertEqual(aggregate._node_counter({"usage": 2**64 - 1}, "usage"), str(2**64 - 1))
        self.assertIsNone(aggregate._node_counter({}, "usage"))
        for value in (True, False, -1, 2**64, "12"):
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                aggregate._node_counter({"usage": value}, "usage")

    def test_writer_cannot_overwrite_existing_directory_or_evidence(self):
        document = {name: [] for name in aggregate.TABLES}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "original").write_bytes(b"unchanged")
            with patch.object(aggregate.docker, "aggregate", return_value={}), \
                    patch.object(aggregate, "_aggregate", return_value=document):
                with self.assertRaises(FileExistsError):
                    aggregate.write({"status": "passed"}, {}, root)
            self.assertEqual([path.name for path in root.iterdir()], ["original"])
            self.assertEqual((root / "original").read_bytes(), b"unchanged")

    def test_unvalidated_input_is_rejected_before_original_replay(self):
        with patch.object(aggregate.docker, "aggregate") as original:
            with self.assertRaises(EvidenceError):
                aggregate.aggregate({"status": "failed"}, {})
            original.assert_not_called()


if __name__ == "__main__":
    unittest.main()
