#!/usr/bin/env python3
"""Attest the common browser flow against actual preinstalled node publications."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient
from tools.phase2_operator_process import Process, require, write_json
from tools.rust_capsule_project import fresh
from tools.stateful_reference_conductor import Backend, attest_originals, decode, regular, select

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("rust", "c", "typescript", "go", "java", "dotnet")


def validate_inputs(inputs: dict) -> tuple[str, list[dict]]:
    require(set(inputs) == {"schemaVersion", "scope", "cli", "node", "operatorConfiguration",
                           "aliceConfiguration", "backends", "browser"}
            and inputs["schemaVersion"] == "latent.stateful-reference.conductor-input.v1",
            "closed-app-conductor-input")
    for name in ("cli", "node", "operatorConfiguration", "aliceConfiguration"):
        require(isinstance(inputs[name], str) and 0 < len(inputs[name]) <= 4096
                and not any(ord(char) < 32 or ord(char) == 127 for char in inputs[name]),
                "bounded-app-conductor-path")
    scope, plans = inputs["scope"], inputs["backends"]
    require(scope in ("single-backend", "six-backend-matrix") and isinstance(plans, list)
            and len(plans) == (1 if scope == "single-backend" else 6), "finite-app-browser-scope")
    for plan in plans:
        require(isinstance(plan, dict) and set(plan) == {"language", "entities"}
                and isinstance(plan["entities"], dict) and set(plan["entities"]) == {"alice", "bob"},
                "closed-two-entity-app-plan")
        for entity in plan["entities"].values():
            require(isinstance(entity, dict) and set(entity) == {
                "directory", "publication", "resultPolicy", "statePolicies", "grants"},
                "closed-app-publication-plan")
    languages = [plan["language"] for plan in plans]
    require(all(isinstance(language, str) for language in languages)
            and len(set(languages)) == len(languages) and set(languages) <= set(LANGUAGES)
            and (scope != "six-backend-matrix" or set(languages) == set(LANGUAGES)), "exact-app-guest-matrix")
    require(isinstance(inputs["browser"], dict) and set(inputs["browser"]) == {
        "origin", "toolchain", "chrome", "frontend", "users"}, "closed-app-browser-configuration")
    return scope, plans


def run(source: Path, output: Path) -> dict:
    require(sys.platform == "linux", "real-browser-conductor-requires-linux-process-ownership")
    inputs = decode(regular(source.parent, source.name, 32768))
    scope, plans = validate_inputs(inputs)
    languages = [plan["language"] for plan in plans]
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents, "app-browser-output-outside-checkout")
    output = fresh(output)
    evidence = Evidence(output / "evidence")
    deadline = time.monotonic() + 900
    report = {"schemaVersion": "latent.stateful-reference.browser-conductor.v1", "scope": scope,
              "coreBrowserQualified": False, "phase4ApplicationQualified": False,
              "source": [], "selections": [], "originals": [], "passed": False}
    browser = None
    with owned_cancellation() as cancellation:
        operator = RecordingClient(Path(inputs["cli"]), output, cancellation, deadline, evidence)
        operator.environment = build_environment(output)
        operator.config = Path(inputs["operatorConfiguration"])
        user = RecordingClient(Path(inputs["cli"]), output, cancellation, deadline, evidence)
        user.environment = build_environment(output)
        user.config = Path(inputs["aliceConfiguration"])
        # The observer does not derive or replace any credential. Existing
        # protected node configuration supplies the operator and Alice profiles.
        backends = {}
        try:
            for plan in plans:
                require(set(plan["entities"]) == {"alice", "bob"}, "two-distinct-app-entity-publications")
                pair = {}
                for entity in ("alice", "bob"):
                    selected = plan["entities"][entity]
                    backend = Backend.read(plan["language"], entity, Path(selected["directory"]), selected["publication"])
                    pair[entity] = backend
                    report["source"].append(backend.observation())
                    # Warm all ordinary deployments before the browser's own
                    # unchanged 240-second bound begins. Selected triggers are
                    # explicitly switched again on each original signal phase.
                    select(operator, backend, result_policy=selected["resultPolicy"],
                           state_policies=selected["statePolicies"], grants=selected["grants"], install_triggers=False)
                require(pair["alice"].publication != pair["bob"].publication,
                        "distinct-app-namespace-publications")
                backends[plan["language"]] = pair
            browser_inputs = dict(inputs["browser"], scope=scope,
                                  schemaVersion="latent.stateful-reference.browser-input.v1")
            browser_inputs["backends"] = [backends[language]["alice"].observation() for language in languages]
            path = output / "browser-inputs.json"
            write_json(path, browser_inputs)
            path.chmod(0o600)
            browser = Process([inputs["node"], str(ROOT / "tools/check_stateful_reference.mjs"), str(path)],
                              output, build_environment(output), cancellation, maximum=262144)
            browser_deadline = min(deadline, time.monotonic() + 240)
            for plan in plans:
                language = plan["language"]
                waiting = browser.line(browser_deadline)
                evidence.record("browser-" + language + "-waiting", waiting)
                require(waiting == {"event": "waiting", "phase": "backend-selected", "language": language},
                        "original-browser-selection-phase")
                pair = backends[language]
                selections = []
                for entity in ("alice", "bob"):
                    selected = plan["entities"][entity]
                    selections.append(select(operator, pair[entity], result_policy=selected["resultPolicy"],
                                             state_policies=selected["statePolicies"], grants=selected["grants"]))
                require(time.monotonic() < browser_deadline and not browser.owner.exited(),
                        "original-live-browser-leader")
                os.kill(browser.owner.process.pid, signal.SIGUSR1)
                complete = browser.line(browser_deadline)
                evidence.record("browser-" + language + "-complete", complete)
                require(complete.get("event") == "complete" and complete.get("phase") == "backend-browser"
                        and complete.get("language") == language, "actual-browser-backend-completion")
                report["selections"].append({"language": language, "selected": selections,
                                             "browserOriginalCommandIds": complete["originalCommandIds"]})
            observed = browser.line(browser_deadline)
            evidence.record("browser-receipt", observed)
            require(observed.get("schemaVersion") == "latent.stateful-reference.browser.v1"
                    and observed.get("passed") is True and observed.get("scope") == scope
                    and observed.get("transport") == "real-node-http"
                    and observed.get("responseLoss") == "actual-terminal-reply-then-abort"
                    and [row["language"] for row in observed["observations"]] == languages,
                    "actual-browser-receipt-contract")
            actual = browser.complete(browser_deadline)
            require(actual.returncode == 0, "actual-browser-exit")
            user.calls = operator.calls  # One evidence ordinal space for both profiles.
            for observation in observed["observations"]:
                report["originals"].append({"language": observation["language"],
                    "records": attest_originals(user, backends[observation["language"]]["alice"], observation)})
            report.update(passed=True, coreBrowserQualified=True, browser=observed,
                          qualificationBoundary="real common browser flow and current original-command/effect association")
        except BaseException as error:
            report["failureType"] = type(error).__name__
            raise
        finally:
            if browser is not None:
                browser.close()
                evidence.write("browser.stdout", bytes(browser.buffers[0]))
                evidence.write("browser.stderr", bytes(browser.buffers[1]))
                report["browserProcessReaped"] = browser.closed and browser.owner.finished
            report["evidence"] = evidence.summary()
            report["remainingApplicationGates"] = ["transactional-inbox-real-broker", "restart-before-dispatch",
                "policy-blocked-and-uncertain-reconciliation", "schema-rollout-and-retention", "physical-dormancy",
                "packaged-create-build-sign-admit-run-cleanup"]
            write_json(output / "receipt.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.inputs, args.output)
    print(json.dumps({"passed": result["passed"], "coreBrowserQualified": result["coreBrowserQualified"],
                      "phase4ApplicationQualified": False, "receipt": str(args.output / "receipt.json")}))


if __name__ == "__main__":
    main()
