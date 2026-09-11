"""Keep cell reuse, affine supervisor ownership and process resources distinct."""
from tools.optimization_evidence.common import require, uint
from tools.phase1_cleanup_shutdown import LIVE, OUTCOMES, validate_cleanup_snapshot


def cleanup(value, variant, previous=None, *, initial=False):
    if variant == "control":
        require(value is None, "recovery-control-cleanup-unavailable")
        return
    validate_cleanup_snapshot(value, require)
    require(value["capacity"] == 68 and value["accepting"] is True and value["driverAlive"] is True
            and value["driverJoined"] is False and value["failed"] is False
            and value["timedOut"] == value["panicked"] == value["fallbacks"] == 0,
            "recovery-supervisor-unhealthy-or-configuration-changed")
    if initial:
        require(all(value[key] == 0 for key in (*LIVE, "handoffs", *OUTCOMES)), "recovery-supervisor-already-used")
    if previous is not None:
        require(all(value[key] >= previous[key] for key in ("handoffs", *OUTCOMES)), "recovery-supervisor-counters-regressed")


def node(sample, variant):
    inventory = sample["inventory"]
    require(inventory["nodeId"] == "transport-recovery" and inventory["cacheSummary"]["maximumEntries"] == "4"
            and inventory["cacheSummary"]["maximumConcurrentPreparations"] == "4"
            and sample["resources"]["descendants"] == []
            and sample["ownership"]["journal"]["maximum_active"] == "68", "recovery-observed-node-controls")
    cells = inventory["cellCapacity"]
    require(len(cells) == 1 and cells[0]["class"] == "standard" and cells[0]["total"] == 4
            and cells[0]["queueCapacity"] == 64, "recovery-cell-pool-changed")
    entries = {row["name"]: row for row in inventory["topology"]["entries"]}
    for name, capacity, kind in (("invocation-cleanup-driver", 1, "task"), ("invocation-cleanup-slots", 68, "continuation")):
        if variant == "control":
            require(name not in entries, "recovery-control-invents-supervisor-topology")
        else:
            row = entries.get(name)
            require(row is not None and row["configuredCount"] == str(capacity) and row["kind"] == kind
                    and row["ownership"] == "node-fixed" and row["activeCount"] is not None
                    and uint(row["activeCount"]) <= capacity, "recovery-supervisor-topology")
            if capacity == 1:
                require(row["activeCount"] == "1", "recovery-driver-not-actually-live")
    return {key: cells[0][key] for key in ("total", "available", "active", "quarantined", "queueDepth")}
