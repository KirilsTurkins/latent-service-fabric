"""Actual debug raw, rehashed forgeries and fixed population bounds; no workloads."""
import copy
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.optimization_backend_revision.evidence import Artifacts
from tools.optimization_backend_revision.recovery import aggregate, model
from tools.optimization_backend_revision.recovery.parse import parse
from tools.optimization_backend_revision.recovery.proofs import terminal_precedence
from tools.optimization_evidence.common import canonical, sha256


class Fixture:
    def __init__(self, root, variant="candidate"):
        self.root, self.variant = root, variant
        source = Path(__file__).parent / "fixtures/transport_recovery"
        self.raw = json.loads(gzip.decompress((source / f"{variant}.json.gz").read_bytes()))
        for name in ("capsule", "contracts", "deployment"):
            shutil.copyfile(source / f"generic-{name}.json", root / f"generic-{name}.json")
        self.identity, self.selected = copy.deepcopy(self.raw["identity"]), copy.deepcopy(self.raw["plan"])
        self.component = {"path": "generic/generic-capsule.wasm", "sha256": self.raw["fixture"]["component_sha256"],
                          "bytes": self.raw["fixture"]["component_bytes"]}

    def replay(self):
        (self.root / "recovery.json").write_bytes(canonical(self.raw))
        refs = []
        for path in self.root.glob("*.json"):
            data = path.read_bytes()
            refs.append({"path": path.name, "sha256": sha256(data), "bytes": str(len(data))})
        artifacts = Artifacts(self.root, refs, set())
        artifacts.path(next(row for row in refs if row["path"] == "recovery.json"))
        return parse(self.raw, self.selected, self.identity, artifacts, self.root / "recovery.json", self.component, self.variant)

    def offers(self):
        return [row for row in self.raw["samples"] if row["kind"] == "invoke"]

    def checkpoints(self):
        return [row for row in self.raw["samples"] if row["kind"] == "checkpoint"]

    def remove_record(self, removed):
        sequence = int(removed["sequence"])
        self.raw["diagnostic"]["records"].remove(removed)
        def renumber(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ("sequence", "phase_record_sequence", "terminal_sequence") and child is not None and int(child) > sequence:
                        value[key] = str(int(child) - 1)
                    else:
                        renumber(child)
            elif isinstance(value, list):
                for child in value:
                    renumber(child)
        renumber(self.raw)


class RecoveryFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))

    def test_original_actual_debug_graph_binds_all_work_and_recovery(self):
        value = self.fixture.replay()
        self.assertEqual(self.fixture.identity["qualification"], "functional-debug-only")
        self.assertEqual((value["samples"], value["commands"], value["diagnostic_event_count"]), ("61", "125", "688"))
        cleanup = value["shutdown"]["cleanup"]
        self.assertEqual((cleanup["handoffs"], cleanup["completed"], cleanup["reserved"], cleanup["queued"], cleanup["running"]), (19, 19, 0, 0, 0))
        self.assertTrue(cleanup["driverJoined"])
        self.assertEqual(sum(row["transport_handoff"] is not None for row in value["coverage"]), 19)
        actual = [row for row in value["coverage"] if row["case"] == "running-disconnect"]
        self.assertEqual(len(actual), 5)
        self.assertTrue(all(row["running_at_drop_trigger"] and row["disconnect"]["aborted"]
                            and row["native_cleanup"]["disposition"] == "released" and row["cells"]["available"] == 4 for row in actual))

    def test_fixed_one_pair_and_short_envelopes_not_old_budget_override(self):
        for profile in ("smoke", "full"):
            self.assertEqual(model.population(profile), [(1, "control"), (1, "candidate")])
            with self.assertRaises(ValueError):
                model.plan(profile, 2)
        self.assertEqual(len(model.offers()), 61)
        self.assertEqual(sum(case == "recovery" for case, _, _ in model.offers()), 30)
        for ceiling in (1, 2, 5, 10):
            for case in ("expiry", "disconnect"):
                self.assertEqual(sum(item[:2] == (case, ceiling) for item in model.offers()), 3)
        self.fixture.offers()[1]["transport_budget_millis"] = "1000"
        with self.assertRaisesRegex(ValueError, "original-envelope"):
            self.fixture.replay()

    def test_actual_control_keeps_capacity_loss_and_unavailable_supervisor(self):
        self.fixture = Fixture(Path(self.temporary.name), "control")
        parsed = self.fixture.replay()
        self.assertEqual((parsed["samples"], parsed["commands"], parsed["diagnostic_event_count"]), ("61", "125", "547"))
        self.assertNotIn("cleanup", parsed["shutdown"])
        self.assertTrue(all(row["supervisor"] is None and row["transport_handoff"] is None for row in parsed["coverage"]))
        value = aggregate.aggregate({"profile": "smoke"}, "sha256:" + "a" * 64, {},
            [{"repetition": 1, "variant": "control", "status": "passed", **parsed}], False, False)
        self.assertEqual(value["runs"][0]["followup_successes"], "5")
        self.assertEqual(value["runs"][0]["actual_running_disconnects"], "0")
        self.assertEqual(value["runs"][0]["coverage"][11]["cells"]["quarantined"], 4)

    def test_both_actual_graphs_match_new_aggregate_schema(self):
        import jsonschema
        records = []
        for variant in ("control", "candidate"):
            fixture = Fixture(Path(self.temporary.name), variant)
            records.append({"repetition": 1, "variant": variant, "status": "passed", **fixture.replay()})
        value = aggregate.aggregate({"profile": "smoke"}, "sha256:" + "a" * 64, {}, records, True, False)
        schema_path = Path(__file__).resolve().parents[2] / "benchmarks/optimization/recovery-aggregate.schema.json"
        schema = json.loads(schema_path.read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(json.loads(canonical(value)))
        self.assertEqual((value["status"], value["validated_calls"], value["validated_commands"]), ("incomplete", "122", "250"))

    def test_five_running_witness_cannot_be_erased_after_rehash(self):
        self.fixture.offers()[49]["running_witness"] = None
        with self.assertRaisesRegex(ValueError, "five-running"):
            self.fixture.replay()

    def test_changed_native_release_or_crossed_activation_cannot_claim_reuse(self):
        row = self.fixture.offers()[49]
        original = copy.deepcopy(row["cleanup_log"])
        for changes in ({"cleanup": "abandoned"}, {"activation_id": self.fixture.offers()[51]["activation_id"]}):
            with self.subTest(changes=changes):
                row["cleanup_log"] = copy.deepcopy(original)
                row["cleanup_log"]["attributes"].update(changes)
                with self.assertRaisesRegex(ValueError, "not-released|log-identity"):
                    self.fixture.replay()

    def test_abort_requires_actual_join_and_does_not_fabricate_grpc_receipt(self):
        row = self.fixture.offers()[49]
        original = copy.deepcopy(row)
        row["disconnect"]["joined_nanos"] = str(int(row["disconnect"]["requested_nanos"]) - 1)
        with self.assertRaisesRegex(ValueError, "actual-or-joined"):
            self.fixture.replay()
        row.clear()
        row.update(original)
        row["grpc_code"] = 1
        with self.assertRaisesRegex(ValueError, "fabricates-rpc-response"):
            self.fixture.replay()

    def test_handoff_slot_generation_or_activation_cannot_cross(self):
        records = [row for row in self.fixture.raw["diagnostic"]["records"] if row["observation"]["kind"] == "transport-handoff"]
        records[1]["observation"]["slot"] = records[0]["observation"]["slot"]
        records[1]["observation"]["generation"] = records[0]["observation"]["generation"]
        with self.assertRaisesRegex(ValueError, "duplicate-handoff"):
            self.fixture.replay()

    def test_handoff_counter_cannot_be_zeroed_at_a_source_proved_checkpoint(self):
        checkpoint = next(row for row in self.fixture.checkpoints() if row["cleanup"]["completed"] > 0)
        checkpoint["cleanup"].update(handoffs=0, completed=0)
        with self.assertRaisesRegex(ValueError, "not-bound-to-source-events"):
            self.fixture.replay()

    def test_removing_handoff_record_cannot_keep_final_count(self):
        records = self.fixture.raw["diagnostic"]["records"]
        removed = next(row for row in records if row["observation"]["kind"] == "transport-handoff")
        # Rebind all references to the subsequent real records, preserving
        # meaningful chronology instead of merely failing sequence numbering.
        self.fixture.remove_record(removed)
        with self.assertRaisesRegex(ValueError, "handoffs|response-crossed"):
            self.fixture.replay()

    def test_erasing_final_running_cannot_erase_source_cleanup_requirement(self):
        row = self.fixture.offers()[49]
        row["running_witness_final"] = row["cleanup_log"] = None
        with self.assertRaisesRegex(ValueError, "source-running-witness-erased"):
            self.fixture.replay()

    def test_handoff_cause_and_clock_bind_actual_drop_and_publication(self):
        offer = self.fixture.offers()[49]
        events = [row["observation"] for row in self.fixture.raw["diagnostic"]["records"]
                  if row["token"] == offer["diagnostic_token"]]
        handoff = next(row for row in events if row["kind"] == "transport-handoff")
        winner = next(row for row in events if row["kind"] == "terminal-winner")
        original = copy.deepcopy(handoff)
        mutations = (({"cause": "deadline-exceeded"}, "deadline-still-future"),
                     ({"observed_at_nanos": str(int(offer["dispatch_nanos"]) + 1)}, "before-client-drop"),
                     ({"observed_at_nanos": str(int(winner["observed_at_nanos"]) + 1)}, "after-terminal"))
        for changes, reason in mutations:
            with self.subTest(changes=changes):
                handoff.clear()
                handoff.update(original | changes)
                with self.assertRaisesRegex(ValueError, reason):
                    self.fixture.replay()

    def test_cleanup_revision_cannot_cross_the_actual_pinned_response(self):
        row = self.fixture.offers()[49]
        row["cleanup_log"]["attributes"]["revision"] = "revision-v1:sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "pinned-revision-crossed"):
            self.fixture.replay()

    def test_published_failure_requires_actual_terminal_decision(self):
        token = self.fixture.offers()[49]["diagnostic_token"]
        removed = next(row for row in self.fixture.raw["diagnostic"]["records"]
                       if row["token"] == token and row["observation"]["kind"] == "terminal-decision")
        self.fixture.remove_record(removed)
        with self.assertRaisesRegex(ValueError, "required-terminal-decision-missing"):
            self.fixture.replay()

    def test_final_deadline_and_raw_disconnect_winners_cannot_be_crossed(self):
        original = copy.deepcopy(self.fixture.raw)
        for ordinal, code, state, reason in ((11, "cancelled", "cancelled", "expired-deadline-winner"),
                (49, "deadline-exceeded", "deadline_exceeded", "unexpired-disconnect-winner")):
            with self.subTest(ordinal=ordinal):
                self.fixture.raw = copy.deepcopy(original)
                offer = self.fixture.offers()[ordinal]
                offer["retained_status"].update(code=code, terminal_state=state)
                command = next(row for row in self.fixture.raw["samples"] if row["kind"] == "command"
                               and row["operation"] == "status" and row["target"] == offer["activation_id"])
                command["response"].update(code=code, terminal_state=state)
                winner = next(row["observation"] for row in self.fixture.raw["diagnostic"]["records"]
                              if row["token"] == offer["diagnostic_token"] and row["observation"]["kind"] == "terminal-winner")
                winner["terminal_state"] = state.replace("_", "-")
                with self.assertRaisesRegex(ValueError, reason):
                    self.fixture.replay()

    def test_terminal_precedence_preserves_explicit_cancel_and_resource_violations(self):
        terminal_precedence({"terminal_state": "cancelled"},
                            {"cancel_response": {"grpc_code": 0, "disposition": 1}},
                            {"decision": "deadline-exceeded"}, None)
        terminal_precedence({"terminal_state": "resource_exhausted"}, {"cancel_response": None},
                            {"decision": "accepted"}, {"cause": "cancelled"})
        with self.assertRaisesRegex(ValueError, "expired-deadline-winner"):
            terminal_precedence({"terminal_state": "resource_exhausted"}, {"cancel_response": None},
                                {"decision": "deadline-exceeded"}, {"cause": "cancelled"})

    def test_candidate_cannot_hide_join_or_quarantine(self):
        report = self.fixture.raw["shutdown"]
        original = report.pop("cleanup")
        with self.assertRaisesRegex(ValueError, "observer-missing"):
            self.fixture.replay()
        report["cleanup"] = original
        report["quarantinedCells"] = 1
        with self.assertRaisesRegex(ValueError, "cell-capacity"):
            self.fixture.replay()

    def test_complete_claim_cannot_omit_or_duplicate_offer(self):
        self.fixture.offers()[-1]["ordinal"] = "59"
        with self.assertRaisesRegex(ValueError, "missing-duplicate"):
            self.fixture.replay()

    def test_aggregate_keeps_client_drop_in_its_actual_population(self):
        parsed = self.fixture.replay()
        value = aggregate.aggregate({"profile": "smoke"}, "sha256:" + "a" * 64, {},
            [{"repetition": 1, "variant": "candidate", "status": "passed", **parsed}], False, False)
        row = value["runs"][0]
        self.assertEqual(row["followup_successes"], "30")
        self.assertEqual(row["actual_running_disconnects"], "5")
        self.assertEqual(sum(int(number) for number in row["all_offers"]["counts"]["outcomes"].values()), 61)
        self.assertEqual(row["all_offers"]["counts"]["outcomes"]["client-disconnected"], "16")
        self.assertEqual(value["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
