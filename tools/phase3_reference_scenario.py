"""Real selected node/HTTP operations; no replay or synthetic response transport."""
from __future__ import annotations

import base64
import hashlib
from http.client import HTTPConnection
import json
import re
import time

from tools.phase2_operator_process import require, write_json
from tools.phase3_reference_config import HTTP_CAPABILITY
from tools.phase3_management_scenario import PROVIDER_CREDENTIAL
from tools.phase3_web_scenario import CONTRACT, MEDIA, MIB, TENANT, budget, deployment_manifest, idle_inventory, selected_client_asset

PRIVATE = (b"lsf-private-angular-reference-v1", b"lsf-private-reference-upstream", PROVIDER_CREDENTIAL)


def manifest(record, publication, name, weight=10000):
    value = deployment_manifest(record, publication, name, weight)
    value["spec"]["resources"]["outboundRequests"] = 1
    value["spec"]["grants"] = [{"capability": HTTP_CAPABILITY, "policy": "reference-http"}]
    return value


def deploy(client, record, publication):
    source = client.directory / "deploy-green.json"
    write_json(source, manifest(record, publication, "green"))
    state = client.call("deployment", "get", "green", "--operation-snapshot", codes=(6,))["data"]
    result = client.call("deployment", "apply", source, "--operation-id", "deploy-green",
                         "--expected-generation", "0", "--expected-state-version", state["stateVersion"])
    require(result["outcomeKnown"], "reference-deployment-uncertain")
    return client.call("deployment", "get", "green")["data"]["deployment"]


def invocation_arguments(client, activation, path="/", route="green"):
    source = client.directory / f"{activation}-input.json"
    resources = client.directory / f"{activation}-budget.json"
    write_json(source, [{"profile": "buffered-v1", "method": "get", "scheme": "http", "authority": client.host,
                         "path": path, "query": {"none": None}, "headers": [], "media-type": {"none": None}, "body-base64": ""}])
    limits = budget()
    limits["outboundRequests"] = 1
    write_json(resources, limits)
    arguments = ["--rpc-timeout-ms", "5000", "invoke", "--budget-profile", "phase3", "--service", "angular-reference", "--contract", CONTRACT,
                 "--function", "handle", "--activation-id", activation, "--input", source, "--budget", resources]
    if route is not None:
        arguments += ["--route", route]
    return arguments


def decode_render(result, records, publications, expected_status=200):
    require(result["outcomeKnown"] and result["category"] == "success", "reference-render-result")
    payload = result["data"]["payload"]
    require(payload["mediaType"] == MEDIA and payload["encoding"] == "base64"
            and len(payload["data"]) <= 256 * 1024, "reference-render-envelope")
    values = json.loads(base64.b64decode(payload["data"], validate=True))
    require(len(values) == 1 and values[0]["status"] == expected_status, "reference-application-status")
    html = base64.b64decode(values[0]["body-base64"], validate=True)
    pin = result["data"]["resolvedRevision"]
    selected = [name for name, publication in publications.items() if publication == pin["publicationId"]]
    require(len(selected) == 1, "reference-render-publication")
    name = selected[0]
    require(pin["releaseDigest"] == records[name]["componentDigest"] and records[name]["version"].encode() in html,
            "reference-render-source-version")
    require(b"ngh=" in html and all(private not in html for private in PRIVATE), "reference-hydration-private-data")
    selected_client_asset(records[name], publications[name], html.decode("utf-8"))
    return {"pin": pin, "version": records[name]["version"], "htmlDigest": "sha256:" + hashlib.sha256(html).hexdigest(),
            "applicationStatus": expected_status}


def invoke(client, records, publications, activation, path="/", route="green", expected_status=200):
    started = time.monotonic()
    result = client.call(*invocation_arguments(client, activation, path, route))
    observation = decode_render(result, records, publications, expected_status)
    observation.update(activationId=activation, roundTripMicros=int((time.monotonic() - started) * 1000000))
    return observation


