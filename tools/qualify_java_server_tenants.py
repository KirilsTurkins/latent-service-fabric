#!/usr/bin/env python3
"""Build one neutral ordinary Java server and execute both tenant scopes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.dev_workflow.common import require
from tools.java_capsule_build import build
from tools.java_capsule_project import validate
from tools.java_server_node import run
from tools.java_server_tenant_project import create
from tools.java_server_tenants import TenantControls
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_json, snapshot, write_json

PRODUCTS = ("latent", "latentd", "package", "capsule_contracts", "capsule_authoring")


def select_initial_tenant(path: Path):
    deployment = read_json(path)
    require(deployment["metadata"].get("tenant") is None, "tenant-isolation-neutral-deployment")
    deployment["metadata"]["tenant"] = "examples"
    # The signer already created this operator manifest. Replace only this
    # selected deployment; the signed package and its evidence are unchanged.
    path.write_bytes(json.dumps(deployment, indent=2).encode("utf-8") + b"\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "wasi-sdk", "native-directory", "native-tuple", "read-only-cache"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--gradle", default="gradle")
    args = parser.parse_args(argv)
    require(args.output.absolute() != ROOT and ROOT not in args.output.absolute().parents,
            "tenant-isolation-outside-project-required")
    binaries = {name: args.native_directory / name for name in PRODUCTS}
    native = ordinary_tuple(args.native_tuple, binaries)
    inputs = {"native": native, "source": source_identity(ROOT), "workflow": file_identity(Path(__file__)),
              "fixture": file_identity(ROOT / "tools/java_server_tenant_project.py"),
              "programme": file_identity(ROOT / "tools/java_server_tenants.py")}
    output = fresh(args.output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=900, command_seconds=900)
    stage = "source"
    result = {"status": "in-progress", "inputs": inputs}
    try:
        project = create(output / "source")
        declaration, _lock, _pins = validate(snapshot(project))
        require(declaration["tenant"] is None and "/" not in declaration["service"]
                and declaration["limits"]["memoryBytes"] == 67108864
                and declaration["limits"]["cpuFuel"] == 1000000000
                and declaration["limits"]["wallTimeLimitMillis"] == 120000
                and declaration["limits"]["outboundRequests"] == 0,
                "tenant-isolation-original-zero-egress-limits")
        stage = "ordinary-compile"
        artifact = build(project, output / "build", binaries["capsule_contracts"], binaries["package"],
            "https://github.com/KirilsTurkins/latent-service-fabric", args.wasi_sdk, gradle=args.gradle,
            timeout=min(900, commands.deadline - time.monotonic()), read_only_cache=args.read_only_cache)
        stage = "sign-exact-neutral-server"
        fixture = output / "signed"
        commands.run("sign-neutral-server", binaries["capsule_authoring"], "fixture-sign-shared-java-server", fixture, artifact)
        releases = read_json(fixture / "release-set.json")
        require(len(releases["releases"]) == 1 and releases["tenant"] is None
                and releases["tenants"] == ["examples", "foreign"], "tenant-isolation-signing-identity")
        record = releases["releases"][0]
        require(record["componentDigest"] == file_identity(output / "build/component.wasm")["sha256"],
                "tenant-isolation-exact-signed-component")
        # Deployment metadata is an operator input. The signed neutral package,
        # original build and build observation stay byte-identical for both.
        selected = fixture / record["name"] / "deployment.json"
        select_initial_tenant(selected)
        stage = "actual-two-tenant-shared-node"
        execution = run(binaries["latent"], binaries["latentd"], fixture, output / "build", output / "execution",
            helper=True, tls_tool=binaries["capsule_authoring"], lifecycle=TenantControls(fixture))
        require(execution["status"] == "passed" and execution["lifecycle"]["status"] == "passed"
                and len(execution["lifecycle"]["cases"]) == 9, "tenant-isolation-complete-programme")
        require(ordinary_tuple(args.native_tuple, binaries) == native and source_identity(ROOT) == inputs["source"],
                "tenant-isolation-native-or-source-changed")
        require(time.monotonic() < commands.deadline, "tenant-isolation-original-deadline")
        result.update(status="passed", execution=execution, commands=commands.records)
    except BaseException as error:
        result.update(status="failed", stage=stage, commands=commands.records,
            reason=str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        raise
    finally:
        write_json(output / "qualification.json", result)
    print(json.dumps({"status": "passed", "cases": 9, "receipt": str(output / "qualification.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
