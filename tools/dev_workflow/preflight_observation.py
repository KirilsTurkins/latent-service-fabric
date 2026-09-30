"""Bounded, authorized observations; no mixed-state positive result or invocation."""
from __future__ import annotations

import re

from .common import DevError, digest, encode, members, require, sha
from .preflight import BUDGETS, U32_BUDGETS, MAX_DOCUMENT, WEB_CONTRACT, atom, contract, uint

_STATES = {1: "coherent", 2: "stale", 3: "unavailable"}
_PREPARATION = {1: "ready", 2: "rejected", 3: "unavailable", 4: "not-requested"}
_PROFILES = {1: "wasmtime-service-values-v1", 2: "wasmtime-buffered-web-values-v1"}
_BINDING = {"configured-current", "policy-changed-or-revoked", "provider-unavailable",
            "publication-unavailable", "route-changed-or-unavailable", "inspection-indeterminate"}
_NUMERIC = {"configuredBound", "calculatedRequirement", "fixedBytes", "liftingFuel", "liftMultiplier"}


def diagnostic(value):
    if value is None:
        return None
    members(value, {"schemaVersion", "stage", "reason"}, {"stageName", "reasonName", "profile", "profileDigest"} | _NUMERIC)
    require(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1
            and type(value["stage"]) is int and 1 <= value["stage"] <= 8
            and type(value["reason"]) is int and 1 <= value["reason"] <= 16, "preflight-diagnostic-vocabulary")
    result = {name: value[name] for name in ("schemaVersion", "stage", "reason")}
    if value.get("profile") is not None:
        require(type(value["profile"]) is int and value["profile"] in _PROFILES, "preflight-diagnostic-profile")
        result["profile"] = value["profile"]
    if value.get("profileDigest") is not None:
        require(isinstance(value["profileDigest"], str) and re.fullmatch(r"[0-9a-f]{64}", value["profileDigest"]),
                "preflight-diagnostic-profile-digest")
        result["profileDigest"] = value["profileDigest"]
    for name in sorted(_NUMERIC):
        if value.get(name) is not None:
            uint(value[name])
            result[name] = value[name]
    return result


def _revision(value):
    members(value, {"id", "digest", "revision"})
    atom(value["id"])
    sha(value["digest"])
    uint(value["revision"])
    return {name: value[name] for name in ("id", "digest", "revision")}


