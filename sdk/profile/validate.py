import base64
import json
import re
import sys

from generate import ROOT, generated_files, read_contract


def unsigned_decimal(value):
    return isinstance(value, str) and bool(re.fullmatch(r"0|[1-9][0-9]{0,19}", value)) and int(value) < 1 << 64


def validate_value(field, value, messages, enums, depth=0):
    if depth > 32:
        raise ValueError("fixture nesting exceeds bound")
    kind = field["type"]
    if field.get("map"):
        if not isinstance(value, dict) or len(value) > 128:
            raise ValueError("invalid bounded fixture map")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("non-string map key")
            validate_value({"type": kind}, item, messages, enums, depth + 1)
    elif field.get("repeated"):
        if not isinstance(value, list) or len(value) > 128:
            raise ValueError("invalid bounded fixture list")
        for item in value:
            validate_value({"type": kind}, item, messages, enums, depth + 1)
    elif kind in messages:
        if not isinstance(value, dict):
            raise ValueError("message must be an object, not null")
        fields = {member["name"]: member for member in messages[kind]}
        if value.keys() - fields.keys():
            raise ValueError("unknown fixture fields: " + ",".join(value.keys() - fields.keys()))
        for name, item in value.items():
            validate_value(fields[name], item, messages, enums, depth + 1)
    elif kind == "uint64":
        if not unsigned_decimal(value):
            raise ValueError("uint64 must be a canonical decimal string")
    elif kind in enums or kind in ("uint32", "int32"):
        minimum, maximum = (0, (1 << 32) - 1) if kind == "uint32" else (-(1 << 31), (1 << 31) - 1)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("integer outside protobuf range")
    elif kind == "bool":
        if type(value) is not bool:
            raise ValueError("expected boolean")
    elif kind in ("string", "bytes"):
        if not isinstance(value, str) or len(value.encode("utf-8")) > field.get("maximum_bytes", 65536):
            raise ValueError("expected bounded string")
        if kind == "bytes":
            decoded = base64.b64decode(value, validate=True)
            if base64.b64encode(decoded).decode("ascii") != value:
                raise ValueError("noncanonical fixture base64")
    else:
        raise ValueError("unsupported fixture type")


def request_error(kind, value):
    if kind == "ApplyPolicyRequest":
        if "expected_generation" not in value:
            return "missing-generation"
        if not value.get("operation_id"):
            return "invalid-operation-id"
    if kind == "InvokeRequest":
        if any(name in value and value[name] == "" for name in ("activation_id", "parent_activation_id", "root_activation_id")):
            return "invalid-identity"
    if kind in ("ListPoliciesRequest", "ListCapabilitiesRequest"):
        if kind == "ListCapabilitiesRequest" and not value.get("deployment_id"):
            return "invalid-deployment-id"
        page = value.get("page")
        if kind == "ListPoliciesRequest" and page is None:
            return "missing-page"
        if page is not None:
            size = page.get("page_size", 0)
            minimum, maximum = (1, 32) if kind == "ListPoliciesRequest" else (0, 128)
            if not minimum <= size <= maximum:
                return "invalid-page-size"
            if "page_token" in page and (not page["page_token"] or len(page["page_token"].encode("utf-8")) > (117 if kind == "ListPoliciesRequest" else 160)):
                return "invalid-page-token"
        if kind == "ListCapabilitiesRequest" and any(
            name in value and (not value[name] or not value[name].isascii() or len(value[name]) > 128)
            for name in ("contract_prefix", "provider")
        ):
            return "invalid-filter"
    return None


def response_error(kind, value, messages):
    groups = {}
    for field in messages[kind]:
        if field.get("oneof") and field["name"] in value:
            groups[field["oneof"]] = groups.get(field["oneof"], 0) + 1
    return "contradictory-oneof" if any(count > 1 for count in groups.values()) else None


def validate():
    profile, messages, enums = read_contract()
    fixture_path = ROOT / "sdk/profile/fixtures.json"
    if fixture_path.stat().st_size > 256 * 1024:
        raise ValueError("fixture file exceeds 256 KiB")
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixtures["profile"] != profile["profile"]:
        raise ValueError("fixture profile mismatch")
    names = set()
    for case in fixtures["cases"]:
        if case["name"] in names:
            raise ValueError("duplicate vector " + case["name"])
        names.add(case["name"])
        validate_value({"type": case["type"]}, case["value"], messages, enums)
        if "request_error" in case and request_error(case["type"], case["value"]) != case["request_error"]:
            raise ValueError("request-boundary marker mismatch: " + case["name"])
        if "response_error" in case and response_error(case["type"], case["value"], messages) != case["response_error"]:
            raise ValueError("response-boundary marker mismatch: " + case["name"])
    for case in fixtures["unsigned"]:
        if unsigned_decimal(case["decimal"]) != case["valid"]:
            raise ValueError("unsigned boundary marker mismatch")
    forbidden = {"actor", "principal", "credentials", "claims", "provider_credentials"}
    for operation in profile["operations"]:
        if forbidden & {field["name"] for field in messages[operation["request"]]}:
            raise ValueError("caller-authoritative identity field")
    for path, expected in generated_files().items():
        if not (ROOT / path).exists() or (ROOT / path).read_text(encoding="utf-8") != expected:
            raise ValueError("stale generated file: " + path)
    return len(fixtures["cases"]), len(fixtures["unsigned"])


if __name__ == "__main__":
    try:
        vector_count, unsigned_count = validate()
        print(f"client profile validated: 8 RPCs, 6 facades, {vector_count} shared vectors, {unsigned_count} unsigned boundaries")
    except (ValueError, KeyError, OSError) as failure:
        print(str(failure), file=sys.stderr)
        sys.exit(1)
