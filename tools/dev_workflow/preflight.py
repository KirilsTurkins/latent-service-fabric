"""Versioned, finite composition checks. No execution, signing or deployment.

Input declarations are structural evidence. Only an authenticated immutable
target observation can establish preparation; even that is not an invocation
receipt or a grant. Current authority remains the node's normal dispatch owner.
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import MAX_DOCUMENT, decode, digest, encode, members, require, sha
from . import paths
from .composition_contract import matrix_identity, validate_semantics

FORMAT = "latent.composition.v1"
RESULT = "latent.composition.preflight.v1"
MATRIX = "latent.composition.support.v1"
MAX_COMPONENTS = 8
MAX_CHECKS = 640
MAX_U64 = (1 << 64) - 1
BUDGETS = {"cpuFuel", "memoryBytes", "wallTimeLimitMillis", "childCalls", "outboundRequests",
           "stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes", "effectCount"}
U32_BUDGETS = {"childCalls", "outboundRequests", "effectCount"}
LANGUAGES = {"rust", "c", "java", "dotnet", "go", "typescript", "static"}
KINDS = {"capsule", "static-site"}
PROFILES = {"standalone-java-v1", "http-java-v1", "former-http-global-values-v1", "static-site-v1"}
WEB_CONTRACT = "latent:web/application@0.1.0"
CONTEXT_CONTRACT = "latent:context/context@0.1.0"
REMEDIATION = {
    "selected-component-preparation": "Review the producer stage/reason and measured bounds; use the maintained profile for the exact target and check the same bytes again.",
    "immutable-publication-selection-stale": "Review the current immutable publication/revision/deployment tuple and repeat the read-only check.",
    "immutable-publication-identities": "Select the actual admitted package and component; preserve their exact release and publication identity.",
    "observed-composition-changed-or-stale": "Review changed catalog, policy, provider and profile identities, then start a new read-only observation.",
    "selected-provider-binding-policy-current": "Select current installed provider, binding and policy digests; caller-specific grants remain enforced at dispatch.",
    "ordinary-context-provider-not-installed": "Use the documented ordinary-capsule context baseline; native sealed renderer context requires its own verified publication projection.",
    "http-minimum-wire-payload": "Select at least 2097152 wire payload bytes for the maintained HTTP node, with bounded request and response bodies.",
    "trigger-contract-publication-match": "Select the exact compatible export and publication kind for the intended trigger.",
    "actual-component-contract-surface": "Use imports and public export functions from the selected component's authoritative surface.",
}


def atom(value, maximum=256):
    require(isinstance(value, str) and len(value) <= maximum
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", value), "preflight-invalid-identity")
    return value


def contract(value):
    atom(value)
    require(re.fullmatch(r"[a-z][a-z0-9-]*:[a-z][a-z0-9-]*/[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+", value),
            "preflight-exact-contract-required")
    return value


def uint(value):
    require(isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value)
            and int(value) <= MAX_U64, "preflight-u64-decimal-string-required")
    return int(value)


def _array(value, maximum, code):
    require(isinstance(value, list) and len(value) <= maximum, code)
    return value


def _budget(value, *, partial=False):
    members(value, set() if partial else BUDGETS, BUDGETS if partial else set())
    for name, number in value.items():
        if name != "wallTimeLimitMillis" or number is not None:
            selected = uint(number)
            require(name not in U32_BUDGETS or selected <= (1 << 32) - 1, "preflight-resource-counter-bound")
    return value


def _component(value):
    common = {"id", "packageDigest", "language", "witShape", "publicationKind", "target", "imports", "exports"}
    optional = {"manifestPath", "manifestDigest", "headerNames", "dynamicHeaders", "captureBudget"}
    members(value, common, optional | {"componentDigest", "contractMetadataDigest", "releaseDigest", "budget", "componentPath",
                                     "metadataPath", "engineConfigurationDigest", "assetsDigest", "webManifestDigest"})
    static = value["publicationKind"] == "static-site"
    members(value, common | ({"assetsDigest", "webManifestDigest"} if static else {"componentDigest", "releaseDigest", "contractMetadataDigest", "budget"}),
            optional if static else optional | {"componentPath", "metadataPath", "engineConfigurationDigest"})
    atom(value["id"], 64)
    for name in ({"packageDigest", "webManifestDigest", "assetsDigest"} if static
                 else {"packageDigest", "componentDigest", "releaseDigest", "contractMetadataDigest"}):
        sha(value[name])
    require(value["language"] in LANGUAGES and value["publicationKind"] in KINDS, "preflight-unsupported-selection")
    require(value["witShape"] in {"nested-values-v1", "static-assets-v1", "resources", "futures", "streams", "unknown"},
            "preflight-unsupported-shape-selection")
    selector = {"publicationId", "webGeneration"} if static else {
        "service", "route", "revision", "publicationId", "deploymentId", "contract", "function"}
    target = members(value["target"], selector)
    for name, selected in target.items():
        if name == "webGeneration":
            require(uint(selected) > 0, "preflight-static-generation-required")
        else:
            contract(selected) if name == "contract" else atom(selected)
    imports = _array(value["imports"], 64, "preflight-import-count")
    for imported in imports:
        contract(imported)
    require(len(imports) == len(set(imports)), "preflight-duplicate-import")
    exports = _array(value["exports"], 32, "preflight-export-count")
    unique = set()
    for exported in exports:
        members(exported, {"contract", "functions"})
        selected = contract(exported["contract"])
        require(selected not in unique, "preflight-duplicate-export")
        unique.add(selected)
        functions = _array(exported["functions"], 64, "preflight-function-count")
        for function in functions:
            atom(function, 64)
        require(functions and len(functions) == len(set(functions)), "preflight-duplicate-or-empty-functions")
    if value["publicationKind"] == "static-site":
        require(value["language"] == "static" and value["witShape"] == "static-assets-v1"
                and not imports and not exports, "preflight-static-publication-is-not-invokable")
    if not static:
        _budget(value["budget"])
    for name in ("componentPath", "manifestPath", "metadataPath"):
        if name in value:
            paths.relative(value[name])
    if "manifestDigest" in value:
        sha(value["manifestDigest"])
    if "engineConfigurationDigest" in value:
        require(isinstance(value["engineConfigurationDigest"], str)
                and re.fullmatch(r"blake3:[0-9a-f]{64}", value["engineConfigurationDigest"]),
                "preflight-engine-configuration-digest")
    require(("manifestPath" in value) == ("manifestDigest" in value), "preflight-manifest-identity-required")
    if static and "manifestDigest" in value:
        require(value["manifestDigest"] == value["webManifestDigest"], "preflight-static-manifest-identity")
    if "headerNames" in value:
        for name in _array(value["headerNames"], 64, "preflight-header-count"):
            require(isinstance(name, str) and re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}", name),
                    "preflight-header-name-bound")
    require(type(value.get("dynamicHeaders", False)) is bool, "preflight-dynamic-header-boolean")
    return value


def validate(value):
    members(value, {"schemaVersion", "tenant", "nodeProfile", "components", "triggers", "serviceEdges", "providers", "policies"})
    require(value["schemaVersion"] == FORMAT, "preflight-unknown-version")
    atom(value["tenant"])
    profile = members(value["nodeProfile"], {"id", "javaGuest", "maximumWirePayloadBytes", "maximumRequestBodyBytes", "maximumResponseBodyBytes"})
    require(profile["id"] in PROFILES and type(profile["javaGuest"]) is bool, "preflight-node-profile")
    for name in ("maximumWirePayloadBytes", "maximumRequestBodyBytes", "maximumResponseBodyBytes"):
        uint(profile[name])
    components = _array(value["components"], MAX_COMPONENTS, "preflight-component-count")
    require(components, "preflight-empty-composition")
    for component in components:
        _component(component)
    ids = {component["id"] for component in components}
    require(len(ids) == len(components), "preflight-ambiguous-component")
    targets = [encode(component["target"]) for component in components]
    require(len(targets) == len(set(targets)), "preflight-ambiguous-target")
    for trigger in _array(value["triggers"], 16, "preflight-trigger-count"):
        members(trigger, {"kind", "component"}, {"contract", "function"})
        require(trigger["kind"] in {"http", "typed", "static"} and trigger["component"] in ids, "preflight-trigger-selection")
        members(trigger, {"kind", "component"} if trigger["kind"] == "static"
                else {"kind", "component", "contract", "function"})
        if trigger["kind"] != "static":
            contract(trigger["contract"])
            atom(trigger["function"], 64)
    for edge in _array(value["serviceEdges"], 16, "preflight-edge-count"):
        members(edge, {"from", "to", "contract", "function", "declaredGrantDigest", "requestBudget"})
        require(edge["from"] in ids and (edge["to"] is None or edge["to"] in ids), "preflight-edge-selection")
        static_ids = {component["id"] for component in components if component["publicationKind"] == "static-site"}
        require(edge["from"] not in static_ids and edge["to"] not in static_ids, "preflight-static-service-edge")
        contract(edge["contract"])
        atom(edge["function"], 64)
        sha(edge["declaredGrantDigest"])
        _budget(edge["requestBudget"], partial=True)
    for provider in _array(value["providers"], 32, "preflight-provider-count"):
        members(provider, {"contract", "providerProfile", "configurationDigest", "bindingId", "bindingDigest", "policyIds"},
                {"configurationEpoch"})
        contract(provider["contract"])
        atom(provider["providerProfile"], 128)
        atom(provider["bindingId"])
        sha(provider["configurationDigest"])
        sha(provider["bindingDigest"])
        for policy in _array(provider["policyIds"], 8, "preflight-provider-policy-count"):
            atom(policy)
        if "configurationEpoch" in provider:
            uint(provider["configurationEpoch"])
    for policy in _array(value["policies"], 32, "preflight-policy-count"):
        members(policy, {"id", "digest"})
        atom(policy["id"])
        sha(policy["digest"])
    require(len(encode(value)) <= MAX_DOCUMENT, "preflight-input-byte-limit")
    return validate_semantics(value)


def _check(checks, level, state, code, *, component=None, diagnostic=None):
    require(len(checks) < MAX_CHECKS, "preflight-result-count")
    require(state in {"passed", "failed", "unsupported", "untested", "not-checked"}, "preflight-result-state")
    require(level in {"structural", "authoritative-preparation", "authenticated-live-state", "executed-qualification"},
            "preflight-evidence-level")
    row = {"evidenceLevel": level, "state": state, "code": code}
    if component is not None:
        row["component"] = component
    if diagnostic is not None:
        row["diagnostic"] = diagnostic
    if state in {"failed", "unsupported"}:
        row["remediation"] = REMEDIATION.get(code, "Review the exact selection and versioned support matrix before a separate controlled qualification.")
    checks.append(row)


def structural(value, directory: Path | None = None):
    from .preflight_structure import inspect
    value = validate(value)
    checks, hops = inspect(value, directory, _check)
    return value, checks, hops


def run(value, *, directory: Path | None = None, observe=None):
    value, checks, hops = structural(value, directory)
    observation = {"state": "not-checked"}
    if observe is not None:
        from .preflight_observation import inspect
        observation = inspect(value, observe, checks, _check)
    else:
        _check(checks, "authoritative-preparation", "not-checked", "authenticated-target-observation-required")
        _check(checks, "authenticated-live-state", "not-checked", "current-authority-not-observed")
    _check(checks, "executed-qualification", "not-checked", "separate-controlled-qualification-required")
    result = {"schemaVersion": RESULT, "compositionDigest": digest(encode(value)), "supportMatrix": MATRIX,
              "supportMatrixDigest": matrix_identity(),
              "checks": checks, "serviceHops": hops, "observation": observation,
              "passed": not any(row["state"] in {"failed", "unsupported"} for row in checks),
              "fullyChecked": False, "executionAuthorized": False, "grantCreated": False,
              "reservationCreated": False, "trafficEnabled": False,
              "currentness": "observation-only-normal-admission-rechecks",
              "remainingBudget": "invocation-dependent", "dynamicTargets": "not-checked",
              "undeclaredEdges": "not-checked"}
    require(len(encode(result)) <= MAX_DOCUMENT, "preflight-result-byte-limit")
    return result


def load(path: Path):
    return validate(decode(paths.read(path.absolute().parent, path.name, MAX_DOCUMENT)))


def human(result):
    lines = ["Composition preflight: " + ("checks passed" if result["passed"] else "checks failed")]
    lines.extend(f"{row['evidenceLevel']}: {row['state']} ({row['code']})"
                 + (f" [{row['component']}]" if "component" in row else "") for row in result["checks"])
    if not result["passed"]:
        lines.append("Review the exact selections and the safe diagnostic; correct rejected profiles, exports or authority before qualification.")
    if result["observation"]["state"] == "changed":
        lines.append("The observed composition changed. Start a new read-only check against the reviewed current selection.")
    lines.append("Remaining budgets and dynamic targets depend on the actual invocation.")
    return "\n".join(lines) + "\n"
