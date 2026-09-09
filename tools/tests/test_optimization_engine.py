"""Fixed population and semantic boundary checks; no guest execution."""
import copy
import json
from pathlib import Path
import unittest

from tools.optimization_backend_revision.engine import aggregate, calls, model, resources, schedule
from tools.optimization_evidence.common import EvidenceError, sha256
from tools.optimization_evidence.workload import framed
from tools.optimization_revision_runner import engine


class EngineModelTests(unittest.TestCase):
    def test_exact_rotation_and_shared_control_population(self):
        symbols = {("control", "D0"): "O", ("candidate", "D0"): "D0", ("candidate", "P0"): "P0",
                   ("candidate", "D1"): "D1", ("candidate", "P1"): "P1"}
        expected = ("O D0 P0 D1 P1", "O P1 D1 P0 D0", "P0 D1 P1 O D0", "P0 D0 O P1 D1",
                    "P1 O D0 P0 D1", "P1 D1 P0 D0 O", "D0 P0 D1 P1 O")
        rows = model.population("full")
        self.assertEqual(len(rows), 35)
        for block, order in enumerate(expected, 1):
            selected = [row for row in rows if row["repetition"] == block]
            self.assertEqual([row["sequence_ordinal"] for row in selected], list(range(5)))
            self.assertEqual(" ".join(symbols[row["variant"], row["engine_profile_id"]] for row in selected), order)
            self.assertEqual(len({model.run_id(row) for row in selected}), 5)
        self.assertEqual(model.population("smoke"), rows[:5])

    def test_complete_work_denominators_include_functional_and_setup(self):
        for profile, invokes, commands, matrix_calls, external_calls in (
                ("smoke", 52, 125, 260, 32), ("full", 794, 1609, 27790, 6160)):
            self.assertEqual(model.counts(profile), {"invokes": invokes, "commands": commands,
                                                    "functional_invokes": 24, "functional_commands": 53, "setup_commands": 16})
            self.assertEqual(invokes * len(model.population(profile)), matrix_calls)
            external = engine.plan(profile)
            self.assertEqual(external["setup_cases"], [])
            self.assertEqual([row["id"] for row in external["cases"]], ["warm-echo"])
            plan = external["cases"][0]["client_plan"]
            self.assertEqual((plan["warmup_attempts"] + plan["measured_attempts"]) * 2 * external["repetitions"], external_calls)

    def test_model_rejects_reordered_or_crossed_selection(self):
        row = model.population("full")[7]
        for change in ({"sequence_ordinal": 0}, {"variant": "control"}, {"engine_profile_id": "P1"},
                       {"repetition": True}, {"sequence_ordinal": False}):
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                model.plan("full", **dict(row, **change))
        with self.assertRaises(EvidenceError):
            model.plan("smoke", repetition=2)

    def test_all_generated_plans_validate_and_schema_rejects_crossings(self):
        import jsonschema
        root = Path(__file__).resolve().parents[2] / "benchmarks/optimization"
        schema = json.loads((root / "engine-plan.schema.json").read_bytes())
        validator = jsonschema.Draft202012Validator(schema)
        for profile in ("smoke", "full"):
            for row in model.population(profile):
                plan = model.plan(profile, **row)
                validator.validate(plan)
                for mutation in ({"unexpected": True}, {"profile": "other"}, {"repetition": 8}, {"repetition": True},
                                 {"sequence_ordinal": 5}, {"engine_profile_id": "P2"}):
                    with self.subTest(plan=plan, mutation=mutation), self.assertRaises(jsonschema.ValidationError):
                        validator.validate(dict(plan, **mutation))
                if row["variant"] == "candidate":
                    with self.assertRaises(jsonschema.ValidationError):
                        validator.validate(dict(plan, requested_engine=None))
                else:
                    with self.assertRaises(jsonschema.ValidationError):
                        validator.validate(dict(plan, requested_engine=model.PROFILES["D0"]))
        for path in root.glob("engine*.schema.json"):
            jsonschema.Draft202012Validator.check_schema(json.loads(path.read_bytes()))

    def test_configuration_contrasts_reference_same_actual_D0(self):
        records = []
        for row in model.population("full"):
            # Pure arithmetic fixture, explicitly not a source/build evidence graph.
            records.append({**row, "status": "passed", "source": {"commit": "synthetic"},
                            "binary": {"sha256": "synthetic"}, "configuration_digest": row["engine_profile_id"],
                            "metrics": {"elapsed": str(row["sequence_ordinal"] + 1), "unavailable": None}})
        results = aggregate.comparisons(records, "full")
        self.assertEqual(len(results), 4)
        for index in range(7):
            baselines = [row["pairs"][index]["baseline"] for row in results[1:]]
            self.assertEqual(baselines[0], baselines[1])
            self.assertEqual(baselines[1], baselines[2])
            self.assertEqual(baselines[0]["engine_profile_id"], "D0")
            self.assertEqual(baselines[0]["variant"], "candidate")
        for row in results:
            self.assertEqual(row["metrics"]["unavailable"]["available_pairs"], 0)
            self.assertEqual(row["metrics"]["unavailable"]["unavailable_pairs"], 7)
        with self.assertRaisesRegex(EvidenceError, "duplicate-owner"):
            aggregate.comparisons(records + records[:1], "full")


