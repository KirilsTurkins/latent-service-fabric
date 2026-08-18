#!/usr/bin/env python3
"""Verify that cross-language SDK compilers match the pinned baseline exactly."""

from __future__ import annotations

import platform
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools" / "toolchain.toml"
TSC = ROOT / "sdk" / "typescript-client" / "node_modules" / "typescript" / "bin" / "tsc"


class VersionError(RuntimeError):
    """Raised when an installed tool does not match the repository baseline."""


def run(command: Sequence[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.stdout.strip()


def extract(pattern: str, output: str, tool: str) -> str:
    match = re.search(pattern, output, re.MULTILINE)
    if match is None:
        raise VersionError(f"could not parse {tool} version from: {output!r}")
    return match.group(1)


def require_exact(tool: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise VersionError(f"{tool} version mismatch: expected {expected}, found {actual}")


def java_runtime_version(output: str) -> str:
    return extract(r"^\s*java\.runtime\.version\s*=\s*([^\s]+)", output, "Java runtime")


def normalize_temurin_runtime(version: str) -> str:
    return version.removesuffix("-LTS")


def validate() -> None:
    baseline = tomllib.loads(BASELINE.read_text(encoding="utf-8"))
    contracts = baseline["contracts"]
    sdk = baseline["sdk"]

    require_exact("Python", platform.python_version(), contracts["python"])
    require_exact("Go", extract(r"\bgo(\d+\.\d+\.\d+)\b", run(["go", "version"]), "Go"), sdk["go"])
    require_exact("Node", run(["node", "--version"]).removeprefix("v"), sdk["node"])
    require_exact(
        "TypeScript",
        extract(r"^Version\s+(\S+)$", run(["node", str(TSC), "--version"]), "TypeScript"),
        sdk["typescript"],
    )

    expected_java = sdk["java"]
    expected_javac = expected_java.split("+", maxsplit=1)[0]
    require_exact(
        "javac",
        extract(r"^javac\s+(\S+)$", run(["javac", "-version"]), "javac"),
        expected_javac,
    )
    java_settings = run(["java", "-XshowSettings:properties", "-version"])
    if not re.search(r"^\s*java\.vendor\s*=\s*Eclipse Adoptium\s*$", java_settings, re.MULTILINE):
        raise VersionError("Java distribution mismatch: expected Eclipse Adoptium Temurin")
    require_exact(
        "Java runtime",
        normalize_temurin_runtime(java_runtime_version(java_settings)),
        expected_java,
    )

    require_exact(".NET", run(["dotnet", "--version"]), sdk["dotnet"])
    require_exact("Zig", run(["zig", "version"]), sdk["zig"])
    require_exact(
        "Zig C frontend",
        extract(
            r"^clang version (\d+\.\d+\.\d+)",
            run(["zig", "cc", "--version"]),
            "Zig C frontend",
        ),
        sdk["zig_clang"],
    )


def main() -> int:
    try:
        validate()
    except (OSError, subprocess.CalledProcessError, VersionError) as exc:
        print(f"toolchain validation failed: {exc}", file=sys.stderr)
        return 1
    print("validated exact SDK toolchain versions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
