"""Shared exact-JDK and non-preview class-file checks for both Java SDK builds."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "tools/toolchain.toml"


def baseline() -> dict:
    return tomllib.loads(BASELINE.read_text(encoding="utf-8"))["sdk"]


def release() -> int:
    return int(baseline()["java"].split(".", maxsplit=1)[0])


def executable(home: Path, name: str) -> str:
    return str(home / "bin" / (name + (".exe" if sys.platform == "win32" else "")))


def check_jdk(home: Path | None = None) -> Path:
    # All build tools come from one installation. Never install or fall back to
    # another JDK when JAVA_HOME or the caller's explicit installation is wrong.
    if home is None:
        configured = os.environ.get("JAVA_HOME")
        if configured:
            home = Path(configured)
        else:
            launcher = shutil.which("java")
            if launcher is None:
                raise ValueError("Java is missing; set JAVA_HOME to the pinned Temurin JDK")
            home = Path(launcher).resolve().parent.parent
    home = home.resolve(strict=True)
    spec = importlib.util.spec_from_file_location("lsf_java_versions", ROOT / "tools/check_tool_versions.py")
    assert spec is not None and spec.loader is not None
    versions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(versions)
    try:
        versions.validate_java(baseline()["java"], home)
    except versions.VersionError as exc:
        raise ValueError(str(exc)) from None
    return home


def check_header(header: bytes, label: str, java_release: int) -> None:
    if len(header) != 8:
        raise ValueError(f"truncated Java class header: {label}")
    magic, minor, major = struct.unpack(">IHH", header)
    if magic != 0xCAFEBABE or (major, minor) != (java_release + 44, 0):
        raise ValueError(f"class must target non-preview Java {java_release}: {label} (major={major}, minor={minor})")


def verify_classes(directory: Path) -> int:
    paths = sorted(directory.rglob("*.class"))
    if not paths:
        raise ValueError(f"no Java classes found: {directory}")
    selected_release = release()
    for path in paths:
        with path.open("rb") as stream:
            check_header(stream.read(8), str(path), selected_release)
    return len(paths)


def verify_jar(path: Path) -> int:
    selected_release = release()
    with zipfile.ZipFile(path) as archive:
        entries = [item for item in archive.infolist() if item.filename.endswith(".class")]
        if not entries:
            raise ValueError(f"no Java classes in JAR: {path}")
        for item in entries:
            with archive.open(item) as stream:
                check_header(stream.read(8), item.filename, selected_release)
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--java-home", type=Path)
    verify = subparsers.add_parser("classes")
    verify.add_argument("paths", type=Path, nargs="+")
    args = parser.parse_args()
    if args.action == "check":
        home = check_jdk(args.java_home)
        print(json.dumps({"java": baseline()["java"], "javaHome": str(home), "release": release()}))
    else:
        count = sum(verify_classes(path) if path.is_dir() else verify_jar(path) for path in args.paths)
        print(json.dumps({"release": release(), "classMajor": release() + 44, "preview": False, "classes": count}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"Java toolchain validation failed: {exc}") from None
