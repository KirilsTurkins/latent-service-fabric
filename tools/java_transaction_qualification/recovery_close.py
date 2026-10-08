"""Closed observations of existing native close actions; never authority.

The native owner computes and validates the plan digest and original row CAS,
checks current purpose/actor/artifacts and writes the receipt. This collector
retains those original descriptions, with no provider acknowledgement or retry.
"""
from __future__ import annotations

import re

from . import configuration as cfg, recovery
from .inputs import require

FORMAT = "lsf.effect-recovery-close.v1"
OUTCOME = "closed-without-redrive"
PLAN_FIELDS = {"schemaVersion", "operatorId", "operationId", "scope", "expectedView", "expectedGuard",
               "lossWindowDigest", "reason", "effects"}
EFFECT_FIELDS = {"effectId", "originalDigest", "payloadDigest", "historyDigest",
                 "originalDisposition", "originalClockMillis"}
ELIGIBLE = {"Pending", "Uncertain", "KnownFailed", "RetryScheduled", "PolicyBlocked"}


def closed(value, fields):
    require(isinstance(value, dict) and set(value) == fields, "closed-native-effect-reconciliation-data")


def identity(value, maximum=256):
    require(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= maximum
            and not any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value),
            "native-reconciliation-identity-bound")


def integer(value):
    require(type(value) is int and 0 < value < 2**64, "native-reconciliation-original-integer")


def effects(values):
    require(isinstance(values, list) and 0 < len(values) <= 16
            and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in values)
            and len(set(values)) == len(values), "native-reconciliation-original-effect-selection")


def digest_bytes(value):
    raw = recovery.byte_array(value, 32)
    require(len(raw) == 32 and raw != bytes(32), "native-reconciliation-original-digest-bytes")


def plan(value):
    closed(value, PLAN_FIELDS)
    require(value["schemaVersion"] == FORMAT and value["operatorId"] == cfg.OPERATOR,
            "original-native-reconciliation-format-and-actor")
    identity(value["operationId"])
    identity(value["reason"], 128)
    scope = value["scope"]
    closed(scope, {"tenant", "namespace", "incarnation"})
    require(scope == {"tenant": cfg.TENANT, "namespace": cfg.NAMESPACE, "incarnation": 1}
            and type(scope["incarnation"]) is int, "original-native-reconciliation-scope")
    recovery.original_view(value["expectedView"])
    guard = recovery.byte_array(value["expectedGuard"], 133)
    require(len(guard) == 133, "original-native-reconciliation-guard")
    digest_bytes(value["lossWindowDigest"])
    require(isinstance(value["effects"], list) and 0 < len(value["effects"]) <= 16,
            "native-reconciliation-selection-count")
    for selected in value["effects"]:
        closed(selected, EFFECT_FIELDS)
        for name in ("originalDigest", "payloadDigest", "historyDigest"):
            digest_bytes(selected[name])
        require(isinstance(selected["originalDisposition"], str)
                and selected["originalDisposition"] in ELIGIBLE, "native-reconciliation-original-disposition")
        integer(selected["originalClockMillis"])
    identifiers = [selected["effectId"] for selected in value["effects"]]
    effects(identifiers)
    require(identifiers == sorted(identifiers), "native-reconciliation-canonical-effect-order")


def request(value):
    require(isinstance(value, dict), "closed-native-effect-reconciliation-request")
    if value.get("action") == "inspect-close-effects":
        closed(value, {"action", "operationId", "effectIds", "reason"})
        identity(value["operationId"])
        identity(value["reason"], 128)
        effects(value["effectIds"])
    else:
        closed(value, {"action", "operationId", "plan", "acknowledgement"})
        require(value["action"] == "close-effects", "unknown-native-effect-reconciliation-action")
        plan(value["plan"])
        require(value["operationId"] == value["plan"]["operationId"], "original-native-close-operation")
        recovery.original_digest(value["acknowledgement"])


def result(original, value):
    request(original)
    if original["action"] == "inspect-close-effects":
        closed(value, {"action", "plan", "planDigest", "proposedOutcome", "recoveryRemainsPaused"})
        plan(value["plan"])
        recovery.original_digest(value["planDigest"])
        require(value["action"] == original["action"] and value["proposedOutcome"] == OUTCOME
                and value["recoveryRemainsPaused"] is True
                and value["plan"]["operationId"] == original["operationId"]
                and value["plan"]["reason"] == original["reason"]
                and [item["effectId"] for item in value["plan"]["effects"]] == sorted(original["effectIds"]),
                "original-native-inspected-close-association")
    else:
        closed(value, {"action", "receipt", "recoveryRemainsPaused", "providerAcknowledgementInferred"})
        receipt = value["receipt"]
        closed(receipt, {"schemaVersion", "outcome", "plan", "acknowledgement", "observedAtMillis"})
        plan(receipt["plan"])
        integer(receipt["observedAtMillis"])
        require(value["action"] == original["action"] and value["recoveryRemainsPaused"] is True
                and value["providerAcknowledgementInferred"] is False
                and receipt["schemaVersion"] == FORMAT and receipt["outcome"] == OUTCOME
                and receipt["plan"] == original["plan"]
                and recovery.byte_array(receipt["acknowledgement"], 32)
                    == bytes.fromhex(original["acknowledgement"][7:])
                and all(item["originalClockMillis"] <= receipt["observedAtMillis"]
                        for item in receipt["plan"]["effects"]),
                "original-native-close-receipt-is-never-provider-success")
    return value
