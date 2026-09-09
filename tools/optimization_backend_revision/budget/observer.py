"""Replay source-observed deadlines and owned wait guards, without inferred clocks."""
import re

from tools.optimization_evidence.attempts import PLATFORM_CODES
from tools.optimization_evidence.common import fields, require, text, uint

PHASES = {"received", "resolved", "admitted", "queued", "materializing", "running", "suspended",
          "preparing-commit", "committed", "effects-pending"}
TERMINALS = {"completed", "rejected", "cancelled", "deadline-exceeded", "resource-exhausted", "guest-trap",
             "state-conflict", "dependency-failed", "platform-failed"}
DECISIONS = {"accepted", "completed", "cancelled", "deadline-exceeded", "queue-infeasible", "load-stale",
             "queue-estimate-overflow", "missing-deadline", "rejected"}


def instant(value):
    require(isinstance(value, str) and re.fullmatch(r"0|-?[1-9][0-9]{0,19}", value), "budget-diagnostic-instant")
    result = int(value)
    require(abs(result) <= 2**64 - 1, "budget-diagnostic-instant-bound")
    return result


def optional(value):
    return None if value is None else instant(value)


def waits(value, previous=None, final=False):
    fields(value, "supported armed completed dropped live maximum_live rechecks overflowed")
    require(value["supported"] is True and value["overflowed"] is False, "budget-wait-observation-unavailable")
    numbers = {name: uint(value[name]) for name in ("armed", "completed", "dropped", "live", "maximum_live", "rechecks")}
    require(numbers["armed"] == numbers["completed"] + numbers["dropped"] + numbers["live"]
            and numbers["live"] <= numbers["maximum_live"] <= numbers["armed"], "budget-wait-ownership-inconsistent")
    if previous is not None:
        require(all(numbers[name] >= uint(previous[name]) for name in numbers if name != "live"), "budget-wait-counter-regressed")
    require(not final or numbers["live"] == 0, "budget-final-live-wait")
    return numbers


def deadline(value):
    fields(value, "admitted_at_nanos admitted_at_unix_millis expires_at_nanos unix_millis")
    admitted, expires = instant(value["admitted_at_nanos"]), optional(value["expires_at_nanos"])
    uint(value["admitted_at_unix_millis"])
    if value["unix_millis"] is not None:
        uint(value["unix_millis"])
    require((expires is None) == (value["unix_millis"] is None), "budget-partial-effective-deadline")
    return admitted, expires


def grant(value):
    fields(value, "cpu_fuel memory_bytes wall_time_limit_millis log_bytes reserved_dimensions_zero")
    require(value["reserved_dimensions_zero"] is True and value["cpu_fuel"] == "10000000000"
            and value["memory_bytes"] == "67108864" and value["log_bytes"] == "16384"
            and value["wall_time_limit_millis"] is not None
            and uint(value["wall_time_limit_millis"]) in (1, 2, 5, 10, 1000), "budget-diagnostic-grant")


def decision(value):
    require(value["decision"] in DECISIONS and ((value["platform_code"] in PLATFORM_CODES)
            if value["decision"] == "rejected" else value["platform_code"] is None), "budget-diagnostic-decision")


