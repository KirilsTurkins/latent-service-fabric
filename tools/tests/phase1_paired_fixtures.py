"""Tiny synthetic paired documents, never performance evidence."""

import copy
from pathlib import Path

from tools.phase0_collector_identity import EXPECTED_RELEASE_BUILD_CONFIGURATION
from tools.phase1_evidence.common import canonical, reference, sha256
from tools.phase1_paired.common import CONTROL_COMMIT, CONTROL_TREE, GRANTS, INPUT, METHOD, TIMINGS
from tools.phase1_paired.control import CHECKS
from tools.tests.phase1_measurement_fixtures import identity as base_identity, sample, shutdown


def plan():
    return {"schema": "latent.phase1.paired-plan.v1", "profile": "smoke", "repetition": 1,
            "warmup_samples": 2, "measured_samples": 4, "maximum_run_seconds": "120", "maximum_output_bytes": "16777216"}


def identity(arm):
    value = base_identity()
    value["build"].update(profile="release", overrides={"recipe_sha256": sha256(b"recipe"), "collector_surface": "native-binary" if arm == "control" else "libtest",
        "recipe": "tools/phase0_build_environment.sh:phase0_release_cargo", "opt_level": "3", "debug": "1", "codegen_units": "16",
        "lto": "false", "debug_assertions": "false", "overflow_checks": "false", "incremental": "false", "panic": "unwind", "strip": "none",
        "path_remap": "source-target-cargo-home-v1", "linker_build_id": "sha1", "promoted_locals": "source-filename"})
    value["environment"]["kernel"] = "Linux host 1 #1 x86_64 GNU/Linux"
    if arm == "control":
        value["source"].update(commit=CONTROL_COMMIT, tree=CONTROL_TREE)
    value["fixtures"] = [{"name": "echo", "sha256": sha256(arm.encode()), "bytes": str(len(arm))}]
    value["binary"] = {"sha256": sha256((arm + " binary").encode()), "bytes": str(len(arm + " binary"))}
    return value


