"""Parse the immutable historical targeted report without relabelling full proof."""

from ..aggregate_phase0_hot_path_profiles import verify_targeted_profile_document
from ..phase0_collector_identity import require_native_collector_identity
from ..phase1_evidence.common import fields, integer, require
from .common import INPUT
from .metrics import consumption, summarize, timing

CHECKS = {"targeted_profile_" + suffix for suffix in (
    "selected_semantics", "selected_outcomes_pass", "reclaims_selected_activation_state",
    "failure_recovery_pass", "contention_state_pass", "prepared_cache_reuse_pass",
    "topology_is_constant", "release_clears_prepared_state", "runtime_shutdown_returns_to_process_baseline")}


def parse(document, plan, identity, bootstrap):
    verify_targeted_profile_document(document, "paired control", "warm-execution")
    require(document["observational_only"] is True, "historical-scope-changed")
    checks = document["checks"]
    require(len(checks) == len(CHECKS) and {row["name"] for row in checks} == CHECKS
            and all(row["passed"] is True for row in checks), "historical-targeted-checks-incomplete")
    count = plan["warmup_samples"] + plan["measured_samples"]
    config = document["config"]
    expected = {"pool_capacity": 2, "pool_queue_capacity": 3, "runtime_workers": 2,
                "warm_samples": count, "fuel": 10_000_000_000, "memory_bytes": 16_777_216,
                "wasmtime_allocator": "on_demand", "wasmtime_copy_on_write_images": True,
                "prepared_cache_enabled": True}
    require(all(config.get(key) == value and type(config[key]) is type(value) for key, value in expected.items()), "historical-effective-controls-changed")
    artifact = document["artifact"]
    collector = require_native_collector_identity(artifact["collector"], "control", "phase0-baseline")
    require(collector["executable_digest"] == identity["binary"]["sha256"]
            and collector["executable_bytes"] == int(identity["binary"]["bytes"]), "historical-executable-not-bound")
    for label, expected_ref in (("component", bootstrap["component"]), ("capsule", bootstrap["capsule"])):
        require(artifact[label + "_digest"] == expected_ref["sha256"]
                and artifact[label + "_bytes"] == int(expected_ref["bytes"]), "historical-artifact-not-bound")
    environment = document["environment"]
    host = identity["environment"]
    mappings = {"operating_system": host["os"].lower(), "architecture": host["arch"],
                "cpu_model": host["cpu_model"],
                "total_memory_bytes": int(host["memory_total_bytes"]), "rustc": identity["build"]["rustc"],
                "cargo": identity["build"]["cargo"], "rust_target": identity["build"]["target"],
                "build_profile": "release", "wasmtime_version": identity["build"]["wasmtime"] + " (workspace pin)",
                "repository_commit": identity["source"]["commit"]}
    require(all(environment.get(key) == value for key, value in mappings.items()), "historical-observed-environment-mismatch")
    # Historical std::thread::available_parallelism observes quota/affinity;
    # Python os.cpu_count reports machine logical CPUs. Do not equate them.
    integer(environment["logical_cpu_count"], 1, int(host["logical_cpus"]))
    kernel = host["kernel"].split()
    require(len(kernel) >= 5, "missing-observed-kernel")
    del kernel[1]  # uname -a includes node name; historical -srvmo excludes it.
    while len(kernel) >= 3 and kernel[-3] == kernel[-2] == host["arch"]:
        del kernel[-3]
    require(environment["kernel"].split() == kernel, "historical-kernel-mismatch")
    rows = document["activation_samples"]
    require(isinstance(rows, list) and len(rows) == count, "changed-historical-population")
    samples = []
    for index, row in enumerate(rows):
        require(row["scenario"] == "warm_echo" and type(row["iteration"]) is int and row["iteration"] == index
                and row["activation_id"] == f"baseline-warm-echo-{index:08}", "reordered-historical-population")
        require(row["input_bytes"] == row["output_bytes"] == 25 and row["contract_result_valid"] is True
                and row["expected_outcome"] == "success" and row["timeout_or_cancel_overshoot_micros"] is None,
                "historical-semantic-input-mismatch")
        outcome = fields(row["outcome"], "name error_code output_utf8 consumption")
        require(outcome["name"] == "success" and outcome["error_code"] is None and outcome["output_utf8"] == INPUT,
                "historical-semantic-output-mismatch")
        consumption(outcome["consumption"], legacy=True)
        require(row["pool_after"] == {"capacity": 2, "available": 2, "queue_depth": 0, "active_leases": 0, "quarantined": 0}, "historical-cell-not-idle")
        runner = row["runner_after"]
        require(runner == {"active_cancellation_registrations": 0, "running_invocations": 0,
                          "total_invocations": index + 1, "released_cells": index + 1,
                          "quarantined_cells": 0, "disposition_failures": 0}, "historical-owner-leak")
        backend = fields(row["backend_resources_after"], "active_invocations live_stores live_host_states live_component_instances live_temporary_buffers live_cancellation_probes stores_created")
        require(backend["stores_created"] == index + 1 and all(value == 0 for key, value in backend.items()
                if key != "stores_created"), "historical-store-reuse-or-leak")
        cache = row["prepared_cache_after"]
        require(cache["entries"] == cache["maximum_entries"] == 1
                and cache["source_bytes"] == int(identity["fixtures"][0]["bytes"])
                and cache["source_bytes"] <= cache["maximum_source_bytes"], "historical-cache-not-reused")
        require(row["retained_log_entries_after_clear"] == 0 and row["observed_runtime_workers_after"] == 2,
                "historical-fixed-owner-mismatch")
        process(row["process_after"])
        samples.append({"elapsed": integer(row["elapsed_micros"], 0, 2**64-1),
                        "timing": timing(row["phase_timings"], legacy=True)})
    require(document["payload_flow"]["input_bytes_submitted_to_typed_call"] == 25 * count
            and document["payload_flow"]["output_bytes_returned_from_typed_call"] == 25 * count
            and document["payload_flow"]["copy_bytes_claimed"] == 0, "historical-payload-flow-mismatch")
    snapshots = document["process_snapshots"]
    require(isinstance(snapshots, list) and len(snapshots) == count + 5
            and snapshots[-1]["label"] == "runtime_stopped", "missing-historical-shutdown-observation")
    process(snapshots[-1])
    require(snapshots[-1]["thread_count"] <= 2, "historical-runtime-workers-remain")
    return {"metrics": summarize(samples, plan["warmup_samples"], integer(document["timings"]["component_preparation_micros"], 0, 2**64-1)),
            "samples": str(count), "process_identity": None,
            "effective_options": expected, "historical_full_proof": "not-run-targeted-only"}


def process(value):
    require(value["probe_supported"] is True and value["process_count"] == 1
            and value["child_process_count"] == 0, "historical-process-observation-missing")
    for key in ("thread_count", "file_descriptor_count", "rss_bytes", "virtual_memory_bytes"):
        integer(value[key], 1, 2**64-1)
    for key in ("open_socket_count", "listening_socket_count"):
        integer(value[key], 0, 2**64-1)
