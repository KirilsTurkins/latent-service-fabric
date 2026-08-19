#!/usr/bin/env python3
"""Build, validate, test, and package the Phase 0 Rust echo component fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN_BASELINE = ROOT / "tools" / "toolchain.toml"
CAPSULE_TEMPLATE = ROOT / "examples" / "echo-contract" / "capsule.json"
DEFAULT_OUTPUT = ROOT / "target" / "capsules" / "echo-rust"
BUILD_ROOT = ROOT / "target" / "echo-capsule-build"

PACKAGE = "latent-toolchain-smoke"
CARGO_EXAMPLE = "echo-capsule"
RUST_TARGET = "wasm32-wasip2"
PROFILE = "release"
COMPONENT_FILE = "echo.component.wasm"
COMPONENT_WIT_FILE = "component.wit"
DIGEST_FILE = "digest.txt"
MANIFEST_FILE = "capsule.json"
METADATA_FILE = "build-metadata.json"
TRUST_FILE = "local-trust.json"

EXPECTED_WORLD = "examples:echo/service@0.1.0"
EXPECTED_COMPONENT_PACKAGE = "root:component"
EXPECTED_COMPONENT_WORLD = "root"
EXPECTED_IMPORTS = (
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
)
EXPECTED_EXPORTS = ("examples:echo/api@0.1.0",)


class BuildError(RuntimeError):
    """Raised when the fixture cannot be built or validated deterministically."""


def run_checked(
    command: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command from the repository root and raise a contextual error."""

    try:
        return subprocess.run(
            list(command),
            cwd=ROOT,
            env=None if environment is None else dict(environment),
            check=True,
            text=True,
            capture_output=capture_output,
        )
    except FileNotFoundError as exc:
        raise BuildError(f"required executable is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        rendered = " ".join(command)
        details = (exc.stderr or exc.stdout or "").strip()
        suffix = f"\n{details}" if details else ""
        raise BuildError(f"command failed: {rendered}{suffix}") from exc


def load_toolchain_baseline() -> dict[str, Any]:
    """Load the checked-in exact toolchain selections."""

    with TOOLCHAIN_BASELINE.open("rb") as stream:
        return tomllib.load(stream)


def executable_version(executable: str) -> str:
    """Return combined version output for an executable."""

    result = run_checked([executable, "--version"], capture_output=True)
    return f"{result.stdout}\n{result.stderr}".strip()


def require_exact_tool_versions(baseline: Mapping[str, Any]) -> None:
    """Reject builds performed with a different Rust or wasm-tools version."""

    expected_rust = str(baseline["rust"]["toolchain"])
    actual_rust = executable_version("rustc")
    rust_match = re.search(r"\brustc\s+(\d+\.\d+\.\d+)\b", actual_rust)
    if rust_match is None or rust_match.group(1) != expected_rust:
        raise BuildError(
            f"rustc version mismatch: expected {expected_rust}, found {actual_rust!r}"
        )

    actual_cargo = executable_version("cargo")
    cargo_match = re.search(r"\bcargo\s+(\d+\.\d+\.\d+)\b", actual_cargo)
    if cargo_match is None or cargo_match.group(1) != expected_rust:
        raise BuildError(
            f"Cargo version mismatch: expected {expected_rust}, found {actual_cargo!r}"
        )

    expected_wasm_tools = str(baseline["contracts"]["wasm-tools"])
    actual_wasm_tools = executable_version("wasm-tools")
    wasm_tools_match = re.search(
        r"\bwasm-tools\s+(\d+\.\d+\.\d+)\b", actual_wasm_tools
    )
    if wasm_tools_match is None or wasm_tools_match.group(1) != expected_wasm_tools:
        raise BuildError(
            "wasm-tools version mismatch: "
            f"expected {expected_wasm_tools}, found {actual_wasm_tools!r}"
        )


def reproducible_environment(target_directory: Path) -> dict[str, str]:
    """Create the deterministic Cargo environment used for every guest build."""

    environment = os.environ.copy()
    for key in ("CARGO_ENCODED_RUSTFLAGS", "RUSTFLAGS", "RUSTDOCFLAGS"):
        environment.pop(key, None)
    for key in tuple(environment):
        if key.startswith("CARGO_PROFILE_"):
            environment.pop(key)
    environment.update(
        {
            "CARGO_ENCODED_RUSTFLAGS": f"--remap-path-prefix={ROOT}=/workspace",
            "CARGO_INCREMENTAL": "0",
            "CARGO_TERM_COLOR": "never",
            "CARGO_TARGET_DIR": str(target_directory),
            "SOURCE_DATE_EPOCH": "0",
        }
    )
    return environment


def cargo_artifact_candidates(target_directory: Path) -> tuple[Path, ...]:
    """Return Cargo output names used for a WebAssembly `cdylib` example."""

    examples = target_directory / RUST_TARGET / PROFILE / "examples"
    return (
        examples / "echo_capsule.wasm",
        examples / "libecho_capsule.wasm",
    )


def build_component(target_directory: Path) -> Path:
    """Perform one clean, locked component build and return its artifact path."""

    if target_directory.exists():
        shutil.rmtree(target_directory)
    target_directory.parent.mkdir(parents=True, exist_ok=True)

    run_checked(
        [
            "cargo",
            "build",
            "--package",
            PACKAGE,
            "--example",
            CARGO_EXAMPLE,
            "--target",
            RUST_TARGET,
            "--release",
            "--locked",
        ],
        environment=reproducible_environment(target_directory),
    )

    for artifact in cargo_artifact_candidates(target_directory):
        if artifact.is_file():
            return artifact
    candidates = ", ".join(str(path) for path in cargo_artifact_candidates(target_directory))
    raise BuildError(f"Cargo did not produce the expected component at: {candidates}")


def sha256_digest(data: bytes) -> str:
    """Return the canonical manifest digest for artifact bytes."""

    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def validate_component_wit(wit_text: str) -> None:
    """Confirm the final component world has exactly the checked-in authorities."""

    without_block_comments = re.sub(r"/\*.*?\*/", "", wit_text, flags=re.DOTALL)
    without_comments = re.sub(r"//.*", "", without_block_comments)
    normalized = re.sub(r"\s+", " ", without_comments)

    package_pattern = rf"\bpackage\s+{re.escape(EXPECTED_COMPONENT_PACKAGE)}\s*;"
    if re.search(package_pattern, normalized) is None:
        raise BuildError(
            "wasm-tools did not infer the expected root:component package"
        )

    world_pattern = rf"\bworld\s+{re.escape(EXPECTED_COMPONENT_WORLD)}\s*\{{"
    if re.search(world_pattern, normalized) is None:
        raise BuildError("wasm-tools did not infer the expected root component world")

    imports = tuple(
        match.strip()
        for match in re.findall(r"\bimport\s+([^;{{}}]+?)\s*;", without_comments)
    )
    if set(imports) != set(EXPECTED_IMPORTS) or len(imports) != len(EXPECTED_IMPORTS):
        rendered = ", ".join(imports) if imports else "none"
        raise BuildError(
            "component must declare exactly the context and log imports; "
            f"inferred: {rendered}"
        )

    exports = tuple(
        match.strip()
        for match in re.findall(r"\bexport\s+([^;{{}}]+?)\s*;", without_comments)
    )
    if set(exports) != set(EXPECTED_EXPORTS) or len(exports) != len(EXPECTED_EXPORTS):
        rendered = ", ".join(exports) if exports else "none"
        raise BuildError(
            "component must export exactly examples:echo/api@0.1.0; "
            f"inferred: {rendered}"
        )


def infer_and_validate_component(component: Path) -> str:
    """Run wasm-tools validation and return the inferred WIT text."""

    run_checked(["wasm-tools", "validate", str(component)])
    result = run_checked(
        ["wasm-tools", "component", "wit", str(component)],
        capture_output=True,
    )
    validate_component_wit(result.stdout)
    return result.stdout


def deterministic_json(document: Mapping[str, Any]) -> str:
    """Serialize generated metadata with stable key order and a final newline."""

    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def generated_capsule_manifest(digest: str) -> dict[str, Any]:
    """Materialize the checked-in capsule template with a computed digest."""

    document = json.loads(CAPSULE_TEMPLATE.read_text(encoding="utf-8"))
    document["component"]["digest"] = digest
    annotations = document["metadata"].setdefault("annotations", {})
    annotations.update(
        {
            "latent.dev/purpose": "phase-0-echo-fixture",
            "latent.dev/source": "examples/echo-contract/guest-rust",
            "latent.dev/trust": "local-build",
        }
    )
    return document


def build_metadata(
    *,
    digest: str,
    baseline: Mapping[str, Any],
    reproducibility_verified: bool,
) -> dict[str, Any]:
    """Create stable build provenance without timestamps or machine-specific paths."""

    return {
        "artifact": COMPONENT_FILE,
        "cargoExample": CARGO_EXAMPLE,
        "cargoPackage": PACKAGE,
        "componentWorld": f"{EXPECTED_COMPONENT_PACKAGE}/{EXPECTED_COMPONENT_WORLD}",
        "contentDigest": digest,
        "exports": list(EXPECTED_EXPORTS),
        "imports": list(EXPECTED_IMPORTS),
        "profile": PROFILE,
        "reproducibility": {
            "scope": (
                "byte-for-byte for repeated clean builds from the same source tree "
                "with the pinned toolchain, target, lockfile, and profile"
            ),
            "verified": reproducibility_verified,
        },
        "rustTarget": RUST_TARGET,
        "rustToolchain": str(baseline["rust"]["toolchain"]),
        "schemaVersion": 1,
        "source": "examples/echo-contract/guest-rust",
        "sourceWorld": EXPECTED_WORLD,
        "wasmTools": str(baseline["contracts"]["wasm-tools"]),
        "world": EXPECTED_WORLD,
    }


def local_trust_declaration(digest: str) -> dict[str, Any]:
    """Create the explicit local-only trust declaration consumed by the spike."""

    return {
        "artifact": COMPONENT_FILE,
        "contentDigest": digest,
        "mode": "local-build",
        "schemaVersion": 1,
        "scope": "phase-0-development-only",
        "signature": None,
        "validatedWith": "wasm-tools",
    }


def write_outputs(
    *,
    output_directory: Path,
    component_bytes: bytes,
    inferred_wit: str,
    baseline: Mapping[str, Any],
    reproducibility_verified: bool,
) -> str:
    """Write the stable local capsule bundle and return its digest."""

    if output_directory.exists():
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True)

    digest = sha256_digest(component_bytes)
    (output_directory / COMPONENT_FILE).write_bytes(component_bytes)
    normalized_wit = inferred_wit.rstrip() + "\n"
    (output_directory / COMPONENT_WIT_FILE).write_text(normalized_wit, encoding="utf-8")
    (output_directory / DIGEST_FILE).write_text(
        f"{digest}  {COMPONENT_FILE}\n", encoding="utf-8"
    )
    (output_directory / MANIFEST_FILE).write_text(
        deterministic_json(generated_capsule_manifest(digest)), encoding="utf-8"
    )
    (output_directory / METADATA_FILE).write_text(
        deterministic_json(
            build_metadata(
                digest=digest,
                baseline=baseline,
                reproducibility_verified=reproducibility_verified,
            )
        ),
        encoding="utf-8",
    )
    (output_directory / TRUST_FILE).write_text(
        deterministic_json(local_trust_declaration(digest)), encoding="utf-8"
    )
    return digest


