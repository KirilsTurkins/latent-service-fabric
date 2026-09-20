"""Small trusted-local onboarding scenario; reuses the operator process owner.

No build, registry, installed service, arbitrary prose execution or automatic
mutation retry. The caller owns the private directories and total deadline.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import re
import secrets
import time

from tools.phase2_operator_process import (
    Process, read_json, require, stopped_record, write_json,
)

NODE_ID = "first-node-guide"
SERVICE = "examples/echo"
CONTRACT = "examples:echo/api@0.1.0"
DEPLOYMENT = "echo-production"
MEDIA = "application/vnd.latent.wit-values.v1+json"
ECHO_FILES = {
    "echo-capsule.wasm": 64 * 1024 * 1024,
    "capsule.json": 262144, "contracts.json": 262144,
    "deployment.json": 262144, "input.json": 65536,
}


def stage_echo(source, destination):
    """Copy only the five public generated inputs, never credentials or archives."""
    require(source.is_dir() and not source.is_symlink(), "echo-root")
    identities = {}
    for name, maximum in ECHO_FILES.items():
        path = source / name
        require(not path.is_symlink() and path.is_file(), "echo-input-file")
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        require(0 < len(data) <= maximum, "echo-input-size")
        with (destination / name).open("xb") as stream:
            stream.write(data)
        (destination / name).chmod(0o600)
        identities[name] = "sha256:" + hashlib.sha256(data).hexdigest()
    manifest = read_json(destination / "capsule.json")
    deployment = read_json(destination / "deployment.json")
    require(manifest["component"]["digest"] == identities["echo-capsule.wasm"],
            "echo-component-identity")
    require(deployment["metadata"] == {"name": DEPLOYMENT, "tenant": "examples"}
            and deployment["spec"]["service"] == SERVICE
            and deployment["spec"]["release"] == identities["echo-capsule.wasm"],
            "echo-deployment-identity")
    require(read_json(destination / "input.json") == ["hello"], "echo-input-payload")
    return identities


def configure(directory):
    token = secrets.token_urlsafe(32)
    config = directory / "node.json"
    write_json(config, {
        "formatVersion": 1, "securityProfile": "local-experimental-v1",
        "dataDirectory": "data", "bind": "127.0.0.1:0", "nodeId": NODE_ID,
        "supplyChain": {"mode": "trusted-local"},
        "execution": {"maximumWallTimeMillis": 5000},
        "credentials": [{"token": token, "subject": "guide-operator",
                         "tenant": "examples", "role": "operator"}],
    })
    return config, token


def check_configuration(client, binary, directory, config, valid):
    process = Process([str(binary), "check-config", "--config", str(config)],
                      directory, client.environment, client.cancellation, maximum=65536)
    try:
        result = process.complete(min(client.deadline, time.monotonic() + 10))
        require((result.returncode == 0) if valid else (result.returncode == 2),
                "configuration-check-result")
        require(not (directory / "data").exists(), "configuration-check-created-storage")
    finally:
        process.close()


def connect(client, binary, directory, config, token, ordinal):
    node = Process([str(binary), "serve", "--config", str(config)], directory,
                   client.environment, client.cancellation, maximum=262144)
    try:
        started = node.line(min(client.deadline, time.monotonic() + 15))
        endpoint = started.get("endpoint", "")
        require(started.get("schemaVersion") == "latent.standalone.status.v1"
                and started.get("event") in ("ready", "started")
                and started.get("nodeId") == NODE_ID, "node-startup-identity")
        require(isinstance(endpoint, str)
                and re.fullmatch(r"127\.0\.0\.1:([0-9]{1,5})", endpoint)
                and 1 <= int(endpoint.rsplit(":", 1)[1]) <= 65535, "node-endpoint")
        profile = client.directory / f"client-{ordinal}.json"
        write_json(profile, {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{
            "name": "operator", "endpoint": "http://" + endpoint, "tenant": "examples",
            "token": token, "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 5000,
        }]})
        client.config, client.node = profile, node
        ready_by = min(client.deadline, time.monotonic() + 10)
        for _ in range(40):
            require(time.monotonic() < ready_by, "node-readiness")
            value = client.call("node", "get", NODE_ID)["data"]["inventory"]
            if value["health"]["ready"] is True:
                return node
            time.sleep(0.025)
        require(False, "node-readiness")
    except BaseException:
        client.node = None
        node.close()
        raise


def stop(client, node):
    client.node = None
    node.stop()
    # The maintained owner requires physical reap as well as the node's report.
    result = stopped_record(node)
    return {"processId": result["processId"], "reaped": result["reaped"],
            "clean": result["record"]["clean"]}


def invoke(client, package, activation, *, declared=False):
    path = package / ("empty.json" if declared else "input.json")
    value = client.call("invoke", "--service", SERVICE, "--contract", CONTRACT,
                        "--function", "echo", "--activation-id", activation,
                        "--input", path, codes=(3,) if declared else (0,))
    require(value["category"] == ("declared-error" if declared else "success")
            and value["outcomeKnown"] is True
            and value["data"]["activationId"] == activation, "invocation-result")
    if not declared:
        payload = value["data"]["payload"]
        require(payload["encoding"] == "base64" and payload["mediaType"] == MEDIA,
                "echo-output-format")
        raw = base64.b64decode(payload["data"], validate=True)
        require(payload["byteLength"] == str(len(raw)) and len(raw) <= 65536,
                "echo-output-size")
        import json
        require(json.loads(raw) == [{"ok": "hello"}], "echo-output-value")
    return value


def exercise(client, binary, directory, package):
    config, token = configure(directory)
    invalid = directory / "invalid.json"
    write_json(invalid, {"formatVersion": 0})
    check_configuration(client, binary, directory, invalid, False)
    check_configuration(client, binary, directory, config, True)
    client.call("validate", "capsule", package / "capsule.json")
    client.call("validate", "deployment", package / "deployment.json")
    malformed = client.directory / "malformed.json"
    write_json(malformed, {"notACapsule": True})
    rejected = client.call("validate", "capsule", malformed, codes=(2,))
    require(rejected["category"] == "local-error"
            and rejected["requestDispatched"] is False, "local-error-classification")
    node = connect(client, binary, directory, config, token, 1)
    shutdowns = []
    try:
        correct = client.config
        wrong = copy.deepcopy(read_json(correct))
        wrong["profiles"][0]["token"] = "X" * 43 if token != "X" * 43 else "Y" * 43
        denied = client.directory / "denied.json"
        write_json(denied, wrong)
        client.config = denied
        try:
            result = client.call("node", "get", NODE_ID, codes=(4,))
            require(result["category"] == "platform-failure", "authentication-classification")
        finally:
            client.config = correct
        published = client.call("release", "publish", "--manifest", package / "capsule.json",
                                "--component", package / "echo-capsule.wasm",
                                "--contracts", package / "contracts.json")["data"]["release"]
        digest = read_json(package / "capsule.json")["component"]["digest"]
        require(published["digest"] == digest, "published-component-identity")
        applied = client.call("deployment", "apply", package / "deployment.json",
                              "--expected-generation", "0")["data"]["deployment"]
        generation = applied["generation"]
        require(isinstance(generation, str) and re.fullmatch(r"[1-9][0-9]{0,19}", generation),
                "deployment-generation")
        client.call("route", "get")
        invoke(client, package, "first-node-before")
        require(client.call("activation", "get", "first-node-before")["data"]["terminalState"]
                == "completed", "activation-status")
        write_json(package / "empty.json", [""])
        invoke(client, package, "first-node-empty", declared=True)
        shutdowns.append(stop(client, node))
        node = None
        # The same protected config/catalog is reused, without another mutation.
        # A newly selected port is read from this owned node's startup message.
        node = connect(client, binary, directory, config, token, 2)
        recovered = client.call("release", "get", digest)["data"]["release"]
        require(recovered == published, "release-recovery")
        require(client.call("deployment", "get", DEPLOYMENT)["data"]["deployment"]["generation"]
                == generation, "deployment-recovery")
        invoke(client, package, "first-node-after")
        client.call("node", "get", NODE_ID)
        client.call("deployment", "delete", DEPLOYMENT, "--expected-generation", generation)
        absent = client.call("deployment", "get", DEPLOYMENT, codes=(6,))
        require(absent["category"] == "not-found", "deployment-removal")
        shutdowns.append(stop(client, node))
        node = None
        # Only a read is sent to the now-stopped endpoint. No probe Invoke/retry.
        unavailable = client.call("node", "get", NODE_ID, codes=(5,))
        require(unavailable["category"] == "transport-failure", "unavailable-classification")
        return {"successfulInvocations": 2, "declaredErrors": 1,
                "activationIds": ["first-node-before", "first-node-empty", "first-node-after"],
                "componentDigest": digest, "deploymentGeneration": generation,
                "failuresChecked": ["invalid-configuration", "invalid-capsule", "wrong-credentials",
                                    "declared-error", "stopped-node"],
                "retainedDeploymentInvokedAfterRestart": True, "shutdowns": shutdowns}
    finally:
        client.node = None
        if node is not None:
            node.close()
