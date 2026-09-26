#!/usr/bin/env python3
"""Overlap two real nodes and let one actual activation receipt expire.

This source qualification uses one unprivileged Linux account. It exercises
workspace ownership and node credentials, not isolation between WSL users or
authenticated clean-host installation. Expired original intents remain private.
"""
from __future__ import annotations

import argparse
import base64
import copy
import os
from pathlib import Path
import secrets
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_node_application_probe import stage_runtime
from tools.dev_recovery_fixture_probe import rejected
from tools.dev_secret_fixture_probe import author as secret_author
from tools.dev_workflow import backend, build, client, helper, paths, process, project, secret_fixture, snapshot, state
from tools.dev_workflow.common import DevError, decode, digest, encode, require
from tools.dev_workflow.node_output import PROVIDER_COUNTERS

TTL_MILLIS = 3000


def author(payload: Path, destination: Path, side: str) -> tuple[dict, dict]:
    require(side in {"a", "b"}, "isolation-probe-side")
    descriptor, fixtures = secret_author(payload, destination)
    own, foreign = "dev-only-" + side, "dev-only-" + ("b" if side == "a" else "a")
    # The two guest components have distinct observable results and publications.
    # Their private secrets are generated only after this public source snapshot.
    marker = 100 if side == "a" else 200
    component = destination / "app/src/lib.rs"
    original = component.read_text(encoding="utf-8")
    require(original.count("                    count\n") == 1, "secret-probe-source-contract-changed")
    component.write_text(original.replace("                    count\n", f"                    count + {marker}\n"),
                         encoding="utf-8", newline="\n")
    for selected in sorted((destination / "tests").glob("*.json")):
        raw = selected.read_bytes().replace(b"dev-allowed", own.encode()).replace(b"dev-other-workspace", foreign.encode())
        if selected.name.endswith("-expected.json") and decode(raw) == ["64"]:
            raw = encode([str(64 + marker)]).rstrip(b"\n")
        selected.write_bytes(raw)
    fixtures["secrets"]["references"][0]["name"] = own
    raw = encode(fixtures)
    (destination / "tests/secret-fixture.json").write_bytes(raw)
    cases = decode(paths.read(destination, "tests/scenarios.json"))
    for case in cases["scenarios"]:
        case["fixtures"][0]["identity"] = digest(raw)
    (destination / "tests/scenarios.json").write_bytes(encode(cases))
    return descriptor, fixtures


def clean_stop(connection, root: Path) -> dict:
    stopped = connection.call("down", {}, timeout=30)
    counters = stopped.get("providerShutdown", {})
    require(stopped.get("reaped") is True and stopped.get("cleanShutdown") is True
            and counters.get("clean") is True
            and all(type(counters.get(key)) is int and counters[key] == 0
                    for key in (*PROVIDER_COUNTERS, "secretGenerations", "secretReferences")),
            "overlapping-workspace-cleanup-unconfirmed")
    require(state.load(root, "lifecycle.json")["state"] == "stopped", "stopped-workspace-not-durable")
    return stopped


