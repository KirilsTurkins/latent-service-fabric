"""Structural input and immutable-byte observations, never runtime authority."""
from .common import require
from . import paths
from .preflight import BUDGETS, CONTEXT_CONTRACT, WEB_CONTRACT, uint
from .composition_contract import selection_support, support_matrix


def exports(component, contract, function):
    return any(row["contract"] == contract and function in row["functions"] for row in component["exports"])


def _bytes(component, directory, checks, add):
    for path_field, digest_field, maximum in (
        ("componentPath", "componentDigest", 32 * 1024 * 1024),
        ("manifestPath", "manifestDigest", 256 * 1024),
        ("metadataPath", "contractMetadataDigest", 1024 * 1024),
    ):
        if path_field not in component:
            continue
        require(directory is not None, "preflight-input-directory-required")
        actual, _ = paths.digest_file(directory, component[path_field], maximum)
        add(checks, "structural", "passed" if actual == component[digest_field] else "failed",
            "immutable-selected-bytes-match" if actual == component[digest_field] else "immutable-selected-bytes-changed",
            component=component["id"])


def _headers(component, checks, add):
    if "headerNames" not in component and not component.get("dynamicHeaders"):
        return
    try:
        from tools.browser_response_ownership import inspect_declared_header_names
    except ImportError:
        add(checks, "structural", "not-checked", "response-ownership-tool-version-required", component=component["id"])
        return
    result = inspect_declared_header_names(component.get("headerNames", []), dynamic=component.get("dynamicHeaders", False))
    add(checks, "structural", "failed" if result["conflicts"] else "passed", "declared-response-header-ownership",
        component=component["id"])
    if result["dynamicOutputRequiresExecution"]:
        add(checks, "executed-qualification", "not-checked", "dynamic-response-output-requires-validation", component=component["id"])


def _capture(component, checks, add):
    if "captureBudget" not in component:
        return
    budget = component["captureBudget"]
    require(isinstance(budget, dict) and budget.get("schemaVersion") == "latent.static-site.budget.v1", "preflight-capture-budget-version")
    # This is a capture diagnostic, not signed authority or final node capacity.
    add(checks, "structural", "not-checked", "capture-budget-requires-original-capture-and-current-admission", component=component["id"])


def _component(component, profile, checks, add):
    supported = selection_support(component, profile)
    add(checks, "structural", "passed" if supported["state"] == "supported" else supported["state"],
        supported["code"], component=component["id"],
        diagnostic={"schemaVersion": 1, "stage": 4, "reason": 6}
        if supported["code"] == "ordinary-context-provider-not-installed" else None)
    selected = component["target"]
    if component["publicationKind"] != "static-site":
        valid = exports(component, selected["contract"], selected["function"])
        add(checks, "structural", "passed" if valid else "failed", "declared-target-export-match", component=component["id"])
    if component["witShape"] in {"resources", "futures", "streams"}:
        add(checks, "structural", "unsupported" if component["language"] == "java" else "untested", "selected-java-wit-shape-unsupported" if component["language"] == "java"
            else "shape-requires-language-owned-qualification", component=component["id"])
    elif component["witShape"] == "unknown" or component["language"] not in {"java", "static"}:
        add(checks, "structural", "untested", "selected-combination-needs-source-matched-owner-evidence", component=component["id"])
    else:
        add(checks, "structural", "passed", "declared-profile-has-maintained-qualification-owner", component=component["id"])
    if component["language"] == "java" and not profile["javaGuest"]:
        add(checks, "structural", "unsupported", "java-engine-profile-not-selected", component=component["id"])
    if component["language"] == "java":
        if len(component["exports"]) != 1:
            add(checks, "structural", "unsupported", "maintained-java-single-export-interface", component=component["id"])
        versions = {}
        for selected_contract in component["imports"] + [row["contract"] for row in component["exports"]]:
            base, version = selected_contract.rsplit("@", 1)
            versions.setdefault(base, set()).add(version)
        if any(len(selected_versions) > 1 for selected_versions in versions.values()):
            add(checks, "structural", "unsupported", "maintained-java-version-alias-unsupported", component=component["id"])
    # Capsule declarations/HTTP targets cannot create the private CheckedWebLayout
    # renderer projection that owns implicit context in the native web workflow.
    if CONTEXT_CONTRACT in component["imports"]:
        add(checks, "structural", "unsupported", "ordinary-context-provider-not-installed", component=component["id"],
            diagnostic={"schemaVersion": 1, "stage": 4, "reason": 6})