def run_component_tests(component: Path) -> None:
    """Execute typed Wasmtime tests against the generated component."""

    environment = os.environ.copy()
    environment["LATENT_ECHO_COMPONENT"] = str(component.resolve())
    run_checked(
        [
            "cargo",
            "test",
            "--package",
            PACKAGE,
            "--test",
            "echo_component",
            "--locked",
            "--",
            "--ignored",
            "--nocapture",
        ],
        environment=environment,
    )


def build_fixture(
    *,
    output_directory: Path,
    check_reproducible: bool,
    execute_component_tests: bool,
) -> str:
    """Build the complete local fixture bundle and return its content digest."""

    baseline = load_toolchain_baseline()
    require_exact_tool_versions(baseline)

    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    BUILD_ROOT.mkdir(parents=True)

    try:
        cargo_target = BUILD_ROOT / "cargo-target"
        first_artifact = build_component(cargo_target)
        first_bytes = first_artifact.read_bytes()

        if check_reproducible:
            second_artifact = build_component(cargo_target)
            second_bytes = second_artifact.read_bytes()
            if first_bytes != second_bytes:
                raise BuildError(
                    "repeated clean component builds are not byte-for-byte identical: "
                    f"{sha256_digest(first_bytes)} != {sha256_digest(second_bytes)}"
                )

        staging_component = BUILD_ROOT / COMPONENT_FILE
        staging_component.write_bytes(first_bytes)
        inferred_wit = infer_and_validate_component(staging_component)
        if execute_component_tests:
            run_component_tests(staging_component)

        return write_outputs(
            output_directory=output_directory,
            component_bytes=first_bytes,
            inferred_wit=inferred_wit,
            baseline=baseline,
            reproducibility_verified=check_reproducible,
        )
    finally:
        shutil.rmtree(BUILD_ROOT, ignore_errors=True)


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="generated local capsule bundle directory",
    )
    parser.add_argument(
        "--check-reproducible",
        action="store_true",
        help="perform two clean builds and require byte-for-byte identity",
    )
    parser.add_argument(
        "--run-component-tests",
        action="store_true",
        help="invoke success and declared errors through typed Wasmtime bindings",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    try:
        digest = build_fixture(
            output_directory=options.output.resolve(),
            check_reproducible=options.check_reproducible,
            execute_component_tests=options.run_component_tests,
        )
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"built {options.output / COMPONENT_FILE}")
    print(f"digest {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
