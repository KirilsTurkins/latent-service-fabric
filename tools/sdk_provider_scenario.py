"""Shared finite fixture setup and result contract for actual SDK processes."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time

from tools.phase2_operator_process import Process, read_json, require, write_json
from tools.phase2_operator_scenario import TOKEN
from tools.phase3_management_scenario import TENANT

LANGUAGES = {"rust", "typescript", "go", "c", "java", "dotnet"}
ASSERTIONS = {
    "httpGuest", "blobGuest", "declaredError", "platformFailure", "wrongTenant", "wrongCredential",
    "boundedPages", "providerInspection", "mutationReceipt", "exactReplay", "preconditionConflict",
    "localCancellation", "explicitCancellation", "lostResponseStatus", "absoluteDeadline",
    "responseLimit", "shutdownOutstanding", "clientOwnersReaped",
}


def publish_callee(client, fixture):
    summary = read_json(fixture / "fixture.json")
    records = [entry for entry in summary["fixtures"] if entry["name"] == "rust-callee"]
    require(len(records) == 1, "sdk-callee-fixture")
    source = fixture / "rust-callee"
    publication = client.call("release", "publish-package", source / "package",
                              "--evidence", source / "evidence/index.json", "--operation-id", "publish-callee",
                              "--expected-generation", "0")["data"]["operation"]["publication"]["id"]
    budget = {"cpuFuel": 100000000, "memoryBytes": 4194304, "wallTimeLimitMillis": 5000,
              "childCalls": 0, "outboundRequests": 0, "stateReadBytes": 0, "stateWriteBytes": 0,
              "blobReadBytes": 0, "blobWriteBytes": 0, "logBytes": 0, "effectCount": 0}
    path = client.directory / "callee-deployment.json"
    write_json(path, {"apiVersion": "latent.dev/v1alpha1", "kind": "Deployment",
                     "metadata": {"name": "guest-callee", "tenant": TENANT},
                     "spec": {"service": "callee", "release": records[0]["componentDigest"],
                              "publication": publication, "route": {"weight": 10000}, "resources": budget,
                              "availability": {"minimumCachedCopies": 1, "minimumZones": 1},
                              "placement": {"trustClass": "internal", "architectures": ["x86_64"]}}})
    snapshot = client.call("deployment", "get", "guest-callee", "--operation-snapshot", codes=(6,))["data"]
    result = client.call("deployment", "apply", path, "--operation-id", "deploy-callee",
                         "--expected-generation", "0", "--expected-state-version", snapshot["stateVersion"])
    require(result["outcomeKnown"], "sdk-callee-deployment-uncertain")
    return {"publication": publication, "componentDigest": records[0]["componentDigest"],
            "service": "callee", "route": "guest-callee", "contract": "tests:local/api@1.0.0",
            "function": "answer"}


def start_provider(client, control):
    process = Process([sys.executable, str(Path(__file__).with_name("sdk_provider_http_fixture.py")),
                       "--control", str(control)], control, client.environment, client.cancellation, maximum=4096)
    try:
        started = process.line(min(client.deadline, time.monotonic() + 10))
        require(set(started) == {"port"} and type(started["port"]) is int
                and 1 <= started["port"] <= 65535, "sdk-provider-startup")
        return process, started["port"]
    except BaseException:
        process.close()
        raise


def stop_provider(process):
    process.stop()
    lines = bytes(process.buffers[0]).splitlines()
    require(len(lines) == 1, "sdk-provider-shutdown-record")
    result = json.loads(lines[0])
    require(set(result) == {"requests", "authorized", "unexpected", "holds", "closedHolds"}
            and all(type(value) is int and 0 <= value <= 32 for value in result.values()),
            "sdk-provider-shutdown-bound")
    require(result["requests"] == result["authorized"] and result["unexpected"] == 0
            and result["holds"] == result["closedHolds"] == 4,
            "sdk-provider-authority-or-physical-reclamation")
    require(process.closed and process.owner.finished and process.owner.process.returncode == 0,
            "sdk-provider-not-reaped")
    return result


def participant_input(directory, control, language, endpoint, targets, port):
    require(language in LANGUAGES, "sdk-language")
    credential = directory / "client-token"
    with credential.open("xb") as output:
        output.write(TOKEN.encode("ascii"))
    credential.chmod(0o600)
    path = directory / "input.json"
    fields = ("service", "route", "contract", "function", "publication", "componentDigest")
    write_json(path, {"schemaVersion": "latent.sdk.provider.workflow.input.v1", "language": language,
                     "endpoint": "http://" + endpoint, "tenant": TENANT, "credentialFile": str(credential),
                     "controlDirectory": str(control), "upstreamUrl": f"http://localhost:{port}/allowed",
                     "targets": {name: {key: value[key] for key in fields} for name, value in targets.items()},
                     "policyDocument": json.dumps({"formatVersion": 1, "tenant": TENANT, "rules": []},
                                                  separators=(",", ":"))})
    return path


def validate_result(value, language):
    require(isinstance(value, dict) and set(value) == {"schemaVersion", "language", "assertions", "activationIds",
                                                     "operationId", "auditAttempt", "transport"}, "sdk-result-shape")
    require(value["schemaVersion"] == "latent.sdk.provider.workflow.result.v1"
            and value["language"] == language, "sdk-result-profile")
    require(set(value["assertions"]) == ASSERTIONS and all(item is True for item in value["assertions"].values()),
            "sdk-acceptance-incomplete")
    require(isinstance(value["activationIds"], list) and 6 <= len(value["activationIds"]) <= 16
            and len(set(value["activationIds"])) == len(value["activationIds"])
            and all(isinstance(item, str) and re.fullmatch(language + r"-[a-z0-9-]{1,48}", item)
                    for item in value["activationIds"]), "sdk-activation-identities")
    require(value["operationId"] == language + "-policy-create", "sdk-operation-identity")
    attempt = value["auditAttempt"]
    require(isinstance(attempt, str) and re.fullmatch(r"[1-9][0-9]{0,19}", attempt)
            and int(attempt) <= 18446744073709551615, "sdk-observed-audit-attempt")
    require(value["transport"] == "numeric-loopback-http2-protobuf-v1", "sdk-transport-profile")
    return value


def run_participant(client, directory, command, input_path, language):
    require(1 <= len(command) <= 16 and all(isinstance(item, str) and 0 < len(item) <= 4096 for item in command),
            "sdk-command-bound")
    participant = Process([*command, "--config", str(input_path)], directory, client.environment,
                          client.cancellation, maximum=65536)
    try:
        result = participant.complete(min(client.deadline, time.monotonic() + 90))
        require(result.returncode == 0 and not result.stderr, "sdk-participant-failed")
        lines = result.stdout.splitlines()
        require(len(lines) == 1 and len(lines[0]) <= 32768, "sdk-participant-output-bound")
        value = validate_result(json.loads(lines[0]), language)
        require(participant.owner.finished, "sdk-participant-not-reaped")
        return value
    finally:
        participant.close()
