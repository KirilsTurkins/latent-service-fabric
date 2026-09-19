"""Bounded selected-publication helpers for the actual Angular T1 workflow."""
from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import json
import re
import time

from tools.phase2_operator_process import file_digest, read_json, require, write_json
from tools.phase2_operator_scenario import NODE_ID
from tools.run_security_profile_workflow import configuration, replace_config

TENANT = "tests"
CONTRACT = "latent:web/application@0.1.0"
MEDIA = "application/vnd.latent.wit-values.v1+json"
FOREIGN_TOKEN = "LSF-PUBLIC-ANGULAR-FOREIGN-TEST-ONLY"
PREPARATION_MILLIS = 300000
MIB = 1024 * 1024


def configure_angular_node(client, directory, fixture, compiler):
    path, value = configuration(client, directory, fixture, compiler)
    value["rendererProfile"] = "angular-ssr-component-v1"
    value["cells"][0].update(maximumMemoryBytes=256 * MIB)
    value["execution"].update(maximumCpuFuel=2000000000, maximumLogBytes=0)
    value["limits"] = {"maximumComponentBytes": 32 * MIB, "maximumPayloadBytes": 2 * MIB}
    value["cache"].update(sourceBytes=128 * MIB, compiledImageBytes=256 * MIB)
    value["isolatedAot"].update(
        process={"jobTimeoutMillis": PREPARATION_MILLIS, "maximumOutputBytes": 128 * MIB,
                 "addressSpaceBytes": 4 * 1024 * MIB},
        cache={"entries": 8, "diskBytes": 512 * MIB},
        images={"maximumImages": 4, "maximumImageBytes": 128 * MIB,
                "maximumTotalBytes": 512 * MIB})
    value["audit"].update(records=1024, diskBytes=16 * MIB)
    value["shutdownGraceMillis"] = 5000
    value["credentials"].append({"token": FOREIGN_TOKEN, "subject": "foreign-operator",
                                  "tenant": "foreign", "role": "operator"})
    value["httpIngress"] = {
        "formatVersion": 1, "bind": "127.0.0.1:0", "transport": {"mode": "loopback"},
        "authentication": {"mode": "public-origins", "origins": [
            {"authority": "alice.angular.test", "subject": "Alice<unsafe>", "tenant": TENANT},
            {"authority": "bob.angular.test", "subject": "Bob", "tenant": TENANT},
            {"authority": "foreign.angular.test", "subject": "Foreign", "tenant": "foreign"}]},
        "limits": {"maximumConnections": 4, "maximumExchanges": 2,
                   "maximumBufferBytes": 24 * MIB, "maximumRequestsPerConnection": 4}}
    replace_config(path, value)
    return path, value


def client_profile(client, ordinal):
    profile = read_json(client.config)
    profile["profiles"][0]["limits"] = {
        "maximumComponentBytes": 32 * MIB, "maximumPayloadBytes": MIB,
        "maximumResponseBytes": 4 * MIB}
    path = client.directory / f"angular-client-{ordinal}.json"
    write_json(path, profile)
    client.config = path
    return profile


def foreign_profile(client, profile):
    foreign = copy.deepcopy(profile)
    foreign["profiles"][0].update(tenant="foreign", token=FOREIGN_TOKEN)
    path = client.directory / "foreign-client.json"
    write_json(path, foreign)
    return path


def tree_inventory(directory, client, maximum_bytes=512 * MIB):
    entries = {}
    pending = [directory]
    total = 0
    seen = 0
    while pending:
        parent = pending.pop()
        require(not parent.is_symlink(), "angular-inventory-link")
        for path in parent.iterdir():
            client.cancellation.check()
            require(time.monotonic() < client.deadline, "workflow-deadline")
            seen += 1
            require(seen <= 1024 and not path.is_symlink(), "angular-inventory-count-or-link")
            if path.is_dir():
                pending.append(path)
                continue
            require(path.is_file(), "angular-inventory-file")
            size = path.stat().st_size
            total += size
            require(total <= maximum_bytes, "angular-inventory-bytes")
            digest = file_digest(path, maximum_bytes, client.cancellation, client.deadline) if size else None
            entries[path.relative_to(directory).as_posix()] = (size, digest)
    return entries


