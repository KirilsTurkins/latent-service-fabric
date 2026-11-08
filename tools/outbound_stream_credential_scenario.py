"""Explicit real-node management handoff qualification; no installed stream proof.

Run only with selected native executables and a new protected work directory.
The local-experimental node owns actual durable policy/audit catalogs. Provider
and publication identifiers are metadata fixtures, not installed/signed claims.
A controller withholds one successful apply response; it never fakes a receipt,
replays a mutation or simulates the native authenticator. Bearers are replaced
across a clean restart, not through live credential rotation or token expiry.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import secrets
import sys
import time

from tools import outbound_stream_operator as stream
from tools.build_process_signals import owned_cancellation
from tools.dev_workflow import paths, process, state
from tools.dev_workflow.client import Client, successful
from tools.dev_workflow.common import DevError, MAX_DOCUMENT, decode, encode, require
from tools.phase2_operator_process import Process, stopped_record

NODE = "stream-credential-qualification"
TENANT = "examples"
CASES = ("first-binding", "first-policy", "revocation")
MAX_CALLS = 64
SCHEMA = "latent.stream-credential-qualification.v1"


class ObservedClient(Client):
    """Actual CLI calls, with one explicitly armed post-success loss seam."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attempts = 0
        self.mutations = 0
        self.withhold_kind = None
        self.withheld = False
        self.last_status = None

    def call(self, *arguments, **kwargs):
        require(self.attempts < MAX_CALLS, "credential-scenario-call-bound")
        self.attempts += 1
        mutation = "apply" in arguments
        self.mutations += int(mutation)
        result = super().call(*arguments, **kwargs)
        self.last_status = (result.get("category"), (result.get("error") or {}).get("code"),
                            result.get("outcomeKnown"))
        if mutation and self.withhold_kind is not None:
            kind = arguments[arguments.index("--kind") + 1]
            if kind == self.withhold_kind:
                successful(result)
                self.withhold_kind = None
                self.withheld = True
                raise DevError("credential-scenario-confirmation-withheld", uncertain=True)
        return result


def configuration(token):
    return {
        "formatVersion": 1, "dataDirectory": "data", "nodeId": NODE, "bind": "127.0.0.1:0",
        "workers": {"runtime": 1, "control": 1},
        "cells": [{"class": "standard", "capacity": 1, "queueCapacity": 2,
                   "maximumMemoryBytes": 67108864}],
        "execution": {"maximumCpuFuel": 10000000000, "maximumWallTimeMillis": 5000,
                      "maximumLogBytes": 16384},
        "cache": {"entries": 2, "preparations": 1}, "catalogs": {"releaseEntries": 8, "deployments": 8},
        "retention": {"terminalEntries": 32, "terminalTtlMillis": 30000}, "shutdownGraceMillis": 5000,
        "audit": {"mode": "durable", "records": 256, "diskBytes": 4194304,
                  "queuedOperations": 8, "queryOwners": 2},
        "budgetProfile": {"mode": "phase3", "maximumOutboundRequests": 8,
                          "maximumBlobReadBytes": 65536, "maximumBlobWriteBytes": 65536},
        "capabilityPolicies": {"formatVersion": 1, "maximumControlJobs": 2},
        "credentials": [{"token": token, "subject": "workflow-operator", "tenant": TENANT,
                         "role": "operator"}],
    }


def specification():
    return {"node": NODE, "tenant": TENANT, "provider": {
        "id": "streams", "tenant": TENANT, "service": "stream-host",
        "capability": stream.CAPABILITY, "profile": stream.PROFILE,
        "configurationDigest": "sha256:" + "a" * 64, "configurationEpoch": "1"},
        "consumer": "examples/mail", "publication": "publication:sha256:" + "b" * 64,
        "principal": {"kind": "administrator", "subject": "workflow-operator"},
        "destination": {"host": "127.0.0.1", "port": 32123, "transport": "tcp"},
        "bindingId": "stream-installed", "policyId": "stream-allow"}


def operator(root, client):
    value = specification()
    return stream.StreamOperator(root, client, **{key: item for key, item in value.items()
        if key not in {"bindingId", "policyId"}}, binding_id=value["bindingId"], policy_id=value["policyId"])


def snapshot(root):
    return {name: stream._private_read(root / name, MAX_DOCUMENT) if (root / name).exists() else None
            for name in ("stream-operator-owner.json", "operations.json", "stream-policy-receipts.json")}


