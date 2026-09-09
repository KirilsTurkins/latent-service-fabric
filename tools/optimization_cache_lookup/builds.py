"""Exact common inputs and separate cache lookup/behavior build receipts."""
from tools.optimization_evidence.common import fields, require, text, uint
from tools.optimization_evidence.resources import clean, process
from tools.optimization_revision_evidence.identity import source
from tools.optimization_revision_runner import backend
from tools.optimization_revision_runner.build import validate_refs

SCHEMA = "latent.optimization.cache-builds.v1"
LOOKUP_CONTROLS = ("crates/latent-wasmtime/src/cache/measurement.rs",
                   "crates/latent-wasmtime/src/cache/measurement",
                   "crates/latent-wasmtime/src/preparation_observer.rs",
                   "crates/latent-wasmtime/Cargo.toml")
RECIPE_CONTROLS = ("Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml", "tools/phase0_build_environment.sh")
COMMON = (*backend.CONTROLS, *backend.COLD_CONTROLS, *LOOKUP_CONTROLS, *RECIPE_CONTROLS)
PYTHON_INPUTS = ("tools/optimization_cache_lookup", "tools/build_optimization_cache_benchmarks.py",
                 "tools/run_optimization_cache_lookup.py", "tools/validate_optimization_cache_lookup.py",
                 "tools/optimization_backend_revision", "tools/optimization_revision_runner",
                 "tools/artifact_identity_runner", "tools/artifact_identity_evidence")


def controlled(inputs):
    result = {}
    # A split measurement implementation directory is optional; its complete
    # membership must still match if present in any arm.
    for prefix in COMMON:
        selected = {name: (row["sha256"], row["bytes"]) for name, row in inputs.items()
                    if name == prefix or name.startswith(prefix + "/")}
        require(selected or prefix.endswith("/cache/measurement"), "cache-common-source-missing:" + prefix)
        result.update(selected)
    return result


def settings(value):
    fields(value, "profile rustc cargo wasmtime target overrides")
    expected = {"recipe": "tools/phase0_build_environment.sh:phase0_release_cargo", "opt_level": "3", "debug": "1",
                "codegen_units": "16", "lto": "false", "debug_assertions": "false", "overflow_checks": "false",
                "incremental": "false", "panic": "unwind", "strip": "none", "path_remap": "source-target-cargo-home-v1",
                "linker_build_id": "sha1", "promoted_locals": "source-filename", "collector_surface": "libtest"}
    require(value["profile"] == "release" and set(value["overrides"]) == set(expected) | {"recipe_sha256"}
            and all(value["overrides"][key] == item for key, item in expected.items()), "cache-build-recipe-changed")
    for name in ("rustc", "cargo", "wasmtime", "target"):
        text(value[name])


def validate(value, artifacts, profile, kind):
    fields(value, "schema kind requested_refs build builds harness cleanup")
    require(value["schema"] == SCHEMA and value["kind"] == kind and kind in ("lookup", "behavior"), "cache-build-schema")
    validate_refs(value["requested_refs"], profile)
    settings(value["build"])
    require(value["cleanup"] == {"owned_worktree_removed": True}, "cache-build-worktree-not-removed")
    fields(value["builds"], "control candidate")
    paths, controls = set(), []
    executable_kind = "lookup" if kind == "lookup" else "backend"
    for label, build in (*value["builds"].items(), ("harness", value["harness"])):
        shared = "source source_after inputs source_path target_path"
        if label == "harness" and kind == "lookup":
            fields(build, shared)
        else:
            fields(build, shared + " command process log " + ("echo" if label == "harness" else "executables"))
            if label == "harness":
                require(isinstance(build["command"], list) and len(build["command"]) == 3
                        and build["command"][1:] == ["tools/build_echo_capsule.py", "--verify-reproducible"], "cache-echo-command")
            else:
                require(build["command"] == ["/bin/bash", "-eu", "-o", "pipefail", "-c", backend.libtest_recipe(executable_kind)],
                        "cache-libtest-command")
                fields(build["executables"], executable_kind)
                row = build["executables"][executable_kind]
                require(row["path"] == f"builds/{label}/{backend.LIBTESTS[executable_kind][2]}" and uint(row["bytes"]) > 0,
                        "cache-executable-path")
                artifacts.path(row)
            owner = build["process"]
            process(owner, "artifact-identity-helper", owner["executable_sha256"])
            require(clean(owner), "cache-build-process-not-clean")
            artifacts.path(build["log"])
            sidecar = build["log"]["path"] + ".process.json"
            require(sidecar in artifacts.rows and artifacts.json(artifacts.rows[sidecar]) == owner, "cache-unbound-build-receipt")
        source(build["source"])
        require(build["source"] == build["source_after"] and build["source"]["commit"] == value["requested_refs"][label],
                "cache-source-build-mismatch")
        paths.add((text(build["source_path"]), text(build["target_path"])))
        inputs = build["inputs"]
        require(isinstance(inputs, dict) and 1 <= len(inputs) <= 512, "cache-input-count")
        for name, row in inputs.items():
            require(row["path"] == f"builds/{label}/source/{name}", "cache-input-path")
            artifacts.path(row)
        require(inputs["Cargo.lock"]["sha256"] == build["source"]["cargo_lock_sha256"]
                and inputs["tools/phase0_build_environment.sh"]["sha256"] == value["build"]["overrides"]["recipe_sha256"],
                "cache-recipe-or-lock-not-bound")
        controls.append(controlled(inputs))
    require(len(paths) == 1 and controls[0] == controls[1] == controls[2], "cache-common-source-or-build-paths-differ")
    if kind == "behavior":
        echo = fields(value["harness"]["echo"], "component capsule contracts deployment build")
        for row in echo.values():
            artifacts.path(row)
        require(0 < uint(echo["component"]["bytes"]) <= 16 * 1024**2, "cache-echo-bound")
        capsule, deployment = (artifacts.json(echo[key]) for key in ("capsule", "deployment"))
        require(capsule["component"]["digest"] == deployment["spec"]["release"] == echo["component"]["sha256"],
                "cache-echo-metadata-crossed")
    return value


def identity(value, variant, environment):
    kind = "lookup" if value["kind"] == "lookup" else "backend"
    return {"source": value["builds"][variant]["source"], "build": value["build"], "environment": environment,
            "binary": value["builds"][variant]["executables"][kind]}
