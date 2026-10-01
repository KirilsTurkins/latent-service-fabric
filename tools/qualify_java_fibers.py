#!/usr/bin/env python3
"""Prepare an actual opt-in fiber component and unchanged reference JDK control.

Signed node execution is a separate selected test; this compiler receipt alone
does not qualify the complete Java standard concurrency profile.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
if __package__ in (None, ""): sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_guest.compiler import Compiler
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json


def throwable_model_control(compiler: Compiler, output: Path) -> dict:
    """Test the actual locked classlib IR, without loading application classes."""
    names = {"teavm-classlib", "teavm-core", "teavm-extension-spi", "teavm-interop",
             "teavm-relocated-libs-asm", "teavm-relocated-libs-asm-analysis",
             "teavm-relocated-libs-asm-commons", "teavm-relocated-libs-asm-tree", "teavm-relocated-libs-hppc"}
    lock = json.loads(read_file(compiler.sdk / "feasibility/dependencies.lock.json"))
    artifacts = [item for item in lock["artifacts"]
                 if Path(item["path"]).parts[-3] in names and item["path"].startswith("org/teavm/")]
    if (len(artifacts) != len(names) or {Path(item["path"]).parts[-3] for item in artifacts} != names):
        raise ValueError("Java Throwable model requires the exact locked tooling closure")
    cache = compiler.directory / "gradle-home/caches/modules-2/files-2.1"
    jars, identities = [], {}
    for item in sorted(artifacts, key=lambda row: row["path"]):
        parts = Path(item["path"]).parts
        candidates = list((cache / ".".join(parts[:-3]) / parts[-3] / parts[-2]).glob("*/" + parts[-1]))
        if len(candidates) != 1: raise ValueError("Java Throwable model tooling jar is missing or ambiguous")
        raw = read_file(candidates[0], 25 * 1024 * 1024)
        if len(raw) != item["size"] or digest(raw) != item["sha256"]:
            raise ValueError("Java Throwable model tooling jar integrity mismatch")
        jars.append(candidates[0])
        identities[item["path"]] = item["sha256"]
    output.mkdir()
    classpath = os.pathsep.join(map(str, jars))
    compiler.run("throwable-model-compile", "javac", "-proc:none", "--release", "25", "-cp", classpath,
                 "-d", output,
                 compiler.sdk / "fibers/compiler/dev/latent/guest/runtime/compiler/ThrowableInitialization.java",
                 compiler.sdk / "fibers/conformance/compiler/ThrowableInitializationControl.java")
    result = compiler.run("throwable-model-control", "java", "-Xmx256m", "-cp",
                          str(output) + os.pathsep + classpath,
                          "dev.latent.guest.runtime.compiler.ThrowableInitializationControl")
    expected = ("THROWABLE_INITIALIZATION_CONTROL PASS constructors=5;original-negative;real-array-initializer;"
                "method-owners;layout-and-repeated-port-negatives;application-identity")
    if result.strip() != expected: raise ValueError("Java Throwable model control did not complete")
    return {"status": "actual-locked-classlib-model-passed", "constructors": 5, "jarDigests": identities}


def recipe_inputs() -> dict[str, str]:
    paths = [Path(__file__), *sorted((ROOT / "tools/java_guest").glob("*.py")),
             ROOT / "tools/stage_runtime_wit.py", ROOT / "tools/rust_capsule_project.py",
             ROOT / "tools/build_observation.py", ROOT / "tools/build_process.py",
             ROOT / "tools/build_process_linux.py", ROOT / "tools/build_process_windows.py"]
    return {path.relative_to(ROOT).as_posix(): digest(read_file(path)) for path in paths}


def prepare(output: Path, wasi_sdk: Path, *, gradle="gradle", offline_cache: Path | None = None):
    output = fresh(output)
    fixture = ROOT / "sdk/java-guest/fibers/conformance"
    # Exercise real source attribution independently of package-directory layout.
    source = output / "src/Capsule.java"
    source.parent.mkdir(parents=True)
    source.write_bytes(read_file(fixture / "Capsule.java"))
    wit = output / "wit/service.wit"
    wit.parent.mkdir()
    wit.write_bytes(read_file(fixture / "service.wit"))
    started = time.monotonic()
    before = recipe_inputs()
    report = {"formatVersion": 1, "profile": "teavm-activation-fibers-v1", "qualification": "pending",
              "status": "running", "nodeExecution": "not-run", "sourceDigest": digest(source.read_bytes())}
    report["recipeInputs"] = before
    try:
        compiler = Compiler(output / "compiler", wasi_sdk, gradle=gradle, offline_cache=offline_cache, timeout=1200)
        control = output / "reference-jdk"
        control.mkdir()
        main = control / "Main.java"
        main.write_bytes(read_file(fixture / "Main.java"))
        compiler.paths["javac"] = compiler.paths["java"].parent / "javac"
        compiler.run("reference-jdk-compile", "javac", "-proc:none", "-d", control, source, main)
        report["reference"] = []
        for iteration in range(3):
            result = compiler.run(f"reference-jdk-{iteration}", "java", "-cp", control, "Main")
            if result.strip() != "42 42 42 42": raise ValueError("reference-JDK fiber observable mismatch")
            report["reference"].append({"iteration": iteration, "modes": [0, 1, 2, 3], "results": [42, 42, 42, 42]})
        component, report["record"] = compiler.compile(output / "src", wit.parent,
            "tests:caller/service@1.0.0", output / "build", activation_profile=True)
        report["throwableModel"] = throwable_model_control(compiler, output / "throwable-model")
        compiler.check_unchanged()
        report["sdkInputs"] = {name: digest(data) for name, data in compiler.original_sdk.items()}
        report["componentDigest"] = digest(read_file(component, 64 * 1024 * 1024))
        compiler.check_unchanged()
        if recipe_inputs() != before: raise ValueError("Java fiber qualification recipe changed during preparation")
        report["commands"] = compiler.records
        (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
        report["status"] = "component-built-unqualified"
    except BaseException as error:
        report.update(status="failed", reason=str(error))
        raise
    finally:
        report["seconds"] = round(time.monotonic() - started, 6)
        write_json(output / "FIBERS-COMPILE.json", report)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wasi-sdk", type=Path, required=True)
    parser.add_argument("--gradle", default="gradle")
    parser.add_argument("--offline-cache", type=Path)
    args = parser.parse_args()
    prepare(args.output, args.wasi_sdk, gradle=args.gradle, offline_cache=args.offline_cache)


if __name__ == "__main__": main()
