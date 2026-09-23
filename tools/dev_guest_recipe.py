#!/usr/bin/env python3
"""Typed controller adapter around the maintained Rust authoring recipe (#544)."""
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
from tools.rust_capsule_build import build


def diagnostics(output: Path) -> None:
    """Forward Cargo's primary source diagnostics, not arbitrary retained logs."""
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


def compile_rust(payload: Path, project: Path, output: Path, check) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project, output = Path(os.path.abspath(args.project)), Path(os.path.abspath(args.output))
    # Distribution layout: <payload>/recipe/tools/dev_guest_recipe.py.
    payload = Path(__file__).resolve().parents[2]
    result = {"schemaVersion": "latent.dev.compiler-result.v1", "language": "rust", "ownerIssue": 544,
              "cleanup": "reaped", "code": "success"}
    try:
        with owned_cancellation() as cancellation:
            compile_rust(payload, project, output, cancellation.check)
    except BuildProcessError as error:
        result["code"] = "compiler-process-failed"
        if error.reason in {"process-cleanup", "process-ownership"}:
            result.update(code="compiler-cleanup-unconfirmed", cleanup="uncertain")
    except (KeyboardInterrupt, SystemExit):
        result["code"] = "compiler-cancelled"
    except (ValueError, OSError, RuntimeError) as error:
        result["code"] = "compiler-input-or-build-failed"
        detail = "".join(character if 32 <= ord(character) != 127 else " " for character in str(error))[:512]
        sys.stderr.write("Maintained Rust recipe: " + detail + "\n")
    finally:
        diagnostics(output)
    sys.stdout.buffer.write(encode(result))
    return 0 if result["code"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
