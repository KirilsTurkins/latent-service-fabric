#!/usr/bin/env python3
"""Replay every reviewed Rust Cargo recipe cold and twice dependency-warm.

Destructive work is restricted to a newly created target in an explicitly
acknowledged disposable checkout. This measures local dependency archive costs,
not GitHub cache-service transfer. It cannot promote an optimization by itself.
Release/calibration profiles, required CI topology, and shared caches are untouched.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import aot_test_inputs, ci_cargo, ci_cargo_cache
from tools import ci_cargo_observe as observations
from tools import ci_suite_discovery as discovery, ci_suite_inventory as registry
from tools.owned_test_process import ProcessFailure, run_owned

MAX_ARCHIVE_BYTES = 16 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 100000
CACHE_PATHS = ("debug/.fingerprint", "debug/build", "debug/deps")
STATES = ("cold", "warm-1", "warm-2")


def checked(argv: list[str], repo: Path, env: dict[str, str], *, timeout: int = 300) -> bytes:
    result = run_owned(argv, cwd=repo, env=env, timeout=timeout, maximum=observations.MAX_BYTES)
    if result.returncode:
        raise ProcessFailure("assertion-failure", "evaluation-command-failed", result)
    return result.output


def hashed_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def cache_archive(target: Path, archive: Path, packages: list[str]) -> dict:
    """Snapshot a fresh, pruned private target; never save test outputs or credentials."""
    began = time.monotonic()
    if any(p.is_symlink() for p in (target, *target.parents, archive, *archive.parents)):
        raise ValueError("linked-dependency-archive-path")
    aliases = {alias for name in packages for alias in (name, name.replace("-", "_"))}
    files, size = [], 0
    for prefix in CACHE_PATHS:
        root = target / prefix
        if root.is_symlink() or root.parent.is_symlink():
            raise ValueError("linked-dependency-cache-root")
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("linked-or-special-dependency-cache-product")
            if not path.is_file():
                continue
            relative = path.relative_to(target).as_posix()
            if any(re.match(r"^(?:lib)?" + re.escape(alias) + r"(?:-[0-9a-f]{6,}|\.|$)", part)
                   for alias in aliases for part in Path(relative).parts):
                raise ValueError("workspace-product-survived-cargo-clean")
            size += path.stat().st_size
            files.append(path)
            if len(files) > MAX_ARCHIVE_FILES or size > MAX_ARCHIVE_BYTES:
                raise ValueError("dependency-cache-archive-limit")
    if not files:
        raise ValueError("empty-dependency-cache-archive")
    # Cargo can hard-link regular dependency products. Snapshot each file's
    # bytes so the archive never needs link entries, which restore rejects.
    with tarfile.open(archive, "w:gz", compresslevel=1, dereference=True) as output:
        for path in sorted(files):
            output.add(path, arcname=path.relative_to(target).as_posix(), recursive=False)
    digest = hashed_file(archive)
    return {"seconds": time.monotonic() - began, "files": len(files),
            "uncompressedBytes": size, "archiveBytes": archive.stat().st_size,
            "sha256": digest}


def restore(target: Path, archive: Path, expected: str) -> dict:
    began = time.monotonic()
    if (any(p.is_symlink() for p in (target, *target.parents, archive, *archive.parents))
            or target.exists() or not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES):
        raise ValueError("unsafe-dependency-restore")
    if hashed_file(archive) != expected:
        raise ValueError("dependency-archive-integrity-failure")
    with tarfile.open(archive, "r:gz") as source:
        members, names, size = [], set(), 0
        for member in source:
            path = Path(member.name)
            if (len(members) >= MAX_ARCHIVE_FILES or not member.isfile() or member.size < 0
                    or member.name != path.as_posix() or path.is_absolute() or ".." in path.parts
                    or member.name in names or not any(path.is_relative_to(prefix) for prefix in CACHE_PATHS)):
                raise ValueError("unsafe-dependency-archive-member")
            size += member.size
            if size > MAX_ARCHIVE_BYTES:
                raise ValueError("expanded-dependency-archive-limit")
            names.add(member.name)
            members.append(member)
        if not members:
            raise ValueError("empty-dependency-cache-archive")
        target.mkdir()
        source.extractall(target, members=members, filter="data")
    return {"seconds": time.monotonic() - began, "archiveBytes": archive.stat().st_size,
            "uncompressedBytes": size, "files": len(members)}


def exact_discovery(receipt: dict) -> dict:
    return {"activeCases": receipt["activeCases"], "suites": [
        {key: suite[key] for key in ("id", "cases", "ignored", "contract", "successMarker") if key in suite}
        for suite in receipt["suites"]]}


def overlaps(observed: list[dict]) -> dict:
    owners: dict[str, list[str]] = {}
    for item in observed:
        for unit in item["units"]:
            owners.setdefault(unit["identity"], []).append(item["invocation"]["name"])
    shared = {key: sorted(set(value)) for key, value in owners.items() if len(set(value)) > 1}
    return {"sharedArtifactIdentities": shared, "commandEliminations": [],
            "interpretation": "shared artifacts are reuse, not equivalent check/clippy/test coverage"}


def evaluate(repo: Path, output: Path, configuration: str) -> dict:
    repo = repo.resolve()
    target = repo / "target"
    if target.exists() or target.is_symlink():
        raise ValueError("evaluation-requires-disposable-checkout-with-no-target")
    if Path(os.path.abspath(output)).is_relative_to(repo):
        raise ValueError("evaluation-diagnostics-must-be-outside-checkout")
    output = observations.output_directory(output, repo)
    env = dict(os.environ)
    if any(env.get(key) for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR", "LSF_AOT_TEST_INPUTS", "LSF_AOT_TEST_EXECUTION_ONLY")):
        raise ValueError("evaluation-requires-clean-build-environment")
    # This is the same non-incremental setting installed by the pinned CI toolchain action.
    env["CARGO_INCREMENTAL"] = "0"
    record = {"schemaVersion": "latent.ci.cargo-evaluation.v1", "passed": False,
              "scope": "all-reviewed-rust-cargo-recipes-with-authenticated-aot-and-suite-discovery",
              "configuration": configuration, "samples": [], "eligibleForDefaultPromotion": False,
              "cacheBackend": "local-tar-gzip-dependency-products-not-GitHub-cache",
              "sharedCacheWrites": False, "networkTransferSeconds": None,
              "excluded": ["downstream-renderer-and-provider-qualification", "release-and-resource-calibration", "msrv-job"]}
    try:
        record["cacheIdentity"] = ci_cargo_cache.observe(repo, configuration, "rust", env)
        metadata = json.loads(checked(["cargo", "metadata", "--locked", "--no-deps", "--format-version=1"], repo, env))
        workspace = set(metadata["workspace_members"])
        packages = sorted(package["name"] for package in metadata["packages"] if package["id"] in workspace)
        if not packages or len(packages) > 256:
            raise ValueError("invalid-workspace-pruning-selection")
        if metadata["target_directory"] != str(target):
            raise ValueError("evaluation-target-override")
        data = registry.load()
        record["recipes"] = [asdict(invocation) for recipe in ci_cargo.RUST_RECIPES for invocation in ci_cargo.RECIPES[recipe]]
        expected = None
        with tempfile.TemporaryDirectory(prefix="lsf-cargo-evaluation-") as private_directory:
            archive = Path(private_directory) / "dependencies.tar.gz"
            for state in STATES:
                sample = {"state": state, "passed": False, "restore": None, "save": None}
                record["samples"].append(sample)
                if state == "cold":
                    target.mkdir()
                else:
                    # The target did not exist when this invocation took ownership.
                    if target.is_symlink() or target.parent != repo:
                        raise ValueError("evaluation-target-ownership-changed")
                    shutil.rmtree(target)
                    sample["restore"] = restore(target, archive, saved["sha256"])
                began = time.monotonic()
                observed = []
                inv_env = dict(env)
                sample_output = output / state
                inventory = sample_output / "inventory.jsonl"
                for recipe in ci_cargo.RUST_RECIPES:
                    for invocation in ci_cargo.RECIPES[recipe]:
                        print("Cargo evaluation: " + state + ":" + invocation.name, flush=True)
                        item = observations.observe(invocation, repo=repo, output=sample_output / invocation.name,
                            environment=inv_env, configuration=configuration,
                            inventory=inventory if invocation.inventory else None, timeout=7200)
                        observed.append(item)
                    if recipe == "prepare":
                        start = time.monotonic()
                        receipt = discovery.discover(repo, inventory, data)
                        current = exact_discovery(receipt)
                        if expected is not None and current != expected:
                            raise ValueError("cold-warm-test-identity-mismatch")
                        expected = current
                        observations.atomic_json(sample_output / "discovery.json", receipt)
                        sample["discoverySeconds"] = time.monotonic() - start
                        sample["caseIdentityDigest"] = ci_cargo_cache.canonical_digest(current)
                        sample["activeCases"] = current["activeCases"]
                        start = time.monotonic()
                        manifest = aot_test_inputs.prepare(repo, inventory, Path(private_directory) / ("aot-" + state))
                        validated = aot_test_inputs.validate(repo, manifest)
                        inv_env.update({key: value for key, value in aot_test_inputs.environment(manifest, validated).items()
                                        if key.startswith("LSF_AOT_")})
                        sample["aotPreparationSeconds"] = time.monotonic() - start
                    if recipe == "test":
                        for invocation, owner in zip(ci_cargo.RECIPES[recipe], (None, "explicit-doctests", "signing-compatibility"), strict=True):
                            raw = (sample_output / invocation.name / "cargo.log").read_text()
                            if owner is None:
                                discovery.validate_custom_execution(data, raw)
                            else:
                                discovery.validate_recipe_execution(data, owner, raw)
                sample["completedSuiteSeconds"] = time.monotonic() - began
                sample["observations"] = [str(Path(state) / item["invocation"]["name"] / "observation.json") for item in observed]
                sample["builtArtifactRecords"] = sum(item["builtArtifactRecords"] for item in observed)
                sample["freshArtifactRecords"] = sum(item["freshArtifactRecords"] for item in observed)
                sample["overlap"] = overlaps(observed)
                if state == "cold":
                    start = time.monotonic()
                    checked(["cargo", "clean", *[argument for package in packages for argument in ("--package", package)]], repo, env)
                    sample["pruneSeconds"] = time.monotonic() - start
                    saved = cache_archive(target, archive, packages)
                    sample["save"] = saved
                sample["passed"] = True
                observations.atomic_json(output / "evaluation.json", record)
        record["passed"] = True
    finally:
        # Keep attempted products for local debugging. No shared or pre-existing target is deleted.
        active_error = sys.exc_info()[0]
        try:
            observations.atomic_json(output / "evaluation.json", record)
        except (OSError, ValueError) as error:
            print("Cargo evaluation export failed: " + type(error).__name__, file=sys.stderr)
            if active_error is None:
                raise
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--configuration", choices=ci_cargo.CONFIGURATIONS, default="current")
    parser.add_argument("--disposable-checkout", action="store_true", required=True)
    args = parser.parse_args()
    try:
        evaluate(ci_cargo.ROOT, args.output, args.configuration)
        return 0
    except (ProcessFailure, OSError, ValueError, tarfile.TarError) as error:
        print("Cargo recipe evaluation failed: " + str(error), file=sys.stderr)
        if isinstance(error, ProcessFailure) and error.result and error.result.returncode:
            return error.result.returncode if error.result.returncode > 0 else 128 - error.result.returncode
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
