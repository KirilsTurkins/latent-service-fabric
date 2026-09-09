"""Shared direct-invocation oracles with explicit logical resource scopes."""
import json

from tools.optimization_evidence.common import digest, fields, integer, require, sha256, text, uint
from tools.optimization_evidence.workload import MEDIA
from tools.optimization_cache_lookup.events import CACHE_FIELDS
from tools.phase1_paired.common import TIMINGS
from ..cache.accounting import runtime

RESOURCES = ("active_invocations", "live_stores", "live_host_states", "live_component_instances",
             "live_temporary_buffers", "live_cancellation_probes", "stores_created")
ZERO_BUDGET = ("child_calls", "outbound_requests", "state_read_bytes", "state_write_bytes",
               "blob_read_bytes", "blob_write_bytes", "effect_count")
BUDGET = dict(cpu_fuel="10000000000", memory_bytes="67108864", wall_time_limit_millis="1000",
              log_bytes="16384", **dict.fromkeys(ZERO_BUDGET, "0"))
CONSUMPTION = ("cpu_fuel", "peak_memory_bytes", "wall_time_micros", "log_bytes", *ZERO_BUDGET)


def decimal(value):
    if type(value) is int:
        integer(value, 0, 2**64-1)
        return str(value)
    if isinstance(value, dict):
        return {key: decimal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimal(item) for item in value]
    return value


def resources(value, stores, *, pending=False):
    fields(value, " ".join(RESOURCES))
    for item in value.values():
        uint(item)
    require(uint(value["stores_created"]) == stores, "ownership-fresh-store-population")
    if pending:
        require(value["active_invocations"] == value["live_stores"] == value["live_host_states"]
                == value["live_component_instances"] == value["live_cancellation_probes"] == "1",
                "ownership-pending-native-owners-not-live")
    else:
        require(all(value[key] == "0" for key in RESOURCES[:-1]), "ownership-native-owners-not-reclaimed")
    return value


def cache(value, entries, components, *, hits=0):
    value = decimal(value)
    fields(value, "resident runtimes")
    row = fields(value["resident"], CACHE_FIELDS)
    for item in row.values():
        uint(item)
    limits = {"maximum_entries": "4", "maximum_source_bytes": "67108864", "maximum_metadata_bytes": "8388608",
              "maximum_compiled_image_bytes": "134217728", "maximum_concurrent_preparations": "4"}
    require(all(row[key] == expected for key, expected in limits.items()), "ownership-cache-config-changed")
    require(uint(row["entries"]) == uint(row["misses"]) == entries
            and uint(row["hits"]) == hits and row["evictions"] == row["invalidations"] == row["preparing"]
            == row["preparing_source_bytes"] == row["preparing_metadata_bytes"] == "0",
            "ownership-unexpected-preparation-or-cache-operation")
    require(uint(row["source_bytes"]) == sum(uint(component["bytes"]) for component in components),
            "ownership-cache-component-charge-crossed")
    for name in ("source_bytes", "metadata_bytes", "compiled_image_bytes"):
        require(uint(row[name]) <= uint(row["maximum_" + name]) and (uint(row[name]) > 0) == bool(entries),
                "ownership-cache-byte-bound")
    unique = runtime(value["runtimes"], "candidate")
    require(unique["unpublished"]["runtimes"] == unique["evicted_live"]["runtimes"] == "0"
            and uint(unique["resident"]["runtimes"]) == entries
            and all(unique["resident"][key] == row[key] for key in ("source_bytes", "metadata_bytes", "compiled_image_bytes")),
            "ownership-runtime-ledger-crossed")
    return value


def consumption(value):
    fields(value, " ".join(CONSUMPTION))
    result = {key: uint(item) for key, item in value.items()}
    require(result["cpu_fuel"] <= 10_000_000_000 and result["peak_memory_bytes"] <= 67_108_864
            and result["log_bytes"] <= 16_384 and all(result[key] == 0 for key in ZERO_BUDGET),
            "ownership-consumption-exceeds-grant")
    return result