def control(selected, observed, built):
    host, build = observed["environment"], observed["build"]
    environment = {"operating_system": "linux", "architecture": host["arch"], "kernel": "Linux 1 #1 x86_64 GNU/Linux",
                   "cpu_model": host["cpu_model"], "logical_cpu_count": 2, "total_memory_bytes": int(host["memory_total_bytes"]),
                   "rustc": build["rustc"], "cargo": build["cargo"], "rust_target": build["target"], "build_profile": "release",
                   "wasmtime_version": build["wasmtime"] + " (workspace pin)", "repository_commit": CONTROL_COMMIT}
    raw = {"schema_version": "latent.phase0.targeted-profile.v2", "status": "pass", "observational_only": True,
           "profile_workload": "warm-execution", "full_invariant_proof_required": True,
           "workload_semantics": "repeated successful warm echoes after one preparation; no failure sequence, pool probe, or throughput",
           "selected_scenarios": ["warm_echo"], "activation_throughput": None, "preparation_cache_reuse": None,
           "targeted_contention": None, "checks": [{"name": name, "passed": True} for name in sorted(CHECKS)],
           "environment": environment, "config": {"mode": "full", "profile_workload": "warm-execution", "pool_capacity": 2,
               "pool_queue_capacity": 3, "runtime_workers": 2, "warm_samples": 6, "fuel": 10_000_000_000,
               "memory_bytes": 16_777_216, "wasmtime_allocator": "on_demand", "wasmtime_copy_on_write_images": True,
               "prepared_cache_enabled": True}, "artifact": {"collector": {"schema_version": "latent.phase0.native-collector.v1",
               "collector": "phase0-baseline", "executable_digest": observed["binary"]["sha256"], "executable_bytes": int(observed["binary"]["bytes"]),
               "build_configuration": EXPECTED_RELEASE_BUILD_CONFIGURATION}},
           "activation_samples": [], "timings": {"component_preparation_micros": 50},
           "payload_flow": {"input_bytes_submitted_to_typed_call": 150, "output_bytes_returned_from_typed_call": 150, "copy_bytes_claimed": 0}}
    for key in ("component", "capsule"):
        raw["artifact"].update({key + "_digest": built[key]["sha256"], key + "_bytes": int(built[key]["bytes"])})
    for index in range(6):
        raw["activation_samples"].append({"scenario": "warm_echo", "iteration": index,
            "activation_id": f"baseline-warm-echo-{index:08}", "input_bytes": 25, "output_bytes": 25,
            "contract_result_valid": True, "expected_outcome": "success", "timeout_or_cancel_overshoot_micros": None,
            "elapsed_micros": 1000 if index < 2 else 20 + index,
            "outcome": {"name": "success", "error_code": None, "output_utf8": INPUT,
                        "consumption": {"cpu_fuel": 100, "peak_memory_bytes": 1024, "wall_time_micros": 10, "log_bytes": 10}},
            "phase_timings": {key: 1 for key in TIMINGS},
            "pool_after": {"capacity": 2, "available": 2, "queue_depth": 0, "active_leases": 0, "quarantined": 0},
            "runner_after": {"active_cancellation_registrations": 0, "running_invocations": 0,
                "total_invocations": index + 1, "released_cells": index + 1, "quarantined_cells": 0, "disposition_failures": 0},
            "backend_resources_after": {"stores_created": index + 1, "live_stores": 0, "active_invocations": 0,
                                       "live_host_states": 0, "live_component_instances": 0, "live_temporary_buffers": 0, "live_cancellation_probes": 0},
            "prepared_cache_after": {"entries": 1, "maximum_entries": 1, "source_bytes": 7, "maximum_source_bytes": 100},
            "retained_log_entries_after_clear": 0, "observed_runtime_workers_after": 2,
            "process_after": {"probe_supported": True, "process_count": 1, "child_process_count": 0, "thread_count": 4,
                              "file_descriptor_count": 8, "rss_bytes": 1024, "virtual_memory_bytes": 4096, "open_socket_count": 0, "listening_socket_count": 0}})
    raw["process_snapshots"] = [copy.deepcopy(raw["activation_samples"][0]["process_after"]) for _ in range(11)]
    raw["process_snapshots"][-1].update(label="runtime_stopped", thread_count=1)
    return raw


