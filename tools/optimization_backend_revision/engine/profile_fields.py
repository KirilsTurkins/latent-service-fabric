"""Exact compatibility metadata for the fixed #106, 64-bit engine experiment.

These are the configured source policies, not inferred RSS or engine queries.
The caller separately binds the digest to preparation keys and source receipts;
this module checks its syntax without adding a BLAKE3 implementation.
"""
import re

from tools.optimization_evidence.common import require, text


# WasmtimeConfig defaults plus config/runtime.rs and the common engine plan.
# The legacy profile already included the linear-memory residency threshold.
_COMMON = {
    "component-model": "enabled",
    "component-model-async": "enabled",
    "fuel": "enabled",
    "epoch-interruption": "enabled",
    "memory-accounting": "aggregate-linear-memory",
    "ambient-wasi-authority": "none",
    "cpu-feature-policy": "native-host-detection",
    "dispatch-policy": "wasmtime-component-phase-1",
    "copy-on-write-images": "true",
    "prepared-cache-enabled": "true",
    "hostcall-fuel": "configured-bounded-transfer-v1",
    "value-codec": "canonical-json-v1",
    "maximum-component-bytes": "16777216",
    "maximum-memory-bytes": "67108864",
    "maximum-fuel": "10000000000",
    "fuel-async-yield-interval": "10000",
    "maximum-wasm-stack-bytes": "524288",
    "async-stack-bytes": "2097152",
    "prepared-cache-maximum-entries": "8",
    "prepared-cache-maximum-source-bytes": "134217728",
    "prepared-cache-maximum-metadata-bytes": "67108864",
    "prepared-cache-maximum-compiled-image-bytes": "536870912",
    "maximum-artifact-metadata-bytes": "1048576",
    "maximum-concurrent-preparations": "4",
    "maximum-active-instances": "4",
    "maximum-instances-per-store": "128",
    "maximum-memories-per-store": "16",
    "maximum-tables-per-store": "128",
    "maximum-table-elements": "10000",
    "invocation-log-maximum-entries": "8",
    "invocation-log-maximum-bytes": "16384",
    "retained-log-maximum-entries": "256",
    "retained-log-maximum-bytes": "524288",
    "epoch-ticks": "1",
    "epoch-tick-interval-millis": "5",
    "pooling-maximum-component-instance-bytes": "1048576",
    "pooling-maximum-core-instance-bytes": "1048576",
    "pooling-maximum-core-instances-per-component": "4",
    "pooling-maximum-memories-per-component": "2",
    "pooling-maximum-tables-per-component": "2",
    "pooling-linear-memory-keep-resident-bytes": "0",
    "hostcall-fuel-bytes": "131072",
    "compiler-workers": "2",
    "maximum-preparation-waiters": "68",
    "maximum-waiters-per-preparation": "68",
    "maximum-ready-preparations": "68",
    # J * (repository metadata 4MiB + manifest 1MiB + reader allowance 64KiB).
    "maximum-preparation-document-bytes": "21233664",
    "value-max-input-bytes": "1048576",
    "value-max-output-bytes": "1048576",
    "value-max-depth": "32",
    "value-max-nodes": "16384",
    "value-max-string-bytes": "262144",
    "value-max-collection-items": "4096",
    "value-max-type-nodes": "4096",
    "value-max-type-name-bytes": "256",
    "value-max-lifted-bytes": "16777216",
    "value-max-decoded-value-bytes": "16777216",
    "context-exposure-policy": "explicit-allowlists-v1",
    "context-metadata-prefix-count": "1",
    "context-metadata-prefix-0": "guest.",
    "context-claim-key-count": "0",
    "context-baggage-key-count": "0",
}

_PROFILES = {
    "D0": ("on-demand", "speed"),
    "P0": ("pooling", "speed"),
    "D1": ("on-demand", "speed-and-size"),
    "P1": ("pooling", "speed-and-size"),
}


def validate(config, selected, target, cpu):
    """Validate the complete fixed profile and return its declared digest.

    ``selected`` is the validated experiment plan, including ``variant``,
    ``engine_profile_id`` and ``requested_engine``. Other plan fields belong to
    the plan validator. ``target`` and ``cpu`` come from the bound outer profile.
    """
    require(isinstance(selected, dict), "engine-profile-selection")
    variant, profile = selected.get("variant"), selected.get("engine_profile_id")
    require(variant in ("control", "candidate") and isinstance(profile, str)
            and profile in _PROFILES and (variant != "control" or profile == "D0"),
            "engine-profile-selection")
    allocator, optimization = _PROFILES[profile]
    requested = None if variant == "control" else {"allocator": allocator, "optimization": optimization}
    require("requested_engine" in selected and selected["requested_engine"] == requested,
            "engine-profile-request-crossed")
    text(target, 128)
    text(cpu, 256)
    pooling = allocator == "pooling"
    expected = dict(_COMMON, target=target, cpu=cpu)
    expected.update({"instance-allocation-strategy": "pooling" if pooling else "on_demand",
                     "pooling-maximum-instances": "4" if pooling else "1"})
    if variant == "candidate":
        expected.update({
            "engine-layout-policy": "wasmtime-47.0.3-bounded-v1",
            "compiler-optimization": optimization,
            "memory-reservation-bytes": "67108864" if pooling else "4294967296",
            "memory-reservation-for-growth-bytes": "0" if pooling else "2147483648",
            "memory-guard-bytes": "0" if pooling else "33554432",
            "memory-may-move": "true",
            "guard-before-linear-memory": "true",
            "async-stack-zeroing": "false",
            "pooling-unused-warm-slots": "0",
            "pooling-decommit-batch-size": "1",
            "pooling-table-keep-resident-bytes": "0",
            "pooling-async-stack-keep-resident-bytes": "0",
        })
    require(isinstance(config, dict) and len(config) <= 128
            and set(config) == set(expected) | {"configuration-digest"},
            "engine-profile-fields")
    require(all(isinstance(value, str) for value in config.values())
            and all(config[name] == value for name, value in expected.items()),
            "engine-profile-values")
    digest = config["configuration-digest"]
    require(re.fullmatch(r"blake3:[0-9a-f]{64}", digest) is not None, "engine-profile-digest")
    return digest
