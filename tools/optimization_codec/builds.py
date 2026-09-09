"""Exact common codec probe, type fixture, clock, recipe and source identities."""
from tools.optimization_evidence.common import fields, require, text, uint
from tools.optimization_evidence.resources import clean, process
from tools.optimization_revision_evidence.identity import source
from tools.optimization_revision_runner import backend
from tools.optimization_revision_runner.build import validate_refs

SCHEMA = "latent.optimization.codec-builds.v1"
from tools.optimization_revision_runner.codec_build import CONTROLS as COMMON


def controlled(inputs):
    result = {}
    # A split measurement implementation directory is optional; its complete
    # membership must still match if present in any arm.
    for prefix in COMMON:
        selected = {name: (row["sha256"], row["bytes"]) for name, row in inputs.items()
                    if name == prefix or name.startswith(prefix + "/")}
        require(selected or prefix.endswith("/tests/measurement"), "codec-common-source-missing:" + prefix)
        result.update(selected)
    return result


def settings(value):
    fields(value, "profile rustc cargo wasmtime target overrides")
    expected = {"recipe": "tools/phase0_build_environment.sh:phase0_release_cargo", "opt_level": "3", "debug": "1",
                "codegen_units": "16", "lto": "false", "debug_assertions": "false", "overflow_checks": "false",
                "incremental": "false", "panic": "unwind", "strip": "none", "path_remap": "source-target-cargo-home-v1",
                "linker_build_id": "sha1", "promoted_locals": "source-filename", "collector_surface": "libtest"}
    require(value["profile"] == "release" and set(value["overrides"]) == set(expected) | {"recipe_sha256"}
            and all(value["overrides"][key] == item for key, item in expected.items()), "codec-build-recipe-changed")
    for name in ("rustc", "cargo", "wasmtime", "target"):
        text(value[name])


def validate(value, artifacts, profile):
    fields(value, "schema requested_refs build builds harness cleanup")
    require(value["schema"] == SCHEMA, "codec-build-schema")
    validate_refs(value["requested_refs"], profile)
    settings(value["build"])
    require(value["cleanup"] == {"owned_worktree_removed": True}, "codec-build-worktree-not-removed")
    fields(value["builds"], "control candidate")
    paths, controls = set(), []
    executable_kind = "codec"
    for label, build in (*value["builds"].items(), ("harness", value["harness"])):
        shared = "source source_after inputs source_path target_path"
        if label == "harness":
            fields(build, shared)
        else:
            fields(build, shared + " command process log executables")
            require(build["command"] == ["/bin/bash", "-eu", "-o", "pipefail", "-c", backend.libtest_recipe(executable_kind)],
                    "codec-libtest-command")
            fields(build["executables"], executable_kind)
            row = build["executables"][executable_kind]
            require(row["path"] == f"builds/{label}/{backend.LIBTESTS[executable_kind][2]}" and uint(row["bytes"]) > 0,
                    "codec-executable-path")
            artifacts.path(row)
            owner = build["process"]
            process(owner, "artifact-identity-helper", owner["executable_sha256"])
            require(clean(owner), "codec-build-process-not-clean")
            artifacts.path(build["log"])
            sidecar = build["log"]["path"] + ".process.json"
            require(sidecar in artifacts.rows and artifacts.json(artifacts.rows[sidecar]) == owner, "codec-unbound-build-receipt")
        source(build["source"])
        require(build["source"] == build["source_after"] and build["source"]["commit"] == value["requested_refs"][label],
                "codec-source-build-mismatch")
        paths.add((text(build["source_path"]), text(build["target_path"])))
        inputs = build["inputs"]
        require(isinstance(inputs, dict) and 1 <= len(inputs) <= 512, "codec-input-count")
        for name, row in inputs.items():
            require(row["path"] == f"builds/{label}/source/{name}", "codec-input-path")
            artifacts.path(row)
        require(inputs["Cargo.lock"]["sha256"] == build["source"]["cargo_lock_sha256"]
                and inputs["tools/phase0_build_environment.sh"]["sha256"] == value["build"]["overrides"]["recipe_sha256"],
                "codec-recipe-or-lock-not-bound")
        controls.append(controlled(inputs))
    require(len(paths) == 1 and controls[0] == controls[1] == controls[2], "codec-common-source-or-build-paths-differ")
    return value


def identity(value, variant, environment):
    kind = "codec"
    return {"source": value["builds"][variant]["source"], "build": value["build"], "environment": environment,
            "binary": value["builds"][variant]["executables"][kind]}
