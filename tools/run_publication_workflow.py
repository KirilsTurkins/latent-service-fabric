#!/usr/bin/env python3
"""Bounded real CLI/node publication migration test; Linux/Python 3.13.

Requires freshly signed, key-free export_publication_workflow_fixture output.
No registry, build, retry loop, benchmark campaign or persistent report directory.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Client, WorkflowError, bounded_receipt, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import TOKEN, configure_node, connect, receipt, stop
from tools.phase2_operator_canary import invoke, rollback_target
from tools.run_phase2_operator_workflow import build_identity, inventory


def publication(value, tenant):
    require(isinstance(value, dict) and value.get("tenant") == tenant
            and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", value.get("id", "")), "publication-scope-shape")
    return value


def record(client, selected):
    value = client.call("release", "lifecycle", "--publication", selected["id"])["data"]["status"]["record"]
    require(value["publication"] == selected, "lifecycle-publication")
    return value


def other_connection(client, primary, ordinal):
    profile = read_json(primary.config)
    profile["profiles"][0].update(tenant="other", token=TOKEN + "-OTHER")
    path = client.directory / f"other-{ordinal}.json"
    write_json(path, profile)
    client.config, client.node = path, primary.node


def manifest(fixture, work, tenant, name, selected, ordinal, weight=10000):
    value = read_json(fixture / name / "deployment.json")
    value["metadata"] = {"name": "blue" if tenant == "tests" else "other-blue", "tenant": tenant}
    value["spec"]["publication"] = selected["id"]
    value["spec"]["route"]["weight"] = weight
    path = work / f"manifest-{tenant}-{ordinal}.json"
    write_json(path, value)
    return path


def apply(client, path, operation):
    deployment_id = read_json(path)["metadata"]["name"]
    snapshot = client.call("deployment", "get", deployment_id, "--operation-snapshot", codes=(0, 6))["data"]
    current = snapshot.get("deployment")
    arguments = ("deployment", "apply", path, "--operation-id", operation,
                 "--expected-state-version", snapshot["stateVersion"],
                 "--expected-generation", current["generation"] if current else "0")
    return arguments, receipt(client.call(*arguments), operation)


def publish(client, fixture, tenant):
    rows = {}
    for name in ("blue", "green"):
        operation = "publish-" + name
        arguments = ("release", "publish-package", fixture / name / "package",
                     "--evidence", fixture / name / "evidence/index.json",
                     "--operation-id", operation, "--expected-generation", "0")
        result = client.call(*arguments)
        value, accepted = result["data"]["release"], result["data"]["operation"]
        selected = publication(value["publication"], tenant)
        require(result["outcomeKnown"] and accepted["publication"] == selected, "publish-association")
        require(client.call("release", "operation", operation)["data"]["receipt"] == accepted, "publish-operation")
        rows[name] = {"reference": selected, "component": value["digest"], "package": value["packageDigest"],
                      "receipt": accepted, "arguments": arguments}
    require(rows["blue"]["component"] == rows["green"]["component"], "fixture-wasm-must-match")
    require(rows["blue"]["package"] != rows["green"]["package"], "corrected-sbom-must-change-package")
    require(rows["blue"]["reference"] != rows["green"]["reference"], "publications-must-coexist")
    denial = client.call("release", "get", rows["blue"]["component"], codes=(2,))
    require(denial["category"] == "local-error" and denial["requestDispatched"] is False,
            "component-only-selector-rejected")
    return rows


def check_pin(client, metadata, input_path, activation, selected, component):
    pin = invoke(client, metadata, input_path, activation)
    require(pin["publicationId"] == selected["id"] and pin["releaseDigest"] == component, "invocation-publication")
    return pin


def replay_history(client, rows, operations):
    for row in rows.values():
        require(client.call(*row["arguments"])["data"]["operation"] == row["receipt"], "restart-publication-replay")
    for arguments, accepted in operations:
        require(client.call("deployment", "operation", accepted["operationId"])["data"]["receipt"] == accepted,
                "restart-deployment-operation")
        replay = client.call(*arguments)
        require(replay["data"]["replayed"] and replay["data"]["receipt"] == accepted, "restart-deployment-replay")
    deployment_id = "blue" if rows["blue"]["reference"]["tenant"] == "tests" else "other-blue"
    current = client.call("deployment", "get", deployment_id)["data"]["deployment"]
    require(current["publication"] == rows["blue"]["reference"], "replay-must-not-reinstall-candidate")


def rollout(client, other, rows, other_rows, fixture, work):
    selected = rows["green"]["reference"]
    candidate = read_json(fixture / "green/deployment.json")
    candidate["spec"]["publication"] = selected["id"]
    candidate["spec"]["route"]["weight"] = 1000
    path = work / "rollout-candidate.json"
    write_json(path, candidate)
    base = client.call("deployment", "get", "blue")["data"]["deployment"]
    arguments = ("rollout", "start", "coexist", "--base", "blue", "--expected-base-generation", base["generation"],
                 "--candidate", path, "--weights", "1000,10000", "--operation-id", "rollout-start", "--expected-revision", "0")
    started = receipt(client.call(*arguments), "rollout-start")
    target = rollback_target(client, "coexist", started)
    completed = receipt(client.call("rollout", "advance", "coexist", "--expected-revision", started["revision"],
                                    "--next-step", "1", "--operation-id", "rollout-complete"), "rollout-complete")
    status = client.call("rollout", "get", "coexist")["data"]["status"]
    for key, name in (("base", "blue"), ("candidate", "green")):
        require(status[key]["publicationId"] == rows[name]["reference"]["id"], "rollout-status-publication")
    for accepted in (started, completed):
        require(accepted["basePublicationId"] == rows["blue"]["reference"]["id"]
                and accepted["candidatePublicationId"] == selected["id"], "rollout-receipt-publications")
    before = record(client, selected)
    revoked = client.call("release", "revoke", "--publication", selected["id"], "--operation-id", "revoke-candidate",
                          "--expected-generation", before["generation"])["data"]["operation"]
    require(revoked["publication"] == selected and revoked["record"]["state"].endswith("REVOKED"), "candidate-revocation")
    require(record(client, rows["blue"]["reference"])["state"].endswith("ADMITTED"), "base-must-remain-eligible")
    require(record(other, other_rows["green"]["reference"])["state"].endswith("ADMITTED"), "other-tenant-not-revoked")
    # The exact current route still carries the revoked candidate: authority must win.
    metadata = read_json(fixture / "fixture.json")
    input_path = work / "input.json"
    denied = client.call("--rpc-timeout-ms", "5000", "invoke", "--service", metadata["service"], "--contract", metadata["contract"],
                         "--function", metadata["function"], "--activation-id", "revoked-candidate",
                         "--input", input_path, "--cpu-fuel", "1000000", "--memory-bytes", "4194304",
                         "--log-bytes", "1024", "--wall-time-ms", "5000", codes=(4,))
    require(denied["error"]["code"] == "permission-denied", "revoked-invocation-denied")
    rolled = receipt(client.call("rollout", "rollback", "coexist", "--expected-revision", completed["revision"],
                                  "--target-generation", target, "--operation-id", "rollout-back"), "rollout-back")
    require(client.call(*arguments)["data"]["receipt"] == started, "revoked-rollout-start-replay")
    return started, rolled, revoked


def renew(other, rows, fixture):
    selected = rows["green"]["reference"]
    before = record(other, selected)
    arguments = ("release", "renew-evidence", "--publication", selected["id"],
                 "--package-digest", rows["green"]["package"],
                 "--evidence", fixture / "green/renewed-evidence/index.json",
                 "--operation-id", "renew-green", "--expected-generation", before["generation"])
    renewed = other.call(*arguments)["data"]["operation"]
    require(renewed["publication"] == selected and int(renewed["record"]["generation"]) > int(before["generation"]),
            "renewal-publication-generation")
    require(renewed["record"]["evidenceRevisionDigest"] != before["evidenceRevisionDigest"], "renewal-must-replace-evidence")
    require(other.call(*arguments)["data"]["operation"] == renewed, "renewal-replay")
    return renewed



def check_audit(client, rows):
    count, previous, token = 0, 0, None
    seen_tokens = set()
    for pages in range(1, 17):
        arguments = ["audit", "query", "--scope", "tenant", "--page-size", "16"]
        if token:
            arguments.extend(("--page-token", token))
        data = client.call(*arguments)["data"]
        for row in data["records"]:
            sequence = int(row["sequence"])
            require(sequence > previous, "audit-page-order")
            previous = sequence
            value = row["data"].get("attempt") or row["data"].get("outcome")
            if value and value["identities"].get("rollout") == "coexist":
                identities = value["identities"]
                require(identities["basePublicationId"] == rows["blue"]["reference"]["id"]
                        and identities["candidatePublicationId"] == rows["green"]["reference"]["id"], "audit-publication-pair")
                count += 1
        token = data["page"]["nextPageToken"]
        if not token:
            require(count == 8, "audit-rollout-attempt-outcome-coverage")
            return pages
        require(isinstance(token, str) and len(token) <= 4096 and token not in seen_tokens, "audit-page-token")
        seen_tokens.add(token)
    raise WorkflowError("audit-profile-bound")


def wait_restart_floor(client):
    # Enforced admission intentionally rejects a restart before its last durable
    # five-second future clock floor. Wait without rewriting trusted time/state.
    ready = time.monotonic() + 5
    while time.monotonic() < ready:
        client.cancellation.check()
        require(time.monotonic() < client.deadline, "workflow-deadline")
        time.sleep(min(0.025, max(0, ready - time.monotonic())))


def run(args):
    fixture = args.fixture_root.resolve(strict=True)
    metadata = read_json(fixture / "fixture.json")
    require(metadata.get("publicationWorkflow") is True, "wrong-fixture-profile")
    original = inventory(fixture)
    # Prove the correction affects only the embedded inventory input.
    require((fixture / "blue/inputs/component.wasm").read_bytes() == (fixture / "green/inputs/component.wasm").read_bytes(), "fixture-wasm-differs")
    require((fixture / "blue/inputs/capsule.json").read_bytes() == (fixture / "green/inputs/capsule.json").read_bytes(), "fixture-metadata-differs")
    require(read_json(fixture / "blue/sbom-inputs.json") != read_json(fixture / "green/sbom-inputs.json"), "fixture-sbom-unchanged")
    with owned_cancellation() as cancellation:
        with tempfile.TemporaryDirectory(prefix="lsf-publication-workflow-") as temporary:
            work = Path(temporary)
            node_dir = work / "node"
            node_dir.mkdir(mode=0o700)
            deadline = time.monotonic() + 180
            client, other = [Client(args.cli.resolve(strict=True), work, cancellation, deadline) for _ in range(2)]
            identities = build_identity(args, cancellation, deadline)
            config = read_json(configure_node(node_dir, fixture, "tests"))
            config["credentials"].append({"token": TOKEN + "-OTHER", "tenant": "other", "subject": "other-operator", "role": "operator"})
            config_path = node_dir / "publication-node.json"
            write_json(config_path, config)
            input_path = work / "input.json"
            write_json(input_path, metadata["input"])
            node, shutdown = None, []
            try:
                node = connect(client, args.node.resolve(strict=True), node_dir, config_path, "tests", 1)
                other_connection(other, client, 1)
                all_rows, history, pins = {}, {}, []
                for active, tenant in ((client, "tests"), (other, "other")):
                    rows = publish(active, fixture, tenant)
                    all_rows[tenant], history[tenant] = rows, []
                    # Exercise both exact publications, then retain blue as the rollback base.
                    for index, name in enumerate(("blue", "green", "blue")):
                        path = manifest(fixture, work, tenant, name, rows[name]["reference"], index)
                        saved = apply(active, path, "apply-" + str(index))
                        require(saved[1]["publication"] == rows[name]["reference"], "apply-publication")
                        history[tenant].append(saved)
                        pins.append(check_pin(active, metadata, input_path, tenant + "-" + str(index),
                                              rows[name]["reference"], rows[name]["component"]))
                require(len({row["reference"]["id"] for rows in all_rows.values() for row in rows.values()}) == 4, "tenant-publications-must-differ")
                for name in ("blue", "green"):
                    require(all_rows["tests"][name]["package"] == all_rows["other"][name]["package"], "tenant-package-dedup")
                foreign = client.call("release", "get", "--publication", all_rows["other"]["blue"]["reference"]["id"], codes=(4, 6))
                missing = client.call("release", "get", "--publication", "publication:sha256:" + "0" * 64, codes=(4, 6))
                require(foreign["category"] == missing["category"] and foreign.get("error") == missing.get("error"), "foreign-existence-leak")
                stop(client, node)
                other.node = None
                shutdown.append(stopped_record(node))
                wait_restart_floor(client)
                node = connect(client, args.node.resolve(strict=True), node_dir, config_path, "tests", 2)
                other_connection(other, client, 2)
                for active, tenant in ((client, "tests"), (other, "other")):
                    replay_history(active, all_rows[tenant], history[tenant])
                rows, other_rows = all_rows["tests"], all_rows["other"]
                started, rolled, revoked = rollout(client, other, rows, other_rows, fixture, work)
                pins.append(check_pin(client, metadata, input_path, "restored-blue", rows["blue"]["reference"], rows["blue"]["component"]))
                renewed = renew(other, other_rows, fixture)
                require(record(client, rows["green"]["reference"])["state"].endswith("REVOKED"), "renewal-must-not-unrevoke-other-publication")
                # Restart after independent lifecycle changes and inspect original operations again.
                stop(client, node)
                other.node = None
                shutdown.append(stopped_record(node))
                wait_restart_floor(client)
                node = connect(client, args.node.resolve(strict=True), node_dir, config_path, "tests", 3)
                other_connection(other, client, 3)
                require(client.call("rollout", "operation", "coexist", "rollout-start")["data"]["receipt"] == started, "restart-rollout-history")
                require(client.call("release", "operation", "revoke-candidate")["data"]["receipt"] == revoked, "restart-revocation-history")
                require(other.call("release", "operation", "renew-green")["data"]["receipt"] == renewed, "restart-renewal-history")
                pins.append(check_pin(client, metadata, input_path, "restart-blue", rows["blue"]["reference"], rows["blue"]["component"]))
                require(record(client, rows["green"]["reference"])["state"].endswith("REVOKED"), "restart-lost-revocation")
                audit_pages = check_audit(client, rows)
                stop(client, node)
                other.node = None
                shutdown.append(stopped_record(node))
                node = None
                require(client.calls + other.calls <= 160 and time.monotonic() < deadline, "workflow-bound")
                require(inventory(fixture) == original, "fixture-mutated")
                result = {"schemaVersion": "latent.publication.workflow.v1", "passed": True,
                          "identities": identities, "publications": {tenant: {name: {key: row[key] for key in ("reference", "component", "package")}
                            for name, row in rows.items()} for tenant, rows in all_rows.items()},
                          "successfulInvocations": len(pins), "deniedInvocations": 1,
                          "cliProcesses": client.calls + other.calls, "auditPages": audit_pages, "shutdown": shutdown,
                          "temporaryOutputsRemoved": True, "syntheticTestEvidence": True,
                          "rollback": rolled, "renewal": renewed, "revocation": revoked}
            finally:
                client.node = other.node = None
                if node is not None:
                    node.close()
        cancellation.check()
    return bounded_receipt(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--source-commit", help="Exact commit supplied by the CI binary build owner")
    args = parser.parse_args()
    require(args.source_commit is None or re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "source-commit")
    print(run(args))


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, WorkflowError) else "fixture-or-process-error"
        print("Publication workflow failed: " + reason, file=sys.stderr)
        sys.exit(1)
