"""Maintained config checks and bounded authenticated activation readiness."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time

from .common import document, encode, execute, require
from .configuration import EXTERNAL, client_document, load, validate_layout
from . import files, host
from .layout import Layout, service_identity
from .verify import version


def current(layout: Layout) -> Path:
    with files.directory(layout.prefix, {0, os.geteuid()}) as parent:
        target = os.readlink("current", dir_fd=parent)
    parts = target.split("/")
    require(len(parts) == 2 and parts[0] == "releases", "unsafe-current-release-link")
    version(parts[1])
    result = layout.prefix / target
    with files.directory(result, {0, os.geteuid()}):
        pass
    return result


def preflight(layout: Layout, candidate: str | None = None) -> dict:
    identity = service_identity(layout)
    observation = host.platform_check()
    node = load(layout, identity)
    validate_layout(layout, node, node.get("securityProfile"))
    for path in (layout.data, layout.cache):
        host.filesystem_probe(path)
    root = layout.prefix / "releases" / version(candidate) if candidate is not None else current(layout)
    with files.directory(root, {0, os.geteuid()}):
        pass
    for name in ("latent", "latentd", "latent-aot-compiler"):
        host.dynamic_probe(root / "bin" / name)
    source = document(files.read(root / "release-source.json", 65536), 65536)
    with tempfile.TemporaryDirectory(prefix=".lsf-preflight-", dir=layout.cache) as temporary:
        config = layout.node
        if candidate is not None and node["securityProfile"] == EXTERNAL:
            node["isolatedAot"] = {**node["isolatedAot"], "compilerExecutable": str(root / "bin" / "latent-aot-compiler"),
                                   "compilerDigest": "sha256:" + source["engine"]["compilerSha256"]}
            config = Path(temporary) / "node.json"
            files.create(config, encode(node))
        status, output = execute([str(root / "bin" / "latentd"), "check-config", "--config", str(config)],
                                 timeout=40, maximum=65536, cwd=str(layout.data))
    require(status == 0, "node-check-config-failed-no-profile-fallback")
    report = document(output, 65536)
    require(report.get("schemaVersion") == "latent.standalone.config-check.v1"
            and report.get("profile") == node["securityProfile"]
            and report.get("protectedCredentialFile") is True, "node-profile-check-incomplete")
    require(report.get("wasmtimeVersion") == source["engine"]["wasmtimeVersion"]
            and report.get("hostAbiProfile") == source["engine"]["hostAbiProfile"], "node-engine-identity-mismatch")
    if node["securityProfile"] == EXTERNAL:
        require(report.get("admission") == "enforced" and report.get("authenticatedNativeLoading") is True
                and report.get("compilerSandbox") == "lsf-linux-x86_64-landlock3-seccomp-v1",
                "isolated-compiler-sandbox-not-established")
    return {"schemaVersion": "latent.native-preflight.v1", "host": observation, "profile": report}


def readiness(layout: Layout, timeout: float = 20) -> dict:
    identity = service_identity(layout)
    node = load(layout, identity)
    validate_layout(layout, node, node.get("securityProfile"))
    root = current(layout)
    deadline = time.monotonic() + timeout
    with files.directory(layout.cache, {0, os.geteuid()}):
        pass
    with tempfile.TemporaryDirectory(prefix=".lsf-ready-", dir=layout.cache) as directory:
        client = Path(directory) / "client.json"
        files.create(client, encode(client_document(node)))
        for _attempt in range(10):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            status, output = execute([
                str(root / "bin" / "latent"), "--config", str(client), "--output", "json",
                "--connect-timeout-ms", "500", "--rpc-timeout-ms", "1000", "node", "get", node["nodeId"],
            ], timeout=min(2, remaining), maximum=262144, cwd=str(layout.data))
            if status == 0:
                result = document(output, 262144)
                inventory = result.get("data", {}).get("inventory", {})
                attributes = inventory.get("node", {}).get("attributes", {})
                if (result.get("schemaVersion") == "latent.cli.result.v1" and result.get("category") == "success"
                        and inventory.get("node", {}).get("id") == node["nodeId"]
                        and attributes.get("lsf.security.profile") == node["securityProfile"]
                        and inventory.get("health", {}).get("ready") is True
                        and inventory.get("pressure", {}).get("loadAvailable") is True):
                    return {"schemaVersion": "latent.native-readiness.v1", "authenticated": True,
                            "activationReady": True, "profile": node["securityProfile"]}
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    require(False, "activation-readiness-failed-inspect-local-journal-and-check-config")
