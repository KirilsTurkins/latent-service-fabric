"""Measurement-local virtual/resident observations with explicit availability."""
from tools.optimization_evidence.common import fields, require, uint

STATUS = ("vm_size_bytes", "vm_peak_bytes", "rss_bytes", "vm_hwm_bytes")
ROLLUP = ("pss_bytes", "private_clean_bytes", "private_dirty_bytes", "shared_clean_bytes", "shared_dirty_bytes")
REASONS = ("unsupported-platform", "missing", "permission-denied", "oversized",
           "invalid-format", "missing-field", "identity-unavailable")


def memory(value, expected_checkpoint, owner, lower, upper, *, operating_system="Linux"):
    fields(value, "schema checkpoint collector_started_nanos collector_finished_nanos "
                  "process_id start_time_ticks status smaps_rollup")
    require(value["schema"] == "latent.optimization.engine-memory.v1"
            and value["checkpoint"] == expected_checkpoint, "engine-memory-checkpoint")
    start, finish = uint(value["collector_started_nanos"]), uint(value["collector_finished_nanos"])
    require(lower <= start <= finish <= upper, "engine-memory-clock-crossed")
    identity_missing = value["process_id"] is None or value["start_time_ticks"] is None
    require((value["process_id"] is None) == (value["start_time_ticks"] is None), "engine-memory-partial-identity")
    unsupported = operating_system != "Linux"
    require(not unsupported or identity_missing, "engine-memory-native-identity-on-unsupported-platform")
    if not identity_missing:
        require((uint(value["process_id"]), uint(value["start_time_ticks"])) == owner,
                "engine-memory-process-crossed")
    result = {}
    for name, source, keys in (("status", "proc-self-status", STATUS),
                               ("smaps_rollup", "proc-self-smaps-rollup", ROLLUP)):
        section = fields(value[name], "source values")
        require(section["source"] == source, "engine-memory-source")
        entries = fields(section["values"], " ".join(keys))
        for key, row in entries.items():
            fields(row, "value_bytes reason")
            if row["value_bytes"] is None:
                require(row["reason"] in REASONS, "engine-memory-unavailable-reason")
            else:
                require(row["reason"] is None, "engine-memory-value-with-reason")
                uint(row["value_bytes"])
            reason = "unsupported-platform" if unsupported else "identity-unavailable"
            require(not identity_missing or row == {"value_bytes": None, "reason": reason},
                    "engine-memory-unbound-value")
            require(unsupported or row["reason"] != "unsupported-platform", "engine-memory-crossed-platform-reason")
            result[key] = row["value_bytes"]
    for peak, current in (("vm_peak_bytes", "vm_size_bytes"), ("vm_hwm_bytes", "rss_bytes")):
        if result[peak] is not None and result[current] is not None:
            require(uint(result[peak]) >= uint(result[current]), "engine-memory-high-water-below-current")
    return result


def summarize(samples):
    result = {}
    for name in (*STATUS, *ROLLUP):
        observed = [uint(row[name]) for row in samples if row[name] is not None]
        result[name] = {"observed": len(observed), "unavailable": len(samples) - len(observed),
                        "minimum": str(min(observed)) if observed else None,
                        "maximum": str(max(observed)) if observed else None,
                        "last": samples[-1][name] if samples else None}
    return result
