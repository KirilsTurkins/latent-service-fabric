"""Read the real target RPC around signed Java deployment and binding changes."""
from copy import deepcopy
import re

from tools.java_http_composition.node import ADAPTER, DOMAIN, DOMAIN_CONTRACT, TENANT, WEB_CONTRACT
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase2_operator_scenario import NODE_ID

WRONG_TENANT_TOKEN = "LSF-PUBLIC-JAVA-OTHER-TENANT-TEST-ONLY"
INVOKER_TOKEN = "LSF-PUBLIC-JAVA-INVOKER-TEST-ONLY"


def arguments(name, *, route=True, publication=None, revision=None, routing_key=None, preparation=True):
    service, contract, function = (DOMAIN, DOMAIN_CONTRACT, "status") if name == "domain" else (ADAPTER, WEB_CONTRACT, "handle")
    result = ["--rpc-timeout-ms", "30000", "route", "target", "--service", service,
              "--contract", contract, "--function", function, "--maximum-wait-millis", "30000"]
    if route:
        result += ["--route", "java-http-" + name]
    if publication:
        result += ["--publication", publication]
    if revision:
        result += ["--revision", revision]
    if routing_key:
        result += ["--routing-key", routing_key]
    if preparation:
        result.append("--include-preparation")
    return result


def owners(client):
    inventory = client.call("node", "get", getattr(client, "node_id", NODE_ID))["data"]["inventory"]
    return {"cells": [{key: row[key] for key in ("active", "quarantined", "queueDepth")}
                      for row in inventory["cellCapacity"]], "quotas": inventory["quotas"]["usage"]}


def observe(client, name, *, expected=None, guard=True, state_name="coherent", **selectors):
    count = getattr(client, "java_inspections", 0)
    require(count < 32, "java-target-inspection-count")
    client.java_inspections = count + 1
    before = owners(client) if guard else None
    response = client.call(*arguments(name, **selectors), timeout=35)
    value = response["data"]
    require(value["schemaVersion"] == 1 and value["tenant"] == TENANT
        and value["liveGrantsChecked"] is False and value["stateName"] == state_name
        and (selectors.get("routing_key") or value["selectedRevisionId"] is None),
        "java-target-coherent-descriptive-observation")
    require(len(value["candidates"]) <= 32 and "receipt" not in value and "operation" not in value,
        "java-target-bounded-read-only-reply")
    if expected is not None:
        require(len(value["candidates"]) == expected, "java-target-candidate-count")
    if guard:
        require(before == owners(client), "java-target-inspection-acquired-execution-owners")
    return value


def selected(client, releases, publications, name):
    result = observe(client, name, publication=publications[name], expected=1)
    candidate = result["candidates"][0]
    release = next(row for row in read_json(releases / "release-set.json")["releases"]
                   if row["name"] == "java-http-" + name)
    preparation = candidate["preparation"]
    require(candidate["componentDigest"] == release["componentDigest"]
        and candidate["packageDigest"] == release["packageDigest"]
        and candidate["publication"] == {"tenant": TENANT, "id": publications[name]}
        and candidate["requestedPublication"] == candidate["publication"], "java-target-original-signed-identities")
    require(candidate["exportCompatible"] and candidate["eligible"]
        and candidate["httpCompatible"] == (name == "adapter"), "java-target-independent-export-http-compatibility")
    require(preparation["stateName"] == "ready" and preparation["diagnostic"] is None
        and preparation["profileName"] == ("wasmtime-service-values-v1" if name == "domain"
                                           else "wasmtime-buffered-web-values-v1"), "java-target-actual-selected-profile")
    require(re.fullmatch(r"blake3:[0-9a-f]{64}", preparation["engineConfigurationDigest"])
        and preparation["sealedMetadataFingerprint"] and preparation["engineVersion"]
        and preparation["targetTriple"] and preparation["cpuFeatureSet"] is not None,
        "java-target-original-engine-metadata")
    manifest = read_json(releases / ("java-http-" + name) / "package/layers/capsule.json")
    expected_imports = {row["contract"] for row in manifest["imports"]}
    require(set(preparation["imports"]) == expected_imports
        and int(preparation["importCount"]) == len(preparation["imports"]) + len(preparation["typeImports"]),
        "java-target-actual-callable-type-import-split")
    if name == "domain":
        require("examples:java-http-domain/types@1.0.0" in preparation["typeImports"],
            "java-target-shared-types-are-not-providers")
    contract = DOMAIN_CONTRACT if name == "domain" else WEB_CONTRACT
    function = "status" if name == "domain" else "handle"
    require({"contract": contract, "function": function} in preparation["exports"], "java-target-actual-export-tuple")
    declared = preparation["declaredBudget"]
    require(declared is not None and all(int(declared[field]) == int(value)
        for field, value in manifest["execution"]["limits"].items()), "java-target-original-declared-budget")
    return result


