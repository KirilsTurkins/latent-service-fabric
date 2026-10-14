#!/usr/bin/env python3
"""Build, sign and execute the ordinary Java server lifecycle qualification."""
from __future__ import annotations

import argparse
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
from tools.dev_workflow.common import require
from tools.java_capsule_build import build
from tools.java_server_lifecycle_project import create_fixtures
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_java_server_lifecycle import main as qualify, ordinary_tuple
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

PRODUCTS = {"latent": ("latent", "bin"), "latentd": ("latentd", "bin"),
            "package": ("package", "example"), "capsule_contracts": ("capsule_contracts", "example"),
            "capsule_authoring": ("capsule_authoring", "example")}


def native(commands, output, pins):
    before = source_identity(ROOT)
    head = commands.run("source-head", "git", "rev-parse", "HEAD").decode().strip()
    tree = commands.run("source-tree", "git", "rev-parse", "HEAD^{tree}").decode().strip()
    require(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (head, tree)), "server-lifecycle-source-ref")
    commands.run("source-clean", "git", "diff", "--exit-code", "HEAD", "--")
    paths, _materials = resolve_tools(pins, ROOT, commands.environment)
    commands.environment["RUSTC"] = str(paths["rustc"])
    data = commands.run("default-native-build", paths["cargo"], "build", "--locked", "-p", "latent", "-p", "latentd", "--bins",
        "-p", "latent-packaging", "--example", "package", "--example", "capsule_contracts",
        "-p", "latent-policy", "--example", "capsule_authoring", "--message-format=json")
    rows = [json.loads(line) for line in data.splitlines()]
    completed = [row for row in rows if row.get("reason") == "build-finished"]
    require(len(completed) == 1 and completed[0].get("success") is True, "server-lifecycle-native-build-incomplete")
    frozen = fresh(output / "native")
    products = {}
    for name, (target, kind) in PRODUCTS.items():
        selected = [row for row in rows if row.get("reason") == "compiler-artifact"
            and row["target"]["name"] == target and kind in row["target"]["kind"] and row.get("executable")]
        require(len(selected) == 1 and not set(selected[0]["features"]) & {
            "development-test-node", "development-outbound-streams"}, "server-lifecycle-native-default-product")
        artifact = selected[0]
        original = Path(artifact["executable"])
        expected = file_identity(original, 512 * 1024 * 1024)
        owned = frozen / name
        shutil.copyfile(original, owned)
        owned.chmod(0o700)
        require(file_identity(owned, 512 * 1024 * 1024) == expected
                and file_identity(original, 512 * 1024 * 1024) == expected, "server-lifecycle-native-capture-changed")
        products[name] = {**expected, "actualFeatures": artifact["features"]}
    require(source_identity(ROOT) == before, "server-lifecycle-native-source-changed")
    commands.run("source-still-clean", "git", "diff", "--exit-code", "HEAD", "--")
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text())
    versions = [row["version"] for row in lock["package"] if row["name"] == "wasmtime"]
    require(versions == ["48.0.6"], "server-lifecycle-current-wasmtime-required")
    receipt = frozen / "native-tuple.json"
    write_json(receipt, {"status": "passed", "scope": "completed-default-native-products-only",
        "tupleRole": "ordinary-defaults", "features": [], "hostAbiProfile": "lsf-host-abi-phase3-v5",
        "wasmtimeVersion": versions[0], "head": head, "tree": tree, "sourceIdentity": before, "binaries": products})
    return frozen, receipt