def run(payload: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-isolation-probe-required")
    output.mkdir(mode=0o700, parents=True)
    began, deadline = time.monotonic(), time.monotonic() + 900
    report = {"schemaVersion": "latent.dev.workspace-isolation-source-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "userBoundary": "same-unprivileged-linux-owner",
              "maximumSeconds": 900, "passed": False, "cleanup": "unconfirmed", "phase": "prepare", "workspaces": {}}
    owner = helper.root_directory()
    roots, connections, configurations, private_values = {}, {}, {}, []
    try:
        for side in ("a", "b"):
            root = state.workspace(owner, "test-" + side + "-" + secrets.token_hex(3), create=True)
            roots[side] = root
            descriptor, fixtures = author(payload, root / "Author spaces-\u00fc", side)
            excluded = secrets.token_hex(32).encode()
            paths.write_new(root / "Author spaces-\u00fc/app/.env", excluded)
            private_values.append(excluded)
            record, content = snapshot.observe(root / "Author spaces-\u00fc", descriptor["inputRoots"], tuple(descriptor["exclude"]))
            require(all(excluded not in raw for raw in content.values())
                    and all(".env" not in row["path"].split("/") for row in record["files"]),
                    "excluded-author-credential-transferred")
            (root / "snapshots").mkdir(mode=0o700)
            source = root / "snapshots" / record["identity"][7:]
            snapshot.materialize(source, record, content)
            trust = project.trust_identity(descriptor)
            state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
                         "source": str(source), "snapshot": record["identity"]})
            built = build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
            runtime = stage_runtime(root, supplied)
            # Normal supported retention configuration, set before the node's
            # first start. No host clock, receipt store or node code is replaced.
            node = decode(paths.read(root / "runtime/config", "node.json"))
            node.setdefault("retention", {})["terminalTtlMillis"] = TTL_MILLIS
            state.atomic(root / "runtime/config", "node.json", node)
            connection = backend.Backend({"kind": "linux", "python": str(Path(sys.executable).resolve()),
                "helper": str(supplied / "helper.pyz"), "helperSha256": runtime["helperSha256"]}, root.name, root)
            connections[side] = connection
            profile = connection.call("prepare-test", {"consent": True, "admission": "signed-fixture",
                                       "toolRoot": str(payload), "fixtures": fixtures})
            startup = connection.call("up", {}, timeout=180)
            connection.call("deploy", {})
            configuration = decode(paths.read(root / "runtime/config/client", "client.json"))
            configurations[side] = configuration
            private_values.extend(secret_fixture.values(root, fixtures["secrets"]))
            private_values.append(configuration["profiles"][0]["token"].encode())
            report["workspaces"][side] = {"workspace": root.name, "runtime": runtime, "source": record["identity"],
                "artifacts": built["artifacts"], "startup": startup, "profile": profile,
                "excludedAuthorCredentialsTransferred": False}
        report["phase"] = "overlap"
        require(configurations["a"]["profiles"][0]["token"] != configurations["b"]["profiles"][0]["token"],
                "workspace-credential-reused")
        require(len(set(private_values)) == len(private_values), "workspace-private-material-reused")
        require(report["workspaces"]["a"]["artifacts"]["component"] != report["workspaces"]["b"]["artifacts"]["component"],
                "distinct-workspace-guest-components-required")
        for side in ("a", "b"):
            require(all(c.call("status", {}).get("state") == "ready" for c in connections.values()),
                    "two-workspaces-not-concurrently-ready")
            tested = connections[side].call("test", {"environment": "node", "selection": []}, timeout=120)
            report["workspaces"][side]["tests"] = tested
            require(tested["passed"], "isolated-workspace-scenarios-failed")
            report["workspaces"][side]["deployment"] = state.load(roots[side], "last-deployment.json")
            own, _ = helper.client(roots[side], deadline=deadline)
            other, _ = helper.client(roots["b" if side == "a" else "a"], deadline=deadline)
            activation = tested["results"][-1]["activationId"]
            found = own.lookup("invoke", activation)
            missing = other.lookup("invoke", activation)
            require(found["category"] == "success" and found["outcomeKnown"] is True
                    and found["data"]["activationId"] == activation
                    and missing["category"] == "not-found" and missing["outcomeKnown"] is True,
                    "workspace-activation-result-not-isolated")
            report["workspaces"][side]["activationIsolation"] = {"original": found, "otherNode": missing}
        require(report["workspaces"]["a"]["tests"]["identity"]["node"]
                != report["workspaces"]["b"]["tests"]["identity"]["node"], "workspace-node-identity-reused")
        report["crossCredentials"] = {}
        for side, foreign in (("a", "b"), ("b", "a")):
            config = copy.deepcopy(configurations[side])
            config["profiles"][0]["token"] = configurations[foreign]["profiles"][0]["token"]
            state.atomic(roots[side], "foreign-credential.json", config)
            cli, _ = helper.client(roots[side], deadline=deadline)
            cross = client.Client(cli.binary, roots[side] / "foreign-credential.json", roots[side], deadline=deadline)
            selected = report["workspaces"][side]["deployment"]
            result = cross.call("deployment", "get", selected["deployment"], "--operation-snapshot")
            require(result["category"] == "platform-failure" and result["outcomeKnown"] is True
                    and result["error"]["code"] == "unauthenticated", "foreign-workspace-credential-not-rejected")
            report["crossCredentials"][side] = {"code": result["error"]["code"], "calls": 1,
                "credentialInArguments": False, "privateConfigurationExported": False}
        report["phase"] = "stop-restart-one-while-other-ready"
        other_deployment = state.load(roots["b"], "last-deployment.json")
        report["stopAWhileBReady"] = clean_stop(connections["a"], roots["a"])
        b_test = connections["b"].call("test", {"environment": "node", "selection": ["cold-read"]}, timeout=60)
        require(b_test["passed"] and state.load(roots["b"], "last-deployment.json") == other_deployment,
                "stopping-one-workspace-changed-another")
        report["bWhileAStopped"] = b_test
        connections["a"].call("up", {}, timeout=180)
        retained = connections["a"].call("test", {"environment": "node", "selection": ["cold-read"]}, timeout=60)
        require(retained["passed"] and state.load(roots["a"], "last-deployment.json")
                == report["workspaces"]["a"]["deployment"], "isolated-retained-restart-redeployed")
        report["retainedA"] = retained
        report["phase"] = "actual-receipt-expiry"
        root, connection = roots["a"], connections["a"]
        arguments = {"service": "greeting", "contract": "examples:greeting/api@1.0.0", "function": "read",
                     "mediaType": "application/vnd.latent.wit-values.v1+json",
                     "input": base64.b64encode(encode(["dev-only-a", False])).decode()}
        arguments["service"] = state.load(root, "project.json")["descriptor"]["service"]
        fault = process.run([sys.executable, "-B", str(Path(__file__).with_name("dev_node_fault_probe.py")),
            "--helper", str(supplied / "helper.pyz"), "--helper-sha256", runtime["helperSha256"],
            "--workspace", root.name, "--kind", "invoke"], root, timeout=60, maximum=262144, stdin=encode(arguments))
        require(fault.returncode == 0, "real-expiring-response-discard-failed")
        dropped = decode(fault.stdout)
        pending = state.load(root, "operations.json")["pending"]
        require(dropped["remoteMutationCalls"] == dropped["selectedMutationCalls"] == 1
                and pending["id"] == dropped["discarded"]["id"], "expiry-must-retain-one-real-original")
        cli, _ = helper.client(root, deadline=deadline)
        found = cli.lookup("invoke", pending["id"])
        require(found["category"] == "success" and found["outcomeKnown"] is True
                and found["data"]["activationId"] == pending["id"]
                and found["data"]["terminalState"] == "completed", "original-terminal-receipt-not-observed-before-expiry")
        began_wait = time.monotonic()
        observations = 0
        while True:
            require(time.monotonic() < min(deadline, began_wait + 20), "real-receipt-expiry-not-observed")
            time.sleep(0.2)
            expired = cli.lookup("invoke", pending["id"])
            observations += 1
            if expired["category"] != "success":
                break
        require(expired["category"] == "not-found" and expired["outcomeKnown"] is True,
                "expiry-must-be-actual-not-found-not-transport-failure")
        rejection = rejected(lambda: connection.call("recover", {}), "original-activation-receipt-unavailable-no-replay")
        blocked = rejected(lambda: connection.call("invoke", arguments), "recover-original-operation-before-new-mutation")
        require(state.load(root, "operations.json")["pending"] == pending, "expired-intent-was-replaced")
        other = connections["b"].call("test", {"environment": "node", "selection": ["cold-read"]}, timeout=60)
        require(other["passed"] and state.load(roots["b"], "last-deployment.json") == other_deployment,
                "unresolved-workspace-blocked-another-owner")
        report["expiry"] = {"terminalTtlMillis": TTL_MILLIS, "clockChanged": False, "receiptStoreEdited": False,
            "injection": dropped, "found": found, "expired": expired, "readOnlyPolls": observations,
            "waitSeconds": round(time.monotonic() - began_wait, 3), "recovery": rejection,
            "newMutation": blocked, "sameOriginalRetained": True, "otherWorkspaceUnaffected": other}
        require(time.monotonic() < deadline, "isolation-probe-deadline")
        report.update(passed=True, phase="complete")
    except BaseException as error:
        report["failure"] = error.code if isinstance(error, DevError) else type(error).__name__
        raise
    finally:
        report["shutdown"] = {}
        for side, connection in connections.items():
            try:
                if (roots[side] / "lifecycle.json").exists():
                    report["shutdown"][side] = clean_stop(connection, roots[side])
            except BaseException as error:
                report.update(passed=False, cleanupFailure=error.code if isinstance(error, DevError) else type(error).__name__)
        report["cleanup"] = ("owned-nodes-reaped-private-original-intent-and-workspaces-retained"
                             if not report.get("cleanupFailure") else "unconfirmed-private-workspaces-retained")
        report["retainedWorkspaces"] = {side: root.name for side, root in roots.items()}
        report["seconds"] = round(time.monotonic() - began, 3)
        raw = encode(report)
        require(all(value not in raw and digest(value).encode() not in raw for value in private_values),
                "private-workspace-material-in-public-receipt")
        state.atomic(output, "observation.json", report)
    require(report["passed"], "isolation-probe-cleanup-failed")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "source-node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True), args.output.absolute())
    print(encode({"passed": result["passed"], "cleanup": result["cleanup"]}).decode())
