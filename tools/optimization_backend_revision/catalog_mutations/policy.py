"""Actual catalog work receipts, separate from native compiler/cache ownership."""
from tools.optimization_backend_revision.catalog.policy import (
    accounting, cleanup, compiler, engine, owners, preparation,
)
from tools.optimization_evidence.common import canonical, fields, require, uint

WORK_COUNTS = (
    "normalization_deployment_encodes compiler_calls compiler_completed compiler_failed "
    "compiler_deployment_encodes revision_identity_encodes contract_schema_encodes "
    "record_derivations record_payload_reuses record_derivation_reuses scopes_staged scope_content_reuses "
    "route_memberships_staged route_memberships_remapped encoder_calls encoder_completed encoder_failed "
    "persistence_deployment_encodes payload_serializations envelope_serializations load_payload_serializations "
    "payload_buffer_bytes payload_capacity_max encoded_buffer_bytes encoded_capacity_max "
    "load_payload_buffer_bytes load_payload_capacity_max stage_calls stage_requested_bytes stage_write_failures "
    "stage_completed stage_synced_bytes stage_sync_failures stage_written_bytes"
).split()
WORK_OPERATIONS = ("open", "apply-many", "apply-versioned", "delete-versioned", "compile-snapshot", "publish-snapshot")


def configuration(value, selected):
    maximum = max(16, selected["populated_size"])
    expected = {"formatVersion": 1, "dataDirectory": "data", "nodeId": "catalog-mutation-comparison", "bind": "127.0.0.1:0",
        "workers": {"runtime": 2, "control": 1},
        "cells": [{"class": "standard", "capacity": 2, "queueCapacity": 3, "maximumMemoryBytes": 67108864}],
        "execution": {"maximumCpuFuel": 10000000000, "maximumWallTimeMillis": 5000, "maximumLogBytes": 16384},
        "catalogs": {"releaseEntries": maximum, "releaseIndexBytes": 1073741824,
                     "deployments": maximum, "deploymentStateBytes": 1073741824},
        "cache": {"entries": 4, "sourceBytes": 67108864, "metadataBytes": 16777216,
                  "compiledImageBytes": 268435456, "preparations": 1},
        "retention": {"terminalEntries": 64, "terminalTtlMillis": 60000, "bytes": 20971520},
        "telemetry": {"queueEntries": 256, "retainedEntries": 128, "retainedBytes": 1048576}, "shutdownGraceMillis": 500}
    require(canonical(value) == canonical(expected), "catalog-mutation-configured-controls")


def work_counts(value):
    fields(value, " ".join(WORK_COUNTS))
    result = {key: None if key == "stage_written_bytes" and item is None else uint(item)
              for key, item in value.items()}
    require(all(item is None or item <= 2**64 - 1 for item in result.values()), "catalog-mutation-work-u64-bound")
    return result


def work_receipt(value):
    fields(value, "sequence operation outcome compiled_generation overflowed counts")
    require(0 < uint(value["sequence"]) <= 2**64 - 1 and value["operation"] in WORK_OPERATIONS
            and value["outcome"] in ("returned-ok", "returned-error", "owner-dropped")
            and value["overflowed"] is False, "catalog-mutation-work-receipt")
    if value["compiled_generation"] is not None:
        require(uint(value["compiled_generation"]) <= 2**64 - 1, "catalog-mutation-work-generation")
    work_counts(value["counts"])
    return value


def work_snapshot(value, *, sequence=None):
    fields(value, "started finished active maximum_active overflowed poisoned last")
    started, finished = uint(value["started"]), uint(value["finished"])
    require(started == finished <= 2**64 - 1 and uint(value["active"]) == 0
            and uint(value["maximum_active"]) == (1 if started else 0)
            and value["overflowed"] is value["poisoned"] is False,
            "catalog-mutation-work-overlap-or-coverage")
    if sequence is not None:
        require(type(sequence) is int and started == sequence, "catalog-mutation-work-sequence")
    if started == 0:
        require(value["last"] is None, "catalog-mutation-work-empty-receipt")
    else:
        work_receipt(value["last"])
        require(uint(value["last"]["sequence"]) == started, "catalog-mutation-work-last-sequence")
    return value


def work_operation(before, after, operation, generation, *, normalization=None):
    work_snapshot(before)
    work_snapshot(after, sequence=uint(before["started"]) + 1)
    receipt = after["last"]
    require(operation in WORK_OPERATIONS and receipt["operation"] == operation
            and receipt["outcome"] == "returned-ok" and type(generation) is int and generation >= 0
            and receipt["compiled_generation"] == str(generation), "catalog-mutation-work-operation-association")
    counts = work_counts(receipt["counts"])
    require(counts["compiler_calls"] == counts["compiler_completed"]
            and counts["encoder_calls"] == counts["encoder_completed"]
            and all(counts[key] == 0 for key in ("compiler_failed", "encoder_failed", "stage_write_failures", "stage_sync_failures"))
            and counts["stage_written_bytes"] is not None, "catalog-mutation-work-success-counters")
    if normalization is not None:
        require(type(normalization) is int and counts["normalization_deployment_encodes"] == normalization,
                "catalog-mutation-work-normalization-count")
    return counts