def signed_views(commands, output, artifacts):
    signed = output / "joint-signed"
    commands.run("sign-isolated-fixtures", output / "selected-native/capsule_authoring", "demo-sign", signed, *artifacts)
    releases = read_json(signed / "release-set.json")
    require(len(releases["releases"]) == 3, "server-lifecycle-three-exact-signed-inputs")
    views = {}
    for label, selected in zip(("baseline", "first", "second"), releases["releases"], strict=True):
        require(selected["componentDigest"] == file_identity(output / ("build-" + label) / "component.wasm")["sha256"],
                "server-lifecycle-exact-signed-build-association")
        view = fresh(output / ("signed-" + label))
        for path in signed.iterdir():
            if path.is_file() and path.name != "release-set.json":
                shutil.copyfile(path, view / path.name)
        shutil.copytree(signed / selected["name"], view / selected["name"])
        write_json(view / "release-set.json", {**releases, "releases": [selected]})
        views[label] = view
    return views


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wasi-sdk", type=Path, required=True)
    parser.add_argument("--gradle", default="gradle")
    parser.add_argument("--read-only-cache", type=Path)
    parser.add_argument("--peer-port", type=int, default=32195)
    parser.add_argument("--native-directory", type=Path)
    parser.add_argument("--native-tuple", type=Path)
    args = parser.parse_args(argv)
    require(type(args.peer_port) is int and 1 <= args.peer_port <= 65535, "server-lifecycle-explicit-peer-port")
    require((args.native_directory is None) == (args.native_tuple is None), "server-lifecycle-complete-native-inputs")
    require(args.output.absolute() != ROOT and ROOT not in args.output.absolute().parents,
            "server-lifecycle-projects-must-be-outside-runtime")
    output = fresh(args.output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=900)
    commands.environment.update(CARGO_TARGET_DIR=os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target")),
        CARGO_PROFILE_DEV_DEBUG="0", CARGO_PROFILE_TEST_DEBUG="0", CARGO_INCREMENTAL="0")
    if "JAVA_HOME" in os.environ:
        commands.environment["JAVA_HOME"] = os.environ["JAVA_HOME"]
    stage = "native"
    try:
        pins = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        directory, receipt = ((args.native_directory, args.native_tuple) if args.native_directory is not None
                              else native(commands, output, pins))
        binaries = {name: directory / name for name in PRODUCTS}
        observed = ordinary_tuple(receipt, binaries)
        # Freeze supplied products too: other qualifications can rebuild the shared target.
        selected = fresh(output / "selected-native")
        for name, binary in binaries.items():
            shutil.copyfile(binary, selected / name)
            (selected / name).chmod(0o700)
        require(ordinary_tuple(receipt, {name: selected / name for name in PRODUCTS}) == observed,
                "server-lifecycle-selected-native-changed")
        projects = create_fixtures(output / "projects", args.peer_port)
        artifacts = []
        for label, project in projects.items():
            stage = "build-" + label
            artifact = build(project, output / ("build-" + label), selected / "capsule_contracts", selected / "package",
                "https://github.com/KirilsTurkins/latent-service-fabric", args.wasi_sdk,
                gradle=args.gradle, timeout=min(900, commands.deadline - time.monotonic()),
                read_only_cache=args.read_only_cache)
            artifacts.append(artifact)
        stage = "sign"
        views = signed_views(commands, output, artifacts)
        stage = "real-shared-ingress"
        qualify(["--binary", str(selected / "latent"), "--node", str(selected / "latentd"),
            "--tls-tool", str(selected / "capsule_authoring"), "--native-tuple", str(receipt),
            "--baseline-source", str(projects["baseline"]), "--baseline-fixture", str(views["baseline"]),
            "--baseline-build", str(output / "build-baseline"), "--first-fixture", str(views["first"]),
            "--first-build", str(output / "build-first"), "--second-fixture", str(views["second"]),
            "--second-build", str(output / "build-second"), "--peer-port", str(args.peer_port),
            "--output", str(output / "execution")])
        require(ordinary_tuple(receipt, {name: selected / name for name in PRODUCTS}) == observed,
                "server-lifecycle-native-product-changed")
        require(time.monotonic() < commands.deadline, "server-lifecycle-suite-deadline")
        write_json(output / "suite.json", {"status": "passed", "scope": "isolated-signed-java-source-fixtures",
            "nativeTuple": observed, "qualification": file_identity(output / "execution/lifecycle-qualified.json"),
            "commands": commands.records})
    except BaseException as error:
        write_json(output / "FAILED.json", {"status": "failed", "stage": stage, "commands": commands.records,
            "reason": str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
