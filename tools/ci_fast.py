#!/usr/bin/env python3
"""Execute the selected host-only correctness lane and retain actual build/test evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import ci_suite_inventory as registry
from tools.ci_rust_artifacts import ArtifactError, require_source, run_owned
from tools.ci_suite_discovery import discover


def selected_packages(encoded: str, data: dict) -> list[str]:
    registry.require(len(encoded) <= 8192, "package-selection-limit")
    packages = json.loads(encoded)
    registry.require(isinstance(packages, list) and packages and all(isinstance(n, str) for n in packages),
                     "empty-or-invalid-package-selection")
    registry.require(packages == sorted(set(packages)) and set(packages) <= set(data["fastPackages"]),
                     "unregistered-fast-package")
    graph = registry.workspace(registry.ROOT)
    deps = registry.closure(graph, set(packages))
    registry.require(not any(f in name for name in deps for f in data["forbiddenFastDependencies"]),
                     "heavyweight-fast-dependency")
    return packages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages-json", required=True)
    parser.add_argument("--output", type=Path, default=Path("target/ci-fast"))
    parser.add_argument("--msrv", action="store_true")
    args = parser.parse_args()
    result = {"schemaVersion": "latent.ci.fast.v1", "passed": False, "commands": []}
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        data = registry.load()
        packages = selected_packages(args.packages_json, data)
        result["packages"] = packages
        require_source(registry.ROOT, os.environ.get("GITHUB_SHA"), dict(os.environ))
        package_args = [value for name in packages for value in ("-p", name)]
        recipe = [*package_args, "--all-targets", "--all-features", "--locked"]

        def command(argv: list[str], name: str, *, capture: bool = False) -> bytes:
            print("+ " + " ".join(argv), flush=True)
            start = time.monotonic()
            status, output = run_owned(argv, cwd=registry.ROOT, env=dict(os.environ),
                                       timeout=900, maximum=32 * 1024 * 1024)
            (args.output / (name + ".log")).write_bytes(output)
            result["commands"].append({"argv": argv, "seconds": round(time.monotonic() - start, 6),
                                       "exitCode": status})
            if not capture or status:
                print(output.decode("utf-8", errors="replace")[-16000:], flush=True)
            registry.require(status == 0, "fast-command-failed: " + name)
            return output

        if args.msrv:
            command(["cargo", "+1.94.1", "check", *recipe], "msrv")
        else:
            command(["cargo", "fmt", "--all", "--check"], "format")
            command(["cargo", "check", *recipe], "check")
            command(["cargo", "clippy", *recipe], "clippy")
            if "latent-admission" in packages:
                command(["cargo", "clippy", "-p", "latent-admission", "--all-targets", "--all-features",
                         "--locked", "--no-deps", "--", "-D", "warnings"], "strict-clippy")
            encoded = command(["cargo", "test", *recipe, "--no-run", "--message-format=json,json-render-diagnostics"],
                              "build", capture=True)
            inventory = args.output / "cargo-artifacts.jsonl"
            inventory.write_bytes(encoded)
            result["discovery"] = discover(registry.ROOT, inventory, data, packages, execute=True)
            docs = [p for p in packages if p in {"latent-admission", "latent-scheduler"}]
            if docs:
                command(["cargo", "test", *[a for p in docs for a in ("-p", p)], "--doc", "--locked"], "doctests")
        result["passed"] = True
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except (ArtifactError, ValueError, OSError, TypeError, KeyError) as error:
        result["error"] = str(error)
        print(f"Fast correctness failed: {error}", file=sys.stderr)
        return 1
    finally:
        (args.output / ("msrv-receipt.json" if args.msrv else "receipt.json")).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
