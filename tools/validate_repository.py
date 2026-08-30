#!/usr/bin/env python3
"""Validate authoritative repository sources while excluding generated artifacts."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
WARNINGS: list[str] = []

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".generated",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "artifacts",
    "coverage",
    "node_modules",
    "target",
}

SCHEMA_EXAMPLES: dict[str, tuple[str, ...]] = {
    "binding.schema.json": ("examples/bindings/*.json",),
    "capsule-manifest.schema.json": ("examples/**/capsule.json",),
    "deployment.schema.json": ("examples/**/deployment.json",),
    "policy.schema.json": ("examples/policies/*.json",),
    "route-snapshot.schema.json": (),
    "trigger.schema.json": ("examples/**/*trigger.json",),
}

SVG_UNSAFE_ELEMENTS = frozenset({"embed", "foreignObject", "iframe", "image", "object", "script"})
SVG_NONLOCAL_URL = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.IGNORECASE)
SVG_CSS_IMPORT = re.compile(r"@import\b", re.IGNORECASE)


def fail(message: str) -> None:
    ERRORS.append(message)


def warn(message: str) -> None:
    WARNINGS.append(message)


def is_generated_directory(path: Path, root: Path) -> bool:
    if path.name in IGNORED_DIRECTORY_NAMES:
        return True

    relative = path.relative_to(root)
    parts = relative.parts
    if parts[:2] == ("sdk", "typescript-client") and path.name == "dist":
        return True
    if parts[:2] == ("sdk", "java-client") and path.name == "build":
        return True
    if parts[:2] == ("sdk", "dotnet") and path.name in {"bin", "obj"}:
        return True
    return False


def iter_source_files(root: Path = ROOT) -> Iterator[Path]:
    for directory, directories, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        directories[:] = sorted(
            name
            for name in directories
            if not is_generated_directory(current / name, root)
        )
        for filename in sorted(filenames):
            path = current / filename
            if not path.is_symlink():
                yield path


def files_with_suffix(suffix: str, root: Path = ROOT) -> Iterator[Path]:
    return (path for path in iter_source_files(root) if path.suffix.lower() == suffix.lower())


def validate_json(root: Path = ROOT) -> None:
    for path in files_with_suffix(".json", root):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - validator must report every parser failure
            fail(f"invalid JSON {path.relative_to(root).as_posix()}: {exc}")


def validate_toml(root: Path = ROOT) -> None:
    for path in files_with_suffix(".toml", root):
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - validator must report every parser failure
            fail(f"invalid TOML {path.relative_to(root).as_posix()}: {exc}")


def _xml_local_name(name: str) -> str:
    return name.rsplit("}", maxsplit=1)[-1]


def validate_svg(root: Path = ROOT) -> None:
    """Enforce the project SVG safety and accessibility baseline."""

    for path in files_with_suffix(".svg", root):
        relative = path.relative_to(root)
        try:
            document = ElementTree.parse(path)
        except (ElementTree.ParseError, OSError) as exc:
            fail(f"invalid SVG {relative}: {exc}")
            continue

        svg = document.getroot()
        if _xml_local_name(svg.tag) != "svg":
            fail(f"SVG root must be <svg>: {relative}")
            continue
        for attribute in ("viewBox", "role", "aria-labelledby"):
            if not svg.get(attribute, "").strip():
                fail(f"SVG missing {attribute}: {relative}")
        if svg.get("role", "").strip() and svg.get("role") != "img":
            fail(f"SVG role must be img: {relative}")

        elements = list(svg.iter())
        identifiers = {
            element.get("id")
            for element in elements
            if isinstance(element.tag, str) and element.get("id")
        }
        required_labels = set(svg.get("aria-labelledby", "").split())
        if not required_labels <= identifiers:
            missing = ", ".join(sorted(required_labels - identifiers))
            fail(f"SVG aria-labelledby references missing ID(s) {missing}: {relative}")

        for local_name in ("title", "desc"):
            matches = [
                element
                for element in elements
                if isinstance(element.tag, str) and _xml_local_name(element.tag) == local_name
            ]
            if not any((element.text or "").strip() for element in matches):
                fail(f"SVG missing non-empty <{local_name}>: {relative}")
            elif not any(
                (element.text or "").strip() and element.get("id") in required_labels
                for element in matches
            ):
                fail(f"SVG aria-labelledby must reference a non-empty <{local_name}>: {relative}")

        for element in elements:
            if not isinstance(element.tag, str):
                continue
            local_name = _xml_local_name(element.tag)
            if local_name in SVG_UNSAFE_ELEMENTS:
                fail(f"SVG contains disallowed <{local_name}>: {relative}")
            for attribute, value in element.attrib.items():
                attribute_name = _xml_local_name(attribute)
                if attribute_name.lower().startswith("on"):
                    fail(f"SVG contains event handler {attribute_name}: {relative}")
                if (
                    attribute_name in {"href", "src"}
                    and (value or "").strip()
                    and not value.strip().startswith("#")
                ):
                    fail(f"SVG contains non-local reference in {attribute_name}: {relative}")
                if SVG_NONLOCAL_URL.search(value or ""):
                    fail(f"SVG contains non-local URL reference: {relative}")

        style_text = "\n".join(
            "".join(element.itertext())
            for element in elements
            if isinstance(element.tag, str) and _xml_local_name(element.tag) == "style"
        )
        if SVG_CSS_IMPORT.search(style_text):
            fail(f"SVG contains external CSS import: {relative}")


def validate_workspace() -> None:
    manifest_path = ROOT / "Cargo.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    members = manifest.get("workspace", {}).get("members", [])
    if not members:
        fail("Cargo workspace has no members")
        return

    for member in members:
        directory = ROOT / member
        cargo = directory / "Cargo.toml"
        if not directory.is_dir():
            fail(f"workspace member directory missing: {member}")
            continue
        if not cargo.is_file():
            fail(f"workspace member Cargo.toml missing: {member}")
            continue
        parsed = tomllib.loads(cargo.read_text(encoding="utf-8"))
        package = parsed.get("package", {})
        if not package.get("name"):
            fail(f"workspace member has no package name: {member}")
        source = directory / "src" / ("main.rs" if member.startswith("apps/") else "lib.rs")
        if not source.is_file():
            fail(f"workspace member source missing: {source.relative_to(ROOT)}")

        for dependency, specification in dependency_specifications(parsed):
            if isinstance(specification, dict) and "path" in specification:
                target = (directory / specification["path"]).resolve()
                if not target.is_dir():
                    fail(
                        f"path dependency {dependency} from {member} does not exist: "
                        f"{specification['path']}"
                    )


def dependency_specifications(manifest: dict) -> Iterator[tuple[str, object]]:
    for table_name in ("dependencies", "dev-dependencies", "build-dependencies"):
        yield from manifest.get(table_name, {}).items()
    for target in manifest.get("target", {}).values():
        for table_name in ("dependencies", "dev-dependencies", "build-dependencies"):
            yield from target.get(table_name, {}).items()


def validate_toolchain_baseline() -> None:
    required = [
        ROOT / "Cargo.lock",
        ROOT / "rust-toolchain.toml",
        ROOT / "tools" / "toolchain.toml",
        ROOT / "tools" / "requirements.lock",
        ROOT / "global.json",
        ROOT / "sdk" / "typescript-client" / "package-lock.json",
    ]
    for path in required:
        if not path.is_file():
            fail(f"toolchain baseline file missing: {path.relative_to(ROOT)}")
    if any(not path.is_file() for path in required):
        return

    baseline = tomllib.loads((ROOT / "tools/toolchain.toml").read_text(encoding="utf-8"))
    rust_toolchain = tomllib.loads((ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))

    expected_toolchain = baseline["rust"]["toolchain"]
    actual_toolchain = rust_toolchain["toolchain"]["channel"]
    if actual_toolchain != expected_toolchain:
        fail(
            f"Rust toolchain drift: tools/toolchain.toml has {expected_toolchain}, "
            f"rust-toolchain.toml has {actual_toolchain}"
        )

    expected_target = baseline["rust"]["target"]
    actual_targets = rust_toolchain["toolchain"].get("targets", [])
    if expected_target not in actual_targets:
        fail(f"Rust target {expected_target} is not pinned in rust-toolchain.toml")

    expected_msrv = baseline["rust"]["msrv"]
    actual_msrv = workspace["workspace"]["package"]["rust-version"]
    if actual_msrv != expected_msrv:
        fail(
            f"MSRV drift: tools/toolchain.toml has {expected_msrv}, "
            f"Cargo.toml has {actual_msrv}"
        )

    cargo_dependencies = workspace["workspace"].get("dependencies", {})
    for dependency, expected_version in baseline["rust"]["dependencies"].items():
        specification = cargo_dependencies.get(dependency)
        if specification is None:
            fail(f"pinned workspace dependency missing: {dependency}")
            continue
        actual_version = (
            specification if isinstance(specification, str) else specification.get("version")
        )
        if actual_version != f"={expected_version}":
            fail(
                f"workspace dependency {dependency} must be pinned to "
                f"={expected_version}, found {actual_version!r}"
            )

    requirements = (ROOT / "tools/requirements.lock").read_text(encoding="utf-8")
    expected_jsonschema = baseline["contracts"]["jsonschema"]
    if f"jsonschema=={expected_jsonschema}" not in requirements.splitlines():
        fail("jsonschema version differs between toolchain.toml and requirements.lock")

    expected_dotnet = baseline["sdk"]["dotnet"]
    dotnet = json.loads((ROOT / "global.json").read_text(encoding="utf-8"))
    if dotnet.get("sdk", {}).get("version") != expected_dotnet:
        fail(".NET SDK version differs between toolchain.toml and global.json")

    expected_typescript = baseline["sdk"]["typescript"]
    package = json.loads(
        (ROOT / "sdk/typescript-client/package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (ROOT / "sdk/typescript-client/package-lock.json").read_text(encoding="utf-8")
    )
    if package.get("devDependencies", {}).get("typescript") != expected_typescript:
        fail("TypeScript version differs between toolchain.toml and package.json")
    locked_typescript = package_lock.get("packages", {}).get("node_modules/typescript", {})
    if locked_typescript.get("version") != expected_typescript:
        fail("TypeScript version differs between toolchain.toml and package-lock.json")

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow_versions = [
        expected_toolchain,
        expected_msrv,
        baseline["contracts"]["wasm-tools"],
        baseline["contracts"]["buf"],
        baseline["contracts"]["python"],
        baseline["sdk"]["go"],
        baseline["sdk"]["node"],
        baseline["sdk"]["typescript"],
        baseline["sdk"]["java"],
        baseline["sdk"]["dotnet"],
    ]
    for version in workflow_versions:
        if str(version) not in workflow:
            fail(f"pinned tool version {version} is not referenced by CI")


def validate_proto() -> None:
    proto_root = ROOT / "api" / "proto"
    proto_files = list(proto_root.rglob("*.proto"))
    if not proto_files:
        fail("no Protobuf definitions found")
        return

    for path in proto_files:
        text = path.read_text(encoding="utf-8")
        if 'syntax = "proto3";' not in text:
            fail(f"missing proto3 declaration: {path.relative_to(ROOT)}")
        if not re.search(r"^package\s+[a-zA-Z0-9_.]+;", text, re.MULTILINE):
            fail(f"missing Protobuf package: {path.relative_to(ROOT)}")
        for imported in re.findall(r'import\s+"([^"]+)";', text):
            if not (proto_root / imported).is_file():
                fail(f"unresolved Protobuf import {imported} in {path.relative_to(ROOT)}")


def validate_wit() -> None:
    wit_files = list((ROOT / "wit").rglob("*.wit")) + list((ROOT / "examples").rglob("*.wit"))
    if not wit_files:
        fail("no WIT definitions found")
        return

    packages: dict[str, Path] = {}
    for path in wit_files:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^package\s+([^;]+);", text, re.MULTILINE)
        if not match:
            fail(f"missing WIT package declaration: {path.relative_to(ROOT)}")
            continue
        package = match.group(1).strip()
        if package in packages and path.parent != packages[package].parent:
            fail(
                f"duplicate WIT package {package}: "
                f"{packages[package].relative_to(ROOT)} and {path.relative_to(ROOT)}"
            )
        packages[package] = path
        if "interface " not in text and "world " not in text:
            fail(f"WIT file defines neither interface nor world: {path.relative_to(ROOT)}")


def validate_schemas() -> None:
    required = set(SCHEMA_EXAMPLES)
    schema_paths = sorted((ROOT / "schemas").glob("*.schema.json"))
    actual = {path.name for path in schema_paths}
    missing = required - actual
    if missing:
        fail(f"missing required schemas: {', '.join(sorted(missing))}")

    schema_ids: dict[str, Path] = {}
    for path in schema_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            fail(f"schema is not Draft 2020-12: {path.relative_to(ROOT)}")
        schema_id = document.get("$id")
        if not schema_id:
            fail(f"schema lacks $id: {path.relative_to(ROOT)}")
        elif schema_id in schema_ids:
            fail(
                f"duplicate schema $id {schema_id}: "
                f"{schema_ids[schema_id].relative_to(ROOT)} and {path.relative_to(ROOT)}"
            )
        else:
            schema_ids[schema_id] = path

        try:
            Draft202012Validator.check_schema(document)
        except SchemaError as exc:
            fail(f"invalid JSON Schema {path.relative_to(ROOT)}: {exc.message}")
            continue

        patterns = SCHEMA_EXAMPLES.get(path.name, ())
        examples = sorted({example for pattern in patterns for example in ROOT.glob(pattern)})
        if patterns and not examples:
            fail(f"schema has no checked-in examples: {path.relative_to(ROOT)}")
            continue

        validator = Draft202012Validator(document, format_checker=FormatChecker())
        for example_path in examples:
            example = json.loads(example_path.read_text(encoding="utf-8"))
            for error in sorted(validator.iter_errors(example), key=lambda item: tuple(str(part) for part in item.absolute_path)):
                location = "/" + "/".join(str(part) for part in error.absolute_path)
                fail(
                    f"schema validation failed for {example_path.relative_to(ROOT)} "
                    f"at {location}: {error.message}"
                )


def validate_interface_only_policy() -> None:
    forbidden = ("todo!", "unimplemented!", "panic!(\"not implemented", "TODO_IMPLEMENTATION")
    for path in files_with_suffix(".rs"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                fail(f"implementation placeholder token {token!r} found in {path.relative_to(ROOT)}")

    for app_main in (ROOT / "apps").glob("*/src/main.rs"):
        text = app_main.read_text(encoding="utf-8")
        if not re.search(r"fn\s+main\s*\(\s*\)\s*\{\s*\}", text, re.DOTALL):
            warn(f"binary placeholder has behavior: {app_main.relative_to(ROOT)}")


def validate_required_docs() -> None:
    required = [
        "README.md",
        "ARCHITECTURE.md",
        "VALIDATION.md",
        "docs/architecture/overview.md",
        "docs/api-surface.md",
        "docs/development/toolchain.md",
        "docs/svg-style.md",
        "docs/testing/invariants.md",
        "adr/0005-forbid-per-service-idle-execution-allocation.md",
    ]
    for relative in required:
        if not (ROOT / relative).is_file():
            fail(f"required documentation missing: {relative}")


def validate_nonempty_files() -> None:
    for path in iter_source_files():
        if path.stat().st_size == 0:
            fail(f"empty file: {path.relative_to(ROOT)}")


def main() -> int:
    validate_json()
    validate_toml()
    validate_svg()
    validate_workspace()
    validate_toolchain_baseline()
    validate_proto()
    validate_wit()
    validate_schemas()
    validate_interface_only_policy()
    validate_required_docs()
    validate_nonempty_files()

    print(f"validated repository: {sum(1 for _ in iter_source_files())} source files")
    for message in WARNINGS:
        print(f"warning: {message}")
    for message in ERRORS:
        print(f"error: {message}", file=sys.stderr)
    return 1 if ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(main())