class EngineMemoryTests(unittest.TestCase):
    def sample(self):
        value = {"schema": "latent.optimization.engine-memory.v1", "checkpoint": "post-start",
                 "collector_started_nanos": "10", "collector_finished_nanos": "20",
                 "process_id": "123", "start_time_ticks": "456"}
        for name, source, keys in (("status", "proc-self-status", resources.STATUS),
                                   ("smaps_rollup", "proc-self-smaps-rollup", resources.ROLLUP)):
            value[name] = {"source": source, "values": {key: {"value_bytes": "0", "reason": None} for key in keys}}
        return value

    def test_available_zero_and_missing_field_remain_distinct(self):
        value = self.sample()
        value["smaps_rollup"]["values"]["pss_bytes"] = {"value_bytes": None, "reason": "permission-denied"}
        result = resources.memory(value, "post-start", (123, 456), 0, 30)
        self.assertEqual(result["rss_bytes"], "0")
        self.assertIsNone(result["pss_bytes"])
        summary = resources.summarize([result])
        self.assertEqual(summary["rss_bytes"]["observed"], 1)
        self.assertEqual(summary["pss_bytes"]["unavailable"], 1)
        self.assertIsNone(summary["pss_bytes"]["maximum"])
        value["smaps_rollup"]["values"]["pss_bytes"]["value_bytes"] = "0"
        with self.assertRaisesRegex(EvidenceError, "value-with-reason"):
            resources.memory(value, "post-start", (123, 456), 0, 30)

    def test_resource_identity_clock_and_high_water_mutations(self):
        for change in ({"process_id": "124"}, {"start_time_ticks": "457"}, {"process_id": None},
                       {"collector_started_nanos": "31"}, {"collector_finished_nanos": "31"}, {"checkpoint": "elsewhere"}):
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                resources.memory(dict(self.sample(), **change), "post-start", (123, 456), 0, 30)
        value = self.sample()
        value["status"]["values"]["rss_bytes"]["value_bytes"] = "1"
        with self.assertRaisesRegex(EvidenceError, "high-water-below-current"):
            resources.memory(value, "post-start", (123, 456), 0, 30)

    def test_unavailable_identity_and_unsupported_platform_are_bound(self):
        for os_name, reason in (("Linux", "identity-unavailable"), ("Windows", "unsupported-platform")):
            value = self.sample()
            value.update(process_id=None, start_time_ticks=None)
            for name in ("status", "smaps_rollup"):
                for row in value[name]["values"].values():
                    row.update(value_bytes=None, reason=reason)
            result = resources.memory(value, "post-start", (123, 456), 0, 30, operating_system=os_name)
            self.assertTrue(all(item is None for item in result.values()))
            with self.assertRaises(EvidenceError):
                resources.memory(value, "post-start", (123, 456), 0, 30,
                                 operating_system="Windows" if os_name == "Linux" else "Linux")
            crossed = copy.deepcopy(value)
            crossed["status"]["values"]["rss_bytes"] = {"value_bytes": "0", "reason": None}
            with self.assertRaisesRegex(EvidenceError, "unbound-value"):
                resources.memory(crossed, "post-start", (123, 456), 0, 30, operating_system=os_name)


