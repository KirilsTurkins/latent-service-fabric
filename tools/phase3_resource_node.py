"""Real standalone-node setup, finite catalogs and separately bracketed observations."""
from __future__ import annotations

import base64
import json
import time

from tools.phase2_operator_process import Client, Process, read_json, require, write_json
from tools.phase2_operator_scenario import NODE_ID
from tools.phase3_management_scenario import configure_provider_node
from tools.phase3_resource_profile import LIMITS, digest, quiescent


class ResourceClient(Client):
    def call(self, *arguments, **keywords):
        require(self.calls < LIMITS["maximumControls"], "resource-control-bound")
        expected = keywords.pop("codes", (0,))
        result = super().call(*arguments, codes=(0, 2, 3, 4, 5, 6, 130), **keywords)
        code = {"success": 0, "local-error": 2, "declared-error": 3, "platform-failure": 4,
                "transport-failure": 5, "not-found": 6, "interrupted": 130}[result["category"]]
        if code not in expected:
            self.last_failure = {"call": self.calls, "category": result["category"],
                                 "error": result.get("error"), "outcomeKnown": result["outcomeKnown"]}
        require(code in expected, f"resource-control-failure-{self.calls}-{code}")
        return result


def configure(directory, fixture, port, profile):
    initial = configure_provider_node(directory, fixture, port)
    settings = read_json(initial)
    settings["cells"][0].update(capacity=profile["cells"], queueCapacity=2)
    settings["catalogs"].update(deployments=profile["dormantSteps"][-1] + 3, releaseEntries=8)
    settings["retention"].update(terminalEntries=32, terminalTtlMillis=30000)
    settings["cache"].update(entries=2, preparations=1)
    settings["audit"].update(records=4096, diskBytes=33554432)
    for binding in settings["providers"]["bindings"]:
        binding.pop("route")
    output = directory / "resource-node.json"
    write_json(output, settings)
    return output, settings


def apply_dormant(client, count, previous):
    applied, refusal = previous, None
    for ordinal in range(previous, count):
        name = f"dormant-{ordinal:03}"
        kind = "http" if ordinal % 2 == 0 else "blob"
        value = read_json(client.directory / f"{kind}-deployment.json")
        value["metadata"]["name"] = name
        path = client.directory / f"{name}.json"
        write_json(path, value)
        snapshot = client.call("deployment", "get", name, "--operation-snapshot", codes=(6,))["data"]
        result = client.call("deployment", "apply", path, "--operation-id", "apply-" + name,
                             "--expected-generation", "0", "--expected-state-version", snapshot["stateVersion"],
                             codes=(0, 4))
        require(result["outcomeKnown"], "resource-dormant-uncertain")
        if result["category"] != "success":
            require(result["error"]["code"] == "resource-exhausted", "resource-dormant-unexpected-failure")
            refusal = {"requestedDeployment": name, "category": result["category"],
                       "code": result["error"]["code"], "outcomeKnown": result["outcomeKnown"],
                       "limitingOwner": "not-exposed-by-CLI"}
            break
        applied += 1
    observed = pages(client, "deployment", "deployments")
    require(len(observed) == applied + 3, "resource-dormant-count")
    return {"rows": observed, "applied": applied, "refusal": refusal}


def pages(client, command, key):
    rows, seen, token = [], set(), None
    for _page in range(8):
        arguments = [command, "list", "--page-size", "64"]
        if token:
            arguments += ["--page-token", token]
        value = client.call(*arguments)["data"]
        rows += value[key]
        require(len(rows) <= 256, "resource-catalog-row-bound")
        token = value["nextPageToken"]
        if token is None:
            return rows
        require(token not in seen, "resource-catalog-cursor-cycle")
        seen.add(token)
    raise ValueError("resource-catalog-page-bound")


def delete_deployments(client, count):
    names = [f"dormant-{ordinal:03}" for ordinal in range(count)] + ["guest-http", "guest-blob", "guest-callee"]
    for name in names:
        state = client.call("deployment", "get", name, "--operation-snapshot")["data"]
        result = client.call("deployment", "delete", name, "--operation-id", "delete-" + name,
                             "--expected-generation", state["deployment"]["generation"],
                             "--expected-state-version", state["stateVersion"])
        require(result["outcomeKnown"], "resource-delete-uncertain")
    require(not pages(client, "deployment", "deployments"), "resource-unrouted-count")


def sample(client, probe, phase, dormant, capabilities=True):
    began = time.monotonic_ns()
    inventory = client.call("node", "get", NODE_ID)["data"]["inventory"]
    after_inventory = time.monotonic_ns()
    usage = None
    if capabilities:
        usage = client.call("capability", "list", "--deployment", "guest-http", "--include-node-usage")["data"]
        require(usage["nextPageToken"] is None, "resource-capability-pages")
        usage = {key: usage[key] for key in ("nodeUsage", "tenantUsage")}
    after_capabilities = time.monotonic_ns()
    observed = probe.sample()
    return {"phase": phase, "dormantDeployments": dormant,
            "brackets": {"beganNanos": str(began), "inventoryFinishedNanos": str(after_inventory),
                         "capabilitiesFinishedNanos": str(after_capabilities)},
            "inventory": {key: inventory[key] for key in
                          ("queueDepth", "routeGeneration", "cacheSummary", "cellCapacity", "quotas", "topology")},
            "capabilities": usage, "os": observed}


def settled_samples(client, probe, phase, dormant, count, capabilities=True):
    result = []
    for _sample in range(count):
        for _attempt in range(20):
            observed = sample(client, probe, phase, dormant, capabilities)
            if quiescent(observed):
                result.append(observed)
                break
            time.sleep(0.025)
        else:
            require(False, "resource-settle-bound")
        time.sleep(0.025)
    return result


def invocation(client, target, activation, arguments, function=None):
    path = client.directory / f"{activation}-input.json"
    budget_path = client.directory / f"{activation}-budget.json"
    write_json(path, arguments)
    write_json(budget_path, target["budget"])
    argv = [client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator",
            "--rpc-timeout-ms", "5000", "invoke", "--service", target["service"], "--route", target["route"],
            "--contract", target["contract"], "--function", function or target["function"],
            "--activation-id", activation, "--input", str(path), "--budget", str(budget_path),
            "--budget-profile", "phase3"]
    process = Process(argv, client.directory, client.environment, client.cancellation, maximum=32768)
    process.resource_activation = activation
    process.resource_input_digest = digest(arguments)
    return process


def finish(client, process):
    try:
        completed = process.complete(min(client.deadline, time.monotonic() + 8))
    finally:
        process.close()
    value = json.loads(completed.stdout)
    require(value["schemaVersion"] == "latent.cli.result.v1" and completed.returncode in (0, 3, 4, 5, 130),
            "resource-invocation-result")
    payload = value["data"].get("payload")
    decoded = None
    if payload:
        require(payload["encoding"] == "base64" and len(payload["data"]) <= 4096, "resource-payload-bound")
        decoded = json.loads(base64.b64decode(payload["data"], validate=True))
    error = value.get("error") or {}
    activation = value["data"].get("activationId")
    require(activation in (None, process.resource_activation), "resource-activation-association")
    return {"category": value["category"], "exitCode": completed.returncode,
            "requestedActivationId": process.resource_activation, "activationId": activation,
            "requestDispatched": value["requestDispatched"], "outcomeKnown": value["outcomeKnown"],
            "code": error.get("code"), "grpcCode": error.get("grpcCode"), "value": decoded,
            "inputDigest": process.resource_input_digest, "processReaped": process.owner.finished}
