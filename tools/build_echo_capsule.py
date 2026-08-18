#!/usr/bin/env python3
"""Build and validate the generated Phase 0 Rust echo component fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / "tools" / "toolchain.toml"
CONTRACT = ROOT / "examples" / "echo-contract" / "wit" / "echo.wit"
CAPSULE_TEMPLATE = ROOT / "examples" / "echo-contract" / "capsule.json"
CAPSULE_SCHEMA = ROOT / "schemas" / "capsule-manifest.schema.json"

PACKAGE = "latent-toolchain-smoke"
EXAMPLE = "echo-capsule"
TARGET = "wasm32-wasip2"
PROFILE = "release"
ARTIFACT_NAME = "echo-capsule.wasm"
SOURCE_WORLD = "examples:echo/service@0.1.0"
EXPECTED_IMPORTS = {
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
}
EXPECTED_EXPORTS = {"examples:echo/api@0.1.0"}
REPRODUCIBILITY_SCOPE = (
    "byte-identical output for two clean builds from the same checkout, source path, "
    "host platform, pinned Rust toolchain, target, dependency lockfile, and release settings"
)


class BuildError(RuntimeError):
    """Raised when the fixture cannot be built or validated."""


def command_from_environment(name: str, default: str) -> list[str]:
    value = os.environ.get(name, default)
    command = shlex.split(value)
    if not command:
        raise BuildError(f"{name} resolves to an empty command")
    return command


def run_checked(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    print(f"+ {shlex.join(command)}", file=sys.stderr)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, file=sys.stderr, end="")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        raise BuildError(
            f"command failed with exit code {completed.returncode}: {shlex.join(command)}"
        )
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    return completed


def load_toolchain() -> dict[str, Any]:
    return tomllib.loads(TOOLCHAIN.read_text(encoding="utf-8"))


def parse_version(output: str, tool: str) -> str:
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", output)
    if not match:
        raise BuildError(f"could not parse {tool} version from: {output.strip()!r}")
    return match.group(1)


def verify_tool_versions(toolchain: dict[str, Any]) -> None:
    configured_target = str(toolchain["rust"]["target"])
    if configured_target != TARGET:
        raise BuildError(
            f"tools/toolchain.toml selects {configured_target}; the echo fixture expects {TARGET}"
        )

    rustc = command_from_environment("RUSTC", "rustc")
    wasm_tools = command_from_environment("WASM_TOOLS", "wasm-tools")

    rustc_version = parse_version(run_checked([*rustc, "--version"]).stdout, "rustc")
    expected_rustc = str(toolchain["rust"]["toolchain"])
    if rustc_version != expected_rustc:
        raise BuildError(
            f"rustc {rustc_version} is active; the echo fixture requires {expected_rustc}"
        )

    wasm_tools_version = parse_version(
        run_checked([*wasm_tools, "--version"]).stdout, "wasm-tools"
    )
    expected_wasm_tools = str(toolchain["contracts"]["wasm-tools"])
    if wasm_tools_version != expected_wasm_tools:
        raise BuildError(
            "wasm-tools "
            f"{wasm_tools_version} is active; the echo fixture requires {expected_wasm_tools}"
        )


def canonical_build_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_TARGET_DIR"):
        environment.pop(name, None)
    environment.update(
        {
            "CARGO_INCREMENTAL": "0",
            "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "1",
            "CARGO_PROFILE_RELEASE_DEBUG": "0",
            "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
            "CARGO_PROFILE_RELEASE_STRIP": "debuginfo",
            "CARGO_TERM_COLOR": "never",
            "LC_ALL": "C",
            "SOURCE_DATE_EPOCH": "0",
            "TZ": "UTC",
        }
    )
    return environment


def validate_source_contract() -> None:
    source = CONTRACT.read_text(encoding="utf-8")
    required_fragments = (
        "package examples:echo@0.1.0;",
        "world service",
        "import latent:context/context@0.1.0;",
        "import latent:log/log@0.1.0;",
        "export api;",
        "empty-message",
        "message-too-large",
    )
    for fragment in required_fragments:
        if fragment not in source:
            raise BuildError(f"echo contract no longer contains {fragment!r}")

    compact = re.sub(r"\s+", " ", source)
    if not re.search(
        r"echo:\s*func\s*\(\s*message:\s*string\s*\)\s*"
        r"->\s*result\s*<\s*string\s*,\s*echo-error\s*>\s*;",
        compact,
    ):
        raise BuildError("echo contract no longer declares the expected echo function")


def extract_cargo_artifact(cargo_output: str) -> Path:
    artifacts: set[Path] = set()
    for line in cargo_output.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("reason") != "compiler-artifact":
            continue
        target = message.get("target", {})
        if target.get("name") != EXAMPLE or "example" not in target.get("kind", []):
            continue
        for filename in message.get("filenames", []):
            path = Path(filename)
            if path.suffix == ".wasm":
                artifacts.add(path)

    if len(artifacts) != 1:
        rendered = ", ".join(str(path) for path in sorted(artifacts)) or "none"
        raise BuildError(f"expected one echo component artifact from Cargo, found: {rendered}")
    artifact = artifacts.pop()
    if not artifact.is_file():
        raise BuildError(f"Cargo reported a missing artifact: {artifact}")
    return artifact


def build_once(build_directory: Path) -> bytes:
    if build_directory.exists():
        shutil.rmtree(build_directory)
    build_directory.parent.mkdir(parents=True, exist_ok=True)

    cargo = command_from_environment("CARGO", "cargo")
    completed = run_checked(
        [
            *cargo,
            "build",
            "--locked",
            "--release",
            "--target",
            TARGET,
            "--package",
            PACKAGE,
            "--example",
            EXAMPLE,
            "--target-dir",
            str(build_directory),
            "--message-format",
            "json-render-diagnostics",
        ],
        environment=canonical_build_environment(),
    )
    return extract_cargo_artifact(completed.stdout).read_bytes()


def build_component(target_root: Path, verify_reproducible: bool) -> tuple[bytes, bool]:
    build_parent = target_root / "capsule-build"
    if verify_reproducible:
        first_directory = build_parent / "echo-a"
        second_directory = build_parent / "echo-b"
        try:
            first = build_once(first_directory)
            second = build_once(second_directory)
        finally:
            shutil.rmtree(first_directory, ignore_errors=True)
            shutil.rmtree(second_directory, ignore_errors=True)
        if first != second:
            first_digest = hashlib.sha256(first).hexdigest()
            second_digest = hashlib.sha256(second).hexdigest()
            raise BuildError(
                "echo component is not reproducible within the documented boundary: "
                f"sha256:{first_digest} != sha256:{second_digest}"
            )
        return first, True

    build_directory = build_parent / "echo"
    try:
        return build_once(build_directory), False
    finally:
        shutil.rmtree(build_directory, ignore_errors=True)


def parse_root_world(wit: str) -> tuple[set[str], set[str]]:
    match = re.search(r"\bworld\s+root\s*\{(?P<body>.*?)^\s*\}", wit, re.DOTALL | re.MULTILINE)
    if not match:
        raise BuildError("wasm-tools did not expose a root component world")
    body = match.group("body")
    imports = {
        item.strip()
        for item in re.findall(r"^\s*import\s+([^;]+);", body, re.MULTILINE)
    }
    exports = {
        item.strip()
        for item in re.findall(r"^\s*export\s+([^;]+);", body, re.MULTILINE)
    }
    return imports, exports


def validate_extracted_interface(interface_directory: Path) -> None:
    root_wit = interface_directory / "component.wit"
    if not root_wit.is_file():
        raise BuildError("wasm-tools did not write component.wit")
    imports, exports = parse_root_world(root_wit.read_text(encoding="utf-8"))
    if imports != EXPECTED_IMPORTS:
        raise BuildError(
            "unexpected component imports: "
            f"expected {sorted(EXPECTED_IMPORTS)}, found {sorted(imports)}"
        )
    if exports != EXPECTED_EXPORTS:
        raise BuildError(
            "unexpected component exports: "
            f"expected {sorted(EXPECTED_EXPORTS)}, found {sorted(exports)}"
        )

    extracted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(interface_directory.rglob("*.wit"))
    )
    compact = re.sub(r"\s+", " ", extracted)
    required_patterns = (
        r"package\s+examples:echo@0\.1\.0\s*;",
        r"variant\s+echo-error\s*\{[^}]*empty-message\s*,[^}]*message-too-large",
        r"echo:\s*func\s*\(\s*message:\s*string\s*\)\s*"
        r"->\s*result\s*<\s*string\s*,\s*echo-error\s*>\s*;",
    )
    for pattern in required_patterns:
        if not re.search(pattern, compact):
            raise BuildError(
                "component interface does not contain the expected echo contract: "
                f"{pattern}"
            )


def build_capsule_manifest(digest: str) -> dict[str, Any]:
    manifest = json.loads(CAPSULE_TEMPLATE.read_text(encoding="utf-8"))
    manifest["component"]["digest"] = f"sha256:{digest}"
    annotations = manifest["metadata"].setdefault("annotations", {})
    annotations["latent.dev/purpose"] = "phase-0-echo-fixture"
    annotations["latent.dev/trust"] = "local-build"
    annotations["latent.dev/artifact"] = ARTIFACT_NAME

    schema = json.loads(CAPSULE_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise BuildError(f"generated capsule metadata is invalid: {details}")
    if manifest["component"]["world"] != SOURCE_WORLD:
        raise BuildError("capsule template does not identify the checked-in echo world")
    if set(manifest["exports"]) != EXPECTED_EXPORTS:
        raise BuildError("capsule template exports do not match the component")
    template_imports = {item["contract"] for item in manifest["imports"]}
    if template_imports != EXPECTED_IMPORTS:
        raise BuildError("capsule template imports do not match the component")
    if any(item.get("optional", False) for item in manifest["imports"]):
        raise BuildError("echo component imports must remain required")
    return manifest


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def validate_and_stage_output(
    component: bytes,
    *,
    output_directory: Path,
    reproducibility_verified: bool,
    toolchain: dict[str, Any],
) -> str:
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".echo-output-", dir=output_directory.parent)
    )
    try:
        artifact = staging / ARTIFACT_NAME
        artifact.write_bytes(component)
        digest = hashlib.sha256(component).hexdigest()

        wasm_tools = command_from_environment("WASM_TOOLS", "wasm-tools")
        run_checked([*wasm_tools, "validate", str(artifact)])

        interface_directory = staging / "interface"
        run_checked(
            [
                *wasm_tools,
                "component",
                "wit",
                str(artifact),
                "--out-dir",
                str(interface_directory),
            ]
        )
        validate_extracted_interface(interface_directory)

        interface_json = run_checked(
            [*wasm_tools, "component", "wit", str(artifact), "--json"]
        ).stdout
        try:
            parsed_interface = json.loads(interface_json)
        except json.JSONDecodeError as error:
            raise BuildError(f"wasm-tools emitted invalid interface JSON: {error}") from error
        write_json(staging / "interface.json", parsed_interface)

        manifest = build_capsule_manifest(digest)
        write_json(staging / "capsule.json", manifest)
        (staging / "sha256.txt").write_text(
            f"{digest}  {ARTIFACT_NAME}\n", encoding="utf-8"
        )

        receipt = {
            "schemaVersion": 1,
            "artifact": ARTIFACT_NAME,
            "contentDigest": f"sha256:{digest}",
            "sizeBytes": len(component),
            "cargoPackage": PACKAGE,
            "cargoTarget": EXAMPLE,
            "profile": PROFILE,
            "target": TARGET,
            "sourceWorld": SOURCE_WORLD,
            "imports": sorted(EXPECTED_IMPORTS),
            "exports": sorted(EXPECTED_EXPORTS),
            "toolchain": {
                "rust": str(toolchain["rust"]["toolchain"]),
                "witBindgen": str(toolchain["rust"]["dependencies"]["wit-bindgen"]),
                "wasmTools": str(toolchain["contracts"]["wasm-tools"]),
            },
            "trust": {
                "kind": "local-clean-build",
                "signed": False,
            },
            "reproducibility": {
                "verified": reproducibility_verified,
                "scope": REPRODUCIBILITY_SCOPE,
            },
        }
        write_json(staging / "build.json", receipt)

        if output_directory.exists():
            shutil.rmtree(output_directory)
        staging.replace(output_directory)
        return digest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def resolve_target_root() -> Path:
    configured = os.environ.get("CARGO_TARGET_DIR")
    if configured is None:
        return ROOT / "target"
    target = Path(configured).expanduser()
    if not target.is_absolute():
        target = ROOT / target
    return target.resolve()


def resolve_output_directory(
    configured: Path | None, target_root: Path
) -> Path:
    if configured is None:
        output_directory = target_root / "capsules" / "echo"
    else:
        output_directory = configured.expanduser()
        if not output_directory.is_absolute():
            output_directory = ROOT / output_directory
        output_directory = output_directory.resolve()

    resolved_target_root = target_root.resolve()
    if (
        output_directory == resolved_target_root
        or resolved_target_root not in output_directory.parents
    ):
        raise BuildError(
            "the generated capsule output directory must be a child of "
            f"{resolved_target_root}"
        )
    return output_directory


def relative_display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-reproducible",
        action="store_true",
        help="perform two isolated clean builds and require byte-identical components",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="override the generated capsule directory",
    )
    arguments = parser.parse_args()

    try:
        toolchain = load_toolchain()
        verify_tool_versions(toolchain)
        validate_source_contract()
        target_root = resolve_target_root()
        output_directory = resolve_output_directory(arguments.output_dir, target_root)
        component, reproducibility_verified = build_component(
            target_root, arguments.verify_reproducible
        )
        digest = validate_and_stage_output(
            component,
            output_directory=output_directory,
            reproducibility_verified=reproducibility_verified,
            toolchain=toolchain,
        )
    except (BuildError, OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "artifact": relative_display(output_directory / ARTIFACT_NAME),
                "capsule": relative_display(output_directory / "capsule.json"),
                "digest": f"sha256:{digest}",
                "reproducibilityVerified": reproducibility_verified,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
