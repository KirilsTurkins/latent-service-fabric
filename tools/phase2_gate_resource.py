#!/usr/bin/env python3
"""Run or validate phase2-dormant-32-r1; no build, install, registry or retries."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_gate_resource_os import checkpoint, fixture_inventory, hash_file
from tools.phase2_gate_resource_profile import (
    PROFILE, canonical, digest, sha, validate_receipt,
)
from tools.phase2_gate_resource_run import BoundedClient, run
from tools.phase2_operator_process import WorkflowError, read_json, require, write_json

SOURCE_FILES = (
    "tools/phase2_gate_resource.py", "tools/phase2_gate_resource_run.py",
    "tools/phase2_gate_resource_profile.py", "tools/phase2_gate_resource_os.py",
    "tools/phase2_operator_process.py", "tools/phase2_operator_scenario.py",
    "tools/phase2_operator_canary.py", "tools/build_process_linux.py",
    "tools/build_process_signals.py", "docs/testing/phase-2-resource-profile.md",
    "crates/latent-policy/src/supply_chain/tests/operator_fixture.rs",
    "crates/latent-policy/src/supply_chain/tests/operator_fixture/resources.rs",
)


def build_identity(path, cli, node, source, deadline, cancellation):
    value = read_json(path, 16384)
    require(set(value) == {"schemaVersion", "sourceRevision", "cargoLockSha256",
                          "rustcVersion", "buildProfile", "cliSha256", "nodeSha256"},
            "build-identity-shape")
    require(value["schemaVersion"] == "latent.phase2.resource-build.v1"
            and re.fullmatch(r"[0-9a-f]{40}", value["sourceRevision"]),
            "build-source-identity")
    require(isinstance(value["rustcVersion"], str)
            and re.fullmatch(r"rustc [A-Za-z0-9 .()+_-]{1,120}", value["rustcVersion"])
            and value["buildProfile"] in ("debug", "release"), "build-tool-identity")
    for field, file in (("cliSha256", cli), ("nodeSha256", node),
                        ("cargoLockSha256", source / "Cargo.lock")):
        require(sha(value[field]) == hash_file(file, PROFILE["maximumBinaryBytes"],
                                             deadline=deadline, cancellation=cancellation),
                "build-bytes-mismatch")
    return value


def metadata(fixture):
    value = read_json(fixture / "fixture.json", 32768)
    require(value["formatVersion"] == 1 and value["profile"] == PROFILE["id"]
            and value["syntheticTestEvidence"] is True and value["tenant"] == "tests"
            and value["service"] == "tests/packaging", "resource-fixture-profile")
    require(int(value["proofAgeExpiresAtUnixSeconds"]) > time.time() + PROFILE["deadlineSeconds"]
            and int(value["expiresAtUnixSeconds"]) > time.time() + PROFILE["deadlineSeconds"],
            "resource-fixture-expiring")
    packages = value["packages"]
    require(len(packages) == 32 and [item["name"] for item in packages] ==
            [f"capsule-{i:02}" for i in range(32)], "resource-fixture-count")
    for field in ("packageDigest", "manifestDigest", "componentDigest"):
        require(len({sha(item[field]) for item in packages}) == 32, "resource-fixture-identities")
    return value


def execute(args):
    # Covers identity reads, first fixture mutation, every child lifetime, and
    # final receipt publication. Nested shared helpers reuse this exact owner.
    with owned_cancellation() as cancellation:
        execute_owned(args, cancellation)


def execute_owned(args, cancellation):
    require(sys.platform == "linux" and sys.version_info >= (3, 13), "linux-python313-required")
    for path in (args.cli, args.node, args.fixture_root, args.build_identity, args.output):
        require(path is not None and path.is_absolute(), "absolute-input-required")
    require(not args.output.exists() and not args.output.is_symlink()
            and args.output.parent.is_dir() and not args.output.parent.is_symlink(),
            "receipt-output-exists")
    require(args.fixture_root.is_dir() and not args.fixture_root.is_symlink(), "fixture-directory")
    source = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    deadline = started + PROFILE["deadlineSeconds"]
    result = {
        "schemaVersion": "latent.phase2.resource-receipt.v1", "profile": PROFILE,
        "profileDigest": digest(PROFILE), "passed": False, "syntheticTestEvidence": True,
        "samples": [], "invocations": [], "controls": 0, "invokeAttempts": 0,
        "temporaryOutputsRemoved": False,
    }
    stage = "identities"
    failure = None
    try:
        result["build"] = build_identity(args.build_identity, args.cli, args.node, source,
                                         deadline, cancellation)
        result["collectorSources"] = [
            {"path": name, "digest": hash_file(source / name, 1024 * 1024,
                                               deadline=deadline, cancellation=cancellation)}
            for name in SOURCE_FILES
        ]
        result["host"] = {
            "system": platform.system(), "machine": platform.machine(),
            "kernelRelease": platform.release(), "pythonVersion": platform.python_version(),
            "pageSize": str(os.sysconf("SC_PAGE_SIZE")), "clockTicks": str(os.sysconf("SC_CLK_TCK")),
        }
        require(all(len(value) <= 128 for value in result["host"].values()), "host-identity-bound")
        fixture = metadata(args.fixture_root)
        original = fixture_inventory(args.fixture_root, deadline, cancellation)
        result["fixtureInventoryDigest"] = digest(original)
        result["fixtureFiles"] = len(original)
        result["fixtureBytes"] = str(sum(row["bytes"] for row in original))
        result["packages"] = fixture["packages"]
        result["fixtureMetadataDigest"] = hash_file(args.fixture_root / "fixture.json", 32768,
                                                   deadline=deadline, cancellation=cancellation)
        result["policyFileDigest"] = hash_file(args.fixture_root / "policy.json", 262144,
                                              deadline=deadline, cancellation=cancellation)
        result["verifiedAtUnixSeconds"] = fixture["verifiedAtUnixSeconds"]
        result["proofAgeExpiresAtUnixSeconds"] = fixture["proofAgeExpiresAtUnixSeconds"]
        checkpoint(deadline, cancellation)
        stage = "owned-node"
        with owned_cancellation() as cancellation:
            with tempfile.TemporaryDirectory(prefix="lsf-phase2-resource-") as temporary:
                work = Path(temporary)
                client_dir, node_dir = work / "client", work / "node"
                client_dir.mkdir(mode=0o700)
                node_dir.mkdir(mode=0o700)
                client = BoundedClient(args.cli, client_dir, cancellation,
                                       started + PROFILE["deadlineSeconds"])
                try:
                    run(client, args.node, node_dir, args.fixture_root, fixture, result)
                finally:
                    result["controls"] = client.controls
                    result["invokeAttempts"] = client.invocations
            result["temporaryOutputsRemoved"] = True
            cancellation.check()
        stage = "receipt-validation"
        require(fixture_inventory(args.fixture_root, deadline + PROFILE["shutdownSeconds"], cancellation)
                == original, "resource-fixture-changed")
        result["elapsedMillis"] = str(int((time.monotonic() - started) * 1000))
        result["passed"] = True
        validate_receipt(result)
        # Validation is still owned work. Observe cancellation and the existing
        # final deadline before publishing a passing receipt; file publication
        # itself is not atomic with host signal delivery.
        result["elapsedMillis"] = str(int((time.monotonic() - started) * 1000))
        checkpoint(deadline + PROFILE["shutdownSeconds"], cancellation)
    except BaseException as error:
        result["passed"] = False
        # Only fixed stage tokens from our own harness are retained. Never
        # retain stdout/stderr, credentials, paths or arbitrary exception text.
        reason = str(error) if isinstance(error, WorkflowError) else "resource-unavailable"
        require(len(reason) <= 256 and re.fullmatch(r"[A-Za-z0-9_.:-]+", reason),
                "resource-diagnostic-bound")
        failure = stage + ":" + reason
        result["failure"] = failure
        result["elapsedMillis"] = str(int((time.monotonic() - started) * 1000))
    require(len(canonical(result)) <= PROFILE["maximumReceiptBytes"], "receipt-bound")
    write_json(args.output, result)
    print(json.dumps({"schemaVersion": result["schemaVersion"], "profile": PROFILE["id"],
                      "passed": result["passed"], "receiptDigest": digest(result),
                      "samples": len(result["samples"]), "invokeAttempts": result["invokeAttempts"],
                      "controls": result["controls"]}, separators=(",", ":")))
    if failure:
        raise WorkflowError(failure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--build-identity", type=Path)
    parser.add_argument("--output", type=Path, help="New compact receipt file; never overwritten")
    parser.add_argument("--validate", type=Path, help="Validate an existing passing receipt without spawning")
    args = parser.parse_args()
    if args.validate:
        require(all(value is None for value in (
            args.cli, args.node, args.fixture_root, args.build_identity, args.output)),
            "validation-arguments")
        validate_receipt(read_json(args.validate, PROFILE["maximumReceiptBytes"]))
        print('{"valid":true,"profile":"phase2-dormant-32-r1"}')
    else:
        execute(args)


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, WorkflowError) else "resource-unavailable"
        print("Phase 2 resource profile failed: " + reason, file=sys.stderr)
        sys.exit(1)