def refused(action, code=None):
    try:
        action()
    except DevError as error:
        require(error.uncertain and (code is None or error.code == code), "credential-scenario-wrong-refusal")
    else:
        raise DevError("credential-scenario-missing-refusal")


def start(binary, root, cancellation, deadline):
    node = Process([str(binary), "serve", "--config", str(root / "node.json")],
                   root, process.environment(root), cancellation, maximum=262144)
    try:
        record = node.line(min(deadline, time.monotonic() + 15))
        require(record.get("event") == "started" and isinstance(record.get("endpoint"), str)
                and re.fullmatch(r"127\.0\.0\.1:[1-9][0-9]{0,4}", record["endpoint"])
                and not record.get("providers"), "credential-scenario-node-startup")
        return node, record["endpoint"]
    except BaseException:
        node.close()
        raise


def inspect_node(client):
    # Management reachability is not activation or provider readiness. Preserve
    # the actual health observation instead of assuming an idle node is ready.
    result = successful(client.call("node", "get", NODE))
    inventory = result.get("inventory", {})
    require(inventory.get("node", {}).get("id") == NODE
            and type(inventory.get("health", {}).get("ready")) is bool,
            "credential-scenario-node-identity")
    return inventory["health"]["ready"]


def stop(node):
    node.stop()
    stopped_record(node)  # Requires the real clean status, exited leader and finished group owner.


