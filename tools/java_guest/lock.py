"""Pinned full-SDK binding reference; changed outputs require explicit review."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile

if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.java_guest.bindings import generate
from tools.rust_capsule_project import ROOT, read_file
from tools.stage_runtime_wit import copy_wit_tree, dependencies


def reference(run, sdk: Path, platform: Path, output: Path) -> dict:
    source, staged = sdk / "wit", output / "wit"
    copy_wit_tree(source, staged)
    for package in dependencies(source, platform): copy_wit_tree(package, staged / "deps" / package.name)
    return generate(run, staged, "latent:java-guest/sdk@1.0.0", output / "bindings")


def verify(run, sdk: Path, platform: Path, output: Path) -> str:
    actual = reference(run, sdk, platform, output)
    if actual != json.loads(read_file(sdk / "bindings.lock.json")):
        raise ValueError("Java SDK binding drift: inspect and explicitly update the reviewed lock")
    return actual["digest"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Explicitly regenerate the reviewed lock; inspect its diff")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lsf-java-bindings-") as temporary:
        output = Path(temporary)
        environment = build_environment(output)
        def run(_stage, tool, *arguments):
            value = run_bounded_result([tool, *map(str, arguments)], ROOT, environment,
                                      timeout_seconds=60, max_output_bytes=4 * 1024 * 1024)
            if value.returncode: raise ValueError(value.stderr.decode("utf-8"))
            return value.stdout.decode("utf-8")
        sdk, platform = ROOT / "sdk/java-guest", ROOT / "wit/platform"
        if args.update:
            (sdk / "bindings.lock.json").write_text(json.dumps(reference(run, sdk, platform, output), indent=2) + "\n", encoding="utf-8")
        else: print(verify(run, sdk, platform, output))


if __name__ == "__main__": main()
