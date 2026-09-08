"""Build two immutable refs as-is in one exclusively owned source path."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from .files import retain
from .helpers import command
from .model import BUILD_RECIPE, PAIRED_INPUTS, PROBE, PROBE_DIRECTORY

RECIPE = BUILD_RECIPE


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=60, check=False)
    if len(result.stdout) + len(result.stderr) > 2 * 1024 * 1024 or result.returncode:
        raise RuntimeError("git-inspection-failed")
    return result.stdout.decode("utf-8").strip()


def identity(root: Path) -> dict:
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("build-source-dirty")
    return {"commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"), "clean": True}


def matching_controls(root: Path, control: str, candidate: str) -> None:
    for name in PAIRED_INPUTS:
        if git(root, "rev-parse", f"{control}:{name}") != git(root, "rev-parse", f"{candidate}:{name}"):
            raise ValueError("paired-build-controls-differ")


def build_arm(source: Path, target: Path, arm: str, output: Path, deadline: int) -> dict:
    directory = output / "builds" / arm
    directory.mkdir(parents=True)
    before = identity(source)
    tracked = git(source, "ls-files").splitlines()
    probe_paths = [name for name in tracked if name == PROBE or name.startswith(PROBE_DIRECTORY + "/")]
    if PROBE not in probe_paths or len(probe_paths) > 64:
        raise ValueError("probe-source-missing-or-large")
    inputs = [name for name in tracked if name.endswith("Cargo.toml") or name in (
        "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml", "tools/phase0_build_environment.sh")]
    if len(inputs) > 128 or "Cargo.lock" not in inputs:
        raise ValueError("build-input-bound")
    retained = {name: retain(source / name, directory / "source" / name, output)
                for name in sorted(set(inputs + probe_paths))}
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    executable = target / "release" / "artifact-identity-probe"
    executable.unlink(missing_ok=True)
    argv = ["/bin/bash", "-eu", "-o", "pipefail", "-c", RECIPE]
    receipt = command(argv, directory / "build.log", 3600, source, deadline, env)
    after = identity(source)
    if before != after:
        raise ValueError("build-source-changed")
    binary = retain(executable, directory / "artifact-identity-probe", output)
    (output / binary["path"]).chmod(0o755)
    from .files import reference
    return {"source_before": before, "source_after": after, "binary": binary,
            "inputs": {name: retained[name] for name in inputs},
            "probe_sources": {name: retained[name] for name in probe_paths},
            "command": argv, "log": reference(directory / "build.log", output), "process": receipt,
            "source_path": str(source), "target_path": str(target)}


def validate_refs(control: str, candidate: str, profile: str) -> None:
    if any(re.fullmatch(r"[0-9a-f]{40}", ref) is None for ref in (control, candidate)):
        raise ValueError("refs-must-be-full-commit-identities")
    if profile == "full" and control == candidate:
        raise ValueError("full-requires-distinct-commits")
