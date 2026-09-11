#!/usr/bin/env python3
"""Validate Phase 1 build-foundation ownership and dependency invariants."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []

PROTO_INPUT_MANIFEST = Path("api/proto/latent-api.protos")
GENERATED_BINDING_OWNERS: dict[str, tuple[str, ...]] = {
    "crates/latent-rpc/build.rs": ("OUT_DIR", "latent-api.protos"),
    "crates/latent-component-bindings/build.rs": (
        "OUT_DIR",
        "wit/platform/runtime",
        "examples/echo-contract/wit",
    ),
}
LEGACY_BINDING_BUILD_SCRIPTS = ("tools/toolchain-smoke/build.rs",)
WASMTIME_TARGET_BUILD_SCRIPT = "crates/latent-wasmtime/build.rs"
WASMTIME_TARGET_BUILD_REQUIRED_TOKENS = (
    'std::env::var("TARGET")',
    "cargo:rustc-env=LATENT_WASMTIME_HOST_TARGET={target}",
)
WASMTIME_TARGET_BUILD_FORBIDDEN_TOKENS = (
    "OUT_DIR",
    "stage_echo_world",
    "copy_wit_tree",
    "write_bindings_invocation",
    "echo_bindings.rs",
    "wasmtime::component::bindgen!",
    "examples/echo-contract/wit",
    "wit/platform/context",
    "wit/platform/log",
)
GENERATED_SOURCE_SUFFIXES = {".cs", ".go", ".java", ".rs", ".ts"}
REQUIRED_DOCS = (
    "docs/development/build-foundation.md",
    "docs/development/toolchain.md",
)


def fail(message: str) -> None:
    ERRORS.append(message)


def dependency_specifications(manifest: dict) -> Iterator[tuple[str, object]]:
    for table_name in ("dependencies", "dev-dependencies", "build-dependencies"):
        yield from manifest.get(table_name, {}).items()
    for target in manifest.get("target", {}).values():
        for table_name in ("dependencies", "dev-dependencies", "build-dependencies"):
            yield from target.get(table_name, {}).items()


def workspace_dependency_graph(root: Path = ROOT) -> dict[str, set[str]]:
    workspace = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    members = workspace.get("workspace", {}).get("members", [])
    member_names: dict[Path, str] = {}
    manifests: dict[str, tuple[Path, dict]] = {}

    for member in members:
        directory = (root / member).resolve()
        cargo = directory / "Cargo.toml"
        if not cargo.is_file():
            continue
        parsed = tomllib.loads(cargo.read_text(encoding="utf-8"))
        name = parsed.get("package", {}).get("name")
        if not name:
            continue
        member_names[directory] = name
        manifests[name] = (directory, parsed)

    graph = {name: set() for name in manifests}
    for name, (directory, manifest) in manifests.items():
        for _dependency, specification in dependency_specifications(manifest):
            if not isinstance(specification, dict) or "path" not in specification:
                continue
            target = (directory / specification["path"]).resolve()
            target_name = member_names.get(target)
            if target_name is not None:
                graph[name].add(target_name)
    return graph


def validate_workspace_dependency_graph(root: Path = ROOT) -> None:
    graph = workspace_dependency_graph(root)
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        current = state.get(node, 0)
        if current == 2:
            return
        if current == 1:
            start = stack.index(node)
            cycle = stack[start:] + [node]
            fail(f"workspace dependency cycle: {' -> '.join(cycle)}")
            return

        state[node] = 1
        stack.append(node)
        for dependency in sorted(graph.get(node, set())):
            visit(dependency)
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        visit(node)


def _manifest_entries(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def validate_generated_contract_boundaries(root: Path = ROOT) -> None:
    proto_root = root / "api/proto"
    manifest = root / PROTO_INPUT_MANIFEST
    if not manifest.is_file():
        fail(f"Protobuf generation manifest missing: {PROTO_INPUT_MANIFEST.as_posix()}")
    else:
        entries = _manifest_entries(manifest)
        invalid = [
            entry
            for entry in entries
            if not entry.endswith(".proto")
            or Path(entry).is_absolute()
            or ".." in Path(entry).parts
        ]
        if invalid:
            fail(f"invalid Protobuf generation manifest entries: {', '.join(invalid)}")
        if entries != sorted(entries):
            fail(f"Protobuf generation manifest must be sorted: {PROTO_INPUT_MANIFEST.as_posix()}")
        if len(entries) != len(set(entries)):
            fail(
                "Protobuf generation manifest contains duplicates: "
                f"{PROTO_INPUT_MANIFEST.as_posix()}"
            )
        actual = {
            path.relative_to(proto_root).as_posix()
            for path in proto_root.rglob("*.proto")
        }
        listed = set(entries)
        if actual != listed:
            missing = ", ".join(sorted(actual - listed)) or "none"
            stale = ", ".join(sorted(listed - actual)) or "none"
            fail(f"Protobuf generation manifest drift: missing=[{missing}], stale=[{stale}]")

    authoritative_wit_roots = [root / "wit", *sorted((root / "examples").glob("*/wit"))]
    for authoritative_root in [proto_root, *authoritative_wit_roots]:
        if not authoritative_root.exists():
            continue
        for path in authoritative_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in GENERATED_SOURCE_SUFFIXES:
                fail(
                    "generated language source must not be checked into contract authority: "
                    f"{path.relative_to(root)}"
                )

    for relative, required_tokens in GENERATED_BINDING_OWNERS.items():
        path = root / relative
        if not path.is_file():
            fail(f"generated binding owner missing: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for token in required_tokens:
            if token not in text:
                fail(f"generated binding owner {relative} does not reference {token}")

    wasmtime_build_script = root / WASMTIME_TARGET_BUILD_SCRIPT
    if not wasmtime_build_script.is_file():
        fail(
            "Wasmtime target-export build script missing: "
            f"{WASMTIME_TARGET_BUILD_SCRIPT}"
        )
    else:
        text = wasmtime_build_script.read_text(encoding="utf-8")
        for token in WASMTIME_TARGET_BUILD_REQUIRED_TOKENS:
            if token not in text:
                fail(
                    f"Wasmtime target-export build script does not reference {token}: "
                    f"{WASMTIME_TARGET_BUILD_SCRIPT}"
                )
        for token in WASMTIME_TARGET_BUILD_FORBIDDEN_TOKENS:
            if token in text:
                fail(
                    "Wasmtime target-export build script must not duplicate binding "
                    f"generation ({token}): {WASMTIME_TARGET_BUILD_SCRIPT}"
                )

    for relative in LEGACY_BINDING_BUILD_SCRIPTS:
        if (root / relative).exists():
            fail(f"legacy duplicated binding generator must be removed: {relative}")


def validate_ci_and_docs(root: Path = ROOT) -> None:
    workflow_path = root / ".github/workflows/ci.yml"
    if not workflow_path.is_file():
        fail("CI workflow missing: .github/workflows/ci.yml")
    else:
        workflow = workflow_path.read_text(encoding="utf-8")
        for token in (
            "pull_request:",
            "cargo fmt --all --check",
            "cargo check --workspace --all-targets --all-features --locked",
            "cargo clippy --workspace --all-targets --all-features --locked",
            "cargo test --workspace --all-targets --all-features --locked",
            "latent-rpc",
            "latent-component-bindings",
        ):
            if token not in workflow:
                fail(f"CI workflow does not enforce foundation token: {token}")

    makefile = (root / "Makefile").read_text(encoding="utf-8")
    for target in ("rpc-bindings:", "component-bindings:", "phase1-foundation:"):
        if target not in makefile:
            fail(f"Makefile foundation target missing: {target}")

    for relative in REQUIRED_DOCS:
        if not (root / relative).is_file():
            fail(f"foundation documentation missing: {relative}")


def main() -> int:
    validate_workspace_dependency_graph()
    validate_generated_contract_boundaries()
    validate_ci_and_docs()

    for message in ERRORS:
        print(f"error: {message}", file=sys.stderr)
    if ERRORS:
        return 1
    print("validated build foundation: dependency graph, generation boundaries, CI, and docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
