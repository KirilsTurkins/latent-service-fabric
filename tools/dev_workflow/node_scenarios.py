"""Shared application scenarios on the selected separate, authenticated node."""
from __future__ import annotations

import platform
import time

from . import build, node_fixtures, node_invocation, node_test_grants, node_test_profile, node_tests, paths, scenarios, service, state
from .common import decode, digest, members, require


def run(root, arguments, *, deadline: float | None = None):
    from .helper import client, deploy, installation
    members(arguments, {"environment", "selection"})
    require(arguments["environment"] == "node", "linux-test-cannot-fallback-to-portable")
    require(root.name.startswith("test-"), "explicit-disposable-test-workspace-required")
    saved = state.load(root, "project.json")
    source, build_receipt = build.accepted(root, saved)
    descriptor = saved["descriptor"]
    deadline = min(deadline if deadline is not None else float("inf"), time.monotonic() + 300)
    cli, journal = client(root, deadline=deadline)
    deployed, revision, current_grants = node_tests.target(root, descriptor, build_receipt, cli)
    installed = None
    if (root / "test-profile.json").exists():
        installed = node_test_profile.installed(root, descriptor, service.request(root, "status"))
    cases = []
    for name in descriptor["scenarios"]:
        cases.extend(scenarios.validate(decode(paths.read(source, name)), "node")["scenarios"])
    require(all(case["service"] == descriptor["service"] for case in cases),
            "scenario-service-outside-test-project")
    manifest = decode(paths.read(source, descriptor["artifacts"]["capsule"]))
    ceilings = manifest["execution"]["limits"]
    def controls(case):
        execution = case["execution"]
        return (installed is not None and not execution.get("cancelBeforeStart", False)
                and set(execution["grants"]) <= {entry["capability"] for entry in installed.values()})
    def invoke(case, raw):
        nonlocal deployed, revision, current_grants
        require(case["service"] == descriptor["service"], "scenario-service-outside-test-project")
        execution = case.get("execution", {"grants": []}) if installed is not None else None
        if execution is not None:
            selected = node_test_grants.selection(root, descriptor, deployed["publication"], execution, installed, cli, journal)
            if current_grants != selected:
                # deploy observes the owned generation and catalog state before
                # applying. It records/reconciles the original operation ID.
                deploy(root, test_grants=selected, deadline=deadline)
                current_grants = selected
        deployed, revision, current_grants = node_tests.target(root, descriptor, build_receipt, cli)
        path = root / "test-input.json"
        if path.exists():
            paths.read(root, path.name, 1048576)
            path.unlink()
        paths.write_new(path, raw)
        budget = dict(ceilings)
        budget["wallTimeLimitMillis"] = min(case["timeoutMillis"], budget.get("wallTimeLimitMillis") or case["timeoutMillis"])
        for key, target in (("fuel", "cpuFuel"), ("memoryBytes", "memoryBytes")):
            if execution is not None and key in execution:
                budget[target] = int(execution[key])
        state.atomic(root, "test-budget.json", budget)
        return node_invocation.execute(cli, journal, {"case": case["id"], "inputSha256": digest(raw), "expectedRevision": revision},
            lambda activation: cli.call("invoke", "--service", case["service"], "--contract", case["contract"],
                "--function", case["function"], "--input", path, "--media-type", case["mediaType"], "--activation-id", activation,
                "--budget", root / "test-budget.json", "--budget-profile", "phase3" if installed is not None else "phase1",
                "--rpc-timeout-ms", str(case["timeoutMillis"] + 1000), timeout=case["timeoutMillis"] / 1000 + 5), deadline)
    layout, current = installation(root)
    node = decode(paths.read(layout.node.parent, layout.node.name))
    signing = None
    if (root / "test-signing-receipt.json").exists():
        from .node_test_signing import selected
        signing = selected(root, build_receipt)
    supported = {"context", "log", "fresh-state", "fuel", "memory"}
    if installed is not None:
        if any(name.startswith("clock") for name in installed):
            supported.add("clock")
        if "random" in installed:
            supported.add("random")
    fixture_profile = state.load(root, "test-profile.json") if installed is not None else {}
    fixtures = fixture_profile.get("fixtures")
    initialized = node_fixtures.initialized(source, cases, fixtures)
    report = scenarios.run({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}, source, "node",
        arguments["selection"], invoke, {"source": build_receipt["source"], "artifacts": build_receipt["artifacts"],
        "deployment": deployed, "expectedRevision": revision, "hostAbi": descriptor["hostAbi"],
        "package": build_receipt["package"], "fixtureProviders": installed or {}, "fixtureConfiguration": fixtures,
        "fixtureCheck": fixture_profile.get("fixtureCheck"),
        "admission": node["supplyChain"]["mode"], "testSigning": signing,
        "runtime": decode(paths.read(current, "release-source.json")), "node": node["nodeId"],
        "profile": node["securityProfile"], "os": "linux", "architecture": platform.machine(), "kernel": platform.release()},
        supported=supported,
        initialized_fixtures=initialized, execution_controls=controls, expected_revision=lambda: revision)
    pending = journal.read()["pending"]
    if any(item.get("recovery", {}).get("clientCleanup") == "unconfirmed" for item in report["results"]):
        report["cleanup"] = "client-cleanup-unconfirmed-node-retained"
    elif pending:
        report["cleanup"] = "original-operation-unresolved-node-retained"
    elif any(item.get("outcomeKnown") is False for item in report["results"]):
        report["cleanup"] = "original-result-unavailable-node-retained"
    elif any(item.get("activationId") for item in report["results"]):
        report["cleanup"] = "invocation-results-received-node-retained"
    else:
        report["cleanup"] = "no-invocations-node-retained"
    report["pendingOperation"] = {key: pending[key] for key in ("id", "kind", "requestDigest")} if pending else None
    report["identity"]["deployment"] = deployed
    report["identity"]["expectedRevision"] = revision
    state.atomic(root, "test-report.json", report)
    return report
