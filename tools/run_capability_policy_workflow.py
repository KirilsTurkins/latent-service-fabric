#!/usr/bin/env python3
"""Bounded real CLI/node policy lifecycle; no guest execution or load campaign."""
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
from tools.phase2_operator_process import Client, bounded_receipt, require, stopped_record, write_json
from tools.phase2_operator_scenario import NODE_ID, TOKEN, connect, stop


def scenario(client, directory):
    policy = directory / "policy.json"
    binding = directory / "binding.json"
    resource = directory / "resource.json"
    write_json(policy, {"formatVersion": 1, "tenant": "tests", "rules": []})
    write_json(binding, {"formatVersion": 1, "tenant": "tests",
                        "capability": "latent:secrets/reader@0.1.0", "providerProfile": "local-secrets-v1",
                        "configurationDigest": "sha256:" + "2" * 64, "configurationEpoch": 1,
                        "restriction": {"operations": []}})
    write_json(resource, {"kind": "secrets", "reference": "test-key"})
    apply = ("policy", "apply", "--id", "p", "--file", policy,
             "--operation-id", "create-p", "--expected-generation", "0")
    first = client.call(*apply)["data"]
    require(first["receipt"]["generation"] == "2", "initial-revision")
    require(client.call(*apply)["data"] == first, "exact-replay")
    require(client.call("policy", "get", "--id", "p")["data"]["policy"] == first["policy"], "get-record")
    client.call("policy", "--kind", "provider-binding", "apply", "--id", "binding", "--file", binding,
                "--operation-id", "create-binding", "--expected-generation", "0")
    explained = client.call("policy", "explain", "--id", "p", "--provider-binding", "binding",
                            "--service", "echo", "--publication-id", "publication:sha256:" + "1" * 64,
                            "--capability", "latent:secrets/reader@0.1.0", "--operation", "read",
                            "--resource", resource)["data"]
    require(explained["decision"] == "deny" and explained["executionPermission"] is False, "explanation-only")
    page = client.call("policy", "list", "--page-size", "1")["data"]
    require(len(page["policies"]) == 1 and page["nextPageToken"] is None, "bounded-page")
    client.call("policy", "revoke", "--id", "p", "--operation-id", "revoke-p", "--expected-generation", "2")
    receipt = client.call("policy", "operation", "--operation-id", "revoke-p")["data"]["receipt"]
    require(receipt["revoked"] is True and receipt["generation"] == "4", "revocation-receipt")
    require(client.call(*apply)["data"] == first, "historical-replay")
    require(client.call("policy", "get", "--id", "p")["data"]["policy"]["revoked"] is True, "replay-must-not-restore")
    unknown = client.call("policy", "operation", "--operation-id", "absent", codes=(6,))
    require(unknown["outcomeKnown"] is False and unknown["data"]["mutationOutcome"] == "unknown", "outcome-absence-is-unknown")
    return receipt


def run(args):
    with owned_cancellation() as cancellation:
        with tempfile.TemporaryDirectory(prefix="lsf-policy-workflow-") as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            config = directory / "node.json"
            write_json(config, {"formatVersion": 1, "dataDirectory": "data", "nodeId": NODE_ID,
                                "bind": "127.0.0.1:0", "workers": {"runtime": 1, "control": 1},
                                "shutdownGraceMillis": 5000,
                                "capabilityPolicies": {"formatVersion": 1, "maximumControlJobs": 2},
                                "credentials": [{"token": TOKEN, "subject": "workflow-operator",
                                                 "tenant": "tests", "role": "operator"}]})
            config.chmod(0o600)
            client = Client(args.cli.resolve(strict=True), directory, cancellation, time.monotonic() + 120)
            node = connect(client, args.node.resolve(strict=True), directory, config, "tests", 1)
            try:
                receipt = scenario(client, directory)
                stop(client, node)
                first = stopped_record(node)
                node = connect(client, args.node.resolve(strict=True), directory, config, "tests", 2)
                require(client.call("policy", "operation", "--operation-id", "revoke-p")["data"]["receipt"] == receipt, "restart-receipt")
                require(client.call("policy", "get", "--id", "p")["data"]["policy"]["revoked"] is True, "restart-revocation")
                stop(client, node)
                second = stopped_record(node)
                for stopped in (first, second):
                    policy = stopped["record"]["report"]["policies"]
                    require(policy["workCompleted"] and policy["activeJobs"] == 0
                            and policy["retainedReadOwners"] == 0, "policy-owner-cleanup")
                report = {"schemaVersion": "latent.capability-policy.workflow.v1", "passed": True,
                          "cliCalls": client.calls, "nodeStarts": 2, "guestInvokes": 0,
                          "replayedRevision": "2", "recoveredRevocation": "4", "ownersReaped": True}
            finally:
                node.close()
        require(not directory.exists(), "temporary-storage-retained")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    print(bounded_receipt(run(args)))


if __name__ == "__main__":
    main()
