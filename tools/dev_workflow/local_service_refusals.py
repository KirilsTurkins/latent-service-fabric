"""Closed, non-authoritative first-refusal observations from the owned fixture node."""
from __future__ import annotations

import json
import re

from .common import MAX_LOG

PREFIX = "LSF_LOCAL_SERVICE_REFUSAL_V1 "
SCHEMA = "latent.dev.local-service-refusal.v1"
SAMPLING = "before-public-redaction-after-adapter-return"
DIMENSIONS = frozenset({"cpu-fuel", "memory-bytes", "wall-time-micros", "child-calls", "outbound-requests",
                       "state-read-bytes", "state-write-bytes", "blob-read-bytes", "blob-write-bytes", "log-bytes", "effect-count"})
CODES = frozenset({"unavailable", "deadline-exceeded", "cancelled", "resource-exhausted", "permission-denied",
                   "unauthenticated", "invalid-argument", "not-found", "already-exists", "incompatible-contract",
                   "state-conflict", "dependency-failed", "guest-trap", "corrupt-artifact", "route-unavailable",
                   "admission-rejected", "internal"})


def number(value, maximum=18446744073709551615):
    return type(value) is int and 0 <= value <= maximum


def valid(row):
    if (not isinstance(row, dict) or set(row) != {"schemaVersion", "activationId", "sampling", "stage", "code",
            "reason", "typedBudget", "remaining", "descendants"}
            or row["schemaVersion"] != SCHEMA or row["sampling"] != SAMPLING
            or not isinstance(row["activationId"], str) or not re.fullmatch(r"dev-[0-9a-f]{32}", row["activationId"])
            or row["stage"] not in {"setup", "broker-dispatch", "child-start", "child-completion"}
            or row["code"] not in CODES or row["reason"] not in {"typed-budget", "descendant-capacity", "unclassified"}):
        return False
    remaining = row["remaining"]
    if (not isinstance(remaining, dict) or set(remaining) != {"cpuFuel", "memoryBytes", "childCalls", "wallTimeLimitMillis"}
            or not all(number(remaining[key]) for key in ("cpuFuel", "memoryBytes"))
            or not number(remaining["childCalls"], 4294967295)
            or remaining["wallTimeLimitMillis"] is not None and not number(remaining["wallTimeLimitMillis"])):
        return False
    descendants = row["descendants"]
    if descendants is not None and (not isinstance(descendants, dict)
            or set(descendants) != {"depth", "liveChildren", "liveDescendants", "reservedMemoryBytes", "liveObservedChildMemoryBytes", "closed"}
            or not number(descendants["depth"], 16) or type(descendants["closed"]) is not bool
            or not all(number(descendants[key]) for key in ("liveChildren", "liveDescendants", "reservedMemoryBytes", "liveObservedChildMemoryBytes"))):
        return False
    budget = row["typedBudget"]
    if budget is not None and (not isinstance(budget, dict) or set(budget) != {"dimension", "limit", "consumed", "requested"}
            or budget["dimension"] not in DIMENSIONS or not all(number(budget[key]) for key in ("limit", "consumed", "requested"))):
        return False
    return ((budget is not None) == (row["reason"] == "typed-budget")
            and (row["reason"] == "unclassified" or row["code"] == "resource-exhausted"))


def pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate-observation-field")
        value[key] = item
    return value


def observe(logs, scenarios):
    unavailable = {"state": "unavailable", "reason": "invalid-or-ambiguous-closed-observation"}
    if not isinstance(logs, str) or len(logs.encode()) > MAX_LOG:
        return unavailable
    cases = scenarios.get("results") if isinstance(scenarios, dict) else None
    if not isinstance(cases, list) or len(cases) > 32:
        return unavailable
    try:
        selected = {}
        for case in cases:
            if not isinstance(case, dict):
                return unavailable
            identity = case.get("activationId")
            if not isinstance(identity, str) or not re.fullmatch(r"dev-[0-9a-f]{32}", identity) or identity in selected:
                return unavailable
            selected[identity] = case["id"]
        records = {}
        for line in logs.splitlines():
            if not line.startswith(PREFIX):
                continue
            if len(line.encode()) > 2048 + len(PREFIX) or len(records) >= 32:
                return unavailable
            row = json.loads(line[len(PREFIX):], object_pairs_hook=pairs)
            if not valid(row) or row["activationId"] not in selected or row["activationId"] in records:
                return unavailable
            records[row["activationId"]] = row
    except (ValueError, TypeError, KeyError):
        return unavailable
    return {"state": "observed", "schemaVersion": SCHEMA, "sampling": SAMPLING,
            "cases": [{"case": name, "activationId": identity,
                       "state": "observed" if identity in records else "unknown-no-retained-refusal",
                       **({"refusal": records[identity]} if identity in records else {})}
                      for identity, name in selected.items()]}
