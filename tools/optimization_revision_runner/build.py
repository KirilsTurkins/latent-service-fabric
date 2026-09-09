"""Build immutable refs as-is at one owned path; share client/CLI/component bytes."""
from __future__ import annotations

from contextlib import contextmanager
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


def matching_controls(repo: Path, refs: dict, controls=SOURCE_CONTROLS) -> None:
    for name in controls:
        if len({git(repo, "rev-parse", f"{ref}:{name}") for ref in refs.values()}) != 1:
            raise ValueError("revision-common-source-controls-differ:" + name)


def preflight_build_parent(target_parent: Path) -> Path:
    """A nested checkout would inherit all Cargo configuration above this path."""
    resolved = target_parent.resolve()
    for ancestor in (resolved, *resolved.parents):
        for name in ("config", "config.toml"):
            candidate = ancestor / ".cargo" / name
            if candidate.exists() or candidate.is_symlink():
                raise ValueError(
                    f"revision-build-parent-inherits-Cargo-config: {candidate}; "
                    "choose --target-root outside the repository and other Cargo-configured ancestors "
                    "(for example an external /tmp directory). The pinned build policy remains required."
                )
    return resolved


@contextmanager
def owned_checkout(repo: Path, first_ref: str, target_parent: Path, cleaned):
    """One registered source and target path, removed after every exit path."""
    parent = preflight_build_parent(target_parent)
    removed, temporary = False, None
    try:
        with tempfile.TemporaryDirectory(prefix="revision-build-owned-", dir=parent) as temporary:
            root, target = Path(temporary)/"source",Path(temporary)/"target"
            registered = False
            try:
                git(repo,"worktree","add","--detach",str(root),first_ref)
                registered = True
                yield root,target
            finally:
                # An interrupted add may have written its owned registration.
                if registered or (root/".git").exists():
                    if root.parent.resolve() != Path(temporary).resolve():
                        raise ValueError("revision-owned-worktree-path-mismatch")
                    git(repo,"worktree","remove","--force",str(root))
                    removed = True
    finally:
        cleaned(removed and temporary is not None and not Path(temporary).exists())


def build_one(root: Path, target: Path, label: str, output: Path, deadline: int, *,
              controls=SOURCE_CONTROLS, harness_command=None) -> dict:
    directory = output / "builds" / label
    directory.mkdir(parents=True)
    before = source(root)
    tracked = git(root, "ls-files").splitlines()
    inputs = [name for name in tracked if name.endswith("Cargo.toml") or name == "Cargo.lock"
              or any(name == parent or name.startswith(parent + "/") for parent in controls)]
    if not 1 <= len(inputs) <= 512:
        raise ValueError("revision-build-source-bound")
    retained = {name: legacy.retain(root / name, output, f"builds/{label}/source/{name}")
                for name in sorted(inputs)}
    names = {"client": "optimization-client", "cli": "latent"} if label == "harness" else {"server": "latentd"}
    for filename in names.values():
        (target / "release" / filename).unlink(missing_ok=True)
    argv = (harness_command or HARNESS_COMMAND) if label == "harness" else ["/bin/bash", "-eu", "-o", "pipefail", "-c", SERVER_RECIPE]
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
            suite: dict, save, backend_output: Path | None = None, *, selected=None) -> None:
    target_parent = preflight_build_parent(target_parent)
    options = {} if selected is None else {"controls": selected.SOURCE_CONTROLS,
                                          "harness_command": selected.HARNESS_COMMAND}
    matching_controls(repo, refs, **({} if selected is None else {"controls": selected.SOURCE_CONTROLS}))
    backend_receipt = None
    budget_backend = None
    if backend_output is not None:
        import copy
        from . import backend
        backend_output.mkdir(parents=True, exist_ok=False)
        if selected is not None:
            if selected.EXPERIMENT == "recovery":
                from . import recovery_build as budget_backend
            else:
                from . import budget_build as budget_backend
        backend_controls = backend.CONTROLS if budget_backend is None else budget_backend.CONTROLS
        for name in backend_controls:
            if len({git(repo, "rev-parse", f"{ref}:{name}") for ref in refs.values()}) != 1:
                raise ValueError("backend-collector-source-controls-differ:" + name)
        backend_receipt = {"schema": "latent.optimization.backend-builds.v1" if budget_backend is None else budget_backend.SCHEMA, "requested_refs": refs,
                           "build": copy.deepcopy(suite["identity"]["build"]), "builds": {}, "harness": None,
                           "cleanup": {"owned_worktree_removed": False}}
        backend_receipt["build"]["overrides"]["collector_surface"] = "libtest"
    def cleaned(removed):
        # A failed build still has a successful ownership receipt when both
        # Git registration and the private source/target directory were removed.
        if removed:
            suite["cleanup"]["owned_worktree_removed"] = True
            if backend_receipt is not None:
                backend_receipt["cleanup"]["owned_worktree_removed"] = True
                from .collect import write
                write(backend_output / "backend-builds.json", backend_receipt)
            save()
    with owned_checkout(repo,refs["control"],target_parent,cleaned) as (root,target):
        for label in ("control", "candidate", "harness"):
            if label != "control":
                git(root, "checkout", "--detach", refs[label])
            if source(root)["commit"] != refs[label]:
                raise ValueError("revision-source-ref-mismatch")
            suite["identity"]["builds"][label] = build_one(root, target, label, output, deadline, **options)
            if backend_receipt is not None:
                if label == "harness":
                    backend_receipt["harness"] = (backend.build_echo if budget_backend is None else budget_backend.generic)(
                        root, target, backend_output, deadline)
                else:
                    if budget_backend is None:
                        backend_receipt["builds"][label] = backend.build_backend(root, target, label, backend_output, deadline)
                    else:
                        backend_receipt["builds"][label] = backend.build_libtest(
                            root, target, label, backend_output, deadline, "backend", budget_backend.CONTROLS)
                from .collect import write
                write(backend_output / "backend-builds.json", backend_receipt)
            save()
