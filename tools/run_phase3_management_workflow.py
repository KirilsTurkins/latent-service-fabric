#!/usr/bin/env python3
"""Finite real client/node/provider acceptance; this does not qualify Angular T1."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, WorkflowError, bounded_receipt, file_digest, require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_management_scenario import (
    HTTP_CONTRACT, TENANT, configure_provider_node, invoke_guest, publish_and_deploy_guests,
    start_http_fixture, stop_http_fixture,
)


HTTP_PROBE_ERRORS = dict(enumerate((
    "permission-denied", "uncertain", "invalid-url", "invalid-request",
    "request-too-large", "response-too-large", "deadline-exceeded", "cancelled",
    "budget-exhausted", "dns-failed", "tls-failed", "connection-failed", "unavailable",
), 10))


def probe(client, target, which, expected, text="", handle=0, *, stage="initial"):
    require(stage in {"initial", "restart"}, "provider-probe-stage")
    provider = "http" if target["contract"] == HTTP_CONTRACT else "blob"
    context = f"provider-{provider}-{stage}-case-{which}"
    try:
        result, value = invoke_guest(client, target, which, text, handle)
    except WorkflowError as failure:
        raise WorkflowError(f"{context}-{failure}") from None
    category = HTTP_PROBE_ERRORS.get(value) if provider == "http" and type(value) is int else None
    require(result["outcomeKnown"] and value == expected,
            f"{context}-http-error-{category}" if category else f"{context}-unexpected-result")
    return result["data"]["activationId"]


def inspection(client, targets, port):
    records = {}
    for name, target in targets.items():
        value = client.call("capability", "list", "--deployment", target["route"],
                            "--include-node-usage", "--page-size", "1")["data"]
        require(value["executionPermission"] is False and len(value["capabilities"]) == 1,
                "capability-sampled-page")
        records[name] = value
    for suffix, allowed in (("allowed", True), ("denied", False)):
        resource = client.directory / f"resource-{client.calls}-{suffix}.json"
        write_json(resource, {"kind": "http", "origin": {"scheme": "http", "host": "localhost", "port": port},
                              "method": "GET", "path": f"/{suffix}"})
        value = client.call("capability", "explain", "--deployment", targets["http"]["route"],
                            "--capability", "latent:http/client@0.2.0", "--operation", "send",
                            "--resource", resource)["data"]
        require(value["allowed"] is allowed and value["executionPermission"] is False,
                "capability-explain-not-admission")
    return records


def run(args):
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix="lsf-phase3-management-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        node_root, client_root, http_root = (root / name for name in ("node", "client", "http"))
        for directory in (node_root, client_root, http_root):
            directory.mkdir(mode=0o700)
        client = Client(args.cli, client_root, cancellation, time.monotonic() + 300)
        identity = {"cliDigest": file_digest(args.cli, 1024 * 1024 * 1024, cancellation, client.deadline),
                    "nodeDigest": file_digest(args.node, 1024 * 1024 * 1024, cancellation, client.deadline)}
        peer, port = start_http_fixture(client, http_root)
        node = None
        shutdown = []
        try:
            config = configure_provider_node(node_root, args.fixture_root, port)
            node = connect(client, args.node, node_root, config, TENANT, 1)
            targets = publish_and_deploy_guests(client, args.fixture_root, node, port)
            url = f"http://localhost:{port}/allowed"
            activations = [probe(client, targets["http"], which, 201 if which == 1 else 2201, url)
                           for which in (0, 1, 2)]
            activations.append(probe(client, targets["http"], 0, 10, f"http://localhost:{port}/denied"))
            activations.append(probe(client, targets["blob"], 0, 4))
            activations.append(probe(client, targets["blob"], 1, 1))
            activations.append(probe(client, targets["blob"], 2, 10))
            before = inspection(client, targets, port)
            stop(client, node)
            shutdown.append(stopped_record(node))
            restart_after = time.monotonic() + 6
            while time.monotonic() < restart_after:
                client.cancellation.check()
                require(time.monotonic() < client.deadline, "workflow-deadline")
                time.sleep(min(0.025, max(0, restart_after - time.monotonic())))
            node = connect(client, args.node, node_root, config, TENANT, 2)
            after = inspection(client, targets, port)
            require(all(before[name]["revision"] == after[name]["revision"] for name in targets),
                    "provider-restart-changed-selected-revision")
            activations.append(probe(client, targets["http"], 0, 2201, url, stage="restart"))
            activations.append(probe(client, targets["blob"], 0, 4, stage="restart"))
            revoked = client.call("policy", "revoke", "--id", "http-allow", "--operation-id", "revoke-http",
                                  "--expected-generation", targets["http"]["policyGeneration"])
            require(revoked["outcomeKnown"], "grant-revocation-uncertain")
            denied, result = invoke_guest(client, targets["http"], 0, url, codes=(4,))
            require(result is None and denied["category"] == "platform-failure", "revoked-grant-executed")
            stop(client, node)
            shutdown.append(stopped_record(node))
            node = None
            upstream = stop_http_fixture(peer)
            require(upstream == {"requests": 4, "authorized": 4, "unexpected": 0}, "provider-authority-or-hidden-retry")
            require(all(entry["record"]["report"]["providers"]["clean"] for entry in shutdown), "provider-reclamation")
            return {"schemaVersion": "latent.phase3.management.workflow.v1", "scope": "http-blob-provider-workflow",
                    "buildIdentity": identity, "clientCommands": client.calls, "activations": activations,
                    "upstream": upstream, "shutdown": shutdown, "grantsRevoked": True,
                    "selectedRevisionPreservedAcrossRestart": True, "angularT1Qualified": False}
        finally:
            if node is not None:
                node.close()
            peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == "linux", "provider-workflow-platform")
    args.cli = args.cli.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    args.fixture_root = args.fixture_root.resolve(strict=True)
    print(bounded_receipt(run(args)))


if __name__ == "__main__":
    try:
        main()
    except WorkflowError as failure:
        print(str(failure), file=sys.stderr)
        raise SystemExit(1)
    except (KeyError, OSError, TypeError, ValueError):
        print("provider-workflow-invalid-input-or-response", file=sys.stderr)
        raise SystemExit(1)
