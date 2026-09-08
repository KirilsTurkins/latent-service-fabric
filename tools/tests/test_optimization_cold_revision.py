"""Replay real field relationships using complete, explicitly synthetic arms."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.optimization_backend_revision import validate_suite
from tools.optimization_backend_revision.cold import model
from tools.tests.cold_revision_fixtures import Fixture


class ColdRevisionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fixture=Fixture(Path(self.directory.name))
        self.path=self.fixture.root/"suite.json"

    def change(self,mutation,arm=1):
        ref=self.fixture.suite["runs"][arm]["raw"]
        raw=json.loads((self.fixture.root/ref["path"]).read_bytes())
        mutation(raw)
        self.fixture.replace(ref,raw)

    def test_complete_smoke_replays_zero_based_jobs_and_all_offers_without_full_claim(self):
        value=validate_suite(self.path)
        self.assertEqual((value["status"],value["validated_calls"]),("incomplete","154"))
        self.assertTrue(value["population_complete"])
        self.assertEqual(len(value["pairs"]),1)
        self.assertEqual(value,validate_suite(self.path))
        self.assertEqual(model.population("full"),(853,1729))
        self.assertEqual(model.population("smoke"),(77,177))
        for run in value["runs"]:
            self.assertEqual(sum(int(row["offers"]) for row in run["phase_metrics"]),77)
            self.assertEqual(run["compiler_job_records"][0]["job_id"],"0")
            phases={row["phase"]:row for row in run["phase_metrics"]}
            self.assertEqual([row["actual_compilations"] for row in run["phase_metrics"]],["1","0","1","5","1","0"])
            self.assertEqual(phases["warmup"]["warm_key_compilations"],"1")
            self.assertEqual(phases["warmup"]["cold_key_compilations"],"0")
            self.assertEqual(run["unattributed_compilation_records"],[])

    def test_rehashed_missing_offer_and_false_deadline_are_rejected(self):
        self.change(lambda raw: raw["samples"].pop(1))
        with self.assertRaisesRegex(ValueError,"event-count"):
            validate_suite(self.path)

    def test_rehashed_extended_budget_is_rejected(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row["kind"] == "invoke")
            row["deadline_nanos"]=str(int(row["deadline_nanos"])+1)
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"deadline-rewritten"):
            validate_suite(self.path)

    def test_fresh_engine_cannot_start_with_a_prepared_cache(self):
        def mutate(raw):
            raw["samples"][0]["node"]["inventory"]["cacheSummary"]["entries"]="1"
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"dormant-execution-cache"):
            validate_suite(self.path)

    def test_candidate_cannot_delete_optional_compiler_proof(self):
        self.change(lambda raw: raw["shutdown"].pop("compiler"))
        with self.assertRaisesRegex(ValueError,"compiler-proof-absent"):
            validate_suite(self.path)

    def test_candidate_cannot_delete_observer_compiler_proof(self):
        self.change(lambda raw: raw["final_observer"]["snapshot"].update(compiler=None))
        with self.assertRaisesRegex(ValueError,"pool-unobserved"):
            validate_suite(self.path)

    def test_rehashed_initial_snapshot_cannot_claim_cancellation_trigger(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row["kind"] == "cancellation")
            row["trigger"]["observation"]=copy.deepcopy(raw["initial_observer"])
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"trigger-not-compilation"):
            validate_suite(self.path)

    def test_completed_compiler_cannot_be_claimed_running(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row["kind"] == "cancellation")
            row["trigger"]["running_when_observed"]=True
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"trigger-not-compilation"):
            validate_suite(self.path)

    def test_cancellation_cannot_precede_its_deciding_capture(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row["kind"] == "cancellation")
            row["commands"][0]["started_nanos"]="0"
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"disposition-or-order"):
            validate_suite(self.path)

    def test_rehashed_cancellation_cannot_finish_after_its_phase(self):
        def mutate(raw):
            end=next(row for row in raw["samples"] if row["kind"] == "phase-end" and row["phase"] == "cancel")
            cancel=next(row for row in raw["samples"] if row["kind"] == "cancellation")
            for index,command in enumerate(cancel["commands"]):
                command["started_nanos"]=str(int(end["finished_nanos"])+1_000_000+index*20_000)
                command["finished_nanos"]=str(int(command["started_nanos"])+1000)
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"control-after-phase-end"):
            validate_suite(self.path)

    def test_rehashed_job_cannot_compile_after_its_successful_replies(self):
        def mutate(raw):
            first=next(row for row in raw["samples"] if row.get("key") == "1")
            captures=[raw["initial_observer"],raw["final_observer"]]
            captures.extend(row["observer"] for row in raw["samples"] if "observer" in row)
            captures.extend(row["trigger"]["observation"] for row in raw["samples"] if row["kind"] == "cancellation")
            for capture in captures:
                for row in capture["snapshot"]["recent_stages"]:
                    if row["job_id"] == "1":
                        row["started_nanos"]=str(int(first["completed_nanos"])+1000)
                        row["finished_nanos"]=str(int(row["started_nanos"])+1000)
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"success-before-observed-compilation"):
            validate_suite(self.path)

    def test_retained_accounting_cannot_borrow_another_activation(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row["kind"] == "invoke")
            row["retained_status"]["activation_id"]="foreign"
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"crossed-retained-activation"):
            validate_suite(self.path)

    def test_compiler_work_cannot_bleed_into_next_burst(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row["kind"] == "phase-end")
            row["observer"]["snapshot"]["compiler"]["queued_jobs"]="1"
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"phase-compiler-owner"):
            validate_suite(self.path)

    def test_rehashed_transient_ready_and_document_overruns_are_rejected(self):
        reference=self.fixture.suite["runs"][1]["raw"]
        original=json.loads((self.fixture.root/reference["path"]).read_bytes())
        for field,ceiling in (("ready_preparations",68),("ready_metadata_bytes",67_108_864),
                              ("ready_compiled_image_bytes",536_870_912),("reserved_document_bytes",21_233_664),
                              ("workers_live",2)):
            with self.subTest(field=field):
                raw=copy.deepcopy(original)
                snapshot=next(row["observer"]["snapshot"] for row in raw["samples"] if row["kind"] == "phase-start")
                snapshot["compiler"][field]=str(ceiling+1)
                self.fixture.replace(reference,raw)
                with self.assertRaisesRegex(ValueError,"compiler-gauge-bound"):
                    validate_suite(self.path)

    def test_rehashed_document_ceiling_cannot_be_raised_to_fit(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row["kind"] == "phase-start")
            row["observer"]["snapshot"]["compiler"]["maximum_document_bytes"]="999999999999"
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"compiler-controls"):
            validate_suite(self.path)

    def test_rehashed_idle_counts_cannot_hide_live_byte_charges(self):
        reference=self.fixture.suite["runs"][1]["raw"]
        original=json.loads((self.fixture.root/reference["path"]).read_bytes())
        for field,error in (("ready_metadata_bytes","ready-bytes-without-owner"),
                            ("ready_compiled_image_bytes","ready-bytes-without-owner"),
                            ("reserved_document_bytes","document-bytes-without-job")):
            with self.subTest(field=field):
                raw=copy.deepcopy(original)
                row=next(row for row in raw["samples"] if row["kind"] == "phase-end")
                row["observer"]["snapshot"]["compiler"][field]="1"
                self.fixture.replace(reference,raw)
                with self.assertRaisesRegex(ValueError,error):
                    validate_suite(self.path)

    def test_rehashed_cpu_record_cannot_change_task_mid_interval(self):
        def mutate(raw):
            row=raw["final_observer"]["snapshot"]["recent_stages"][0]
            row["thread_cpu"]["after"]["identity"]["thread_id"]="999"
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"cpu-thread-crossed"):
            validate_suite(self.path)

    def test_rehashed_cpu_totals_cannot_relabel_quantized_ticks(self):
        def mutate(raw):
            raw["final_observer"]["snapshot"]["stages"][0]["thread_cpu_user_ticks"]="99999"
        self.change(mutate)
        with self.assertRaisesRegex(ValueError,"cpu-total-not-raw"):
            validate_suite(self.path)

    def test_worker_whole_job_can_have_actual_same_task_cpu(self):
        def mutate(raw):
            captures=[raw["initial_observer"],raw["final_observer"]]
            captures.extend(row["observer"] for row in raw["samples"] if "observer" in row)
            captures.extend(row["trigger"]["observation"] for row in raw["samples"] if row["kind"] == "cancellation")
            for capture in captures:
                snapshot=capture["snapshot"]
                rows=snapshot["recent_stages"]
                whole=[row for row in rows if row["stage"] == "whole_job"]
                for row in whole:
                    donor=next(item for item in rows if item["job_id"] == row["job_id"] and item["stage"] == "component_new")
                    row["thread_cpu"]=copy.deepcopy(donor["thread_cpu"])
                total=next(row for row in snapshot["stages"] if row["stage"] == "whole_job")
                total.update(thread_cpu_samples=str(len(whole)),thread_cpu_unavailable="0",thread_cpu_user_ticks=str(len(whole)))
        self.change(mutate)
        result=validate_suite(self.path)
        stage=next(row for row in result["runs"][1]["preparation_stages"] if row["stage"] == "whole_job")
        self.assertEqual(stage["thread_cpu_samples"],"8")
        self.assertEqual(stage["thread_cpu_unavailable"],"0")

    def test_undispatched_warm_offer_remains_in_population_and_not_success_latency(self):
        def mutate(raw):
            row=next(row for row in raw["samples"] if row.get("phase") == "same-key" and row.get("key") == "0")
            row.update(outcome="client-overload",dispatch_nanos=None,dispatch_lag_nanos=None,
                       grpc_timeout_header=None,rpc_received=False,response=None,backend_timing=None,
                       retained_status={"grpc_code":5})
            row.pop("valid_response")
        self.change(mutate)
        value=validate_suite(self.path)
        selected=value["pairs"][0]["warm_during_cold"][0]
        self.assertEqual(selected["candidate"]["counts"]["attempts"],"16")
        self.assertEqual(selected["candidate"]["counts"]["undispatched"],"1")
        self.assertEqual(selected["candidate"]["successful_response_latency_nanos"]["count"],"15")
        self.assertEqual(selected["successful_latency_contrasts_conditioned_on_success"]["median"]["absolute"],"0")

    def test_failed_arm_stays_failed_with_other_arm_retained(self):
        self.fixture.suite.update(status="failed",reason="collection-failed")
        self.fixture.suite["runs"][1].update(status="failed",reason="collector-failed")
        self.fixture.save()
        value=validate_suite(self.path)
        self.assertEqual((value["status"],value["validated_calls"]),("failed","77"))
        self.assertFalse(value["attempt_count_complete"])


class CompilationPopulationTests(unittest.TestCase):
    def test_same_release_recompilation_is_counted_in_its_actual_phase(self):
        from tools.optimization_backend_revision.cold.aggregate import phase_compilations
        first={"sequence":"0","job_id":"0","component_digest":["0"]*32,
               "started_nanos":"10","finished_nanos":"20"}
        again=dict(first,sequence="6",job_id="1",started_nanos="40",finished_nanos="50")
        before={"observed_nanos":"30","recent_stages":[first]}
        after={"observed_nanos":"60","recent_stages":[first,again]}
        self.assertEqual(phase_compilations([first,again],(before,after)),[again])
        # Repeated snapshots at one timestamp cannot assign an old record twice.
        self.assertEqual(phase_compilations([first,again],(after,after)),[])


if __name__ == "__main__":
    unittest.main()
