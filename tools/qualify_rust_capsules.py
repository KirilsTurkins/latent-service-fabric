#!/usr/bin/env python3
"""One bounded outside-checkout Rust authoring qualification, with retained evidence.

No release publishing, production trust changes or acceptance-ticket closure.
Compilers run without inherited secrets. Demo signing is a later, distinct
process and its keys never reach a compiler. Every failure keeps its own output.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, resolve_tools
from tools.check_rust_capsule_ownership import check as ownership
from tools.phase3_resource_identity import file_identity, inventory as directory_identity, source_identity
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands, build
from tools.rust_capsule_project import ROOT, TEMPLATES, create, digest, fresh, read_json, write_json

HELPERS = ("rust_capsule.py", "rust_capsule_project.py", "rust_capsule_build.py", "qualify_rust_capsules.py",
    "run_rust_capsule_workflow.py", "rust_capsule_cases.py", "rust_capsule_node.py", "check_rust_capsule_ownership.py",
    "build_observation.py", "build_process.py", "build_process_linux.py", "build_process_windows.py", "build_process_signals.py",
    "phase2_operator_process.py", "phase2_operator_scenario.py", "phase3_management_scenario.py",
    "phase3_resource_os.py", "phase3_resource_identity.py", "phase3_resource_profile.py", "sdk_provider_scenario.py",
    "sdk_provider_http_fixture.py", "stage_runtime_wit.py", "build_guest_capsules.py")


def inputs():
    return {"runtime": source_identity(ROOT), "sdk": directory_identity(ROOT / "sdk/rust-guest"),
            "wit": directory_identity(ROOT / "wit/platform"), "schemas": directory_identity(ROOT / "schemas"),
            "guide": file_identity(ROOT / "docs/component-development/rust-authoring.md"),
            "helpers": {name: file_identity(ROOT / "tools" / name, 1024 * 1024) for name in HELPERS}}


def guide(output: Path, environment: dict[str, str]):
    """Execute only the reviewed guide's six printed Bash steps with built tools."""
    output = fresh(output)
    source = ROOT / "docs/component-development/rust-authoring.md"
    before = source.read_bytes()
    if len(before) > 32768:
        raise ValueError("authoring guide byte limit")
    blocks = re.findall(r"^```bash\n(.*?)^```$", before.decode().replace("\r\n", "\n"), re.M | re.S)
    if len(blocks) != 6:
        raise ValueError("review the authoring guide execution steps")
    script = output / "guide.sh"
    script.write_text("\n".join(blocks), encoding="utf-8")
    projects = output / "projects"
    commands = Commands(ROOT, output, dict(environment, LSF_RUST_PROJECTS=str(projects)))
    bash = shutil.which("bash", path=environment["PATH"])
    if bash is None:
        raise ValueError("Bash is required to execute the printed authoring guide")
    commands.run("printed-guide", bash, "--noprofile", "--norc", script)
    for filename, category, expected in (
        ("answer.json", "success", [{"ok": "Hello, Ada!"}]),
        ("error.json", "declared-error", [{"err": "Please enter a name."}]),
    ):
        value = read_json(projects / "results" / filename)
        payload = value["data"].get("payload") or value["data"]["declaredError"]["payload"]
        actual = json.loads(base64.b64decode(payload["data"], validate=True))
        if value["category"] != category or not value["outcomeKnown"] or actual != expected:
            raise ValueError("printed authoring guide result mismatch")
    if source.read_bytes() != before:
        raise ValueError("authoring guide changed during execution")
    result = {"status": "passed", "sourceDigest": digest(before), "bashSteps": len(blocks), "commands": commands.records}
    write_json(output / "guide.json", result)
    return result


def qualify(output: Path, *, offline=False):
    output = output.absolute()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("qualification projects must be outside the runtime checkout")
    output = fresh(output)
    result = {"schemaVersion": "latent.rust-capsule.qualification.v1", "status": "in-progress",
              "releasePublication": "not-performed", "newcomerReview345": "pending-human-review"}
    stage = "source"
    try:
        before = inputs()
        write_json(output / "source-inputs.json", before)
        result["sourceIdentityDigest"] = digest((output / "source-inputs.json").read_bytes())
        pins = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        environment = build_environment(output)
        target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_PROFILE_DEV_DEBUG="0", CARGO_PROFILE_TEST_DEBUG="0",
                           CARGO_INCREMENTAL="0", RUSTUP_TOOLCHAIN=pins["rust"]["toolchain"])
        if offline:
            environment["CARGO_NET_OFFLINE"] = "true"
        paths, materials = resolve_tools(pins, ROOT, environment)
        environment["RUSTC"] = str(paths["rustc"])
        commands = Commands(ROOT, output, environment)
        result["tools"] = materials
        stage = "host-build"
        commands.run(stage, paths["cargo"], "build", "--locked", "-p", "latent", "-p", "latentd", "--bins",
            "-p", "latent-packaging", "--example", "package", "--example", "capsule_contracts",
            "-p", "latent-policy", "--example", "capsule_authoring")
        if inputs() != before:
            raise ValueError("host sources changed during compilation")
        binaries = {name: target / "debug" / name for name in ("latent", "latentd", "examples/package", "examples/capsule_contracts", "examples/capsule_authoring")}
        result["binaries"] = {name: file_identity(path) for name, path in binaries.items()}
        stage = "standalone-builds"
        built = []
        result["builds"] = {}
        (output / "projects").mkdir(mode=0o700)
        (output / "builds").mkdir(mode=0o700)
        for template in TEMPLATES:
            project = create(output / "projects" / template, template)
            artifact = build(project, output / "builds" / template, binaries["examples/capsule_contracts"],
                             binaries["examples/package"], "https://github.com/KirilsTurkins/latent-service-fabric", offline=offline)
            built.append(artifact)
            result["builds"][template] = read_json(artifact / "BUILD-COMPLETE.json")
        stage = "ownership"
        result["ownership"] = ownership(output / "ownership", offline=offline)
        stage = "sdk-runtime-ownership"
        # Preserve the full Rust AND C guest gate. The optional Rust-only local
        # iteration switch is deliberately not used by qualification.
        commands.run("build-sdk-guests", sys.executable, ROOT / "tools/build_guest_capsules.py", "--output", output / "sdk-guests")
        commands.environment["LSF_GUEST_CAPSULES"] = str(output / "sdk-guests")
        commands.run("sdk-runtime-tests", paths["cargo"], "test", "--locked", "-p", "latent-wasmtime", "--test", "guest_sdk",
                     "--", "--ignored", "--test-threads=1")
        stage = "sign-demo"
        commands.run(stage, binaries["examples/capsule_authoring"], "demo-sign", output / "releases", *built)
        stage = "enforced-node"
        result["node"] = node_workflow(binaries["latent"], binaries["latentd"], output / "releases", output / "node")
        stage = "printed-guide"
        result["guide"] = guide(output / "guide", environment)
        if inputs() != before or {name: file_identity(path) for name, path in binaries.items()} != result["binaries"]:
            raise ValueError("qualification inputs changed")
        result.update(status="passed", commands=commands.records)
        # Large raw OS observations live in the node receipt rather than being
        # duplicated in the parent qualification marker.
        result["node"] = {"status": result["node"]["status"], "receiptDigest": file_identity(output / "node/workflow.json")["sha256"]}
        write_json(output / "qualification.json", result)
        return result
    except BaseException as error:
        result.pop("node", None)
        result.update(status="failed", stage=stage, reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        write_json(output / "QUALIFICATION-FAILED.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, offline=args.offline)))


if __name__ == "__main__":
    main()
