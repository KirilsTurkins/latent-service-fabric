#!/usr/bin/env python3
"""Typed controller adapter around maintained language-owned authoring recipes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process import BuildProcessError, run_bounded
from tools.build_process_signals import owned_cancellation
from tools.dev_guest_tools import ZIG_VERSION, linker, stage_registry, unpack_zig
from tools.dev_workflow.common import encode, require


def diagnostics(output: Path, language: str) -> None:
    """Forward Cargo's primary source diagnostics, not arbitrary retained logs."""
    if language == "c":
        c_diagnostics(output)
        return
    retained = 0
    for path in sorted((output / "logs").glob("*-compile.stdout.txt")):
        with path.open("rb") as source:
            for raw in source:
                if len(raw) > 16384:
                    continue
                try:
                    value = json.loads(raw)
                except (ValueError, RecursionError):
                    continue
                if not isinstance(value, dict) or value.get("reason") != "compiler-message":
                    continue
                retained += len(raw)
                if retained > 128 * 1024:
                    return
                sys.stderr.buffer.write(raw)


def c_diagnostics(output: Path) -> None:
    from tools.dev_workflow import paths
    from tools.dev_workflow.common import decode
    if not (output / "diagnostic-source.json").exists():
        return
    mapping = decode(paths.read(output, "diagnostic-source.json", 16384))
    prefix = (mapping["capturedSource"] + "/").encode()
    replacement = (mapping["requestedSource"] + "/").encode()
    retained = 0
    for path in sorted((output / "logs").glob("*-zig.stderr.txt")):
        for line in paths.read(path.parent, path.name, 4 * 1024 * 1024).splitlines():
            if len(line) > 16384 or prefix not in line:
                continue
            raw = line.replace(prefix, replacement) + b"\n"
            retained += len(raw)
            if retained > 128 * 1024:
                return
            sys.stderr.buffer.write(raw)


def compile_rust(payload: Path, project: Path, output: Path, check) -> None:
    from tools.rust_capsule_build import build
    require(sys.platform == "linux" and platform.machine() == "x86_64", "rust-adapter-requires-linux-x86-64")
    cache = project.parent / "build-cache"
    require(cache.is_dir() and output.parent == project.parent, "rust-adapter-owned-attempt-paths")
    sdk = payload / "sdk"
    os.environ.update(PATH=str(sdk / "bin") + os.pathsep + os.defpath, CARGO_HOME=str(cache / "cargo"))
    stage_registry(sdk / "registry", cache / "cargo/registry", check)
    zig = unpack_zig(sdk / "zig.tar.xz", cache / "zig", check)
    version = run_bounded([str(zig), "version"], cwd=project, env=dict(os.environ),
                          timeout_seconds=10, max_output_bytes=1024).stdout.decode().strip()
    require(version == ZIG_VERSION, "guest-linker-version")
    check()
    build(project, output, sdk / "bin/capsule-contracts", None,
          "https://github.com/KirilsTurkins/latent-service-fabric", offline=True,
          host_linker=linker(zig, cache), rust_bin=sdk / "rust/bin")
    check()


def compile_c(payload: Path, project: Path, output: Path, check) -> None:
    from tools.c_capsule_build import build
    require(sys.platform == "linux" and platform.machine() == "x86_64", "c-adapter-requires-linux-x86-64")
    cache = project.parent / "build-cache"
    require(cache.is_dir() and output.parent == project.parent, "c-adapter-owned-attempt-paths")
    sdk = payload / "sdk"
    os.environ["PATH"] = str(sdk / "bin") + os.pathsep + os.defpath
    zig = unpack_zig(sdk / "zig.tar.xz", cache / "zig", check)
    build(project, output, sdk / "bin/capsule-contracts", None,
          "https://github.com/KirilsTurkins/latent-service-fabric",
          installed={"zig": zig, "wit-bindgen": sdk / "bin/wit-bindgen", "wasm-tools": sdk / "bin/wasm-tools"})
    check()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("rust", "c"), required=True)
    args = parser.parse_args()
    project, output = Path(os.path.abspath(args.project)), Path(os.path.abspath(args.output))
    # Distribution layout: <payload>/recipe/tools/dev_guest_recipe.py.
    payload = Path(__file__).resolve().parents[2]
    result = {"schemaVersion": "latent.dev.compiler-result.v1", "language": args.language, "ownerIssue": {"rust": 544, "c": 545}[args.language],
              "cleanup": "reaped", "code": "success"}
    try:
        with owned_cancellation() as cancellation:
            {"rust": compile_rust, "c": compile_c}[args.language](payload, project, output, cancellation.check)
    except BuildProcessError as error:
        result["code"] = "compiler-process-failed"
        if error.reason in {"process-cleanup", "process-ownership"}:
            result.update(code="compiler-cleanup-unconfirmed", cleanup="uncertain")
    except (KeyboardInterrupt, SystemExit):
        result["code"] = "compiler-cancelled"
    except (ValueError, OSError, RuntimeError) as error:
        result["code"] = "compiler-input-or-build-failed"
        detail = "".join(character if 32 <= ord(character) != 127 else " " for character in str(error))[:512]
        sys.stderr.write("Maintained " + args.language + " recipe: " + detail + "\n")
    finally:
        diagnostics(output, args.language)
    sys.stdout.buffer.write(encode(result))
    return 0 if result["code"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