class Diagnostic:
    def __init__(self, value, *, maximum_identities=23, maximum_records=512):
        fields(value, "collector_started_nanos collector_finished_nanos origin_nanos overflowed identities records")
        begin, finish = uint(value["collector_started_nanos"]), uint(value["collector_finished_nanos"])
        origin = instant(value["origin_nanos"])
        require(origin <= begin <= finish and value["overflowed"] is False, "budget-diagnostic-capture-or-overflow")
        require(isinstance(value["identities"], list) and len(value["identities"]) <= maximum_identities
                and isinstance(value["records"], list) and len(value["records"]) <= maximum_records, "budget-diagnostic-capacity")
        self.value, self.identities, self.records, self.by_token = value, {}, {}, {}
        ids = set()
        for expected, row in enumerate(value["identities"]):
            fields(row, "token activation_id")
            token = uint(row["token"])
            require(token == expected, "budget-diagnostic-token-sequence")
            if row["activation_id"] is not None:
                text(row["activation_id"], 256)
                require(row["activation_id"] not in ids, "budget-diagnostic-id-crossed")
                ids.add(row["activation_id"])
            self.identities[token] = row["activation_id"]
            self.by_token[token] = []
        for expected, row in enumerate(value["records"]):
            fields(row, "sequence token observation")
            sequence, token = uint(row["sequence"]), uint(row["token"])
            require(sequence == expected and token in self.identities, "budget-diagnostic-record-sequence")
            observation = row["observation"]
            at = instant(observation.get("observed_at_nanos"))
            require(origin <= at <= finish, "budget-diagnostic-record-outside-capture")
            self.check_observation(observation)
            self.records[sequence] = row
            self.by_token[token].append(observation)
        for rows in self.by_token.values():
            require(rows and rows[0]["kind"] == "ingress"
                    and sum(row["kind"] == "ingress" for row in rows) == 1, "budget-diagnostic-ingress-missing")
            for kind in ("body-decoded", "admitted-ledger", "execution-deadline", "terminal-winner"):
                require(sum(row["kind"] == kind for row in rows) <= 1, "budget-diagnostic-stage-duplicated")

    @staticmethod
    def check_observation(row):
        kind = row.get("kind")
        extra = {
            "ingress": "expires_at_nanos deadline_unix_millis",
            "body-decoded": "request_deadline_unix_millis request_wall_time_limit_millis",
            "admission-check": "deadline remaining_nanos required_nanos decision platform_code",
            "admitted-ledger": "deadline budget", "execution-deadline": "deadline budget",
            "terminal-decision": "expires_at_nanos decision platform_code",
            "lifecycle-phase": "phase", "terminal-winner": "terminal_state",
        }
        require(kind in extra, "budget-diagnostic-kind")
        fields(row, "kind observed_at_nanos " + extra[kind])
        at = instant(row["observed_at_nanos"])
        if kind == "ingress":
            optional(row["expires_at_nanos"])
            if row["deadline_unix_millis"] is not None:
                uint(row["deadline_unix_millis"])
        elif kind == "body-decoded":
            for name in ("request_deadline_unix_millis", "request_wall_time_limit_millis"):
                if row[name] is not None:
                    uint(row[name])
        elif kind in ("admission-check", "admitted-ledger", "execution-deadline"):
            admitted, expires = deadline(row["deadline"])
            require(admitted <= at, "budget-deadline-before-admission")
            if kind == "admission-check":
                decision(row)
                require(row["remaining_nanos"] == (None if expires is None else str(max(0, expires - at))),
                        "budget-remaining-not-actual-deadline")
                if row["required_nanos"] is not None:
                    uint(row["required_nanos"])
                if row["decision"] == "accepted" and row["remaining_nanos"] is not None:
                    require(uint(row["remaining_nanos"]) > uint(row["required_nanos"] or "0"), "budget-admitted-without-required-time")
            else:
                grant(row["budget"])
        elif kind == "terminal-decision":
            optional(row["expires_at_nanos"])
            decision(row)
        elif kind == "lifecycle-phase":
            require(row["phase"] in PHASES, "budget-lifecycle-phase")
        else:
            require(row["terminal_state"] in TERMINALS, "budget-terminal-state")

    def bind(self, offer, variant):
        from .lineage import check as check_lineage
        token = offer["diagnostic_token"]
        if token is None:
            require(offer["outcome"] == "transport-failure", "budget-unobserved-platform-decision")
            return {"observed": False, "phases": [], "terminal_states": [], "deadline_extensions": [], "late_completed_decisions": []}
        token = uint(token)
        require(token in self.identities and self.identities[token] in (None, offer["activation_id"]), "budget-offer-token-crossed")
        rows = self.by_token[token]
        ingress = rows[0]
        require(uint(offer["dispatch_nanos"]) <= instant(ingress["observed_at_nanos"]), "budget-ingress-before-dispatch")
        require(ingress["expires_at_nanos"] is not None and ingress["deadline_unix_millis"] is not None,
                "budget-original-deadline-unobserved")
        header = offer["grpc_timeout_header"]
        require(isinstance(header, str) and re.fullmatch(r"[0-9]{1,8}[HMSmun]", header), "budget-ingress-timeout-header")
        unit = {"H": 3_600_000_000_000, "M": 60_000_000_000, "S": 1_000_000_000, "m": 1_000_000, "u": 1000, "n": 1}[header[-1]]
        require(instant(ingress["expires_at_nanos"]) - instant(ingress["observed_at_nanos"])
                == min(int(header[:-1]) * unit, 5_000_000_000), "budget-ingress-not-original-timeout")
        if offer["case"] != "delayed-body":
            require(self.identities[token] == offer["activation_id"] and sum(row["kind"] == "body-decoded" for row in rows) == 1,
                    "budget-body-identity-unobserved")
        for row in rows:
            if row["kind"] == "body-decoded":
                require(self.identities[token] == offer["activation_id"]
                        and row["request_deadline_unix_millis"] == offer["deadline_unix_millis"]
                        and row["request_wall_time_limit_millis"] == offer["budget_millis"], "budget-body-request-crossed")
            if row["kind"] in ("admitted-ledger", "execution-deadline"):
                require(row["budget"]["wall_time_limit_millis"] == offer["budget_millis"], "budget-granted-wall-changed")
                admitted, effective = deadline(row["deadline"])
                require(variant != "candidate" or effective is not None
                        and effective <= admitted + uint(offer["budget_millis"]) * 1_000_000, "budget-candidate-native-wall-extended")
        check_lineage(rows, offer, variant)
        expiry = optional(ingress["expires_at_nanos"])
        extensions, late = [], []
        ledger = None
        for row in rows:
            if "deadline" in row:
                _, current = deadline(row["deadline"])
                if expiry is not None and current is not None and current > expiry:
                    extensions.append({"stage": row["kind"], "nanos": str(current - expiry)})
                if row["kind"] == "admitted-ledger":
                    ledger = row["deadline"]
                elif row["kind"] == "execution-deadline":
                    require(variant != "candidate" or row["deadline"] == ledger, "budget-candidate-execution-deadline-reconstructed")
            if row["kind"] == "terminal-decision":
                terminal_expiry = optional(row["expires_at_nanos"])
                if ledger is not None:
                    require(variant != "candidate" or row["expires_at_nanos"] == ledger["expires_at_nanos"],
                            "budget-candidate-terminal-deadline-crossed")
                if row["decision"] == "deadline-exceeded" and terminal_expiry is not None:
                    require(instant(row["observed_at_nanos"]) >= terminal_expiry, "budget-premature-terminal-expiry")
            if row["kind"] == "terminal-decision" and row["decision"] in ("accepted", "completed"):
                limiting = [item for item in (expiry, optional(row["expires_at_nanos"]),
                    optional(ledger["expires_at_nanos"]) if ledger is not None else None) if item is not None]
                if limiting and instant(row["observed_at_nanos"]) >= min(limiting):
                    late.append({"observed_at_nanos": row["observed_at_nanos"], "expires_at_nanos": str(min(limiting))})
        require(variant != "candidate" or (not extensions and not late), "budget-candidate-deadline-extended-or-late-completion")
        phases = [row["phase"] for row in rows if row["kind"] == "lifecycle-phase"]
        winners = [row["terminal_state"] for row in rows if row["kind"] == "terminal-winner"]
        if offer["outcome"] == "success":
            require("running" in phases and winners == ["completed"]
                    and any(row["kind"] == "terminal-decision" and row["decision"] in ("accepted", "completed")
                            and instant(row["observed_at_nanos"]) <= uint(offer["completed_nanos"]) for row in rows),
                    "budget-success-without-actual-terminal-decision")
        effective_expiry = optional(ledger["expires_at_nanos"]) if ledger is not None else None
        terminal_decisions = [row for row in rows if row["kind"] == "terminal-decision"]
        return {"observed": True, "phases": phases, "terminal_states": winners,
                "deadline_extensions": extensions, "late_completed_decisions": late,
                "terminal_decision_observed": bool(terminal_decisions),
                "admitted_expires_at_nanos": None if effective_expiry is None else str(effective_expiry),
                "native_terminal_decision_overshoot_nanos": None if effective_expiry is None or not terminal_decisions else
                    str(max(0, instant(terminal_decisions[-1]["observed_at_nanos"]) - effective_expiry)),
                "client_response_after_admitted_expiry_nanos": None if effective_expiry is None else
                    str(max(0, uint(offer["completed_nanos"]) - effective_expiry))}