class EngineSemanticTests(unittest.TestCase):
    """Small counterexamples are parser units, never qualifying source evidence."""
    def test_rehashed_payload_and_crossed_response_projection_reject(self):
        expected = [692060160]
        raw = framed(expected)
        row = {"utf8": raw.decode(), "sha256": sha256(raw), "bytes": str(len(raw)),
               "value": expected, "media_type": schedule.MEDIA}
        self.assertEqual(calls.blob(row, expected, response=True), expected)
        forged = copy.deepcopy(row)
        changed = framed([1])
        forged.update(utf8=changed.decode(), sha256=sha256(changed), bytes=str(len(changed)), value=[1])
        with self.assertRaisesRegex(EvidenceError, "semantic-or-request-crossed"):
            calls.blob(forged, expected, response=True)
        row["value"] = [1]
        with self.assertRaisesRegex(EvidenceError, "projection-crossed"):
            calls.blob(row, expected, response=True)

    def test_guest_log_uses_declared_struct_order_and_same_activation(self):
        attrs = {"latent.activation_id": "engine-fn-17", "latent.span_id": "b" * 16, "latent.trace_id": "a" * 32}
        record = {"activation_id": "engine-fn-17", "level": "info", "message": schedule.DIRTY, "fields": attrs}
        raw = framed(record)
        # The surrounding serde_json Value sorts its keys; its original hash
        # and log charge still cover CapturedLog's declared struct field order.
        retained = {"record": dict(sorted(record.items())), "sha256": sha256(raw), "encoded_bytes": str(len(raw))}
        offer = {"activation_id": "engine-fn-17"}
        calls.guest_logs([retained], offer)
        forged = copy.deepcopy(retained)
        forged["record"]["activation_id"] = "engine-fn-18"
        changed = dict(record, activation_id="engine-fn-18")
        forged.update(sha256=sha256(framed(changed)), encoded_bytes=str(len(framed(changed))))
        with self.assertRaisesRegex(EvidenceError, "log-identity"):
            calls.guest_logs([forged], offer)
        retained["sha256"] = sha256(framed(retained["record"]))
        with self.assertRaisesRegex(EvidenceError, "byte-binding"):
            calls.guest_logs([retained], offer)

    def test_functional_plan_has_real_faults_and_three_recovery_reset_boundaries(self):
        cases = [schedule.functional(index) for index in range(1, 25)]
        self.assertEqual(sum(case[-1] is None for case in cases), 15)
        self.assertEqual([index + 1 for index, case in enumerate(cases) if case[-1] == "cancelled"], [17, 19, 20, 21, 22])
        self.assertEqual(cases[8][2], ["trap"])
        self.assertEqual(cases[9][3], [692060160])
        self.assertEqual(cases[16][2], ["cancel"])
        self.assertEqual(cases[17][3], [692060160])
        self.assertEqual(cases[22][1:4], ("identify", [], [11]))
        self.assertEqual(cases[23][1:4], ("bump", [], [1]))
        self.assertEqual(schedule.grant(cases[14][4])["wall_time_limit_millis"], "50")
        self.assertEqual(schedule.grant(cases[12][4])["memory_bytes"], "4194304")


if __name__ == "__main__":
    unittest.main()
