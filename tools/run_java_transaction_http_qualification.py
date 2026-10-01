#!/usr/bin/env python3
"""Qualify preserved signed Java guests using actual already-built Phase 4 owners.

Linux/Python 3.13. This creates one private disposable root and retains every
failed attempt. It invokes no compiler, installs no inferred grant and cannot
qualify a packaged developer distribution or the full Phase 4 completion gate.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import file_identity
from tools.build_process_signals import owned_cancellation
from tools.java_transaction_qualification import configuration as cfg, inputs, lifecycle, packaging, policies
from tools.java_transaction_qualification.campaign import Campaign
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient, native
from tools.phase2_operator_process import bounded_receipt, read_json, write_json
from tools.rust_capsule_project import fresh

COLLECTORS = ("tools/run_java_transaction_http_qualification.py", "tools/phase2_operator_process.py",
    "tools/phase2_operator_scenario.py", "tools/build_process_linux.py", "tools/build_process_signals.py",
    "tools/static_api/node.py", "tools/java_transaction_qualification/inputs.py",
    "tools/java_transaction_qualification/packaging.py", "tools/java_transaction_qualification/evidence.py",
    "tools/java_transaction_qualification/configuration.py", "tools/java_transaction_qualification/policies.py",
    "tools/java_transaction_qualification/lifecycle.py", "tools/java_transaction_qualification/http.py",
    "tools/java_transaction_qualification/campaign.py", "tools/java_transaction_qualification/provider.py")
REMAINING = ["reviewed-schema-and-restore-original-results", "trap-and-fuel-after-staging",
             "cancellation-before-commit", "memory-exhaustion-before-commit", "crash-before-commit",
             "full-retention-horizon-expiry", "authenticated-clean-host-packaged-distribution"]


def parse():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cli", "node", "aot-compiler", "contracts-tool", "signer", "portable", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--native-source-commit", required=True, help="Exact source supplied by the binary build owner")
    parser.add_argument("--conductor-source-commit", required=True, help="Separate frozen collector source identity")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    inputs.require(sys.platform == "linux" and sys.version_info >= (3, 13), "linux-python313-required")
    inputs.require(0 < args.timeout <= 1200
                   and all(re.fullmatch(r"[0-9a-f]{40}", value)
                           for value in (args.native_source_commit, args.conductor_source_commit)),
                   "original-qualification-source-and-deadline")
    for name in ("cli", "node", "aot_compiler", "contracts_tool", "signer"):
        path = getattr(args, name)
        inputs.require(path.is_absolute() and path.is_file() and not path.is_symlink(), "actual-native-executable-required")
    inputs.require(args.portable.is_absolute() and args.portable.is_dir() and not args.portable.is_symlink()
                   and args.output.is_absolute(), "original-qualification-roots")
    return args


def tool_identity(args):
    return {name: file_identity(getattr(args, name), name, 1073741824)
            for name in ("cli", "node", "aot_compiler", "contracts_tool", "signer")}


def collector_identity():
    root = Path(__file__).resolve().parents[1]
    return {name: file_identity(root / name, "collector", 262144)["digest"] for name in COLLECTORS}


def prepare_environment(client, args, work, signed):
    native(client, args.signer, "fixture-tls", "fixture-tls", work / "tls")
    native(client, args.signer, "fixture-clock", "fixture-state-clock", work / "clock", lifecycle.NODE_ID)
    clock = read_json(work / "clock/clock-bootstrap.json")
    checkpoint = work / "clock/state-clock.json"
    client.evidence.record("fresh-native-clock", clock)
    credential_root = work / "credentials"
    credential_root.mkdir(mode=0o700)
    token = os.urandom(32).hex().encode()
    credential = credential_root / "put-once-header"
    with credential.open("xb") as output:
        # The shared native credential owner injects this exact header value;
        # it does not invent an authentication scheme from a secret file.
        output.write(b"Bearer " + token)
    credential.chmod(0o600)
    peer_token = work / "recipient-token"
    with peer_token.open("xb") as output:
        output.write(token)
    peer_token.chmod(0o600)
    recipient_root, node_root = work / "recipient", work / "node"
    recipient_root.mkdir(mode=0o700)
    node_root.mkdir(mode=0o700)
    peer = lifecycle.Peer(client, recipient_root, work / "tls", peer_token, os.urandom(32).hex())
    try:
        configuration = cfg.configure(node_root, signed, args.aot_compiler, work / "tls", checkpoint,
                                      peer.port, credential)
        client.evidence.record("bootstrap-configuration", configuration.value)
        return peer, configuration, lifecycle.Node(client, args.node, node_root)
    except BaseException:
        peer.close()
        raise


def provision(client, args, signed, items, peer, configuration, node):
    node.start(configuration.path)
    publications = lifecycle.publish(client, signed, items)
    node.stop()
    lifecycle.admission_lease_interval(client)
    operations = cfg.installed(items, publications, peer.incarnation)
    full_path = configuration.selected(configuration.path.parent / "installed-node.json", operations)
    hosts = lifecycle.inspect(client, args.node, full_path, operations)
    proposals = policies.documents(hosts, publications)
    client.evidence.record("actual-native-hosts", hosts.value)
    client.evidence.record("reviewed-policy-proposals", proposals)
    # Explicit normal authenticated mutations turn these proposals into actual
    # current decisions. The inspection and configuration alone grant nothing.
    node.start(configuration.path)
    actual_receipts = policies.apply(client, proposals)
    client.evidence.record("authenticated-policy-receipts", actual_receipts)
    node.stop()
    lifecycle.admission_lease_interval(client)
    node.start(full_path)
    legacy = next(item for item in items if item.name == "put-once-legacy-v1")
    lifecycle.create_namespace(client, legacy, publications[legacy.name])
    return full_path, publications, proposals, actual_receipts


def run(args):
    work = fresh(args.output)
    work.chmod(0o700)
    evidence = Evidence(work / "evidence")
    client_root = work / "client"
    client_root.mkdir(mode=0o700)
    record = {"schemaVersion": "latent.java-transaction.focused-native.v1", "passed": False,
        "trust": "ephemeral-native-package-test-only", "nativeSourceCommit": args.native_source_commit,
        "conductorSourceCommit": args.conductor_source_commit, "sourceIdentityKind": "supplied-build-identity",
        "compilerSourceCommit": inputs.COMPILER_SOURCE, "guestCompiledAgain": False,
        "packagedDistributionQualified": False, "remainingScenarios": REMAINING}
    stage, node, peer, client = "identity", None, None, None
    started = time.monotonic()
    try:
        with owned_cancellation() as cancellation:
            deadline = time.monotonic() + args.timeout
            tools, collectors = tool_identity(args), collector_identity()
            items = inputs.load(args.portable)
            record.update(nativeTools=tools, collectorDigests=collectors,
                          originalInputs=[item.observation() for item in items])
            client = RecordingClient(args.cli, client_root, cancellation, deadline, evidence)
            try:
                stage = "package"
                signed = packaging.package(args.portable, work / "packages", args.contracts_tool, args.signer,
                    timeout=max(1, int(min(600, deadline - time.monotonic()))))
                evidence.record("actual-package-fixture", read_json(work / "packages/package-fixture-receipt.json"))
                stage = "bootstrap"
                peer, configuration, node = prepare_environment(client, args, work, signed)
                stage = "current-authority"
                full_path, publications, proposals, receipts = provision(
                    client, args, signed, items, peer, configuration, node)
                stage = "actual-http"
                record["campaign"] = Campaign(client, configuration, full_path, signed, items,
                    publications, proposals, receipts, peer, node).execute()
                stage = "physical-retirement"
                node.stop()
                peer.stop()
                evidence.passed("actual-physical-retirement", {
                    "cleanNodeSessions": len(node.shutdown), "originalNodeReports": node.shutdown,
                    "recipient": peer.shutdown})
                stage = "identity-recheck"
                inputs.require(tool_identity(args) == tools and collector_identity() == collectors
                               and [item.observation() for item in inputs.load(args.portable)] == record["originalInputs"],
                               "qualification-input-changed")
                record.update(passed=True, signedGuestExecutionQualified=True)
            finally:
                # Cleanup is finite and owned even when a mutation, observation
                # or signal fails. A missing native report is never synthesized.
                with cancellation.defer():
                    if node is not None:
                        node.close()
                    if peer is not None:
                        peer.close()
                cancellation.check()
    except BaseException as error:
        record.update(passed=False, signedGuestExecutionQualified=False,
                      failedStage=stage, failureType=type(error).__name__)
        reason = str(error)
        if re.fullmatch(r"[a-z0-9][a-z0-9:-]{0,191}", reason):
            record["fixedFailureReason"] = reason
        # The exact original bounded subprocess/socket observations remain in
        # the private evidence directory; no error message is public authority.
    finally:
        record.update(seconds=round(time.monotonic() - started, 6),
                      cliProcesses=client.calls if client else 0, measuredCases=list(evidence.cases))
        record["evidenceInventory"] = evidence.record("inventory", evidence.summary())
        write_json(work / "campaign-receipt.json", record)
    print(bounded_receipt(record))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run(parse()))
