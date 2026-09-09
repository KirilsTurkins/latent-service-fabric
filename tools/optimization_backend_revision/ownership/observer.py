"""Replay bounded raw-vector ownership from the actual source event sequence."""
from tools.optimization_evidence.common import fields, require, uint

GAUGES = ("live_invocations", "live_raw_owners", "live_raw_capacity_bytes",
          "maximum_live_raw_owners", "maximum_live_raw_capacity_bytes")
COUNTERS = ("started_invocations", "finished_invocations", "dropped_invocations", *GAUGES)


class Observer:
    def __init__(self, variant, ids):
        require(variant in ("control", "candidate"), "ownership-observer-variant")
        self.variant, self.ids = variant, ids
        self.records, self.origin, self.last = [], None, 0
        self.enabled = False

    def check(self, value, *, enabled, lower=0, upper=2**64-1):
        fields(value, "capture_started_nanos capture_finished_nanos origin_offset_nanos snapshot")
        start, finish, origin = (uint(value[key]) for key in ("capture_started_nanos", "capture_finished_nanos", "origin_offset_nanos"))
        require(max(self.last, lower) <= start <= finish <= upper, "ownership-observer-capture-crossed")
        require(self.origin in (None, origin), "ownership-observer-origin-changed")
        self.origin, self.last = origin, finish
        snapshot = fields(value["snapshot"], "enabled overflowed maximum_identities maximum_identity_bytes maximum_records observed_nanos identities records " + " ".join(COUNTERS))
        require(snapshot["enabled"] is enabled and snapshot["overflowed"] is False
                and snapshot["maximum_identities"] == "8" and snapshot["maximum_identity_bytes"] == "512"
                and snapshot["maximum_records"] == "64", "ownership-observer-coverage-or-bounds")
        require(start <= origin + uint(snapshot["observed_nanos"]) <= finish, "ownership-observer-clock-not-bracketed")
        expected_ids = [{"token": str(index), "activation_id": identifier} for index, identifier in enumerate(self.ids)]
        require(snapshot["identities"] == (expected_ids if enabled else [])
                and (not self.enabled or enabled), "ownership-observer-identities-or-enable-changed")
        self.enabled = enabled
        records = snapshot["records"]
        require(isinstance(records, list) and len(records) <= 10 and records[:len(self.records)] == self.records,
                "ownership-observer-records-erased-or-mutated")
        state = dict.fromkeys(COUNTERS, 0)
        seen, capacity, previous = {}, {}, 0
        for sequence, row in enumerate(records):
            fields(row, "sequence token phase observed_nanos raw_length_bytes raw_capacity_bytes drop_reason " + " ".join(GAUGES))
            token, phase, observed = uint(row["token"]), row["phase"], uint(row["observed_nanos"])
            require(row["sequence"] == str(sequence) and token < len(self.ids) and enabled,
                    "ownership-observer-sequence-or-token")
            require(previous <= observed <= uint(snapshot["observed_nanos"]), "ownership-observer-event-clock")
            previous = observed
            end = "invocation_finished" if token == 0 else "invocation_dropped"
            expected = (["raw_owner_created", "raw_owner_dropped", "before_call_export", "guest_call_start", end]
                        if self.variant == "candidate" else
                        ["raw_owner_created", "before_call_export", "guest_call_start", "raw_owner_dropped", end])
            index = seen.get(token, 0)
            require(index < len(expected) and phase == expected[index]
                    and (token == 0 or seen.get(token - 1) == 5), "ownership-observer-phase-or-proof-order")
            seen[token] = index + 1
            length, cap = uint(row["raw_length_bytes"]), uint(row["raw_capacity_bytes"])
            require(length == 65536 and length <= cap <= 131072, "ownership-observer-raw-payload-capacity")
            require(capacity.get(token, cap) == cap, "ownership-observer-raw-capacity-changed")
            capacity[token] = cap
            if phase == "raw_owner_created":
                state["started_invocations"] += 1
                state["live_invocations"] += 1
                state["live_raw_owners"] += 1
                state["live_raw_capacity_bytes"] += cap
                state["maximum_live_raw_owners"] = max(state["maximum_live_raw_owners"], state["live_raw_owners"])
                state["maximum_live_raw_capacity_bytes"] = max(state["maximum_live_raw_capacity_bytes"], state["live_raw_capacity_bytes"])
            elif phase == "raw_owner_dropped":
                state["live_raw_owners"] -= 1
                state["live_raw_capacity_bytes"] -= cap
            elif phase.startswith("invocation_"):
                state["live_invocations"] -= 1
                state["finished_invocations" if phase == "invocation_finished" else "dropped_invocations"] += 1
            reason = ("before_guest_call" if self.variant == "candidate" else "owner_scope_exit") if phase == "raw_owner_dropped" else None
            require(row["drop_reason"] == reason and all(uint(row[key]) == state[key] for key in GAUGES),
                    "ownership-observer-owner-conservation")
        require(all(uint(snapshot[key]) == state[key] for key in COUNTERS), "ownership-observer-snapshot-conservation")
        self.records = records
        return snapshot

    def proof(self, token, action, destroyed):
        rows = [row for row in self.records if uint(row["token"]) == token]
        require(len(rows) == 5, "ownership-proof-events-incomplete")
        by_phase = {row["phase"]: row for row in rows}
        guest = self.origin + uint(by_phase["guest_call_start"]["observed_nanos"])
        drop = self.origin + uint(by_phase["raw_owner_dropped"]["observed_nanos"])
        retired = self.origin + uint(rows[-1]["observed_nanos"])
        require(guest <= action <= retired <= destroyed, "ownership-proof-action-not-before-retirement")
        require(drop <= guest if self.variant == "candidate" else action <= drop,
                "ownership-proof-raw-owner-release-boundary")
        return {"guest_call_start_nanos": str(guest), "raw_owner_dropped_nanos": str(drop),
                "invocation_retired_nanos": str(retired), "drop_reason": by_phase["raw_owner_dropped"]["drop_reason"]}
