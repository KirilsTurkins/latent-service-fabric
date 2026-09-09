"""Functional-only source observations, actual deadline lineage and guest effects."""
import json
import re

from tools.optimization_evidence.common import fields, require, uint
from ..budget.observer import Diagnostic as Base, deadline, instant
from . import schedule


class Diagnostic(Base):
    def __init__(self, value):
        super().__init__(value, maximum_identities=24, maximum_records=1024)
        require(len(self.identities) == 24 and set(self.identities.values()) == {f"engine-fn-{n:02}" for n in range(1, 25)},
                "engine-functional-observer-population")

    @staticmethod
    def check_observation(row):
        if row.get("kind") in ("admitted-ledger", "execution-deadline"):
            fields(row, "kind observed_at_nanos deadline budget")
            admitted, _ = deadline(row["deadline"])
            require(admitted <= instant(row["observed_at_nanos"]), "engine-ledger-before-admission")
            require(row["budget"] in [schedule.grant(name) for name in "GFMDHRC"], "engine-diagnostic-grant")
        else:
            Base.check_observation(row)

    def bind_call(self, call, status):
        row, expected = call["row"], call["expected"]
        projected = {**row, "case": "queued" if expected["index"] == 22 else "engine-functional",
                     "budget_millis": expected["budget"]["wall_time_limit_millis"],
                     "retained_status": status["response"], "retained_observed_nanos": status["finished_nanos"]}
        summary = super().bind(projected, "candidate")  # Both sources already include #103 precise deadlines.
        records = self.by_token[uint(row["diagnostic_token"])]
        require(all(event["budget"] == expected["budget"] for event in records if "budget" in event), "engine-ledger-request-grant-crossed")
        require("running" in summary["phases"] and len([r for r in records if r["kind"] == "execution-deadline"]) == 1
                and summary["terminal_decision_observed"], "engine-functional-not-actually-running")
        winner = next(event for event in records if event["kind"] == "terminal-winner")
        require(instant(winner["observed_at_nanos"]) <= uint(row["completed_nanos"]), "engine-publication-after-rpc-response")
        final = next(event for event in records if event["kind"] == "terminal-decision")
        if expected["code"] == "deadline-exceeded":
            require(final["decision"] == "deadline-exceeded" and instant(final["observed_at_nanos"])
                    >= int(summary["admitted_expires_at_nanos"]), "engine-deadline-fault-not-actual-expiry")
        oracle(call, records)
        return summary

    def running(self, sequence, call, before):
        sequence = uint(sequence)
        require(sequence in self.records, "engine-running-witness-not-recorded")
        record = self.records[sequence]
        event = record["observation"]
        require(record["token"] == call["row"]["diagnostic_token"] and event["kind"] == "lifecycle-phase"
                and event["phase"] == "running" and instant(event["observed_at_nanos"]) <= before,
                "engine-running-witness-crossed")


def oracle(call, records):
    row, expected, output = call["row"], call["expected"], call["output"]
    logs = row["guest_logs"]
    name = expected["function"]
    if expected["target_index"] in (6, 7):
        require(len(logs) == 1 and logs[0]["record"]["message"] == schedule.DIRTY
                and logs[0]["record"]["level"] == "info" and len(logs[0]["record"]["fields"]) == 3,
                "engine-memory-dirty-witness-missing")
    elif expected["target_index"] == 0 and name == "echo":
        # The maintained Echo guest emits one bounded result log, including
        # the input's UTF-8 byte length. Host correlation fields are checked
        # independently by calls.guest_logs before this fixture oracle.
        require(len(logs) == 1 and logs[0]["record"]["message"] == "echo invocation"
                and logs[0]["record"]["level"] == "info", "engine-echo-result-log-missing")
        attrs = logs[0]["record"]["fields"]
        require(len(attrs) == 6 and attrs.get("activation_id") == row["activation_id"]
                and attrs.get("message_bytes") == str(len(expected["payload"][0].encode("utf-8")))
                and attrs.get("outcome") == "success", "engine-echo-result-log-crossed")
    elif name == "snapshot":
        require(isinstance(output, list) and len(output) == 1 and logs == [], "engine-context-result-shape")
        value = output[0]
        marker = "a" if row["target"]["tenant"] == "engine-a" else "b"
        ledger = next(event for event in records if event["kind"] == "admitted-ledger")
        require(value["activation"] == row["activation_id"] and value["root"] == f"engine-root-{marker}"
                and value["parent"] == {"some": f"engine-parent-{marker}"}
                and value["principal"] == {"kind": "administrator", "subject": f"engine-subject-{marker}",
                    "tenant": {"some": f"engine-{marker}"}, "service": {"none": None}, "claims": []}
                and value["metadata"] == [["guest.marker", marker]]
                and value["deadline"] == {"some": ledger["deadline"]["unix_millis"]}
                and "private-" not in json.dumps(value), "engine-context-authority-or-deadline-crossed")
        trace = fields(value["trace"], "trace-id span-id trace-flags baggage")
        require(re.fullmatch(r"[0-9a-f]{32}", trace["trace-id"]) and re.fullmatch(r"[0-9a-f]{16}", trace["span-id"])
                and trace["trace-flags"] == 0 and trace["baggage"] == [], "engine-context-trace-crossed")
        for key in ("cpu-fuel", "memory-bytes", "log-bytes"):
            require(uint(value["remaining"][key]) <= uint(ledger["budget"][key.replace("-", "_")]), "engine-context-grant-exceeded")
    elif name == "clocks":
        require(isinstance(output, list) and len(output) == 1 and isinstance(output[0], list) and len(output[0]) == 3
                and len(logs) == 2 and all(item["record"]["message"] == "clock-step" for item in logs), "engine-clock-call-count")
        times = []
        for reading in output[0]:
            fields(reading, "monotonic wall")
            times.append(uint(reading["monotonic"]))
            uint(reading["wall"])
        require(times == sorted(times), "engine-monotonic-clock-regressed")
    elif name == "log-probe":
        require(isinstance(output, list) and len(output) == 1 and len(logs) == 1, "engine-log-probe-output")
        value = fields(output[0], "before after outcome")
        require(value["outcome"] == {"ok": True} and uint(value["before"]) - uint(value["after"]) == call["consumption"]["log_bytes"]
                and logs[0]["record"]["message"] == expected["payload"][0]
                and logs[0]["record"]["fields"].get("probe") == expected["payload"][1][0]["value"], "engine-log-probe-budget-crossed")
    else:
        require(not logs, "engine-unexpected-guest-log")
    if expected["code"] == "resource-exhausted":
        kind = "activation.fuel-exhausted" if name == "spin" else "activation.memory-exhausted"
        require(row["native_fault"]["kind"] == kind and row["response"]["details"] == [], "engine-resource-fault-detail-crossed")