def _dependency(value):
    members(value, {"capability", "state", "policyIdentityDigest", "providerConfigurationEpoch",
                    "binding", "policies", "providerProfile", "configurationDigest"})
    contract(value["capability"])
    require(value["state"] in _BINDING, "preflight-binding-state")
    require(isinstance(value["policyIdentityDigest"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["policyIdentityDigest"]), "preflight-policy-identity")
    atom(value["providerProfile"], 128)
    sha(value["configurationDigest"])
    uint(value["providerConfigurationEpoch"])
    require(isinstance(value["policies"], list) and len(value["policies"]) <= 8, "preflight-policy-count")
    policies = sorted((_revision(row) for row in value["policies"]), key=lambda row: row["id"])
    require(len({row["id"] for row in policies}) == len(policies), "preflight-policy-ambiguity")
    return {**value, "binding": _revision(value["binding"]), "policies": policies}


def _preparation(value):
    required = {"state", "stateName", "diagnostic", "profile", "profileName", "engineVersion",
                "engineConfigurationDigest", "targetTriple", "cpuFeatureSet", "sealedMetadataFingerprint",
                "importCount", "functionCount", "hostcallFuel", "maximumLiftedBytes", "maximumTypeNodes",
                "declaredBudget", "imports", "typeImports", "exports"}
    members(value, required)
    require(type(value["state"]) is int and _PREPARATION.get(value["state"]) == value["stateName"],
            "preflight-preparation-state")
    details = diagnostic(value["diagnostic"])
    result = {"state": value["state"], "diagnostic": details}
    if value["state"] != 1:
        if details and "profileDigest" in details:
            result["engineConfigurationDigest"] = "blake3:" + details["profileDigest"]
        return result
    require(type(value["profile"]) is int and _PROFILES.get(value["profile"]) == value["profileName"],
            "preflight-preparation-profile")
    require(isinstance(value["engineConfigurationDigest"], str)
            and re.fullmatch(r"blake3:[0-9a-f]{64}", value["engineConfigurationDigest"]), "preflight-engine-key")
    for name in ("engineVersion", "targetTriple"):
        atom(value[name], 128)
    require(isinstance(value["cpuFeatureSet"], str) and len(value["cpuFeatureSet"]) <= 1024, "preflight-engine-cpu-bound")
    require(value["sealedMetadataFingerprint"] is None or isinstance(value["sealedMetadataFingerprint"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["sealedMetadataFingerprint"]), "preflight-metadata-fingerprint")
    for name in ("importCount", "functionCount", "hostcallFuel", "maximumLiftedBytes", "maximumTypeNodes"):
        uint(value[name])
    budget = dict(members(value["declaredBudget"], BUDGETS))
    for name in U32_BUDGETS:
        require(type(budget[name]) is int and 0 <= budget[name] <= (1 << 32) - 1, "preflight-prepared-counter-bound")
        budget[name] = str(budget[name])
    for name, number in budget.items():
        if name != "wallTimeLimitMillis" or number is not None:
            uint(number)
    require(isinstance(value["imports"], list) and isinstance(value["typeImports"], list)
            and len(value["imports"]) + len(value["typeImports"]) <= 64
            and isinstance(value["exports"], list) and len(value["exports"]) <= 2048, "preflight-surface-bound")
    imports = sorted(contract(row) for row in value["imports"])
    type_imports = sorted(contract(row) for row in value["typeImports"])
    exports = []
    for row in value["exports"]:
        members(row, {"contract", "function"})
        exports.append((contract(row["contract"]), atom(row["function"], 64)))
    require(len(set(imports + type_imports)) == len(imports) + len(type_imports)
            and len(set(exports)) == len(exports), "preflight-surface-ambiguity")
    require(uint(value["importCount"]) == len(imports) + len(type_imports), "preflight-surface-import-count")
    # Only closed identities, bounded counts and the actual surface are retained;
    # CPU labels and arbitrary diagnostic names never enter the public result.
    return {**result, "profile": value["profile"], "engineConfigurationDigest": value["engineConfigurationDigest"],
            "engineVersion": value["engineVersion"], "targetTriple": value["targetTriple"],
            "cpuFeatureSetDigest": digest(value["cpuFeatureSet"].encode()),
            "sealedMetadataFingerprint": value["sealedMetadataFingerprint"],
            "imports": imports, "typeImports": type_imports, "exports": sorted(exports), "declaredBudget": budget,
            **{name: value[name] for name in ("importCount", "functionCount", "hostcallFuel", "maximumLiftedBytes", "maximumTypeNodes")}}


def _snapshot(value, component, tenant):
    require(isinstance(value, dict) and len(encode(value)) <= MAX_DOCUMENT, "preflight-observation-byte-limit")
    require(value.get("schemaVersion") == "latent.cli.result.v1" and value.get("outcomeKnown") is True
            and value.get("category") == "success", "preflight-authenticated-observation-unavailable")
    data = members(value["data"], {"schemaVersion", "tenant", "service", "contract", "function", "route", "state", "stateName",
                   "catalogTransaction", "routeGeneration", "bindingGeneration", "policyStoreGeneration", "candidates",
                   "selectedRevisionId", "liveGrantsChecked"})
    require(type(data["schemaVersion"]) is int and data["schemaVersion"] == 1 and data["tenant"] == tenant,
            "preflight-observation-owner")
    for name in ("service", "contract", "function", "route"):
        require(data[name] == component["target"][name], "preflight-observation-selector")
    require(type(data["state"]) is int and _STATES.get(data["state"]) == data["stateName"]
            and data["liveGrantsChecked"] is False, "preflight-observation-state")
    stamp = {name: data[name] for name in ("catalogTransaction", "routeGeneration", "bindingGeneration", "policyStoreGeneration")}
    for name, number in stamp.items():
        if name != "policyStoreGeneration" or number is not None:
            uint(number)
    require(isinstance(data["candidates"], list) and len(data["candidates"]) <= 32, "preflight-candidate-bound")
    candidates = []
    for row in data["candidates"]:
        members(row, {"deploymentId", "deploymentGeneration", "revisionId", "componentDigest", "publication",
                      "requestedPublication", "packageDigest", "publicationGeneration", "routingWeight", "exportCompatible",
                      "httpCompatible", "eligible", "reasons", "reasonNames", "dependencies", "preparation", "publicationKind", "httpBindings"})
        atom(row["deploymentId"])
        atom(row["revisionId"])
        sha(row["componentDigest"])
        uint(row["deploymentGeneration"])
        if row["packageDigest"] is not None:
            sha(row["packageDigest"])
        if row["publicationGeneration"] is not None:
            uint(row["publicationGeneration"])
        for name in ("publication", "requestedPublication"):
            if row[name] is not None:
                members(row[name], {"tenant", "id"})
                require(row[name]["tenant"] == tenant, "preflight-publication-owner")
                atom(row[name]["id"])
        require(type(row["routingWeight"]) is int and 0 <= row["routingWeight"] <= 10000
                and all(type(row[name]) is bool for name in ("exportCompatible", "httpCompatible", "eligible")),
                "preflight-candidate-eligibility")
        require(isinstance(row["reasons"], list) and len(row["reasons"]) <= 10
                and all(type(reason) is int and 1 <= reason <= 10 for reason in row["reasons"]), "preflight-candidate-reason")
        require(isinstance(row["dependencies"], list) and len(row["dependencies"]) <= 32, "preflight-dependency-bound")
        dependencies = sorted((_dependency(item) for item in row["dependencies"]), key=lambda item: item["capability"])
        require(len({item["capability"] for item in dependencies}) == len(dependencies), "preflight-dependency-ambiguity")
        require(row["publicationKind"] is None or row["publicationKind"] == "capsule", "preflight-publication-kind")
        require(isinstance(row["httpBindings"], list) and len(row["httpBindings"]) <= 32, "preflight-http-binding-bound")
        bindings = []
        for binding in row["httpBindings"]:
            members(binding, {"id", "generation", "selectedDeploymentGeneration", "state"})
            atom(binding["id"], 128)
            uint(binding["generation"])
            uint(binding["selectedDeploymentGeneration"])
            require(binding["state"] in {"configured-current", "deployment-changed"}, "preflight-http-binding-state")
            bindings.append(binding)
        require(len({row["id"] for row in bindings}) == len(bindings), "preflight-http-binding-ambiguity")
        candidates.append({**{key: item for key, item in row.items() if key != "reasonNames"}, "dependencies": dependencies,
                           "preparation": _preparation(row["preparation"]), "httpBindings": sorted(bindings, key=lambda item: item["id"])})
    require(len({row["revisionId"] for row in candidates}) == len(candidates), "preflight-candidate-ambiguity")
    return {"state": data["state"], "stamp": stamp, "candidates": sorted(candidates, key=lambda row: row["revisionId"])}


def _component(component, snapshot, value, checks, add):
    identity = component["target"]
    selected = [row for row in snapshot["candidates"] if row["deploymentId"] == identity["deploymentId"]
                and row["revisionId"] == identity["revision"] and row["publication"] is not None
                and row["publication"]["id"] == identity["publicationId"]]
    if len(selected) != 1:
        add(checks, "authenticated-live-state", "failed", "immutable-publication-selection-stale", component=component["id"])
        return
    row = selected[0]
    matched = (row["componentDigest"] == component["componentDigest"] == component["releaseDigest"]
               and row["packageDigest"] == component["packageDigest"] and row["publicationKind"] == component["publicationKind"])
    add(checks, "authenticated-live-state", "passed" if matched else "failed", "immutable-publication-identities", component=component["id"])
    add(checks, "authenticated-live-state", "passed" if row["eligible"] and row["exportCompatible"] else "failed",
        "current-target-eligibility", component=component["id"])
    if any(trigger["kind"] == "http" and trigger["component"] == component["id"] for trigger in value["triggers"]):
        current_http = row["httpCompatible"] and any(binding["state"] == "configured-current"
            and binding["selectedDeploymentGeneration"] == row["deploymentGeneration"] for binding in row["httpBindings"])
        add(checks, "authenticated-live-state", "passed" if current_http else "not-checked",
            "existing-http-trigger-target-current" if current_http else "http-trigger-not-currently-bound", component=component["id"])
    prepared = row["preparation"]
    state = {1: "passed", 2: "failed", 3: "not-checked", 4: "not-checked"}[prepared["state"]]
    add(checks, "authoritative-preparation", state, "selected-component-preparation", component=component["id"], diagnostic=prepared["diagnostic"])
    expected_engine = component.get("engineConfigurationDigest")
    if expected_engine is None:
        add(checks, "authoritative-preparation", "not-checked", "intended-engine-configuration-digest-required", component=component["id"])
    else:
        add(checks, "authoritative-preparation", "passed" if expected_engine == prepared.get("engineConfigurationDigest") else "failed",
            "exact-engine-configuration-identity", component=component["id"])
    if prepared["state"] != 1:
        return {"component": component["id"], "state": _PREPARATION[prepared["state"]],
                "engineConfigurationDigest": prepared.get("engineConfigurationDigest")}
    declared_exports = sorted((item["contract"], function) for item in component["exports"] for function in item["functions"])
    surface = sorted(component["imports"]) == sorted(prepared["imports"] + prepared["typeImports"])
    surface = surface and declared_exports == prepared["exports"]
    add(checks, "authoritative-preparation", "passed" if surface else "failed", "actual-component-contract-surface", component=component["id"])
    add(checks, "authoritative-preparation", "passed" if component["budget"] == prepared["declaredBudget"] else "failed",
        "actual-declared-resource-budget", component=component["id"])
    expected_profile = 2 if identity["contract"] == WEB_CONTRACT and identity["function"] == "handle" else 1
    add(checks, "authoritative-preparation", "passed" if prepared["profile"] == expected_profile else "failed",
        "selected-signature-profile", component=component["id"])
    add(checks, "authoritative-preparation", "not-checked", "signed-contract-document-hash-not-projected", component=component["id"])
    _providers(component, prepared["imports"], row["dependencies"], value, checks, add)
    return {"component": component["id"], "state": "ready", "profile": prepared["profile"],
            "metadataFingerprintFormat": "lsf-wasmtime-preparation-metadata-v2",
            **{name: prepared[name] for name in ("engineConfigurationDigest", "sealedMetadataFingerprint", "importCount",
                                               "functionCount", "hostcallFuel", "maximumLiftedBytes", "maximumTypeNodes")}}


def _providers(component, imports, dependencies, value, checks, add):
    declarations = {row["contract"]: row for row in value["providers"]}
    policies = {row["id"]: row["digest"] for row in value["policies"]}
    if set(imports) - {row["capability"] for row in dependencies}:
        add(checks, "authenticated-live-state", "failed", "required-provider-binding-not-observed", component=component["id"])
    for dependency in dependencies:
        selected = declarations.get(dependency["capability"])
        if selected is None:
            add(checks, "authenticated-live-state", "failed", "required-provider-not-selected", component=component["id"])
            continue
        actual_policies = {row["id"]: row["digest"] for row in dependency["policies"]}
        expected_policies = {name: policies[name] for name in selected["policyIds"]}
        valid = (dependency["state"] == "configured-current" and dependency["providerProfile"] == selected["providerProfile"]
                 and dependency["configurationDigest"] == selected["configurationDigest"]
                 and dependency["binding"]["id"] == selected["bindingId"] and dependency["binding"]["digest"] == selected["bindingDigest"]
                 and actual_policies == expected_policies and ("configurationEpoch" not in selected
                    or dependency["providerConfigurationEpoch"] == selected["configurationEpoch"]))
        add(checks, "authenticated-live-state", "passed" if valid else "failed", "selected-provider-binding-policy-current", component=component["id"])


def inspect(value, observe, checks, add):
    components = [row for row in value["components"] if row["publicationKind"] == "capsule"]
    if len(components) != len(value["components"]):
        add(checks, "authenticated-live-state", "not-checked", "static-publication-requires-native-web-inspection")
    if not components:
        return {"state": "not-checked"}
    before, after = [], []
    try:
        for collection in (before, after):
            for component in components:
                collection.append(_snapshot(observe(component, preparation=True), component, value["tenant"]))
    except (DevError, OSError, ValueError, KeyError, TypeError):
        add(checks, "authenticated-live-state", "failed", "authenticated-target-observation-unavailable")
        return {"state": "unavailable"}
    stamps = [row["stamp"] for row in before + after]
    coherent = all(row["state"] == 1 for row in before + after) and all(stamp == stamps[0] for stamp in stamps)
    coherent = coherent and all(encode(first) == encode(last) for first, last in zip(before, after))
    if not coherent:
        add(checks, "authenticated-live-state", "failed", "observed-composition-changed-or-stale")
        return {"state": "changed", "authorizationCreated": False}
    if stamps[0]["policyStoreGeneration"] is None:
        add(checks, "authenticated-live-state", "not-checked", "coherent-policy-store-generation-unavailable")
    else:
        add(checks, "authenticated-live-state", "passed", "coherent-authorized-composition-observation")
    selected_components = [result for component, snapshot in zip(components, before)
                           if (result := _component(component, snapshot, value, checks, add)) is not None]
    engine_keys = sorted({row["preparation"]["engineConfigurationDigest"] for snapshot in before for row in snapshot["candidates"]
                         if "engineConfigurationDigest" in row["preparation"]})
    return {"state": "coherent" if stamps[0]["policyStoreGeneration"] is not None else "partial", **stamps[0],
            "engineConfigurationDigests": engine_keys, "components": selected_components,
            "liveGrantsChecked": False, "authorizationCreated": False,
            "expiration": "current-state-at-observation-normal-dispatch-rechecks"}
