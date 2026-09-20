#!/usr/bin/env python3
"""Reviewed Cargo command recipes; not a test selector or an artifact authenticator.

Keep default commands byte-for-byte equivalent to the CI coverage map. A caller
must still validate prepared artifacts through ci_rust_artifacts.py. In
particular, this module never treats cache restoration as successful testing.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
CONFIGURATIONS = ("current", "ci-correctness")


@dataclass(frozen=True)
class Invocation:
    name: str
    args: tuple[str, ...]
    packages: tuple[str, ...]
    features: str
    targets: str
    profile: str
    coverage: str
    toolchain: str = "pinned"
    inventory: bool = False

    def command(self, configuration: str = "current", timings: bool = False) -> list[str]:
        if configuration not in CONFIGURATIONS:
            raise ValueError(f"unknown Cargo configuration: {configuration}")
        if configuration != "current" and self.toolchain == "msrv":
            raise ValueError("the correctness experiment must not alter MSRV")
        command = ["cargo"]
        if self.toolchain == "msrv":
            command.append("+" + msrv_version(ROOT))
        args = list(self.args)
        # Insert Cargo options before any rustc/libtest arguments.
        separator = args.index("--") if "--" in args else len(args)
        options: list[str] = []
        if configuration != "current":
            if args[0] == "fmt":
                raise ValueError("formatting is independent of build profiles")
            options += ["--config", str(ROOT / ".cargo/ci-correctness.toml")]
        if timings and args[0] != "fmt":
            options.append("--timings")
        args[separator:separator] = options
        return command + args


def declared_toolchain(root: Path, selection: str) -> str:
    import tomllib
    try:
        if selection == "msrv":
            version = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["rust-version"]
        else:
            version = tomllib.loads((root / "rust-toolchain.toml").read_text(encoding="utf-8"))["toolchain"]["channel"]
    except (KeyError, TypeError) as error:
        raise ValueError("missing declared Cargo toolchain") from error
    if not isinstance(version, str) or not version or len(version) > 128:
        raise ValueError("invalid declared Cargo toolchain")
    return version


def msrv_version(root: Path) -> str:
    return declared_toolchain(root, "msrv")


ALL = ("--workspace", "--all-targets", "--all-features", "--locked")
RECIPES: dict[str, tuple[Invocation, ...]] = {
    "format": (
        Invocation("format", ("fmt", "--all", "--check"), ("workspace",), "n/a", "sources", "n/a", "rustfmt"),
    ),
    "workspace-check": (
        Invocation("workspace-check", ("check", *ALL), ("workspace",), "all", "host/all-targets", "dev", "feature-unified workspace checking"),
    ),
    "bindings": (
        Invocation("rpc-check", ("check", "-p", "latent-rpc", "--all-targets", "--all-features", "--locked"), ("latent-rpc",), "all", "host/all-targets", "dev", "independent generated RPC bindings"),
        Invocation("component-host", ("check", "-p", "latent-component-bindings", "--locked"), ("latent-component-bindings",), "default", "host/default-targets", "dev", "independent host Component Model bindings"),
        Invocation("component-wasip2", ("check", "-p", "latent-component-bindings", "--target", "wasm32-wasip2", "--locked"), ("latent-component-bindings",), "default", "wasm32-wasip2/default-targets", "dev", "supported guest Component Model bindings"),
        Invocation("smoke-wasip2", ("check", "-p", "latent-toolchain-smoke", "--target", "wasm32-wasip2", "--locked"), ("latent-toolchain-smoke",), "default", "wasm32-wasip2/default-targets", "dev", "supported guest toolchain"),
        Invocation("echo-wasip2", ("check", "-p", "latent-toolchain-smoke", "--example", "echo-capsule", "--target", "wasm32-wasip2", "--locked"), ("latent-toolchain-smoke",), "default", "wasm32-wasip2/example:echo-capsule", "dev", "supported guest echo example"),
    ),
    "production": (
        Invocation("applications", ("check", "-p", "latent", "-p", "latentd", "--all-features", "--locked"), ("latent", "latentd"), "all", "host/default-targets", "dev", "production selection without workspace dev-dependency unification"),
        Invocation("aot-compiler", ("check", "-p", "latent-wasmtime", "--bin", "latent-aot-compiler", "--all-features", "--locked"), ("latent-wasmtime",), "all", "host/bin:latent-aot-compiler", "dev", "independently selected production AOT compiler"),
    ),
    "clippy": (
        Invocation("clippy-workspace", ("clippy", *ALL), ("workspace",), "all", "host/all-targets", "dev", "workspace lint coverage"),
        Invocation("clippy-strict", ("clippy", "-p", "latent", "-p", "latentd", "-p", "latent-testkit", "-p", "latent-admission", "--all-targets", "--all-features", "--locked", "--no-deps", "--", "-D", "warnings"), ("latent", "latentd", "latent-testkit", "latent-admission"), "all", "host/all-targets", "dev", "selected warnings-as-errors policy"),
    ),
    "prepare": (
        Invocation("workspace-build", ("build", *ALL), ("workspace",), "all", "host/all-targets", "dev", "normal binaries, examples and build-mode targets"),
        Invocation("test-inventory", ("test", *ALL, "--no-run", "--message-format=json,json-render-diagnostics"), ("workspace",), "all", "host/all-targets", "test", "exact compiled harness inventory for existing artifact runners", inventory=True),
    ),
    "test": (
        Invocation("workspace-tests", ("test", *ALL), ("workspace",), "all", "host/all-targets", "test", "workspace test execution, including custom harnesses"),
        Invocation("doctests", ("test", "-p", "latent-admission", "-p", "latent-scheduler", "--doc", "--locked"), ("latent-admission", "latent-scheduler"), "default", "host/doctests", "test", "doctests omitted by --all-targets"),
        Invocation("signing-compatibility", ("test", "-p", "latent-signing", "--lib", "--locked", "--features", "ed25519-dalek/legacy_compatibility", "crypto::tests"), ("latent-signing",), "default+ed25519-dalek/legacy_compatibility", "host/lib;filter=crypto::tests", "test", "negative controls under the compatibility feature"),
    ),
    "msrv": (
        Invocation("msrv", ("check", *ALL), ("workspace",), "all", "host/all-targets", "dev", "independent minimum supported compiler", toolchain="msrv"),
    ),
}
RUST_RECIPES = ("workspace-check", "bindings", "production", "clippy", "prepare", "test")


def plan(recipe: str, configuration: str = "current", timings: bool = False) -> dict:
    if recipe not in RECIPES:
        raise ValueError(f"unknown Cargo recipe: {recipe}")
    commands = []
    for invocation in RECIPES[recipe]:
        entry = asdict(invocation)
        entry["argv"] = invocation.command(configuration, timings)
        entry["declaredToolchain"] = declared_toolchain(ROOT, invocation.toolchain)
        del entry["args"]
        commands.append(entry)
    return {"schemaVersion": "latent.ci.cargo-recipe.v1", "recipe": recipe,
            "configuration": configuration, "commands": commands}


def execute(recipe: str, configuration: str = "current", *, inventory: Path | None = None,
            timings: bool = False) -> int:
    selected = plan(recipe, configuration, timings)  # validate before touching outputs
    needs_inventory = any(entry["inventory"] for entry in selected["commands"])
    if needs_inventory != (inventory is not None):
        raise ValueError("--inventory is required only for the prepare recipe")
    if inventory is not None:
        inventory = inventory.parent.resolve() / inventory.name
        # Build inventories are ephemeral; never overwrite a tracked source file.
        if inventory.is_symlink() or (inventory.exists() and not inventory.is_file()):
            raise ValueError("inventory must be a regular file, not a link or directory")
        try:
            relative = inventory.relative_to(ROOT)
        except ValueError:
            pass
        else:
            if not relative.parts or relative.parts[0] != "target":
                raise ValueError("an in-checkout inventory must be beneath target/")
        inventory.parent.mkdir(parents=True, exist_ok=True)
        inventory.unlink(missing_ok=True)  # a failed preparation must not leave a stale inventory
    for entry in selected["commands"]:
        command = entry["argv"]
        print("+ " + shlex.join(command), file=sys.stderr, flush=True)
        temporary: Path | None = None
        try:
            if entry["inventory"]:
                assert inventory is not None
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=inventory.parent,
                                                 prefix=".cargo-inventory-", delete=False) as output:
                    temporary = Path(output.name)
                    result = subprocess.run(command, cwd=ROOT, stdout=output, check=False)
                if result.returncode == 0:
                    validate_inventory(temporary)
                    temporary.replace(inventory)
            else:
                result = subprocess.run(command, cwd=ROOT, check=False)
            if result.returncode != 0:
                return result.returncode if result.returncode > 0 else 128 - result.returncode
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return 0


def validate_inventory(path: Path) -> None:
    """Check stream completion only; ci_rust_artifacts owns artifact validation."""
    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate Cargo inventory key")
            result[key] = value
        return result

    finished = False
    artifacts = 0
    consumed = 0
    records = 0
    with path.open("rb") as stream:
        while raw := stream.readline(1024 * 1024 + 1):
            consumed += len(raw)
            records += 1
            if len(raw) > 1024 * 1024 or consumed > 32 * 1024 * 1024 or records > 100_000:
                raise ValueError("Cargo inventory exceeds its stream bounds")
            if not raw.strip():
                continue
            entry = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(entry, dict) or not isinstance(entry.get("reason"), str) or finished:
                raise ValueError("invalid or post-completion Cargo inventory record")
            if entry["reason"] == "compiler-artifact":
                artifacts += 1
            if entry["reason"] == "build-finished":
                if entry.get("success") is not True:
                    raise ValueError("Cargo did not report a successful build")
                finished = True
    if not finished or not artifacts:
        raise ValueError("Cargo inventory lacks artifacts or successful completion")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "run"))
    parser.add_argument("recipe", choices=tuple(RECIPES))
    parser.add_argument("--configuration", choices=CONFIGURATIONS, default="current")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--timings", action="store_true", help="retain Cargo's own HTML timings")
    args = parser.parse_args(argv)
    try:
        if args.operation == "plan":
            if args.inventory is not None:
                raise ValueError("--inventory is an output option for run prepare")
            print(json.dumps(plan(args.recipe, args.configuration, args.timings), indent=2))
            return 0
        return execute(args.recipe, args.configuration, inventory=args.inventory, timings=args.timings)
    except (OSError, ValueError) as error:
        print(f"Cargo recipe failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
