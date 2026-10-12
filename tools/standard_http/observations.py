"""Peer observation predicates; none substitutes for guest or host-ledger evidence."""
from __future__ import annotations

import re

from .peer import MAX_CONNECTIONS, MAX_CONTACTS, MAX_EVENTS, MAX_RECEIVED, MAX_SECONDS
from .protocol import require
from .vectors import PROFILE

COUNTS = ("acceptedConnections", "startedRequests", "completedResponseWrites", "committedMutations",
          "rejectedRequests", "connectionBoundRejections", "receivedBytes")
STATES = {"accepted", "request-started", "request-complete", "held-headers", "held-body", "held-upload", "closed"}
EVENTS = {"connection-accepted", "request-started", "request-complete", "mutation-committed",
          "gate-pending", "gate-released", "response-write-complete", "peer-connection-closed",
          "remote-write-half-ended", "peer-request-deadline", "connection-lost", "request-rejected"}


def validate(value: dict) -> None:
    require(isinstance(value, dict) and value.get("schemaVersion") == PROFILE
            and value.get("kind") == "controlled-peer-observation"
            and value.get("evidenceScope") == "peer-protocol-only", "fixture-observation-profile")
    require(value.get("failure") is None, "fixture-observation-failed")
    require(isinstance(value.get("generation"), str)
            and re.fullmatch(r"[a-f0-9]{32}", value["generation"]), "fixture-observation-generation")
    require(value.get("state") in {"ready", "stopped"}
            and type(value.get("openConnections")) is int
            and 0 <= value["openConnections"] <= MAX_CONNECTIONS
            and type(value.get("listeningOrigins")) is int
            and value["listeningOrigins"] in {0, 2}, "fixture-observation-owner")
    require(value.get("limits") == {"connections": MAX_CONNECTIONS, "contacts": MAX_CONTACTS,
                                  "events": MAX_EVENTS, "receivedBytes": MAX_RECEIVED,
                                  "maximumSeconds": MAX_SECONDS}, "fixture-observation-limits")
    origins = value.get("origins")
    require(isinstance(origins, dict) and set(origins) == {"primary", "secondary"}
            and all(isinstance(origin, dict) and set(origin) == {"scheme", "host", "port"}
                    and origin["scheme"] == "http" and origin["host"] == "127.0.0.1"
                    and type(origin["port"]) is int and 1 <= origin["port"] <= 65535
                    for origin in origins.values())
            and origins["primary"]["port"] != origins["secondary"]["port"],
            "fixture-observation-origins")
    require(all(type(value.get(key)) is int and value[key] >= 0 for key in COUNTS),
            "fixture-observation-count")
    rows, events = value.get("requests"), value.get("events")
    require(isinstance(rows, list) and isinstance(events, list)
            and len(rows) == value["acceptedConnections"] <= MAX_CONTACTS
            and len(events) <= MAX_EVENTS and value["receivedBytes"] <= MAX_RECEIVED,
            "fixture-observation-bound")
    require(all(isinstance(row, dict) and type(row.get("request")) is int for row in rows)
            and [row["request"] for row in rows] == list(range(1, len(rows) + 1)),
            "fixture-observation-request-order")
    require(all(isinstance(item, dict) and type(item.get("sequence")) is int for item in events)
            and [item["sequence"] for item in events] == list(range(1, len(events) + 1)),
            "fixture-observation-event-order")
    require(all(type(row.get("responseBytesWritten")) is int and row["responseBytesWritten"] >= 0
                and row.get("role") in {"primary", "secondary"} and row.get("state") in STATES
                and ("closeReason" in row) == (row["state"] == "closed") for row in rows),
            "fixture-observation-request")
    require(all(item.get("kind") in EVENTS and type(item.get("request")) is int
                and 1 <= item["request"] <= len(rows) for item in events), "fixture-observation-event")
    require(value["openConnections"] == sum(row["state"] != "closed" for row in rows)
            and (value["state"] != "stopped" or value["openConnections"] == value["listeningOrigins"] == 0)
            and (value["state"] != "ready" or value["listeningOrigins"] == 2
                 or value["acceptedConnections"] == MAX_CONTACTS), "fixture-observation-owner-inconsistent")
    require(value["startedRequests"] == sum("vector" in row for row in rows)
            and value["committedMutations"] == sum(row.get("mutationCommitted") is True for row in rows)
            and value["completedResponseWrites"] == sum(row.get("closeReason") == "response-write-complete"
                                                        for row in rows)
            and value["rejectedRequests"] == sum(item.get("kind") == "request-rejected" for item in events),
            "fixture-observation-inconsistent")


def delta(before: dict, after: dict) -> dict:
    validate(before)
    validate(after)
    require(before.get("generation") == after.get("generation"), "fixture-observation-generation")
    require(before["origins"] == after["origins"] and before["limits"] == after["limits"],
            "fixture-observation-profile-changed")
    require(after["events"][:len(before["events"])] == before["events"],
            "fixture-observation-history-changed")
    require(all(after[key] >= before[key] for key in COUNTS), "fixture-observation-count-regressed")
    for old, new in zip(before["requests"], after["requests"]):
        require(old["request"] == new["request"] and old["role"] == new["role"]
                and old["responseBytesWritten"] <= new["responseBytesWritten"],
                "fixture-observation-owner-changed")
        for field in ("vector", "method", "requestFraming", "bodyBytes", "bodySha256", "mutationCommitted"):
            require(field not in old or old[field] == new.get(field), "fixture-observation-request-changed")
        require(old["state"] != "closed" or old == new, "fixture-observation-closed-owner-changed")
    return {**{key: after[key] - before[key] for key in COUNTS},
            "requests": after["requests"][len(before["requests"]):],
            "events": after["events"][len(before["events"]):]}


def require_zero_contact(before: dict, after: dict) -> None:
    change = delta(before, after)
    require(before.get("state") == after.get("state") == "ready"
            and before.get("listeningOrigins") == after.get("listeningOrigins") == 2,
            "fixture-zero-contact-needs-live-listeners")
    require(all(change[key] == 0 for key in COUNTS), "fixture-denied-operation-contacted-peer")


def require_one_committed_request(before: dict, after: dict, identity="commit-pending") -> None:
    change = delta(before, after)
    require(change["acceptedConnections"] == change["startedRequests"] == change["committedMutations"] == 1
            and len(change["requests"]) == 1 and change["requests"][0].get("vector") == identity,
            "fixture-mutation-replayed-or-not-committed")
    require(change["requests"][0].get("mutationCommitted") is True,
            "fixture-mutation-not-committed")


def require_stripped_redirect(before: dict, after: dict) -> None:
    change = delta(before, after)
    rows = [row for row in change["requests"] if row.get("vector") == "redirect-target"]
    require(len(rows) == 1 and rows[0].get("closeReason") == "response-write-complete"
            and all(rows[0].get(key) is False for key in
                    ("authorizationPresent", "cookiePresent", "proxyAuthorizationPresent")),
            "fixture-redirect-credential-not-stripped")
