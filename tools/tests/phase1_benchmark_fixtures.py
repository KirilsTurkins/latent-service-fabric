"""Small synthetic benchmark populations for evidence validation tests."""

from tools.phase1_evidence.common import canonical, sha256
from tools.phase1_evidence.workloads import TIMING_FIELDS
from tools.tests.phase1_measurement_fixtures import fixture_documents, sample, work


def input_record():
    echo = fixture_documents()[0]["fixtures"][0]
    inputs = {}
    for name, message in (("cold_first_rpc", "phase0 retained first echo"), ("warm_rpc", "phase0 warm echo")):
        encoded = canonical([message])
        inputs[name] = {"payload_sha256": sha256(encoded), "payload_byte_length": str(len(encoded)),
                        "media_type": "application/vnd.latent.wit-values.v1+json", "payload_utf8": encoded.decode()}
    return {"component_digest": echo["component_sha256"], "component_size_bytes": echo["component_bytes"],
            "manifest_sha256": echo["capsule"]["sha256"], "contract_metadata_sha256": echo["contracts"]["sha256"],
            "tenant": "examples", "service": "measurement-echo", "contract": "examples:echo/api@0.1.0", "function": "echo",
            "inputs": inputs, "budget": {"cpu_fuel": "10000000000", "memory_bytes": "16777216", "wall_time_limit_millis": "1000", "log_bytes": "16384"},
            "preparation_key": {"backend_id": "wasmtime-component-phase-1", "engine_version": "47.0.3",
                "engine_configuration_digest": sha256(b"engine"), "target_triple": "x86_64-unknown-linux-gnu", "cpu_feature_set": ""},
            "backend_options": {"allocator": "on_demand", "copy_on_write": True, "fuel_async_yield_interval": "10000",
                "maximum_wasm_stack_bytes": "524288", "async_stack_bytes": "2097152", "hostcall_fuel": "131072", "prepared_cache_enabled": True},
            "boundary_version": "wasmtime-component-call-includes-canonical-post-return-v1",
            "rpc_boundary": "persistent-loopback-tonic-invoke-round-trip-v1"}


def populate(emit):
    input_value = input_record()
    emit("benchmark-input", input_value)
    for name in ("echo", "generic", "capabilities"):
        emit("publication", {"release_digest": sha256(name.encode()), "deployment_id": name,
                             "publish_elapsed_nanos": "100", "apply_elapsed_nanos": "50"})
    tick, invocation_id = 0, 0
    def checkpoint(phase):
        nonlocal tick
        tick += 1
        emit("checkpoint", {"phase": phase, "resources": sample(phase, tick)})
    def invoke(boundary, index, case="success"):
        nonlocal invocation_id
        invocation_id += 1
        outcome = {"domain": "declared-error", "trap": "guest-trap", "fuel": "resource-exhausted", "memory": "resource-exhausted",
                   "deadline": "deadline-exceeded", "cancel": "cancelled"}.get(case, "success")
        emit("benchmark-call", {"boundary": boundary, "sample": str(index), "invocation": {
            "activation_id": f"synthetic-{invocation_id}", "case": case, "outcome": outcome, "rpc_latency_micros": "10",
            "consumption": {"cpu_fuel": "100", "peak_memory_bytes": "1024", "wall_time_micros": "5", "log_bytes": "10"},
            "timing": None if case in ("cancel", "deadline") else {key: "1" for key in TIMING_FIELDS},
            "retained_consumption_matches": True}})
    def prepare(operation, index):
        before = {key: "0" for key in ("entries", "hits", "misses", "preparing", "source_bytes", "compiled_image_bytes")}
        after = dict(before, entries="1", misses="1", source_bytes="4", compiled_image_bytes="100")
        if operation == "cache_hit":
            before, after = after, dict(after, hits="1")
        emit("benchmark-prepare", {"sample": str(index), "operation": operation, "elapsed_micros": "7", "cache_before": before, "cache_after": after})
    checkpoint("before-warmup")
    prepare("initial", 0)
    invoke("warmup", 0)
    checkpoint("after-warmup")
    for index in range(4):
        prepare("cold", index)
        prepare("cache_hit", index)
        emit("benchmark-route", {"sample": str(index), "boundary": "directory-deployment-resolver.resolve", "elapsed_nanos": "10",
            **{key: input_value[key] for key in ("tenant", "service", "contract", "function")},
            "release_digest": input_value["component_digest"], "revision_id": "revision-echo", "route_generation": str(3+index)})
        emit("benchmark-management", {"sample": str(index), "publish_mode": "idempotent-existing-release", "apply_mode": "same-manifest-new-generation",
            "publish_elapsed_nanos": "10", "apply_elapsed_nanos": "20", "release_digest": input_value["component_digest"], "deployment_id": input_value["service"],
            "previous_object_generation": str(1 if index == 0 else 3+index), "object_generation": str(4+index), "catalog_generation": str(4+index),
            "persisted_generation_matches": True, "persisted_record_sha256": sha256(str(index).encode())})
        invoke("cold_first_rpc", index)
        invoke("warm_rpc", index)
        for boundary, count, successes in (("offered_capacity_rpc", 2, 2), ("cancel_released_queue_rpc", 5, 3)):
            if count == 5:
                tick += 1
                emit("benchmark-queue", {"sample": str(index), "active_before_release": "2", "queued_before_release": "3",
                     "resources": sample("queue", tick, active=2, queued=3)})
            for item in range(count):
                invoke(boundary, index, "cancel" if item >= successes else "success")
            emit("benchmark-batch", {"boundary": boundary, "sample": str(index), "attempted_invocations": str(count),
                "successful_invocations": str(successes), "cancelled_invocations": str(count-successes), "elapsed_micros": "50",
                "offered_concurrency": str(count), "includes_retained_status_validation": True,
                "scheduler": {"granted_before": "0", "granted_after": str(count), "total_wait_micros_before": "0",
                              "total_wait_micros_after": "10", "grants": str(count), "wait_sum_micros": "10"}})
        for case in ("domain", "trap", "fuel", "memory", "deadline", "cancel"):
            invoke("fault_" + case, index, case)
            invoke("recovery_" + case, index)
        checkpoint("sample-complete")
    checkpoint("final")
    final_work = work(invocation_id, 220)
    return {"samples_per_boundary": "4", "warmup_invocations": "1", "planned_invoke_attempts": "85", "actual_invoke_attempts": str(invocation_id),
            "offered_capacity_concurrency": "2", "queue_holder_count": "2", "queue_waiter_count": "3", "work": final_work}, final_work
