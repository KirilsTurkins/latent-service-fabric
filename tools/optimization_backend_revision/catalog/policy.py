"""Fixed catalog configuration and affirmative zero-guest ownership checks."""
import re

from tools.optimization_backend_revision.cache.accounting import runtime
from tools.optimization_backend_revision.cold.observer import STAGES
from tools.optimization_backend_revision.engine.profile_fields import _COMMON
from tools.optimization_cache_lookup.events import CACHE_FIELDS
from tools.optimization_evidence.common import canonical, fields, require, uint
from tools.phase1_cleanup_shutdown import validate_cleanup_snapshot, validate_cleanup_shutdown
from tools.phase1_compiler_shutdown import COUNTERS, FIELDS, LIMITS, ZERO, validate_compiler_shutdown
from . import model

CACHE_LIMITS = {"maximum_entries": "4", "maximum_source_bytes": "67108864",
                "maximum_metadata_bytes": "16777216", "maximum_compiled_image_bytes": "268435456",
                "maximum_concurrent_preparations": "1"}
COMPILER_LIMITS = dict(zip(LIMITS, (1, 1, 0, 5, 5, 5, 5308416), strict=True))


def owners(configured, joined, released):
    require(all(type(item) is int for item in fields(configured, "invocation control").values())
            and all(type(item) is int for item in fields(joined, "invocation control").values())
            and configured == {"invocation": 2, "control": 1} and joined == {"invocation": 0, "control": 0}
            and all(item is True for item in fields(released, "artifacts deployments").values()), "catalog-owner-joins")


def configuration(value, selected):
    maximum = 16 if selected["mode"] == "allocation" else max(16, model.scales(selected["profile"])[-1])
    expected = {"formatVersion": 1, "dataDirectory": "data", "nodeId": "catalog-comparison", "bind": "127.0.0.1:0",
        "workers": {"runtime": 2, "control": 1},
        "cells": [{"class": "standard", "capacity": 2, "queueCapacity": 3, "maximumMemoryBytes": 67108864}],
        "execution": {"maximumCpuFuel": 10000000000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16384},
        "catalogs": {"releaseEntries": maximum, "releaseIndexBytes": 1073741824,
                     "deployments": maximum, "deploymentStateBytes": 1073741824},
        "cache": {"entries": 4, "sourceBytes": 67108864, "metadataBytes": 16777216,
                  "compiledImageBytes": 268435456, "preparations": 1},
        "retention": {"terminalEntries": 64, "terminalTtlMillis": 60000, "bytes": 20971520},
        "telemetry": {"queueEntries": 256, "retainedEntries": 128, "retainedBytes": 1048576}, "shutdownGraceMillis": 500}
    require(canonical(value) == canonical(expected), "catalog-configured-controls")


def engine(value, identity):
    fields(value, "id wasmtime_version pooling_allocator configuration")
    require(value["id"] == "wasmtime-component-phase-1" and value["wasmtime_version"] == identity["build"]["wasmtime"]
            == "47.0.3" and value["pooling_allocator"] is False, "catalog-effective-engine")
    expected = dict(_COMMON, target=identity["build"]["target"], cpu="host-baseline")
    expected.update({"instance-allocation-strategy": "on_demand", "pooling-maximum-instances": "1",
        "prepared-cache-maximum-entries": "4", "prepared-cache-maximum-source-bytes": "67108864",
        "prepared-cache-maximum-metadata-bytes": "16777216", "prepared-cache-maximum-compiled-image-bytes": "268435456",
        "maximum-concurrent-preparations": "1", "maximum-active-instances": "2", "compiler-workers": "1",
        "maximum-preparation-waiters": "5", "maximum-waiters-per-preparation": "5", "maximum-ready-preparations": "5",
        "maximum-preparation-document-bytes": "5308416", "engine-layout-policy": "wasmtime-47.0.3-bounded-v1",
        "compiler-optimization": "speed", "memory-reservation-bytes": "4294967296",
        "memory-reservation-for-growth-bytes": "2147483648", "memory-guard-bytes": "33554432",
        "memory-may-move": "true", "guard-before-linear-memory": "true", "async-stack-zeroing": "false",
        "pooling-unused-warm-slots": "0", "pooling-decommit-batch-size": "1",
        "pooling-table-keep-resident-bytes": "0", "pooling-async-stack-keep-resident-bytes": "0"})
    config = fields(value["configuration"], " ".join(expected) + " configuration-digest")
    require(all(config[key] == item for key, item in expected.items())
            and isinstance(config["configuration-digest"], str)
            and re.fullmatch(r"blake3:[0-9a-f]{64}", config["configuration-digest"]) is not None,
            "catalog-effective-engine-fields")
    return value


