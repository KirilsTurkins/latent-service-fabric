"""Explicit namespace selection for the production Linux immutable-blob provider."""
from __future__ import annotations

import re

from .common import members, require

OPERATIONS = ("create", "open", "read", "write", "seal")
PROVIDER = ("latent:blob/blob@0.2.0", "linux-immutable-blobs-v1", OPERATIONS, "blob")
SERVICE = "runtime-host-blob"


def validate(value):
    members(value, {"namespace"})
    require(isinstance(value["namespace"], str) and re.fullmatch(r"dev-[a-z0-9-]{1,32}", value["namespace"]),
            "explicit-disposable-blob-namespace-required")
    return value


def initialized(selected, providers):
    validate(selected)
    actual = (providers or {}).get("blob", {})
    return (actual.get("capability") == PROVIDER[0] and actual.get("profile") == PROVIDER[1]
            and actual.get("service") == SERVICE and actual.get("configurationEpoch") == "1")
