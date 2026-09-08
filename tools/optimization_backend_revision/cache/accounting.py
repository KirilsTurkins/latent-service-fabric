"""Unique runtime conservation, separate from RSS and per-owner ready charges."""
from tools.optimization_evidence.common import fields, require, uint
from tools.optimization_cache_lookup.events import CACHE_FIELDS

COSTS = ("runtimes", "source_bytes", "metadata_bytes", "compiled_image_bytes")
POPULATIONS = ("live", "unpublished", "resident", "evicted_live")
RESIDENT = ("entries", "source_bytes", "metadata_bytes", "compiled_image_bytes")


def runtime(value, variant, zero=False):
    if variant == "control":
        require(value is None, "cache-control-fabricated-runtime-ledger")
        return None
    fields(value, " ".join(POPULATIONS))
    for name in POPULATIONS:
        row = fields(value[name], " ".join(COSTS))
        for item in row.values():
            uint(item)
        if row["runtimes"] == "0":
            require(all(item == "0" for item in row.values()), "cache-runtime-cost-without-object")
    for key in COSTS:
        require(uint(value["live"][key]) == sum(uint(value[name][key]) for name in POPULATIONS[1:]), "cache-runtime-conservation")
    if zero:
        require(all(item == "0" for row in value.values() for item in row.values()), "cache-runtime-retained-after-shutdown")
    return value


def check(value, variant, idle=True):
    fields(value, "resident runtimes")
    resident = fields(value["resident"], CACHE_FIELDS)
    for item in resident.values():
        uint(item)
    require(resident["maximum_entries"] == "4" and resident["maximum_source_bytes"] == "134217728"
            and resident["maximum_metadata_bytes"] == "67108864" and resident["maximum_compiled_image_bytes"] == "536870912"
            and resident["maximum_concurrent_preparations"] == "4", "cache-accounting-controls")
    for name, limit in (("entries", "maximum_entries"), ("source_bytes", "maximum_source_bytes"),
                        ("metadata_bytes", "maximum_metadata_bytes"), ("compiled_image_bytes", "maximum_compiled_image_bytes"),
                        ("preparing", "maximum_concurrent_preparations")):
        require(uint(resident[name]) <= uint(resident[limit]), "cache-resident-limit-exceeded")
    if resident["entries"] == "0":
        require(all(resident[name] == "0" for name in RESIDENT), "cache-resident-bytes-without-entry")
    if idle:
        require(all(resident[name] == "0" for name in ("preparing", "preparing_source_bytes", "preparing_metadata_bytes")),
                "cache-checkpoint-preparation-not-drained")
    unique = runtime(value["runtimes"], variant)
    if unique is not None:
        require(unique["resident"]["runtimes"] == resident["entries"]
                and all(unique["resident"][name] == resident[name] for name in COSTS[1:]), "cache-resident-ledger-disagrees")
        if idle:
            require(unique["unpublished"]["runtimes"] == "0", "cache-unpublished-owner-at-idle")
    return value


def checkpoint(label, value, variant):
    check(value, variant)
    counts = {"empty": (0, 0, 0), "ownership-empty": (0, 0, 0),
              "held-two-ready": (1, 1, 0), "held-ready-and-active": (1, 1, 0),
              "evicted-held-ready-and-active": (5, 4, 1), "evicted-held-ready": (5, 4, 1),
              "resident-new-and-evicted-old": (5, 4, 1), "released-old-ready": (4, 4, 0),
              "ownership-complete": (4, 4, 0)}
    if label in counts:
        require(uint(value["resident"]["entries"]) == counts[label][1], "cache-checkpoint-residency")
    if variant == "candidate":
        unique = value["runtimes"]
        if label in counts:
            require(tuple(uint(unique[key]["runtimes"]) for key in ("live", "resident", "evicted_live")) == counts[label],
                    "cache-held-owner-count")
        elif not label.startswith("held-"):
            require(unique["evicted_live"]["runtimes"] == "0", "cache-idle-evicted-owner-not-released")


def same_resident(before, after):
    require(all(before["resident"][name] == after["resident"][name] for name in RESIDENT), "cache-failed-refill-evicted-resident")


def sampled(label, value, node):
    """Bind the drained accounting capture to the adjacent actual node probe."""
    summary = node["inventory"]["cacheSummary"]
    require(summary["available"] is True, "cache-resident-sample-unavailable")
    for name, item in value["resident"].items():
        first, *rest = name.split("_")
        camel = first + "".join(word.title() for word in rest)
        require(summary[camel] == item, "cache-accounting-sample-disagrees")
    rows = [row for row in node["inventory"]["topology"]["entries"] if row["name"] == "prepared-instance-reservations"]
    active = "1" if label in ("held-ready-and-active", "evicted-held-ready-and-active") else "0"
    require(len(rows) == 1 and rows[0]["configuredCount"] == "4" and rows[0]["activeCount"] == active,
            "cache-materialization-owner-not-sampled")


def ownership(checkpoints, variant):
    if variant == "control":
        return
    old = checkpoints["held-two-ready"]["runtimes"]["resident"]
    for label in ("evicted-held-ready-and-active", "evicted-held-ready", "resident-new-and-evicted-old"):
        require(checkpoints[label]["runtimes"]["evicted_live"] == old, "cache-held-runtime-cost-crossed")
    require(checkpoints["held-ready-and-active"]["runtimes"] == checkpoints["held-two-ready"]["runtimes"],
            "cache-materialization-double-charged-runtime")
    before, after = checkpoints["resident-new-and-evicted-old"], checkpoints["released-old-ready"]
    require(before["resident"] == after["resident"] and before["runtimes"]["resident"] == after["runtimes"]["resident"],
            "cache-old-pin-refund-changed-new-resident")
    for key in COSTS:
        require(uint(before["runtimes"]["live"][key]) - uint(after["runtimes"]["live"][key]) == uint(old[key]),
                "cache-old-pin-refund-not-exact")
