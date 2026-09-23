"""Finite real-node operations for independently built Rust capsule projects.

This is an isolated acceptance owner, not an SDK runtime or a production trust
bootstrap. It reuses the ordinary CLI, enforced admission and owned processes.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import time

from tools.phase2_operator_process import Client, Process, require, write_json, read_json
from tools.phase2_operator_scenario import NODE_ID
from tools.phase3_management_scenario import configure_provider_node
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS

MEDIA = "application/vnd.latent.wit-values.v1+json"
MAX_CALLS = 384


class RecordingClient(Client):
    """Keep bounded results from this public-input experiment, never credentials."""
    def __init__(self, *args, evidence: Path):
        super().__init__(*args)
        self.evidence = evidence
        self.retained = 0
        evidence.mkdir(mode=0o700)

    def call(self, *args, **kwargs):
        require(self.calls < MAX_CALLS, "authoring-control-count")
        expected = kwargs.pop("codes", (0,))
        value = super().call(*args, codes=(0, 2, 3, 4, 5, 6, 130), **kwargs)
        original_call = self.calls
        encoded = json.dumps(value).encode()
        self.retained += len(encoded)
        require(self.retained <= 4 * 1024 * 1024, "authoring-control-retention")
        write_json(self.evidence / f"{self.calls:03}.json", value)
        code = {"success": 0, "local-error": 2, "declared-error": 3, "platform-failure": 4,
                "transport-failure": 5, "not-found": 6, "interrupted": 130}[value["category"]]
        if code not in expected:
            # Read-only failure evidence. Never retry an uncertain mutation or
            # turn a subsequently found receipt into a successful test attempt.
            diagnostics = {"failedCall": original_call, "audit": [], "auditComplete": False}
            commands = []
            if args[:2] in (("deployment", "apply"), ("deployment", "delete")) and "--operation-id" in args:
                operation = args[args.index("--operation-id") + 1]
                commands.insert(0, ("operation", ("deployment", "operation", operation)))
            for name, command in commands:
                try:
                    require(self.calls < MAX_CALLS, "authoring-diagnostic-count")
                    diagnostics[name] = super().call(*command, codes=(0, 2, 3, 4, 5, 6, 130))
                except Exception as error:
                    diagnostics[name] = {"diagnosticFailure": type(error).__name__}
            token, seen = None, set()
            for _page in range(8):
                try:
                    require(self.calls < MAX_CALLS, "authoring-diagnostic-count")
                    command = ("audit", "query", "--scope", "tenant", "--page-size", "64")
                    if token is not None:
                        command += ("--page-token", token)
                    page = super().call(*command, codes=(0, 2, 3, 4, 5, 6, 130))
                    require(len(json.dumps(diagnostics).encode()) + len(json.dumps(page).encode()) <= 262144,
                            "authoring-diagnostic-retention")
                    diagnostics["audit"].append(page)
                    if page["category"] != "success":
                        break
                    token = page["data"]["page"]["nextPageToken"]
                    if token is None:
                        diagnostics["auditComplete"] = True
                        break
                    require(isinstance(token, str) and token not in seen, "authoring-diagnostic-page-cycle")
                    seen.add(token)
                except Exception as error:
                    diagnostics["auditFailure"] = type(error).__name__
                    break
            write_json(self.evidence / "unexpected-control-diagnostics.json", diagnostics)
        require(code in expected, f"authoring-control-{original_call}-{code}")
        return value


def configure(directory, fixture, port, *, runtime_grants=False, language="rust"):
    initial = configure_provider_node(directory, fixture, port)
    settings = read_json(initial)
    settings["credentials"][0]["tenant"] = "examples"
    settings["providers"].pop("blob")
    settings["providers"]["http"]["identity"]["tenant"] = "examples"
    settings["providers"]["bindings"] = [{"name": "http-binding", "tenant": "examples",
        "consumerService": "examples/my-http-status", "providerService": "http-host",
        "contract": "latent:http/client@0.2.0", "providerBinding": "http-installed", "route": "my-http-status"}]
    settings["cache"].update(entries=2, preparations=1)
    settings["catalogs"].update(releaseEntries=8, deployments=24)
    settings["audit"].update(records=1024, diskBytes=16777216)
    if language == "java":
        settings.setdefault("engine", {})["javaGuest"] = True
        for cell in settings["cells"]:
            cell["maximumMemoryBytes"] = 67_108_864
    settings["capabilityPolicies"]["store"] = {
        "maximumRecords": 64, "maximumOutcomes": 128, "maximumCatalogBytes": 4194304,
        "maximumReadOwners": 64, "maximumPageRecords": 16}
    if runtime_grants:
        from tools.guest_runtime_grants import configure as configure_runtime
        configure_runtime(settings, ("greeting", "word-count", "shipping", "http-status", "recovery"),
                          language="java" if language == "java" else "go")
    path = directory / "authoring-node.json"
    write_json(path, settings)
    return path, settings


def deploy(client, source, publication, *, name=None, grants=None, generation="0"):
    value = read_json(source)
    name = name or value["metadata"]["name"]
    value["metadata"]["name"] = name
    value["spec"]["publication"] = publication
    if grants is not None:
        value["spec"]["grants"] = grants
    path = client.directory / f"deployment-{name}-{generation}.json"
    write_json(path, value)
    state = client.call("deployment", "get", name, "--operation-snapshot", codes=(6,) if generation == "0" else (0,))["data"]
    result = client.call("deployment", "apply", path, "--operation-id", f"apply-{name}-{generation}",
                        "--expected-generation", generation, "--expected-state-version", state["stateVersion"])
    require(result["outcomeKnown"], "authoring-deployment-uncertain")
    return {"name": name, "service": value["spec"]["service"], "budget": value["spec"]["resources"],
            "grants": value["spec"]["grants"],
            "generation": result["data"]["receipt"]["objectGeneration"], "publication": publication}


def grant_http(client, node, fixture, publication, target, port):
    descriptors = [row for row in node.startup_record["providers"] if row["capability"] == "latent:http/client@0.2.0"]
    require(len(descriptors) == 1, "authoring-provider-count")
    descriptor = descriptors[0]
    require(descriptor["capability"] == "latent:http/client@0.2.0" and descriptor["tenant"] == "examples"
            and descriptor["profile"] == "bounded-http-v1", "authoring-provider-identity")
    binding = client.directory / "http-binding.json"
    write_json(binding, {"formatVersion": 1, "tenant": "examples", "capability": descriptor["capability"],
        "providerProfile": descriptor["profile"], "configurationDigest": descriptor["configurationDigest"],
        "configurationEpoch": 1, "restriction": {"operations": []}})
    client.call("policy", "--kind", "provider-binding", "apply", "--id", "http-installed", "--file", binding,
                "--operation-id", "install-http", "--expected-generation", "0")
    policy = client.directory / "http-policy.json"
    write_json(policy, {"formatVersion": 1, "tenant": "examples", "rules": [{
        "id": "allow", "effect": "allow", "principals": [{"kind": "administrator", "subject": "workflow-operator"}],
        "services": [target["service"]], "publications": [publication], "capability": descriptor["capability"],
        "operations": ["send"], "resources": {"kind": "http", "origins": [{"scheme": "http", "host": "localhost", "port": port}],
            "methods": ["GET"], "paths": ["/allowed"], "pathPrefixes": []},
        # The provider reserves body + two header copies + header descriptors
        # + canonical-lowering overhead before dispatch (14336 bytes here).
        # The encoded wire limit (8192) alone is not this ownership ceiling.
        "ceiling": {"operations": 1, "inputBytes": 4096, "outputBytes": 16384, "wallTimeMillis": 5000}}]})
    client.call("policy", "apply", "--id", "http-allow", "--file", policy,
                "--operation-id", "grant-http", "--expected-generation", "0")
    return deploy(client, fixture / "my-http-status/deployment.json", publication, generation=str(target["generation"]),
                  grants=target["grants"] + [{"capability": descriptor["capability"], "policy": "http-allow"}])


def start_call(client, target, template, function, arguments, activation, *, wall=None):
    path = client.directory / f"{activation}-input.json"
    budget_path = client.directory / f"{activation}-budget.json"
    write_json(path, arguments)
    budget = dict(target["budget"])
    if wall is not None:
        budget["wallTimeLimitMillis"] = wall
    write_json(budget_path, budget)
    argv = [client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator",
        "--rpc-timeout-ms", "5000", "invoke", "--service", target["service"], "--route", target["name"],
        "--contract", f"examples:{template}/api@1.0.0", "--function", function, "--activation-id", activation,
        "--input", str(path), "--budget", str(budget_path), "--budget-profile", "phase3"]
    process = Process(argv, client.directory, client.environment, client.cancellation, maximum=32768)
    process.authoring_activation = activation
    process.authoring_started = time.monotonic_ns()
    return process


def finish_call(client, process):
    try:
        completed = process.complete(min(client.deadline, time.monotonic() + 8))
    finally:
        process.close()
    value = json.loads(completed.stdout)
    require(value["schemaVersion"] == "latent.cli.result.v1" and completed.returncode in (0, 3, 4, 5), "authoring-invoke-result")
    payload = value["data"].get("payload") or (value["data"].get("declaredError") or {}).get("payload")
    decoded = None
    if payload:
        require(payload["encoding"] == "base64" and payload["mediaType"] == MEDIA and len(payload["data"]) <= 8192,
                "authoring-typed-result")
        decoded = json.loads(base64.b64decode(payload["data"], validate=True))
    result = {"activation": process.authoring_activation, "exitCode": completed.returncode,
        "elapsedNanos": str(time.monotonic_ns() - process.authoring_started), "decoded": decoded,
        "response": value, "processReaped": process.owner.finished}
    write_json(client.evidence / (process.authoring_activation + ".json"), result)
    return result


def call(client, target, template, function, arguments, activation, **kwargs):
    return finish_call(client, start_call(client, target, template, function, arguments, activation, **kwargs))


def assert_value(result, expected, code=0):
    require(result["exitCode"] == code and result["decoded"] == expected
            and result["response"]["outcomeKnown"] is True, "authoring-application-result")


def sample(client, probe: Probe, phase, population, *, active=False):
    deadline = min(client.deadline, time.monotonic() + 3)
    for attempt in range(64):
        inventory = client.call("node", "get", NODE_ID)["data"]["inventory"]
        require(inventory["topology"]["available"] and inventory["topology"]["complete"], "authoring-topology-unavailable")
        topology = inventory["topology"]["entries"]
        cells = inventory["cellCapacity"]
        require(cells and all(cell["observationAvailable"] for cell in cells), "authoring-cells-unavailable")
        occupied = sum(int(cell["active"]) + int(cell["quarantined"]) for cell in cells)
        require(all(int(row["activeCount"]) == 0 and int(row["configuredCount"]) == 0
                    for row in topology if row["ownership"] == "service-resident"), "authoring-resident-app-owner")
        idle = (occupied == 0 and int(inventory["queueDepth"]) == 0
            and all(int(v) == 0 for v in inventory["quotas"]["usage"].values())
            and all(int(row["activeCount"]) == 0 for row in topology if row["ownership"] == "activation-scoped"))
        if active:
            require(occupied == 1 and any(int(value) > 0 for value in inventory["quotas"]["usage"].values()),
                    "authoring-active-owner-missing")
        if active or idle:
            cache = inventory["cacheSummary"]
            require(cache["available"] and int(cache["entries"]) <= 2 and int(cache["preparing"]) <= 1,
                    "authoring-cache-bound")
            return {"phase": phase, "dormantDeployments": population, "settlingObservations": attempt + 1,
                    "inventory": inventory, "os": probe.sample()}
        require(time.monotonic() < deadline, "authoring-reclamation-deadline")
        time.sleep(0.01)
    raise ValueError("authoring-reclamation-observation-bound")


def provider_idle(client):
    value = client.call("capability", "list", "--deployment", "my-http-status", "--include-node-usage")["data"]
    require(value["nextPageToken"] is None, "authoring-provider-page-bound")
    counters = value["nodeUsage"]["counters"]
    require(not value["nodeUsage"]["unavailable"] and all(name in counters for name in ACTIVE_COUNTERS),
            "authoring-provider-counters-unavailable")
    require(all(int(counters[name]) == 0 for name in ACTIVE_COUNTERS), "authoring-provider-not-reclaimed")
    return value["nodeUsage"]


def delete_all(client, names):
    for name in names:
        state = client.call("deployment", "get", name, "--operation-snapshot")["data"]
        result = client.call("deployment", "delete", name, "--operation-id", "delete-" + name,
                            "--expected-generation", state["deployment"]["generation"],
                            "--expected-state-version", state["stateVersion"])
        require(result["outcomeKnown"], "authoring-delete-uncertain")
    require(client.call("deployment", "list")["data"]["deployments"] == [], "authoring-deployment-cleanup")
