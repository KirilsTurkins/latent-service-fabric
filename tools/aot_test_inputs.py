#!/usr/bin/env python3
"""Prepare exact AOT test executables; execution never builds or strips inputs.

This is a same-checkout, same-job recipe for the prepared-artifact boundary in
#428. It is not production compiler approval or a native sandbox qualification.
Cargo's originals are retained. Only immutable executable preparation is shared.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts

SCHEMA = "latent.aot-test-inputs.v1"
PROFILE = "debug-all-features-v1"
FEATURES = ("aot-test-timings",)
MAX_FILE = 512 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
HARNESS_NAMES = ("aot_supervisor", "isolated_aot", "native_aot_cache")
PREPARE = ("cargo test -p latent-wasmtime --all-features --locked --no-run "
           "--test aot_supervisor --test isolated_aot --test native_aot_cache "
           "--message-format=json > target/aot-tests.jsonl && "
           "python3 tools/aot_test_inputs.py prepare --inventory target/aot-tests.jsonl "
           "--output target/aot-test-inputs")


class InputError(ValueError):
    """A stable, bounded input/preparation failure."""


def read_json(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise InputError("manifest-limit")
    value = json.loads(raw, object_pairs_hook=artifacts.unique_object)
    if not isinstance(value, dict):
        raise InputError("invalid-manifest")
    return value


def exact_file(path: Path, *, executable: bool = False) -> Path:
    if not path.is_absolute() or len(str(path)) > 4096:
        raise InputError("noncanonical-file-path")
    if path.resolve(strict=True) != path or not stat.S_ISREG(path.lstat().st_mode):
        raise InputError("symlink-or-nonregular-file")
    size = path.stat().st_size
    if not 0 < size <= MAX_FILE:
        raise InputError("file-size-limit")
    if executable and not os.access(path, os.X_OK):
        raise InputError("file-not-executable")
    return path


def digest(path: Path) -> list[int]:
    exact_file(path)
    with path.open("rb") as stream:
        result = hashlib.file_digest(stream, "sha256").digest()
    return list(result)


def stamp(path: Path) -> dict:
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}


def check_stamp(record: dict, *, executable: bool = True) -> Path:
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "bytes"}:
        raise InputError("invalid-file-identity")
    if (not isinstance(record["path"], str) or not isinstance(record["bytes"], int)
            or not isinstance(record["sha256"], list) or len(record["sha256"]) != 32
            or any(type(value) is not int or not 0 <= value <= 255 for value in record["sha256"])):
        raise InputError("invalid-file-identity")
    path = exact_file(Path(record["path"]), executable=executable)
    if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
        raise InputError("changed-file-bytes")
    return path


def command_output(repo: Path, command: list[str]) -> str:
    status, output = artifacts.run_owned(command, cwd=repo, env=dict(os.environ),
                                        timeout=30, maximum=artifacts.MAX_INVENTORY_BYTES)
    if status:
        raise InputError("preparation-command-failed")
    return output.decode("utf-8").strip()


def checkout_identity(repo: Path) -> dict:
    # This observes the preparation checkout, not when a caller made an inventory.
    # Original executable hashes below bind the actual Cargo products separately.
    head = command_output(repo, ["git", "rev-parse", "--verify", "HEAD"])
    dirty = command_output(repo, ["git", "status", "--porcelain", "--untracked-files=no"])
    if dirty:
        raise InputError("prepare-requires-clean-tracked-checkout")
    return {"commit": head, "lock": stamp(repo / "Cargo.lock"),
            "toolchain": stamp(repo / "rust-toolchain.toml"),
            "target": [platform.system(), platform.machine()]}


def inventory_inputs(inventory: Path, repo: Path) -> tuple[dict, tuple[Path, ...]]:
    expected = repo / "crates/latent-wasmtime/Cargo.toml"
    target_root = (repo / "target/debug").resolve(strict=True)
    roles = {"compiler": ("latent-aot-compiler", "bin", False, "src/bin/latent-aot-compiler.rs")}
    roles.update({name: (name, "test", True, f"tests/{name}.rs") for name in HARNESS_NAMES})
    found: dict[str, dict] = {}
    links: set[Path] = set()
    size = count = 0
    finished = False
    with inventory.open("rb") as stream:
        while raw := stream.readline(artifacts.MAX_LINE_BYTES + 1):
            size += len(raw)
            count += 1
            if size > artifacts.MAX_INVENTORY_BYTES or count > artifacts.MAX_RECORDS or len(raw) > artifacts.MAX_LINE_BYTES:
                raise InputError("inventory-limit")
            if not raw.strip():
                continue
            if finished:
                raise InputError("inventory-after-finish")
            item = json.loads(raw, object_pairs_hook=artifacts.unique_object)
            if not isinstance(item, dict):
                raise InputError("invalid-cargo-record")
            if item.get("reason") == "build-finished":
                if item.get("success") is not True:
                    raise InputError("cargo-build-failed")
                finished = True
            elif item.get("reason") == "build-script-executed":
                linked = item.get("linked_paths", [])
                if not isinstance(linked, list) or len(linked) > artifacts.MAX_LINK_PATHS:
                    raise InputError("link-path-limit")
                for value in linked:
                    if not isinstance(value, str) or len(value) > 4096:
                        raise InputError("invalid-link-path")
                    path = Path(value.split("=", 1)[-1])
                    if path.is_absolute() and path.resolve().is_relative_to(repo / "target"):
                        links.add(path.resolve(strict=True))
                if len(links) > artifacts.MAX_LINK_PATHS:
                    raise InputError("link-path-limit")
            elif item.get("reason") == "compiler-artifact" and item.get("manifest_path") == str(expected):
                target, profile = item["target"], item["profile"]
                if not isinstance(target, dict) or not isinstance(profile, dict):
                    raise InputError("invalid-cargo-target")
                for role, (name, kind, testing, source) in roles.items():
                    if target.get("name") != name or target.get("kind") != [kind] or profile.get("test") is not testing:
                        continue
                    if target.get("src_path") != str(expected.parent / source) or str(profile.get("opt_level")) != "0":
                        raise InputError("wrong-cargo-owner-or-profile")
                    path = exact_file(Path(item["executable"]), executable=True)
                    root = target_root if kind == "bin" else target_root / "deps"
                    if path.parent != root or role in found:
                        raise InputError("ambiguous-or-foreign-cargo-product")
                    found[role] = {"original": stamp(path), "features": item.get("features", []),
                                   "cargo_profile": profile}
    if not finished or set(found) != set(roles):
        raise InputError("missing-successful-cargo-products")
    if {tuple(value["features"]) for value in found.values()} != {FEATURES}:
        raise InputError("incompatible-cargo-feature-sets")
    return found, tuple(sorted(links))


def prepare(repo: Path, inventory: Path, output: Path) -> Path:
    if "LSF_AOT_TEST_EXECUTION_ONLY" in os.environ:
        raise InputError("preparation-forbidden-in-execution-only-mode")
    started = time.monotonic_ns()
    identity = checkout_identity(repo)
    entries, links = inventory_inputs(inventory, repo)
    inventory_ns = time.monotonic_ns() - started
    if output.exists():
        raise InputError("output-exists-use-validate-or-new-directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.parent.resolve() != output.parent:
        raise InputError("noncanonical-output-parent")
    objcopy = shutil.which("objcopy")
    if objcopy is None:
        raise InputError("objcopy-unavailable")
    staging = Path(tempfile.mkdtemp(prefix=".aot-prepare-", dir=output.parent))
    stages = {"inventory_and_original_hash_ns": inventory_ns}
    try:
        for role in ("compiler", "aot_supervisor"):
            original = Path(entries[role]["original"]["path"])
            copy = staging / role
            start = time.monotonic_ns()
            status, _ = artifacts.run_owned([objcopy, "--strip-debug", str(original), str(copy)],
                                            cwd=repo, env=dict(os.environ), timeout=120, maximum=4096)
            if status:
                raise InputError("strip-failed")
            copy.chmod(0o555)
            stages[f"{role}_strip_ns"] = time.monotonic_ns() - start
            start = time.monotonic_ns()
            selected = stamp(copy)
            selected["path"] = str(output / role)
            stages[f"{role}_expected_digest_ns"] = time.monotonic_ns() - start
            entries[role]["prepared"] = selected
            # Rehash the original after strip: neither replacement nor mutation is allowed.
            check_stamp(entries[role]["original"])
        runtime = artifacts.cargo_environment(repo, artifacts.Artifact(
            Path(entries["aot_supervisor"]["original"]["path"]),
            repo / "crates/latent-wasmtime", links), dict(os.environ))
        runtime = {key: runtime[key] for key in ("LD_LIBRARY_PATH", "CARGO_MANIFEST_DIR") if key in runtime}
        manifest = {"schema": SCHEMA, "profile": PROFILE, "checkout": identity,
                    "inventory": stamp(inventory), "entries": entries, "runtime": runtime,
                    "preparation_ns": stages, "preparation_total_ns": time.monotonic_ns() - started}
        (staging / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        (staging / "manifest.json").chmod(0o444)
        staging.rename(output)
        return output / "manifest.json"
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def validate(repo: Path, manifest_path: Path) -> dict:
    manifest = read_json(exact_file(manifest_path))
    if manifest.get("schema") != SCHEMA or manifest.get("profile") != PROFILE:
        raise InputError("wrong-input-schema-or-profile")
    if manifest.get("checkout") != checkout_identity(repo):
        raise InputError("stale-checkout-identity")
    check_stamp(manifest["inventory"], executable=False)
    if not isinstance(manifest["entries"], dict):
        raise InputError("wrong-executable-roles")
    if set(manifest["entries"]) != {"compiler", *HARNESS_NAMES}:
        raise InputError("wrong-executable-roles")
    for role, entry in manifest["entries"].items():
        original = check_stamp(entry["original"])
        if not original.is_relative_to(repo / "target/debug"):
            raise InputError("foreign-original-executable")
        if role in ("compiler", "aot_supervisor"):
            prepared = check_stamp(entry["prepared"])
            if prepared != manifest_path.parent / role or prepared == original:
                raise InputError("wrong-prepared-executable-path")
    runtime = manifest["runtime"]
    if (not isinstance(runtime, dict) or set(runtime) != {"LD_LIBRARY_PATH", "CARGO_MANIFEST_DIR"}
            or any(not isinstance(value, str) or len(value) > 32768 or "\n" in value or "\r" in value or "\0" in value
                   for value in runtime.values())
            or runtime["CARGO_MANIFEST_DIR"] != str(repo / "crates/latent-wasmtime")):
        raise InputError("invalid-runtime-environment")
    directories = runtime["LD_LIBRARY_PATH"].split(os.pathsep)
    if (not directories or len(directories) > artifacts.MAX_LINK_PATHS + 3
            or any(not Path(value).is_absolute() or not Path(value).is_dir() for value in directories)):
        raise InputError("invalid-runtime-library-path")
    return manifest


def environment(manifest_path: Path, manifest: dict) -> dict[str, str]:
    return {**manifest["runtime"], "LSF_AOT_TEST_INPUTS": str(manifest_path),
            "LSF_AOT_TEST_INPUTS_SHA256": bytes(digest(manifest_path)).hex(),
            "LSF_AOT_TEST_EXECUTION_ONLY": "1", "LSF_AOT_REQUIRE_LINUX": "1"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--inventory", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    for operation in ("validate", "environment"):
        p = sub.add_parser(operation)
        p.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    try:
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise InputError("not-run-linux-x86_64-required")
        if args.command == "prepare":
            path = prepare(repo, args.inventory.resolve(strict=True), args.output.absolute())
            print(path)
        else:
            path = args.manifest.absolute()
            manifest = validate(repo, path)
            if args.command == "environment":
                for key, value in environment(path, manifest).items():
                    if "\n" in value or "\r" in value:
                        raise InputError("invalid-runtime-environment")
                    print(f"{key}={value}")
            else:
                print("AOT test inputs: validated; no tests executed")
        return 0
    except (OSError, ValueError, KeyError, TypeError, artifacts.ArtifactError,
            subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, (InputError, artifacts.ArtifactError)) else "invalid-prepared-input"
        print(f"AOT test inputs: {reason}\nPrepare explicitly: {PREPARE}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
