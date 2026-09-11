"""Original deadline lineage plus real, activation-bound supervisor transfers."""
from tools.optimization_evidence.common import fields, require, uint
from ..budget.observer import Diagnostic as BudgetDiagnostic, instant


class Diagnostic(BudgetDiagnostic):
    def __init__(self, value):
        super().__init__(value, maximum_identities=64, maximum_records=2048)
        self.handoffs = {}
        generations = {}
        for record in self.records.values():
            event = record["observation"]
            if event["kind"] != "transport-handoff":
                continue
            token, slot, generation = uint(record["token"]), uint(event["slot"]), uint(event["generation"])
            require(token not in self.handoffs and generation > generations.get(slot, 0), "recovery-crossed-or-duplicate-handoff")
            generations[slot] = generation
            self.handoffs[token] = {"sequence": record["sequence"], **event}

    @staticmethod
    def check_observation(row):
        if row.get("kind") != "transport-handoff":
            return BudgetDiagnostic.check_observation(row)
        fields(row, "kind observed_at_nanos slot generation cause")
        require(uint(row["slot"]) < 68 and uint(row["generation"]) > 0
                and row["cause"] in ("cancelled", "deadline-exceeded"), "recovery-handoff-identity-or-cause")

    def bind(self, offer, variant):
        # Both references already include #103 precise lineage. Status may stay
        # pending in the old abandoned-owner arm; it is checked separately.
        projected = {key: value for key, value in offer.items() if key != "retained_status"}
        result = super().bind(projected, "candidate")
        token = uint(offer["diagnostic_token"])
        handoff = self.handoffs.get(token)
        require(variant != "control" or handoff is None, "recovery-control-invents-cleanup-handoff")
        if handoff is not None:
            at = instant(handoff["observed_at_nanos"])
            require(uint(offer["dispatch_nanos"]) <= at
                    <= uint(offer["acknowledgement"]["finished_nanos"]), "recovery-handoff-outside-offer")
            records = self.by_token[token]
            winners = [row for row in records if row["kind"] == "terminal-winner"]
            require(len(winners) == 1 and at <= instant(winners[0]["observed_at_nanos"]), "recovery-handoff-after-terminal")
            if handoff["cause"] == "deadline-exceeded":
                limiting = [instant(records[0]["expires_at_nanos"])]
                limiting.extend(instant(row["deadline"]["expires_at_nanos"]) for row in records
                                if row["kind"] == "admitted-ledger" and row["deadline"]["expires_at_nanos"] is not None)
                require(at >= min(limiting), "recovery-handoff-deadline-still-future")
            elif offer["disconnect"] is not None and offer["disconnect"]["aborted"]:
                require(uint(offer["disconnect"]["requested_nanos"]) <= at, "recovery-handoff-before-client-drop")
        result["transport_handoff"] = handoff
        return result

    def ran(self, offer):
        return [row for row in self.by_token[uint(offer["diagnostic_token"])]
                if row["kind"] == "lifecycle-phase" and row["phase"] == "running"]

    def running(self, value, offer, lower, upper):
        if value is None:
            return False
        fields(value, "observed_nanos phase_record_sequence")
        sequence, observed = uint(value["phase_record_sequence"]), uint(value["observed_nanos"])
        require(sequence in self.records, "recovery-running-record-missing")
        record = self.records[sequence]
        event = record["observation"]
        require(record["token"] == offer["diagnostic_token"] and event["kind"] == "lifecycle-phase"
                and event["phase"] == "running" and lower <= observed <= upper
                and instant(event["observed_at_nanos"]) <= observed, "recovery-running-witness-crossed")
        return True

    def acknowledgement(self, value, offer):
        fields(value, "started_nanos finished_nanos terminal_sequence maximum_millis")
        begin, end = uint(value["started_nanos"]), uint(value["finished_nanos"])
        require(value["maximum_millis"] == "250" and uint(offer["completed_nanos"]) <= begin <= end
                <= uint(offer["retained_observed_nanos"]), "recovery-acknowledgement-clock")
        sequence = value["terminal_sequence"]
        if sequence is not None:
            sequence = uint(sequence)
            require(sequence in self.records, "recovery-ack-record-missing")
            record = self.records[sequence]
            require(record["token"] == offer["diagnostic_token"] and record["observation"]["kind"] == "terminal-winner"
                    and instant(record["observation"]["observed_at_nanos"]) <= end, "recovery-ack-crossed-terminal")
        return {"terminal_observed": sequence is not None, "elapsed_nanos": str(end - begin),
                "observation_limit_nanos": "250000000", "observation_overshoot_nanos": str(max(0, end - begin - 250_000_000))}

    def snapshot(self, value, lower, upper):
        """The capture follows its marker and precedes the next offered call.

        Handoff-start precedes queue commit. Only a later terminal publication
        before the lower bound proves that this transferred future was driven.
        This avoids treating the pre-queue event as an atomic counter snapshot.
        """
        minimum, maximum, completed_maximum = 0, 0, 0
        for token, event in self.handoffs.items():
            started = instant(event["observed_at_nanos"])
            terminals = [instant(row["observed_at_nanos"]) for row in self.by_token[token] if row["kind"] == "terminal-winner"]
            minimum += any(started <= ended <= lower for ended in terminals)
            maximum += started <= upper
            completed_maximum += started <= upper and any(ended <= upper for ended in terminals)
        require(minimum <= value["handoffs"] <= maximum and value["completed"] <= completed_maximum,
                "recovery-snapshot-handoffs-not-bound-to-source-events")