def fixture_metadata(fixture):
    metadata = read_json(fixture / "fixture.json")
    require(metadata["schemaVersion"] == "latent.phase3.angular.fixture.v1"
            and metadata["tenant"] == TENANT and metadata["actualAngularBuild"] is True
            and metadata["reproducibility"] == "not-checked"
            and metadata["dependencyCompleteness"] == "declared-inputs-incomplete",
            "actual-angular-observation-required")
    records = {record["name"]: record for record in metadata["fixtures"]}
    require(len(metadata["fixtures"]) == 3 and set(records) == {"angular", "alternate", "missing-sbom"},
            "angular-fixture-profile")
    require(records["angular"]["componentDigest"] == records["alternate"]["componentDigest"]
            and records["angular"]["packageDigest"] != records["alternate"]["packageDigest"],
            "independent-publication-fixtures")
    return metadata, records


def publication_receipt(result, operation):
    require(result["outcomeKnown"] and result["category"] == "success", "web-mutation-uncertain")
    receipt = result["data"]["operation"]
    require(receipt["operationId"] == operation and receipt["publication"]["tenant"] == TENANT
            and receipt["actor"]["subject"] == "workflow-operator"
            and result["data"]["auditAck"] is not None, "web-mutation-identity-or-audit")
    return receipt


def publish(client, fixture, name, operation=None, evidence="evidence", codes=(0,)):
    operation = operation or "publish-" + name
    result = client.call("--rpc-timeout-ms", "30000", "web", "publish", fixture / name / "package",
                         "--evidence", fixture / name / evidence / "index.json",
                         "--operation-id", operation, "--expected-generation", "0", codes=codes, timeout=45)
    return publication_receipt(result, operation) if codes == (0,) else result


def prepare(client, publication, generation, wait=PREPARATION_MILLIS, codes=(0,)):
    result = client.call("--rpc-timeout-ms", str(wait), "web", "prepare", "--publication", publication,
                         "--lifecycle-generation", generation, "--maximum-wait-ms", str(wait),
                         codes=codes, timeout=wait / 1000 + 10)
    if codes == (0,):
        require(result["outcomeKnown"] and result["data"]["prepared"] is True
                and result["data"]["executionAuthorized"] is False
                and result["data"]["publication"]["id"] == publication
                and result["data"]["lifecycleGeneration"] == str(generation), "web-preparation-result")
    return result


def budget():
    return {"cpuFuel": 2000000000, "memoryBytes": 256 * MIB, "wallTimeLimitMillis": 5000,
            "childCalls": 0, "outboundRequests": 0, "stateReadBytes": 0, "stateWriteBytes": 0,
            "blobReadBytes": 0, "blobWriteBytes": 0, "logBytes": 0, "effectCount": 0}


def deployment_manifest(record, publication, name="angular", weight=10000):
    return {"apiVersion": "latent.dev/v1alpha1", "kind": "Deployment",
            "metadata": {"name": name, "tenant": TENANT},
            "spec": {"service": record["service"], "release": record["componentDigest"],
                     "publication": publication, "route": {"weight": weight}, "grants": [],
                     "resources": budget(),
                     "availability": {"minimumCachedCopies": 1, "minimumZones": 1},
                     "placement": {"trustClass": "internal", "architectures": ["x86_64"]}}}


def deploy(client, record, publication, operation, generation=0, name="angular", weight=10000):
    source = client.directory / f"{operation}.json"
    write_json(source, deployment_manifest(record, publication, name, weight))
    state = client.call("deployment", "get", name, "--operation-snapshot", codes=(0, 6))["data"]
    applied = client.call("deployment", "apply", source, "--operation-id", operation,
                          "--expected-generation", str(generation),
                          "--expected-state-version", state["stateVersion"])
    require(applied["outcomeKnown"], "web-deployment-uncertain")
    return client.call("deployment", "get", name)["data"]["deployment"]


def invocation_arguments(client, record, path, activation_id, route="angular"):
    source = client.directory / f"{activation_id}-input.json"
    resources = client.directory / f"{activation_id}-budget.json"
    write_json(source, [{"profile": "buffered-v1", "method": "get", "scheme": "http",
                         "authority": "alice.angular.test", "path": path, "query": {"none": None},
                         "headers": [], "media-type": {"none": None}, "body-base64": ""}])
    write_json(resources, {name: value for name, value in budget().items()
                           if name not in {"outboundRequests", "blobReadBytes", "blobWriteBytes"}})
    return ["--rpc-timeout-ms", "5000", "invoke", "--service", record["service"],
            "--contract", CONTRACT, "--function", "handle", "--route", route,
            "--activation-id", activation_id, "--input", source, "--budget", resources]