def run_case(case, node_binary, cli, root, cancellation, deadline):
    require(case in CASES, "credential-scenario-case")
    paths.new_directory(root)
    owner_root = root / "operator"
    paths.new_directory(owner_root)
    old_token, new_token, foreign_token = (secrets.token_urlsafe(32) for _ in range(3))
    settings = configuration(old_token)
    paths.write_new(root / "node.json", encode(settings))
    paths.write_new(root / "specification.json", encode(specification()))
    checked = process.run([str(node_binary), "check-config", "--config", str(root / "node.json")],
                          root, timeout=min(15, deadline - time.monotonic()), maximum=65536)
    checked_profile = decode(checked.stdout, 65536)
    require(checked.returncode == 0 and checked_profile.get("profile") == "local-experimental-v1"
            and checked_profile.get("protectedCredentialFile") is True, "credential-scenario-config-refused")
    node, endpoint = start(node_binary, root, cancellation, deadline)
    try:
        profile = {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{
            "name": "operator", "endpoint": "http://" + endpoint, "tenant": TENANT,
            "token": old_token, "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 5000}]}
        paths.write_new(root / "old.json", encode(profile))
        old = ObservedClient(cli, root / "old.json", owner_root, deadline=deadline)
        observed_readiness = [inspect_node(old)]
        control = operator(owner_root, old)
        if case == "revocation":
            control.grant()
        old.withhold_kind = "provider-binding" if case == "first-binding" else "policy"
        refused(control.revoke if case == "revocation" else control.grant,
                "credential-scenario-confirmation-withheld")
        require(old.withheld, "credential-scenario-no-dispatched-loss")
        pending = copy.deepcopy(control.journal.read()["pending"])
        before = snapshot(owner_root)
        attempted_mutations = old.mutations
        try:
            control.grant()
        except DevError as error:
            require(error.code == "recover-original-operation-before-new-mutation",
                    "credential-scenario-pending-fence")
        else:
            raise DevError("credential-scenario-pending-fence")
        require(snapshot(owner_root) == before and old.mutations == attempted_mutations,
                "credential-scenario-pending-changed")
        stop(node)
        # Same store and endpoint; explicit stopped-node credential replacement.
        settings["bind"] = endpoint
        settings["credentials"][0]["token"] = new_token
        settings["credentials"].append({"token": foreign_token, "subject": "foreign-operator",
                                        "tenant": "foreign", "role": "operator"})
        state.atomic(root, "node.json", settings)
        node, restarted_endpoint = start(node_binary, root, cancellation, deadline)
        require(restarted_endpoint == endpoint, "credential-scenario-endpoint-changed")
        profile["profiles"][0]["token"] = new_token
        paths.write_new(root / "new.json", encode(profile))
        replacement = ObservedClient(cli, root / "new.json", owner_root, deadline=deadline)
        observed_readiness.append(inspect_node(replacement))
        denied = old.call("node", "get", NODE)
        require(denied["outcomeKnown"] is True and denied["category"] == "platform-failure"
                and denied.get("error", {}).get("code") == "unauthenticated",
                "credential-scenario-old-bearer-not-rejected")
        refused(control.recover)
        require(snapshot(owner_root) == before, "credential-scenario-denied-recovery-changed-state")
        profile["profiles"][0]["token"] = foreign_token
        paths.write_new(root / "foreign.json", encode(profile))
        foreign = ObservedClient(cli, root / "foreign.json", owner_root, deadline=deadline)
        # A node operator may inspect global node identity, but another tenant
        # cannot obtain this original operation receipt. Absence stays unknown.
        refused(lambda: control.adopt_client(foreign, preserve_pending=True))
        require(snapshot(owner_root) == before and foreign.mutations == 0 and foreign.attempts > 0
                and (foreign.last_status in {("platform-failure", "permission-denied", True),
                                             ("platform-failure", "unauthenticated", True)}
                     or foreign.attempts == 2 and foreign.last_status == ("not-found", None, False)),
                "credential-scenario-foreign-handoff-changed-state")
        reads = replacement.attempts
        result = control.adopt_client(replacement, preserve_pending=True)
        after = snapshot(owner_root)
        require(result.get("recoveryRequired") is True and result.get("executionPermission") is False
                and replacement.attempts - reads == 4 and replacement.mutations == 0
                and after["operations.json"] == before["operations.json"]
                and after["stream-policy-receipts.json"] == before["stream-policy-receipts.json"],
                "credential-scenario-handoff-not-preserved")
        # Exercise the actual source command and selected native CLI on restart.
        arguments = [sys.executable, "-m", "tools.outbound_stream_operator", "recover", "--cli", str(cli),
            "--client-config", str(root / "new.json"), "--state-dir", str(owner_root),
            "--specification", str(root / "specification.json")]
        completed = process.run(arguments, Path(__file__).resolve().parents[1],
                                timeout=min(30, deadline - time.monotonic()), maximum=65536)
        require(all(value.encode() not in completed.stdout + completed.stderr for value in
                    (old_token, new_token, foreign_token, str(root))), "credential-scenario-output-not-redacted")
        recovered = decode(completed.stdout, 65536)
        require(completed.returncode == 0 and recovered.get("status") == "completed"
                and recovered.get("command") == "recover"
                and recovered["result"]["data"]["receipt"]["operationId"] == pending["id"],
                "credential-scenario-source-recovery-failed")
        fresh = operator(owner_root, replacement)
        require(fresh.journal.read()["pending"] is None, "credential-scenario-recovery-not-settled")
        if case != "revocation":
            fresh.grant()
        fresh.revoke()
        mutations = replacement.mutations
        fresh.revoke()
        require(replacement.mutations == mutations and fresh._records()["policy:stream-allow"]
                ["document"]["rules"][0]["effect"] == "deny", "credential-scenario-cleanup-not-idempotent")
        stop(node)
        return {"case": case, "status": "passed", "handoffReadCalls": 4, "handoffMutations": 0,
                "originalPendingPreserved": True, "oldBearerRejected": True, "foreignTenantHandoffRefused": True,
                "sourceCommandRecovery": True, "durableDenyConfirmed": True, "cleanNodeStops": 2,
                "nodeReadyAtInspection": observed_readiness}
    finally:
        node.close()


def run(node, cli, root):
    require(sys.platform == "linux", "credential-scenario-linux-required")
    node, cli, root = node.absolute(), cli.absolute(), root.absolute()
    binaries = {name: paths.digest_file(path.parent, path.name, 256 * 1024 * 1024)
                for name, path in (("node", node), ("cli", cli))}
    require(all(size > 0 for _, size in binaries.values()), "credential-scenario-empty-executable")
    paths.new_directory(root)
    deadline = time.monotonic() + 90
    with owned_cancellation() as cancellation:
        cases = [run_case(case, node, cli, root / case, cancellation, deadline) for case in CASES]
    require(binaries == {name: paths.digest_file(path.parent, path.name, 256 * 1024 * 1024)
                         for name, path in (("node", node), ("cli", cli))}, "credential-scenario-executable-changed")
    return {"schemaVersion": SCHEMA, "status": "passed", "cases": cases,
            "binaries": {name: {"sha256": sha, "size": size} for name, (sha, size) in binaries.items()},
            "realNode": True, "profile": "local-experimental-v1", "injectedPostSuccessLoss": True,
            "credentialReplacement": "stopped-node-restart", "installedStreamProvider": False,
            "streamExecution": False, "productionReadiness": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, type=Path)
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.node, args.cli, args.work_dir)
    except Exception:
        # Never print exception text, native stderr, credentials or host paths.
        print(json.dumps({"schemaVersion": SCHEMA, "status": "failed", "productionReadiness": False}),
              file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
