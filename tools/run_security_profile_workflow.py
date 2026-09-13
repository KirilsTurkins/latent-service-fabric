#!/usr/bin/env python3
"""Small real-node external-capsule profile regression; no registry or load run.

Uses freshly exported synthetic signed operator fixtures and already-built node,
CLI and approved compiler binaries. Owns/reaps every process and removes its
temporary storage. It does not generate or claim real build provenance.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_canary import invoke
from tools.phase2_operator_process import (
    Client, Process, WorkflowError, bounded_receipt, file_digest, read_json, require,
    stopped_record, write_json,
)
from tools.phase2_operator_scenario import NODE_ID, TOKEN, configure_node, connect, stop
from tools.run_phase2_operator_workflow import inventory

EXTERNAL = "external-capsule-v1"


def replace_config(path, value):
    # Only this workflow's stopped-node configuration may be rewritten. The
    # shared write_json helper intentionally uses exclusive creation elsewhere.
    require(path.name == "node.json" and path.is_file() and not path.is_symlink(),
            "owned-config-file")
    data = json.dumps(value, separators=(",", ":")).encode()
    require(len(data) <= 65536, "owned-config-size")
    path.write_bytes(data)


def command(client, node, config, name, success):
    process = Process([str(node), name, "--config", str(config)], client.directory,
                      client.environment, client.cancellation, maximum=32768)
    try:
        result = process.complete(min(client.deadline, time.monotonic() + 40))
    finally:
        process.close()
    require(process.owner.finished and process.closed, "command-owner-not-reaped")
    require((result.returncode == 0) == success, "profile-command-exit")
    combined = result.stdout + result.stderr
    require(TOKEN.encode() not in combined and str(config.parent).encode() not in combined,
            "profile-secret-or-path-disclosure")
    if success:
        require(not result.stderr, "profile-check-diagnostic")
        report = json.loads(result.stdout)
        require(report["schemaVersion"] == "latent.standalone.config-check.v1"
                and report["profile"] == EXTERNAL and report["threatClass"] == "T1"
                and report["admission"] == "enforced"
                and report["protectedCredentialFile"] is True
                and report["guestBoundary"] == "in-process-wasmtime"
                and report["wasmtimeVersion"] == "47.0.4"
                and report["hostAbiProfile"] == "lsf-host-abi-phase3-v2"
                and report["compilerSandbox"] == "lsf-linux-x86_64-landlock3-seccomp-v1"
                and report["authenticatedNativeLoading"] is True, "profile-check-controls")
        return report
    require(not result.stdout and result.stderr, "rejected-profile-started-or-unclassified")
    return None


def configuration(client, node_dir, fixture, compiler):
    path = configure_node(node_dir, fixture, "tests")
    key = node_dir / "native.key"
    key.write_bytes(bytes([83]) * 32)  # Public test-only same-node authentication key.
    key.chmod(0o600)
    value = read_json(path)
    value["securityProfile"] = EXTERNAL
    value["isolatedAot"] = {
        "compilerExecutable": str(compiler),
        "compilerDigest": file_digest(compiler, 512 * 1024 * 1024,
                                      client.cancellation, client.deadline),
        "keyFile": "native.key", "blobRoot": "native-blobs", "receiptRoot": "native-receipts",
        "process": {"maximumOutputBytes": 2097152},
        "cache": {"entries": 4, "diskBytes": 8388608},
        "images": {"maximumImages": 2, "maximumImageBytes": 2097152, "maximumTotalBytes": 4194304},
    }
    replace_config(path, value)
    return path, value


def rejection_checks(client, args, path, original):
    variants = []
    for missing in ("isolatedAot", "supplyChain"):
        value = copy.deepcopy(original)
        del value[missing]
        variants.append(value)
    for name in (None, "fixed-execution-host-v1", "external-capsule-v2"):
        variants.append(dict(original, securityProfile=name))
    wrong = copy.deepcopy(original)
    wrong["isolatedAot"]["compilerDigest"] = "sha256:" + "0" * 64
    variants.append(wrong)
    for value in variants:
        replace_config(path, value)
        for name in ("check-config", "serve"):
            command(client, args.node, path, name, False)
    replace_config(path, original)
    path.parent.parent.chmod(0o755)
    path.parent.chmod(0o755)
    path.chmod(0o644)
    command(client, args.node, path, "check-config", False)
    path.chmod(0o600)
    path.parent.chmod(0o700)
    path.parent.parent.chmod(0o700)
    # Protect the integrity of the separately read trust policy as well.
    policy = path.parent / "policy.json"
    policy.chmod(0o666)
    command(client, args.node, path, "check-config", False)
    policy.chmod(0o600)
    require(not (path.parent / "data").exists()
            and not (path.parent / "native-blobs").exists(), "rejection-created-storage")
    return 14


def publish_and_apply(client, fixture):
    published = client.call("release", "publish-package", fixture / "blue/package",
                            "--evidence", fixture / "blue/evidence/index.json",
                            "--operation-id", "profile-publish", "--expected-generation", "0")
    require(published["outcomeKnown"], "publication-uncertain")
    state = client.call("deployment", "get", "blue", "--operation-snapshot", codes=(6,))["data"]
    client.call("deployment", "apply", fixture / "blue/deployment.json", "--operation-id", "profile-apply",
                "--expected-state-version", state["stateVersion"], "--expected-generation", "0")


def restarted(client, args, directory, path, original):
    # Existing durable supply-chain leases require this minimum closed interval.
    until = time.monotonic() + 6
    weakened = copy.deepcopy(original)
    del weakened["securityProfile"]
    replace_config(path, weakened)
    for name in ("check-config", "serve"):
        command(client, args.node, path, name, False)
    replace_config(path, original)
    before = inventory(directory)
    command(client, args.node, path, "check-config", True)
    require(inventory(directory) == before, "check-config-mutated-existing-storage")
    while time.monotonic() < until:
        client.cancellation.check()
        require(time.monotonic() < client.deadline, "workflow-deadline")
        time.sleep(0.025)
    return connect(client, args.node, directory, path, "tests", 2)


def run(args):
    fixture = args.fixture_root.resolve(strict=True)
    original_fixture = inventory(fixture)
    metadata = read_json(fixture / "fixture.json")
    with owned_cancellation() as cancellation:
        with tempfile.TemporaryDirectory(prefix="lsf-security-profile-") as temporary:
            directory = Path(temporary)
            node_dir = directory / "node"
            node_dir.mkdir(mode=0o700)
            client = Client(args.cli, directory, cancellation, time.monotonic() + 180)
            path, original = configuration(client, node_dir, fixture, args.compiler)
            rejected = rejection_checks(client, args, path, original)
            before = inventory(node_dir)
            report = command(client, args.node, path, "check-config", True)
            require(inventory(node_dir) == before, "check-config-created-storage")
            node = None
            shutdown = []
            try:
                node = connect(client, args.node, node_dir, path, "tests", 1)
                attributes = client.call("node", "get", NODE_ID)["data"]["inventory"]["node"]["attributes"]
                require(attributes["lsf.security.profile"] == EXTERNAL
                        and attributes["lsf.security.admission"] == "enforced", "inventory-profile")
                publish_and_apply(client, fixture)
                input_path = directory / "input.json"
                write_json(input_path, metadata["input"])
                for name in ("external-cold", "external-warm"):
                    invoke(client, metadata, input_path, name)
                stop(client, node)
                shutdown.append(stopped_record(node))
                node = None
                node = restarted(client, args, node_dir, path, original)
                invoke(client, metadata, input_path, "external-restarted")
                stop(client, node)
                shutdown.append(stopped_record(node))
                node = None
                require(client.calls <= 20, "cli-call-bound")
                require(inventory(fixture) == original_fixture, "fixture-mutated")
                result = {"schemaVersion": "latent.security-profile.workflow.v1", "passed": True,
                          "profile": report, "rejectedCommands": rejected + 2, "cliProcesses": client.calls,
                          "successfulInvocations": 3, "shutdown": shutdown,
                          "syntheticTestEvidence": True, "temporaryOutputsRemoved": True}
            finally:
                client.node = None
                if node is not None:
                    node.close()
        cancellation.check()
    return bounded_receipt(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cli", "node", "compiler", "fixture-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ("cli", "node", "compiler"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    print(run(args))


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, WorkflowError) else "fixture-or-process-error"
        print("Security profile workflow failed: " + reason, file=sys.stderr)
        sys.exit(1)
