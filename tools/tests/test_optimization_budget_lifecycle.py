"""Small synthetic protocol observations; never benchmark or release evidence."""
import copy
import unittest
from unittest.mock import patch

from tools.optimization_backend_revision.budget import attempts, failed, model, proofs
from tools.optimization_backend_revision.budget.observer import Diagnostic, waits


def offered(index=0, start=1000):
    case, budget, function = model.offers()[index]
    transport = model.transport_budget(case, budget)
    release = "sha256:" + "a" * 64
    deadline = start + transport * 1_000_000
    absolute = (1_000_000_000 + deadline + 999_999) // 1_000_000
    row = {"kind": "invoke", "ordinal": str(index), "case": case, "budget_millis": str(budget), "function": function,
           "transport_budget_millis": str(model.transport_budget(case, budget)),
           "activation_id": f"budget-{index:02}-{case}-{budget}", "release_digest": release,
           "scheduled_nanos": str(start), "dispatch_nanos": str(start + 10), "dispatch_lag_nanos": "10",
           "completed_nanos": str(start + 900), "deadline_nanos": str(deadline), "deadline_unix_millis": str(absolute),
           "absolute_deadline_quantization_nanos": str(absolute * 1_000_000 - 1_000_000_000 - deadline), "overshoot_nanos": "0",
           "grpc_timeout_header": f"{transport * 1000 - 1}u", "request_payload": attempts.payload(b"[]"),
           "expected_payload": attempts.payload(b"[11]") if function == "identify" else None,
           "diagnostic_token": "0", "body_gate": None, "rpc_received": True, "outcome": "success", "valid_response": True,
           "response": {"activation_id": f"budget-{index:02}-{case}-{budget}", "release_digest": release, "revision_id": "revision",
                        "route_generation": "1", "code": None, "payload": attempts.payload(b"[11]"),
                        "consumption": {name: "0" for name in attempts.common.CONSUMPTION.split()}}}
    row["response"]["consumption"].update(cpu_fuel="100", peak_memory_bytes="65536", wall_time_micros="1")
    if case == "queued":
        row["queue_witness"] = None
    return row


def diagnostic(offer):
    start = int(offer["dispatch_nanos"])
    header = offer["grpc_timeout_header"]
    expiry = str(start + 10 + int(header[:-1]) * 1000)
    grant = {"cpu_fuel": "10000000000", "memory_bytes": "67108864", "wall_time_limit_millis": offer["budget_millis"],
             "log_bytes": "16384", "reserved_dimensions_zero": True}
    deadline = {"admitted_at_nanos": str(start + 20), "admitted_at_unix_millis": "1000", "expires_at_nanos": expiry,
                "unix_millis": offer["deadline_unix_millis"]}
    values = [
        {"kind": "ingress", "observed_at_nanos": str(start + 10), "expires_at_nanos": expiry, "deadline_unix_millis": offer["deadline_unix_millis"]},
        {"kind": "body-decoded", "observed_at_nanos": str(start + 20), "request_deadline_unix_millis": offer["deadline_unix_millis"],
         "request_wall_time_limit_millis": offer["budget_millis"]},
        {"kind": "admission-check", "observed_at_nanos": str(start + 20), "deadline": deadline,
         "remaining_nanos": str(int(expiry) - start - 20), "required_nanos": "1000000", "decision": "accepted", "platform_code": None},
        {"kind": "admitted-ledger", "observed_at_nanos": str(start + 30), "deadline": deadline, "budget": grant},
        {"kind": "execution-deadline", "observed_at_nanos": str(start + 40), "deadline": deadline, "budget": grant},
        {"kind": "lifecycle-phase", "observed_at_nanos": str(start + 50), "phase": "running"},
        {"kind": "terminal-decision", "observed_at_nanos": str(start + 100), "expires_at_nanos": expiry,
         "decision": "completed", "platform_code": None},
        {"kind": "terminal-winner", "observed_at_nanos": str(start + 110), "terminal_state": "completed"},
    ]
    return {"collector_started_nanos": "10000000000", "collector_finished_nanos": "10000000100", "origin_nanos": "0",
            "overflowed": False, "identities": [{"token": "0", "activation_id": offer["activation_id"]}],
            "records": [{"sequence": str(index), "token": "0", "observation": copy.deepcopy(row)} for index, row in enumerate(values)]}


