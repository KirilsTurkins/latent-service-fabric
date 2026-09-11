"""Bind two trusted native resource details without changing public redaction."""
from tools.optimization_evidence.common import fields, require, text, uint

FIELDS = ("source capture_started_nanos capture_finished_nanos tenant activation_id phase terminal_state "
          "terminal_at_unix_millis release_digest revision_id route_generation code detail_count kind cell_id "
          "detail_field_count consumption")


def validate(row, expected, elapsed):
    fault = row["native_fault"]
    required = expected["phase"] == "functional" and expected["index"] in (10, 12)
    if not required:
        require(fault is None, "engine-native-fault-outside-fixed-cases")
        return
    fields(fault, FIELDS)
    require(fault["source"] == "tenant-scoped-local-manager"
            and fault["tenant"] == row["target"]["tenant"] and fault["activation_id"] == row["activation_id"]
            and all(fault[key] == row["response"][key] for key in
                    ("release_digest", "revision_id", "route_generation", "code", "consumption")),
            "engine-native-fault-receipt-crossed")
    require(fault["phase"] == "running" and fault["terminal_state"] == "resource_exhausted"
            and fault["code"] == "resource-exhausted" and fault["detail_count"] == fault["detail_field_count"] == "1"
            and fault["kind"] == ("activation.fuel-exhausted" if expected["index"] == 10 else "activation.memory-exhausted")
            and row["response"]["details"] == [], "engine-native-fault-kind-or-redaction-crossed")
    text(fault["cell_id"], 512)
    uint(fault["terminal_at_unix_millis"])
    require(uint(row["completed_nanos"]) <= uint(fault["capture_started_nanos"])
            <= uint(fault["capture_finished_nanos"]) <= elapsed, "engine-native-fault-capture-clock")


def status(row, command):
    fault = row["native_fault"]
    if fault is not None:
        require(uint(fault["capture_finished_nanos"]) <= uint(command["started_nanos"])
                and all(fault[key] == command["response"][key] for key in
                        ("activation_id", "phase", "terminal_state", "code", "consumption")),
                "engine-native-fault-status-crossed")
