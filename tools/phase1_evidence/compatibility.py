"""Metric-specific compatibility; source changes are the measured treatment."""

import re

from .common import canonical

BUILD_FIELDS = {"opt_level": "opt_level", "debug": "debug_info", "codegen_units": "codegen_units",
    "lto": "lto", "debug_assertions": "debug_assertions", "overflow_checks": "overflow_checks",
    "incremental": "incremental", "panic": "panic", "strip": "strip", "path_remap": "path_remap_policy",
    "linker_build_id": "linker_build_id", "promoted_locals": "promoted_local_symbols"}


def scalar(value):
    return str(value).lower() if value is not None else None


def kernel_identity(value):
    # uname -a adds a hostname, whereas the Phase0 collector used -srvmo.
    # Neither hostname nor duplicate machine/processor suffixes are a kernel.
    found = re.search(r"(?:^|\s)(\d+\.\d+\.\S+)\s+(.*)", value)
    if not found:
        return None
    return (found.group(1), re.split(r"\s+(?:x86_64|aarch64|GNU/Linux)(?:\s|$)", found.group(2))[0])


def reasons(candidate, reference, *, activation=False):
    result = []
    group = candidate["kinds"]["benchmark"]
    runs = [run for run in candidate["runs"] if run["kind"] == "benchmark"]
    if candidate["profile"] != "full" or group["status"] != "passed" or len(runs) < 7:
        result.append("candidate-not-full-calibration")
    if reference.get("status") != "pass" or reference.get("run_count", 0) < 7:
        result.append("reference-not-full-calibration")
    if not runs or not runs[0]["benchmark_input"]:
        return result + ["missing-candidate-benchmark-input"]
    run, prior = runs[0], reference["reference_identity"]
    identity, inputs = run["identity"], run["benchmark_input"]
    build, old_build = identity["build"], prior["collector"]["build_configuration"]
    environment, old_environment = identity["environment"], prior["environment"]
    if build["profile"] != old_build.get("cargo_profile") or any(
            scalar(build["overrides"].get(new)) != scalar(old_build.get(old)) for new, old in BUILD_FIELDS.items()):
        result.append("build-configuration-mismatch")
    for current, old in (("rustc", "rustc"), ("cargo", "cargo"), ("target", "rust_target")):
        if build[current].strip() != old_environment.get(old, "").strip():
            result.append("toolchain-" + current + "-mismatch")
    if build["wasmtime"].split()[0] != old_environment.get("wasmtime_version", "").split()[0]:
        result.append("wasmtime-version-mismatch")
    for current, old in (("os", "operating_system"), ("arch", "architecture"), ("cpu_model", "cpu_model"),
                         ("logical_cpus", "logical_cpu_count"), ("memory_total_bytes", "total_memory_bytes")):
        if scalar(environment[current]) != scalar(old_environment.get(old)):
            result.append("host-" + current.replace("_", "-") + "-mismatch")
    kernel = kernel_identity(environment["kernel"])
    if kernel is None or kernel != kernel_identity(old_environment.get("kernel", "")):
        result.append("host-kernel-mismatch")
    observations = reference.get("host_observations", {}).get("runs", [])
    if not observations:
        result.append("missing-reference-host-observations")
    else:
        for row in observations:
            for key in ("systemd_detect_virt", "systemd_detect_virt_container", "systemd_detect_virt_vm", "wsl_detected"):
                value = environment["virtualization"].get(key)
                if value is None or value != row.get("virtualization", {}).get(key):
                    result.append("virtualization-mismatch-or-unobserved")
            for new, old in (("LD_PRELOAD", "ld_preload"), ("MALLOC_CONF", "malloc_conf")):
                value = environment["allocator"].get(new)
                if value is None or value != row.get("allocator", {}).get(old):
                    result.append("allocator-mismatch-or-unobserved")
            policies = row.get("cpu_frequency_policy", {}).get("observed")
            if policies is None or canonical(environment["cpu_policy"]) != canonical(policies):
                result.append("cpu-policy-mismatch-or-unobserved")
    artifact = prior["artifact"]
    if inputs["component_digest"] != artifact.get("component_digest") or scalar(inputs["component_size_bytes"]) != scalar(artifact.get("component_bytes")):
        result.append("component-input-mismatch")
    options, config = inputs["backend_options"], prior["config"]
    for new, old in (("allocator", "wasmtime_allocator"), ("copy_on_write", "wasmtime_copy_on_write_images"),
                     ("prepared_cache_enabled", "prepared_cache_enabled")):
        if options[new] != config.get(old):
            result.append("engine-" + new.replace("_", "-") + "-mismatch")
    for key in ("fuel_async_yield_interval", "maximum_wasm_stack_bytes", "async_stack_bytes", "hostcall_fuel"):
        if key not in config:
            result.append("unobserved-reference-engine-" + key.replace("_", "-"))
        elif scalar(options[key]) != scalar(config[key]):
            result.append("engine-" + key.replace("_", "-") + "-mismatch")
    if activation and scalar(inputs["budget"]["cpu_fuel"]) != scalar(config.get("fuel")):
        result.append("activation-fuel-budget-mismatch")
    if activation and scalar(inputs["budget"]["memory_bytes"]) != scalar(config.get("memory_bytes")):
        result.append("activation-memory-budget-mismatch")
    if activation:
        for key in ("wall_time_limit_millis", "log_bytes"):
            if key not in config:
                result.append("unobserved-reference-activation-" + key.replace("_", "-"))
            elif scalar(inputs["budget"][key]) != scalar(config[key]):
                result.append("activation-" + key.replace("_", "-") + "-mismatch")
    return sorted(set(result))
