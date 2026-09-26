#!/usr/bin/env python3
"""Drive the actual watch controller through edits, owned failures and revision pins."""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import secrets
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_node_application_probe import stage_runtime
from tools.dev_watch_fixture_inputs import author, edit
from tools.dev_watch_inflight import Inflight
from tools.dev_watch_revocation import run as revoked_restore
from tools.dev_workflow import backend, build_cache, build_client, build_control, helper, paths, project, state, watch
from tools.dev_workflow.common import DevError, decode, digest, encode, require


class Complete(Exception):
    """End this finite driver after all real controller observations are captured."""


class DrivenBackend(backend.Backend):
    def __init__(self, *args):
        super().__init__(*args)
        self.on_build_tick = lambda: None

    def call(self, operation, arguments, *, check=None, **options):
        def observe():
            if operation == "build":
                self.on_build_tick()
            if check is not None:
                check()
        return super().call(operation, arguments, check=observe, **options)


def run(payload: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(),
            "new-unprivileged-linux-watch-probe-required")
    output.mkdir(mode=0o700, parents=True)
    owner = helper.root_directory()
    root = state.workspace(owner, "test-watch-" + secrets.token_hex(3), create=True)
    host = root.parent.parent / ("host-watch-" + secrets.token_hex(3))
    paths.new_directory(host)
    control = state.workspace(host, root.name, create=True)
    source = host / "Author spaces-\u00fc"
    descriptor = author(payload, source)
    state.atomic(control, "trust.json", {"project": str(source), "recipe": project.trust_identity(descriptor)})
    began, deadline = time.monotonic(), time.monotonic() + 900
    report = {"schemaVersion": "latent.dev.watch-source-probe.v1", "publisherAuthenticated": False,
        "cleanHost": False, "qualificationComplete": False, "passed": False, "cleanup": "unconfirmed",
        "phase": "build-cache-preparation", "events": [], "observations": {}, "deployments": []}
    connection, inflight = None, None
    stage = "initial"
    try:
        report["runtime"] = runtime = stage_runtime(root, supplied)
        connection = DrivenBackend({"kind": "linux", "python": str(Path(sys.executable).resolve()),
            "helper": str(supplied / "helper.pyz"), "helperSha256": runtime["helperSha256"]}, root.name, control)
        # Warm B's exact source/tool/recipe cache before A starts. The later
        # source edit must still transfer/revalidate/package those exact bytes.
        edit(source, 201)
        report["warmB"] = build_client.run(control, connection, source, str(payload))
        edit(source, 101)
        report["initialA"] = build_client.run(control, connection, source, str(payload))
        report["profile"] = connection.call("prepare-test", {"consent": True, "admission": "trusted-local"})
        report["startup"] = connection.call("up", {}, timeout=180)
        report["phase"] = "watch"
        inflight = Inflight(root, descriptor, deadline)

        def current_value(marker):
            result = connection.call("invoke", {"service": descriptor["service"],
                "contract": "examples:greeting/api@1.0.0", "function": "value",
                "mediaType": "application/vnd.latent.wit-values.v1+json", "input": "W10="})
            selected = state.load(root, "last-deployment.json")
            require(result["category"] == "success" and result["outcomeKnown"] is True
                    and decode(base64.b64decode(result["data"]["payload"]["data"], validate=True)) == [marker]
                    and result["data"]["resolvedRevision"]["publicationId"] == selected["publication"],
                    "last-working-watch-deployment-not-callable")
            return result

        def tick():
            nonlocal stage
            require(time.monotonic() < deadline, "watch-probe-deadline")
            if stage != "slow":
                return
            active = build_control.status(root)
            if active.get("state") != "running" or active.get("attempt") is None:
                return
            ready = root / "builds" / active["attempt"] / "source/build-cache/qualification-ready.txt"
            if not ready.exists():
                return
            pid = int(paths.read(ready.parent, ready.name, 20))
            require(pid > 1, "slow-recipe-child-identity")
            observed = report["observations"]["rapidEdits"] = {"build": active, "childPid": pid,
                "delay": "owned-recipe-child-before-rust-compiler", "maximumDelaySeconds": 30}
            edit(source, 401)
            observed["intermediate"] = build_client.selection(source)[1]
            edit(source, 501, expected=999)
            observed["latest"] = build_client.selection(source)[1]
            stage = "superseding"
        connection.on_build_tick = tick

        def emit(event):
            nonlocal stage
            require(len(report["events"]) < 24, "watch-probe-event-bound")
            report["events"].append(event)
            kind = event["event"]
            if kind == "deployed":
                deployed = event["deployment"]
                report["deployments"].append(deployed)
                if stage == "b":
                    report["observations"]["inflight"] = inflight.switched(report["deployments"][0], deployed)
                    require(event["build"]["attempt"] == report["warmB"]["attempt"], "exact-warm-b-cache-not-reused")
                elif stage == "latest":
                    require(deployed["source"] == report["observations"]["rapidEdits"]["latest"],
                            "obsolete-source-deployed-after-rapid-edits")
                else:
                    require(stage == "initial", "unexpected-watch-deployment")
                return
            if kind == "post-deploy-tests":
                require(event["rollbackPerformed"] is False and event["report"]["selection"] == ["value"],
                        "focused-tests-or-no-rollback-contract-changed")
                if stage == "initial":
                    require(event["passed"], "initial-watch-a-test-failed")
                    inflight.start()
                    edit(source, 201)
                    stage = "b"
                elif stage == "b":
                    require(event["passed"], "new-watch-b-test-failed")
                    report["observations"]["bValue"] = current_value(201)
                    edit(source, 301, compiler_error=True)
                    stage = "compiler-error"
                elif stage == "latest":
                    require(event["passed"] is False, "post-deploy-failure-was-hidden")
                    report["observations"]["postDeployFailureStillLive"] = current_value(501)
                    require(state.load(root, "last-deployment.json") == event["currentDeployment"],
                            "failed-focused-test-silently-rolled-back")
                    stage = "complete"
                else:
                    require(False, "unexpected-watch-test-stage")
                return
            if kind == "build-superseded":
                require(stage == "superseding" and event["phase"] == "build", "unexpected-superseded-build")
                active = connection.call("build-status", {})
                require(active["state"] == "reaped" and active["reason"] == "guest-build-superseded", "slow-build-not-reaped")
                prior = report["observations"]["rapidEdits"]
                require(active["id"] == prior["build"]["id"], "wrong-build-cancelled")
                child = Path(f'/proc/{prior["childPid"]}/stat')
                require(not child.exists() or child.read_text().rsplit(")", 1)[1].split()[0] in {"Z", "X"},
                        "slow-recipe-descendant-still-running")
                prior["cleanup"] = active
                prior["lastWorkingValue"] = current_value(201)
                stage = "latest"
                return
            if kind == "edit-failed":
                expected = {"compiler-error": "guest-build-failed-last-deployment-retained",
                            "malformed": "build-output-is-not-component-model"}
                require(stage in expected and event["code"] == expected[stage] and event["phase"] == "build"
                        and not event["uncertain"], "unexpected-watch-failure")
                selected = report["deployments"][1]
                require(event["currentDeployment"] == selected and state.load(root, "last-deployment.json") == selected,
                        "failed-edit-replaced-current-deployment")
                report["observations"][stage] = {"event": event, "callableB": current_value(201)}
                if stage == "compiler-error":
                    edit(source, 301, mode="malformed")
                    stage = "malformed"
                else:
                    edit(source, 301, mode="slow")
                    stage = "slow"
                return
            require(False, "unexpected-watch-event")

        def check_session():
            require(time.monotonic() < deadline, "watch-probe-deadline")
            if stage == "complete":
                raise Complete()
        try:
            watch.run(control, connection, source, str(payload), build=build_client.run, emit=emit,
                      check_session=check_session, test_selection=["value"])
        except Complete:
            pass
        require(stage == "complete" and len(report["deployments"]) == 3, "watch-schedule-incomplete")
        require(state.load(control, "watch-deployment.json") == report["deployments"][-1], "watch-display-not-current")
        report["phase"] = "revoked-publication-admission"
        report["observations"]["revokedRestore"] = revoked_restore(root, report["deployments"][0], deadline)
        report["observations"]["afterRevokedRestore"] = current_value(501)
        attempts = list((root / "builds").iterdir())
        require(len(attempts) <= build_cache.MAX_ATTEMPTS, "watch-build-retention-exceeded")
        report["retention"] = {"attempts": len(attempts), "maximumAttempts": build_cache.MAX_ATTEMPTS,
            "ownedBytes": sum(build_cache.usage(path)[1] for path in attempts)}
        report.update(passed=True, phase="complete")
    except BaseException as error:
        report["failure"] = error.code if isinstance(error, DevError) else type(error).__name__
        raise
    finally:
        cleanup_failures = []
        if inflight is not None:
            try:
                inflight.stop()
            except BaseException as error:
                cleanup_failures.append(error.code if isinstance(error, DevError) else type(error).__name__)
            report["inflightFinal"] = inflight.report
        if connection is not None and (root / "lifecycle.json").exists():
            try:
                stopped = connection.call("down", {}, timeout=30)
                require(stopped.get("reaped") is True and stopped.get("cleanShutdown") is True,
                        "watch-probe-owned-shutdown-unconfirmed")
                report["shutdown"] = stopped
            except BaseException as error:
                cleanup_failures.append(error.code if isinstance(error, DevError) else type(error).__name__)
        if cleanup_failures:
            report.update(passed=False, cleanupFailures=cleanup_failures)
        else:
            report["cleanup"] = "owned-node-invoke-and-recipe-children-reaped-private-state-retained"
        report["retainedWorkspace"] = root.name
        report["seconds"] = round(time.monotonic() - began, 3)
        state.atomic(output, "observation.json", report)
    require(report["passed"], "watch-probe-cleanup-failed")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("payload", "source-node", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True), args.output.absolute())
    print(encode({"passed": result["passed"], "cleanup": result["cleanup"]}).decode())
