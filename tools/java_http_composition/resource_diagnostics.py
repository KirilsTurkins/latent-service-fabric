"""Finite actual Java child fuel and full admission queue observations.

Only the supported authorized journal classifies a failure. These fixtures keep
the original node, signed declarations, deadlines and physical resource owners.
The queued calls are cancelled once each; none is retried or silently executed.
"""
from copy import deepcopy
import json
import time

from tools.java_http_composition import context
from tools.java_http_composition.node import ADAPTER, WEB_CONTRACT, decoded, idle, invoke, web_request
from tools.java_http_composition.qualify import fresh_status, running_adapter
from tools.phase2_operator_process import Process, require, write_json
from tools.phase2_operator_scenario import NODE_ID

FUEL = 1_000_000_000
QUEUE_SIZE = 1
MAX_OBSERVATIONS = 64


def terminal_observation(node, *, stages, reason):
    diagnostic = node.get("diagnostic")
    if diagnostic is None:
        return "unavailable"
    return "observed" if (type(diagnostic.get("stage")) is int and diagnostic["stage"] in stages
        and type(diagnostic.get("reason")) is int and diagnostic["reason"] == reason
        and node.get("diagnosticIsTerminal") is True) else "unexpected"


def _lineage(observed, activation):
    nodes = observed["nodes"]
    roots = [row for row in nodes if row["activationId"] == activation and row["parentActivationId"] is None]
    children = [row for row in nodes if row["parentActivationId"] == activation]
    require(len(nodes) == 2 and len(roots) == len(children) == 1, "java-resource-original-one-child")
    parent, child = roots[0], children[0]
    require(parent["principalKind"] == "administrator" and parent["callerService"] is None
        and child["principalKind"] == "service" and child["callerService"] == ADAPTER
        and parent["rootActivationId"] == child["rootActivationId"] == activation,
        "java-resource-original-host-authority-and-lineage")
    return parent, child


def fuel(client, targets, host):
    activation = "java-diagnostics-child-fuel"
    budget = deepcopy(targets["adapter"]["budget"])
    require(int(budget["cpuFuel"]) > FUEL, "java-resource-original-larger-cpu-grant")
    budget["cpuFuel"] = FUEL
    result = {"schemaVersion": "latent.java-child-fuel.v1", "status": "running", "requestedBudget": budget}
    path = client.evidence / "java-child-fuel-campaign.json"
    try:
        result["invocation"] = invoke(client, targets, "adapter", "handle", web_request(host, "/api/spin"),
            activation, codes=(0, 4), budget_override=budget)
        result["tree"] = context.tree(client, activation)
        write_json(client.evidence / "java-child-fuel-original.json", result)
        parent, child = _lineage(result["tree"], activation)
        require(child["terminalState"] not in (None, "completed") and child["grantedBudget"] is not None,
                "java-resource-spin-child-must-reach-terminal-failure")
        result["actualGrants"] = context.narrowed(parent, child)
        status = client.call("activation", "get", child["activationId"])["data"]
        result["childStatus"] = status
        consumption = status["finalConsumption"]
        require(consumption is not None and 0 < int(consumption["cpuFuel"]) <= int(child["grantedBudget"]["cpuFuel"]),
                "java-resource-original-child-cpu-consumed")
        if result["invocation"]["category"] == "success":
            response = decoded(result["invocation"])
            require(len(response) == 1 and response[0]["status"] == 500, "java-resource-original-child-trap-response")
        require("activation.diagnostic.v1" not in json.dumps(result["invocation"]),
                "java-resource-public-diagnostic-redaction")
        result["typedDiagnostic"] = terminal_observation(child, stages=(5,), reason=11)
        result["afterFuel"] = idle(client)
        result["fresh"] = fresh_status(client, targets, host, "java-diagnostics-after-fuel")
        result["status"] = "passed" if result["typedDiagnostic"] == "observed" else "typed-diagnostic-" + result["typedDiagnostic"]
        return result
    finally:
        write_json(path, result)


def _inventory(client):
    return client.call("node", "get", getattr(client, "node_id", NODE_ID))["data"]["inventory"]


def _wait(client, predicate, observations):
    deadline = min(client.deadline, time.monotonic() + 20)
    while time.monotonic() < deadline:
        client.cancellation.check()
        require(len(observations) < MAX_OBSERVATIONS, "java-resource-observation-count-bound")
        observed = _inventory(client)
        observations.append({"originalControlReceipt": f"{client.calls:03}.json",
            "cellCapacity": observed["cellCapacity"], "quotaUsage": observed["quotas"]["usage"]})
        if predicate(observed):
            return observed
        time.sleep(.025)
    raise RuntimeError("java-resource-original-queue-observation-deadline")


def _counts(value):
    cells = value["cellCapacity"]
    require(len(cells) == 1 and int(cells[0]["queueCapacity"]) == QUEUE_SIZE,
            "java-resource-original-one-cell-class-and-queue-bound")
    return int(cells[0]["active"]), int(cells[0]["queueDepth"])


def _queued(client, targets, host, activation):
    source, budget = client.directory / (activation + "-input.json"), client.directory / (activation + "-budget.json")
    selected = deepcopy(targets["adapter"]["budget"])
    selected.update(cpuFuel=100_000_000, memoryBytes=8 * 1024 * 1024, childCalls=0, outboundRequests=0)
    write_json(source, web_request(host))
    write_json(budget, selected)
    process = Process([client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator",
        "--rpc-timeout-ms", "120000", "invoke", "--service", ADAPTER, "--route", targets["adapter"]["name"],
        "--contract", WEB_CONTRACT, "--function", "handle", "--activation-id", activation,
        "--input", str(source), "--budget", str(budget), "--budget-profile", "phase3"],
        client.directory, client.environment, client.cancellation, maximum=65536)
    return process, selected


