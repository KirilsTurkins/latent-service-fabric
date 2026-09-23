#!/usr/bin/env python3
"""Bounded actual-source Java SDK, signed-node and printed-guide qualification.

Builds never receive signing keys. Failed stages retain their own diagnostics.
This local experiment does not publish a runtime release or close human review.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time
import tomllib

sys.dont_write_bytecode = True
if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, resolve_tools
from tools.java_capsule_build import build
from tools.java_capsule_project import create
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.qualify_rust_capsules import HELPERS, guide
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, read_json, write_json

JAVA_HELPERS = (*HELPERS, "java_capsule.py", "java_capsule_project.py", "java_capsule_build.py",
    "qualify_java_capsules.py", "qualify_java_bridge.py", "build_java_guest_capsules.py",
    "java_guest/compiler.py", "java_guest/bindings.py", "java_guest/model.py", "java_guest/java.py",
    "java_guest/c.py", "java_guest/lock.py", "java_guest/surface.py", "guest_runtime_grants.py", "build_snapshot.py", "../.cargo/managed-guest.toml")


def inputs():
    return {"runtime": source_identity(ROOT), "sdk": inventory(ROOT / "sdk/java-guest"),
            "wit": inventory(ROOT / "wit/platform"), "schemas": inventory(ROOT / "schemas"),
            "guide": file_identity(ROOT / "docs/component-development/java-authoring.md"),
            "helpers": {name: file_identity(ROOT / "tools" / name, 1024 * 1024) for name in JAVA_HELPERS}}


def verify_inputs(output: Path, before: dict, binaries: dict, expected_binaries: dict):
    after = inputs()
    actual_binaries = {name: file_identity(path) for name, path in binaries.items()}
    write_json(output / "source-inputs-after.json", after)
    write_json(output / "binaries-after.json", actual_binaries)
    if after != before:
        raise ValueError("Java qualification source inputs changed")
    changed = sorted(name for name in actual_binaries.keys() | expected_binaries.keys()
                     if actual_binaries.get(name) != expected_binaries.get(name))
    if changed:
        raise ValueError("Java qualification binaries changed: " + ", ".join(changed))


def qualify(output: Path, wasi_sdk: Path):
    output = output.absolute()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Java qualification projects must be outside the runtime checkout")
    output = fresh(output)
    result = {"schemaVersion": "latent.java-capsule.qualification.v1", "status": "in-progress",
              "releasePublication": "not-performed", "newcomerReview345": "pending-human-review"}
    stage, commands = "source", None
    try:
        before = inputs()
        write_json(output / "source-inputs.json", before)
        result["sourceIdentityDigest"] = digest((output / "source-inputs.json").read_bytes())
        pins = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        environment = build_environment(output)
        target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_PROFILE_DEV_DEBUG="0", CARGO_PROFILE_TEST_DEBUG="0",
            CARGO_INCREMENTAL="0", CARGO_BUILD_JOBS="2", RUSTUP_TOOLCHAIN=pins["rust"]["toolchain"],
            PYTHONDONTWRITEBYTECODE="1", WASI_SDK_PATH=str(wasi_sdk.resolve(strict=True)))
        if "JAVA_HOME" in os.environ: environment["JAVA_HOME"] = os.environ["JAVA_HOME"]
        paths, materials = resolve_tools(pins, ROOT, environment)
        environment["RUSTC"] = str(paths["rustc"])
        commands = Commands(ROOT, output, environment, deadline_seconds=3600, command_seconds=1800)
        result["tools"] = materials
        stage = "host-build"
        commands.run(stage, paths["cargo"], "--config", ROOT / ".cargo/managed-guest.toml", "build", "--locked", "-p", "latent", "-p", "latentd", "--bins",
            "-p", "latent-packaging", "--example", "package", "--example", "capsule_contracts",
            "-p", "latent-policy", "--example", "capsule_authoring")
        if inputs() != before: raise ValueError("host sources changed during compilation")
        binaries = {name: target / "debug" / name for name in (
            "latent", "latentd", "examples/package", "examples/capsule_contracts", "examples/capsule_authoring")}
        result["binaries"] = {name: file_identity(path) for name, path in binaries.items()}
        stage = "standalone-builds"
        built, result["builds"] = [], {}
        (output / "projects").mkdir(mode=0o700)
        (output / "builds").mkdir(mode=0o700)
        for template in TEMPLATES:
            project = create(output / "projects" / template, template)
            artifact = build(project, output / "builds" / template, binaries["examples/capsule_contracts"],
                binaries["examples/package"], "https://github.com/KirilsTurkins/latent-service-fabric", wasi_sdk,
                timeout=min(900, commands.deadline - time.monotonic()))
            built.append(artifact)
            result["builds"][template] = read_json(artifact / "BUILD-COMPLETE.json")
        stage = "ownership-state-machines"
        classes = output / "ownership-classes"
        classes.mkdir()
        runtime = ROOT / "sdk/java-guest/runtime/dev/latent/guest"
        commands.run("ownership-compile", "javac", "-d", classes, ROOT / "sdk/java-guest/tests/Ownership.java",
            *(runtime / (name + ".java") for name in ("Handle", "SensitiveBytes", "Unsigned64")))
        commands.run(stage, "java", "-cp", classes, "dev.latent.guest.Ownership")
        stage = "sdk-runtime-ownership"
        commands.run("build-sdk-guests", sys.executable, ROOT / "tools/build_java_guest_capsules.py",
            "--output", output / "sdk-guests", "--wasi-sdk", wasi_sdk,
            "--contracts-tool", binaries["examples/capsule_contracts"], "--packager", binaries["examples/package"])
        commands.environment.update(LSF_GUEST_CAPSULES=str(output / "sdk-guests"), LSF_GUEST_SDK_LANGUAGE="java")
        commands.run("sdk-runtime-tests", paths["cargo"], "--config", ROOT / ".cargo/managed-guest.toml", "test", "--locked", "-p", "latent-wasmtime", "--test", "guest_sdk",
            "--", "--ignored", "--test-threads=1")
        stage = "sign-demo"
        commands.run(stage, binaries["examples/capsule_authoring"], "demo-sign", output / "releases", *built)
        stage = "enforced-node"
        result["node"] = node_workflow(binaries["latent"], binaries["latentd"], output / "releases", output / "node", language="java")
        stage = "printed-guide"
        result["guide"] = guide(output / "guide", environment, "java")
        stage = "final-integrity"
        verify_inputs(output, before, binaries, result["binaries"])
        if time.monotonic() >= commands.deadline: raise ValueError("Java qualification deadline exceeded")
        result.update(status="passed", commands=commands.records)
        result["node"] = {"status": result["node"]["status"], "receiptDigest": file_identity(output / "node/workflow.json")["sha256"]}
        write_json(output / "qualification.json", result)
        return result
    except BaseException as error:
        result.pop("node", None)
        result.update(status="failed", stage=stage, commands=commands.records if commands else [],
            reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        write_json(output / "QUALIFICATION-FAILED.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wasi-sdk", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, args.wasi_sdk)))


if __name__ == "__main__": main()