def _trigger(trigger, components, profile, checks, add):
    component = components[trigger["component"]]
    kind = trigger["kind"]
    valid = (component["publicationKind"] == "static-site") if kind == "static" else exports(component, trigger["contract"], trigger["function"])
    if kind == "http":
        valid = valid and trigger["contract"] == WEB_CONTRACT and trigger["function"] == "handle"
        add(checks, "structural", "passed" if profile["id"] == "http-java-v1" else "failed", "http-ingress-profile-required", component=component["id"])
        add(checks, "structural", "passed" if uint(profile["maximumWirePayloadBytes"]) >= 2 * 1024 * 1024 else "failed",
            "http-minimum-wire-payload", component=component["id"])
        add(checks, "structural", "passed" if uint(profile["maximumRequestBodyBytes"]) <= 65536
            and uint(profile["maximumResponseBodyBytes"]) <= 65536 else "unsupported", "buffered-http-body-profile", component=component["id"])
    if kind != "static" and component["publicationKind"] == "static-site":
        valid = False
    add(checks, "structural", "passed" if valid else "failed", "trigger-contract-publication-match", component=component["id"])


def _edges(value, components, checks, add):
    result = []
    for index, edge in enumerate(value["serviceEdges"]):
        parent = components[edge["from"]]
        if edge["to"] is None:
            result.append({"edge": index, "state": "not-checked", "code": "unresolved-dynamic-service-edge"})
            continue
        child = components[edge["to"]]
        valid = child["publicationKind"] != "static-site" and exports(child, edge["contract"], edge["function"])
        add(checks, "structural", "passed" if valid else "failed", "declared-child-export-match", component=child["id"])
        maximum = {name: str(min(uint(parent["budget"][name]), uint(child["budget"][name]),
                    uint(edge["requestBudget"].get(name, parent["budget"][name]))))
                   for name in sorted(BUDGETS - {"wallTimeLimitMillis"})}
        wall_limits = [selected for selected in (parent["budget"]["wallTimeLimitMillis"],
                       child["budget"]["wallTimeLimitMillis"], edge["requestBudget"].get("wallTimeLimitMillis"))
                       if selected is not None]
        maximum["wallTimeLimitMillis"] = str(min(map(uint, wall_limits))) if wall_limits else "invocation-dependent"
        result.append({"edge": index, "parent": parent["id"], "child": child["id"],
                       "principal": "host-derived-service", "callerService": parent["target"]["service"],
                       "claims": "not-forwarded-by-the-maintained-local-service-profile",
                       "maximumDeclaredShare": maximum, "currentGrantCeiling": "not-checked",
                       "remainingShare": "invocation-dependent", "deadline": "bounded-by-original-parent-and-child",
                       "authorizationCreated": False})
    return result


def inspect(value, directory, add):
    checks = []
    add(checks, "structural", "passed", "closed-versioned-composition-input")
    components = {item["id"]: item for item in value["components"]}
    for component in components.values():
        _component(component, value["nodeProfile"], checks, add)
        _bytes(component, directory, checks, add)
        _headers(component, checks, add)
        _capture(component, checks, add)
        declared = {item["contract"] for item in value["providers"]}
        configured = set(support_matrix()["recognizedImports"]["configuredBindingContracts"])
        missing = any(imported in configured and imported not in declared for imported in component["imports"])
        add(checks, "structural", "failed" if missing else "passed", "declared-provider-installations", component=component["id"])
        if any(imported not in configured and imported != CONTEXT_CONTRACT for imported in component["imports"]):
            add(checks, "structural", "not-checked", "unclassified-import-requires-actual-surface-inspection", component=component["id"])
        add(checks, "authenticated-live-state", "not-checked", "caller-dependent-current-grants-require-dispatch", component=component["id"])
    for trigger in value["triggers"]:
        _trigger(trigger, components, value["nodeProfile"], checks, add)
    used = {policy for provider in value["providers"] for policy in provider["policyIds"]}
    if any(policy["id"] not in used for policy in value["policies"]):
        add(checks, "authenticated-live-state", "not-checked", "unreferenced-declared-policy-selection")
    return checks, _edges(value, components, checks, add)
