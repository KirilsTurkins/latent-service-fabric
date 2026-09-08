"""Fixed paired-method controls and bounded identities."""

from typing import Any

from ..phase1_evidence.common import (GIT_HASH, bounded_tree, digest, fields, integer,
                                     require, text, uint)

PREFIX = "latent.phase1.paired-"
METHOD = "historical-runtime-productionization-bundle-v1"
CONTROL_COMMIT = "52ac47542a05c0a1263f78a14c04a5c2e6b761f3"
CONTROL_TREE = "cac3ececdbd0b5734691c30c0283fccff169a5f5"
INPUT = "phase0 targeted warm echo"
RAW_LIMIT = 16 * 1024 * 1024
GRANTS = {"cpu_fuel": "10000000000", "memory_bytes": "16777216",
          "wall_time_limit_millis": "1000", "log_bytes": "16384"}
TIMINGS = ("backend_setup_micros", "guest_call_micros", "host_call_micros", "host_call_count",
           "component_post_return_micros", "activation_resource_reclamation_micros",
           "outcome_classification_micros", "reusable_proof_micros", "backend_total_micros")


def plan(value: Any) -> None:
    fields(value, "schema profile repetition warmup_samples measured_samples maximum_run_seconds maximum_output_bytes")
    require(value["schema"] == PREFIX + "plan.v1" and value["profile"] in ("smoke", "full"), "invalid-paired-plan")
    integer(value["repetition"], 1, 7)
    full = value["profile"] == "full"
    require(type(value["warmup_samples"]) is int and value["warmup_samples"] == (40 if full else 2)
            and type(value["measured_samples"]) is int and value["measured_samples"] == (400 if full else 4)
            and value["maximum_run_seconds"] == ("600" if full else "120")
            and value["maximum_output_bytes"] == str(RAW_LIMIT), "changed-paired-preset")


def identity(value: Any, arm: str, *, full: bool = True) -> None:
    fields(value, "schema source build environment binary fixtures")
    require(value["schema"] == "latent.phase1.measurement-identity.v1", "invalid-paired-identity")
    source = fields(value["source"], "commit tree dirty cargo_lock_sha256")
    require(all(isinstance(source[key], str) and GIT_HASH.fullmatch(source[key]) for key in ("commit", "tree"))
            and type(source["dirty"]) is bool and (not full or source["dirty"] is False), "unclean-paired-source")
    digest(source["cargo_lock_sha256"])
    if arm == "control":
        require(source["commit"] == CONTROL_COMMIT and source["tree"] == CONTROL_TREE
                and source["dirty"] is False, "control-is-not-historical-runtime")
    else:
        require(arm == "candidate" and source["commit"] != CONTROL_COMMIT, "invalid-candidate-source")
    build = fields(value["build"], "profile rustc cargo wasmtime target overrides")
    require(build["profile"] == "release", "paired-requires-release-build")
    for key in ("rustc", "cargo", "wasmtime", "target"):
        text(build[key])
    require(isinstance(build["overrides"], dict), "missing-paired-build-recipe")
    bounded_tree(build["overrides"])
    expected_recipe = {"recipe": "tools/phase0_build_environment.sh:phase0_release_cargo", "opt_level": "3",
                       "debug": "1", "codegen_units": "16", "lto": "false", "debug_assertions": "false",
                       "overflow_checks": "false", "incremental": "false", "panic": "unwind", "strip": "none",
                       "path_remap": "source-target-cargo-home-v1", "linker_build_id": "sha1",
                       "promoted_locals": "source-filename", "collector_surface": "native-binary" if arm == "control" else "libtest"}
    require(set(build["overrides"]) == set(expected_recipe) | {"recipe_sha256"}
            and all(build["overrides"][key] == item for key, item in expected_recipe.items()), "changed-paired-release-recipe")
    digest(build["overrides"]["recipe_sha256"])
    environment = fields(value["environment"], "os arch kernel cpu_model logical_cpus memory_total_bytes virtualization allocator cpu_policy load_before")
    require(environment["os"].lower() == "linux", "paired-requires-linux-observations")
    for key in ("os", "arch", "kernel", "cpu_model"):
        text(environment[key])
    require(uint(environment["logical_cpus"]) > 0 and uint(environment["memory_total_bytes"]) > 0, "missing-host-capacity")
    for key in ("virtualization", "allocator", "cpu_policy"):
        require(isinstance(environment[key], dict), "missing-host-control")
        bounded_tree(environment[key])
    load = environment["load_before"]
    import math
    require(isinstance(load, list) and len(load) == 3 and all(type(item) in (int, float)
            and math.isfinite(item) and item >= 0 for item in load), "invalid-paired-load")
    binary = fields(value["binary"], "sha256 bytes")
    digest(binary["sha256"])
    require(0 < uint(binary["bytes"]) <= 1024**3, "paired-binary-size")
    require(isinstance(value["fixtures"], list) and len(value["fixtures"]) == 1, "paired-requires-one-echo-fixture")
    fixture = fields(value["fixtures"][0], "name sha256 bytes")
    require(fixture["name"] == "echo" and 0 < uint(fixture["bytes"]) <= RAW_LIMIT, "invalid-paired-echo-fixture")
    digest(fixture["sha256"])


def host_controls(value):
    return {key: item for key, item in value.items() if key != "load_before"}


def build_controls(value):
    # The executable vs libtest entrypoint is observed treatment topology.
    return dict(value, overrides={key: item for key, item in value["overrides"].items() if key != "collector_surface"})
