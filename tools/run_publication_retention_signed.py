#!/usr/bin/env python3
"""Bounded signed-publication retention and stopped coupled-restore qualification.

Only a freshly exported synthetic signed fixture and disposable local nodes are
accepted. This is not a physical power-loss or independently retained-history
compaction qualification.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_canary import invoke
from tools.phase2_operator_process import bounded_receipt, file_digest, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_web_scenario import tree_inventory
from tools.run_phase2_operator_workflow import build_identity, inventory
from tools.run_publication_workflow import Client, apply, manifest, publish, record, wait_restart_floor

TENANT = "tests"
ACTOR = "workflow-operator"
MAX_FILES = 4096
MAX_ENTRIES = 8192
MAX_COPY_BYTES = 256 * 1024 * 1024
DEADLINE_SECONDS = 240
COLLECTORS = (
    "tools/run_publication_retention_signed.py", "tools/run_publication_workflow.py",
    "tools/run_phase2_operator_workflow.py", "tools/phase2_operator_process.py",
    "tools/phase2_operator_scenario.py", "tools/phase2_operator_canary.py",
    "tools/phase3_web_scenario.py", "tools/build_process.py",
    "tools/build_process_linux.py", "tools/build_process_signals.py",
)


def collector_identity(cancellation, deadline):
    root = Path(__file__).resolve().parents[1]
    return {name: file_digest(root / name, 262144, cancellation, deadline) for name in COLLECTORS}


def selected(client, publication):
    value = client.call("release", "retention", "snapshot", "--publication", publication)["data"]
    entries = value.get("entries")
    fence = value.get("catalogFence")
    require(value.get("tenant") == TENANT and isinstance(fence, str)
            and re.fullmatch(r"[0-9a-f]{64}", fence) is not None
            and isinstance(entries, list) and len(entries) == 1, "retention-snapshot-shape")
    target = entries[0].get("target")
    require(isinstance(target, dict) and target.get("publication") == {"tenant": TENANT, "id": publication}
            and isinstance(target.get("expectedGeneration"), str)
            and re.fullmatch(r"[1-9][0-9]{0,19}", target["expectedGeneration"]) is not None
            and int(target["expectedGeneration"]) <= 2**64 - 1,
            "retention-target-association")
    return fence, target, entries[0].get("pin")


def checked_receipt(result, kind, stage, operation, fence, target):
    require(result.get("outcomeKnown") is True and result.get("category") == "success", "retention-outcome")
    data = result.get("data")
    require(isinstance(data, dict) and data.get("replay") is False, "retention-original-mutation")
    receipt = data.get("receipt")
    require(isinstance(receipt, dict) and receipt.get("tenant") == TENANT
            and isinstance(receipt.get("actor"), dict) and receipt["actor"].get("subject") == ACTOR
            and receipt.get("stage") == stage, "retention-receipt-identity")
    command = receipt.get("command")
    require(isinstance(command, dict) and command.get("kind") == "PUBLICATION_MAINTENANCE_KIND_" + kind.upper()
            and command.get("selection") == {"operationId": operation, "catalogFence": fence, "targets": [target]},
            "retention-receipt-selection")
    ack = data.get("auditAck")
    require(isinstance(ack, dict) and ack.get("status") == "AUDIT_ACK_STATUS_DURABLE"
            and isinstance(ack.get("attemptSequence"), str)
            and re.fullmatch(r"[1-9][0-9]{0,19}", ack["attemptSequence"]) is not None,
            "retention-audit-not-durable")
    return receipt


def lookup(client, kind, operation, expected):
    result = client.call("release", "retention", "operation", "--kind", kind, "--operation-id", operation)
    data = result["data"]
    require(result["outcomeKnown"] is True and data.get("tenant") == TENANT
            and data.get("disposition") == "RELEASE_OPERATION_LOOKUP_DISPOSITION_FOUND"
            and data.get("receipt") == expected and data.get("automaticReplay") is False,
            "retention-original-lookup")


def assert_hidden(client, publication):
    removed = client.call("release", "get", "--publication", publication, codes=(4, 6))
    missing = client.call("release", "get", "--publication", "publication:sha256:" + "0" * 64, codes=(4, 6))
    require(removed.get("category") != "success" and removed.get("category") == missing.get("category")
            and removed.get("error") == missing.get("error"), "reclaimed-publication-visible-or-distinguishable")


def audit_attempts(client, expected):
    """Prove the restored audit journal retains these exact committed operations."""
    require(len(expected) == 3, "retention-audit-attempt-count")
    attempts, outcomes, seen_tokens, token, previous = {}, {}, set(), None, 0
    for _ in range(16):
        arguments = ["audit", "query", "--scope", "tenant", "--page-size", "16"]
        if token:
            arguments.extend(("--page-token", token))
        data = client.call(*arguments)["data"]
        require(isinstance(data.get("records"), list) and len(data["records"]) <= 16
                and isinstance(data.get("page"), dict), "retention-audit-page-shape")
        for row in data["records"]:
            sequence = int(row["sequence"])
            require(sequence > previous, "retention-audit-page-order")
            previous = sequence
            attempt, outcome = row["data"].get("attempt"), row["data"].get("outcome")
            key = str(sequence)
            if key in expected and attempt is not None:
                require(key not in attempts and row.get("actor", {}).get("subject") == ACTOR
                        and (attempt.get("operationId"), attempt.get("action")) == expected[key]
                        and attempt.get("replay") is False, "retention-audit-attempt-mismatch")
                attempts[key] = attempt["action"]
            if outcome is not None and outcome.get("attemptSequence") in expected:
                key = outcome["attemptSequence"]
                require(key not in outcomes and outcome.get("result") == "AUDIT_OPERATION_RESULT_COMMITTED"
                        and outcome.get("replay") is False, "retention-audit-outcome-mismatch")
                outcomes[key] = outcome["result"]
        token = data["page"].get("nextPageToken")
        if not token:
            break
        require(isinstance(token, str) and len(token) <= 4096 and token not in seen_tokens,
                "retention-audit-page-token")
        seen_tokens.add(token)
    require(not token and set(attempts) == set(outcomes) == set(expected), "retention-audit-coverage")
    return {"committedAttemptSequences": sorted(attempts, key=int), "restoredAuditVerified": True}


def copy_stopped_installation(source, destination, client):
    """Copy a complete private node tree; preserve content, modes and hardlinks."""
    require(sys.platform == "linux", "restore-requires-linux")
    source, destination = Path(source), Path(destination)
    require(source.is_absolute() and destination.is_absolute() and source.parent == destination.parent
            and source != destination and source.is_dir() and not source.is_symlink()
            and not destination.exists() and not destination.is_symlink(), "restore-owned-paths")
    before = tree_inventory(source, client, maximum_bytes=MAX_COPY_BYTES, maximum_entries=MAX_ENTRIES)
    hardlinks, copied_bytes, copied_files = {}, 0, 0

    def copy_file(src, dst):
        nonlocal copied_bytes, copied_files
        client.cancellation.check()
        require(time.monotonic() < client.deadline, "restore-copy-deadline")
        src, dst = Path(src), Path(dst)
        info = src.lstat()
        copied_files += 1
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and copied_files <= MAX_FILES,
                "restore-regular-owned-file-required")
        identity = (info.st_dev, info.st_ino)
        if identity in hardlinks:
            os.link(hardlinks[identity], dst)
        else:
            copied_bytes += info.st_size
            require(copied_bytes <= MAX_COPY_BYTES, "restore-copy-byte-bound")
            shutil.copy2(src, dst, follow_symlinks=False)
            hardlinks[identity] = dst
        require(stat.S_IMODE(dst.stat().st_mode) == stat.S_IMODE(info.st_mode), "restore-mode-changed")
        return str(dst)

    shutil.copytree(source, destination, copy_function=copy_file, symlinks=False)
    require(tree_inventory(source, client, maximum_bytes=MAX_COPY_BYTES, maximum_entries=MAX_ENTRIES) == before
            and tree_inventory(destination, client, maximum_bytes=MAX_COPY_BYTES, maximum_entries=MAX_ENTRIES) == before,
            "restore-content-mismatch")
    for relative in before:
        original, restored = source / relative, destination / relative
        old_info, new_info = original.stat(), restored.stat()
        require(old_info.st_nlink == new_info.st_nlink
                and (old_info.st_dev, old_info.st_ino) != (new_info.st_dev, new_info.st_ino),
                "restore-hardlinks-or-independent-copy-changed")
        with restored.open("rb") as stream:
            os.fsync(stream.fileno())
    for parent, children, _files in os.walk(destination, topdown=False):
        for name in [parent, *(str(Path(parent) / child) for child in children)]:
            restored = Path(name)
            original = source / restored.relative_to(destination)
            require(not restored.is_symlink() and not original.is_symlink()
                    and original.stat().st_uid == os.getuid() and restored.stat().st_uid == os.getuid()
                    and stat.S_IMODE(restored.stat().st_mode) == stat.S_IMODE(original.stat().st_mode),
                    "restore-directory-owner-or-mode-changed")
            descriptor = os.open(restored, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    return ({"fileCount": copied_files, "uniqueCopiedBytes": copied_bytes,
             "contentModesAndHardlinksVerified": True, "independentCopy": True}, before)


def run(args):
    client = node = identities = None
    phase = "fixture"
    try:
        fixture = args.fixture_root.resolve(strict=True)
        metadata = read_json(fixture / "fixture.json")
        require(metadata.get("publicationWorkflow") is True, "wrong-fixture-profile")
        original_fixture = inventory(fixture)
        with owned_cancellation() as cancellation:
            with tempfile.TemporaryDirectory(prefix="lsf-signed-publication-retention-") as temporary:
                work = Path(temporary).resolve(strict=True)
                directory = work / "node"
                directory.mkdir(mode=0o700)
                deadline = time.monotonic() + DEADLINE_SECONDS
                client = Client(args.cli.resolve(strict=True), work, cancellation, deadline)
                identities = build_identity(args, cancellation, deadline)
                collectors = collector_identity(cancellation, deadline)
                config = configure_node(directory, fixture, TENANT)
                input_path = work / "input.json"
                write_json(input_path, metadata["input"])
                shutdown = []
                try:
                    phase = "signed-publication"
                    node = connect(client, args.node.resolve(strict=True), directory, config, TENANT, 1)
                    rows = publish(client, fixture, TENANT)
                    blue, green = rows["blue"]["reference"], rows["green"]["reference"]
                    path = manifest(fixture, work, TENANT, "blue", blue, 0)
                    _, deployed = apply(client, path, "deploy-blue")
                    require(deployed["publication"] == blue, "surviving-deployment-association")
                    before = invoke(client, metadata, input_path, "retention-blue-before")
                    require(before["publicationId"] == blue["id"]
                            and before["releaseDigest"] == rows["blue"]["component"], "surviving-blue-before")

                    phase = "pin-and-retire"
                    fence, target, pin = selected(client, blue["id"])
                    require(pin is None, "blue-unexpected-existing-pin")
                    pin_result = client.call("release", "retention", "pin", "--operation-id", "pin-blue",
                                             "--catalog-fence", fence, "--target", blue["id"] + "=" + target["expectedGeneration"])
                    pin_receipt = checked_receipt(pin_result, "pin", "retention-updated", "pin-blue", fence, target)
                    _, _, pinned_blue = selected(client, blue["id"])
                    require(isinstance(pinned_blue, dict) and pinned_blue.get("operationId") == "pin-blue",
                            "blue-pin-not-retained")
                    generation = record(client, green)["generation"]
                    retired = client.call("release", "retire", "--publication", green["id"],
                                          "--operation-id", "retire-green", "--expected-generation", generation)
                    require(retired["outcomeKnown"] is True and retired["data"]["operation"]["publication"] == green
                            and retired["data"]["operation"]["record"]["state"].endswith("RETIRED"),
                            "green-retirement")

                    phase = "delete-and-reclaim"
                    fence, target, pin = selected(client, green["id"])
                    require(pin is None, "green-unexpected-pin")
                    target_arg = green["id"] + "=" + target["expectedGeneration"]
                    selection_args = ("--operation-id", "delete-green", "--catalog-fence", fence, "--target", target_arg)
                    deleted = client.call("release", "retention", "delete", *selection_args, "--maximum-wait-ms", "10000")
                    deletion = checked_receipt(deleted, "delete", "visibility-removed", "delete-green", fence, target)
                    require(deletion.get("reclaimed") is None, "deletion-reported-reclaim")
                    assessed = client.call("release", "retention", "assess", *selection_args,
                                           "--maximum-files", "1024", "--maximum-bytes-hashed", "67108864",
                                           "--maximum-wait-ms", "10000")["data"]
                    current = assessed.get("catalogFence")
                    require(assessed.get("tenant") == TENANT and assessed.get("deletion") == deletion["command"]["selection"]
                            and assessed.get("authorizesLaterDeletion") is False and isinstance(current, str)
                            and re.fullmatch(r"[0-9a-f]{64}", current) is not None,
                            "reclamation-assessment-association")
                    reclaimed = client.call("release", "retention", "reclaim", *selection_args,
                                            "--reclamation-fence", current, "--maximum-files", "1024",
                                            "--maximum-bytes-hashed", "67108864", "--maximum-wait-ms", "10000")
                    reclamation = checked_receipt(reclaimed, "reclaim", "namespaces-reclaimed", "delete-green", fence, target)
                    require(reclamation["command"].get("reclamationCatalogFence") == current
                            and isinstance(reclamation.get("reclaimed"), dict)
                            and reclamation["reclaimed"].get("physicalDiskBlocksFreed") is None
                            and reclamation["reclaimed"].get("sharedBlobsRetained", 0) > 0,
                            "shared-blob-retention-not-observed")
                    for kind, operation, original in (("pin", "pin-blue", pin_receipt),
                                                       ("delete", "delete-green", deletion),
                                                       ("reclaim", "delete-green", reclamation)):
                        lookup(client, kind, operation, original)
                    assert_hidden(client, green["id"])
                    after = invoke(client, metadata, input_path, "retention-blue-after")
                    require(after["publicationId"] == blue["id"]
                            and after["releaseDigest"] == rows["blue"]["component"], "surviving-blue-after")

                    phase = "stopped-coupled-restore"
                    stop(client, node)
                    shutdown.append(stopped_record(node))
                    node = None
                    restored = work / "restored-installation"
                    copied, original_node_inventory = copy_stopped_installation(directory, restored, client)
                    wait_restart_floor(client)
                    node = connect(client, args.node.resolve(strict=True), restored, restored / config.name, TENANT, 2)
                    for kind, operation, original in (("pin", "pin-blue", pin_receipt),
                                                       ("delete", "delete-green", deletion),
                                                       ("reclaim", "delete-green", reclamation)):
                        lookup(client, kind, operation, original)
                    assert_hidden(client, green["id"])
                    _, _, restored_pin = selected(client, blue["id"])
                    require(restored_pin == pinned_blue, "restored-pin-differs")
                    expected_audit = {
                        pin_result["data"]["auditAck"]["attemptSequence"]:
                            ("pin-blue", "AUDIT_CONTROL_ACTION_PUBLICATION_PIN"),
                        deleted["data"]["auditAck"]["attemptSequence"]:
                            ("delete-green", "AUDIT_CONTROL_ACTION_PUBLICATION_DELETE"),
                        reclaimed["data"]["auditAck"]["attemptSequence"]:
                            ("delete-green", "AUDIT_CONTROL_ACTION_PUBLICATION_RECLAIM"),
                    }
                    audit = audit_attempts(client, expected_audit)
                    restored_result = invoke(client, metadata, input_path, "retention-blue-restored")
                    require(restored_result["publicationId"] == blue["id"]
                            and restored_result["releaseDigest"] == rows["blue"]["component"],
                            "restored-blue-not-usable")
                    stop(client, node)
                    shutdown.append(stopped_record(node))
                    node = None
                    require(client.calls <= 64 and time.monotonic() < deadline, "signed-retention-budget")
                    require(inventory(fixture) == original_fixture, "signed-fixture-mutated")
                    require(tree_inventory(directory, client, maximum_bytes=MAX_COPY_BYTES,
                                           maximum_entries=MAX_ENTRIES) == original_node_inventory,
                            "stopped-original-changed-after-restore")
                    require(build_identity(args, cancellation, deadline) == identities, "binary-or-input-identity-changed")
                    require(collector_identity(cancellation, deadline) == collectors, "collector-identity-changed")
                    result = {"schemaVersion": "latent.publication.signed-retention.v1", "passed": True,
                              "identities": identities, "collectorIdentities": collectors,
                              "publications": {"retained": blue, "reclaimed": green},
                              "pinReceipt": pin_receipt, "deletionReceipt": deletion,
                              "reclamationReceipt": reclamation, "restoredPin": restored_pin,
                              "restoredAudit": audit,
                              "copy": {**copied, "originalUnchangedAfterRestore": True},
                              "shutdown": shutdown, "cliProcesses": client.calls,
                              "signedNodeDeletionAndStoppedRestore": True, "physicalPowerLossQualified": False,
                              "independentHistoryCompactionQualified": False,
                              "syntheticTestEvidence": True, "temporaryOutputsRemoved": True}
                finally:
                    if node is not None:
                        client.node = None
                        node.close()
            cancellation.check()
        return bounded_receipt(result)
    except BaseException:
        failure = {"schemaVersion": "latent.publication.signed-retention.v1", "passed": False,
                   "phase": phase, "identities": identities,
                   "failedCall": client.failed_call if client is not None else None,
                   "temporaryOutputsRemoved": "unverified", "syntheticTestEvidence": True}
        print(bounded_receipt(failure), file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    require(args.source_commit is None or re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "source-commit")
    print(run(args))


if __name__ == "__main__":
    main()
