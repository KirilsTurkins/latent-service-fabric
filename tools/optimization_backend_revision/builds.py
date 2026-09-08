"""Validate the separately retained same-source collector build receipt."""
from tools.optimization_evidence.common import fields, require, text, uint
from tools.optimization_evidence.resources import process, clean
from tools.optimization_revision_evidence.identity import source
from tools.optimization_revision_runner.backend import CONTROLS, RECIPE
from tools.optimization_revision_runner.build import validate_refs


def validate_experiment(value,artifacts,profile,experiment):
    require(experiment in ("warm","cold"), "backend-experiment-selection")
    validate(value,artifacts,profile)
    if experiment == "cold":
        from tools.optimization_revision_runner.backend import COLD_CONTROLS
        controlled=[]
        for build in (*value["builds"].values(),value["harness"]):
            require(all(name in build["inputs"] for name in COLD_CONTROLS), "cold-cpu-source-proof-missing")
            controlled.append({name:(build["inputs"][name]["sha256"],build["inputs"][name]["bytes"])
                               for name in COLD_CONTROLS})
        require(controlled[0] == controlled[1] == controlled[2], "cold-cpu-source-controls-differ")
    return value


def validate(value, artifacts, profile):
    fields(value, "schema requested_refs build builds harness cleanup")
    require(value["schema"] == "latent.optimization.backend-builds.v1", "invalid-backend-build-schema")
    validate_refs(value["requested_refs"], profile)
    require(value["cleanup"] == {"owned_worktree_removed": True}, "backend-build-worktree-not-removed")
    fields(value["builds"], "control candidate")
    settings = fields(value["build"], "profile rustc cargo wasmtime target overrides")
    require(settings["profile"] == "release" and settings["overrides"]["collector_surface"] == "libtest",
            "backend-requires-release-libtest")
    expected_options = {"recipe": "tools/phase0_build_environment.sh:phase0_release_cargo", "opt_level": "3", "debug": "1",
                        "codegen_units": "16", "lto": "false", "debug_assertions": "false", "overflow_checks": "false",
                        "incremental": "false", "panic": "unwind", "strip": "none", "path_remap": "source-target-cargo-home-v1",
                        "linker_build_id": "sha1", "promoted_locals": "source-filename", "collector_surface": "libtest"}
    require(set(settings["overrides"]) == set(expected_options) | {"recipe_sha256"}
            and all(settings["overrides"][name] == item for name, item in expected_options.items()), "backend-release-settings-changed")
    for name in ("rustc", "cargo", "wasmtime", "target"):
        text(settings[name])
    paths, controls = set(), []
    for label, build in (*value["builds"].items(), ("harness", value["harness"])):
        fields(build, "source source_after inputs command process log source_path target_path "
               + ("echo" if label == "harness" else "executables"))
        source(build["source"])
        require(build["source"] == build["source_after"]
                and build["source"]["commit"] == value["requested_refs"][label], "backend-source-build-mismatch")
        paths.add((text(build["source_path"]), text(build["target_path"])))
        argv = build["command"]
        if label == "harness":
            require(isinstance(argv, list) and len(argv) == 3 and argv[1:] == ["tools/build_echo_capsule.py", "--verify-reproducible"],
                    "backend-echo-build-command")
        else:
            require(argv == ["/bin/bash", "-eu", "-o", "pipefail", "-c", RECIPE], "backend-collector-build-command")
        owner = build["process"]
        process(owner, "artifact-identity-helper", owner["executable_sha256"])
        require(clean(owner), "backend-build-process-not-clean")
        artifacts.path(build["log"])
        sidecar = build["log"]["path"] + ".process.json"
        require(sidecar in artifacts.rows and artifacts.json(artifacts.rows[sidecar]) == owner, "backend-build-receipt-not-bound")
        inputs = build["inputs"]
        require(isinstance(inputs, dict) and 1 <= len(inputs) <= 512, "backend-input-bound")
        for name, row in inputs.items():
            require(row["path"] == f"builds/{label}/source/{name}", "backend-input-path")
            artifacts.path(row)
        required = (*CONTROLS, "rust-toolchain.toml", ".cargo/config.toml", "tools/phase0_build_environment.sh")
        shared = {}
        for prefix in required:
            selected = {name: (row["sha256"], row["bytes"]) for name, row in inputs.items()
                        if name == prefix or name.startswith(prefix + "/")}
            require(selected, "backend-shared-source-missing")
            shared.update(selected)
        controls.append(shared)
        require(inputs["Cargo.lock"]["sha256"] == build["source"]["cargo_lock_sha256"]
                and inputs["tools/phase0_build_environment.sh"]["sha256"] == settings["overrides"]["recipe_sha256"],
                "backend-unbound-recipe-or-lock")
        if label != "harness":
            fields(build["executables"], "backend")
            row = build["executables"]["backend"]
            require(uint(row["bytes"]) > 0, "empty-backend-executable")
            artifacts.path(row)
    require(len(paths) == 1 and controls[0] == controls[1] == controls[2], "backend-collector-inputs-or-paths-differ")
    echo = fields(value["harness"]["echo"], "component capsule contracts deployment build")
    for row in echo.values():
        artifacts.path(row)
    require(0 < uint(echo["component"]["bytes"]) <= 16 * 1024**2, "backend-echo-component-bound")
    capsule, deployment = (artifacts.json(echo[key]) for key in ("capsule", "deployment"))
    require(capsule["component"]["digest"] == deployment["spec"]["release"] == echo["component"]["sha256"],
            "backend-echo-metadata-not-bound")
    return value
