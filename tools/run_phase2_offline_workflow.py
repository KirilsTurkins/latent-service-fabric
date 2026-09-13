#!/usr/bin/env python3
"""Separate real registry outage from retained local execution and revocation.

Fixed profile: two supplied signed test packages, at most 40 CLI processes,
three invocation attempts, one node/cell and a 180-second scenario deadline.
Registry setup and cleanup use separate bounded fixture-tool calls. No retries,
fresh trust, adaptive population or retained raw logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_canary import invoke
from tools.phase2_operator_process import Client, WorkflowError, read_json, require, write_json
from tools.phase2_operator_scenario import configure_node, connect, receipt, route, stop
from tools.run_oci_registry_tests import IMAGE, Registry, certificates, ready
from tools.run_phase2_operator_workflow import package_workflow, registry_profile


def file_digest(path, maximum):
    require(path.is_file() and not path.is_symlink(), "identity-file")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(65536):
            total += len(chunk)
            require(total <= maximum, "identity-file-bound")
            digest.update(chunk)
    require(total > 0, "identity-file-empty")
    return "sha256:" + digest.hexdigest()


def run(args, origin, ca, stop_registry):
    """The supplied registry owner must synchronously stop/reap its own fixture."""
    require(sys.platform == "linux" and sys.version_info >= (3, 13), "linux-python313-required")
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "source-commit")
    for path in (args.cli, args.node):
        require(path.is_absolute(), "absolute-binary")
    identities = {"sourceCommit": args.source_commit,
                  "cliDigest": file_digest(args.cli, 1024 * 1024 * 1024),
                  "nodeDigest": file_digest(args.node, 1024 * 1024 * 1024),
                  "policyFileDigest": file_digest(args.fixture_root / "policy.json", 262144),
                  "registryImage": IMAGE}
    tools_root = Path(__file__).resolve().parent
    identities["collectorDigests"] = {
        name: file_digest(tools_root / name, 262144) for name in (
            "run_phase2_offline_workflow.py", "run_phase2_operator_workflow.py",
            "phase2_operator_scenario.py", "phase2_operator_process.py",
            "phase2_operator_canary.py", "build_process_linux.py",
            "build_process_signals.py", "run_oci_registry_tests.py")}
    metadata = read_json(args.fixture_root / "fixture.json", 16384)
    require(metadata["formatVersion"] == 1 and int(metadata["expiresAtUnixSeconds"]) > time.time() + 180,
            "fixture-expiring")
    with owned_cancellation() as cancellation:
        with tempfile.TemporaryDirectory(prefix="lsf-offline-workflow-") as temporary:
            work = Path(temporary)
            client_dir, node_dir = work / "client", work / "node"
            client_dir.mkdir(mode=0o700)
            node_dir.mkdir(mode=0o700)
            outputs = client_dir / "outputs"
            outputs.mkdir()
            client = Client(args.cli, client_dir, cancellation, time.monotonic() + 180)
            profile = registry_profile(client_dir, origin, ca)
            summaries = package_workflow(client, args.fixture_root, outputs, profile, metadata["tenant"])
            config = configure_node(node_dir, args.fixture_root, metadata["tenant"])
            identities["nodeConfigDigest"] = file_digest(config, 262144)
            node = connect(client, args.node, node_dir, config, metadata["tenant"], 1)
            try:
                published = client.call("release", "publish-package", outputs / "blue-pulled",
                                        "--evidence", outputs / "blue-evidence/index.json",
                                        "--operation-id", "offline-publish", "--expected-generation", "0")["data"]
                digest = summaries["blue"]["componentDigest"]
                require(published["release"]["digest"] == digest, "publication-identity")
                snapshot = client.call("deployment", "get", "blue", "--operation-snapshot", codes=(6,))["data"]
                applied = receipt(client.call("deployment", "apply", args.fixture_root / "blue/deployment.json",
                                               "--operation-id", "offline-apply", "--expected-generation", "0",
                                               "--expected-state-version", snapshot["stateVersion"]), "offline-apply")
                input_path = client_dir / "input.json"
                write_json(input_path, metadata["input"])
                before = invoke(client, metadata, input_path, "offline-before-outage")
                routes = route(client)
                require(before["releaseDigest"] == digest and before["routeGeneration"] == applied["routeGeneration"],
                        "initial-invoke-association")

                # Only the registry owner changes. Node policy, artifacts and
                # routes remain intact; no refresh or readmission is performed.
                stop_registry()
                failed_output = outputs / "outage-pull"
                failure = client.call("--rpc-timeout-ms", "2000", "package", "pull",
                                      "--registry-profile", profile, "--reference", "blue",
                                      "--output-dir", failed_output, "--evidence-output", outputs / "outage-evidence",
                                      codes=(2,))
                require(failure["error"]["code"] == "package-operation-failed" and not failed_output.exists(),
                        "registry-outage-transfer")
                after = invoke(client, metadata, input_path, "offline-during-outage")
                require(after == before and route(client) == routes, "outage-changed-local-authority")

                lifecycle = client.call("release", "lifecycle", digest)["data"]["status"]["record"]
                revoked = client.call("release", "revoke", digest, "--operation-id", "offline-revoke",
                                      "--expected-generation", lifecycle["generation"])["data"]["operation"]
                # The same route is still pinned in catalog history. Current
                # local lifecycle must deny a new call without a registry event.
                denied = client.call("--rpc-timeout-ms", "5000", "invoke", "--service", metadata["service"],
                                     "--contract", metadata["contract"], "--function", metadata["function"],
                                     "--activation-id", "offline-after-revocation", "--input", input_path,
                                     "--wall-time-ms", "5000", "--cpu-fuel", "1000000",
                                     "--memory-bytes", "4194304", "--log-bytes", "1024", codes=(4,))
                require(denied["outcomeKnown"] and denied["category"] == "platform-failure"
                        and denied["error"]["code"] == "permission-denied", "local-revocation-denial")
                current = client.call("release", "lifecycle", digest)["data"]["status"]["record"]
                require(current["state"].endswith("REVOKED") and current["operationId"] == "offline-revoke",
                        "revocation-identity")
                stop(client, node)
                lines = bytes(node.buffers[0]).splitlines()
                require(len(lines) == 1 and len(lines[0]) <= 16384, "shutdown-record-bound")
                shutdown = json.loads(lines[0])
                require(shutdown["schemaVersion"] == "latent.standalone.status.v1"
                        and shutdown["event"] == "stopped" and shutdown["clean"] is True
                        and shutdown["report"]["clean"] is True
                        and node.owner.process.returncode == 0, "shutdown-not-clean")
                node = None
                require(client.calls <= 40 and time.monotonic() < client.deadline, "profile-exceeded")
                result = {"schemaVersion": "latent.phase2.offline-test.v1", "passed": True,
                          "profile": "phase2-offline-r1", "identities": identities,
                          "packageIdentities": summaries, "publication": published["operation"],
                          "deployment": applied, "beforeOutage": before, "duringOutage": after,
                          "outageTransferCode": failure["error"]["code"],
                          "revocation": revoked, "revokedInvokeCode": denied["error"]["code"],
                          "shutdown": shutdown, "cliProcesses": client.calls,
                          "successfulInvocations": 2, "deniedInvocations": 1,
                          "registryStoppedByOwner": True, "nodeReaped": True,
                          "temporaryOutputsRemoved": True, "syntheticTestEvidence": True}
            finally:
                client.node = None
                if node is not None:
                    node.close()
        cancellation.check()
    encoded = json.dumps(result, separators=(",", ":"))
    require(len(encoded.encode("utf-8")) <= 65536, "receipt-byte-bound")
    return encoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True, help="Exact source commit used to build the supplied binaries")
    args = parser.parse_args()
    with owned_cancellation() as cancellation:
        with tempfile.TemporaryDirectory(prefix="lsf-offline-registry-") as temporary:
            directory = Path(temporary)
            registry = Registry(directory)
            try:
                certificates(directory)
                cancellation.check()
                origin = registry.launch()
                ready(origin, directory / "ca.pem")
                cancellation.check()
                result = run(args, origin, directory / "ca.der", registry.close)
            finally:
                with cancellation.defer():
                    registry.close()
        cancellation.check()
    print(result)


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, WorkflowError) else "fixture-or-process-error"
        print("Offline workflow failed: " + reason, file=sys.stderr)
        sys.exit(1)
