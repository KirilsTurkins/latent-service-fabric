#!/usr/bin/env python3
"""Discard one real committed response in an explicitly selected test workspace.

This qualification harness is not packaged into the developer helper. It loads
the exact installed helper and uses its normal journal and public operator CLI;
only delivery of the selected successful response is interrupted. Run it as the
workspace's unprivileged Linux owner while its foreground controller is ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys


def mutation(arguments) -> tuple:
    # Client.control supplies its finite RPC allowance before the subcommand.
    # Inspect only that known prefix; never search arbitrary argument values.
    if arguments[:1] == ("--rpc-timeout-ms",):
        arguments = arguments[2:]
    if arguments[:2] in {("release", "publish"), ("release", "publish-package"), ("deployment", "apply")}:
        return tuple(arguments[:2])
    return ("invoke",) if arguments[:1] == ("invoke",) else ()


def run(args) -> dict:
    if sys.platform != "linux" or os.geteuid() == 0:
        raise ValueError("unprivileged Linux workspace owner required")
    helper_path = args.helper.absolute()
    if (not re.fullmatch(r"sha256:[a-f0-9]{64}", args.helper_sha256)
            or not re.fullmatch(r"test-[a-z0-9-]+", args.workspace)
            or helper_path.resolve() != helper_path):
        raise ValueError("exact helper and explicit test workspace required")
    for path in (helper_path, *helper_path.parents):
        metadata = path.lstat()
        if (metadata.st_uid not in {0, os.geteuid()} or metadata.st_mode & 0o022
                or stat.S_ISLNK(metadata.st_mode)):
            raise ValueError("helper ownership or path protection failed")
    with helper_path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if (len(raw) > 2 * 1024 * 1024
            or "sha256:" + hashlib.sha256(raw).hexdigest() != args.helper_sha256):
        raise ValueError("installed helper identity mismatch")
    # No repository checkout or replacement node/CLI is imported into the guest.
    sys.path.insert(0, str(helper_path))
    from tools.dev_workflow import client, common, helper, state

    root = state.workspace(helper.root_directory(), args.workspace)
    layout, _ = helper.installation(root)
    node = common.decode(layout.node.read_bytes())
    common.require(node["securityProfile"] == "local-experimental-v1",
                   "fault-probe-requires-explicit-local-test-profile")
    cli, journal = helper.client(root)
    common.require(journal.read()["pending"] is None, "recover-existing-operation-before-fault-probe")
    identity = {"schemaVersion": "latent.dev.node-fault-observation.v1", "environment": "node",
                "workspace": args.workspace, "node": node["nodeId"], "profile": node["securityProfile"],
                "helperSha256": args.helper_sha256, "qualificationComplete": False}
    if args.kind == "concurrent":
        # This deliberately separate actor uses observed preconditions and keeps
        # its own intent. It cannot update the developer controller's generation.
        with state.lock(root):
            common.require(not (root / "qualification-concurrent.json").exists(),
                           "inspect-original-concurrent-probe-before-any-new-mutation")
            prior = state.load(root, "last-deployment.json")
            observed = cli.call("deployment", "get", prior["deployment"], "--operation-snapshot")
            common.require(observed["outcomeKnown"] and observed["category"] == "success",
                           "concurrent-probe-observation-failed")
            current = observed["data"]
            generation = current["deployment"]["generation"]
            common.require(generation == prior["generation"], "concurrent-probe-already-conflicted")
            intent = {"id": "qualification-" + secrets.token_hex(16), "deployment": prior["deployment"],
                      "expectedGeneration": generation, "expectedStateVersion": current["stateVersion"]}
            state.atomic(root, "qualification-concurrent.json", intent)
            result = cli.call("deployment", "apply", root / "selected-deployment.json",
                              "--operation-id", intent["id"], "--expected-generation", generation,
                              "--expected-state-version", intent["expectedStateVersion"])
            common.require(result["outcomeKnown"] and result["category"] == "success",
                           "concurrent-probe-result-unconfirmed-inspect-original-identity")
            receipt = result["data"]["receipt"]
            common.require(receipt["operationId"] == intent["id"]
                           and int(receipt["objectGeneration"]) == int(generation) + 1,
                           "concurrent-probe-receipt-mismatch")
            state.atomic(root, "qualification-concurrent-result.json", result)
            common.require(state.load(root, "last-deployment.json") == prior,
                           "separate-actor-modified-controller-observation")
            return {**identity, "injection": "separate-actor-committed-deployment",
                    "remoteMutationCalls": 1, "intent": intent, "receipt": receipt,
                    "controllerGeneration": generation, "serverGeneration": receipt["objectGeneration"]}
    if args.kind == "unknown":
        with state.lock(root):
            pending = journal.begin("release", {"expectedGeneration": "0", "qualification": "never-dispatched"})
        return {**identity, "injection": "prepared-intent-never-dispatched", "pending": pending,
                "remoteMutationCalls": 0, "recoveryAttempted": False, "expiredReceiptTested": False}
    selected = {"release": {("release", "publish"), ("release", "publish-package")},
                "deployment": {("deployment", "apply")}, "invoke": {("invoke",)}}[args.kind]
    arguments = {}
    if args.kind == "invoke":
        arguments = common.decode(sys.stdin.buffer.read(1500001), 1500000)
    original = client.Client.call
    dispatched = []
    mutations = []

    def discard_response(self, *arguments, **options):
        command = mutation(arguments)
        if command:
            mutations.append(command)
        result = original(self, *arguments, **options)
        if command not in selected:
            return result
        common.require(not dispatched, "fault-probe-dispatched-more-than-once")
        common.require(result["outcomeKnown"] and result["category"] == "success",
                       "fault-probe-requires-real-success-before-discard")
        data = result["data"]
        operation_id = (data["activationId"] if args.kind == "invoke"
                        else data.get("operation", data.get("receipt", {}))["operationId"])
        dispatched.append({"id": operation_id, "kind": args.kind,
                           "resultSha256": common.digest(common.encode(result))})
        raise common.DevError("qualification-response-discarded-after-commit", uncertain=True)

    client.Client.call = discard_response
    try:
        try:
            helper.dispatch({"workspace": args.workspace,
                             "operation": "invoke" if args.kind == "invoke" else "deploy",
                             "arguments": arguments})
        except common.DevError as error:
            common.require(error.code == "qualification-response-discarded-after-commit"
                           and error.uncertain, "fault-probe-did-not-reach-selected-response")
        else:
            raise ValueError("selected mutation was not dispatched")
    finally:
        client.Client.call = original
    pending = journal.read()["pending"]
    common.require(len(dispatched) == 1 and pending is not None
                   and pending["id"] == dispatched[0]["id"] and pending["kind"] == args.kind,
                   "original-operation-was-not-retained")
    return {**identity, "injection": "discarded-real-successful-response",
            "remoteMutationCalls": len(mutations), "remoteMutationCommands": mutations,
            "selectedMutationCalls": len(dispatched), "discarded": dispatched[0],
            "pending": pending, "recoveryAttempted": False, "qualificationComplete": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--kind", choices=("release", "deployment", "invoke", "concurrent", "unknown"), required=True)
    result = run(parser.parse_args())
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
