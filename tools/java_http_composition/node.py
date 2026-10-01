"""Bounded signed Java components on the ordinary node and shared HTTP ingress."""
from __future__ import annotations

import base64
import copy
import http.client
import json
from pathlib import Path
import socket
import time

from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import Process, require, read_json, write_json
from tools.phase2_operator_scenario import NODE_ID, configure_node
from tools.run_security_profile_workflow import replace_config
from tools.rust_capsule_node import deploy
from tools.static_api.node import policy

TENANT = "examples"
DOMAIN = "examples/java-http-domain"
ADAPTER = "examples/java-http-adapter"
CONTEXT_REQUIRED = "examples/java-http-context-required"
DOMAIN_CONTRACT = "examples:java-http-domain/api@1.0.0"
CONTEXT_CONTRACT = "examples:java-http-context-required/api@1.0.0"
WEB_CONTRACT = "latent:web/application@0.1.0"
SERVICE_CAPABILITY = "latent:service/invoke@0.1.0"
CHILD_SUBJECT = f"service:{len(TENANT)}:{TENANT}:{len(ADAPTER)}:{ADAPTER}"
MEDIA = "application/vnd.latent.wit-values.v1+json"


def configure(directory: Path, releases: Path, *, http=True, former_profile=False):
    require(not former_profile or not http, "java-former-profile-no-http")
    config = configure_node(directory, releases, TENANT)
    value = read_json(config)
    # Public qualification credentials exercise tenant and management scope.
    # They are bounded test inputs, never guest context or production tokens.
    from tools.java_http_composition.inspection import WRONG_TENANT_TOKEN, INVOKER_TOKEN
    value["credentials"] += [
        {"token": WRONG_TENANT_TOKEN, "subject": "other-workflow-operator", "tenant": "other-examples", "role": "operator"},
        {"token": INVOKER_TOKEN, "subject": "ordinary-workflow-invoker", "tenant": TENANT, "role": "invoke"}]
    value["engine"] = {"javaGuest": True}
    value["execution"].update(maximumWallTimeMillis=120000)
    value["limits"] = {"maximumComponentBytes": 32 * 1024 * 1024,
                       "maximumPayloadBytes": (2 if http else 1) * 1024 * 1024}
    value["cells"][0].update(capacity=2, queueCapacity=4, maximumMemoryBytes=134217728)
    value["budgetProfile"] = {"mode": "phase3", "maximumChildCalls": 4, "maximumDepth": 2,
        "maximumLiveChildren": 1, "maximumLiveDescendants": 2, "maximumOutboundRequests": 0,
        "maximumBlobReadBytes": 0, "maximumBlobWriteBytes": 0}
    value["cache"].update(entries=4, sourceBytes=128 * 1024 * 1024, preparations=1)
    value["catalogs"].update(deployments=8, releaseEntries=8)
    value["audit"].update(records=4096, diskBytes=64 * 1024 * 1024)
    value["retention"].update(terminalEntries=128, terminalTtlMillis=120000)
    value["capabilityPolicies"] = {"formatVersion": 1, "maximumControlJobs": 2,
        "store": {"maximumRecords": 64, "maximumOutcomes": 128, "maximumCatalogBytes": 4194304,
                  "maximumReadOwners": 64, "maximumPageRecords": 16}}
    value["providers"] = {"formatVersion": 1, "bindings": [], "localService": {
        "identity": {"id": "localService", "tenant": TENANT, "service": DOMAIN, "epoch": 1},
        "deployment": "java-http-domain", "contract": DOMAIN_CONTRACT}}
    for name, (contract, _profile, _operation, _kind) in profiles("java").items():
        value["providers"][name] = {"identity": {"id": name, "tenant": TENANT,
                                               "service": "runtime-host", "epoch": 1}}
        for service in (ADAPTER, DOMAIN, CONTEXT_REQUIRED):
            value["providers"]["bindings"].append({"name": name + "-" + service.rsplit("/", 1)[1],
                "tenant": TENANT, "consumerService": service, "providerService": "runtime-host",
                "contract": contract, "providerBinding": name + "-installed"})
    value["providers"]["bindings"].append({"name": "java-domain", "tenant": TENANT,
        "consumerService": ADAPTER, "providerService": DOMAIN,
        "contract": SERVICE_CAPABILITY, "providerBinding": "java-domain-installed"})
    if former_profile:
        value["developmentPreparation"] = {"formatVersion": 1, "consent": True,
            "purpose": "disposable-development-tests", "profile": "former-http-global-values-v1"}
    host = None
    if http:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        host = f"localhost:{port}"
        value["httpIngress"] = {"formatVersion": 1, "bind": f"127.0.0.1:{port}",
            "transport": {"mode": "loopback"}, "authentication": {"mode": "public-origins", "origins": [
                {"authority": host, "subject": "java-http-ingress", "tenant": TENANT}]},
            "limits": {"maximumConnections": 8, "maximumExchanges": 2,
                       "maximumBufferBytes": 24 * 1024 * 1024, "maximumRequestsPerConnection": 4}}
    replace_config(config, value)
    return config, host


