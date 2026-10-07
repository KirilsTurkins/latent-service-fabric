"""Data-only review bytes for the existing disposable Java diagnostic program.

These documents confer no authority. Their identities come from the actual
native startup observation and original signed publications; application still
uses the normal policy owner and its current generation/receipt checks.
"""
from copy import deepcopy
import hashlib
import json
import re

from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import require
from tools.java_http_composition.node import (
    ADAPTER, CHILD_SUBJECT, CONTEXT_REQUIRED, DOMAIN, SERVICE_CAPABILITY, TENANT,
)

# Existing buffered fixture limits, including the native provider's canonical
# header/container copies (latent-http HttpLimits::output_reservation).
HTTP_OUTPUT_RESERVATION_BYTES = 4096 + 2 * 4096 + 16 * 64 + 1024


def _publication(value):
    require(isinstance(value, str) and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", value),
            "java-diagnostic-original-publication")
    return value


def _installed(startup, name, contract, profile, service):
    rows = [row for row in startup["providers"] if row["id"] == name]
    require(len(rows) == 1, "java-diagnostic-original-installed-owner")
    actual = rows[0]
    require(actual["tenant"] == TENANT and actual["service"] == service
            and actual["capability"] == contract and actual["profile"] == profile
            and actual["configurationEpoch"] == "1"
            and isinstance(actual["configurationDigest"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", actual["configurationDigest"]),
            "java-diagnostic-installed-profile")
    return actual


def _proposal(kind, name, document):
    return {"kind": kind, "id": name, "document": document}


def _binding(name, contract, actual, operation):
    return _proposal("provider-binding", name, {"formatVersion": 1, "tenant": TENANT,
        "capability": contract, "providerProfile": actual["profile"],
        "configurationDigest": actual["configurationDigest"], "configurationEpoch": 1,
        "restriction": {"operations": [operation]}})


def runtime(startup, publications):
    require(set(publications) == {"domain", "adapter", "adapter-next", "context-required"},
            "java-diagnostic-original-publication-set")
    selected = sorted(_publication(value) for value in publications.values())
    require(len(set(selected)) == 4, "java-diagnostic-distinct-original-publications")
    result = []
    for name, (contract, profile, operation, kind) in profiles("java").items():
        actual = _installed(startup, name, contract, profile, "runtime-host")
        result.append(_binding(name + "-installed", contract, actual, operation))
        result.append(_proposal("policy", name + "-allow", {"formatVersion": 1, "tenant": TENANT,
            "rules": [{"id": "runtime", "effect": "allow", "principals": [
                {"kind": "administrator", "subject": "workflow-operator"},
                {"kind": "trigger", "subject": "java-http-ingress"},
                {"kind": "service", "subject": CHILD_SUBJECT}],
                "services": [ADAPTER, DOMAIN, CONTEXT_REQUIRED], "publications": selected,
                "capability": contract, "operations": [operation], "resources": {"kind": kind},
                "ceiling": {"operations": 4096, "inputBytes": 0, "outputBytes": 32768,
                            "wallTimeMillis": 5000}}]}))
    return result


def service(startup, publications, *, trigger_only=False):
    actual = _installed(startup, "localService", SERVICE_CAPABILITY,
                        "lsf-local-service-invocation-v1", DOMAIN)
    principals = [{"kind": "trigger", "subject": "java-http-ingress"}]
    if not trigger_only:
        principals.append({"kind": "administrator", "subject": "workflow-operator"})
    return [_binding("java-domain-installed", SERVICE_CAPABILITY, actual, "call"),
        _proposal("policy", "java-domain-allow", {"formatVersion": 1, "tenant": TENANT, "rules": [{
            "id": "selected-domain", "effect": "allow", "principals": principals,
            "services": [ADAPTER], "publications": [_publication(publications["adapter"]),
                                                    _publication(publications["adapter-next"])],
            "capability": SERVICE_CAPABILITY, "operations": ["call"],
            "resources": {"kind": "service", "services": [DOMAIN],
                          "publications": [_publication(publications["domain"])]},
            "ceiling": {"operations": 4, "inputBytes": 1048576, "outputBytes": 1048576,
                        "wallTimeMillis": 60000}}]})]


def http(startup, publication, port):
    from tools.java_http_composition.provider_timeout import BINDING, CAPABILITY, POLICY
    require(type(port) is int and 1 <= port <= 65535, "java-provider-selected-port")
    actual = _installed(startup, "http", CAPABILITY, "bounded-http-v1", "http-host")
    return [_binding(BINDING, CAPABILITY, actual, "send"),
        _proposal("policy", POLICY, {"formatVersion": 1, "tenant": TENANT, "rules": [{
            "id": "selected-domain", "effect": "allow", "principals": [
                {"kind": "administrator", "subject": "workflow-operator"},
                {"kind": "service", "subject": CHILD_SUBJECT}],
            "services": [DOMAIN], "publications": [_publication(publication)], "capability": CAPABILITY,
            "operations": ["send"], "resources": {"kind": "http",
                "origins": [{"scheme": "http", "host": "localhost", "port": port}],
                "methods": ["GET"], "paths": ["/allowed"], "pathPrefixes": []},
            "ceiling": {"operations": 1, "inputBytes": 4096, "outputBytes": HTTP_OUTPUT_RESERVATION_BYTES,
                        "wallTimeMillis": 1000}}]})]


def wrong_clock(document):
    result = deepcopy(document)
    changed = 0
    for rule in result["rules"]:
        for principal in rule["principals"]:
            if principal["kind"] == "service":
                require(principal["subject"] == CHILD_SUBJECT, "java-diagnostic-original-clock-caller")
                principal["subject"] = "service:8:examples:22:examples/wrong-adapter"
                changed += 1
    require(changed == 1, "java-diagnostic-original-clock-principal")
    return result


def program(startup, publications, port):
    """Eight initial records and the original four explicit revisions, no apply."""
    initial = http(startup, publications["domain"], port) + runtime(startup, publications) + service(startup, publications)
    require(len(initial) == 8, "java-diagnostic-initial-record-count")
    clocks = next(row for row in initial if row["id"] == "clockMonotonic-allow")
    selected_service = next(row for row in initial if row["id"] == "java-domain-allow")
    revisions = [
        {**_proposal("policy", clocks["id"], wrong_clock(clocks["document"])), "expectedGeneration": "1"},
        {**deepcopy(clocks), "expectedGeneration": "2"},
        {**_proposal("policy", selected_service["id"], {"formatVersion": 1, "tenant": TENANT, "rules": []}),
         "expectedGeneration": "1"},
        {**deepcopy(selected_service), "expectedGeneration": "2"}]
    return {"initial": [{**row, "expectedGeneration": "0"} for row in initial], "revisions": revisions,
            "initialCount": 8, "revisionCount": 4, "signingPoliciesIncluded": False,
            "authorityApplied": False}


def review_bytes(document):
    """The exact compact file representation used by static_api.node.policy."""
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    require(len(encoded) <= 65536, "java-diagnostic-policy-byte-bound")
    return encoded


def reviewed(program):
    result = deepcopy(program)
    for group in ("initial", "revisions"):
        for row in result[group]:
            encoded = review_bytes(row["document"])
            row.update(bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest())
    return result
