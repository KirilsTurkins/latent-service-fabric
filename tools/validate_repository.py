#!/usr/bin/env python3
"""Perform dependency-free structural validation of the interface scaffold."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
WARNINGS: list[str] = []


def fail(message: str) -> None:
    ERRORS.append(message)


def warn(message: str) -> None:
    WARNINGS.append(message)


def validate_json() -> None:
    for path in ROOT.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - validation utility
            fail(f"invalid JSON {path.relative_to(ROOT)}: {exc}")


def validate_toml() -> None:
    for path in ROOT.rglob("*.toml"):
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - validation utility
            fail(f"invalid TOML {path.relative_to(ROOT)}: {exc}")


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
        name = package.get("name")
        if not name:
            fail(f"workspace member has no package name: {member}")
        source = directory / "src" / ("main.rs" if member.startswith("apps/") else "lib.rs")
        if not source.is_file():
            fail(f"workspace member source missing: {source.relative_to(ROOT)}")

        for dependency, specification in parsed.get("dependencies", {}).items():
            if isinstance(specification, dict) and "path" in specification:
                target = (directory / specification["path"]).resolve()
                if not target.is_dir():
                    fail(
                        f"path dependency {dependency} from {member} does not exist: "
                        f"{specification['path']}"
                    )


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
    required = {
        "capsule-manifest.schema.json",
        "deployment.schema.json",
        "binding.schema.json",
        "policy.schema.json",
        "trigger.schema.json",
        "route-snapshot.schema.json",
    }
    actual = {path.name for path in (ROOT / "schemas").glob("*.schema.json")}
    missing = required - actual
    if missing:
        fail(f"missing required schemas: {', '.join(sorted(missing))}")

    for path in (ROOT / "schemas").glob("*.schema.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if "$schema" not in document or "$id" not in document:
            fail(f"schema lacks $schema or $id: {path.relative_to(ROOT)}")


def validate_interface_only_policy() -> None:
    forbidden = ("todo!", "unimplemented!", "panic!(\"not implemented", "TODO_IMPLEMENTATION")
    for path in ROOT.rglob("*.rs"):
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
        "docs/architecture/overview.md",
        "docs/api-surface.md",
        "docs/testing/invariants.md",
        "adr/0005-forbid-per-service-idle-execution-allocation.md",
    ]
    for relative in required:
        if not (ROOT / relative).is_file():
            fail(f"required documentation missing: {relative}")


def validate_nonempty_files() -> None:
    for path in ROOT.rglob("*"):
        if path.is_file() and path.stat().st_size == 0:
            fail(f"empty file: {path.relative_to(ROOT)}")


def main() -> int:
    validate_json()
    validate_toml()
    validate_workspace()
    validate_proto()
    validate_wit()
    validate_schemas()
    validate_interface_only_policy()
    validate_required_docs()
    validate_nonempty_files()

    print(f"validated repository: {sum(1 for p in ROOT.rglob('*') if p.is_file())} files")
    for message in WARNINGS:
        print(f"warning: {message}")
    for message in ERRORS:
        print(f"error: {message}", file=sys.stderr)
    return 1 if ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(main())
