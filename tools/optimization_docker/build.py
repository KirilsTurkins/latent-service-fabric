"""One clean release build with an explicit reusable Cargo target directory."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import time

from tools.artifact_identity_runner.files import fingerprint, reference, retain, total_bytes, write_json
from tools.artifact_identity_runner.helpers import command
from tools.optimization_revision_runner.build import git, source
from tools.phase1_measurement_environment import build_configuration
from . import fixtures, images

SCHEMA = "latent.optimization.docker-builds.v1"
TARGET = Path("/workspace/project/target")
RECIPE = ["/bin/bash", "tools/build_optimization_bench.sh", "full"]
SOURCE_PREFIXES = ("crates", "apps/latent", "apps/latentd", "api", "wit", "schemas",
                   "examples", "tools/optimization-bench", "tools/optimization-workloads",
                   "tools/toolchain-smoke", "tools/optimization-docker")
SOURCE_FILES = ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml",
                "tools/phase0_build_environment.sh", "tools/build_optimization_bench.sh", "tools/toolchain.toml")
OVERRIDES = {"recipe": "tools/phase0_build_environment.sh:phase0_release_cargo",
             "opt_level": "3", "debug": "1", "codegen_units": "16", "lto": "false",
             "debug_assertions": "false", "overflow_checks": "false", "incremental": "false",
             "panic": "unwind", "strip": "none", "path_remap": "source-target-cargo-home-v1",
             "linker_build_id": "sha1", "promoted_locals": "source-filename",
             "collector_surface": "separate-container-app-and-persistent-client"}


def input_names(repository: Path) -> list[str]:
    tracked = git(repository, "ls-files").splitlines()
    names = sorted(name for name in tracked if name in SOURCE_FILES or name.endswith("Cargo.toml")
                   or name.startswith("tools/") and name.endswith(".py")
                   or any(name.startswith(prefix + "/") for prefix in SOURCE_PREFIXES))
    if not 1 <= len(names) <= 3500 or any(name not in names for name in SOURCE_FILES):
        raise ValueError("docker-build-source-input-bound")
    # Historical raw report archives are outside these source/control prefixes.
    if any(name.startswith("/") or ".." in Path(name).parts or "\\" in name for name in names):
        raise ValueError("docker-build-source-input-path")
    return names


def retain_inputs(repository: Path, output: Path) -> dict:
    names = input_names(repository)
    sizes = {name: fingerprint(repository / name)[1] for name in names}
    if sum(sizes.values()) + 32 * 1024**2 > 1024**3:
        raise ValueError("docker-build-input-total-bound")
    return {name: retain(repository / name, output / "source" / name, output) for name in names}


def validate_receipt(value: dict, output: Path) -> dict:
    """Exact local build receipt checks before image contexts can be materialized."""
    keys = {"schema", "source", "source_after", "source_path", "target_path", "build", "inputs",
            "executables", "component", "fixtures", "command", "process", "log"}
    if (not isinstance(value, dict) or set(value) != keys or value["schema"] != SCHEMA
            or value["source"] != value["source_after"] or value["source"].get("clean") is not True
            or re.fullmatch(r"[0-9a-f]{40}", value["source"].get("commit", "")) is None
            or value["target_path"] != TARGET.as_posix() or value["command"] != RECIPE
            or set(value["executables"]) != set(images.BINARIES)
            or not 1 <= len(value["inputs"]) <= 3500):
        raise ValueError("docker-build-receipt")
    process = value["process"]
    if (type(process.get("exit_code")) is not int or process["exit_code"] != 0 or process.get("reaped") is not True
            or process.get("output_closed") is not True):
        raise ValueError("docker-build-process-not-clean")
    from tools.optimization_evidence.common import read_json, verify_artifact
    for name, row in value["inputs"].items():
        if row["path"] != "source/" + name:
            raise ValueError("docker-build-input-reference")
        verify_artifact(output, row, 256 * 1024**2)
    for key, row in value["executables"].items():
        if row["path"] != "binaries/" + images.BINARIES[key]:
            raise ValueError("docker-build-executable-reference")
        verify_artifact(output, row, 256 * 1024**2)
    verify_artifact(output, value["component"], 16 * 1024**2)
    log = verify_artifact(output, value["log"], 16 * 1024**2)
    if read_json(log.with_suffix(log.suffix + ".process.json")) != process:
        raise ValueError("docker-build-process-sidecar")
    settings = value["build"]
    if (settings.get("profile") != "release"
            or set(settings["overrides"]) != set(OVERRIDES) | {"recipe_sha256", "optimization_recipe_sha256"}
            or any(settings["overrides"].get(key) != expected for key, expected in OVERRIDES.items())
            or settings["overrides"].get("recipe_sha256") != value["inputs"]["tools/phase0_build_environment.sh"]["sha256"]
            or settings["overrides"].get("optimization_recipe_sha256") != value["inputs"]["tools/build_optimization_bench.sh"]["sha256"]
            or value["source"]["cargo_lock_sha256"] != value["inputs"]["Cargo.lock"]["sha256"]):
        raise ValueError("docker-build-recipe-binding")
    total_bytes(output)
    return value


def execute(args, repository: Path) -> int:
    """Called explicitly by the owner; never create/check out/delete a worktree."""
    repository = repository.resolve()
    target, output = args.target_root.resolve(), args.output.resolve()
    if platform.system() != "Linux" or target != TARGET:
        raise ValueError("docker-build-requires-owned-linux-target")
    if (not isinstance(args.source_ref, str) or re.fullmatch(r"[0-9a-f]{40}", args.source_ref) is None
            or output.exists() or output.is_symlink() or output == target
            or any(output.is_relative_to(target / name) for name in ("release", "debug", "wasm32-unknown-unknown"))):
        raise ValueError("docker-build-ref-or-output")
    before = source(repository)
    if before["commit"] != args.source_ref:
        raise ValueError("docker-build-clean-source-ref-mismatch")
    if any(os.environ.get(key) for key in ("LD_PRELOAD", "LD_AUDIT", "MALLOC_CONF", "MALLOC_ARENA_MAX")):
        raise ValueError("docker-build-inherited-allocation-override")
    output.mkdir(parents=True)
    try:
        inputs = retain_inputs(repository, output)
        settings = build_configuration("full")
        settings["overrides"].update(collector_surface="separate-container-app-and-persistent-client",
                                     recipe_sha256=inputs["tools/phase0_build_environment.sh"]["sha256"],
                                     optimization_recipe_sha256=inputs["tools/build_optimization_bench.sh"]["sha256"])
        deadline = time.monotonic_ns() + 10800 * 10**9
        owner = command(RECIPE, output / "build.log", 10800, repository, deadline,
                        dict(os.environ, CARGO_TARGET_DIR=str(target)))
        paths = {key: target / "release" / name for key, name in images.BINARIES.items()}
        component = target / "capsules/optimization/optimization-capsule.wasm"
        sizes = sum(fingerprint(path)[1] for path in paths.values())
        component_size = fingerprint(component, 16 * 1024**2)[1]
        if total_bytes(output) + sizes + 33 * (component_size + 32) + 4 * 1024**2 > 1024**3:
            raise ValueError("docker-build-closure-total-bound")
        executables = {key: retain(path, output / "binaries" / path.name, output) for key, path in paths.items()}
        for row in executables.values():
            (output / row["path"]).chmod(0o755)
        component_ref = retain(component, output / "component.wasm", output)
        fixture = fixtures.materialize(output / "component.wasm", output / "fixtures", root=output, repository=repository)
        after = source(repository)
        if after != before:
            raise ValueError("docker-build-source-changed")
        value = {"schema": SCHEMA, "source": before, "source_after": after, "source_path": str(repository),
                 "target_path": str(target), "build": settings, "inputs": inputs, "executables": executables,
                 "component": component_ref, "fixtures": fixture, "command": RECIPE, "process": owner,
                 "log": reference(output / "build.log", output)}
        validate_receipt(value, output)
        write_json(output / "docker-builds.json", value)
        total_bytes(output)
    except BaseException as error:
        write_json(output / "failure.json", {"type": type(error).__name__, "message": str(error)[:2048]})
        return 1
    return 0
