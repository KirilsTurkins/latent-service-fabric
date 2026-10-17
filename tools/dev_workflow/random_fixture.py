"""Explicit bounded byte requests from the existing system-random provider."""
from .common import members, require

PROVIDER = ("latent:random/random@0.1.0", "system-random-v1", "bytes", "random")


def validate(value):
    members(value, {"maximumOperations", "maximumOutputBytes"})
    require(type(value["maximumOperations"]) is int and 1 <= value["maximumOperations"] <= 16
            and type(value["maximumOutputBytes"]) is int and 1 <= value["maximumOutputBytes"] <= 4096,
            "explicit-random-fixture-bounds")
    return value


def ceiling(value):
    selected = validate(value)
    return {"operations": selected["maximumOperations"], "inputBytes": 8,
            "outputBytes": selected["maximumOutputBytes"], "wallTimeMillis": 5000}


def initialized(selected, providers):
    validate(selected)
    actual = (providers or {}).get("random", {})
    return (actual.get("id") == "random" and actual.get("tenant") == "examples"
            and actual.get("capability") == PROVIDER[0] and actual.get("profile") == PROVIDER[1]
            and actual.get("service") == "runtime-host" and actual.get("configurationEpoch") == "1")
