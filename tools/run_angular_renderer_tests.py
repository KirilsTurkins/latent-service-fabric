#!/usr/bin/env python3
"""Run the real renderer gates using the already-built workspace harnesses."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-manifest", type=Path, required=True)
    parser.add_argument("--component", type=Path, required=True)
    args = parser.parse_args()
    component = args.component.resolve(strict=True)
    if not component.is_file() or not 8 <= component.stat().st_size <= 32 * 1024 * 1024:
        raise RuntimeError("expected a bounded real Angular component")
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    found = {"angular_renderer": set(), "latentd": set()}
    with args.test_manifest.open(encoding="utf-8") as source:
        for line in source:
            if len(line) > 131072:
                raise RuntimeError("Cargo manifest line exceeds limit")
            entry = json.loads(line)
            name = entry.get("target", {}).get("name")
            if entry.get("reason") != "compiler-artifact" or name not in found:
                continue
            if not entry.get("profile", {}).get("test") or not entry.get("executable"):
                continue
            if name == "latentd" and entry["target"]["kind"] != ["lib"]:
                continue
            found[name].add(Path(entry["executable"]).resolve())
    private = component.parent / "renderer.wasm"
    if not private.is_file() or not 8 <= private.stat().st_size <= 32 * 1024 * 1024:
        raise RuntimeError("required private composition fixture is missing")
    environment = dict(os.environ, LSF_ANGULAR_COMPONENT=str(component),
                       LSF_ANGULAR_PRIVATE_COMPONENT=str(private))
    for name, paths in found.items():
        if len(paths) != 1:
            raise RuntimeError(f"expected one {name} test harness")
        executable = paths.pop()
        if not executable.is_file() or not executable.is_relative_to(target):
            raise RuntimeError("harness must belong to this Cargo target")
        filter_args = ["actual_angular_http_"] if name == "latentd" else []
        subprocess.run([str(executable), *filter_args, "--ignored", "--nocapture", "--test-threads=1"],
                       cwd=ROOT, env=environment, check=True, timeout=600)


if __name__ == "__main__":
    main()
