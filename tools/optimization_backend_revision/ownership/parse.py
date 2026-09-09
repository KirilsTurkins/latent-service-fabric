"""Replay every direct call and both observed destruction proofs from raw JSON."""
import re

from tools.optimization_evidence.common import fields, integer, require, sha256, text, uint
from tools.phase1_compiler_shutdown import validate_compiler_shutdown
from ..cache.accounting import runtime
from . import checks, model
from .observer import Observer

BOUNDARIES = {"composition": "direct-wasmtime-factory", "preparation": "explicit-before-invocation-population",
              "construction": "owned-request-and-boxed-backend-future", "invoke": "poll-through-contained-report-and-future-drop",
              "backend_total_excludes": "outer-context-validation", "reclamation": "two-actual-drop-spans-excluding-classification",
              "allocation_selection": "union-of-construction-and-poll-including-warmup",
              "context_capacity": "logical-Rust-capacity-not-allocator-usable-size"}
INVOKE_FIELDS = ("kind ordinal shape phase iteration activation_id fixture_id prepared payload_sha256 payload_bytes context_fixture_id "
                 "budget deadline_unix_millis construction_started_nanos construction_finished_nanos invoke_started_nanos "
                 "invoke_finished_nanos result backend_timing accounting_after outstanding_reservations resources_after")
PROOF_FIELDS = ("kind ordinal proof activation_id prepared payload_sha256 payload_bytes budget deadline_unix_millis started_nanos "
                "pending_observed_nanos pending polls action_nanos future_destroyed_nanos before at_pending after pending_resources "
                "result accounting_after outstanding_reservations resources_after backend_timing")


def profile(value, identity):
    fields(value, "id wasmtime_version target_triple cpu_feature_set pooling_allocator copy_on_write_images async_support fuel_enabled epoch_interruption_enabled configuration")
    require(value["id"] == "wasmtime-component-phase-1" and value["wasmtime_version"] == identity["build"]["wasmtime"]
            and value["cpu_feature_set"] == "host-baseline" and value["pooling_allocator"] is False
            and all(value[key] is True for key in ("copy_on_write_images", "async_support", "fuel_enabled", "epoch_interruption_enabled")),
            "ownership-engine-profile-changed")
    text(value["target_triple"])
    config = value["configuration"]
    require(isinstance(config, dict) and 1 <= len(config) <= 128, "ownership-engine-config-bound")
    for key, item in config.items():
        text(key, 128)
        text(item, 4096, empty=True)
    expected = {"prepared-cache-enabled": "true", "prepared-cache-maximum-entries": "4", "maximum-concurrent-preparations": "4",
                "compiler-workers": "2", "maximum-active-instances": "4", "maximum-fuel": "10000000000",
                "maximum-memory-bytes": "67108864", "hostcall-fuel-bytes": "131072", "fuel-async-yield-interval": "10000",
                "epoch-tick-interval-millis": "1", "instance-allocation-strategy": "on_demand",
                "maximum-artifact-metadata-bytes": "1048576"}
    require(all(config.get(key) == expected_value for key, expected_value in expected.items())
            and re.fullmatch(r"blake3:[0-9a-f]{64}", config.get("configuration-digest", "")) is not None,
            "ownership-engine-policy-changed")