class BudgetLifecycleTests(unittest.TestCase):
    def test_exact_population_and_wire_response(self):
        self.assertEqual(len(model.offers()), 23)
        self.assertEqual(len(proofs.command_order()), 32)
        self.assertEqual(sum(1 for operation, _ in proofs.command_order() if operation == "cancel"), 9)
        row = offered()
        normalized = attempts.validate(row, 1_000_000_000, row["release_digest"])
        self.assertEqual(normalized["outcome"], "success")
        self.assertEqual(row["response"]["activation_id"], "budget-00-prewarm-1000")
        self.assertTrue(Diagnostic(diagnostic(row)).bind(row, "candidate")["observed"])

    def test_changed_budget_and_fast_failure_cannot_be_success(self):
        row = offered()
        row["deadline_nanos"] = str(int(row["deadline_nanos"]) + 1)
        with self.assertRaisesRegex(ValueError, "wire-deadline"):
            attempts.validate(row, 1_000_000_000, row["release_digest"])
        row = offered()
        row["response"]["payload"] = None
        with self.assertRaisesRegex(ValueError, "semantic-success"):
            attempts.validate(row, 1_000_000_000, row["release_digest"])

    def test_candidate_extension_fails_but_control_records_actual_difference(self):
        offer = offered()
        value = diagnostic(offer)
        for row in value["records"]:
            event = row["observation"]
            if "deadline" in event:
                event["deadline"]["expires_at_nanos"] = str(int(event["deadline"]["expires_at_nanos"]) + 1000)
                if "remaining_nanos" in event:
                    event["remaining_nanos"] = str(int(event["remaining_nanos"]) + 1000)
        observed = Diagnostic(value)
        self.assertTrue(observed.bind(offer, "control")["deadline_extensions"])
        with self.assertRaisesRegex(ValueError, "extended|terminal-deadline-crossed"):
            observed.bind(offer, "candidate")

    def test_terminal_decision_at_expiry_is_late_even_if_winner_claims_success(self):
        offer = offered()
        value = diagnostic(offer)
        value["records"][-2]["observation"]["observed_at_nanos"] = offer["deadline_nanos"]
        value["records"][-1]["observation"]["observed_at_nanos"] = str(int(offer["deadline_nanos"]) + 1)
        offer["completed_nanos"] = str(int(offer["deadline_nanos"]) + 2)
        observed = Diagnostic(value)
        self.assertEqual(len(observed.bind(offer, "control")["late_completed_decisions"]), 1)
        with self.assertRaisesRegex(ValueError, "late-completion"):
            observed.bind(offer, "candidate")

    def test_token_sequence_and_remaining_cannot_be_rehashed_into_proof(self):
        offer = offered()
        for mutation, reason in ((lambda value: value["records"][2].update(sequence="3"), "record-sequence"),
                                 (lambda value: value["records"][2]["observation"].update(remaining_nanos="1"), "remaining"),
                                 (lambda value: value.update(overflowed=True), "overflow")):
            value = diagnostic(offer)
            mutation(value)
            with self.assertRaisesRegex(ValueError, reason):
                Diagnostic(value)
        observed = Diagnostic(diagnostic(offer))
        offer["activation_id"] = "crossed"
        with self.assertRaisesRegex(ValueError, "token-crossed"):
            observed.bind(offer, "candidate")

    def test_execution_deadline_cannot_change_only_its_admission_origin(self):
        offer = offered()
        value = diagnostic(offer)
        value["records"][4]["observation"]["deadline"]["admitted_at_nanos"] = "1000"
        with self.assertRaisesRegex(ValueError, "reconstructed"):
            Diagnostic(value).bind(offer, "candidate")

    def test_wait_ownership_and_unavailable_are_not_zero(self):
        value = {"supported": True, "overflowed": False, "armed": "5", "completed": "2", "dropped": "3",
                 "live": "0", "maximum_live": "2", "rechecks": "2"}
        waits(value, final=True)
        for changed in (dict(value, armed="4"), dict(value, live="1"), dict(value, supported=False), dict(value, overflowed=True)):
            with self.assertRaises(ValueError):
                waits(changed, final=True)
        with self.assertRaisesRegex(ValueError, "regressed"):
            waits(dict(value, rechecks="1"), value)

    def test_native_grant_and_longer_transport_are_distinct_proved_limits(self):
        offer = offered(15)
        self.assertEqual((offer["budget_millis"], offer["transport_budget_millis"]), ("5", "1000"))
        offer["outcome"] = "platform-failure"
        offer["response"].update(payload=None, code="deadline-exceeded")
        normalized = attempts.validate(offer, 1_000_000_000, offer["release_digest"])
        self.assertEqual(normalized["outcome"], "platform-failure")
        self.assertEqual(normalized["overshoot_nanos"], "0")
        changed = copy.deepcopy(offer)
        changed["transport_budget_millis"] = "5"
        with self.assertRaisesRegex(ValueError, "transport-boundary"):
            attempts.validate(changed, 1_000_000_000, changed["release_digest"])
        value = diagnostic(offer)
        actual_expiry = 5_001_030
        for row in value["records"]:
            event = row["observation"]
            if "deadline" in event:
                event["deadline"]["expires_at_nanos"] = str(actual_expiry)
                if "remaining_nanos" in event:
                    event["remaining_nanos"] = str(actual_expiry - int(event["observed_at_nanos"]))
        value["records"][-2]["observation"].update(decision="deadline-exceeded", expires_at_nanos=str(actual_expiry),
                                                   observed_at_nanos=str(actual_expiry + 100))
        value["records"][-1]["observation"].update(terminal_state="deadline-exceeded", observed_at_nanos=str(actual_expiry + 200))
        offer["completed_nanos"] = str(actual_expiry + 300)
        observed = Diagnostic(value).bind(offer, "candidate")
        self.assertEqual(observed["native_terminal_decision_overshoot_nanos"], "100")
        self.assertEqual(observed["client_response_after_admitted_expiry_nanos"], "300")

    def test_failed_population_keeps_started_and_missing_final_rows_separate(self):
        value = {"schema": "latent.optimization.budget-lifecycle-arm.v1", "plan": model.plan("smoke"),
                 "identity": {"synthetic": True}, "status": "failed", "reason": "budget-lifecycle-failed",
                 "work": {"invoke_attempts": "22", "commands": "54", "budget_exhausted": False},
                 "samples": [{"kind": "invoke", "ordinal": str(index)} for index in range(20)]}
        observed = failed.summarize(value, value["plan"], value["identity"])
        self.assertEqual((observed["observed_invoke_attempts"], observed["retained_offer_rows"], observed["offers_without_final_rows"]),
                         ("22", "20", "2"))
        value["samples"][-1]["ordinal"] = "0"
        with self.assertRaisesRegex(ValueError, "duplicate-offer"):
            failed.summarize(value, value["plan"], value["identity"])

    def test_cancel_trigger_must_bind_actual_running_record(self):
        offer = offered(21)
        value = diagnostic(offer)
        value["records"][-1]["observation"]["terminal_state"] = "cancelled"
        observed = Diagnostic(value)
        row = {"kind": "command", "ordinal": "0", "operation": "cancel", "target": offer["activation_id"],
               "started_nanos": "1100", "finished_nanos": "2100", "response": {"grpc_code": 0, "disposition": 1, "terminal_state": None},
               "trigger": {"observed_nanos": "1070", "phase_record_sequence": "5"}}
        with patch.object(proofs, "command_order", return_value=[("cancel", 21)]):
            self.assertTrue(proofs.commands([row], {21: offer}, observed)[0]["running_trigger_observed"])
            row["trigger"]["phase_record_sequence"] = "4"
            with self.assertRaisesRegex(ValueError, "trigger-crossed"):
                proofs.commands([row], {21: offer}, observed)


if __name__ == "__main__":
    unittest.main()