def candidate(selected, observed, metadata):
    semantic = {"utf8": INPUT, "sha256": sha256(INPUT.encode()), "bytes": "25"}
    raw = {"schema": "latent.phase1.paired-arm.v1", "arm": "candidate", "profile": "smoke", "plan": selected,
           "identity": observed, "semantic_input": semantic, "semantic_output": semantic,
           "warmup_samples": "2", "measured_samples": "4", "status": "passed", "reason": None,
           "effective_options": dict(GRANTS, pool_capacity="2", queue_capacity="3", runtime_workers="2", control_workers="1",
               prepared_cache_maximum_entries="4", allocator="on_demand", copy_on_write=True, prepared_cache_enabled=True,
               fuel_async_yield_interval="10000", maximum_wasm_stack_bytes="524288", async_stack_bytes="2097152", hostcall_fuel="131072"),
           "configuration": {"formatVersion": 1, "dataDirectory": "data", "nodeId": "phase1-comparison", "bind": "127.0.0.1:0",
               "workers": {"runtime": 2, "control": 1}, "cells": [
               {"class": "standard", "capacity": 2, "queueCapacity": 3, "maximumMemoryBytes": 16_777_216}],
               "execution": {"maximumCpuFuel": 10_000_000_000, "maximumWallTimeMillis": 1000, "maximumLogBytes": 16384},
               "cache": {"entries": 4, "sourceBytes": 67_108_864, "metadataBytes": 16_777_216, "compiledImageBytes": 268_435_456, "preparations": 1},
               "catalogs": {"releaseEntries": 16, "releaseIndexBytes": 16_777_216, "deployments": 16, "deploymentStateBytes": 16_777_216},
               "retention": {"terminalEntries": 64, "terminalTtlMillis": 60_000, "bytes": 20_971_520},
               "telemetry": {"queueEntries": 256, "retainedEntries": 128, "retainedBytes": 1_048_576}, "shutdownGraceMillis": 500},
           "startup": {"catalog_open_nanos": "10", "node_start_nanos": "20", "client_connect_nanos": "10",
                       "excluded": ["fixture-loading", "runtime-construction"], "comparable_to_historical_startup": False},
           "artifact": dict(metadata, component_sha256=observed["fixtures"][0]["sha256"], component_bytes="9",
                            stored_descriptor_reference="local:release:" + observed["fixtures"][0]["sha256"]),
           "publication": {"release_digest": observed["fixtures"][0]["sha256"], "deployment_id": "measurement-echo", "object_generation": "1", "catalog_generation": "1"},
           "preparation_elapsed_micros": "60", "preparation_cache_before": cache(0), "preparation_cache_after": cache(1),
           "samples": [], "elapsed_micros": "1000", "prepared_release_elapsed_micros": "2",
           "shutdown": shutdown(), "data_cleanup": {"removed": True}}
    for index in range(6):
        post = sample("post", index + 1)
        post["backend"]["stores_created"] = str(index + 1)
        post["inventory"]["cacheSummary"].update(entries="1", sourceBytes="9", hits=str(index + 1), misses="1")
        post["work"] = {"invoke_attempts": str(index + 1), "commands": str(2 * index + 4), "budget_exhausted": False}
        raw["samples"].append({"iteration": str(index), "activation_id": f"baseline-warm-echo-{index:08}",
            "semantic_output_sha256": semantic["sha256"], "outcome": "success", "elapsed_micros": str(30 + index),
            "timing": {key: "2" for key in TIMINGS}, "consumption": {"cpu_fuel": "100", "peak_memory_bytes": "1024", "wall_time_micros": "10", "log_bytes": "10"},
            "post_call": post, "receipt": {"release_digest": observed["fixtures"][0]["sha256"], "revision_id": "revision-v1:" + sha256(b"revision"),
            "route_generation": "1", "terminal_state": "completed", "retained_consumption_matches": True}})
    raw["work"] = raw["samples"][-1]["post_call"]["work"]
    raw["after_release"] = sample("released", 7)
    raw["after_release"]["backend"]["stores_created"] = "6"
    return raw


def cache(count):
    return {"entries": str(count), "hits": "0", "misses": str(count), "evictions": "0", "invalidations": "0",
            "source_bytes": str(9 * count), "metadata_bytes": str(count), "compiled_image_bytes": str(count), "preparing": "0"}


