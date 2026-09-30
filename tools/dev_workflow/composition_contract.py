"""Finite composition declarations and source-backed support, never authority.

The input JSON Schema and the existing preflight field validator own shape.
These supplementary checks reject ambiguous selections. The capture validator
interprets only the subset used by the immutable capture diagnostic schema;
it neither reconstructs a capture nor recalculates resource headroom.
"""
from __future__ import annotations

import math
from importlib import resources
from pathlib import Path
import re

from .common import DevError, MAX_DOCUMENT, decode, digest, encode, require
from . import paths

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = "contracts/dev/composition-support-v1.json"
SCHEMA_PATH = "schemas/dev-composition-input.schema.json"
CAPTURE_SCHEMA_PATH = "schemas/static-site-budget.schema.json"
MATRIX = "latent.composition.support.v1"
CONTEXT = "latent:context/context@0.1.0"
MAX_U64 = (1 << 64) - 1
MAX_U32 = (1 << 32) - 1
U32_COUNTERS = {"childCalls", "outboundRequests", "effectCount"}
MAX_SCHEMA_BYTES = 65536
MAX_SCHEMA_NODES = 4096


def _document(name):
    try:
        packaged = resources.files("tools.dev_workflow").joinpath("data/" + name)
        selected = packaged if packaged.is_file() else ROOT / name
        with selected.open("rb") as source:
            value = decode(source.read(MAX_SCHEMA_BYTES + 1), MAX_SCHEMA_BYTES)
        require(isinstance(value, dict), "preflight-support-contract-shape")
        return value
    except OSError as error:
        raise DevError("preflight-support-contract-not-packaged") from error


def support_matrix():
    value = _document(MATRIX_PATH)
    require(value.get("schemaVersion") == MATRIX, "preflight-support-matrix-version")
    require(isinstance(value.get("rows"), list) and 0 < len(value["rows"]) <= 32,
            "preflight-support-matrix-bound")
    return value


def input_schema():
    return _document(SCHEMA_PATH)


def _unique(values, code):
    seen = set()
    for value in values:
        key = encode(value)
        require(key not in seen, code)
        seen.add(key)


def _uint(value):
    require(isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value)
            and int(value) <= MAX_U64, "preflight-u64-decimal-string-required")


def _budget_number(key, number):
    if key == "wallTimeLimitMillis" and number is None:
        return
    _uint(number)
    if key in U32_COUNTERS:
        require(int(number) <= MAX_U32, "preflight-resource-counter-bound")


def validate_semantics(value):
    """Complement schema/field checks; no root preflight import or execution."""
    require(isinstance(value, dict), "document-object-required")
    require(len(encode(value)) <= MAX_DOCUMENT, "preflight-input-byte-limit")
    components = value["components"]
    _unique((item["id"] for item in components), "preflight-ambiguous-component")
    _unique((item["target"] for item in components), "preflight-ambiguous-target")
    selected = {item["id"]: item for item in components}
    for item in components:
        require(re.fullmatch(r"publication:sha256:[0-9a-f]{64}", item["target"]["publicationId"]),
                "preflight-publication-identity-required")
        if item["publicationKind"] == "static-site":
            _uint(item["target"]["webGeneration"])
            require(int(item["target"]["webGeneration"]) > 0, "preflight-static-web-generation-required")
            if "manifestDigest" in item:
                require(item["manifestDigest"] == item["webManifestDigest"],
                        "preflight-static-manifest-identity-required")
        else:
            require(re.fullmatch(r"revision-v1:sha256:[0-9a-f]{64}", item["target"]["revision"]),
                    "preflight-revision-identity-required")
        _unique(item["imports"], "preflight-duplicate-import")
        _unique((row["contract"] for row in item["exports"]), "preflight-duplicate-export")
        for exported in item["exports"]:
            _unique(exported["functions"], "preflight-duplicate-or-empty-functions")
        for key, number in item.get("budget", {}).items():
            _budget_number(key, number)
        for field in ("componentPath", "manifestPath", "metadataPath"):
            if field in item:
                paths.relative(item[field])
        for name in item.get("headerNames", []):
            require(re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}", name),
                    "preflight-header-name-bound")
        if "captureBudget" in item:
            validate_capture_budget(item["captureBudget"])
    for field in ("maximumWirePayloadBytes", "maximumRequestBodyBytes", "maximumResponseBodyBytes"):
        _uint(value["nodeProfile"][field])
    _unique((row["bindingId"] for row in value["providers"]), "preflight-ambiguous-provider-binding")
    _unique((row["contract"] for row in value["providers"]), "preflight-ambiguous-provider-contract")
    _unique((row["id"] for row in value["policies"]), "preflight-ambiguous-policy")
    policies = {row["id"] for row in value["policies"]}
    for provider in value["providers"]:
        _unique(provider["policyIds"], "preflight-duplicate-provider-policy")
        require(all(policy in policies for policy in provider["policyIds"]), "preflight-provider-policy-selection")
        if "configurationEpoch" in provider:
            _uint(provider["configurationEpoch"])
    _unique(value["triggers"], "preflight-duplicate-trigger")
    _unique(([row["from"], row["to"], row["contract"], row["function"]]
             for row in value["serviceEdges"]), "preflight-ambiguous-service-edge")
    for trigger in value["triggers"]:
        require(trigger["component"] in selected, "preflight-trigger-selection")
        if trigger["kind"] == "static":
            require(selected[trigger["component"]]["publicationKind"] == "static-site",
                    "preflight-static-trigger-selection")
    for edge in value["serviceEdges"]:
        require(edge["from"] in selected and (edge["to"] is None or edge["to"] in selected),
                "preflight-edge-selection")
        require(selected[edge["from"]]["publicationKind"] != "static-site"
                and (edge["to"] is None or selected[edge["to"]]["publicationKind"] != "static-site"),
                "preflight-static-service-edge")
        for key, number in edge["requestBudget"].items():
            _budget_number(key, number)
    return value


