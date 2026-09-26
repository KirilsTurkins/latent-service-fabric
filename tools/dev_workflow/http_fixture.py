"""Closed HTTP fixture configuration and private production-provider credential."""
from __future__ import annotations

import base64
import binascii
from pathlib import Path
import re
import secrets

from . import paths, state
from .common import DevError, digest, encode, integer, members, require

PROVIDER = ("latent:http/client@0.2.0", "bounded-http-v1", "send", "http")
MAX_BYTES = 192 * 1024


def validate(value):
    members(value, {"port", "exchanges"})
    integer(value["port"], 1024, 65535)
    require(isinstance(value["exchanges"], list) and 1 <= len(value["exchanges"]) <= 16,
            "http-fixture-exchange-count")
    require(len(encode(value)) <= MAX_BYTES, "http-fixture-byte-limit")
    seen = set()
    for entry in value["exchanges"]:
        members(entry, {"method", "path", "requestBody", "status", "responseBody"})
        require(isinstance(entry["method"], str) and entry["method"] in {"GET", "HEAD", "POST", "PUT", "DELETE"}
                and isinstance(entry["path"], str) and re.fullmatch(r"/[A-Za-z0-9/_.-]{0,255}", entry["path"]),
                "http-fixture-exchange")
        integer(entry["status"], 200, 599)
        require(not 300 <= entry["status"] <= 399, "http-fixture-redirect-not-supported")
        key = (entry["method"], entry["path"])
        require(key not in seen, "http-fixture-duplicate-exchange")
        seen.add(key)
        for name in ("requestBody", "responseBody"):
            require(isinstance(entry[name], str) and len(entry[name]) <= 43692, "http-fixture-body-limit")
            try:
                raw = base64.b64decode(entry[name], validate=True)
            except (binascii.Error, ValueError):
                raise DevError("http-fixture-canonical-body") from None
            require(len(raw) <= 32768 and base64.b64encode(raw).decode() == entry[name], "http-fixture-canonical-body")
    return value


def origin(value):
    return {"scheme": "http", "host": "127.0.0.1", "port": value["port"]}


def resources(value):
    validate(value)
    return {"kind": "http", "origins": [origin(value)], "pathPrefixes": [],
            "methods": sorted({row["method"] for row in value["exchanges"]}),
            "paths": sorted({row["path"] for row in value["exchanges"]})}


def credential(root: Path, value: dict, *, create=False) -> bytes:
    validate(value)
    require(root.name.startswith("test-"), "http-fixture-disposable-workspace-required")
    directory = root / "http-fixture-private"
    identity = digest(encode(value))
    if not directory.exists():
        require(create, "http-fixture-credential-not-prepared")
        paths.new_directory(directory)
        raw = ("Bearer " + secrets.token_hex(32)).encode("ascii")
        paths.write_new(directory / "authorization", raw)
        state.atomic(directory, "owner.json", {"purpose": "disposable-http-fixture", "fixture": identity,
                                             "credentialSha256": digest(raw)})
    saved = state.load(directory, "owner.json")
    members(saved, {"purpose", "fixture", "credentialSha256"})
    raw = paths.read(directory, "authorization", 128)
    require(saved["purpose"] == "disposable-http-fixture" and saved["fixture"] == identity
            and re.fullmatch(rb"Bearer [a-f0-9]{64}", raw) and digest(raw) == saved["credentialSha256"],
            "http-fixture-credential-changed")
    return raw


def installation(root: Path, value: dict) -> dict:
    credential(root, value, create=True)
    return {"configuration": {"formatVersion": 1, "publicRoots": False, "extraRoots": [],
        "limits": {"maximumRequestBodyBytes": 32768, "maximumResponseBodyBytes": 32768,
                   "maximumEncodedResponseBytes": 32768, "maximumHeaderBytes": 8192,
                   "maximumHeaders": 32, "maximumRedirects": 0},
        "destinations": [{"origin": origin(value),
            "addresses": {"networks": ["127.0.0.1/32"], "specialAddresses": ["127.0.0.1"]},
            "resolution": {"kind": "static", "addresses": ["127.0.0.1"]},
            "allowedRequestHeaders": [], "redirectDestinations": []}]},
        "credentialDirectory": str(root / "http-fixture-private"),
        "credentials": [{"reference": "dev-http-peer", "file": "authorization", "destination": 0,
                         "header": "authorization"}]}