def invoke(client, record, publication, activation_id, path="/", route="angular", codes=(0,)):
    result = client.call(*invocation_arguments(client, record, path, activation_id, route), codes=codes)
    if codes != (0,):
        return result
    payload = result["data"]["payload"]
    require(result["outcomeKnown"] and payload["encoding"] == "base64"
            and payload["mediaType"] == MEDIA and len(payload["data"]) <= 256 * 1024,
            "angular-invocation-envelope")
    values = json.loads(base64.b64decode(payload["data"], validate=True))
    require(isinstance(values, list) and len(values) == 1 and values[0]["status"] == 200,
            "angular-invocation-response")
    html = base64.b64decode(values[0]["body-base64"], validate=True).decode("utf-8")
    require("ngh=" in html and "workflow-operator" in html
            and "lsf-private-server-fixture-234" not in html, "actual-angular-render")
    pin = result["data"]["resolvedRevision"]
    require(pin["publicationId"] == publication
            and pin["releaseDigest"] == record["componentDigest"], "selected-render-publication")
    return {"activationId": activation_id, "publication": publication, "revision": pin["revisionId"],
            "htmlDigest": "sha256:" + hashlib.sha256(html.encode()).hexdigest()}


def idle_inventory(client):
    inventory = client.call("node", "get", NODE_ID)["data"]["inventory"]
    require(inventory["health"]["ready"] and inventory["cacheSummary"]["available"], "angular-node-ready")
    require(all(cell["active"] == 0 and cell["queueDepth"] == 0 and cell["quarantined"] == 0
                for cell in inventory["cellCapacity"]), "angular-cells-not-reclaimed")
    require(inventory["quotas"]["usage"]["activeActivations"] == 0
            and inventory["cacheSummary"]["preparing"] == "0", "angular-owner-not-reclaimed")
    return {"cache": inventory["cacheSummary"], "cells": inventory["cellCapacity"],
            "quotas": inventory["quotas"]["usage"]}


def trigger(client, record, publication, deployment, revision, host, path="/", method="GET"):
    name = f"http-{client.calls}"
    source = client.directory / f"{name}.json"
    write_json(source, {"apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
                        "metadata": {"name": name, "tenant": TENANT},
                        "spec": {"target": {"service": record["service"], "contract": CONTRACT,
                                            "function": "handle", "route": "angular",
                                            "publication": publication, "revision": revision,
                                            "deploymentGeneration": int(deployment["generation"])},
                                 "configuration": {"profile": "buffered-v1", "scheme": "http", "host": host,
                                                   "path": path, "pathMatch": "exact", "method": method}}})
    state = client.call("trigger", "get", name, codes=(6,))["data"]["stateVersion"]
    result = client.call("trigger", "apply", source, "--operation-id", name, "--expected-generation", "0",
                         "--expected-state-version", state)
    require(result["outcomeKnown"], "angular-trigger-uncertain")
    return name


def http_response(client, node, host, path="/", method="GET", headers=None, expected=200):
    endpoint = node.startup_record.get("httpEndpoint", "")
    require(re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", endpoint), "angular-http-endpoint")
    require(time.monotonic() + 6 < client.deadline, "workflow-deadline")
    connection = http.client.HTTPConnection(endpoint, timeout=6)
    try:
        connection.request(method, path, headers={"Host": host, "Connection": "close", **(headers or {})})
        response = connection.getresponse()
        body = response.read(MIB + 1)
        accepted = expected if isinstance(expected, tuple) else (expected,)
        require(response.status in accepted, f"angular-http-status-{response.status}")
        require(len(body) <= MIB, "angular-http-body-size")
        fields = response.getheaders()
        require(len(fields) <= 64 and sum(len(name) + len(value) for name, value in fields) <= 16384,
                "angular-http-header-bound")
        return body, dict((name.lower(), value) for name, value in fields)
    finally:
        connection.close()
