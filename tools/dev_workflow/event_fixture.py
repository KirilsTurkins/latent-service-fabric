"""Closed immediate-event peer configuration and private TLS/token preparation."""
from __future__ import annotations

import base64
from pathlib import Path
import re
import secrets

from . import paths, process, state, tool_inventory
from .common import DevError, digest, encode, integer, members, require

PROVIDER = ("latent:events/publisher@0.2.0", "nats-jetstream-publish-v1", "publish", "events")
SERVICE = "event-host"
SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*")
MODES = {"ack", "duplicate", "drop-ack", "wrong-stream", "malformed-ack", "no-responders"}


def validate(value):
    members(value, {"port", "exchanges"})
    integer(value["port"], 1024, 65535)
    require(isinstance(value["exchanges"], list) and 1 <= len(value["exchanges"]) <= 16,
            "event-fixture-exchange-count")
    require(len(encode(value)) <= 192 * 1024, "event-fixture-byte-limit")
    seen = set()
    for entry in value["exchanges"]:
        members(entry, {"topic", "payload", "mode"})
        topic = entry["topic"]
        require(isinstance(topic, str) and len(topic) <= 128 and SUBJECT.fullmatch(topic)
                and topic not in seen, "event-fixture-topic")
        seen.add(topic)
        require(isinstance(entry["mode"], str) and entry["mode"] in MODES, "event-fixture-mode")
        require(isinstance(entry["payload"], str) and len(entry["payload"]) <= 43692, "event-fixture-payload-bound")
        try:
            raw = base64.b64decode(entry["payload"], validate=True)
        except (ValueError, base64.binascii.Error):
            raise DevError("event-fixture-canonical-payload") from None
        require(len(raw) <= 32768 and base64.b64encode(raw).decode() == entry["payload"],
                "event-fixture-canonical-payload")
    return value


def prepare(root: Path, descriptor: dict, tool_root: Path, value: dict):
    validate(value)
    require(root.name.startswith("test-"), "event-fixture-disposable-workspace-required")
    pins = [tool for tool in descriptor["build"]["tools"] if tool["name"] == "test-signer"]
    require(len(pins) == 1 and tool_root.is_absolute(), "pinned-fixture-tool-required")
    pin = pins[0]
    inventory = tool_inventory.check(tool_root, descriptor, "linux-x86_64")
    require(inventory is not None, "event-fixture-tool-inventory-required")
    directory = root / "event-fixture-private"
    identity = digest(encode(value))
    if not directory.exists():
        with paths.opened(tool_root, pin["path"]):
            result = process.run([str(tool_root / pin["path"]), "fixture-tls", str(directory)], root,
                                 timeout=30, maximum=65536)
        require(result.returncode == 0, "event-fixture-tls-preparation-failed-retained")
        require(tool_inventory.check(tool_root, descriptor, "linux-x86_64") == inventory,
                "event-fixture-tool-inventory-changed")
        paths.write_new(directory / "authorization", secrets.token_hex(32).encode("ascii"))
        files = {name: digest(paths.read(directory, name, 16384))
                 for name in ("authorization", "ca.der", "server.pem", "key.pem")}
        state.atomic(directory, "owner.json", {"purpose": "disposable-event-peer", "fixture": identity,
            "signer": pin["sha256"], "toolInventory": inventory, "files": files})
    saved = material(root, value)[2]
    require(saved["signer"] == pin["sha256"] and saved["toolInventory"] == inventory,
            "event-fixture-preparation-tool-changed")


def material(root: Path, value: dict):
    validate(value)
    require(root.name.startswith("test-"), "event-fixture-disposable-workspace-required")
    directory = root / "event-fixture-private"
    paths.private_root(directory)
    saved = state.load(directory, "owner.json")
    members(saved, {"purpose", "fixture", "signer", "toolInventory", "files"})
    members(saved["files"], {"authorization", "ca.der", "server.pem", "key.pem"})
    require(saved["purpose"] == "disposable-event-peer" and saved["fixture"] == digest(encode(value)),
            "event-fixture-owner-changed")
    files = {name: paths.read(directory, name, 16384) for name in saved["files"]}
    require(all(digest(raw) == saved["files"][name] for name, raw in files.items())
            and re.fullmatch(rb"[a-f0-9]{64}", files["authorization"]), "event-fixture-private-material-changed")
    return directory, files, saved


def installation(root: Path, value: dict, tenant: str):
    directory, files, _ = material(root, value)
    return {"configuration": {"formatVersion": 1,
        "endpoint": {"serverName": "localhost", "peer": f'127.0.0.1:{value["port"]}', "allowNonPublicPeer": True},
        "publicRoots": False, "extraRoots": [list(files["ca.der"])],
        "topics": [{"tenant": tenant, "topic": entry["topic"], "subject": entry["topic"],
                    "stream": "LSF_DEV", "duplicateWindowMillis": 60000} for entry in value["exchanges"]],
        "idempotencyNamespace": "disposable-dev-events", "maximumPayloadBytes": 32768, "timeoutMillis": 1000},
        "credentialDirectory": str(directory), "credentialReference": "dev-event-peer", "credentialFile": "authorization"}
