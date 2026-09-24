#!/usr/bin/env python3
"""Actual maintained compiler + generated Java bindings; node gate is separate."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time

if __package__ in (None, ""): sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_guest.compiler import Compiler
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wasi-sdk", type=Path, required=True)
    args = parser.parse_args()
    output = fresh(args.output)
    started = time.monotonic()
    report = {"formatVersion": 1, "qualified": False, "nodeExecution": "not-run", "status": "running"}
    try:
        source = output / "source/dev/latent/app/Capsule.java"
        source.parent.mkdir(parents=True)
        source.write_bytes(read_file(ROOT / "sdk/java-guest/conformance/Capsule.java"))
        compiler = Compiler(output / "compiler", args.wasi_sdk)
        component, details = compiler.compile(output / "source", ROOT / "sdk/java-guest/conformance",
                                             "tests:java-feasibility/capsule@1.0.0", output / "compiled")
        compiler.check_unchanged()
        report.update(status="component-built-unqualified", componentDigest=digest(read_file(component, 64 * 1024 * 1024)),
                      commands=compiler.records, details=details)
        (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
    except BaseException as error:
        report.update(status="failed", reason=str(error))
        raise
    finally:
        report["seconds"] = round(time.monotonic() - started, 6)
        write_json(output / "report.json", report)


if __name__ == "__main__": main()
