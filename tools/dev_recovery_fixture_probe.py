#!/usr/bin/env python3
"""Discard real committed responses and recover via the installed helper protocol."""
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
from tools.dev_workflow import backend, build, client, helper, paths, process, project, snapshot, state
from tools.dev_workflow.common import DevError, decode, digest, encode, require


def rejected(call, code):
    try:
        call()
    except DevError as error:
        require(error.code == code, "unexpected-recovery-probe-rejection")
        return {"code": error.code, "uncertain": error.uncertain}
    raise DevError("recovery-probe-did-not-reject")


def run(payload: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-recovery-probe-required")
    output.mkdir(mode=0o700, parents=True)
    owner = helper.root_directory()
    root = state.workspace(owner, "test-recovery-" + secrets.token_hex(4), create=True)
    report = {"schemaVersion": "latent.dev.recovery-source-probe.v1", "publisherAuthenticated": False,
              "cleanHost": False, "qualificationComplete": False, "passed": False,
              "cleanup": "unconfirmed", "phase": "build", "lostResponses": {}}
    began = time.monotonic()
    deadline = began + 600
    connection = None
    try:
        entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
        template = payload / entry["path"]
        manifest = decode(paths.read(template, "template.json"))
        require(manifest["project"]["language"] == "rust", "rust-template-required")
        author = root / "author"
        project.scaffold(template, author, manifest, entry["identity"])
        descriptor = manifest["project"]
        record, content = snapshot.observe(author, descriptor["inputRoots"], tuple(descriptor["exclude"]))
        (root / "snapshots").mkdir(mode=0o700)
        source = root / "snapshots" / record["identity"][7:]
        snapshot.materialize(source, record, content)
        trust = project.trust_identity(descriptor)
        state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trust,
            "source": str(source), "snapshot": record["identity"]})
        built = build.execute(root, source, descriptor, payload, trusted=trust, cli=supplied / "bin/latent")
        report["artifacts"] = built["artifacts"]
        report["source"] = record["identity"]
        report["runtime"] = stage_runtime(root, supplied)
        connection = backend.Backend({"kind": "linux", "python": str(Path(sys.executable).resolve()),
            "helper": str(supplied / "helper.pyz"), "helperSha256": report["runtime"]["helperSha256"]}, root.name, root)
        report["phase"] = "signed-test-profile"
        report["profile"] = connection.call("prepare-test", {"consent": True, "admission": "signed-fixture", "toolRoot": str(payload)})
        report["startup"] = connection.call("up", {}, timeout=180)
        accepted, _ = build.accepted(root, state.load(root, "project.json"))
        case = decode(paths.read(accepted, descriptor["scenarios"][0]))["scenarios"][0]
        require(case["expect"]["category"] == "success", "successful-first-template-case-required")
        arguments = {key: case[key] for key in ("service", "contract", "function", "mediaType")}
        arguments["input"] = base64.b64encode(paths.read(accepted, case["input"])).decode()

        def fault(kind):
            require(time.monotonic() < deadline, "recovery-probe-deadline")
            command = [sys.executable, "-B", str(Path(__file__).with_name("dev_node_fault_probe.py")),
                "--helper", str(supplied / "helper.pyz"), "--helper-sha256", report["runtime"]["helperSha256"],
                "--workspace", root.name, "--kind", kind]
            result = process.run(command, root, timeout=min(180, deadline - time.monotonic()),
                                 stdin=encode(arguments) if kind == "invoke" else b"", maximum=262144)
            require(result.returncode == 0, "actual-mutation-loss-probe-failed")
            return decode(result.stdout)

        for kind in ("release", "deployment", "invoke"):
            report["phase"] = "lost-" + kind
            dropped = fault(kind)
            pending = state.load(root, "operations.json")["pending"]
            require(dropped["remoteMutationCalls"] == dropped["selectedMutationCalls"] == 1
                    and pending["id"] == dropped["discarded"]["id"], "one-original-mutation-required")
            blocked = rejected(lambda: connection.call("deploy", {}), "recover-original-operation-before-new-mutation")
            require(state.load(root, "operations.json")["pending"] == pending, "blocked-command-changed-pending-intent")
            try:
                recovered = connection.call("recover", {})
            except DevError:
                cli, _ = helper.client(root, deadline=deadline)
                report["failedRecoveryObservation"] = {"injection": dropped, "originalStatus": cli.lookup(kind, pending["id"])}
                raise
            require(state.load(root, "operations.json")["pending"] is None, "recovery-did-not-settle-original")
            history = state.load(root, "operations.json")["history"]
            require(len([row for row in history if row["id"] == pending["id"]]) == 1, "one-local-settlement-required")
            if kind == "invoke":
                require(recovered["data"]["activationId"] == pending["id"]
                        and recovered["data"]["phase"] in {"running", "committed", "effects_pending"}
                        and recovered["data"]["terminalState"] == "completed"
                        and "payload" not in recovered["data"], "lost-invoke-recovery-cannot-invent-result-bytes")
            else:
                settled = state.load(root, "last-publication.json" if kind == "release" else "last-deployment.json")
                require(settled["operation"] == pending["id"], "recovery-original-receipt-identity")
            no_pending = connection.call("recover", {})
            require(no_pending["state"] == "no-pending-operation"
                    and state.load(root, "operations.json")["history"] == history, "recovery-must-not-replay")
            report["lostResponses"][kind] = {"injection": dropped, "blockedNewMutation": blocked,
                "recovered": recovered, "secondRecovery": "no-pending-operation", "historyCount": len(history)}

        report["phase"] = "post-recovery-values-and-restart"
        report["tests"] = connection.call("test", {"environment": "node", "selection": [case["id"]]}, timeout=60)
        require(report["tests"]["passed"], "post-recovery-value-failed")
        selected = state.load(root, "last-deployment.json")
        down = connection.call("down", {})
        require(down["reaped"] and down["cleanShutdown"], "recovery-probe-clean-stop")
        connection.call("up", {}, timeout=180)
        report["retained"] = connection.call("test", {"environment": "node", "selection": [case["id"]]}, timeout=60)
        require(report["retained"]["passed"] and state.load(root, "last-deployment.json") == selected,
                "recovery-restart-must-retain-deployment")

        report["phase"] = "authority"
        layout, current = helper.installation(root)
        original_config = decode(paths.read(layout.client.parent, layout.client.name))
        report["authority"] = {}
        for kind in ("wrong-token", "wrong-tenant"):
            config = copy.deepcopy(original_config)
            config["profiles"][0]["token" if kind == "wrong-token" else "tenant"] = (
                secrets.token_hex(32) if kind == "wrong-token" else "another-tenant")
            path = root / (kind + ".json")
            state.atomic(root, path.name, config)
            foreign = client.Client(current / "bin/latent", path, root, deadline=deadline)
            activation = "qualification-" + secrets.token_hex(16)
            state.atomic(root, kind + "-intent.json", {"activationId": activation,
                "targetTenant": config["profiles"][0]["tenant"], "inputSha256": digest(paths.read(accepted, case["input"]))})
            result = foreign.call("invoke", "--service", case["service"], "--contract", case["contract"],
                "--function", case["function"], "--media-type", case["mediaType"],
                "--input", accepted / case["input"], "--activation-id", activation)
            report["authority"][kind] = {"category": result["category"], "outcomeKnown": result["outcomeKnown"],
                "code": result.get("error", {}).get("code"), "activationId": activation,
                "calls": 1, "credentialInArguments": False, "privateConfigurationExported": False}
            require(result["category"] == "platform-failure" and result["outcomeKnown"] is True
                    and result["error"]["code"] in {"unauthenticated", "permission-denied"}, "cross-authority-invocation-not-denied")

        report["phase"] = "concurrent-deployment"
        concurrent = fault("concurrent")
        conflict = rejected(lambda: connection.call("deploy", {}), "concurrent-deployment-change-no-overwrite")
        require(state.load(root, "last-deployment.json") == selected, "conflict-overwrote-controller-generation")
        cli, _ = helper.client(root, deadline=deadline)
        actual = cli.call("deployment", "get", selected["deployment"], "--operation-snapshot")
        require(actual["data"]["deployment"]["generation"] == concurrent["serverGeneration"], "conflict-overwrote-separate-actor")
        report["concurrent"] = {"injection": concurrent, "rejection": conflict, "controllerUnchanged": True, "actorUnchanged": True}

        report["phase"] = "unknown-receipt"
        unknown = fault("unknown")
        retained = state.load(root, "operations.json")["pending"]
        rejection = rejected(lambda: connection.call("recover", {}), "original-operation-unknown-or-expired-no-replay")
        blocked = rejected(lambda: connection.call("deploy", {}), "recover-original-operation-before-new-mutation")
        require(retained == state.load(root, "operations.json")["pending"], "unknown-original-intent-must-survive")
        report["unknown"] = {"injection": unknown, "recovery": rejection, "newMutation": blocked,
            "sameOriginalRetained": True, "expiredReceiptTested": False, "neverDispatchedQualificationIntent": True}
        report.update(passed=True, phase="complete")
    except BaseException as error:
        report["failure"] = error.code if isinstance(error, DevError) else type(error).__name__
        raise
    finally:
        try:
            if connection is not None and (root / "lifecycle.json").exists():
                stopped = connection.call("down", {}, timeout=30)
                require(stopped.get("reaped") is True and stopped.get("state") == "stopped"
                        and stopped.get("cleanShutdown") is True, "recovery-owned-cleanup-unconfirmed")
                report["shutdown"] = stopped
                report["cleanup"] = "owned-processes-reaped-private-state-retained"
        except BaseException as error:
            report.update(passed=False, cleanup="unconfirmed", cleanupFailure=error.code if isinstance(error, DevError) else type(error).__name__)
        report["retainedWorkspace"] = root.name
        report["seconds"] = round(time.monotonic() - began, 3)
        state.atomic(output, "observation.json", report)
    require(report["passed"], "recovery-probe-cleanup-failed")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "source-node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True), args.output.absolute())
    print(encode({"passed": result["passed"], "cleanup": result["cleanup"]}).decode())
