"""Focused source-built node checks inside the existing application-build owner.

This contributor probe reuses the shipped controller and public node APIs. It
does not produce an authenticated installation or clean-host qualification.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import time

from tools.dev_workflow import helper, node_scenarios, node_test_profile, paths, service, state
from tools.dev_workflow.common import DevError, HOST_ABI, decode, digest, encode, require
from tools.native_runtime import configuration
from tools.native_runtime.layout import Layout


def stage_runtime(root: Path, supplied: Path) -> dict:
    record = decode(paths.read(supplied, "source-node.json"))
    require(record.get("purpose") == "source-application-node-tests" and record.get("publisherAuthenticated") is False
            and record["engine"]["hostAbiProfile"] == HOST_ABI, "explicit-source-node-observation-required")
    require(digest(paths.read(supplied, "helper.pyz")) == record["helperSha256"], "source-node-helper-identity")
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
    release = runtime / "releases" / record["version"]
    paths.relative("releases/" + record["version"])
    (runtime / "releases").mkdir(mode=0o700)
    release.mkdir(mode=0o700)
    (release / "bin").mkdir(mode=0o700)
    for name in ("latent", "latentd", "latent-aot-compiler"):
        raw = paths.read(supplied, "bin/" + name, 256 * 1024 * 1024)
        require(digest(raw) == record["binaries"][name], "source-node-binary-identity")
        paths.write_new(release / "bin" / name, raw)
        (release / "bin" / name).chmod(0o700)
    paths.write_new(release / "release-source.json", encode(record))
    (runtime / "current").symlink_to("releases/" + record["version"])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    configuration.provision(Layout.local(runtime), (os.geteuid(), os.getegid()), configuration.LOCAL,
                            record, None, port, True)
    return record


def run(root: Path, supplied: Path, tools: Path, descriptor: dict, output: Path, *,
        fixtures: dict | None = None, selection: list[str] | None = None) -> dict:
    require(os.name == "posix" and os.geteuid() != 0 and root.name.startswith("test-"),
            "explicit-unprivileged-test-workspace-required")
    require(not output.exists(), "new-source-node-report-required")
    output.mkdir(mode=0o700, parents=True)
    report = {"schemaVersion": "latent.dev.application-node-probe.v1", "language": descriptor["language"],
        "publisherAuthenticated": False, "cleanHost": False, "qualificationComplete": False,
        "passed": False, "cleanup": "unconfirmed", "phase": "source-runtime"}
    uncertain = False
    began = time.monotonic()
    deadline = began + 900
    report["maximumSeconds"] = 900
    state.atomic(root, "source-node-probe.json", report)
    try:
        report["runtime"] = stage_runtime(root, supplied)
        report["phase"] = "signed-test-profile"
        report["profile"] = node_test_profile.prepare(root, descriptor, consent=True,
                                                      admission="signed-fixture", tool_root=tools, fixtures=fixtures)
        report["phase"] = "node-start"
        report["startup"] = service.start(root, supplied / "helper.pyz")
        report["phase"] = "publish-deploy"
        helper.deploy(root, deadline=deadline)
        report["phase"] = "common-scenarios"
        report["tests"] = node_scenarios.run(root, {"environment": "node", "selection": selection or []}, deadline=deadline)
        state.atomic(output, "node-tests.json", report["tests"])
        require(report["tests"]["passed"], "source-node-application-scenarios-failed")
        selected = state.load(root, "last-deployment.json")
        report["phase"] = "retained-restart"
        down = service.request(root, "down", timeout=20)
        require(down["state"] == "stopped" and down.get("reaped") is True and down.get("cleanShutdown") is True,
                "source-node-clean-shutdown-required")
        service.start(root, supplied / "helper.pyz")
        report["retained"] = node_scenarios.run(root, {"environment": "node", "selection": [report["tests"]["selection"][0]]},
                                                deadline=deadline)
        require(report["retained"]["passed"] and state.load(root, "last-deployment.json") == selected,
                "source-node-retained-invocation-must-not-redeploy")
        report["retainedDeployment"] = selected
        require(time.monotonic() < deadline, "source-node-probe-deadline")
        report.update(passed=True, phase="complete")
    except BaseException as error:
        uncertain = isinstance(error, DevError) and error.uncertain
        report["failure"] = error.code if isinstance(error, DevError) else type(error).__name__
        raise
    finally:
        try:
            if (root / "lifecycle.json").exists():
                try:
                    down = service.request(root, "down", timeout=20)
                except (FileNotFoundError, ConnectionRefusedError):
                    down = service.disconnected(root)
                require(down["state"] == "stopped" and down.get("reaped") is True,
                        "source-node-owned-cleanup-unconfirmed")
                report["shutdown"] = down
            pending = state.load(root, "operations.json")["pending"] if (root / "operations.json").exists() else None
            report["pendingOperation"] = {key: pending[key] for key in ("kind", "id", "requestDigest")} if pending else None
            if pending and (root / "last-operation-observation.json").exists():
                observation = state.load(root, "last-operation-observation.json")
                if observation["id"] == pending["id"] and observation["kind"] == pending["kind"]:
                    report["operationObservation"] = observation
            if uncertain or pending or report.get("tests", {}).get("cleanup") == "client-cleanup-unconfirmed-node-retained":
                report.update(passed=False, cleanup="unconfirmed-private-workspace-retained")
            else:
                report["cleanup"] = "owned-node-and-client-processes-reaped"
        except BaseException as error:
            report.update(passed=False, cleanup="unconfirmed-private-workspace-retained",
                          cleanupFailure=error.code if isinstance(error, DevError) else type(error).__name__)
        report["seconds"] = round(time.monotonic() - began, 3)
        state.atomic(root, "source-node-probe.json", report)
        state.atomic(output, "probe.json", report)
    require(report["passed"], "source-node-probe-cleanup-unconfirmed")
    return report