def http(client, node, path="/", host=None, expected=200, method="GET", headers=None):
    endpoint = node.startup_record["httpEndpoint"]
    require(re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", endpoint), "reference-http-endpoint")
    require(time.monotonic() + 6 < client.deadline, "reference-http-deadline")
    connection = HTTPConnection(endpoint, timeout=6)
    try:
        connection.request(method, path, headers={"Host": host or client.host, "Connection": "close", **(headers or {})})
        response = connection.getresponse()
        body = response.read(MIB + 1)
        accepted = expected if isinstance(expected, tuple) else (expected,)
        require(response.status in accepted, f"reference-http-status-{response.status}")
        require(len(body) <= MIB and all(private not in body for private in PRIVATE), "reference-http-body-or-private-data")
        fields = response.getheaders()
        require(len(fields) <= 64 and sum(len(name) + len(value) for name, value in fields) <= 16384,
                "reference-http-header-bound")
        return body, dict((name.lower(), value) for name, value in fields)
    finally:
        connection.close()


def trigger(client, records, publications, name, ordinal):
    selected = invoke(client, records, publications, f"trigger-pin-{ordinal}", route=name)
    deployment = client.call("deployment", "get", name)["data"]["deployment"]
    source = client.directory / f"reference-trigger-{ordinal}.json"
    write_json(source, {"apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
        "metadata": {"name": "reference-http", "tenant": TENANT}, "spec": {"target": {
            "service": "angular-reference", "contract": CONTRACT, "function": "handle", "route": name,
            "publication": publications[name], "revision": selected["pin"]["revisionId"],
            "deploymentGeneration": int(deployment["generation"])}, "configuration": {"profile": "buffered-v1",
            "scheme": "http", "host": client.host, "path": "/", "pathMatch": "prefix", "method": "GET"}}})
    state = client.call("trigger", "get", "reference-http", codes=(0, 6))["data"]
    generation = state["trigger"]["generation"] if state["trigger"] is not None else "0"
    result = client.call("trigger", "apply", source, "--operation-id", f"trigger-{ordinal}",
                         "--expected-generation", generation, "--expected-state-version", state["stateVersion"])
    require(result["outcomeKnown"], "reference-trigger-uncertain")
    return selected


def assets(client, node, records, publications):
    before = idle_inventory(client)
    verified = []
    for name, record in records.items():
        require(1 <= len(record["assets"]) <= 8, "reference-asset-count")
        for asset in record["assets"]:
            path = "/_lsf/assets/" + publications[name] + asset["path"]
            body, headers = http(client, node, path)
            require(len(body) == asset["size"] and "sha256:" + hashlib.sha256(body).hexdigest() == asset["digest"],
                    "reference-immutable-asset-digest")
            require(headers["cache-control"] == "private, max-age=31536000, immutable"
                    and headers["content-type"] == asset["mediaType"], "reference-asset-headers")
            empty, _headers = http(client, node, path, method="HEAD")
            require(not empty, "reference-asset-head-body")
            empty, _headers = http(client, node, path, method="HEAD", expected=304, headers={"If-None-Match": headers["etag"]})
            require(not empty, "reference-asset-304-body")
            verified.append({"publication": publications[name], "path": asset["path"], "digest": asset["digest"]})
        for private in ("/server/renderer.wasm", "/metadata/web-application.json", "/package/sbom.cdx.json", "/../catalog.json"):
            http(client, node, "/_lsf/assets/" + publications[name] + private, expected=(400, 404))
        denied, fields = http(client, node, "/_lsf/assets/" + publications[name] + record["assets"][0]["path"],
                              host=client.foreign, expected=(403, 404))
        require(not denied and "etag" not in fields, "reference-foreign-asset-disclosure")
    for path in ("/catalog.json", "/data/catalog.json", "/_lsf/catalog", "/v1/catalog"):
        http(client, node, path, expected=404)
    after = idle_inventory(client)
    require(before["cache"] == after["cache"] and before["cells"] == after["cells"], "reference-assets-entered-render-cells")
    return {"assets": verified, "before": before, "after": after, "privatePathsDenied": True}
