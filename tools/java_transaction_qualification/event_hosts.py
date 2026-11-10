"""Validate observed signed event and provider identities without granting authority."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from types import MappingProxyType
from typing import Mapping

from .configuration import ALICE, CONTRACT, DEPLOYMENT, NAMESPACE, RESULT_POLICY, SERVICE, STATE_POLICY, TENANT
from .inputs import decode, digest, require
from .policies import (CALLER_FIELDS, EFFECT_FIELDS, INSPECTION_FIELDS, PROVIDER_FIELDS,
                       _caller, epoch, identifier, sha)

PROFILE_FIELDS = {"provider", "destination", "adapter", "intent_format", "payload_format", "idempotency_profile"}
PREVIEW_FIELDS = {"configurationDigest", "configurationEpoch", "profile"}


def _identity(value):
    identifier(value)
    require(not any(unicodedata.category(char) == "Cc" for char in value), "event-control-character")
    return value


@dataclass(frozen=True)
class ConfiguredEventProfile:
    """Original native provider profile; this selection grants no authority."""
    provider_id: str
    topic: str
    idempotency_profile: str
    configuration_digest: str
    configuration_epoch: int


def select_profile(preview: dict, provider_id: str, topic: str) -> ConfiguredEventProfile:
    _identity(provider_id)
    _identity(topic)
    require(isinstance(preview, dict) and len(preview) == 2 and set(preview) == {"schemaVersion", "adapters"}
            and preview["schemaVersion"] == "latent.configured-event-effect-inspection.v1"
            and isinstance(preview["adapters"], list) and 0 < len(preview["adapters"]) <= 16,
            "bounded-native-event-profile-preview")
    matches = [row for row in preview["adapters"] if isinstance(row, dict)
               and isinstance(row.get("profile"), dict) and row["profile"].get("provider") == provider_id
               and row["profile"].get("destination") == topic]
    require(len(matches) == 1 and len(matches[0]) == len(PREVIEW_FIELDS)
            and len(matches[0]["profile"]) == len(PROFILE_FIELDS)
            and set(matches[0]) == PREVIEW_FIELDS and set(matches[0]["profile"]) == PROFILE_FIELDS, "single-original-event-profile")
    row, profile = matches[0], matches[0]["profile"]
    require(profile["adapter"] == "nats-jetstream-effect-v1"
            and type(profile["intent_format"]) is int and profile["intent_format"] == 1
            and profile["payload_format"] == "nats-event-value-v1"
            and isinstance(profile["idempotency_profile"], str)
            and re.fullmatch(r"js-window-v1:[0-9a-f]{64}", profile["idempotency_profile"]),
            "exact-native-event-profile")
    sha(row["configurationDigest"])
    version = epoch(row["configurationEpoch"])
    return ConfiguredEventProfile(provider_id, topic, profile["idempotency_profile"],
                                  row["configurationDigest"], version)


@dataclass(frozen=True)
class ObservedEventHost:
    """Exact inspection proposal, not a policy decision or publication receipt."""
    provider: Mapping[str, object]
    effect: Mapping[str, object]
    profile: Mapping[str, object]
    alice: Mapping[str, object]
    operation_digest: str
    host_digest: str

    @classmethod
    def read(cls, host: dict, preview: dict, operations: list[dict], requirements: bytes):
        require(isinstance(host, dict) and len(host) == len(INSPECTION_FIELDS) + 1
                and set(host) == INSPECTION_FIELDS | {"deferredEvent"}
                and host["schemaVersion"] == "latent.transaction-host-inspection.v1"
                and host["deferredHttp"] == [], "exact-native-event-host-inspection")
        _identity(host["stateProviderProfile"])
        sha(host["stateConfigurationDigest"])
        epoch(host["stateConfigurationEpoch"])
        for name in ("configuredHttpCallers", "configuredTransportCallers"):
            callers = host[name]
            require(isinstance(callers, list) and 0 < len(callers) <= 64
                    and all(isinstance(row, dict) and len(row) == len(CALLER_FIELDS) and set(row) == CALLER_FIELDS
                            and row["ownerKind"] in {"user", "administrator"}
                            and row["service"] is None and row["recoveryKind"] == "original-caller"
                            for row in callers), "bounded-event-authenticated-callers")
            for caller in callers:
                for field in ("subject", "tenant", "recoveryScope"):
                    _identity(caller[field])
            require(len({(row["subject"], row["ownerKind"], row["tenant"]) for row in callers}) == len(callers),
                    "unambiguous-event-caller-observations")
        alice = _caller(host["configuredHttpCallers"], ALICE, "user")
        require(alice == _caller(host["configuredTransportCallers"], ALICE, "user"),
                "same-event-http-and-transport-caller")
        require(isinstance(preview, dict) and len(preview) == 2 and set(preview) == {"schemaVersion", "adapters"}
                and preview["schemaVersion"] == "latent.configured-event-effect-inspection.v1"
                and isinstance(preview["adapters"], list) and 0 < len(preview["adapters"]) <= 16,
                "bounded-native-event-profile-preview")
        require(isinstance(operations, list) and len(operations) == 3
                and {row.get("function") for row in operations if isinstance(row, dict)} == {"update", "query", "scan"},
                "exact-selected-event-operations")
        base_fields = {"tenant", "componentDigest", "publication", "contract", "function", "deployment", "route",
                       "binding", "companionDigest", "incarnation", "resultPolicy", "statePolicies"}
        require(all(len(row) == len(base_fields) + int(row["function"] == "update")
                    and set(row) == base_fields | ({"deferredEvent"} if row["function"] == "update" else set())
                    and row["tenant"] == TENANT and row["contract"] == CONTRACT
                    and row["deployment"] == DEPLOYMENT and row["route"] == DEPLOYMENT and row["binding"] == DEPLOYMENT
                    and type(row["incarnation"]) is int and row["incarnation"] == 1
                    and row["resultPolicy"] == RESULT_POLICY and row["statePolicies"] == [STATE_POLICY]
                    and isinstance(row["publication"], str)
                    and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", row["publication"])
                    and isinstance(row["componentDigest"], str)
                    and re.fullmatch(r"sha256:[0-9a-f]{64}", row["componentDigest"])
                    and isinstance(row["companionDigest"], str)
                    and re.fullmatch(r"sha256:[0-9a-f]{64}", row["companionDigest"])
                    for row in operations)
                and len({(row["publication"], row["componentDigest"], row["companionDigest"]) for row in operations}) == 1,
                "exact-event-operation-scope")
        selected = [row for row in operations if "deferredEvent" in row]
        require(len(selected) == 1 and selected[0]["function"] == "update", "single-event-command-selection")
        operation = selected[0]
        config = operation["deferredEvent"]
        require(isinstance(config, dict) and len(config) == 9 and set(config) == {"requirementsDigest", "providerId", "providerIncarnation",
                "credentialReference", "stagingBinding", "stagingPolicies", "dispatchBinding", "dispatchPolicies", "dispatchAuthority"}
                and config["dispatchAuthority"] == {"formatVersion": 1, "mode": "signed-service-integration"}
                and type(config["dispatchAuthority"]["formatVersion"]) is int
                and isinstance(config["providerId"], str) and isinstance(config["providerIncarnation"], str)
                and re.fullmatch(r"[0-9a-f]{64}", config["providerIncarnation"])
                and isinstance(requirements, bytes) and 0 < len(requirements) <= 8192
                and digest(requirements) == config["requirementsDigest"], "exact-selected-event-constraints")
        for field in ("providerId", "credentialReference", "stagingBinding", "dispatchBinding"):
            _identity(config[field])
        for field in ("stagingPolicies", "dispatchPolicies"):
            require(isinstance(config[field], list) and len(config[field]) == 1, "single-event-policy-selection")
            _identity(config[field][0])
        document = decode(requirements, 8192)
        require(isinstance(document, dict) and len(document) == 13 and set(document) == {"formatVersion", "protocol", "capsule", "deployment",
                "stateBinding", "namespace", "companionDigest", "binding", "operation", "adapter", "payloadFormat",
                "idempotencyProfile", "ceiling"} and type(document.get("formatVersion")) is int
                and document.get("formatVersion") == 1
                and document.get("protocol") == "lsf-jetstream-event-v1"
                and document.get("capsule") == SERVICE and document.get("deployment") == DEPLOYMENT
                and document.get("stateBinding") == DEPLOYMENT and document.get("namespace") == NAMESPACE
                and document.get("companionDigest") == operation.get("companionDigest")
                and document.get("binding") == "approved-event"
                and document.get("ceiling") == {"maximum_payload_bytes": 8192, "maximum_response_bytes": 16384,
                    "maximum_attempts": 3, "maximum_age_millis": 60000, "attempt_timeout_millis": 5000}
                and all(type(value) is int for value in document["ceiling"].values())
                and document.get("operation") == "event" and document.get("adapter") == "nats-jetstream-effect-v1"
                and document.get("payloadFormat") == "nats-event-value-v1"
                and isinstance(document.get("idempotencyProfile"), str)
                and re.fullmatch(r"js-window-v1:[0-9a-f]{64}", document["idempotencyProfile"]),
                "exact-event-requirements-profile")
        rows = host["deferredEvent"]
        require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
                and len(rows[0]) == len(EFFECT_FIELDS) and set(rows[0]) == EFFECT_FIELDS, "single-signed-event-observation")
        effect = rows[0]
        subject = f"service:{len(TENANT.encode())}:{TENANT}:{len(SERVICE.encode())}:{SERVICE}"
        require(effect["tenant"] == TENANT and effect["service"] == SERVICE
                and effect["publication"] == operation["publication"] and effect["namespace"] == NAMESPACE
                and type(effect["incarnation"]) is int and type(operation["incarnation"]) is int
                and effect["incarnation"] == operation["incarnation"] and effect["resultPolicy"] == RESULT_POLICY
                and effect["logicalBinding"] == document.get("binding") and effect["operation"] == "event"
                and effect["stagingBinding"] == config["stagingBinding"]
                and effect["dispatchBinding"] == config["dispatchBinding"]
                and effect["providerProfile"] == "nats-jetstream-effect-v1"
                and effect["configurationDigest"] == "sha256:" + document["idempotencyProfile"].removeprefix("js-window-v1:")
                and effect["dispatchSubject"] == subject and effect["dispatchRecoveryKind"] == "service-integration",
                "same-signed-event-scope-and-purpose")
        _identity(effect["dispatchRecoveryScope"])
        epoch(effect["configurationEpoch"])
        providers = host["configuredProviders"]
        require(isinstance(providers, list) and len(providers) <= 64, "bounded-native-provider-observations")
        matches = [row for row in providers if isinstance(row, dict) and row.get("id") == config["providerId"]]
        require(len(matches) == 1 and len(matches[0]) == len(PROVIDER_FIELDS)
                and set(matches[0]) == PROVIDER_FIELDS, "single-original-event-provider")
        provider = matches[0]
        require(provider["tenant"] == TENANT and provider["capability"] == "latent:events/publisher@0.2.0"
                and provider["configurationDigest"] == "sha256:" + config["providerIncarnation"],
                "same-original-event-provider-configuration")
        _identity(provider["id"])
        _identity(provider["service"])
        _identity(provider["profile"])
        sha(provider["configurationDigest"])
        provider_epoch = epoch(provider["configurationEpoch"], decimal=True)
        rows = [row for row in preview["adapters"] if isinstance(row, dict)
                and isinstance(row.get("profile"), dict)
                and row["profile"].get("idempotency_profile") == document["idempotencyProfile"]]
        require(len(rows) == 1 and len(rows[0]) == len(PREVIEW_FIELDS) and len(rows[0]["profile"]) == len(PROFILE_FIELDS)
                and set(rows[0]) == PREVIEW_FIELDS and set(rows[0]["profile"]) == PROFILE_FIELDS,
                "single-original-event-adapter-profile")
        row = rows[0]
        profile = row["profile"]
        require(row["configurationDigest"] == provider["configurationDigest"]
                and type(row["configurationEpoch"]) is int
                and row["configurationEpoch"] == provider_epoch == effect["configurationEpoch"]
                and profile["provider"] == config["providerId"] and profile["adapter"] == effect["providerProfile"]
                and type(profile["intent_format"]) is int and profile["intent_format"] == 1 and profile["payload_format"] == "nats-event-value-v1",
                "same-installed-event-adapter-owner")
        _identity(profile["destination"])
        selected_profile = select_profile(preview, config["providerId"], profile["destination"])
        require(selected_profile.idempotency_profile == document["idempotencyProfile"]
                and selected_profile.configuration_digest == provider["configurationDigest"]
                and selected_profile.configuration_epoch == provider_epoch,
                "same-unique-event-provider-selection")
        return cls(MappingProxyType(dict(provider)), MappingProxyType(dict(effect)),
                   MappingProxyType(dict(profile)), MappingProxyType(dict(alice)), _operation_digest(operation),
                   _host_digest(host))


def _host_digest(host: dict) -> str:
    raw = json.dumps(host, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    require(len(raw) <= 262144, 'bounded-event-host-observation')
    return hashlib.sha256(raw).hexdigest()


def complete_policy_documents(observed: ObservedEventHost, host: dict, operation: dict, *, go_random=False) -> dict:
    """Propose state, clock, and event rules for one unchanged native observation."""
    from .configuration import CLOCKS, OPERATOR
    from .policies import (DATA_OPERATIONS, MANAGEMENT_OPERATIONS, RECOVERY_OPERATIONS,
                           STATE_CONTRACT, _caller, binding, rule, scope)
    require(isinstance(host, dict) and _host_digest(host) == observed.host_digest,
            'same-original-event-host-observation')
    publication = operation['publication']
    proposals = policy_documents(observed, operation)
    operator = _caller(host['configuredTransportCallers'], OPERATOR, 'administrator')
    rows = host['configuredProviders']
    require(type(go_random) is bool and isinstance(rows, list) and len(rows) == (5 if go_random else 4),
            'exact-event-clock-http-provider-set')
    clocks = {}
    for name, (capability, clock_operation) in CLOCKS.items():
        selected = [row for row in rows if isinstance(row, dict) and row.get('id') == name]
        require(len(selected) == 1 and set(selected[0]) == PROVIDER_FIELDS
                and selected[0]['tenant'] == TENANT and selected[0]['service'] == 'runtime-host'
                and selected[0]['capability'] == capability, 'exact-observed-clock-provider')
        clocks[name] = selected[0]
    proposals['bindings']['transaction-java-aggregate'] = binding(
        STATE_CONTRACT, host['stateProviderProfile'], host['stateConfigurationDigest'],
        host['stateConfigurationEpoch'], [])
    state_rules = []
    for caller, operations in ((observed.alice, DATA_OPERATIONS + ['inspect-effect', 'cancel-command']),
                               (operator, MANAGEMENT_OPERATIONS)):
        state_rules.append(rule(caller['ownerKind'], caller['ownerKind'], caller['subject'], [publication],
            STATE_CONTRACT, operations, {'kind': 'state', 'scopes': [scope(caller)]}))
    state_rules.append(rule('native-recovery', 'administrator', operator['subject'], [publication],
        STATE_CONTRACT, RECOVERY_OPERATIONS, {'kind': 'state', 'scopes': [scope(operator)]},
        input_bytes=64 * 1024 * 1024, output_bytes=64 * 1024 * 1024, calls=1, wall=60000))
    proposals['policies'][STATE_POLICY] = {'formatVersion': 1, 'tenant': TENANT, 'rules': state_rules}
    proposals['deploymentGrants'].append({'capability': STATE_CONTRACT, 'policy': STATE_POLICY,
                                         'operations': list(DATA_OPERATIONS)})
    for name, (capability, clock_operation) in CLOCKS.items():
        descriptor = clocks[name]
        policy_name = {'clockMonotonic': 'clock-monotonic', 'clockWall': 'clock-wall'}[name]
        proposals['bindings'][policy_name + '-installed'] = binding(capability, descriptor['profile'],
            descriptor['configurationDigest'], epoch(descriptor['configurationEpoch'], decimal=True), [clock_operation])
        proposals['policies'][policy_name + '-allow'] = {'formatVersion': 1, 'tenant': TENANT, 'rules': [
            rule('clock', 'user', ALICE, [publication], capability, [clock_operation], {'kind': 'clock'},
                 input_bytes=0, output_bytes=32768, calls=4096, wall=120000)]}
        proposals['deploymentGrants'].append({'capability': capability, 'policy': policy_name + '-allow'})
    if go_random:
        random = [row for row in rows if isinstance(row, dict) and row.get('id') == 'random']
        capability = 'latent:random/random@0.1.0'
        require(len(random) == 1 and set(random[0]) == PROVIDER_FIELDS
                and random[0]['tenant'] == TENANT and random[0]['service'] == 'runtime-host'
                and random[0]['capability'] == capability and random[0]['profile'] == 'system-random-v1',
                'exact-observed-random-provider')
        descriptor = random[0]
        proposals['bindings']['random-installed'] = binding(capability, descriptor['profile'],
            descriptor['configurationDigest'], epoch(descriptor['configurationEpoch'], decimal=True), ['u64-value'])
        proposals['policies']['random-allow'] = {'formatVersion': 1, 'tenant': TENANT, 'rules': [
            rule('random', 'user', ALICE, [publication], capability, ['u64-value'], {'kind': 'random'},
                 input_bytes=8, output_bytes=32768, calls=4096, wall=120000)]}
        proposals['deploymentGrants'].append({'capability': capability, 'policy': 'random-allow'})
    return proposals


def _operation_digest(operation: dict) -> str:
    fields = {"tenant", "componentDigest", "publication", "contract", "function", "deployment", "route", "binding",
              "companionDigest", "incarnation", "resultPolicy", "statePolicies", "deferredEvent"}
    require(isinstance(operation, dict) and len(operation) == len(fields) and set(operation) == fields, "closed-event-operation-observation")
    for field in fields - {"incarnation", "statePolicies", "deferredEvent"}:
        require(isinstance(operation[field], str) and 0 < len(operation[field]) <= 256,
                "bounded-event-operation-text")
    require(type(operation["incarnation"]) is int and operation["incarnation"] == 1
            and operation["statePolicies"] == [STATE_POLICY], "bounded-event-operation-scope")
    effect = operation["deferredEvent"]
    effect_fields = {"requirementsDigest", "providerId", "providerIncarnation", "credentialReference", "stagingBinding",
                     "stagingPolicies", "dispatchBinding", "dispatchPolicies", "dispatchAuthority"}
    require(isinstance(effect, dict) and len(effect) == len(effect_fields) and set(effect) == effect_fields
            and effect["dispatchAuthority"] == {"formatVersion": 1, "mode": "signed-service-integration"}
            and type(effect["dispatchAuthority"]["formatVersion"]) is int,
            "closed-event-operation-authority")
    for field in effect_fields - {"stagingPolicies", "dispatchPolicies", "dispatchAuthority"}:
        require(isinstance(effect[field], str) and 0 < len(effect[field]) <= 256,
                "bounded-event-operation-pin")
    for field in ("stagingPolicies", "dispatchPolicies"):
        require(isinstance(effect[field], list) and len(effect[field]) == 1
                and isinstance(effect[field][0], str) and 0 < len(effect[field][0]) <= 256,
                "bounded-event-operation-policy")
    raw = json.dumps(operation, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    require(len(raw) <= 8192, "bounded-event-operation-observation")
    return hashlib.sha256(raw).hexdigest()


def policy_documents(observed: ObservedEventHost, operation: dict) -> dict:
    """Prepare narrow policies from observations; only a separate apply can grant them."""
    from .policies import INTENT_CONTRACT, binding, rule, scope
    config = operation.get("deferredEvent") if isinstance(operation, dict) else None
    require(isinstance(config, dict) and _operation_digest(operation) == observed.operation_digest
            and operation.get("publication") == observed.effect["publication"]
            and config.get("stagingBinding") == observed.effect["stagingBinding"]
            and config.get("dispatchBinding") == observed.effect["dispatchBinding"]
            and isinstance(config.get("stagingPolicies"), list) and len(config["stagingPolicies"]) == 1
            and isinstance(config.get("dispatchPolicies"), list) and len(config["dispatchPolicies"]) == 1,
            "same-observed-event-policy-selection")
    names = [config["stagingBinding"], config["dispatchBinding"], config["stagingPolicies"][0], config["dispatchPolicies"][0]]
    require(all(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) for name in names)
            and names[0] != names[1] and names[2] != names[3], "distinct-event-policy-owner-identities")
    effect, provider = observed.effect, observed.provider
    publication = effect["publication"]
    event_contract = "latent:events/publisher@0.2.0"
    return {"bindings": {
                names[0]: binding(INTENT_CONTRACT, effect["providerProfile"], effect["configurationDigest"],
                                  effect["configurationEpoch"], ["stage"]),
                names[1]: binding(event_contract, provider["profile"], provider["configurationDigest"],
                                  epoch(provider["configurationEpoch"], decimal=True), ["publish"])},
            "policies": {
                names[2]: {"formatVersion": 1, "tenant": TENANT, "rules": [
                    rule("original-caller", "user", ALICE, [publication], INTENT_CONTRACT, ["stage"],
                         {"kind": "state", "scopes": [scope(observed.alice)]}, input_bytes=65536, output_bytes=65536, calls=1)]},
                names[3]: {"formatVersion": 1, "tenant": TENANT, "rules": [
                    rule("original-source", "service", effect["dispatchSubject"], [publication], event_contract,
                         ["publish"], {"kind": "events", "subjects": [observed.profile["destination"]]},
                         input_bytes=8192, output_bytes=16384, calls=1, wall=5000)]}},
            "deploymentGrants": [{"capability": INTENT_CONTRACT, "policy": names[2], "operations": ["stage"]}]}
