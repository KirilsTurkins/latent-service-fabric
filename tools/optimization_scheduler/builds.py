"""Exact libtest build receipts and source-identical scheduler measurement closure."""
from tools.optimization_evidence.common import fields, require, text, uint
from tools.optimization_evidence.resources import clean, process
from tools.optimization_revision_evidence.identity import source
from tools.optimization_revision_runner import backend
from tools.optimization_revision_runner.build import validate_refs
from tools.optimization_cache_lookup.builds import settings

SCHEMA = "latent.optimization.scheduler-builds.v1"
PYTHON_INPUTS = ("tools/optimization_scheduler", "tools/build_optimization_scheduler.py",
                "tools/run_optimization_scheduler.py", "tools/validate_optimization_scheduler.py",
                "tools/optimization_cache_lookup", "tools/optimization_evidence",
                "tools/optimization_revision_runner", "tools/optimization_revision_evidence",
                "tools/artifact_identity_runner", "tools/artifact_identity_evidence",
                "tools/optimization_runner", "tools/phase1_evidence",
                "tools/phase1_measurement_environment.py", "tools/run_optimization_benchmarks.py",
                "tools/run_phase1_conformance.py", "tools/validate_phase1_conformance.py",
                "tools/phase1_compiler_shutdown.py", "tools/phase1_cleanup_shutdown.py",
                "tools/optimization_backend_revision/ownership/allocations.py",
                "tools/optimization_backend_revision/ownership/model.py",
                "tools/package_phase1_evidence.py", "tools/validate_phase1_archive.py")
COMMON = ("Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml", "tools/phase0_build_environment.sh",
          "crates/latent-scheduler/Cargo.toml", "crates/latent-scheduler/src/local/measurement.rs",
          "crates/latent-scheduler/src/local/measurement", "crates/latent-scheduler/src/local/work.rs",
          *PYTHON_INPUTS)


def controlled(inputs):
    result = {}
    for prefix in COMMON:
        selected = {name: (row["sha256"], row["bytes"]) for name, row in inputs.items()
                    if name == prefix or name.startswith(prefix + "/")}
        require(selected, "scheduler-common-source-missing:" + prefix)
        result.update(selected)
    return result


def validate(value, artifacts, profile):
    fields(value, "schema requested_refs build builds harness cleanup")
    require(value["schema"] == SCHEMA, "scheduler-build-schema")
    validate_refs(value["requested_refs"], profile)
    settings(value["build"])
    require(value["cleanup"] == {"owned_worktree_removed": True}, "scheduler-build-worktree-not-removed")
    fields(value["builds"], "control candidate")
    paths, controls = set(), []
    for label, build in (*value["builds"].items(), ("harness", value["harness"])):
        common = "source source_after inputs source_path target_path"
        fields(build, common if label == "harness" else common + " command process log executables")
        if label != "harness":
            require(build["command"] == ["/bin/bash", "-eu", "-o", "pipefail", "-c", backend.libtest_recipe("scheduler")],
                    "scheduler-libtest-command")
            fields(build["executables"], "scheduler")
            binary = build["executables"]["scheduler"]
            require(binary["path"] == f"builds/{label}/{backend.LIBTESTS['scheduler'][2]}" and uint(binary["bytes"]) > 0,
                    "scheduler-executable-path")
            artifacts.path(binary)
            owner = build["process"]
            process(owner, "artifact-identity-helper", owner["executable_sha256"])
            require(clean(owner), "scheduler-build-process-not-clean")
            artifacts.path(build["log"])
            sidecar = build["log"]["path"] + ".process.json"
            require(sidecar in artifacts.rows and artifacts.json(artifacts.rows[sidecar]) == owner,
                    "scheduler-unbound-build-receipt")
        source(build["source"])
        require(build["source"] == build["source_after"] and build["source"]["commit"] == value["requested_refs"][label],
                "scheduler-source-build-mismatch")
        paths.add((text(build["source_path"]), text(build["target_path"])))
        inputs = build["inputs"]
        require(isinstance(inputs, dict) and 1 <= len(inputs) <= 512, "scheduler-build-input-count")
        for name, row in inputs.items():
            require(row["path"] == f"builds/{label}/source/{name}", "scheduler-source-input-path")
            artifacts.path(row)
        require(inputs["Cargo.lock"]["sha256"] == build["source"]["cargo_lock_sha256"]
                and inputs["tools/phase0_build_environment.sh"]["sha256"] == value["build"]["overrides"]["recipe_sha256"],
                "scheduler-recipe-or-lock-not-bound")
        controls.append(controlled(inputs))
    require(len(paths) == 1 and controls[0] == controls[1] == controls[2], "scheduler-common-source-or-build-paths-differ")
    return value


def identity(value, variant, environment):
    return {"source": value["builds"][variant]["source"], "build": value["build"], "environment": environment,
            "binary": value["builds"][variant]["executables"]["scheduler"]}
