#!/usr/bin/env python3
"""Minimize Java WIT composition stages with the actual pinned parser and C ABI."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import tomllib

sys.dont_write_bytecode = True
if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.java_guest.bindings import generate
from tools.rust_capsule_project import ROOT, fresh, read_file, snapshot, inventory, digest, write_json

CASES = {"shared-types": None, "inclusion": None,
    "multiple-exports": "one nonempty exported interface",
    "aliases": "ambiguous multiple interface versions or import/export aliases",
    "versions": "ambiguous multiple interface versions or import/export aliases",
    "names": "ambiguous multiple interface versions or import/export aliases",
    "public-resources": "borrowed resource export values", "future": "unsupported Java WIT type: future",
    "malformed": "wit-graph"}


def qualify(output: Path) -> dict:
    output = fresh(output)
    source = ROOT / "sdk/java-guest/tests/wit-composition"
    observed = snapshot(source)
    environment = build_environment(output)
    pins = tomllib.loads(read_file(ROOT / "tools/toolchain.toml").decode())
    result = {"profile": "lsf-java-wit-v1+wit-bindgen-0.62.0", "schemaVersion": "latent.java-wit.composition.v1",
        "sourceDigest": digest(inventory(observed)), "execution": "actual-parser-c-abi-bindings-only", "cases": {}}
    try:
        for name, printed, version in (("wasm-tools", "wasm-tools", pins["contracts"]["wasm-tools"]),
                                      ("wit-bindgen", "wit-bindgen-cli", pins["rust"]["dependencies"]["wit-bindgen"])):
            value = run_bounded_result([name, "--version"], cwd=ROOT, env=environment,
                timeout_seconds=10, max_output_bytes=4096)
            if value.returncode != 0 or value.stdout.decode().split()[:2] != [printed, version]:
                raise ValueError("composition-toolchain-must-match-pins")
        for case, expected in CASES.items():
            destination = output / case
            destination.mkdir()
            stages = []

            def run(stage, *arguments):
                value = run_bounded_result(list(map(str, arguments)), cwd=ROOT, env=environment,
                    timeout_seconds=60, max_output_bytes=4 * 1024 * 1024)
                path = destination / (str(len(stages)) + "-" + stage)
                path.with_suffix(".stdout.log").write_bytes(value.stdout)
                path.with_suffix(".stderr.log").write_bytes(value.stderr)
                stages.append({"stage": stage, "exitCode": value.returncode,
                    "stdoutDigest": digest(value.stdout), "stderrDigest": digest(value.stderr)})
                if value.returncode != 0:
                    raise ValueError(stage + ": " + value.stderr.decode("utf-8", "replace")[:4096])
                return value.stdout.decode()

            receipt = {"commands": stages, "expected": "supported" if expected is None else "rejected"}
            result["cases"][case] = receipt
            try:
                first = generate(run, source / case, "service", destination / "bindings")
                second = generate(run, source / case, "service", destination / "repeat")
                if first != second: raise ValueError("composition-bindings-not-reproducible")
                receipt.update(outcome="supported", bindings=first)
                if expected is not None: raise ValueError("unsupported-composition-case-accepted: " + case)
            except ValueError as error:
                if expected is None or expected not in str(error): raise
                receipt.update(outcome="rejected", reason=str(error),
                    stage="parser" if case == "malformed" else "java-binding-profile")
        if snapshot(source) != observed: raise ValueError("composition-case-inputs-changed")
        result["status"] = "passed"
        write_json(output / "composition.json", result)
        return result
    except BaseException as error:
        result.update(status="failed", reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
        write_json(output / "COMPOSITION-FAILED.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    qualify(parser.parse_args().output.resolve())


if __name__ == "__main__": main()
