#!/usr/bin/env python3
"""Qualify actual Angular bytes on a protected T1 node through a separate CLI.

Uses the maintained Angular build/export and real, already-built binaries. No
synthetic build observation, guest admission grant, SDK transport, or provider
bootstrap is substituted. Requires Linux x86-64 and the approved AOT sandbox.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import (
    Client, WorkflowError, bounded_receipt, file_digest, require, stopped_record,
)
from tools.phase2_operator_scenario import audit_pages, connect, stop
from tools.phase3_web_qualification import (
    admission, failure_recovery, http_rendering, independent_publications,
    native_cache_audit, renewal, tenant_denial,
)
from tools.phase3_web_scenario import (
    MIB, TENANT, client_profile, configure_angular_node, deploy, fixture_metadata,
    foreign_profile, http_response, idle_inventory, invoke, prepare, tree_inventory,
)
from tools.run_security_profile_workflow import command, rejection_checks, replace_config


def restarted(client, args, node_root, config, original):
    ready_after = time.monotonic() + 6
    weakened = copy.deepcopy(original)
    del weakened["securityProfile"]
    replace_config(config, weakened)
    for name in ("check-config", "serve"):
        command(client, args.node, config, name, False)
    replace_config(config, original)
    before = tree_inventory(node_root, client)
    command(client, args.node, config, "check-config", True)
    require(tree_inventory(node_root, client) == before, "check-config-mutated-angular-storage")
    while time.monotonic() < ready_after:
        client.cancellation.check()
        require(time.monotonic() < client.deadline, "workflow-deadline")
        time.sleep(0.025)
    node = connect(client, args.node, node_root, config, TENANT, 2)
    client_profile(client, 2)
    return node


def run(args):
    metadata, records = fixture_metadata(args.fixture_root)
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix="lsf-angular-t1-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        node_root, client_root = root / "node", root / "client"
        for directory in (node_root, client_root):
            directory.mkdir(mode=0o700)
        client = Client(args.cli, client_root, cancellation, time.monotonic() + 1200)
        identity = {name + "Digest": file_digest(getattr(args, name), 1024 * MIB, cancellation, client.deadline)
                    for name in ("cli", "node", "compiler")}
        original_fixture = tree_inventory(args.fixture_root, client)
        config, original = configure_angular_node(client, node_root, args.fixture_root, args.compiler)
        rejected = rejection_checks(client, args, config, original)
        before = tree_inventory(node_root, client)
        profile = command(client, args.node, config, "check-config", True)
        require(tree_inventory(node_root, client) == before, "angular-check-config-created-storage")
        node = None
        shutdown = []
        try:
            node = connect(client, args.node, node_root, config, TENANT, 1)
            operator = client_profile(client, 1)
            foreign = foreign_profile(client, operator)
            publications = admission(client, args.fixture_root)
            tenant_denial(client, foreign, publications["angular"])
            dormant = idle_inventory(client)
            require(dormant["cache"]["entries"] == "0", "publication-eagerly-prepared-renderer")
            started = time.monotonic()
            prepare(client, publications["angular"], 1)
            preparation_millis = int((time.monotonic() - started) * 1000)
            prepared = idle_inventory(client)
            require(prepared["cache"]["entries"] == "1"
                    and int(prepared["cache"]["compiledImageBytes"]) > 0, "angular-native-cache-empty")
            cold_native = native_cache_audit(client, records["angular"], "cache-miss")
            deployment = deploy(client, records["angular"], publications["angular"], "deploy-angular")
            invoke(client, records["angular"], publications["angular"], "angular-cold")
            invoke(client, records["angular"], publications["angular"], "angular-warm")
            cancellations = failure_recovery(client, records["angular"], publications["angular"])
            deployment, renewed = renewal(client, args.fixture_root, records["angular"], publications["angular"], deployment)
            deployment, revision, revoked = independent_publications(client, records, publications, deployment)
            http = http_rendering(client, node, records["angular"], publications["angular"], deployment, revision)
            audit_pages(client, {"publish-angular", "publish-alternate", "renew-angular", "revoke-alternate"})
            before_restart = idle_inventory(client)
            stop(client, node)
            shutdown.append(stopped_record(node))
            node = None
            native_before = {name: tree_inventory(node_root / name, client)
                             for name in ("native-blobs", "native-receipts")}
            node = restarted(client, args, node_root, config, original)
            prepare(client, publications["angular"], 2)
            invoke(client, records["angular"], publications["angular"], "angular-restarted")
            warm_native = native_cache_audit(client, records["angular"], "cache-hit")
            prepare(client, publications["alternate"], 2, wait=5000, codes=(4,))
            body, _ = http_response(client, node, "alice.angular.test")
            require(b"ngh=" in body and b"Alice&lt;unsafe&gt;" in body, "angular-http-restart")
            after_restart = idle_inventory(client)
            stop(client, node)
            shutdown.append(stopped_record(node))
            node = None
            native_after = {name: tree_inventory(node_root / name, client)
                            for name in ("native-blobs", "native-receipts")}
            require(native_before == native_after, "native-cache-restart-identity")
            require(tree_inventory(args.fixture_root, client) == original_fixture, "actual-angular-fixture-mutated")
            require(client.calls <= 256, "angular-cli-call-bound")
            result = {"schemaVersion": "latent.angular.t1.workflow.v1", "passed": True,
                      "actualAngularBuild": True, "buildObservationDigest": metadata["buildObservationDigest"],
                      "reproducibility": metadata["reproducibility"], "identity": identity,
                      "profile": profile, "rejectedConfigCommands": rejected + 2,
                      "rejectedAdmissionCases": 3, "publications": publications, "renewal": renewed,
                      "independentRevocation": revoked, "preparationMillis": preparation_millis,
                      "dormant": dormant, "prepared": prepared, "beforeRestart": before_restart,
                      "afterRestart": after_restart, "cancellations": cancellations, "http": http,
                      "nativeCacheFilesUnchangedOnRestart": True, "cliProcesses": client.calls,
                      "nativeCacheMisses": cold_native, "authenticatedNativeCacheHits": warm_native,
                      "shutdown": shutdown, "temporaryOutputsRemoved": True}
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
    for name in ("cli", "node", "compiler", "fixture_root"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    require(sys.platform == "linux", "angular-t1-linux-required")
    print(run(args))


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, WorkflowError) else "fixture-or-process-error"
        print("Angular T1 workflow failed: " + reason, file=sys.stderr)
        sys.exit(1)
