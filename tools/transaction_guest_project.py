"""Captured authoring inputs for the explicit Phase 4 guest template."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "transactional-aggregate"
INPUT_FORMAT = "lsf-wit-values-v1"
RESULT_FORMAT = "lsf-wit-values-v1"
HTTP_REQUIREMENTS = "deferred-http-requirements.json"
HTTP_BODY = b"java-aggregate-put-once-v1\0"
CURRENT_HTTP_PROFILE = "java-current-http-profile.json"


def put_once_requirements(project: dict, companion: bytes) -> dict:
    """Application requirements only; installed native owners supply authority."""
    from tools.dev_workflow.transaction_binding import validate
    binding = validate(companion, capsule=project["service"], deployment=project["name"], binding=project["name"])
    return {
        "schemaVersion": "latent.application.deferred-http-inputs.v1",
        "scope": {"capsule": project["service"], "deployment": project["name"],
                  "transactionBinding": project["name"], "namespace": binding["namespace"],
                  "companionDigest": "sha256:" + hashlib.sha256(companion).hexdigest()},
        "intent": {"binding": "qualified-http", "operation": "put-once", "count": 1,
                   "requestedExpiryUnixMillis": None,
                   "payload": {"bytes": base64.b64encode(HTTP_BODY).decode(),
                               "mediaType": "application/octet-stream", "metadata": []}},
        "adapter": {"name": "qualified-http-put-once-v1", "intentFormat": 1,
                    "payloadFormat": "http-put-once-bytes-v1", "idempotencyProfile": "retained-put-once-v1"},
        "contract": {"retentionHorizonMillis": "600000", "maximumBodyBytes": 27, "retryDelayMillis": "10"},
        "ceiling": {"maximumPayloadBytes": "27", "maximumResponseBytes": "2048", "maximumAttempts": 3,
                    "maximumAgeMillis": "600000", "attemptTimeoutMillis": "2000"},
        "authority": {"installed": False, "ruleGranted": False, "executionQualified": False},
    }


def current_java_http_requirements(project: dict, companion: bytes, profile: str) -> dict:
    """Exact current HTTP transport input, separate from historical put-once data."""
    from tools.dev_workflow.transaction_binding import validate
    binding = validate(companion, capsule=project["service"], deployment=project["name"], binding=project["name"])
    if (project.get("world") != "examples:transactional-aggregate/service@1.0.0"
            or binding["namespace"] != TEMPLATE
            or binding["operations"] != [
                {"operation": name, "mode": mode, "inputFormat": INPUT_FORMAT, "resultFormat": RESULT_FORMAT}
                for name, mode in (("update", "strict-command"), ("query", "fresh-query"), ("scan", "fresh-query"))]
            or not isinstance(profile, str)
            or re.fullmatch(r"qualified-http-v1:[0-9a-f]{64}", profile) is None):
        raise ValueError("explicit current Java HTTP profile and transaction binding required")
    return {"formatVersion": 1, "protocol": "lsf-atomic-idempotent-http-v1",
            "capsule": project["service"], "deployment": project["name"], "stateBinding": binding["binding"],
            "namespace": binding["namespace"], "companionDigest": "sha256:" + hashlib.sha256(companion).hexdigest(),
            "binding": "qualified-http", "operation": "http", "adapter": "qualified-http-effect-v1",
            "payloadFormat": "http-body-value-v1", "idempotencyProfile": profile,
            "ceiling": {"maximum_payload_bytes": 27, "maximum_response_bytes": 2048,
                        "maximum_attempts": 3, "maximum_age_millis": 600000, "attempt_timeout_millis": 2000}}


REFERENCE_WORLD = "examples:order-draft/service@1.0.0"


def reference_http_requirements(project: dict, companion: bytes, profile: str) -> dict:
    """Pin the configured adapter profile; this document supplies no authority."""
    from tools.dev_workflow.transaction_binding import validate
    binding = validate(companion, capsule=project["service"], deployment=project["name"], binding=project["name"])
    draft = binding["namespace"].removeprefix("order-drafts-")
    if (project.get("world") != REFERENCE_WORLD or binding["namespace"] != "order-drafts-" + draft
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", draft) is None
            or binding["operations"] != [
                {"operation": name, "mode": mode, "inputFormat": INPUT_FORMAT, "resultFormat": RESULT_FORMAT}
                for name, mode in (("edit", "strict-command"), ("query", "fresh-query"))]):
        raise ValueError("order-draft notification binding is invalid")
    if not isinstance(profile, str) or re.fullmatch(r"qualified-http-v1:[0-9a-f]{64}", profile) is None:
        raise ValueError("configured qualified HTTP idempotency profile is required")
    return {"formatVersion": 1, "protocol": "lsf-atomic-idempotent-http-v1",
            "capsule": project["service"], "deployment": project["name"], "stateBinding": binding["binding"],
            "namespace": binding["namespace"], "companionDigest": "sha256:" + hashlib.sha256(companion).hexdigest(),
            "binding": "draft-http", "operation": "http", "adapter": "qualified-http-effect-v1",
            "payloadFormat": "http-body-value-v1", "idempotencyProfile": profile,
            "ceiling": {"maximum_payload_bytes": 1024, "maximum_response_bytes": 22528,
                        "maximum_attempts": 3, "maximum_age_millis": 600000, "attempt_timeout_millis": 2000}}


def augment(files: dict[str, bytes], project: dict) -> None:
    """Declare exact compatibility; only authenticated node admission grants it."""
    if "limits" in project:
        # The stateless seed has zero state/effect budgets. These finite request
        # ceilings let an authorized aggregate use its imports; they confer no
        # namespace, recovery, result-read or provider authority.
        project["limits"].update(stateReadBytes=4 * 1024 * 1024,
                                 stateWriteBytes=2 * 1024 * 1024, effectCount=32)
        files["capsule-project.json"] = json.dumps(project, indent=2).encode() + b"\n"
    for package in ("state", "intents"):
        files["wit/deps/" + package + "/package.wit"] = (ROOT / "wit/platform" / package / "package.wit").read_bytes()
    profile = (ROOT / "sdk/profile/transaction-requirements-v1.json").read_bytes()
    schema = (ROOT / "examples/rust-capsules" / TEMPLATE / "state-schema.json").read_bytes()
    files["transaction-profile.json"] = profile
    files["state-schema.json"] = schema
    declaration = {
        "apiVersion": "latent.dev/v1", "kind": "TransactionBinding",
        "capsule": project["service"], "deployment": project["name"], "binding": project["name"],
        "profile": "lsf-transaction-v1", "hostAbiDigest": json.loads(profile)["hostAbiDigest"],
        "namespace": TEMPLATE, "stateSchema": "sha256:" + hashlib.sha256(schema).hexdigest(),
        "operations": [{"operation": name, "mode": mode, "inputFormat": INPUT_FORMAT, "resultFormat": RESULT_FORMAT}
                       for name, mode in (("update", "strict-command"), ("query", "fresh-query"), ("scan", "fresh-query"))],
    }
    files["transaction-binding.json"] = json.dumps(declaration, indent=2).encode() + b"\n"


def package_companion(output: Path, project: dict, files: dict[str, bytes]) -> tuple[str, str, str] | None:
    """Carry the captured companion as an asset without changing old manifests."""
    raw = files.get("transaction-binding.json")
    if raw is None:
        return None
    from tools.dev_workflow.transaction_binding import validate
    validate(raw, capsule=project["service"], deployment=project["name"], binding=project["name"])
    # Semantic/profile/namespace authority validation is the real host admission
    # boundary. Source packaging carries the bytes; it never approves them.
    with (output / "transaction-binding.json").open("xb") as stream:
        stream.write(raw)
    return ("transaction-binding.json", "asset", "application/vnd.latent.transaction-binding.v1+json")


def packaging_arguments(files: dict[str, bytes]) -> tuple[str, ...]:
    """Select offline compatibility from the verified captured host profile."""
    from tools.guest_compatibility_build import host_abi
    return ("--phase4",) if host_abi(files)["id"] == "lsf-host-abi-phase4-v1" else ()


def package_effect_requirements(output: Path, project: dict, files: dict[str, bytes]) -> tuple[str, str, str] | None:
    """Carry exact application requirements beside the unchanged signed binding."""
    from tools.dev_workflow.common import decode, encode, require
    raw = files.get(HTTP_REQUIREMENTS)
    if raw is None:
        if project.get("world") == REFERENCE_WORLD and "order-draft-source.json" in files:
            source = decode(files["order-draft-source.json"], 8192)
            require(source.get("httpProfile") is None, "deferred-http-requirements-required")
        return None
    require("transaction-binding.json" in files, "deferred-http-companion-required")
    value = decode(raw, 8192)
    if project.get("world") == REFERENCE_WORLD:
        require("order-draft-source.json" in files, "deferred-http-source-profile-required")
        source = decode(files["order-draft-source.json"], 8192)
        expected = reference_http_requirements(project, files["transaction-binding.json"], source.get("httpProfile"))
    elif CURRENT_HTTP_PROFILE in files:
        selected = decode(files[CURRENT_HTTP_PROFILE], 8192)
        require(isinstance(selected, dict)
                and set(selected) == {"schemaVersion", "idempotencyProfile"}
                and selected["schemaVersion"] == "latent.java.current-http-source-input.v1",
                "closed-current-java-http-profile-input")
        expected = current_java_http_requirements(project, files["transaction-binding.json"], selected["idempotencyProfile"])
    else:
        expected = put_once_requirements(project, files["transaction-binding.json"])
    require(encode(value) == encode(expected),
            "deferred-http-requirements-drift")
    with (output / HTTP_REQUIREMENTS).open("xb") as stream:
        stream.write(raw)
    return (HTTP_REQUIREMENTS, "asset", "application/json")
