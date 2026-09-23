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


def inputs(language="rust"):
    helpers = HELPERS
    if language == "c":
        helpers += ("c_capsule.py", "c_capsule_project.py", "c_capsule_build.py",
                    "qualify_c_capsules.py", "c_guest/compiler.py", "c_guest/bindings.py")
    elif language == "go":
        helpers += ("go_capsule.py", "go_capsule_project.py", "go_capsule_build.py",
                    "qualify_go_capsules.py", "build_go_guest_capsules.py", "guest_runtime_grants.py",
                    "go_guest/compiler.py", "go_guest/runtime.py", "go_guest/sdk.py", "../.cargo/managed-guest.toml")
    elif language == "typescript":
        helpers += ("typescript_capsule.py", "build_typescript_guest_capsules.py", "qualify_typescript_capsules.py",
                    "typescript_guest/project.py", "typescript_guest/build.py", "typescript_guest/compiler.py",
                    "typescript_guest/probe.py", "typescript_guest/componentize.mjs", "typescript_guest/bundle.mjs",
                    "typescript_guest/signed64.mjs", "typescript_guest/resources.mjs", "../.cargo/managed-guest.toml")
    elif language == "dotnet":
        helpers += ("dotnet_capsule.py", "build_dotnet_guest_capsules.py", "qualify_dotnet_capsules.py",
                    "dotnet_guest/project.py", "dotnet_guest/build.py", "dotnet_guest/compiler.py", "dotnet_guest/sdk.py",
                    "dotnet_guest_bindings.py", "check_dotnet_capsule_ownership.py", "guest_runtime_grants.py",
                    "../.cargo/managed-guest.toml")
    return {"runtime": source_identity(ROOT), "sdk": directory_identity(ROOT / f"sdk/{language}-guest"),
            "wit": directory_identity(ROOT / "wit/platform"), "schemas": directory_identity(ROOT / "schemas"),
            "guide": file_identity(ROOT / f"docs/component-development/{language}-authoring.md"),
            "helpers": {name: file_identity(ROOT / "tools" / name, 1024 * 1024) for name in helpers}}


def guide(output: Path, environment: dict[str, str], language="rust"):
    """Execute only the reviewed guide's six printed Bash steps with built tools."""
    output = fresh(output)
    source = ROOT / f"docs/component-development/{language}-authoring.md"
    before = source.read_bytes()
    if len(before) > 32768:
        raise ValueError("authoring guide byte limit")
    blocks = re.findall(r"^```bash\n(.*?)^```$", before.decode().replace("\r\n", "\n"), re.M | re.S)
    if len(blocks) != 6:
        raise ValueError("review the authoring guide execution steps")
    script = output / "guide.sh"
    script.write_text("\n".join(blocks), encoding="utf-8")
    projects = output / "projects"
    commands = Commands(ROOT, output, dict(environment, **{f"LSF_{language.upper()}_PROJECTS": str(projects)}))
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