def authority(client):
    original = client.config
    result = {}
    for name, token, tenant in (("wrong-tenant", WRONG_TENANT_TOKEN, "other-examples"),
                               ("invoke-only", INVOKER_TOKEN, TENANT)):
        settings = deepcopy(read_json(original))
        settings["profiles"][0].update(token=token, tenant=tenant)
        path = client.directory / (name + "-inspection-client.json")
        write_json(path, settings)
        client.config = path
        try:
            observed = client.call(*arguments("adapter", preparation=False), codes=(0, 4, 6))
            if name == "wrong-tenant" and observed["category"] == "success":
                require(observed["data"]["tenant"] == tenant and not observed["data"]["candidates"],
                    "java-target-wrong-tenant-observed-foreign-publication")
            else:
                require(observed["category"] == "platform-failure" and observed["error"]["code"] == "permission-denied",
                    "java-target-management-authority-denial")
            result[name] = observed
        finally:
            client.config = original
    return result


def stale_policy(client, name, original):
    observed = observe(client, name, expected=1, preparation=False, state_name="stale")
    before, after = original["candidates"][0], observed["candidates"][0]
    require(not after["eligible"] and "policy-changed-or-revoked" in after["reasonNames"],
        "java-target-revoked-policy-not-current")
    old = {dependency["capability"]: dependency for dependency in before["dependencies"]}
    changed = [dependency for dependency in after["dependencies"] if dependency["state"] == "policy-changed-or-revoked"]
    require(changed and all(dependency["policies"] == old[dependency["capability"]]["policies"] for dependency in changed),
        "java-target-stale-original-policy-revisions-lost")
    return observed


def ordinary_http_binding(client, host, original):
    candidate = original["candidates"][0]
    source = client.directory / "ordinary-domain-http-trigger.json"
    write_json(source, {"apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
        "metadata": {"name": "java-ordinary-domain-http", "tenant": TENANT}, "spec": {
            "target": {"service": DOMAIN, "contract": DOMAIN_CONTRACT, "function": "status",
                "route": "java-http-domain", "publication": candidate["publication"]["id"],
                "revision": candidate["revisionId"], "deploymentGeneration": int(candidate["deploymentGeneration"])},
            "configuration": {"profile": "buffered-v1", "scheme": "http", "host": host,
                "path": "/ordinary-domain", "pathMatch": "exact", "method": "GET"}}})
    current = client.call("trigger", "get", "java-ordinary-domain-http", codes=(0, 6))["data"]
    denied = client.call("trigger", "apply", source, "--operation-id", "java-bind-ordinary-domain",
        "--expected-generation", 0, "--expected-state-version", current["stateVersion"], codes=(2, 4))
    require(denied["outcomeKnown"] and denied["category"] != "success", "java-target-ordinary-export-bound-as-http")
    recovered = client.call("trigger", "operation", "java-bind-ordinary-domain") if denied["requestDispatched"] else None
    after = client.call("trigger", "get", "java-ordinary-domain-http", codes=(6,))["data"]
    require(after["trigger"] is None, "java-target-ordinary-binding-created-object")
    return {"denied": denied, "originalOperation": recovered, "after": after}