def java_declaration_reason(component):
    """Early declared-surface feedback; the actual WIT graph remains required."""
    if component["language"] != "java":
        return None
    if len(component["exports"]) != 1:
        return "java-public-export-interface-unsupported"
    interfaces = [*component["imports"], *(row["contract"] for row in component["exports"])]
    bases = [value.rsplit("@", 1)[0] for value in interfaces]
    if len(set(bases)) != len(bases):
        return "java-interface-alias-unsupported"
    return None


def selection_support(component, node_profile):
    """Describe declared support only; never report preparation or permission."""
    matrix = support_matrix()
    reason = java_declaration_reason(component)
    if reason is not None:
        return {"state": "unsupported", "code": reason, "supportMatrix": MATRIX,
                "evidenceLevel": "structural", "executionQualified": False}
    selectors = {"language": component["language"], "witShape": component["witShape"],
                 "publicationKind": component["publicationKind"], "nodeProfile": node_profile["id"],
                 "javaGuest": node_profile["javaGuest"]}
    selectors["provider"] = ("ordinary-context-unavailable"
        if component["publicationKind"] == "capsule" and CONTEXT in component["imports"]
        else "declared-providers" if component["imports"] else "none")
    for row in matrix["rows"]:
        if all(selectors[key] in choices for key, choices in row["select"].items()):
            return {"state": row["state"], "code": row["code"], "supportMatrix": MATRIX,
                    "matrixRow": row["id"], "evidenceLevel": "structural", "executionQualified": False}
    return {"state": "untested", "code": matrix["unlistedCombination"], "supportMatrix": MATRIX,
            "evidenceLevel": "structural", "executionQualified": False}


def _equal(left, right):
    # Python equates False and 0; JSON Schema deliberately distinguishes them.
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    return left == right


def _kind(value, kind):
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return type(value) is bool
    if kind == "integer":
        return type(value) is int or (type(value) is float and math.isfinite(value) and value.is_integer())
    raise DevError("preflight-capture-schema-subset-unsupported")


def _capture_walk(value, schema, document, allowance, depth=0):
    allowance[0] -= 1
    require(depth <= 24 and allowance[0] >= 0, "preflight-capture-budget-complexity")
    if "$ref" in schema:
        name = schema["$ref"]
        require(name.startswith("#/$defs/") and name.count("/") == 2,
                "preflight-capture-schema-subset-unsupported")
        return _capture_walk(value, document["$defs"][name[8:]], document, allowance, depth + 1)
    require(set(schema) <= {"$schema", "$id", "title", "$defs", "type", "const", "enum", "required",
            "additionalProperties", "properties", "items", "minItems", "maxItems", "minLength",
            "maxLength", "minimum", "maximum", "pattern"}, "preflight-capture-schema-subset-unsupported")
    if "type" in schema:
        require(_kind(value, schema["type"]), "preflight-capture-budget-shape")
    if "const" in schema:
        require(_equal(value, schema["const"]), "preflight-capture-budget-shape")
    if "enum" in schema:
        require(any(_equal(value, expected) for expected in schema["enum"]), "preflight-capture-budget-shape")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        require(set(schema.get("required", [])) <= value.keys(), "preflight-capture-budget-shape")
        require(schema.get("additionalProperties", True) is not False or value.keys() <= properties.keys(),
                "preflight-capture-budget-shape")
        for name, child in value.items():
            if name in properties:
                _capture_walk(child, properties[name], document, allowance, depth + 1)
    elif isinstance(value, list):
        require(schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", MAX_SCHEMA_NODES),
                "preflight-capture-budget-shape")
        if "items" in schema:
            for child in value:
                _capture_walk(child, schema["items"], document, allowance, depth + 1)
    elif isinstance(value, str):
        require(schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", MAX_DOCUMENT),
                "preflight-capture-budget-shape")
        if "pattern" in schema:
            require(re.search(schema["pattern"], value) is not None, "preflight-capture-budget-shape")
    elif type(value) in {int, float}:
        require(schema.get("minimum", 0) <= value <= schema.get("maximum", MAX_U64),
                "preflight-capture-budget-shape")


def validate_capture_budget(value):
    """Validate the closed #715 diagnostic, without trusting its observations."""
    require(isinstance(value, dict), "preflight-capture-budget-shape")
    require(value.get("schemaVersion") == "latent.static-site.budget.v1", "preflight-capture-budget-version")
    schema = _document(CAPTURE_SCHEMA_PATH)
    _capture_walk(value, schema, schema, [MAX_SCHEMA_NODES])
    require(len(encode(value)) <= MAX_DOCUMENT, "preflight-capture-budget-byte-limit")
    return value


def matrix_identity():
    return digest(encode(support_matrix()))


def changed_matrix_sources(root=ROOT):
    """Review-time drift check; packaged runtime does not inspect compiler sources."""
    changed = []
    for key, row in support_matrix()["sources"].items():
        source = root / row["path"]
        if not source.is_file() or digest(source.read_bytes()) != row["digest"]:
            changed.append(key)
    return changed
