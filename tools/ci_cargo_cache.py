#!/usr/bin/env python3
"""Build-compatible keys for the opt-in dependency-cache candidate.

This identifies compiler inputs, not executable provenance or passing tests.
The selected CI cache remains the existing baseline pending measured comparison.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from typing import Mapping, Sequence

try:
    from . import ci_cargo
except ImportError:
    import ci_cargo  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "latent.ci.cargo-cache.v1"
NAMESPACE = "lsf-ci-recipe-dependencies-v1"
MAX_INPUT_FILES = 4096
MAX_INPUT_BYTES = 64 * 1024 * 1024
ENV_PREFIXES = ("CARGO_PROFILE_", "CARGO_TARGET_", "CARGO_BUILD_", "CMAKE_", "PKG_CONFIG_", "BINDGEN_EXTRA_CLANG_ARGS", "CC_", "CXX_", "AR_", "CFLAGS_", "CXXFLAGS_")
ENV_NAMES = frozenset({"CARGO_INCREMENTAL", "CARGO_ENCODED_RUSTFLAGS", "CARGO_ENCODED_RUSTDOCFLAGS", "CARGO_HOME", "RUSTFLAGS", "RUSTDOCFLAGS", "RUSTC", "RUSTDOC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "RUSTUP_TOOLCHAIN", "CC", "CXX", "AR", "RANLIB", "LD", "CFLAGS", "CPPFLAGS", "CXXFLAGS", "LDFLAGS", "PROTOC", "HOST_CC", "HOST_CXX", "HOST_CFLAGS", "HOST_CXXFLAGS", "TARGET_CC", "TARGET_CXX", "TARGET_CFLAGS", "TARGET_CXXFLAGS", "CRATE_CC_NO_DEFAULTS"})
SECRET_NAME = re.compile(r"(?:TOKEN|PASSWORD|SECRET|CREDENTIAL|PRIVATE_KEY)")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_digest(value: object) -> str:
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())


def environment_identity(environment: Mapping[str, str]) -> dict[str, str]:
    # Only hashes are retained. Never serialize a credential or arbitrary env dump.
    return {name: digest_bytes(value.encode()) for name, value in sorted(environment.items())
            if (name in ENV_NAMES or name.startswith(ENV_PREFIXES)) and not SECRET_NAME.search(name)}


def relevant(path: str, configuration: str) -> bool:
    p = Path(path)
    return (p.name in {"Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml", "build.rs"}
            or (p.parent.name == ".cargo" and p.name in {"config", "config.toml"})
            or path in {"tools/ci_cargo.py", "tools/ci_cargo_cache.py"}
            or (configuration == "ci-correctness" and path == ".cargo/ci-correctness.toml"))


def hash_inputs(root: Path, names: Sequence[str], configuration: str) -> dict[str, str]:
    root = root.resolve()
    selected = sorted({name for name in names if relevant(name, configuration)})
    required = {"Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml",
                "tools/ci_cargo.py", "tools/ci_cargo_cache.py"}
    if configuration == "ci-correctness":
        required.add(".cargo/ci-correctness.toml")
    if not required.issubset(selected):
        raise ValueError("missing build inputs: " + ", ".join(sorted(required - set(selected))))
    if len(selected) > MAX_INPUT_FILES:
        raise ValueError("too many cache identity inputs")
    total = 0
    result = {}
    for name in selected:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid build input path: {name}")
        path = root / relative
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
            raise ValueError(f"symlinked build input: {name}")
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f"missing or foreign build input: {name}")
        total += path.stat().st_size
        if total > MAX_INPUT_BYTES:
            raise ValueError("cache identity inputs exceed 64 MiB")
        result[name] = digest_bytes(path.read_bytes())
    return result


def identity(*, files: Mapping[str, str], tools: Mapping[str, str], host: Mapping[str, str],
             environment: Mapping[str, str], configuration: str = "current", recipe: str = "rust") -> dict:
    if configuration not in ci_cargo.CONFIGURATIONS:
        raise ValueError(f"unknown configuration: {configuration}")
    if recipe not in {"rust", "msrv"}:
        raise ValueError(f"unknown cache recipe: {recipe}")
    if recipe == "msrv" and configuration != "current":
        raise ValueError("the correctness experiment must not alter MSRV")
    names = ci_cargo.RUST_RECIPES if recipe == "rust" else ("msrv",)
    # One stable recipe identity can be consumed by multiple compatible lanes.
    # Job names/layout are deliberately not inputs. Cargo still checks each unit.
    recipes = {name: [asdict(invocation) for invocation in ci_cargo.RECIPES[name]] for name in names}
    payload = {"schemaVersion": SCHEMA, "namespace": NAMESPACE, "recipe": recipe,
               "configuration": configuration, "recipes": recipes,
               "files": dict(files), "tools": dict(tools), "host": dict(host),
               "environment": environment_identity(environment),
               "cachePaths": ["target/debug/.fingerprint", "target/debug/build", "target/debug/deps"]}
    return {**payload, "digest": canonical_digest(payload)}


def checked_output(command: Sequence[str], root: Path) -> str:
    result = subprocess.run(command, cwd=root, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False, timeout=30)
    if result.returncode != 0 or len(result.stdout) > 1024 * 1024:
        # Do not echo arbitrary subprocess diagnostics into cache metadata.
        raise ValueError(f"cannot observe {command[0]} identity (exit {result.returncode})")
    return result.stdout.strip()


def validate_supported_configuration(data: bytes) -> None:
    """Fail explicitly instead of keying an unobserved compiler/linker/target."""
    config = tomllib.loads(data.decode("utf-8"))
    build = config.get("build", {})
    if not isinstance(build, dict) or any(name in build for name in (
            "rustc", "rustdoc", "rustc-wrapper", "rustc-workspace-wrapper", "target", "target-dir")):
        raise ValueError("candidate does not support Cargo compiler or target overrides")
    targets = config.get("target", {})
    if not isinstance(targets, dict) or any(
            isinstance(value, dict) and "linker" in value for value in targets.values()):
        raise ValueError("candidate does not support Cargo linker overrides")


def validate_supported_environment(environment: Mapping[str, str]) -> None:
    overrides = {"RUSTC", "RUSTDOC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_TARGET_DIR",
                 "CARGO_BUILD_TARGET", "CARGO_BUILD_TARGET_DIR", "CARGO_BUILD_RUSTC", "CARGO_BUILD_RUSTDOC",
                 "CARGO_BUILD_RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER"}
    if any(value and (name in overrides or (name.startswith("CARGO_TARGET_") and name.endswith("_LINKER")))
           for name, value in environment.items()):
        raise ValueError("candidate requires the pinned compiler and default target directory/linker")


def observe(root: Path, configuration: str, recipe: str, environment: Mapping[str, str]) -> dict:
    root = root.resolve()
    validate_supported_environment(environment)
    names = checked_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], root).split("\0")
    files = hash_inputs(root, names, configuration)
    for name in files:
        path = Path(name)
        if path.parent.name == ".cargo" and path.name in {"config", "config.toml", "ci-correctness.toml"}:
            validate_supported_configuration((root / name).read_bytes())
    # Cargo also reads parent-directory and CARGO_HOME configuration. Hash those
    # files, but never credentials.toml or the rest of CARGO_HOME.
    cargo_home = Path(environment.get("CARGO_HOME", str(Path.home() / ".cargo"))).expanduser()
    if not cargo_home.is_absolute():
        cargo_home = root / cargo_home
    external = [*(parent / ".cargo" for parent in root.parents), cargo_home]
    for index, directory in enumerate(external):
        for name in ("config", "config.toml"):
            path = directory / name
            if path.exists():
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                    raise ValueError("unsupported external Cargo configuration")
                data = path.read_bytes()
                validate_supported_configuration(data)
                files[f"external-config/{index}/{name}"] = digest_bytes(data)
    version_arg = ["+" + ci_cargo.msrv_version(root)] if recipe == "msrv" else []
    rustc = checked_output(["rustc", *version_arg, "-vV"], root)
    cargo = checked_output(["cargo", *version_arg, "-vV"], root)
    host_match = re.search(r"^host: (\S+)$", rustc, re.MULTILINE)
    if host_match is None:
        raise ValueError("rustc did not report its host target")
    tools = {"rustc": digest_bytes(rustc.encode()), "cargo": digest_bytes(cargo.encode())}
    for label, default in (("CC", "cc"), ("CXX", "c++"), ("AR", "ar"), ("LD", "ld")):
        command = shlex.split(environment.get(label, default))
        if not command or shutil.which(command[0]) is None:
            raise ValueError(f"cannot resolve native build tool {label}")
        tools[label] = canonical_digest({"argv": command,
                                        "version": checked_output([*command, "--version"], root)})
    host = {"system": platform.system(), "machine": platform.machine(), "target": host_match[1],
            "libc": "/".join(platform.libc_ver()), "runnerOS": environment.get("RUNNER_OS", "local"),
            "runnerArch": environment.get("RUNNER_ARCH", platform.machine()),
            "imageOS": environment.get("ImageOS", "unavailable"),
            "imageVersion": environment.get("ImageVersion", "unavailable")}
    return identity(files=files, tools=tools, host=host, environment=environment,
                    configuration=configuration, recipe=recipe)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", choices=ci_cargo.CONFIGURATIONS, default="current")
    parser.add_argument("--recipe", choices=("rust", "msrv"), default="rust")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = observe(ROOT, args.configuration, args.recipe, os.environ)
        if args.github_output is not None:
            # Entire digest belongs to the prefix, not a fallback-droppable suffix.
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"prefix={NAMESPACE}-{value['digest']}\n")
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Cargo cache identity failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
