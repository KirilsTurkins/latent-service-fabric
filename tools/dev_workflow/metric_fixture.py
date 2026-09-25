"""Closed production-metric descriptors and bounded, value-only export receipts."""
from __future__ import annotations

import re
import sys

from .common import members, require

PROVIDER = ("latent:telemetry/custom@0.1.0", "custom-metrics-v1", "emit-metric", "telemetry")
SERVICE = "runtime-host-metrics"
COUNTERS = ("attempted", "accepted", "invalid", "exhausted", "unavailable", "queuedBytes",
            "capturedRecords", "sinkEvictedEntries", "sinkDroppedOversized")


def name(value, maximum=64):
    return (isinstance(value, str) and 1 <= len(value) <= maximum
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", value)
            and not value.lower().startswith(("latent", "otel", "host")))


def validate(value):
    require(isinstance(value, list) and 1 <= len(value) <= 16, "development-metric-descriptor-limit")
    names = set()
    for entry in value:
        members(entry, {"name", "kind", "unit", "labels", "histogramUpperBounds"})
        require(name(entry["name"]) and entry["name"] not in names
                and isinstance(entry["kind"], str) and entry["kind"] in {"counter", "up-down-counter", "gauge", "histogram"}
                and isinstance(entry["unit"], str) and re.fullmatch(r"[A-Za-z0-9_.\-/]{1,16}", entry["unit"]),
                "development-metric-descriptor-invalid")
        names.add(entry["name"])
        bounds = entry["histogramUpperBounds"]
        require(isinstance(bounds, list) and len(bounds) <= 16
                and (entry["kind"] == "histogram" or not bounds)
                and all(type(item) in (int, float) and -sys.float_info.max <= item <= sys.float_info.max for item in bounds)
                and all(left < right for left, right in zip(bounds, bounds[1:])),
                "development-metric-histogram-invalid")
        require(isinstance(entry["labels"], list) and len(entry["labels"]) <= 8,
                "development-metric-label-limit")
        keys = set()
        for label in entry["labels"]:
            members(label, {"key", "values"})
            values = label["values"]
            require(name(label["key"], 32) and label["key"] not in keys
                    and isinstance(values, list) and 1 <= len(values) <= 16
                    and all(isinstance(item, str) and re.fullmatch(r"[!-~]{1,64}", item) for item in values)
                    and len(set(values)) == len(values), "development-metric-label-invalid")
            keys.add(label["key"])
    return value


def initialized(providers):
    actual = (providers or {}).get("metrics", {})
    return (actual.get("capability") == PROVIDER[0] and actual.get("profile") == PROVIDER[1]
            and actual.get("service") == SERVICE and actual.get("configurationEpoch") == "1")


def observation(value):
    """Reject arbitrary diagnostic fields, labels, malformed values and unbounded records."""
    members(value, {*COUNTERS, "retired", "truncated", "records"}, {"schemaVersion"})
    require(value.get("schemaVersion", "latent.standalone.metrics.v1") == "latent.standalone.metrics.v1"
            and all(type(value[key]) is int and 0 <= value[key] <= 18446744073709551615 for key in COUNTERS)
            and type(value["retired"]) is bool and type(value["truncated"]) is bool
            and isinstance(value["records"], list) and len(value["records"]) <= 16,
            "bounded-metric-observation-required")
    for record in value["records"]:
        members(record, {"name", "unit", "valueBits"})
        require(isinstance(record["name"], str) and record["name"].startswith("latent.application.")
                and name(record["name"].removeprefix("latent.application.")) and isinstance(record["unit"], str)
                and re.fullmatch(r"[A-Za-z0-9_.\-/]{1,16}", record["unit"])
                and isinstance(record["valueBits"], str) and re.fullmatch(r"[0-9a-f]{16}", record["valueBits"]),
                "bounded-metric-record-required")
    require(value["accepted"] <= value["attempted"] and value["capturedRecords"] >= len(value["records"])
            and value["truncated"] == (value["capturedRecords"] > len(value["records"])),
            "metric-observation-association")
    return {key: value[key] for key in (*COUNTERS, "retired", "truncated", "records")}


def reclaimed(value):
    selected = observation(value)
    require(selected["retired"] and selected["queuedBytes"] == 0
            and not selected["truncated"] and selected["sinkEvictedEntries"] == 0
            and selected["sinkDroppedOversized"] == 0
            and selected["accepted"] == selected["capturedRecords"],
            "metric-export-and-cleanup-unconfirmed")
    return selected