def qualify(output: Path, *, offline=False, language="rust", typescript_tools=None, dotnet_tools=None):
    if language not in {"rust", "c", "go", "typescript", "dotnet"}:
        raise ValueError("unsupported authoring qualification language")
    if language == "typescript" and typescript_tools is None:
        raise ValueError("explicit pinned TypeScript compiler installation required")
    creator, builder = create, build
    if language == "c":
        from tools.c_capsule_project import create as creator
        from tools.c_capsule_build import build as builder
    elif language == "go":
        from tools.go_capsule_project import create as creator
        from tools.go_capsule_build import build as builder
    elif language == "typescript":
        from tools.typescript_guest.project import create as creator
        from tools.typescript_guest.build import build as builder
        typescript_tools = Path(typescript_tools).resolve(strict=True)
    elif language == "dotnet":
        from tools.dotnet_guest.project import create as creator
        from tools.dotnet_guest.build import build as builder
        if dotnet_tools is None:
            raise ValueError("explicit pinned .NET compiler installation required")
        dotnet_tools = Path(dotnet_tools).resolve(strict=True)
    output = output.absolute()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("qualification projects must be outside the runtime checkout")
    output = fresh(output)
    result = {"schemaVersion": f"latent.{language}-capsule.qualification.v1", "status": "in-progress",
              "releasePublication": "not-performed", "newcomerReview345": "pending-human-review"}
    stage = "source"
    try:
        before = inputs(language)
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
        cargo_options = ["--config", ROOT / ".cargo/managed-guest.toml"] if language in {"go", "typescript", "dotnet"} else []
        if language == "typescript":
            environment["LSF_TYPESCRIPT_TOOLS"] = str(typescript_tools)
        if language == "dotnet":
            environment["LSF_DOTNET_TOOLS"] = str(dotnet_tools)
        commands = Commands(ROOT, output, environment, **(
            {"deadline_seconds": 3600, "command_seconds": 1800} if language in {"go", "typescript", "dotnet"} else {}))
        result["commandLimits"] = {"overallSeconds": 3600 if language in {"go", "typescript", "dotnet"} else 900,
                                   "perCommandSeconds": commands.command_seconds}
        result["tools"] = materials
        stage = "host-build"
        commands.run(stage, paths["cargo"], *cargo_options, "build", "--locked", "-p", "latent", "-p", "latentd", "--bins",
            "-p", "latent-packaging", "--example", "package", "--example", "capsule_contracts",
            "-p", "latent-policy", "--example", "capsule_authoring")
        if inputs(language) != before:
            raise ValueError("host sources changed during compilation")
        binaries = {name: target / "debug" / name for name in ("latent", "latentd", "examples/package", "examples/capsule_contracts", "examples/capsule_authoring")}
        result["binaries"] = {name: file_identity(path) for name, path in binaries.items()}
        stage = "standalone-builds"
        built = []
        result["builds"] = {}
        (output / "projects").mkdir(mode=0o700)
        (output / "builds").mkdir(mode=0o700)
        for template in TEMPLATES:
            project = creator(output / "projects" / template, template)
            artifact = builder(project, output / "builds" / template, binaries["examples/capsule_contracts"],
                binaries["examples/package"], "https://github.com/KirilsTurkins/latent-service-fabric",
                **({"offline": offline} if language == "rust" else
                   {"tools": typescript_tools} if language == "typescript" else
                   {"tools": dotnet_tools} if language == "dotnet" else {}))
            built.append(artifact)
            result["builds"][template] = read_json(artifact / "BUILD-COMPLETE.json")
        stage = "ownership"
        if language == "rust":
            result["ownership"] = ownership(output / "ownership", offline=offline)
        elif language == "c":
            commands.run("c-scope-compile", "zig", "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", ROOT / "sdk/c-guest/include", ROOT / "sdk/c-guest/tests/ownership.c", "-o", output / "c-ownership")
            commands.run("c-scope-runtime", output / "c-ownership")
        elif language == "go":
            commands.run("go-owner-tests", "go", "test", ROOT / "sdk/go-guest/ownership/owner.go",
                         ROOT / "sdk/go-guest/ownership/owner_test.go")
        elif language == "dotnet":
            from tools.check_dotnet_capsule_ownership import check
            result["ownership"] = check(output / "ownership", environment)
        else:
            node = shutil.which("node", path=environment["PATH"])
            if node is None:
                raise ValueError("pinned Node compiler required")
            owners = output / "typescript-owners"
            commands.run("typescript-owner-compile", node, typescript_tools / "node_modules/typescript/bin/tsc",
                "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--strict",
                "--lib", "ES2022", "--outDir", owners, ROOT / "sdk/typescript-guest/capabilities/owner.ts",
                ROOT / "sdk/typescript-guest/capabilities/result.ts")
            write_json(owners / "package.json", {"type": "module"})
            commands.environment["LSF_TYPESCRIPT_OWNERS"] = str(owners)
            commands.run("typescript-owner-tests", node, "--test", ROOT / "sdk/typescript-guest/tests/owner.test.mjs",
                         ROOT / "sdk/typescript-guest/tests/signed64.test.mjs")
        stage = "sdk-runtime-ownership"
        # Rust/C qualifications preserve their combined runtime gate. Go runs
        # the same ten provider/ownership cases with actual Go components.
        sdk_builder = f"build_{language}_guest_capsules.py" if language in {"go", "typescript", "dotnet"} else "build_guest_capsules.py"
        commands.run("build-sdk-guests", sys.executable, ROOT / "tools" / sdk_builder, "--output", output / "sdk-guests",
                     *(["--tools", typescript_tools] if language == "typescript" else
                       ["--tools", dotnet_tools] if language == "dotnet" else []))
        commands.environment["LSF_GUEST_CAPSULES"] = str(output / "sdk-guests")
        if language in {"go", "typescript", "dotnet"}:
            commands.environment["LSF_GUEST_SDK_LANGUAGE"] = language
        if language == "typescript":
            commands.run("typescript-real-sdk-error-boundary", paths["cargo"], *cargo_options,
                "run", "--locked", "-p", "latent-wasmtime", "--example", "typescript_runtime_probe", "--",
                output / "sdk-guests/typescript-random/component.wasm", "speed", "sdk-random")
            commands.run("typescript-sdk-resources", paths["cargo"], *cargo_options, "run", "--locked", "-p", "latent-wasmtime",
                "--example", "typescript_runtime_probe", "--", output / "sdk-guests/typescript-blob/component.wasm",
                "speed", "sdk-blob")
        if language == "dotnet":
            commands.run("dotnet-real-sdk-secret-cleanup", paths["cargo"], *cargo_options,
                "run", "--locked", "-p", "latent-wasmtime", "--example", "typescript_runtime_probe", "--",
                output / "sdk-guests/dotnet-secrets/component.wasm", "speed", "sdk-dotnet-secrets")
        commands.run("sdk-runtime-tests", paths["cargo"], *cargo_options, "test", "--locked", "-p", "latent-wasmtime", "--test", "guest_sdk",
                     "--", "--ignored", "--test-threads=1", "--show-output")
        stage = "sign-demo"
        commands.run(stage, binaries["examples/capsule_authoring"], "demo-sign", output / "releases", *built)
        stage = "enforced-node"
        result["node"] = node_workflow(binaries["latent"], binaries["latentd"], output / "releases", output / "node", language=language)
        stage = "printed-guide"
        result["guide"] = guide(output / "guide", environment, language)
        if inputs(language) != before or {name: file_identity(path) for name, path in binaries.items()} != result["binaries"]:
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
