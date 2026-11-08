"""Validate observed signed event and provider identities without granting authority."""
from __future__ import annotations
from dataclasses import dataclass
import re

from .configuration import DEPLOYMENT, NAMESPACE, RESULT_POLICY, SERVICE, TENANT
from .inputs import decode, digest, require
from .policies import EFFECT_FIELDS, INSPECTION_FIELDS, PROVIDER_FIELDS, epoch, identifier, sha

PROFILE_FIELDS = {"provider", "destination", "adapter", "intent_format", "payload_format", "idempotency_profile"}
PREVIEW_FIELDS = {"configurationDigest", "configurationEpoch", "profile"}


@dataclass(frozen=True)
class ObservedEventHost:
    """Exact inspection proposal, not a policy decision or publication receipt."""
    provider: dict
    effect: dict
    profile: dict

    @classmethod
    def read(cls, host: dict, preview: dict, operations: list[dict], requirements: bytes):
        require(isinstance(host, dict) and set(host) == INSPECTION_FIELDS | {"deferredEvent"}
                and host["schemaVersion"] == "latent.transaction-host-inspection.v1"
                and host["deferredHttp"] == [], "exact-native-event-host-inspection")
        require(isinstance(preview, dict) and set(preview) == {"schemaVersion", "adapters"}
                and preview["schemaVersion"] == "latent.configured-event-effect-inspection.v1"
                and isinstance(preview["adapters"], list) and 0 < len(preview["adapters"]) <= 16,
                "bounded-native-event-profile-preview")
        require(isinstance(operations, list) and len(operations) == 3
                and {row.get("function") for row in operations if isinstance(row, dict)} == {"update", "query", "scan"},
                "exact-selected-event-operations")
        selected = [row for row in operations if "deferredEvent" in row]
        require(len(selected) == 1 and selected[0]["function"] == "update", "single-event-command-selection")
        operation = selected[0]
        config = operation["deferredEvent"]
        require(isinstance(config, dict) and set(config) == {"requirementsDigest", "providerId", "providerIncarnation",
                "credentialReference", "stagingBinding", "stagingPolicies", "dispatchBinding", "dispatchPolicies", "dispatchAuthority"}
                and config["dispatchAuthority"] == {"formatVersion": 1, "mode": "signed-service-integration"}
                and type(config["dispatchAuthority"]["formatVersion"]) is int
                and isinstance(config["providerId"], str) and isinstance(config["providerIncarnation"], str)
                and re.fullmatch(r"[0-9a-f]{64}", config["providerIncarnation"])
                and isinstance(requirements, bytes) and 0 < len(requirements) <= 8192
                and digest(requirements) == config["requirementsDigest"], "exact-selected-event-constraints")
        document = decode(requirements, 8192)
        require(isinstance(document, dict) and set(document) == {"formatVersion", "protocol", "capsule", "deployment",
                "stateBinding", "namespace", "companionDigest", "binding", "operation", "adapter", "payloadFormat",
                "idempotencyProfile", "ceiling"} and type(document.get("formatVersion")) is int
                and document.get("formatVersion") == 1
                and document.get("protocol") == "lsf-jetstream-event-v1"
                and document.get("capsule") == SERVICE and document.get("deployment") == DEPLOYMENT
                and document.get("stateBinding") == DEPLOYMENT and document.get("namespace") == NAMESPACE
                and document.get("companionDigest") == operation.get("companionDigest")
                and document.get("operation") == "event" and document.get("adapter") == "nats-jetstream-effect-v1"
                and document.get("payloadFormat") == "nats-event-value-v1"
                and isinstance(document.get("idempotencyProfile"), str)
                and re.fullmatch(r"js-window-v1:[0-9a-f]{64}", document["idempotencyProfile"]),
                "exact-event-requirements-profile")
        rows = host["deferredEvent"]
        require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
                and set(rows[0]) == EFFECT_FIELDS, "single-signed-event-observation")
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
        identifier(effect["dispatchRecoveryScope"])
        epoch(effect["configurationEpoch"])
        providers = host["configuredProviders"]
        require(isinstance(providers, list) and len(providers) <= 64, "bounded-native-provider-observations")
        matches = [row for row in providers if isinstance(row, dict) and row.get("id") == config["providerId"]]
        require(len(matches) == 1 and set(matches[0]) == PROVIDER_FIELDS, "single-original-event-provider")
        provider = matches[0]
        require(provider["tenant"] == TENANT and provider["capability"] == "latent:events/publisher@0.2.0"
                and provider["configurationDigest"] == "sha256:" + config["providerIncarnation"],
                "same-original-event-provider-configuration")
        identifier(provider["profile"])
        sha(provider["configurationDigest"])
        provider_epoch = epoch(provider["configurationEpoch"], decimal=True)
        rows = [row for row in preview["adapters"] if isinstance(row, dict)
                and isinstance(row.get("profile"), dict)
                and row["profile"].get("idempotency_profile") == document["idempotencyProfile"]]
        require(len(rows) == 1 and set(rows[0]) == PREVIEW_FIELDS and set(rows[0]["profile"]) == PROFILE_FIELDS,
                "single-original-event-adapter-profile")
        row = rows[0]
        profile = row["profile"]
        require(row["configurationDigest"] == provider["configurationDigest"]
                and type(row["configurationEpoch"]) is int
                and row["configurationEpoch"] == provider_epoch == effect["configurationEpoch"]
                and profile["provider"] == config["providerId"] and profile["adapter"] == effect["providerProfile"]
                and type(profile["intent_format"]) is int and profile["intent_format"] == 1 and profile["payload_format"] == "nats-event-value-v1",
                "same-installed-event-adapter-owner")
        identifier(profile["destination"])
        return cls(provider, effect, profile)
