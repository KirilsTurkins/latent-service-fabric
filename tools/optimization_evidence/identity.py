"""Source, build and retained executable identities for the actual two arms."""

from .common import GIT_HASH, canonical, digest, fields, integer, require, text, uint


def identity(value, artifacts, full):
    fields(value, "source build environment executables components workload_sources build_inputs source_checks")
    source = fields(value["source"], "commit tree dirty cargo_lock_sha256")
    for key in ("commit", "tree"):
        require(isinstance(source[key], str) and GIT_HASH.fullmatch(source[key]), "invalid-source-identity")
    require(type(source["dirty"]) is bool and (not full or not source["dirty"]), "unclean-full-source")
    digest(source["cargo_lock_sha256"])
    build = fields(value["build"], "profile rustc cargo wasmtime target overrides")
    require(build["profile"] == ("release" if full else "debug"), "changed-profile-build")
    for key in ("rustc", "cargo", "wasmtime", "target"):
        text(build[key])
    require(isinstance(build["overrides"], dict) and 1 <= len(build["overrides"]) <= 64,
            "missing-build-controls")
    environment = fields(value["environment"], "os arch kernel cpu_model logical_cpus memory_total_bytes virtualization allocator cpu_policy load_before")
    for key in ("os", "arch", "kernel", "cpu_model"):
        text(environment[key])
    require(environment["os"].lower() == "linux", "requires-linux-process-observations")
    require(uint(environment["logical_cpus"]) > 0 and uint(environment["memory_total_bytes"]) > 0,
            "missing-host-capacity")
    for key in ("virtualization", "allocator", "cpu_policy"):
        require(isinstance(environment[key], dict), "missing-host-control")
    load = environment["load_before"]
    require(isinstance(load, list) and len(load) == 3
            and all(type(item) in (int, float) and item >= 0 for item in load), "invalid-host-load")
    executables = fields(value["executables"], "native lsf client", "cli control")
    for item in executables.values():
        artifacts.path(item)
        require(uint(item["bytes"]) > 0, "empty-executable")
    require(len({executables[key]["sha256"] for key in ("native", "lsf", "client")}) == 3,
            "crossed-executable-identities")
    require(isinstance(value["components"], list) and len(value["components"]) == 5,
            "missing-working-set-components")
    seen = set()
    for item in value["components"]:
        artifacts.path(item)
        require(0 < uint(item["bytes"]) <= 16 * 1024 * 1024, "invalid-component-size")
        seen.add(item["sha256"])
    require(len(seen) == 5, "working-set-reuses-one-component")
    require(isinstance(value["workload_sources"], list) and 1 <= len(value["workload_sources"]) <= 32,
            "missing-shared-workload-source")
    seen.clear()
    for item in value["workload_sources"]:
        artifacts.path(item)
        require(item["path"] not in seen and uint(item["bytes"]) > 0, "duplicate-workload-source")
        seen.add(item["path"])
    required = ("Cargo.lock", "Cargo.toml", "rust-toolchain.toml", "tools/build_optimization_bench.sh",
                "tools/phase0_build_environment.sh", "tools/optimization-bench/Cargo.toml",
                "tools/optimization-workloads/Cargo.toml", "tools/toolchain-smoke/Cargo.toml")
    inputs = value["build_inputs"]
    require(isinstance(inputs, list) and len(inputs) == len(required), "missing-build-provenance")
    indexed = {}
    for item in inputs:
        artifacts.path(item)
        require(item["path"].startswith("sources/") and item["path"][8:] not in indexed, "duplicate-build-input")
        indexed[item["path"][8:]] = item
    require(set(indexed) == set(required), "changed-build-inputs")
    require(indexed["Cargo.lock"]["sha256"] == source["cargo_lock_sha256"]
            and indexed["tools/build_optimization_bench.sh"]["sha256"] == build["overrides"].get("optimization_recipe_sha256")
            and indexed["tools/phase0_build_environment.sh"]["sha256"] == build["overrides"].get("recipe_sha256"),
            "unbound-build-recipe")
    checks = value["source_checks"]
    require(isinstance(checks, list) and len(checks) == 2, "missing-source-stability-checks")
    for item, suffix in zip(checks, ("source-after-build.json", "source-after-run.json"), strict=True):
        require(item["path"].endswith(suffix) and canonical(artifacts.json(item)) == canonical(source),
                "source-changed-during-execution")


def plan(value):
    # The runner's committed preset is the normative finite population. Merely
    # changing the declared manifest cannot remove a difficult measurement.
    from tools.optimization_runner.plans import plan as preset
    fields(value, "schema profile repetitions scenarios cases maximum_run_seconds maximum_artifact_bytes")
    require(value["profile"] in ("smoke", "full"), "invalid-profile")
    require(canonical(value) == canonical(preset(value["profile"])), "changed-benchmark-population")
    integer(value["repetitions"], 1, 7)
