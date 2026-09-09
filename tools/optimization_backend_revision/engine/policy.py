"""Actual engine metadata, bounded native ownership and configuration controls."""
from tools.optimization_evidence.common import fields, require, text, uint
from tools.optimization_cache_lookup.events import CACHE_FIELDS
from tools.phase1_cleanup_shutdown import validate_cleanup_snapshot
from ..cache.accounting import COSTS, runtime

NATIVE = "active_invocations live_stores live_host_states live_component_instances live_temporary_buffers live_cancellation_probes stores_created"


def native(value, live=None):
    fields(value, NATIVE)
    for item in value.values():
        uint(item)
    require(all(uint(value[key]) <= 4 for key in NATIVE.split() if key != "stores_created"), "engine-native-capacity")
    if live is not None:
        require(all(uint(value[key]) == live for key in NATIVE.split() if key != "stores_created"), "engine-native-not-drained")
    return value


def configuration(value, selected):
    fields(value, "formatVersion dataDirectory nodeId bind workers cells execution catalogs cache retention telemetry shutdownGraceMillis",
           "engine")
    require(value["formatVersion"] == 1 and value["dataDirectory"] == "data"
            and value["nodeId"] == "engine-comparison" and value["bind"] == "127.0.0.1:0", "engine-configuration-identity")
    expected = {
        "workers": {"runtime": 2, "control": 4},
        "cells": [{"class": "standard", "capacity": 4, "queueCapacity": 64, "maximumMemoryBytes": 67_108_864}],
        "execution": {"maximumCpuFuel": 10_000_000_000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16384},
        "catalogs": {"releaseEntries": 16, "releaseIndexBytes": 16_777_216, "deployments": 16, "deploymentStateBytes": 16_777_216},
        "cache": {"entries": 8, "sourceBytes": 134_217_728, "metadataBytes": 67_108_864,
                  "compiledImageBytes": 536_870_912, "preparations": 4, "compilerWorkers": 2},
        "retention": {"terminalEntries": 1024, "terminalTtlMillis": 60_000, "bytes": 536_870_912},
        "telemetry": {"queueEntries": 256, "retainedEntries": 128, "retainedBytes": 1_048_576}, "shutdownGraceMillis": 1000}
    require(all(value[name] == expected_value for name, expected_value in expected.items()), "engine-fixed-capacity-controls")
    require(("engine" not in value) if selected["variant"] == "control" else value.get("engine") == selected["requested_engine"],
            "engine-default-omission-or-request-crossed")


def profile(value, selected, identity):
    fields(value, "id wasmtime_version target_triple cpu_feature_set pooling_allocator copy_on_write_images "
                  "async_support fuel_enabled epoch_interruption_enabled configuration effective_policy")
    pooling = selected["engine_profile_id"].startswith("P")
    optimization = "speed-and-size" if selected["engine_profile_id"].endswith("1") else "speed"
    require(value["id"] == "wasmtime-component-phase-1" and value["wasmtime_version"] == identity["build"]["wasmtime"]
            == "47.0.3" and value["cpu_feature_set"] == "host-baseline"
            and value["pooling_allocator"] is pooling
            and all(value[name] is True for name in ("copy_on_write_images", "async_support", "fuel_enabled", "epoch_interruption_enabled")),
            "engine-actual-profile-crossed")
    text(value["target_triple"], 128)
    require(value["target_triple"] == identity["build"]["target"], "engine-profile-build-target-crossed")
    config = value["configuration"]
    require(isinstance(config, dict) and 1 <= len(config) <= 128, "engine-configuration-metadata-bound")
    for name, item in config.items():
        text(name, 128)
        text(item, 4096, empty=True)
    projection = {"source": "common-source-projection", "allocator": "pooling" if pooling else "on_demand",
                  "optimization": optimization, "optimization_source": "pinned-wasmtime-47.0.3-default" if selected["variant"] == "control"
                  else "requested-config-bound-to-candidate-profile", "memory_reservation_bytes": 67_108_864 if pooling else 4_294_967_296,
                  "memory_guard_bytes": 0 if pooling else 33_554_432, "memory_reservation_for_growth_bytes": 0 if pooling else 2_147_483_648,
                  "layout_source": "existing-source-override" if pooling else "pinned-wasmtime-47.0.3-default",
                  "async_stack_zeroing": False, "memory_may_move": True, "guard_before_linear_memory": True,
                  "pooling_maximum_instances": 4 if pooling else 1, "maximum_active_instances": 4,
                  "pooling_unused_warm_slots": "0" if pooling else None, "pooling_decommit_batch_size": "1" if pooling else None,
                  "pooling_keep_resident_bytes": "0" if pooling else None, "maximum_memory_bytes": 67_108_864,
                  "async_stack_bytes": 2_097_152, "maximum_wasm_stack_bytes": 524_288, "fuel_async_yield_interval": "10000"}
    projection = {key: str(item) if type(item) is int else item for key, item in projection.items()}
    require(value["effective_policy"] == projection, "engine-source-projection-crossed")
    from .profile_fields import validate
    return validate(config, selected, value["target_triple"], value["cpu_feature_set"])


def accounting(value, node=None, empty=False):
    fields(value, "resident runtimes")
    resident = fields(value["resident"], CACHE_FIELDS)
    for item in resident.values():
        uint(item)
    limits = {"maximum_entries": "8", "maximum_source_bytes": "134217728", "maximum_metadata_bytes": "67108864",
              "maximum_compiled_image_bytes": "536870912", "maximum_concurrent_preparations": "4"}
    require(all(resident[name] == item for name, item in limits.items()), "engine-cache-controls")
    for name in ("entries", "source_bytes", "metadata_bytes", "compiled_image_bytes"):
        require(uint(resident[name]) <= uint(resident["maximum_" + name]), "engine-cache-bound")
    require(all(resident[key] == "0" for key in ("preparing", "preparing_source_bytes", "preparing_metadata_bytes")), "engine-cache-not-drained")
    unique = runtime(value["runtimes"], "candidate")
    require(unique["resident"]["runtimes"] == resident["entries"]
            and all(unique["resident"][key] == resident[key] for key in COSTS[1:])
            and unique["unpublished"]["runtimes"] == unique["evicted_live"]["runtimes"] == "0", "engine-cache-unique-owner-crossed")
    if empty:
        require(resident["entries"] == resident["hits"] == resident["misses"] == "0", "engine-hidden-cache-warmup")
    if node is not None:
        summary = node["inventory"]["cacheSummary"]
        for key, item in resident.items():
            first, *rest = key.split("_")
            require(summary[first + "".join(part.title() for part in rest)] == item, "engine-cache-sample-crossed")
    return value


def cleanup(value):
    validate_cleanup_snapshot(value, require)
    require(value["capacity"] == 68 and value["failed"] is False
            and value["timedOut"] == value["panicked"] == value["fallbacks"] == 0, "engine-cleanup-controls-or-failure")
