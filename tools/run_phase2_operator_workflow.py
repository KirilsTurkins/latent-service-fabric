#!/usr/bin/env python3
"""Run real Phase 2 CLI/registry/node workflows using already-built binaries.

Linux/Python 3.13 only. Supply the fresh, key-free output of the explicit policy
test export_operator_workflow_fixture, and an owned Zot TLS fixture created by
tools/run_oci_registry_tests.py (or the matching host orchestration helper).
This script never builds Rust, pulls an image, modifies the input fixture, or
claims that its synthetic signed observation is actual build provenance.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import (
    Client, WorkflowError, bounded_receipt, file_digest, read_json, require, write_json,
)
from tools.phase2_operator_scenario import node_workflow
from tools.run_oci_registry_tests import USERNAME, PASSWORD, Registry, certificates, ready


COLLECTOR_FILES = (
    "tools/run_phase2_operator_workflow.py", "tools/phase2_operator_scenario.py",
    "tools/phase2_operator_process.py", "tools/phase2_operator_canary.py",
    "tools/build_process.py", "tools/build_process_linux.py",
    "tools/build_process_signals.py", "tools/run_oci_registry_tests.py",
)


def build_identity(args, cancellation, deadline):
    root = Path(__file__).resolve().parents[1]
    paths = {
        "cliDigest": (args.cli, 1024 * 1024 * 1024),
        "nodeDigest": (args.node, 1024 * 1024 * 1024),
        "cargoLockDigest": (root / "Cargo.lock", 1024 * 1024),
        "workspaceManifestDigest": (root / "Cargo.toml", 262144),
        "rustToolchainDigest": (root / "rust-toolchain.toml", 262144),
    }
    result = {name: file_digest(path, maximum, cancellation, deadline)
              for name, (path, maximum) in paths.items()}
    if args.source_commit is not None:
        # Supplied by the build owner (GITHUB_SHA in CI), not inferred from a
        # binary's filename. Exact bytes are independently measured below.
        result.update(sourceCommit=args.source_commit, sourceCommitKind="supplied-build-identity")
    return result


def collector_identity(cancellation, deadline):
    root = Path(__file__).resolve().parents[1]
    return {name: file_digest(root / name, 262144, cancellation, deadline)
            for name in COLLECTOR_FILES}


def inventory(directory):
    """Bounded exact-byte comparison; reject links and unexpected large fixtures."""
    entries = {}
    total = 0
    pending = [directory]
    seen = 0
    while pending:
        parent = pending.pop()
        require(not parent.is_symlink(), "fixture-link")
        for path in parent.iterdir():
            seen += 1
            require(seen <= 512 and not path.is_symlink(), "fixture-inventory")
            if path.is_dir():
                pending.append(path)
            else:
                require(path.is_file(), "fixture-file")
                size = path.stat().st_size
                total += size
                require(total <= 4 * 1024 * 1024, "fixture-size")
                with path.open("rb") as source:
                    data = source.read(size + 1)
                require(len(data) == size, "fixture-changed")
                entries[path.relative_to(directory).as_posix()] = hashlib.sha256(data).hexdigest()
    return entries


def registry_profile(directory, origin, ca):
    parsed = urlsplit(origin)
    require(parsed.scheme == "https" and parsed.hostname == "127.0.0.1"
            and parsed.username is None and parsed.password is None
            and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
            and parsed.port is not None, "registry-origin")
    require(ca.is_file() and not ca.is_symlink(), "registry-ca")
    with ca.open("rb") as source:
        certificate = source.read(65537)
    require(0 < len(certificate) <= 65536, "registry-ca-size")
    (directory / "ca.der").write_bytes(certificate)
    write_json(directory / "credential.json", {"mode": "basic", "username": USERNAME,
                                               "password": PASSWORD})
    profile = directory / "registry.json"
    write_json(profile, {"formatVersion": 1, "origin": origin.rstrip("/"),
                         "repository": "lsf/operator-workflow",
                         "addresses": [f"127.0.0.1:{parsed.port}"],
                         "credentialFile": "credential.json", "rootCertificates": ["ca.der"]})
    return profile


@contextmanager
def registry_fixture(args, work, cancellation):
    require((args.registry_origin is None) == (args.registry_ca is None), "registry-arguments-paired")
    if args.registry_origin is not None:
        yield args.registry_origin, args.registry_ca
        return
    directory = work / "registry"
    directory.mkdir()
    registry = Registry(directory)
    try:
        certificates(directory)
        cancellation.check()
        origin = registry.launch()
        ready(origin, directory / "ca.pem")
        cancellation.check()
        yield origin, directory / "ca.der"
    finally:
        # The maintained owner verifies its UUID label and immutable container
        # ID. Never remove an image, shared builder, or another run's container.
        with cancellation.defer():
            registry.close()


def package_workflow(client, fixture, output, profile, tenant):
    summaries = {}
    for name in ("blue", "green"):
        source = fixture / name
        built = output / (name + "-built")
        original = inventory(source / "package")
        result = client.call("package", "build", "--source", source / "package-source.json",
                             "--input-root", source / "inputs", "--sbom-inputs", source / "sbom-inputs.json",
                             "--output-dir", built)["data"]
        require(inventory(built) == original, "rebuild-exact-bytes")
        inspected = client.call("package", "inspect", built)["data"]
        require(inspected == result, "inspect-rebuild-identity")
        require(inspected["trustEvaluated"] is False and inspected["executionAuthorized"] is False,
                "inspect-authority")
        client.call("package", "push", built, "--registry-profile", profile, "--reference", name,
                    "--evidence-index", source / "evidence/index.json",
                    "--evidence-root", source / "evidence")
        pulled = output / (name + "-pulled")
        evidence = output / (name + "-evidence")
        client.call("package", "pull", "--registry-profile", profile, "--reference", name,
                    "--output-dir", pulled, "--evidence-output", evidence)
        require(inventory(pulled) == original, "registry-exact-package")
        require(inventory(evidence) == inventory(source / "evidence"), "registry-exact-evidence")
        client.call("--tenant", tenant, "package", "verify", pulled,
                    "--evidence-index", evidence / "index.json", "--evidence-root", evidence,
                    "--policy", fixture / "policy.json")
        summaries[name] = inspected
    require(summaries["blue"]["componentDigest"] != summaries["green"]["componentDigest"],
            "distinct-compatible-fixture")
    # A wrong registry credential is tested by a separate actual CLI process.
    wrong = read_json(profile)
    write_json(profile.parent / "denied-credential.json", {"mode": "basic", "username": USERNAME,
                                                          "password": "PUBLIC-TEST-WRONG"})
    wrong["credentialFile"] = "denied-credential.json"
    denied_profile = profile.parent / "denied-registry.json"
    write_json(denied_profile, wrong)
    denied = output / "denied-package"
    client.call("package", "pull", "--registry-profile", denied_profile, "--reference", "blue",
                "--output-dir", denied, "--evidence-output", output / "denied-evidence", codes=(2,))
    require(not denied.exists(), "registry-auth-published-output")
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--registry-origin", help="Optional externally owned loopback TLS fixture; pair with --registry-ca")
    parser.add_argument("--registry-ca", type=Path, help="External fixture CA in DER format")
    parser.add_argument("--source-commit", help="Optional exact source commit supplied by the binary build owner")
    args = parser.parse_args()
    require(args.source_commit is None or re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "source-commit")
    require(sys.platform == "linux" and sys.version_info >= (3, 13), "linux-python313-required")
    for path in (args.cli, args.node):
        require(path.is_absolute() and path.is_file() and not path.is_symlink(), "binary-required")
    fixture = args.fixture_root.resolve(strict=True)
    metadata = read_json(fixture / "fixture.json", 16384)
    require(metadata.get("formatVersion") == 1 and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", metadata["tenant"]),
            "fixture-metadata")
    require(int(metadata["expiresAtUnixSeconds"]) > time.time() + 300, "fixture-expiring")
    stage = "acquire"
    try:
        with owned_cancellation() as cancellation:
            deadline = time.monotonic() + 300
            build = build_identity(args, cancellation, deadline)
            collectors = collector_identity(cancellation, deadline)
            policy_digest = file_digest(fixture / "policy.json", 262144, cancellation, deadline)
            metadata_digest = file_digest(fixture / "fixture.json", 16384, cancellation, deadline)
            with tempfile.TemporaryDirectory(prefix="lsf-operator-workflow-") as temporary:
                work = Path(temporary)
                client_dir, node_dir = work / "client", work / "node"
                client_dir.mkdir(mode=0o700)
                node_dir.mkdir(mode=0o700)
                outputs = client_dir / "outputs"
                outputs.mkdir()
                client = Client(args.cli, client_dir, cancellation, deadline)
                stage = "registry-fixture"
                with registry_fixture(args, work, cancellation) as (origin, ca):
                    profile = registry_profile(client_dir, origin, ca)
                    stage = "package-transfer"
                    summaries = package_workflow(client, fixture, outputs, profile, metadata["tenant"])
                    stage = "node-management"
                    node_summary = node_workflow(client, args.node, node_dir, fixture, outputs, summaries, metadata)
                result = {"schemaVersion": "latent.operator.workflow-test.v1", "passed": True,
                          "cliProcesses": client.calls, "packages": 2,
                          "syntheticTestEvidence": True, "temporaryOutputsRemoved": True,
                          "build": build, "collectorDigests": collectors,
                          "policyFileDigest": policy_digest, "fixtureMetadataDigest": metadata_digest,
                          "packageIdentities": summaries,
                          "registryOwnership": "external" if args.registry_origin else "runner-owned"}
                result.update(node_summary)
                require(build_identity(args, cancellation, deadline) == build
                        and collector_identity(cancellation, deadline) == collectors
                        and file_digest(fixture / "policy.json", 262144, cancellation, deadline) == policy_digest
                        and file_digest(fixture / "fixture.json", 16384, cancellation, deadline) == metadata_digest,
                        "workflow-identity-changed")
            cancellation.check()
        print(bounded_receipt(result))
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        # Never include argv, server output, tokens or source exception text.
        reason = str(error) if isinstance(error, WorkflowError) else "fixture-or-process-error"
        raise WorkflowError(stage + ":" + reason) from None


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        # WorkflowError is constructed only from fixed stage names and numeric
        # process statuses. Never print a source exception or command output.
        reason = str(error) if isinstance(error, WorkflowError) else "fixture-or-process-error"
        print("Operator workflow failed: " + reason, file=sys.stderr)
        sys.exit(1)
