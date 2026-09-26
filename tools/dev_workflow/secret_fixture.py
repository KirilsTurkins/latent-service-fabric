"""Private generated guest secrets for explicitly selected disposable nodes."""
from __future__ import annotations

from pathlib import Path
import re
import secrets

from . import paths, state
from .common import digest, encode, members, require

PROVIDER = ("latent:secrets/reader@0.1.0", "protected-local-secrets-v1", "read", "secrets")
SERVICE = "runtime-host-secrets"


def validate(value):
    members(value, {"references"})
    require(isinstance(value["references"], list) and 1 <= len(value["references"]) <= 8,
            "development-secret-reference-limit")
    names = set()
    for entry in value["references"]:
        members(entry, {"name"}, {"expired"})
        require(isinstance(entry["name"], str) and re.fullmatch(r"dev-[a-z0-9-]{1,60}", entry["name"])
                and entry["name"] not in names and type(entry.get("expired", False)) is bool,
                "explicit-disposable-secret-reference-required")
        names.add(entry["name"])
    return value


def values(root: Path, selected: dict, *, create=False) -> list[bytes]:
    validate(selected)
    require(root.name.startswith("test-"), "development-secrets-require-test-workspace")
    directory = root / "secret-fixture-private"
    identity = digest(encode(selected))
    if create and not directory.exists():
        paths.new_directory(directory)
        identities = {}
        for entry in selected["references"]:
            raw = secrets.token_hex(32).encode("ascii")
            paths.write_new(directory / entry["name"], raw)
            identities[entry["name"]] = digest(raw)
        state.atomic(directory, "owner.json", {"purpose": "disposable-guest-secrets", "fixture": identity,
                                               "values": identities})
    owner = state.load(directory, "owner.json")
    members(owner, {"purpose", "fixture", "values"})
    require(owner["purpose"] == "disposable-guest-secrets" and owner["fixture"] == identity
            and isinstance(owner["values"], dict)
            and set(owner["values"]) == {entry["name"] for entry in selected["references"]},
            "development-secret-owner-changed")
    result = []
    for entry in selected["references"]:
        raw = paths.read(directory, entry["name"], 64)
        require(re.fullmatch(rb"[a-f0-9]{64}", raw) and digest(raw) == owner["values"][entry["name"]],
                "development-secret-value-changed")
        result.append(raw)
    return result


def installation(root, value):
    values(root, value, create=True)
    return {"directory": str(root / "secret-fixture-private"), "references": [
        {"reference": entry["name"], "file": entry["name"],
         **({"expiresAtUnixMillis": 1} if entry.get("expired", False) else {})} for entry in value["references"]]}


def initialized(providers):
    actual = (providers or {}).get("secrets", {})
    return (actual.get("capability") == PROVIDER[0] and actual.get("profile") == PROVIDER[1]
            and actual.get("service") == SERVICE and actual.get("configurationEpoch") == "1")
