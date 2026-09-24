"""Byte-preserving application scenarios shared by node and portable adapters."""
from __future__ import annotations

import base64
import re
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from . import paths
from .common import MAX_DOCUMENT, decode, digest, encode, identifier, integer, members, require

OUTCOMES = {"success", "declared-error", "platform-failure", "transport-failure"}
NODE_ONLY = {"authentication", "deployment", "restart", "pressure", "compiler-isolation", "protected-files", "native-cache"}
PORTABLE = {"context", "log", "clock", "random", "metrics", "buffered-http-fixture", "fresh-state", "fuel", "memory"}


def validate(value: dict, environment: str) -> dict:
    members(value, {"schemaVersion", "scenarios"})
    require(value["schemaVersion"] == "latent.dev.scenarios.v1" and environment in {"node", "portable"}, "scenario-environment")
    require(len(encode(value)) <= MAX_DOCUMENT, "scenario-document-byte-limit")
    require(isinstance(value["scenarios"], list) and 0 < len(value["scenarios"]) <= 128, "scenario-count-limit")
    names = set()
    fixtures_by_id = {}
    for case in value["scenarios"]:
        members(case, {"id", "service", "contract", "function", "input", "mediaType", "expect", "requires",
                       "timeoutMillis", "required", "fixtures"}, {"execution"})
        identifier(case["id"])
        require(case["id"] not in names, "duplicate-scenario")
        names.add(case["id"])
        for key in ("service", "contract", "function", "mediaType"):
            require(isinstance(case[key], str) and 0 < len(case[key]) <= 512 and "\0" not in case[key], "scenario-selector")
        paths.relative(case["input"])
        expected = members(case["expect"], {"category"}, {"payload", "platformCode"})
        require(expected["category"] in OUTCOMES, "scenario-expected-outcome")
        if "payload" in expected:
            paths.relative(expected["payload"])
        require(type(case["required"]) is bool, "scenario-required-flag")
        if "execution" in case:
            execution = members(case["execution"], {"grants"}, {"fuel", "memoryBytes", "cancelBeforeStart", "deniedCapabilities"})
            require(isinstance(execution["grants"], list) and len(execution["grants"]) <= 32
                    and all(isinstance(item, str) and len(item) <= 512 for item in execution["grants"]),
                    "scenario-explicit-grants")
            require(isinstance(execution.get("deniedCapabilities", []), list)
                    and len(execution.get("deniedCapabilities", [])) <= 32
                    and all(item in execution["grants"] for item in execution.get("deniedCapabilities", [])),
                    "scenario-explicit-denied-capabilities")
            for key in {"fuel", "memoryBytes"} & execution.keys():
                require(isinstance(execution[key], str) and re.fullmatch(r"[1-9][0-9]{0,10}", execution[key]),
                        "scenario-budget-format")
            require(type(execution.get("cancelBeforeStart", False)) is bool, "scenario-cancellation-format")
        integer(case["timeoutMillis"], 1, 30000)
        require(isinstance(case["requires"], list) and len(case["requires"]) <= 32
                and len(set(case["requires"])) == len(case["requires"])
                and set(case["requires"]) <= NODE_ONLY | PORTABLE, "scenario-requirements")
        require(isinstance(case["fixtures"], list) and len(case["fixtures"]) <= 8, "scenario-fixtures")
        for fixture in case["fixtures"]:
            members(fixture, {"id", "kind", "identity"}, {"configuration"})
            identifier(fixture["id"])
            require(fixture["kind"] in {"real-provider", "controlled-peer", "test-adapter"}, "fixture-kind")
            require(isinstance(fixture["identity"], str) and 0 < len(fixture["identity"]) <= 512, "fixture-identity")
            if "configuration" in fixture:
                paths.relative(fixture["configuration"])
            previous = fixtures_by_id.setdefault(fixture["id"], fixture)
            require(previous == fixture, "fixture-id-has-conflicting-definitions")
    return value


