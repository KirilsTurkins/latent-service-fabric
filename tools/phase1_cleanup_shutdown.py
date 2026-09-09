"""Bounded cleanup-driver observations and affirmative final ownership proof.

Older receipts omit this optional object. Presence never implies a join: every
field, slot charge and handoff outcome is checked before final reclamation.
"""
from __future__ import annotations

LIVE = ("reserved", "queued", "running")
OUTCOMES = ("completed", "timedOut", "panicked", "fallbacks")
NUMBERS = ("capacity", *LIVE, "handoffs", *OUTCOMES)
FLAGS = ("accepting", "driverAlive", "driverJoined", "failed")
FIELDS = set(NUMBERS + FLAGS)


def validate_cleanup_snapshot(value, require):
    require(isinstance(value, dict) and set(value) == FIELDS, "cleanup-snapshot-fields")
    for name in NUMBERS:
        require(type(value[name]) is int and 0 <= value[name] <= 2**64 - 1,
                "cleanup-snapshot-counter")
    require(all(type(value[name]) is bool for name in FLAGS), "cleanup-snapshot-flag")
    require(1 <= value["capacity"] <= 1024, "cleanup-capacity-bound")
    require(sum(value[name] for name in LIVE) <= value["capacity"], "cleanup-live-slot-bound")
    require(value["handoffs"] == sum(value[name] for name in OUTCOMES)
            + value["queued"] + value["running"], "cleanup-handoff-accounting")
    require(not value["driverJoined"] or not value["driverAlive"], "cleanup-joined-driver-alive")


def validate_cleanup_shutdown(value, require):
    validate_cleanup_snapshot(value, require)
    require(value["accepting"] is False and value["driverAlive"] is False
            and value["driverJoined"] is True and value["failed"] is False,
            "cleanup-shutdown-state")
    require(all(value[name] == 0 for name in LIVE), "cleanup-live-owners")
    require(value["timedOut"] == value["panicked"] == value["fallbacks"] == 0,
            "cleanup-unacknowledged-handoffs")
