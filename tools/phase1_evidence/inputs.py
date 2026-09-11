"""Bind benchmark payload framing and effective budgets to reported identities."""

from __future__ import annotations

from typing import Any

from .common import decode, digest, fields, require, sha256, text, uint


def benchmark_input(value: Any, identity: dict[str, Any]) -> None:
    fields(value, "component_digest component_size_bytes manifest_sha256 contract_metadata_sha256 tenant service contract function inputs budget preparation_key backend_options boundary_version rpc_boundary")
    for key in ("component_digest", "manifest_sha256", "contract_metadata_sha256"):
        digest(value[key])
    require(any(item["sha256"] == value["component_digest"] and item["bytes"] == value["component_size_bytes"]
                for item in identity["fixtures"]), "benchmark-component-identity-mismatch")
    require(value["contract"] == "examples:echo/api@0.1.0" and value["function"] == "echo", "invalid-benchmark-export")
    require(value["tenant"] == "examples" and value["service"] == "measurement-echo", "invalid-benchmark-scope")
    require(value["boundary_version"] == "wasmtime-component-call-includes-canonical-post-return-v1"
            and value["rpc_boundary"] == "persistent-loopback-tonic-invoke-round-trip-v1", "invalid-benchmark-boundary-version")
    inputs = fields(value["inputs"], "cold_first_rpc warm_rpc")
    for name, expected in (("cold_first_rpc", "phase0 retained first echo"), ("warm_rpc", "phase0 warm echo")):
        frame = fields(inputs[name], "payload_sha256 payload_byte_length media_type payload_utf8")
        payload = text(frame["payload_utf8"], 4096).encode("utf-8")
        require(frame["payload_sha256"] == sha256(payload) and uint(frame["payload_byte_length"]) == len(payload), "benchmark-payload-identity-mismatch")
        require(frame["media_type"] == "application/vnd.latent.wit-values.v1+json" and decode(payload) == [expected], "benchmark-payload-contract-mismatch")
    budget = fields(value["budget"], "cpu_fuel memory_bytes wall_time_limit_millis log_bytes")
    for key, item in budget.items():
        require(item is not None, "missing-benchmark-budget")
        uint(item)
    require(uint(budget["cpu_fuel"]) > 0 and uint(budget["memory_bytes"]) == 16 * 1024 * 1024,
            "invalid-benchmark-grant")
    preparation = fields(value["preparation_key"], "backend_id engine_version engine_configuration_digest target_triple cpu_feature_set")
    for key, item in preparation.items():
        text(item, 4096, empty=key == "cpu_feature_set")
    options = fields(value["backend_options"], "allocator copy_on_write fuel_async_yield_interval maximum_wasm_stack_bytes async_stack_bytes hostcall_fuel prepared_cache_enabled")
    require(options["allocator"] in ("on_demand", "on-demand", "pooling"), "invalid-benchmark-allocator")
    require(type(options["copy_on_write"]) is bool and type(options["prepared_cache_enabled"]) is bool, "invalid-backend-options")
    for key in ("maximum_wasm_stack_bytes", "async_stack_bytes", "hostcall_fuel"):
        uint(options[key])
    if options["fuel_async_yield_interval"] is not None:
        uint(options["fuel_async_yield_interval"])