def suite(root: Path):
    def save(relative, value):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else canonical(value))
        return reference(path, root)
    prefix = "reproduction/control/"
    def old(relative, value):
        ref = save(prefix + relative, value)
        return dict(ref, path=relative)
    built = {"schema": "latent.phase1.control-build.v1", "source": identity("control")["source"],
             "build": identity("control")["build"], "binary": old("release/phase0-baseline", b"control binary"),
             "component": old("echo.wasm", b"control"), "capsule": old("capsule.json", {"execution": {"limits": {"cpuFuel": 10_000_000_000, "memoryBytes": 16_777_216, "logBytes": 16384}}}),
             "artifacts": [old("inputs/Cargo.lock", b"lock"), old("inputs/tools/phase0_build_environment.sh", b"recipe")],
             "shared_guest_sources": [], "commands": [["python3", "tools/build_echo_capsule.py", "--verify-reproducible"],
                ["phase0_release_cargo", "build", "-p", "latentd", "--bin", "phase0-baseline", "--release", "--locked"]],
             "staged_manifest_changes": {"cpuFuel": "10000000000", "memoryBytes": "16777216"},
             "scope": "targeted-historical-runtime-comparison-not-native-calibration", "full_invariant_proof": "not-run-by-this-build-helper"}
    sources = []
    for name in ("component.rs", "logic.rs"):
        logical = "tools/toolchain-smoke/examples/echo_capsule/" + name
        before, after = old("inputs/historical/" + logical, name.encode()), old("inputs/candidate/" + logical, name.encode())
        built["artifacts"].extend((before, after))
        built["shared_guest_sources"].append({"source_path": logical, "historical": before, "candidate": after})
        sources.append({"path": logical, "artifact": save("reproduction/candidate/" + logical, name.encode())})
    for index in range(4):
        built["artifacts"].append(old(f"input-{index}.txt", b"input"))
    build_ref = save(prefix + "build-receipt.json", built)
    save("reproduction/candidate/collector", b"candidate binary")
    save("reproduction/candidate/echo-capsule.wasm", b"candidate")
    result = {"schema": "latent.phase1.paired-suite.v1", "method": METHOD, "profile": "smoke", "plan": plan(),
              "control_build": build_ref, "candidate_guest_sources": sources, "runs": [], "artifacts": []}
    for index, arm in enumerate(("control", "candidate")):
        directory = f"pair-01/{arm}/"
        observed = identity(arm)
        save(directory + "identity.json", observed)
        save(directory + "plan.json", plan())
        if arm == "control":
            raw = control(plan(), observed, built)
            from tools.run_phase1_paired import control_command
            # Runner imports script helpers by direct path; tests set sys.path.
            command = control_command(Path("control"), Path("capsule"), Path("out"), plan())
        else:
            release = observed["fixtures"][0]["sha256"]
            documents = {"capsule": {"metadata": {"tenant": "examples", "name": "measurement-echo"}, "component": {"digest": release}, "exports": ["examples:echo/api@0.1.0"]},
                         "deployment": {"metadata": {"tenant": "examples", "name": "measurement-echo"}, "spec": {"release": release, "service": "measurement-echo"}},
                         "contracts": {"format_version": 1, "contracts": [{"interfaces": [{"id": "examples:echo/api@0.1.0"}]}]}}
            budget = {"cpuFuel": 10_000_000_000, "memoryBytes": 16_777_216, "logBytes": 16384, "wallTimeLimitMillis": None}
            documents["capsule"]["execution"] = {"limits": budget}
            documents["deployment"]["spec"]["resources"] = budget
            refs = {role: dict(save(directory + "echo-" + role + ".json", document), path="echo-" + role + ".json") for role, document in documents.items()}
            raw = candidate(plan(), observed, refs)
            command = ["candidate", "--exact", "standalone::measurements::comparison::phase1_comparison_collector", "--ignored", "--nocapture", "--test-threads=1"]
        row = {"repetition": 1, "arm": arm, "status": "passed", "reason": None, "identity": observed, "command": command,
               "started_micros": str(index * 2000), "finished_micros": str(index * 2000 + 1000),
               "raw": save(directory + ("baseline.json" if arm == "control" else "candidate.json"), raw),
               "process": save(directory + "process.json", {"process_id": 122 + index, "start_time_ticks": "77", "reaped": True, "output_closed": True, "exit_code": 0}),
               "cleanup": save(directory + "parent-cleanup.json", {"removed": True}),
               "host_after": save(directory + "host-after.json", observed["environment"])}
        result["runs"].append(row)
    result["artifacts"] = [reference(path, root) for path in sorted(root.rglob("*")) if path.is_file()]
    path = root / "suite.json"
    path.write_bytes(canonical(result))
    return path


def refresh(path):
    import json
    value = json.loads(path.read_bytes())
    for row in value["runs"]:
        for key in ("raw", "process", "cleanup", "host_after"):
            if row[key] is not None:
                row[key] = reference(path.parent / row[key]["path"], path.parent)
    value["artifacts"] = [reference(path.parent / item["path"], path.parent) for item in value["artifacts"]]
    path.write_bytes(canonical(value))
