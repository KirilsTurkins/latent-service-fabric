#!/usr/bin/env python3
"""Manual, bounded provider resource checkpoint; never a substitute for full #239 acceptance."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process import run_bounded
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, WorkflowError, read_json, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_management_scenario import TENANT, publish_and_deploy_guests
from tools.sdk_provider_scenario import publish_callee
from tools.phase3_resource_analysis import analyze
from tools.phase3_resource_fixture import validity
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.phase3_resource_node import ResourceClient, apply_dormant, configure, delete_deployments, pages, settled_samples
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import LIMITS, PROFILES, SCHEMA, canonical, digest, policy_capacity, validate_receipt
from tools.phase3_resource_storage import storage_snapshot
from tools.phase3_resource_workload import measured_work, mode

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "phase3_resource_campaign.py", "phase3_resource_analysis.py", "phase3_resource_identity.py",
    "phase3_resource_node.py", "phase3_resource_os.py", "phase3_resource_peer.py", "phase3_resource_fixture.py",
    "phase3_resource_profile.py", "phase3_resource_schedule.py", "phase3_resource_workload.py",
    "phase3_resource_web.py", "phase3_resource_render.py", "phase3_resource_storage.py",
    "run_phase3_resource_acceptance.py",
    "phase3_web_scenario.py", "phase3_web_qualification.py", "run_security_profile_workflow.py",
    "phase2_operator_process.py", "phase2_operator_scenario.py", "phase3_management_scenario.py",
    "sdk_provider_scenario.py", "sdk_provider_http_fixture.py", "build_process.py",
    "build_process_linux.py", "build_process_signals.py", "ci_rust_artifacts.py",
)


def write_receipt(path, value):
    encoded = canonical(value) + b"\n"
    require(len(encoded) <= LIMITS["maximumReceiptBytes"] and path.is_absolute()
            and path.parent.is_dir() and not path.parent.is_symlink(), "resource-receipt-destination")
    if path.with_suffix(path.suffix + ".sha256").exists():
        raise FileExistsError("resource-receipt-sidecar-exists")
    with path.open("xb") as output:
        output.write(encoded)
    path.chmod(0o444)
    with path.with_suffix(path.suffix + ".sha256").open("x", encoding="ascii") as output:
        output.write(file_identity(path)["sha256"] + "\n")


def build(args):
    require(re.fullmatch(r"[0-9a-f]{40}", args.revision or ""), "resource-build-revision")
    require(args.record_build.is_absolute() and not args.record_build.exists()
            and not args.record_build.with_suffix(args.record_build.suffix + ".sha256").exists(),
            "resource-build-output-fresh")
    source = source_identity(ROOT)
    cargo = shutil.which("cargo")
    rustc = shutil.which("rustc")
    require(cargo is not None and rustc is not None, "resource-build-tool-unavailable")
    command = [cargo, "build", "--locked", "-p", "latentd", "-p", "latent", "-j", "3"]
    started = time.time_ns()
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")) / "debug"
    require(target.is_absolute() and target.resolve().is_relative_to((ROOT / "target").resolve()),
            "resource-build-target-owner")
    record = {"schemaVersion": "latent.phase3.resource-build.v1", "status": "failed", "sourceRevision": args.revision,
              "revisionAssociation": "operator-asserted-with-explicit-input-digest",
              "sourceInputs": source, "cargoLock": file_identity(ROOT / "Cargo.lock"),
              "command": command,
              "profile": "dev", "environment": {key: os.environ.get(key) for key in
                  ("CARGO_TARGET_DIR", "CARGO_BUILD_JOBS", "CARGO_PROFILE_DEV_DEBUG", "RUSTFLAGS")},
              "startedUnixNanos": str(started)}
    try:
        outcome = run_bounded(command, ROOT, dict(os.environ), timeout_seconds=1200, max_output_bytes=1048576)
        record["buildOutput"] = {"stdout": outcome.stdout.decode("utf-8", "replace"),
                                  "stderr": outcome.stderr.decode("utf-8", "replace"), "exitCode": outcome.returncode}
        record["buildOutputDigest"] = digest(record["buildOutput"])
        require(outcome.returncode == 0, "resource-build-failed")
        compiler = run_bounded([rustc, "--version"], ROOT, dict(os.environ), timeout_seconds=10, max_output_bytes=4096)
        require(compiler.returncode == 0, "resource-build-compiler-identity")
        record["rustcVersion"] = compiler.stdout.decode("ascii").strip()
        require(source_identity(ROOT) == source, "resource-build-source-changed")
        record["binaries"] = {"node": file_identity(target / "latentd"), "cli": file_identity(target / "latent")}
        record["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        record["failure"] = (str(error) if isinstance(error, WorkflowError) else type(error).__name__)[:256]
    record["finishedUnixNanos"] = str(time.time_ns())
    write_receipt(args.record_build, record)
    print(json.dumps({"built": record["status"] == "passed", "failure": record.get("failure"),
                      "identity": file_identity(args.record_build)}))
    return record["status"] == "passed"


def identify(args, result):
    receipt = read_json(args.build_identity)
    result["build"] = receipt
    result["observedBinaries"] = {name: file_identity(path) for name, path in
                                  (("node", args.node), ("cli", args.cli))}
    require(file_identity(args.build_identity)["sha256"] == args.build_identity.with_suffix(
        args.build_identity.suffix + ".sha256").read_text(encoding="ascii").strip(), "resource-build-checksum")
    require(receipt["schemaVersion"] == "latent.phase3.resource-build.v1" and receipt["status"] == "passed",
            "resource-build-schema")
    require(receipt["sourceInputs"] == source_identity(ROOT), "resource-build-source-mismatch")
    require(receipt["cargoLock"] == file_identity(ROOT / "Cargo.lock"), "resource-build-lock-mismatch")
    require(receipt["binaries"] == result["observedBinaries"], "resource-build-binary-mismatch")
    result["collectorSources"] = [{"path": "tools/" + name, **file_identity(ROOT / "tools" / name)}
                                  for name in SOURCE_FILES]
    result["host"] = {"system": platform.system(), "machine": platform.machine(),
                      "kernel": platform.release(), "python": platform.python_version(),
                      "cpuQuota": Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
                      "memoryLimitBytes": Path("/sys/fs/cgroup/memory.max").read_text().strip(),
                      "hostConditions": args.host_condition, "dedicatedHardware": False,
                      "timingInterpretation": "host-specific-observation-with-shared-Docker-host-noise"}


def launch_peer(client, control):
    mode(control, "reply")
    process = Process([sys.executable, str(ROOT / "tools/phase3_resource_peer.py"), "--control", str(control)],
                      control, client.environment, client.cancellation, maximum=16384)
    try:
        startup = process.line(min(client.deadline, time.monotonic() + 10))
        require(set(startup) == {"port"} and type(startup["port"]) is int and 0 < startup["port"] < 65536,
                "resource-peer-startup")
        return process, startup["port"]
    except BaseException:
        process.close()
        raise


def peer_shutdown(peer):
    peer.stop()
    lines = bytes(peer.buffers[0]).splitlines()
    require(len(lines) == 1 and not peer.buffers[1], "resource-peer-shutdown")
    counts = json.loads(lines[0])
    require(counts["requests"] == counts["authorized"] > 0 and counts["unexpected"] == 0
            and counts["holds"] == counts["closedHolds"] > 0, "resource-peer-empty-or-unclean")
    require(peer.closed and peer.owner.finished and peer.owner.process.returncode == 0, "resource-peer-not-reaped")
    return {"counts": counts, "processId": peer.owner.process.pid, "reaped": True}


def node_run(args, result, cancellation, temporary, deadline):
    directories = {name: temporary / name for name in ("node", "client", "control")}
    for directory in directories.values():
        directory.mkdir(mode=0o700)
    client = ResourceClient(args.cli, directories["client"], cancellation, deadline)
    profile = result["profile"]
    peer, port = launch_peer(client, directories["control"])
    node = None
    try:
        config, settings = configure(directories["node"], args.fixture_root, port, profile)
        result["configuration"] = settings
        result["configurationDigest"] = digest(settings)
        result["policyCapacity"] = policy_capacity(profile)
        node = connect(client, args.node, directories["node"], config, TENANT, 1)
        probe = Probe(node, result["build"]["binaries"]["node"])
        result["nodeIdentity"] = probe.identity
        result["installedProviders"] = node.startup_record["providers"]
        result["samples"] += settled_samples(client, probe, "fixed", 0, profile["samplesPerPhase"], False)
        result["storage"] = [{"phase": "fixed", **storage_snapshot(directories["node"], deadline)}]
        targets = publish_and_deploy_guests(client, args.fixture_root, node, port)
        targets["callee"] = publish_callee(client, args.fixture_root)
        result["targets"] = targets
        releases = pages(client, "release", "releases")
        require(len(releases) == 3, "resource-component-catalog")
        fixtures = read_json(args.fixture_root / "fixture.json")["fixtures"]
        result["catalog"] = {"components": len({target["componentDigest"] for target in targets.values()}),
                             "packages": len({fixture["packageDigest"] for fixture in fixtures}),
                             "publications": len({target["publication"] for target in targets.values()}),
                             "scope": "fresh-owned-catalog-verified-admission-receipts-and-release-pages",
                             "releasePageDigest": digest(releases), "dormantPopulations": []}
        previous = 0
        for count in profile["dormantSteps"]:
            deployment = apply_dormant(client, count, previous)
            actual = deployment["applied"]
            result["catalog"]["dormantPopulations"].append({"deployments": len(deployment["rows"]),
                "dormantRequested": count, "dormantAdded": actual, "refusal": deployment["refusal"],
                "pageDigest": digest(deployment["rows"])})
            result["samples"] += settled_samples(client, probe, "dormant", actual, profile["samplesPerPhase"])
            previous = actual
            if deployment["refusal"] is not None:
                result["catalog"]["unattemptedDormantRequests"] = [requested for requested in profile["dormantSteps"]
                                                                   if requested > count]
                break
        result["storage"].append({"phase": "dormant", **storage_snapshot(directories["node"], deadline)})
        measured_work(client, targets, port, directories["control"], probe, profile, result)
        delete_deployments(client, previous)
        result["samples"] += settled_samples(client, probe, "unrouted", 0, profile["samplesPerPhase"], False)
        result["storage"].append({"phase": "unrouted", **storage_snapshot(directories["node"], deadline)})
        stop(client, node)
        result["shutdown"] = stopped_record(node)
        node = None
        result["peerShutdown"] = peer_shutdown(peer)
        result["controlCommands"] = client.calls
    finally:
        result["controlCommands"] = client.calls
        if hasattr(client, "last_failure"):
            result["lastControlFailure"] = client.last_failure
        try:
            if node is not None:
                result["nodeFailureStderr"] = bytes(node.buffers[1])[-8192:].decode("utf-8", "replace")
                node.close()
                result["nodeForcedCleanup"] = {"processId": node.owner.process.pid,
                    "closed": node.closed, "reaped": node.owner.finished,
                    "exitCode": node.owner.process.returncode, "gracefulShutdownObserved": False}
        finally:
            peer.close()
            result["peerOwnership"] = {"processId": peer.owner.process.pid, "closed": peer.closed,
                "reaped": peer.owner.finished, "exitCode": peer.owner.process.returncode}


def run(args):
    require(sys.platform == "linux", "resource-linux-required")
    require(args.output.is_absolute() and not args.output.exists(), "resource-output-fresh")
    profile = PROFILES[args.profile]
    started = time.monotonic()
    result = {"schemaVersion": SCHEMA, "status": "failed", "ticketAcceptance": "pending",
              "profile": profile, "profileDigest": digest(profile), "limits": LIMITS,
              "samples": [], "calls": [], "cycles": [], "checks": {},
              "temporaryOutputsRemoved": None,
              "pendingAcceptance": ["actual-SSR-and-renderer-heap-observation", "secret-event-child-call-campaign",
                                     "OCI-token-resolver-redirect-pool-campaign", "multi-ceiling-and-storage-dedup-campaign"],
              "evidenceScope": "real-standalone-HTTP-blob-provider-checkpoint"}
    root = None
    try:
        identify(args, result)
        original = inventory(args.fixture_root, deadline=started + profile["deadlineSeconds"])
        result["fixtureInventory"] = original
        names = ("angular", "alternate", "missing-sbom") if profile["kind"] == "web" else (
            "rust-http", "rust-blob", "rust-callee")
        result["fixtureTimePreflight"] = validity(args.fixture_root, profile["deadlineSeconds"], names=names)
        require(result["fixtureTimePreflight"]["sufficient"], "resource-fixture-validity-window-too-short")
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix="lsf-resource-239-") as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            if profile["kind"] == "web":
                from tools.phase3_resource_web import web_run
                web_run(args, result, cancellation, root, started + profile["deadlineSeconds"])
            else:
                node_run(args, result, cancellation, root, started + profile["deadlineSeconds"])
        result["temporaryOutputsRemoved"] = True
        result["fixtureUnchanged"] = inventory(args.fixture_root) == original
        if profile["kind"] == "provider":
            analyze(result)
        result["status"] = "checkpoint-passed"
        validate_receipt(result)
    except (Exception, KeyboardInterrupt) as error:
        result["status"] = "failed"
        reason = str(error) if isinstance(error, WorkflowError) else type(error).__name__
        result["failure"] = reason[:256]
    finally:
        if root is not None:
            result["temporaryOutputsRemoved"] = not root.exists()
    result["elapsedMillis"] = int((time.monotonic() - started) * 1000)
    write_receipt(args.output, result)
    print(json.dumps({"status": result["status"], "ticketAcceptance": "pending",
                      "samples": len(result["samples"]), "failure": result.get("failure"),
                      "receipt": file_identity(args.output)}))
    return 0 if result["status"] == "checkpoint-passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="smoke")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--build-identity", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--record-build", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--validate", type=Path)
    parser.add_argument("--host-condition", action="append", default=[])
    parser.add_argument("--matrix", action="store_true")
    args = parser.parse_args()
    if args.matrix:
        print(json.dumps({"profiles": PROFILES, "limits": LIMITS,
                          "maximumContainerCpus": 3, "maximumContainerMemoryBytes": 6442450944,
                          "isolatedCargoTargetRequired": True, "heavyCampaign": False}, sort_keys=True))
        return 0
    if args.validate:
        require(file_identity(args.validate)["sha256"] == args.validate.with_suffix(args.validate.suffix + ".sha256")
                .read_text(encoding="ascii").strip(), "resource-receipt-checksum")
        validate_receipt(read_json(args.validate, LIMITS["maximumReceiptBytes"]))
        print(json.dumps({"valid": True, "ticketAcceptance": "pending"}))
        return 0
    if args.record_build:
        return 0 if build(args) else 1
    require(all(path is not None and path.is_absolute() for path in
                (args.node, args.cli, args.fixture_root, args.build_identity, args.output)), "resource-absolute-inputs")
    require(len(args.host_condition) <= 8 and all(re.fullmatch(r"[a-z0-9-]{1,96}", condition)
            for condition in args.host_condition), "resource-host-label-bound")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
