#!/usr/bin/env python3
"""Check unconditional workspace topology before feature-selected test dependencies."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tomllib

try:
    import validate_foundation as foundation
except ModuleNotFoundError as error:
    if error.name != "validate_foundation":
        raise
    from tools import validate_foundation as foundation

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "latentd", "latent-node", "latent-wasmtime", "latent-http", "latent-nats",
    "latent-state", "latent-vault", "latent-secrets", "latent-blobs",
}
PACKAGES = ("latent-core", "latent-testkit", "latent-admission", "latent-scheduler")


def check_workspace(root: Path) -> None:
    # Reuse CI's authoritative validator, including optional, dev, build and
    # target-specific edges. A selected Cargo graph cannot prove this invariant.
    before = len(foundation.ERRORS)
    foundation.validate_workspace_dependency_graph(root)
    errors = foundation.ERRORS[before:]
    if errors:
        raise RuntimeError("\n".join(errors))
    graph = foundation.workspace_dependency_graph(root)
    missing = set(PACKAGES) - graph.keys()
    if missing:
        raise RuntimeError(f"missing helper graph owners: {sorted(missing)}")
    if graph["latent-core"]:
        raise RuntimeError("neutral core helpers must not depend on another workspace crate")
    for package in ("latent-admission", "latent-scheduler"):
        manifest = tomllib.loads((root / "crates" / package / "Cargo.toml").read_text())
        if "latent-testkit" in graph[package]:
            raise RuntimeError(f"{package} must not depend back on latent-testkit")
        helper = manifest.get("dev-dependencies", {}).get("latent-core", {})
        if "test-support" not in helper.get("features", []):
            raise RuntimeError(f"{package} must select latent-core/test-support for tests")
    print(f"workspace: {len(graph)} packages, unconditional dependency graph is acyclic")


def cargo_command(package: str) -> list[str]:
    args = ["cargo", "tree", "--locked", "-p", package, "--prefix", "none", "--format", "{p}"]
    if package == "latent-core":
        args += ["--features", "test-support", "--edges", "normal,build,dev"]
    elif package == "latent-testkit":
        args += ["--no-default-features", "--edges", "normal,build,dev"]
    else:
        args += ["--edges", "normal,build,dev"]
    return args


def check_selected(package: str, output: str) -> None:
    names = {line.split()[0] for line in output.splitlines() if line.strip()}
    if package not in names:
        raise RuntimeError(f"{package}: missing selected graph root")
    forbidden = FORBIDDEN | ({"latent-activation", "latent-executor", "latent-telemetry"}
                             if package in ("latent-core", "latent-testkit") else set())
    offenders = sorted(name for name in names if name in forbidden or name.startswith("wasmtime"))
    if offenders:
        raise RuntimeError(f"{package} inherited heavy dependencies: {offenders}\n{output}")
    print(f"{package}: {len(names)} dependency nodes, no forbidden runtime/provider dependencies")


def main(root: Path = ROOT) -> None:
    check_workspace(root)
    for package in PACKAGES:
        result = subprocess.run(cargo_command(package), cwd=root, capture_output=True,
                                text=True, check=True, timeout=120)
        check_selected(package, result.stdout)


if __name__ == "__main__":
    main()
