"""Finite source-probe observations of original CLI results; never raw payloads."""
from __future__ import annotations

import re

from .common import encode

TRAP_CODES = frozenset({"guest-trap", "guest-runtime-error", "budget-accounting-failed",
                        "result-limit-exceeded", "invalid-component-result"})
CURRENTNESS_REASONS = frozenset({
    "admission-authority-busy", "admission-authority-poisoned", "admission-control-busy",
    "admission-clock-lease-uncovered", "admission-clock-regression", "admission-durability-uncertain",
    "admission-owner-retired", "admission-restart-clock-floor", "admission-verification-busy",
    "signature-clock-regression", "signature-trust-conflict", "signature-stale-proof",
})
U64_FIELDS = ("cpuFuel", "peakMemoryBytes", "wallTimeMicros", "stateReadBytes", "stateWriteBytes",
              "blobReadBytes", "blobWriteBytes", "logBytes")
U32_FIELDS = ("childCalls", "outboundRequests", "effectCount")
MAX_CASES = 128
MAX_BYTES = 128 * 1024
PHASES = frozenset({"common-scenarios", "retained-restart"})
CATEGORIES = frozenset({"success", "declared-error", "platform-failure", "transport-failure"})


def _decimal(value, bits):
    if bits == 64:
        if not isinstance(value, str) or re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is None:
            return None
        number = int(value)
    else:
        if type(value) is not int or value < 0:
            return None
        number = value
    return str(number) if number < 1 << bits else None


def original_result(value: dict) -> dict:
    """Closed tokens and unsigned consumption only; exclude messages and metadata."""
    output = {}
    if not isinstance(value, dict):
        return {"malformed": True}
    category = value.get("category")
    if isinstance(category, str) and category in CATEGORIES:
        output["category"] = category
    if type(value.get("outcomeKnown")) is bool:
        output["outcomeKnown"] = value["outcomeKnown"]
    data = value.get("data")
    data = data if isinstance(data, dict) else {}
    used = data.get("consumption")
    if isinstance(used, dict):
        consumption = {}
        invalid = []
        fields = [(key, 64) for key in U64_FIELDS] + [(key, 32) for key in U32_FIELDS]
        for name, bits in fields:
            if name not in used:
                continue
            observed = _decimal(used[name], bits)
            if observed is None:
                invalid.append(name)
            else:
                consumption[name] = observed
        output["consumption"] = consumption
        if invalid:
            output["invalidConsumptionFields"] = invalid
    error = value.get("error")
    if not isinstance(error, dict) or error.get("code") != "guest-trap":
        return output
    details = error.get("details")
    if not isinstance(details, list) or len(details) > 16:
        output["trapDetailsUnavailable"] = True
        return output
    trap_rows = [row for row in details if isinstance(row, dict) and row.get("kind") == "activation.guest-trap"]
    if len(trap_rows) != 1 or not isinstance(trap_rows[0].get("fields"), dict):
        output["trapDetailsUnavailable"] = True
        return output
    code = trap_rows[0]["fields"].get("code")
    if not isinstance(code, str) or code not in TRAP_CODES:
        output["trapDetailsUnavailable"] = True
        return output
    output["guestTrapCode"] = code
    reasons = [row for row in details if isinstance(row, dict) and row.get("kind") == "admission.currentness"]
    if code == "guest-runtime-error" and len(reasons) == 1 and isinstance(reasons[0].get("fields"), dict):
        reason = reasons[0]["fields"].get("reason")
        if isinstance(reason, str) and reason in CURRENTNESS_REASONS:
            output["admissionCurrentnessReason"] = reason
    return output


class Capture:
    """Diagnostic collection cannot start a process, retry, or change an outcome."""
    def __init__(self):
        self.rows = []
        self.bytes = 0
        self.truncated = False
        self.client_statuses = set()
        self.observed = 0

    def observer(self, phase):
        if phase not in PHASES:
            raise ValueError("unknown-source-probe-phase")

        def observe(case, result, original_client_reaped):
            data = result.get("data") if isinstance(result, dict) else None
            recovery = data.get("recovery") if isinstance(data, dict) else None
            cleanup = recovery.get("clientCleanup") if isinstance(recovery, dict) else None
            client = ("unconfirmed" if cleanup == "unconfirmed" else
                      "owned-client-reaped" if original_client_reaped is True or cleanup == "owned-client-reaped"
                      else "not-confirmed")
            self.client_statuses.add(client)
            self.observed = min(self.observed + 1, MAX_CASES + 1)
            if (not isinstance(case, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", case) is None
                    or len(self.rows) >= MAX_CASES):
                self.truncated = True
                return
            row = {"phase": phase, "case": case, **original_result(result)}
            row["invocationClientCleanup"] = client
            size = len(encode(row))
            if self.bytes + size > MAX_BYTES:
                self.truncated = True
                return
            self.rows.append(row)
            self.bytes += size
        return observe

    def snapshot(self):
        cleanup = "not-observed"
        if self.client_statuses:
            cleanup = ("unconfirmed" if "unconfirmed" in self.client_statuses else
                       "owned-client-reaped" if self.client_statuses == {"owned-client-reaped"} else "not-confirmed")
        return {"schemaVersion": "latent.dev.source-node-diagnostics.v1", "cases": list(self.rows),
                "observedCaseCountLowerBound": self.observed, "retainedCaseCount": len(self.rows),
                "truncated": self.truncated, "invocationClientCleanup": cleanup}


def process_cleanup(shutdown, diagnostics):
    """Report positive observations, without inferring retirement from scope exit."""
    shutdown = shutdown if isinstance(shutdown, dict) else {}
    node_reaped = shutdown.get("state") == "stopped" and shutdown.get("reaped") is True
    clean = shutdown.get("cleanShutdown") is True
    clients = diagnostics["invocationClientCleanup"]
    return {"nodeReaped": node_reaped, "nodeCleanShutdown": clean, "invocationClients": clients,
            "confirmed": node_reaped and clean and clients == "owned-client-reaped" and not diagnostics["truncated"]}