def timing(value, elapsed, *, optional=False):
    if value is None:
        require(optional, "ownership-invocation-timing-missing")
        return None
    fields(value, " ".join(TIMINGS))
    result = {key: uint(item) for key, item in value.items()}
    require(result["backend_total_micros"] * 1000 <= elapsed + 1000
            and result["host_call_micros"] <= result["guest_call_micros"], "ownership-backend-timing-outside-invocation")
    return result


def prepared(value, fixture, profile):
    fields(value, "backend opaque_handle metadata key")
    text(value["opaque_handle"])
    require(isinstance(value["metadata"], dict) and len(value["metadata"]) <= 64, "ownership-prepared-metadata-bound")
    for key, item in value["metadata"].items():
        text(key)
        text(item, 16384, empty=True)
    key = fields(value["key"], "release engine_version engine_configuration_digest target_triple cpu_feature_set")
    require(value["backend"] == profile["id"] and key["release"] == fixture["component"]["sha256"]
            and key["engine_version"] == profile["wasmtime_version"]
            and key["engine_configuration_digest"] == profile["configuration"]["configuration-digest"]
            and key["target_triple"] == profile["target_triple"] and key["cpu_feature_set"] == profile["cpu_feature_set"],
            "ownership-prepared-release-or-engine-crossed")
    return value


def output(row, payload):
    result = fields(row["result"], "outcome code output consumption cleanup")
    require(result["outcome"] == "success" and result["code"] is None
            and result["cleanup"] == {"disposition": "reusable", "reason": None}, "ownership-normal-result-not-successful-reusable")
    consumption(result["consumption"])
    value = fields(result["output"], "sha256 bytes media_type utf8")
    digest(value["sha256"])
    size = uint(value["bytes"])
    require(value["media_type"] == MEDIA and size <= 131072, "ownership-output-media-or-byte-bound")
    if value["utf8"] is not None:
        encoded = text(value["utf8"], 16384, empty=True).encode()
        require(len(encoded) == size and sha256(encoded) == value["sha256"], "ownership-output-bytes-not-bound")
    else:
        require(size > 16384, "ownership-small-output-erased")
    if not row["shape"].startswith("context-"):
        require(value["sha256"] == sha256(payload) and size == len(payload), "ownership-echo-output-changed")
        return
    require(value["utf8"] is not None, "ownership-context-output-erased")
    values = json.loads(value["utf8"])
    require(isinstance(values, list) and len(values) == 1, "ownership-context-output-frame")
    value = fields(values[0], "activation root parent principal trace deadline metadata remaining")
    identifier = row["activation_id"]
    require(value["activation"] == value["root"] == identifier and value["parent"] == {"some": identifier}
            and value["deadline"] == {"some": row["deadline_unix_millis"]}
            and value["metadata"] == [["guest.visible", identifier]], "ownership-visible-context-lineage")
    require(value["principal"] == {"subject": identifier, "kind": "service", "tenant": {"some": "tests"},
                                   "service": {"some": "ownership-caller"}, "claims": [["role", "reader"]]},
            "ownership-context-claims-or-principal")
    require(value["trace"] == {"trace-id": "11111111111111111111111111111111", "span-id": "1111111111111111",
                               "trace-flags": 1, "baggage": [["locale", "en"]]}, "ownership-context-trace-or-baggage")
    remaining = fields(value["remaining"], "cpu-fuel memory-bytes wall-time-limit-millis log-bytes "
                       + " ".join(name.replace("_", "-") for name in ZERO_BUDGET))
    for name, grant in BUDGET.items():
        item = remaining[name.replace("_", "-")]
        if name == "wall_time_limit_millis":
            fields(item, "some")
            item = item["some"]
        observed = integer(item, 0, 2**32-1) if name in ("child_calls", "outbound_requests", "effect_count") else uint(item)
        require(observed <= uint(grant), "ownership-visible-budget-exceeds-actual-grant")