def grant(client, node, releases, publications, *, child_trigger=False, domain_grants=()):
    grants = []
    for name, (contract, profile, operation, kind) in profiles("java").items():
        installed = next(row for row in node.startup_record["providers"] if row["id"] == name)
        policy(client, "provider-binding", name + "-installed", {"formatVersion": 1, "tenant": TENANT,
            "capability": contract, "providerProfile": profile, "configurationDigest": installed["configurationDigest"],
            "configurationEpoch": 1, "restriction": {"operations": [operation]}})
        policy(client, "policy", name + "-allow", {"formatVersion": 1, "tenant": TENANT, "rules": [{
            "id": "runtime", "effect": "allow", "principals": [
                {"kind": "administrator", "subject": "workflow-operator"},
                {"kind": "trigger", "subject": "java-http-ingress"},
                {"kind": "service", "subject": CHILD_SUBJECT}],
            "services": [ADAPTER, DOMAIN, CONTEXT_REQUIRED], "publications": sorted(publications.values()), "capability": contract,
            "operations": [operation], "resources": {"kind": kind},
            "ceiling": {"operations": 4096, "inputBytes": 0, "outputBytes": 32768, "wallTimeMillis": 5000}}]})
        grants.append({"capability": contract, "policy": name + "-allow"})
    return {name: deploy(client, releases / ("java-http-" + name) / "deployment.json", publications[name],
                        grants=grants + list(domain_grants) if name == "domain" else grants)
            for name in ("domain", "adapter")}


def service_grant(client, node, publications, *, generation=0, trigger_only=False):
    if generation == 0:
        installed = next(row for row in node.startup_record["providers"] if row["id"] == "localService")
        policy(client, "provider-binding", "java-domain-installed", {"formatVersion": 1, "tenant": TENANT,
            "capability": SERVICE_CAPABILITY, "providerProfile": "lsf-local-service-invocation-v1",
            "configurationDigest": installed["configurationDigest"], "configurationEpoch": 1,
            "restriction": {"operations": ["call"]}})
    principals = [{"kind": "trigger", "subject": "java-http-ingress"}]
    if not trigger_only:
        principals.append({"kind": "administrator", "subject": "workflow-operator"})
    result = policy(client, "policy", "java-domain-allow", {"formatVersion": 1, "tenant": TENANT, "rules": [{
        "id": "selected-domain", "effect": "allow", "principals": principals,
        "services": [ADAPTER], "publications": [publications["adapter"], publications["adapter-next"]], "capability": SERVICE_CAPABILITY,
        "operations": ["call"], "resources": {"kind": "service", "services": [DOMAIN],
                                                  "publications": [publications["domain"]]},
        "ceiling": {"operations": 4, "inputBytes": 1048576, "outputBytes": 1048576, "wallTimeMillis": 60000}}]}, generation)
    return result["generation"]


def route(client, host, publication, *, path="/api", function="handle"):
    snapshot = client.call("route", "get")["data"]["snapshot"]
    rows = [row for row in snapshot["services"] if row["service"] == ADAPTER and row["revisions"]]
    require(rows, "java-http-route-present")
    selected = next((row for row in rows if row["routeId"] == "java-http-adapter"), rows[0])
    revision = selected["revisions"][0]
    deployment = client.call("deployment", "get", selected["routeId"])["data"]["deployment"]
    target = {"service": ADAPTER, "contract": WEB_CONTRACT, "function": function,
        "route": selected["routeId"], "publication": publication, "revision": revision["revisionId"],
        "deploymentGeneration": int(deployment["generation"])}
    for method in ("GET", "POST"):
        name = "java-api-" + method.lower()
        state = client.call("trigger", "get", name, codes=(0, 6))["data"]
        source = client.directory / f"{name}-{client.calls}.json"
        write_json(source, {"apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
            "metadata": {"name": name, "tenant": TENANT}, "spec": {"target": target,
            "configuration": {"profile": "buffered-v1", "scheme": "http", "host": host,
                              "path": path, "pathMatch": "prefix", "method": method}}})
        operation = f"java-trigger-{client.calls}"
        applied = client.call("trigger", "apply", source, "--operation-id", operation,
            "--expected-generation", state["trigger"]["generation"] if state["trigger"] else 0,
            "--expected-state-version", state["stateVersion"], codes=(0, 2, 4, 5, 6))
        recovered = client.call("trigger", "operation", operation)
        require(applied["category"] == "success" and applied["outcomeKnown"]
            and recovered["outcomeKnown"] and recovered["data"]["receipt"] == applied["data"]["receipt"],
            "java-http-original-trigger-operation-recovery")
    return target


