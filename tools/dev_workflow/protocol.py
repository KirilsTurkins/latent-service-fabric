"""Version/feature negotiation precedes any backend mutation."""
from __future__ import annotations

import platform
import secrets
import sys

from .common import PROTOCOL, HOST_ABI, members, require

FEATURES = frozenset({"doctor", "install", "up", "status", "logs", "down", "purge", "snapshot",
                      "build", "deploy", "recover", "invoke", "test"})


def hello() -> dict:
    return {"protocol": PROTOCOL, "helperVersion": "1", "hostAbi": HOST_ABI,
            "os": sys.platform, "architecture": platform.machine(), "features": sorted(FEATURES)}


def negotiate(value: dict, *, architecture: str = "x86_64", host_abi: str = HOST_ABI) -> dict:
    members(value, {"protocol", "helperVersion", "hostAbi", "os", "architecture", "features"})
    require(value["protocol"] == PROTOCOL and value["helperVersion"] == "1", "incompatible-backend-protocol")
    require(value["hostAbi"] == host_abi, "incompatible-host-abi")
    require(value["os"] == "linux" and value["architecture"] == architecture, "unsupported-backend-target")
    require(isinstance(value["features"], list) and len(value["features"]) == len(set(value["features"]))
            and set(value["features"]) == FEATURES, "incompatible-backend-features")
    return value


def request(operation: str, workspace: str, arguments: dict) -> dict:
    from .common import identifier
    require(operation in FEATURES | {"hello"}, "unsupported-operation")
    identifier(workspace)
    return {"protocol": PROTOCOL, "requestId": secrets.token_hex(16), "workspace": workspace,
            "operation": operation, "arguments": arguments}


def validate_request(value: dict) -> dict:
    from .common import identifier
    import re
    members(value, {"protocol", "requestId", "workspace", "operation", "arguments"})
    require(value["protocol"] == PROTOCOL, "incompatible-backend-protocol")
    require(isinstance(value["requestId"], str) and re.fullmatch(r"[a-f0-9]{32}", value["requestId"]),
            "invalid-request-id")
    identifier(value["workspace"])
    require(value["operation"] in FEATURES | {"hello"} and isinstance(value["arguments"], dict), "invalid-operation")
    return value


def response(request_value: dict, result: dict, *, code: str = "success", uncertain: bool = False) -> dict:
    return {"protocol": PROTOCOL, "requestId": request_value["requestId"], "workspace": request_value["workspace"],
            "code": code, "uncertain": uncertain, "result": result}


def result(value: dict, sent: dict) -> dict:
    from .common import DevError
    members(value, {"protocol", "requestId", "workspace", "code", "uncertain", "result"})
    require(value["protocol"] == PROTOCOL and value["requestId"] == sent["requestId"]
            and value["workspace"] == sent["workspace"], "backend-response-identity")
    require(type(value["uncertain"]) is bool and isinstance(value["result"], dict), "backend-response-format")
    if value["code"] != "success" or value["uncertain"]:
        # Only bounded static protocol codes are rendered; never arbitrary stderr.
        import re
        code = value["code"]
        require(isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,100}", code), "backend-response-code")
        raise DevError(code, uncertain=value["uncertain"])
    return value["result"]