def compiler(value, *, final=False):
    fields(value, " ".join(FIELDS))
    require(all(type(value[key]) is bool for key in ("accepting", "failed")), "catalog-compiler-boolean-state")
    projected = {key: item if key in ("accepting", "failed") else uint(item) for key, item in value.items()}
    require(all(projected[key] == item for key, item in COMPILER_LIMITS.items())
            and all(projected[key] == 0 for key in (*COUNTERS, *ZERO) if key != "workers_live")
            and projected["failed"] is False, "catalog-hidden-preparation-or-compiler-controls")
    if final:
        validate_compiler_shutdown(projected, require)
    else:
        require(projected["accepting"] is True and projected["workers_live"] == 1
                and projected["workers_joined"] == projected["workers_quiescent"] == 0, "catalog-compiler-not-live")
    return projected


def preparation(value, lower, upper, *, final=False):
    fields(value, "collector_started_nanos collector_finished_nanos snapshot")
    start, finish = uint(value["collector_started_nanos"]), uint(value["collector_finished_nanos"])
    require(lower <= start <= finish <= upper, "catalog-preparation-clock")
    snapshot = fields(value["snapshot"], "enabled revision observed_nanos maximum_running_entries maximum_stage_observations "
                      "active_jobs dropped_running_entries dropped_stage_observations compiler stages running recent_stages")
    require(snapshot["enabled"] is True and snapshot["maximum_running_entries"] == "1"
            and snapshot["maximum_stage_observations"] == "256" and snapshot["active_jobs"] == "0"
            and snapshot["dropped_running_entries"] == snapshot["dropped_stage_observations"] == "0"
            and snapshot["running"] == snapshot["recent_stages"] == [], "catalog-hidden-preparation-observation")
    uint(snapshot["revision"])
    uint(snapshot["observed_nanos"])
    require(isinstance(snapshot["stages"], list) and [row.get("stage") for row in snapshot["stages"]] == list(STAGES),
            "catalog-preparation-stage-manifest")
    for row in snapshot["stages"]:
        fields(row, "stage started completed failed elapsed_nanos thread_cpu_samples thread_cpu_unavailable thread_cpu_user_ticks thread_cpu_system_ticks")
        require(all(item == "0" for key, item in row.items() if key != "stage"), "catalog-hidden-preparation-stage")
    compiler(snapshot["compiler"], final=final)
    return start - uint(snapshot["observed_nanos"]), finish - uint(snapshot["observed_nanos"])


def accounting(value, node):
    fields(value, "resident runtimes")
    resident = fields(value["resident"], CACHE_FIELDS)
    require(all(item == CACHE_LIMITS.get(key, "0") for key, item in resident.items()), "catalog-hidden-cache-activity")
    runtime(value["runtimes"], "candidate", zero=True)
    for key, item in resident.items():
        first, *rest = key.split("_")
        require(node["inventory"]["cacheSummary"][first + "".join(word.title() for word in rest)] == item,
                "catalog-cache-node-crossed")


def cleanup(value, *, final=False):
    (validate_cleanup_shutdown if final else validate_cleanup_snapshot)(value, require)
    require(value["capacity"] == 5 and value["failed"] is False
            and all(value[key] == 0 for key in ("reserved", "queued", "running", "handoffs", "completed", "timedOut", "panicked", "fallbacks")),
            "catalog-hidden-cleanup-handoff")
    if not final:
        require(value["accepting"] is True and value["driverAlive"] is True and value["driverJoined"] is False,
                "catalog-cleanup-driver-not-live")
