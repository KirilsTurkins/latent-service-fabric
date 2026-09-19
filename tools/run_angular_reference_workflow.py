#!/usr/bin/env python3
"""Actual maintained Angular, protected T1 node, scoped HTTP peer and Chromium delivery."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, WorkflowError, bounded_receipt, file_digest, require, stopped_record, write_json
from tools.phase2_operator_scenario import change, connect, receipt, stop
from tools.phase3_reference_config import USERS, authenticate_config, configure, configure_grant, fixtures
from tools.phase3_reference_lifecycle import canary, cancellations, signal_owned, start_peer, wait_idle
from tools.phase3_reference_scenario import assets, deploy, http, invoke, trigger
from tools.phase3_web_qualification import native_cache_audit
from tools.phase3_web_scenario import MIB, TENANT, client_profile, foreign_profile, prepare, publication_receipt, publish, tree_inventory
from tools.run_angular_t1_workflow import QualificationClient
from tools.run_security_profile_workflow import command, rejection_checks, replace_config


def stage(report, name):
    report["lastStage"] = name
    print("Angular reference: " + name, file=sys.stderr, flush=True)


def browser(client, args, records, publications, mode):
    config = client.directory / f"browser-{mode}.json"
    write_json(config, {"schemaVersion": "latent.angular.reference.browser-input.v1", "mode": mode,
        "origin": "http://" + client.host, "chrome": str(args.chrome), "toolchain": str(args.toolchain_root),
        "users": [{"subject": subject, "token": token} for subject, token in USERS],
        "releases": {name: {"publication": publications[name], "version": record["version"], "assets": record["assets"]}
                     for name, record in records.items()}})
    return Process([str(args.nodejs), str(Path(__file__).with_name("check_angular_reference.mjs")), str(config)],
                   client.directory, client.environment, client.cancellation, maximum=128 * 1024)


def browser_wait(client, process, phase):
    event = process.line(min(client.deadline, time.monotonic() + 75))
    require(event == {"event": "waiting", "phase": phase}, "reference-browser-phase")


def browser_result(client, process):
    result = process.complete(min(client.deadline, time.monotonic() + 75))
    if result.returncode != 0:
        print(result.stderr.decode("utf-8", errors="replace")[:8192], file=sys.stderr)
    require(result.returncode == 0, "reference-browser-failed")
    record = json.loads(result.stdout)
    require(record["schemaVersion"] == "latent.angular.reference.browser.v1" and record["passed"] is True
            and record["transport"] == "real-http" and process.owner.finished, "reference-browser-receipt")
    return record


def restart(client, args, node_root, config, ordinal):
    ready = time.monotonic() + 6
    while time.monotonic() < ready:
        client.cancellation.check()
        require(time.monotonic() < client.deadline, "reference-restart-deadline")
        time.sleep(0.025)
    node = connect(client, args.node, node_root, config, TENANT, ordinal)
    client_profile(client, ordinal)
    return node


def run(args, report):
    metadata, records = fixtures(args.fixture_root)
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix="lsf-angular-reference-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        node_root, client_root, peer_root = (root / name for name in ("node", "client", "peer"))
        for directory in (node_root, client_root, peer_root):
            directory.mkdir(mode=0o700)
        client = QualificationClient(args.cli, client_root, cancellation, time.monotonic() + 1200)
        report["identity"] = {name + "Digest": file_digest(getattr(args, name), 1024 * MIB, cancellation, client.deadline)
                              for name in ("cli", "node", "compiler", "nodejs", "chrome")}
        report["builds"] = [{key: record[key] for key in ("name", "version", "componentDigest", "packageDigest", "assetsDigest", "sourceSnapshotDigest", "buildObservationDigest")}
                           for record in records.values()]
        report["reproducibility"] = metadata["reproducibility"]
        report["dependencyCompleteness"] = metadata["dependencyCompleteness"]
        original_fixture = tree_inventory(args.fixture_root, client)
        config, original, client.host, client.foreign = configure(client, node_root, args.fixture_root, args.compiler)
        node = peer = frontend = None
        report["shutdown"] = []
        try:
            stage(report, "protected-configuration")
            report["rejectedConfigurations"] = rejection_checks(client, args, config, original)
            before = tree_inventory(node_root, client)
            report["profile"] = command(client, args.node, config, "check-config", True)
            require(tree_inventory(node_root, client) == before, "reference-check-config-mutated-storage")
            peer = start_peer(client, peer_root)
            node = connect(client, args.node, node_root, config, TENANT, 1)
            profile = client_profile(client, 1)
            foreign = foreign_profile(client, profile)
            stage(report, "signed-two-build-admission")
            for omitted in ("no-publisher-evidence", "no-builder-evidence"):
                rejected = publish(client, args.fixture_root, "green", "reject-" + omitted, omitted, codes=(4,))
                require(rejected["category"] == "platform-failure", "reference-unenforced-admission")
            publications = {}
            for name in ("green", "blue"):
                published = publish(client, args.fixture_root, name)
                replay = publish(client, args.fixture_root, name)
                require(replay["replayed"] and not published["replayed"], "reference-publication-replay")
                publications[name] = published["publication"]["id"]
            report["publications"] = publications
            normal = client.config
            client.config = foreign
            try:
                require(client.call("web", "get", "--publication", publications["green"], codes=(4, 6))["category"] != "success", "reference-foreign-publication")
                require(not client.call("web", "operation", "publish-green")["outcomeKnown"], "reference-foreign-operation")
            finally:
                client.config = normal
            report["assetsBeforePreparation"] = assets(client, node, records, publications)
            require(report["assetsBeforePreparation"]["after"]["cache"]["entries"] == "0", "reference-assets-prepared-renderer")
            report["provider"] = configure_grant(client, node, publications)
            stage(report, "isolated-native-preparation")
            report["preparation"] = {}
            for name in ("green", "blue"):
                started = time.monotonic()
                prepare(client, publications[name], 1)
                report["preparation"][name] = {"millis": int((time.monotonic() - started) * 1000),
                                               "misses": native_cache_audit(client, records[name], "cache-miss")}
            deploy(client, records["green"], publications["green"])
            report["cold"] = invoke(client, records, publications, "reference-cold")
            report["warm"] = invoke(client, records, publications, "reference-warm")
            trigger(client, records, publications, "green", 1)
            stage(report, "real-public-browser")
            frontend = browser(client, args, records, publications, "public")
            browser_wait(client, frontend, "promoted")
            stage(report, "provider-cancellation-and-recovery")
            report["cancellations"] = cancellations(client, node, peer, records, publications)
            stage(report, "pinned-inflight-render-and-canary")
            report["canary"] = canary(client, node, peer, records, publications)
            trigger(client, records, publications, "blue", 2)
            signal_owned(frontend)
            browser_wait(client, frontend, "rolled-back")
            stage(report, "revoked-candidate-restart-and-rollback")
            report["revocation"] = publication_receipt(client.call("web", "revoke", "--publication", publications["blue"],
                "--operation-id", "revoke-reference-blue", "--expected-generation", "1"), "revoke-reference-blue")
            http(client, node, expected=403)
            report["beforeRestart"] = wait_idle(client)
            hits = native_cache_audit(client, records["green"], "cache-hit")
            high_watermark = max(int(hit["sequence"]) for hit in hits)
            stop(client, node)
            report["shutdown"].append(stopped_record(node))
            node = None
            native_before = {name: tree_inventory(node_root / name, client) for name in ("native-blobs", "native-receipts")}
            node = restart(client, args, node_root, config, 2)
            prepare(client, publications["blue"], 2, wait=5000, codes=(4,))
            prepare(client, publications["green"], 1)
            report["authenticatedCacheHits"] = [hit for hit in native_cache_audit(client, records["green"], "cache-hit")
                                                 if int(hit["sequence"]) > high_watermark]
            require(report["authenticatedCacheHits"], "reference-native-restart-cache-not-authenticated")
            promoted = report["canary"]["promoted"]
            rolled = receipt(change(client, "rollback", "reference-canary", promoted["revision"], "reference-rollback",
                "--target-generation", report["canary"]["historicalGeneration"]), "reference-rollback")
            require(rolled["state"].endswith("ROLLED_BACK"), "reference-rollback-state")
            replay = change(client, "rollback", "reference-canary", promoted["revision"], "reference-rollback",
                            "--target-generation", report["canary"]["historicalGeneration"])
            require(replay["data"]["replayed"] and replay["data"]["receipt"] == rolled, "reference-rollback-replay")
            report["rollback"] = rolled
            trigger(client, records, publications, "green", 3)
            signal_owned(frontend)
            report["publicBrowser"] = browser_result(client, frontend)
            frontend.close()
            frontend = None
            report["afterRollback"] = wait_idle(client)
            stop(client, node)
            report["shutdown"].append(stopped_record(node))
            node = None
            native_after = {name: tree_inventory(node_root / name, client) for name in ("native-blobs", "native-receipts")}
            require(native_before == native_after, "reference-native-cache-files-changed")
            stage(report, "real-authenticated-browser")
            replace_config(config, authenticate_config(original, client.host))
            node = restart(client, args, node_root, config, 3)
            prepare(client, publications["green"], 1)
            frontend = browser(client, args, records, publications, "authenticated")
            report["authenticatedBrowser"] = browser_result(client, frontend)
            frontend.close()
            frontend = None
            report["finalIdle"] = wait_idle(client)
            stop(client, node)
            report["shutdown"].append(stopped_record(node))
            node = None
            peer.stop()
            events = [json.loads(line) for line in bytes(peer.buffers[0]).splitlines()]
            stopped = events[-1]
            require(stopped["event"] == "stopped" and stopped["requests"] == stopped["authorized"]
                    and stopped["deniedConnections"] == 0 and stopped["held"] == stopped["closedHeld"] + stopped["releasedHeld"]
                    and stopped["closedHeld"] == 3 and stopped["releasedHeld"] == 1, "reference-peer-cleanup-or-authority")
            report["upstream"] = stopped
            report["peerReaped"] = peer.owner.finished and peer.closed
            peer = None
            require(tree_inventory(args.fixture_root, client) == original_fixture, "reference-fixture-mutated")
            require(client.calls <= 320, "reference-cli-process-count")
            report["cliProcesses"] = client.calls
        finally:
            client.node = None
            closed = []
            for process in (frontend, node, peer):
                if process is not None:
                    process.close()
                    closed.append({"processId": process.owner.process.pid,
                                   "reaped": process.owner.finished and process.closed})
            if closed:
                report["failureCleanup"] = closed
    report["temporaryOutputsRemoved"] = not root.exists()
    require(report["temporaryOutputsRemoved"], "reference-temporary-outputs-retained")
    report["passed"] = True
    stage(report, "complete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cli", "node", "compiler", "fixture-root", "nodejs", "chrome", "toolchain-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == "linux", "reference-linux-required")
    for name in ("cli", "node", "compiler", "fixture_root", "nodejs", "chrome", "toolchain_root"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    require(not args.output.exists(), "reference-output-exists")
    report = {"schemaVersion": "latent.angular.reference.workflow.v1", "passed": False, "lastStage": "inputs"}
    try:
        run(args, report)
    except (Exception, KeyboardInterrupt) as failure:
        report["failure"] = str(failure) if isinstance(failure, WorkflowError) else "reference-invalid-input-or-process"
        print("Angular reference failed: " + report["failure"], file=sys.stderr)
    write_json(args.output, report)
    print(bounded_receipt(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