def parse(value, selected, identity, manifest, manifest_sha256, artifacts, variant):
    fields(value, "schema plan identity fixture_manifest_sha256 process_id runtime_workers observation_hold_millis engine_profile "
           "configuration_debug budget boundaries initial_resources initial_cache initial_observer samples status reason elapsed_nanos work "
           "context_checks before_factory_shutdown factory_shutdown compiler_after_shutdown prepared_runtimes_after_shutdown "
           "raw_inputs_after_shutdown runtime_threads_after_join")
    require(value["schema"] == "latent.optimization.ownership-arm.v1" and value["plan"] == selected
            and value["identity"] == identity and value["fixture_manifest_sha256"] == manifest_sha256
            and value["status"] == "passed" and value["reason"] is None, "ownership-raw-identity-plan-or-status")
    integer(value["process_id"], 2, 2**31-1)
    require(value["runtime_workers"] == 2 and value["observation_hold_millis"] == 100
            and value["budget"] == checks.BUDGET and value["boundaries"] == BOUNDARIES, "ownership-method-boundaries")
    text(value["configuration_debug"], 16384)
    profile(value["engine_profile"], identity)
    elapsed = uint(value["elapsed_nanos"])
    require(elapsed <= int(selected["maximum_run_seconds"]) * 10**9, "ownership-raw-time-bound")
    mode = selected["mode"]
    normal_count = len(selected["shapes"]) * (selected["warmup_per_shape"] + selected["measured_per_shape"])
    proof_ids = [f"ownership-invocation-{normal_count + index:012}" for index in range(2)] if mode == "normal" else []
    observer = Observer(variant, proof_ids)
    observer.check(value["initial_observer"], enabled=False, upper=elapsed)
    checks.resources(value["initial_resources"], 0)
    checks.cache(value["initial_cache"], 0, [])
    expected_prepares = ["capabilities"] if mode == "fixtures" else list(model.ARTIFACTS) if mode == "normal" else [
        "capabilities" if selected["shapes"][0].startswith("context-") else "optimization"]
    fixture_map = {row["id"]: row for row in manifest["artifacts"]}
    samples = value["samples"]
    total = normal_count + len(selected["proofs"])
    require(isinstance(samples, list) and len(samples) == len(expected_prepares) + total, "ownership-raw-population-incomplete")
    components, prepared_values, calls, proofs = [], {}, [], []
    previous = observer.last
    for index, name in enumerate(expected_prepares):
        row = fields(samples[index], "kind fixture_id component capsule contracts started_nanos finished_nanos status cache resources")
        fixture = fixture_map[name]
        start, finish = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(row["kind"] == "prepare" and row["fixture_id"] == name and row["status"] == "passed"
                and all(row[key] == fixture[key] for key in ("component", "capsule", "contracts"))
                and previous <= start <= finish <= elapsed, "ownership-preparation-identity-or-order")
        components.append(fixture["component"])
        checks.resources(row["resources"], 0)
        checks.cache(row["cache"], index + 1, components)
        previous = finish
    payloads = {row["shape"]: artifacts.path(row["artifact"]).read_bytes() for row in manifest["payloads"]}
    for ordinal, row in enumerate(samples[len(expected_prepares):]):
        is_proof = ordinal >= normal_count
        fields(row, PROOF_FIELDS if is_proof else INVOKE_FIELDS)
        require(row["kind"] == ("proof" if is_proof else "invoke") and row["ordinal"] == str(ordinal)
                and row["activation_id"] == f"ownership-invocation-{ordinal:012}" and row["budget"] == checks.BUDGET
                and row["outstanding_reservations"] == "0", "ownership-call-id-or-budget")
        uint(row["deadline_unix_millis"])
        checks.consumption(row["accounting_after"])
        checks.resources(row["resources_after"], ordinal + 1)
        if is_proof:
            proof_index = ordinal - normal_count
            result = proof(row, observer, proof_index, ordinal, previous, elapsed)
            previous = observer.last
            proofs.append(result)
            name = "generic"
        else:
            count = selected["warmup_per_shape"] + selected["measured_per_shape"]
            shape, iteration = selected["shapes"][ordinal // count], ordinal % count
            require(row["shape"] == shape and row["iteration"] == str(iteration)
                    and row["phase"] == ("warmup" if iteration < selected["warmup_per_shape"] else "measured"),
                    "ownership-reordered-shape-or-phase")
            name = "capabilities" if shape.startswith("context-") else "optimization"
            require(row["fixture_id"] == name and row["context_fixture_id"] == (shape if name == "capabilities" else "context-small"),
                    "ownership-context-or-component-crossed")
            payload = b"[]" if name == "capabilities" else payloads[shape]
            require(row["payload_sha256"] == sha256(payload) and uint(row["payload_bytes"]) == len(payload), "ownership-call-payload-crossed")
            start, constructed, invoke, finish = (uint(row[key]) for key in
                ("construction_started_nanos", "construction_finished_nanos", "invoke_started_nanos", "invoke_finished_nanos"))
            require(previous <= start <= constructed <= invoke <= finish <= elapsed, "ownership-invocation-clock-crossed")
            checks.output(row, payload)
            timing = checks.timing(row["backend_timing"], finish - invoke)
            calls.append({"shape": shape, "phase": row["phase"], "ordinal": row["ordinal"],
                          "construction_nanos": str(constructed - start), "invoke_nanos": str(finish - invoke),
                          "construction_through_return_nanos": str(finish - start), "timing": timing})
            previous = finish
        observed_prepared = checks.prepared(row["prepared"], fixture_map[name], value["engine_profile"])
        require(prepared_values.get(name, observed_prepared) == observed_prepared, "ownership-prepared-handle-changed")
        prepared_values[name] = observed_prepared
    before = fields(value["before_factory_shutdown"], "resources cache compiler input")
    checks.resources(before["resources"], total)
    checks.cache(before["cache"], len(expected_prepares), components, hits=total)
    observer.check(before["input"], enabled=mode == "normal", lower=previous, upper=elapsed)
    from tools.phase1_compiler_shutdown import FIELDS, ZERO
    compiler = fields(before["compiler"], " ".join(FIELDS))
    for name, item in compiler.items():
        if name in ("accepting", "failed"):
            require(type(item) is bool, "ownership-compiler-state-type")
        else:
            integer(item, 0, 2**64-1)
    require(compiler["failed"] is False and compiler["maximum_jobs"] == 4 and compiler["maximum_workers"] == 2
            and compiler["maximum_queued_jobs"] == 2 and compiler["workers_live"] == 2
            and all(compiler[name] == 0 for name in ZERO if name != "workers_live"),
            "ownership-compiler-transient-owner-remains")
    shutdown = fields(value["factory_shutdown"], "succeeded started_nanos finished_nanos")
    require(shutdown["succeeded"] is True and observer.last <= uint(shutdown["started_nanos"])
            <= uint(shutdown["finished_nanos"]) <= elapsed, "ownership-factory-shutdown-not-owned")
    observer.check(value["raw_inputs_after_shutdown"], enabled=mode == "normal", lower=uint(shutdown["finished_nanos"]), upper=elapsed)
    validate_compiler_shutdown(value["compiler_after_shutdown"], require)
    require(value["compiler_after_shutdown"]["maximum_jobs"] == 4 and value["compiler_after_shutdown"]["maximum_workers"] == 2
            and value["runtime_threads_after_join"] == 0, "ownership-runtime-or-compiler-joins")
    runtime(checks.decimal(value["prepared_runtimes_after_shutdown"]), "candidate", zero=True)
    expected_checks = len(value["context_checks"]) if mode == "fixtures" else sum(shape.startswith("context-") for shape in selected["shapes"])
    require(value["work"] == {"preparation_attempts": str(len(expected_prepares)), "invoke_attempts": str(total),
                               "proof_attempts": str(len(proofs)), "context_validation_checks": str(expected_checks)},
            "ownership-work-counters-not-population")
    generation_checks(value["context_checks"], manifest, mode)
    return {"process_id": value["process_id"], "elapsed_nanos": str(elapsed), "work": value["work"],
            "calls": calls, "proofs": proofs, "engine_profile": value["engine_profile"],
            "configuration_debug": value["configuration_debug"], "factory_shutdown": shutdown,
            "compiler_after_shutdown": value["compiler_after_shutdown"],
            "prepared_runtimes_after_shutdown": value["prepared_runtimes_after_shutdown"],
            "raw_inputs_after_shutdown": value["raw_inputs_after_shutdown"]}


def proof(row, observer, index, ordinal, previous, elapsed):
    expected = ("cancel-pending", "drop-pending")[index]
    payload = b"[]" + b" " * (65536 - 2)
    require(row["proof"] == expected and row["pending"] is True and uint(row["polls"]) > 0
            and row["payload_sha256"] == sha256(payload) and row["payload_bytes"] == "65536", "ownership-proof-work-or-pending")
    start, pending, action, destroyed = (uint(row[key]) for key in
                                       ("started_nanos", "pending_observed_nanos", "action_nanos", "future_destroyed_nanos"))
    require(previous <= start <= pending <= action <= destroyed <= elapsed, "ownership-proof-clock-order")
    observer.check(row["before"], enabled=True, lower=start, upper=pending)
    at_pending = observer.check(row["at_pending"], enabled=True, lower=pending, upper=action)
    owned = [item for item in at_pending["records"] if item["token"] == str(index)]
    require(owned and owned[-1]["phase"] == "guest_call_start"
            and at_pending["live_invocations"] == "1" and at_pending["live_raw_owners"] == ("0" if observer.variant == "candidate" else "1"),
            "ownership-proof-pending-not-actual-guest-dispatch")
    checks.resources(row["pending_resources"], ordinal + 1, pending=True)
    observer.check(row["after"], enabled=True, lower=destroyed, upper=elapsed)
    result = observer.proof(index, action, destroyed)
    if index == 1:
        require(row["result"] is None, "ownership-dropped-future-fabricated-report")
    else:
        report = fields(row["result"], "outcome code output consumption cleanup")
        require(report["outcome"] == "interrupted" and report["code"] == "Cancelled" and report["output"] is None
                and report["cleanup"] == {"disposition": "reusable", "reason": None}, "ownership-cancel-not-acknowledged-reusable")
        checks.consumption(report["consumption"])
    checks.timing(row["backend_timing"], destroyed - start, optional=index == 1)
    return {"proof": expected, "activation_id": row["activation_id"], "action_nanos": str(action),
            "future_destroyed_nanos": str(destroyed), **result}


def generation_checks(rows, manifest, mode):
    require(isinstance(rows, list) and (3 <= len(rows) <= 20 if mode == "fixtures" else rows == []),
            "ownership-host-only-charge-check-count")
    if mode != "fixtures":
        return
    from .fixtures import charge
    for index, row in enumerate(rows):
        fields(row, "shape content_bytes charge error")
        require(row["shape"] == model.SHAPES[3 + min(index, 2)] and uint(row["content_bytes"]) <= 1048576,
                "ownership-charge-search-shape-or-bound")
        if row["charge"] is None:
            require(row["error"] == "resource-exhausted", "ownership-charge-search-error")
        else:
            require(row["error"] is None, "ownership-charge-search-status")
            charge(row["charge"])
    for context in manifest["contexts"]:
        require(any(row["shape"] == context["shape"] and row["charge"] == context["charge"] for row in rows),
                "ownership-frozen-context-not-actually-checked")
