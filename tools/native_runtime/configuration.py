"""Explicit profiles, protected credentials, and exclusive AOT key creation."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat

from .common import document, encode, require
from . import files
from .layout import Layout

LOCAL = "local-experimental-v1"
EXTERNAL = "external-capsule-v1"


def client_document(node: dict) -> dict:
    credentials = node.get("credentials", [])
    operators = [entry for entry in credentials if entry.get("role") == "operator"]
    require(operators, "operator-credential-required-for-readiness")
    credential = operators[0]
    require(node.get("bind", "127.0.0.1:50051").startswith("127.0.0.1:"), "installer-requires-ipv4-loopback")
    return {"formatVersion": 1, "defaultProfile": "local", "profiles": [{
        "name": "local", "endpoint": "http://" + node["bind"], "tenant": credential["tenant"],
        "token": credential["token"], "connectTimeoutMillis": 500, "rpcTimeoutMillis": 5000,
        "limits": {"maximumComponentBytes": 16777216, "maximumPayloadBytes": 1048576,
                   "maximumResponseBytes": 262144},
    }]}


def load(layout: Layout, identity: tuple[int, int]) -> dict:
    return document(files.read(layout.node, 65536, owners={0, identity[0]}, private=True,
                               trusted_gid=identity[1]), 65536)


def validate_layout(layout: Layout, node: dict, profile: str) -> None:
    require(profile in {LOCAL, EXTERNAL} and node.get("securityProfile") == profile, "explicit-profile-mismatch")
    require(node.get("dataDirectory") == str(layout.data), "configured-data-path-outside-installation")
    require(isinstance(node.get("shutdownGraceMillis"), int) and 1 <= node["shutdownGraceMillis"] <= 5000,
            "installer-shutdown-grace-must-be-1-to-5000ms")
    client_document(node)
    if profile == EXTERNAL:
        require(node.get("supplyChain", {}).get("mode") == "enforced", "external-profile-requires-enforced-admission")
        isolated = node.get("isolatedAot", {})
        require(isolated.get("keyFile") == str(layout.config / "private" / "native-aot.key")
                and isolated.get("blobRoot") == str(layout.cache / "native-blobs")
                and isolated.get("receiptRoot") == str(layout.cache / "native-receipts")
                and isolated.get("compilerExecutable") == str(layout.current / "bin" / "latent-aot-compiler"),
                "external-profile-path-mismatch")


def provision(layout: Layout, identity: tuple[int, int], profile: str, release: dict,
              policy: Path | None, port: int, initialize: bool, approved_compiler: str | None = None) -> dict:
    require(profile in {LOCAL, EXTERNAL}, "unsupported-security-profile")
    require(layout.system or profile == LOCAL, "rootless-evaluation-requires-local-experimental-v1")
    require(1024 <= port <= 65535, "unprivileged-loopback-port-required")
    controller = (os.geteuid(), os.getegid())
    owners = {0, controller[0], identity[0]}
    config_identity = (controller[0], identity[1])
    files.mkdir(layout.config, 0o750 if layout.system else 0o700, config_identity, owners=owners)
    files.mkdir(layout.config / "client", 0o700, controller, owners=owners)
    for path in (layout.data, layout.cache):
        files.mkdir(path, 0o700, identity, owners=owners)
    if profile == EXTERNAL:
        files.mkdir(layout.config / "private", 0o700, identity, owners=owners)
        key = layout.config / "private" / "native-aot.key"
        if not key.exists():
            require(initialize, "existing-host-key-missing-restore-backup")
            files.create(key, secrets.token_bytes(32), identity=identity)
        with files.regular(key, 32, owners=owners) as descriptor:
            metadata = os.fstat(descriptor)
            require(metadata.st_uid == identity[0] and stat.S_IMODE(metadata.st_mode) in {0o400, 0o600}
                    and os.read(descriptor, 33) != bytes(32) and metadata.st_size == 32, "invalid-existing-host-key")
        policy_target = layout.config / "admission-policy.json"
        if not policy_target.exists():
            require(initialize and policy is not None, "operator-trust-policy-required-installation-unactivated")
            policy_bytes = files.read(policy, 262144, owners={0, os.geteuid()})
            document(policy_bytes, 262144)
            files.create(policy_target, policy_bytes, 0o640, config_identity)
        elif policy is not None:
            require(files.read(policy_target, 262144) == files.read(policy, 262144, owners={0, os.geteuid()}),
                    "existing-trust-policy-is-not-overwritten")
    if not layout.node.exists():
        require(initialize and not layout.client.exists(), "existing-node-config-missing-restore-backup")
        node = {
            "formatVersion": 1, "securityProfile": profile, "dataDirectory": str(layout.data),
            "bind": f"127.0.0.1:{port}", "nodeId": "lsf-" + secrets.token_hex(8),
            "shutdownGraceMillis": 5000, "execution": {"maximumWallTimeMillis": 5000},
            "audit": {"mode": "durable"},
            "supplyChain": {"mode": "trusted-local"},
            "credentials": [{"token": secrets.token_urlsafe(32), "subject": "installation-operator",
                             "tenant": "examples", "role": "operator"}],
        }
        if profile == EXTERNAL:
            node["supplyChain"] = {"mode": "enforced", "policyFile": str(layout.config / "admission-policy.json")}
            node["isolatedAot"] = {
                "compilerExecutable": str(layout.current / "bin" / "latent-aot-compiler"),
                "compilerDigest": "sha256:" + release["engine"]["compilerSha256"],
                "keyFile": str(layout.config / "private" / "native-aot.key"),
                "blobRoot": str(layout.cache / "native-blobs"), "receiptRoot": str(layout.cache / "native-receipts"),
            }
        files.create(layout.node, encode(node), 0o640 if layout.system else 0o600, config_identity)
    node = load(layout, identity)
    validate_layout(layout, node, profile)
    if not layout.client.exists():
        require(initialize, "existing-client-config-missing-restore-backup")
        files.create(layout.client, encode(client_document(node)), identity=controller)
    existing_client = document(files.read(layout.client, 65536, owners={0, controller[0]}, private=True), 65536)
    require(existing_client == client_document(node), "client-config-mismatch-no-automatic-credential-rotation")
    if "isolatedAot" in node:
        require(node["isolatedAot"]["compilerDigest"] == "sha256:" + release["engine"]["compilerSha256"]
                or approved_compiler == release["engine"]["compilerSha256"],
                "compiler-change-requires-explicit-approve-compiler-sha256")
    return node


def approve_compiler(layout: Layout, identity: tuple[int, int], node: dict, release: dict, approved: str | None) -> None:
    if "isolatedAot" not in node or node["isolatedAot"]["compilerDigest"] == "sha256:" + release["engine"]["compilerSha256"]:
        return
    require(approved == release["engine"]["compilerSha256"], "compiler-approval-mismatch")
    require(load(layout, identity) == node, "operator-configuration-changed-during-upgrade")
    node["isolatedAot"]["compilerDigest"] = "sha256:" + approved
    files.replace(layout.node, encode(node), 0o640, (os.geteuid(), identity[1]))