def request(host, path="/api/status", *, method="GET", value=None, headers=None, maximum=1048576):
    connection = http.client.HTTPConnection("127.0.0.1", int(host.rsplit(":", 1)[1]), timeout=125)
    try:
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        connection.request(method, path, body=body, headers={"Host": host, "Connection": "close",
            "Content-Type": MEDIA, "Origin": "http://" + host, **(headers or {})})
        response = connection.getresponse()
        body = response.read(maximum + 1)
        require(len(body) <= maximum, "java-http-response-bound")
        return response.status, body, dict(response.getheaders())
    finally:
        connection.close()


def invoke(client, targets, name, function, arguments, activation, *, route_name=True, codes=(0,), budget_override=None,
           context_flags=()):
    source = client.directory / (activation + ".json")
    write_json(source, arguments)
    budget = client.directory / (activation + "-budget.json")
    write_json(budget, targets[name]["budget"] if budget_override is None else budget_override)
    extra = ("--route", targets[name]["name"]) if route_name else ()
    count = getattr(client, "java_invocations", 0)
    require(count < 64, "java-http-invocation-count")
    client.java_invocations = count + 1
    service, contract = {"domain": (DOMAIN, DOMAIN_CONTRACT), "adapter": (ADAPTER, WEB_CONTRACT),
                         "context-required": (CONTEXT_REQUIRED, CONTEXT_CONTRACT)}[name]
    argv = [client.executable, "--output", "json", "--config", str(client.config), "--profile", "operator",
        "--rpc-timeout-ms", "120000", "invoke", "--service", service,
        "--contract", contract, "--function", function,
        "--activation-id", activation, "--input", str(source), "--budget", str(budget), "--budget-profile", "phase3",
        *extra, *context_flags]
    began = time.monotonic_ns()
    process = Process(argv, client.directory, client.environment, client.cancellation, maximum=65536)
    try:
        completed = process.complete(min(client.deadline, time.monotonic() + 123))
    finally:
        process.close()
    for stream in ("stdout", "stderr"):
        with (client.evidence / (activation + "." + stream + ".log")).open("xb") as file:
            file.write(getattr(completed, stream))
    result = json.loads(completed.stdout)
    write_json(client.evidence / (activation + ".json"), {"response": result,
        "rpcTimeoutMillis": 120000, "processTimeoutMillis": 123000,
        "elapsedNanos": str(time.monotonic_ns() - began), "processReaped": process.owner.finished})
    require(result["schemaVersion"] == "latent.cli.result.v1" and completed.returncode in codes,
        "java-http-invocation-outcome")
    return result



def rebind(client, targets, releases, publications, names=("adapter",)):
    """Explicit new deployment operations after a policy revision changes."""
    result = {}
    for name in names:
        previous = targets[name]
        targets[name] = deploy(client, releases / ("java-http-" + name) / "deployment.json",
            publications[name], generation=str(previous["generation"]), grants=previous["grants"])
        result[name] = {"previousGeneration": previous["generation"],
            "currentGeneration": targets[name]["generation"], "publication": publications[name]}
    return result

def decoded(result):
    payload = result["data"].get("payload") or (result["data"].get("declaredError") or {}).get("payload")
    return None if payload is None else json.loads(base64.b64decode(payload["data"], validate=True))


def web_request(host, path="/api/status", *, method="get", body=""):
    return [{"profile": "buffered-v1", "method": method, "scheme": "http", "authority": host,
        "path": path, "query": {"none": None}, "headers": [], "media-type": {"some": MEDIA} if body else {"none": None},
        "body-base64": base64.b64encode(body.encode()).decode()}]


def idle(client):
    end = min(client.deadline, time.monotonic() + 10)
    for _ in range(128):
        inventory = client.call("node", "get", getattr(client, "node_id", NODE_ID))["data"]["inventory"]
        cells = inventory["cellCapacity"]
        if all(int(row["active"]) == int(row["quarantined"]) == int(row["queueDepth"]) == 0 for row in cells):
            require(all(int(v) == 0 for v in inventory["quotas"]["usage"].values()), "java-composition-quota-retained")
            return inventory
        require(time.monotonic() < end, "java-composition-physical-cleanup-deadline")
        time.sleep(.025)
    raise RuntimeError("java-composition-physical-cleanup-observation-bound")