def _complete(client, process, activation):
    completed = process.complete(min(client.deadline, time.monotonic() + 15))
    for name in ("stdout", "stderr"):
        with (client.evidence / (activation + "." + name + ".log")).open("xb") as output:
            output.write(getattr(completed, name))
    result = {"response": json.loads(completed.stdout), "exitCode": completed.returncode,
              "processReaped": process.owner.finished}
    write_json(client.evidence / (activation + "-original.json"), result)
    require(completed.returncode == 4 and result["response"]["error"]["code"] == "cancelled"
        and result["response"]["outcomeKnown"] is True, "java-resource-original-cancellation-result")
    return result


def queue(client, targets, host):
    result = {"schemaVersion": "latent.java-queue-pressure.v1", "status": "running",
              "queueCapacity": QUEUE_SIZE, "originalFixtureQueueCeiling": 4, "cellCapacity": 2,
              "maximumRootInvocations": 3, "maximumChildInvocations": 1,
              "maximumObservations": MAX_OBSERVATIONS, "observations": [], "queued": [], "cleanup": {}}
    owners, cancelled = {}, set()
    held = "java-diagnostics-held-spin"
    try:
        idle(client)
        owners[held] = running_adapter(client, targets, host, held)
        result["held"] = _wait(client, lambda value: _counts(value) == (2, 0), result["observations"])
        result["heldTree"] = context.tree(client, held)
        _lineage(result["heldTree"], held)
        require(all(row["terminalState"] is None for row in result["heldTree"]["nodes"]),
                "java-resource-original-held-tree-still-running")
        for index in range(QUEUE_SIZE):
            activation = "java-diagnostics-queued-" + str(index)
            owners[activation], budget = _queued(client, targets, host, activation)
            result["queued"].append({"activationId": activation, "requestedBudget": budget})
            original = _wait(client, lambda value: _counts(value) == (2, index + 1), result["observations"])
            require(int(original["quotas"]["usage"]["activeActivations"]) == index + 3,
                    "java-resource-original-accepted-queue-reservations")
        budget = result["queued"][-1]["requestedBudget"]
        overflow = "java-diagnostics-admission-refused"
        result["refused"] = invoke(client, targets, "adapter", "handle", web_request(host), overflow,
                                    budget_override=budget, codes=(4,))
        result["refusedTree"] = context.tree(client, overflow)
        write_json(client.evidence / "java-queue-pressure-original.json", result)
        require(result["refused"]["error"]["code"] == "resource-exhausted"
            and result["refused"]["outcomeKnown"] is True, "java-resource-actual-admission-pressure-refusal")
        nodes = result["refusedTree"]["nodes"]
        require(len(nodes) == 1 and nodes[0]["activationId"] == overflow and nodes[0]["parentActivationId"] is None
            and nodes[0]["principalKind"] == "administrator" and nodes[0]["callerService"] is None
            and nodes[0]["terminalState"] not in (None, "completed"), "java-resource-original-refused-root")
        require("activation.diagnostic.v1" not in json.dumps(result["refused"]),
                "java-resource-public-queue-diagnostic-redaction")
        result["typedDiagnostic"] = terminal_observation(nodes[0], stages=(1, 2), reason=9)
        for entry in [*result["queued"], {"activationId": held}]:
            activation = entry["activationId"]
            cancelled.add(activation)  # Never replay a dispatched cancellation.
            entry["cancellation"] = client.call("activation", "cancel", activation, "--reason", "Finite Java queue fixture")
            require(entry["cancellation"]["data"]["disposition"] == "accepted", "java-resource-original-cancel-accepted")
            entry["completed"] = _complete(client, owners[activation], activation)
            entry["tree"] = context.tree(client, activation)
            require(all(row["terminalState"] == "cancelled" for row in entry["tree"]["nodes"]),
                    "java-resource-original-cancelled-journal")
            if activation == held:
                require(len(entry["tree"]["nodes"]) == 2, "java-resource-held-child-cancellation")
                result["heldCancellation"] = entry
            else:
                require(len(entry["tree"]["nodes"]) == 1, "java-resource-queued-root-never-created-child")
                entry["status"] = client.call("activation", "get", activation)["data"]
                consumed = entry["status"]["finalConsumption"]
                require(consumed is not None and int(consumed["cpuFuel"]) == int(consumed["memoryBytes"]) == 0,
                        "java-resource-queued-root-never-materialized")
        result["afterCancellation"] = idle(client)
        result["fresh"] = fresh_status(client, targets, host, "java-diagnostics-after-queue")
        result["status"] = "passed" if result["typedDiagnostic"] == "observed" else "typed-diagnostic-" + result["typedDiagnostic"]
        return result
    finally:
        cleaned = True
        for activation, process in owners.items():
            if activation not in cancelled:
                cancelled.add(activation)
                try:
                    result["cleanup"][activation] = client.call("activation", "cancel", activation,
                        "--reason", "Failed finite Java fixture cleanup", codes=(0, 4, 5, 6, 130))
                except BaseException as error:
                    result["cleanup"][activation] = {"failure": type(error).__name__, "cancellationOutcomeKnown": False}
                    cleaned = False
            try:
                process.close()
                require(process.closed and process.owner.finished, "java-resource-cli-not-reaped")
            except BaseException as error:
                result["cleanup"][activation + "-process"] = {"failure": type(error).__name__, "reaped": False}
                cleaned = False
        write_json(client.evidence / "java-queue-pressure-campaign.json", result)
        if result["status"] != "running":
            require(cleaned, "java-resource-original-queue-cleanup-failed")
