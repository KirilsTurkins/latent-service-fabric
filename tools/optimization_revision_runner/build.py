"""Build immutable refs as-is at one owned path; share client/CLI/component bytes."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

from tools.artifact_identity_runner.build import git, identity
from tools.artifact_identity_runner.helpers import command
from tools.optimization_evidence.common import hash_file
from tools import run_optimization_benchmarks as legacy
from .model import CONTROL, HARNESS_COMMAND, SERVER_RECIPE, SOURCE_CONTROLS


def source(root: Path) -> dict:
    return {**identity(root), "cargo_lock_sha256": hash_file(root / "Cargo.lock", 16 * 1024**2)[0]}


def validate_refs(refs: dict, profile: str) -> None:
    if set(refs) != {"control", "candidate", "harness"} or any(
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None for value in refs.values()):
        raise ValueError("revision-refs-must-be-full-commit-identities")
    if profile == "full" and refs["candidate"] == refs["control"]:
        raise ValueError("full-requires-distinct-revisions")


def matching_controls(repo: Path, refs: dict) -> None:
    for name in SOURCE_CONTROLS:
        if len({git(repo, "rev-parse", f"{ref}:{name}") for ref in refs.values()}) != 1:
            raise ValueError("revision-common-source-controls-differ:" + name)


def build_one(root: Path, target: Path, label: str, output: Path, deadline: int) -> dict:
    directory = output / "builds" / label
    directory.mkdir(parents=True)
    before = source(root)
    tracked = git(root, "ls-files").splitlines()
    inputs = [name for name in tracked if name.endswith("Cargo.toml") or name == "Cargo.lock"
              or any(name == parent or name.startswith(parent + "/") for parent in SOURCE_CONTROLS)]
    if not 1 <= len(inputs) <= 512:
        raise ValueError("revision-build-source-bound")
    retained = {name: legacy.retain(root / name, output, f"builds/{label}/source/{name}")
                for name in sorted(inputs)}
    names = {"client": "optimization-client", "cli": "latent"} if label == "harness" else {"server": "latentd"}
    for filename in names.values():
        (target / "release" / filename).unlink(missing_ok=True)
    argv = HARNESS_COMMAND if label == "harness" else ["/bin/bash", "-eu", "-o", "pipefail", "-c", SERVER_RECIPE]
    receipt = command(argv, directory / "build.log", 3600, root, deadline,
                      dict(os.environ, CARGO_TARGET_DIR=str(target)))
    after = source(root)
    if before != after:
        raise ValueError("revision-source-changed-during-build")
    binaries = {name: legacy.retain(target / "release" / filename, output, f"builds/{label}/{filename}")
                for name, filename in names.items()}
    for row in binaries.values():
        (output / row["path"]).chmod(0o755)
    result = {"source": before, "source_after": after, "inputs": retained, "executables": binaries,
              "command": argv, "process": receipt, "log": legacy.ref(directory / "build.log", output),
              "source_path": str(root), "target_path": str(target)}
    if label == "harness":
        result["component"] = legacy.retain(target / "capsules/optimization/optimization-capsule.wasm",
                                            output, "builds/harness/optimization-capsule.wasm")
    return result


def collect(repo: Path, refs: dict, output: Path, target_parent: Path, deadline: int,
            suite: dict, save, backend_output: Path | None = None) -> None:
    matching_controls(repo, refs)
    backend_receipt = None
    if backend_output is not None:
        import copy
        from . import backend
        backend_output.mkdir(parents=True, exist_ok=False)
        for name in backend.CONTROLS:
            if len({git(repo, "rev-parse", f"{ref}:{name}") for ref in refs.values()}) != 1:
                raise ValueError("backend-collector-source-controls-differ:" + name)
        backend_receipt = {"schema": "latent.optimization.backend-builds.v1", "requested_refs": refs,
                           "build": copy.deepcopy(suite["identity"]["build"]), "builds": {}, "harness": None,
                           "cleanup": {"owned_worktree_removed": False}}
        backend_receipt["build"]["overrides"]["collector_surface"] = "libtest"
    with tempfile.TemporaryDirectory(prefix="revision-build-owned-", dir=target_parent) as temporary:
        root, target = Path(temporary) / "source", Path(temporary) / "target"
        registered = False
        try:
            git(repo, "worktree", "add", "--detach", str(root), refs["control"])
            registered = True
            for label in ("control", "candidate", "harness"):
                if label != "control":
                    git(root, "checkout", "--detach", refs[label])
                if source(root)["commit"] != refs[label]:
                    raise ValueError("revision-source-ref-mismatch")
                suite["identity"]["builds"][label] = build_one(root, target, label, output, deadline)
                if backend_receipt is not None:
                    if label == "harness":
                        backend_receipt["harness"] = backend.build_echo(root, target, backend_output, deadline)
                    else:
                        backend_receipt["builds"][label] = backend.build_backend(root, target, label, backend_output, deadline)
                    from .collect import write
                    write(backend_output / "backend-builds.json", backend_receipt)
                save()
        finally:
            if registered:
                if root.parent.resolve() != Path(temporary).resolve():
                    raise ValueError("revision-owned-worktree-path-mismatch")
                git(repo, "worktree", "remove", "--force", str(root))
    suite["cleanup"]["owned_worktree_removed"] = True
    if backend_receipt is not None:
        backend_receipt["cleanup"]["owned_worktree_removed"] = True
        from .collect import write
        write(backend_output / "backend-builds.json", backend_receipt)