def run(document: dict, root: Path, environment: str, selection: list[str], adapter,
        identity: dict, *, supported: set[str], initialized_fixtures: set[str] | None = None,
        execution_controls: bool = False, expected_revision: dict | None = None) -> dict:
    validate(document, environment)
    require(environment in {"node", "portable"}, "explicit-test-environment-required")
    require(expected_revision is None or environment == "node", "portable-has-no-node-revision")
    available = {case["id"] for case in document["scenarios"]}
    require(len(selection) <= 128 and set(selection) <= available, "unknown-test-selection")
    selected = [case for case in document["scenarios"] if not selection or case["id"] in selection]
    require(selected, "empty-test-selection")
    # Validate and read all inputs before the first call.
    prepared = [(case, paths.read(root, case["input"], 1048576),
                 paths.read(root, case["expect"]["payload"], 1048576) if "payload" in case["expect"] else None)
                for case in selected]
    results = []
    deadline = time.monotonic() + 300
    required_failed = False
    fixtures = initialized_fixtures or set()
    for case, raw, expected_payload in prepared:
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            results.append({"id": case["id"], "status": "failed", "required": case["required"], "reason": "test-run-deadline"})
            required_failed = True
            continue
        missing = set(case["requires"]) - supported
        if "execution" in case and not execution_controls:
            missing.add("per-invocation-execution-controls")
        if environment == "portable":
            missing |= set(case["requires"]) & NODE_ONLY
        missing_fixtures = {entry["id"] for entry in case["fixtures"]} - fixtures
        if missing or missing_fixtures:
            results.append({"id": case["id"], "status": "unsupported", "required": case["required"],
                            "missing": sorted(missing), "unavailableFixtures": sorted(missing_fixtures)})
            required_failed |= case["required"]
            continue
        result = adapter({**case, "timeoutMillis": min(case["timeoutMillis"], remaining)}, raw)
        matched = result.get("category") == case["expect"]["category"] and result.get("outcomeKnown") is True
        revision = result.get("data", {}).get("resolvedRevision")
        revision_keys = {"publicationId", "releaseDigest", "revisionId", "routeGeneration"}
        if (not isinstance(revision, dict) or set(revision) != revision_keys
                or not all(isinstance(value, str) and 0 < len(value) <= 256 for value in revision.values())):
            revision = None
        target_matches = (expected_revision is None or revision is not None
                          and all(revision.get(key) == value for key, value in expected_revision.items()))
        matched &= target_matches
        payload_identity = None
        if expected_payload is not None:
            data = result.get("data", {})
            payload = data.get("payload") or (data.get("declaredError") or {}).get("payload", {})
            try:
                actual = base64.b64decode(payload.get("data", ""), validate=True)
            except (ValueError, TypeError):
                actual = None
            if actual is not None:
                payload_identity = digest(actual)
            matched &= (payload.get("encoding") == "base64" and actual == expected_payload
                        and payload.get("byteLength") == str(len(expected_payload))
                        and payload.get("mediaType") == case["mediaType"])
        error = result.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,100}", code) else None
        if "platformCode" in case["expect"]:
            matched &= code == case["expect"]["platformCode"]
        status = "passed" if matched else "failed"
        required_failed |= not matched
        results.append({"id": case["id"], "status": status, "required": case["required"],
                        "category": result.get("category"), "outcomeKnown": result.get("outcomeKnown"),
                        "activationId": result.get("data", {}).get("activationId"), "inputSha256": digest(raw),
                        "payloadSha256": payload_identity,
                        "fixtures": case["fixtures"], "platformCode": code,
                        "resolvedRevision": revision, "targetMatches": target_matches})
    return {"schemaVersion": "latent.dev.test-report.v1", "environment": environment,
            "identity": identity, "selection": [case["id"] for case in selected], "results": results,
            "passed": not required_failed, "cleanup": "adapter-must-confirm",
            "excludedChecks": sorted(NODE_ONLY) if environment == "portable" else []}


def junit(report: dict) -> bytes:
    results = report["results"]
    failures = sum(item["status"] == "failed" or item["status"] == "unsupported" and item["required"] for item in results)
    root = ET.Element("testsuite", name="latent-" + report["environment"], tests=str(len(results)), failures=str(failures))
    for item in results:
        case = ET.SubElement(root, "testcase", name=item["id"])
        if item["status"] == "failed" or item["status"] == "unsupported" and item["required"]:
            ET.SubElement(case, "failure", message=item["status"])
        elif item["status"] == "unsupported":
            ET.SubElement(case, "skipped", message="optional unsupported scenario")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
