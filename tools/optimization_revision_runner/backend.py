"""Optional diagnostic inputs in a separate archive root; no diagnostic execution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from tools import run_optimization_benchmarks as legacy
from tools.artifact_identity_runner.helpers import command
from .build import git, source

CONTROLS = ("apps/latentd/src/standalone/measurements/comparison", "tools/build_echo_capsule.py",
            "tools/toolchain-smoke/examples/echo_capsule", "examples/echo-contract", "tools/toolchain.toml")
# Retain these when present; only the new cold replay requires equality. Older
# exact-source warm collectors and immutable receipts remain valid unchanged.
COLD_CONTROLS = ("crates/latent-wasmtime/src/preparation_observer/cpu.rs",
                 "crates/latent-wasmtime/src/preparation_observer/model.rs")
RECIPE = ("source tools/phase0_build_environment.sh; phase0_reject_inherited_build_overrides; "
          "phase0_reject_hidden_cargo_configuration; phase0_release_cargo test --release --locked "
          "-p latentd --lib --no-run --message-format=json")


def inputs(root, label, output, extra_controls=()):
    names = [name for name in git(root, "ls-files").splitlines()
             if name.endswith("Cargo.toml") or name in ("Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml",
                                                       "tools/phase0_build_environment.sh")
             or any(name == prefix or name.startswith(prefix + "/") for prefix in (*CONTROLS,*COLD_CONTROLS,*extra_controls))]
    if not 1 <= len(names) <= 512:
        raise ValueError("backend-build-input-bound")
    return {name: legacy.retain(root / name, output, f"builds/{label}/source/{name}") for name in names}


def build_backend(root: Path, target: Path, label: str, output: Path, deadline: int) -> dict:
    return build_libtest(root, target, label, output, deadline, "backend")


LIBTESTS = {"backend": ("latentd", "latentd", "latentd-backend-collector"),
            "lookup": ("latent-wasmtime", "latent_wasmtime", "latent-wasmtime-cache-lookup")}


def libtest_recipe(kind):
    if kind not in LIBTESTS:
        raise ValueError("unsupported-libtest-build-target")
    return RECIPE.replace("-p latentd ", "-p " + LIBTESTS[kind][0] + " ")


def build_libtest(root: Path, target: Path, label: str, output: Path, deadline: int,
                  kind: str, extra_controls=()) -> dict:
    recipe = libtest_recipe(kind)
    _, target_name, filename = LIBTESTS[kind]
    directory = output / "builds" / label
    directory.mkdir(parents=True)
    before = source(root)
    retained = inputs(root, label, output, extra_controls)
    argv = ["/bin/bash", "-eu", "-o", "pipefail", "-c", recipe]
    receipt = command(argv, directory / "build.log", 3600, root, deadline,
                      dict(os.environ, CARGO_TARGET_DIR=str(target)))
    matches = []
    for line in (directory / "build.log").read_bytes().splitlines():
        try:
            row = json.loads(line)
        except (UnicodeError, ValueError):
            continue
        if (isinstance(row, dict) and row.get("reason") == "compiler-artifact" and row.get("executable")
                and row.get("profile", {}).get("test") and row.get("target", {}).get("name") == target_name):
            matches.append(Path(row["executable"]).resolve())
    if len(matches) != 1 or not matches[0].is_relative_to(target.resolve()):
        raise ValueError("backend-cargo-executable-selection")
    binary = legacy.retain(matches[0], output, f"builds/{label}/{filename}")
    (output / binary["path"]).chmod(0o755)
    after = source(root)
    if before != after:
        raise ValueError("backend-build-source-changed")
    return {"source": before, "source_after": after, "inputs": retained, "executables": {kind: binary},
            "command": argv, "process": receipt, "log": legacy.ref(directory / "build.log", output),
            "source_path": str(root), "target_path": str(target)}


def build_echo(root: Path, target: Path, output: Path, deadline: int, extra_controls=()) -> dict:
    directory = output / "builds" / "harness"
    directory.mkdir(parents=True)
    before = source(root)
    retained = inputs(root, "harness", output, extra_controls)
    argv = [str(Path(sys.executable).resolve()), "tools/build_echo_capsule.py", "--verify-reproducible"]
    receipt = command(argv, directory / "build.log", 3600, root, deadline,
                      dict(os.environ, CARGO_TARGET_DIR=str(target)))
    echo = {name: legacy.retain(target / "capsules/echo" / filename, output, "echo/" + filename)
            for name, filename in (("component", "echo-capsule.wasm"), ("capsule", "capsule.json"),
                                   ("contracts", "contracts.json"), ("deployment", "deployment.json"), ("build", "build.json"))}
    after = source(root)
    if before != after:
        raise ValueError("echo-build-source-changed")
    return {"source": before, "source_after": after, "inputs": retained, "echo": echo,
            "command": argv, "process": receipt, "log": legacy.ref(directory / "build.log", output),
            "source_path": str(root), "target_path": str(target)}
