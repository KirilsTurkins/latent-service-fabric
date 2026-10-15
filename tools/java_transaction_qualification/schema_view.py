"""Check schema-bound descriptive views; native review remains authoritative."""
from __future__ import annotations

import hashlib

from . import configuration as cfg, http, lifecycle, recovery
from .inputs import require


def _binding(schema):
    recovery.original_digest(schema)
    # session::codec::key_prefix: the campaign uses namespace scope, incarnation 1,
    # with no entity. session::version::scope_digest also binds the exact schema.
    prefix = bytearray(b"state-v1\0")
    for value in (cfg.TENANT, cfg.NAMESPACE):
        raw = value.encode("utf-8")
        prefix.extend(len(raw).to_bytes(2, "little"))
        prefix.extend(raw)
    prefix.extend((1).to_bytes(8, "little"))
    prefix.append(0)
    return hashlib.sha256(b"lsf-namespace-view-v2\0" + prefix + schema.encode("ascii")).digest()


def advanced(previous, current, original_item, target_item):
    old, new = bytes(recovery.original_view(previous)), bytes(recovery.original_view(current))
    # Re-read each retained, digest-bound companion using the existing collector
    # path. These expected identities are observations, never decoder grants.
    original_schema, target_schema = lifecycle.schema(original_item), lifecycle.schema(target_item)
    require(original_schema != target_schema
            and old[3:35] == _binding(original_schema) and new[3:35] == _binding(target_schema)
            and old[35:43] == new[35:43] == (1).to_bytes(8, "little"),
            "actual-native-schema-view-binding")
    generation, epoch = int.from_bytes(old[43:51], "little"), int.from_bytes(old[51:59], "little")
    # MigrationProgress::result_namespace/result_history use checked_add(1).
    require(generation < 2**64 - 1 and epoch < 2**64 - 1
            and int.from_bytes(new[43:51], "little") == generation + 1
            and int.from_bytes(new[51:59], "little") == epoch + 1
            and new[59:67] == old[59:67], "actual-native-schema-history-advanced")


def minimum_refused(campaign, count, before, original_view, migrated_view, original_item, target_item):
    """Observe this schema-history refusal, without inferring its private cause."""
    require(campaign.service == cfg.SERVICE, "current-terminal-schema-minimum-observation")
    advanced(original_view, migrated_view, original_item, target_item)
    original, migrated = bytes(recovery.original_view(original_view)), bytes(recovery.original_view(migrated_view))
    minimum = http.view_token(before["state-view"])
    require(before["disposition"] == "query" and minimum[:43] == original[:43]
            and minimum[51:67] == original[51:67]
            and int.from_bytes(minimum[43:51], "little") <= int.from_bytes(original[43:51], "little"),
            "original-pre-schema-query-minimum")
    current, _ = campaign.query(count)
    ready = http.view_token(current["state-view"])
    require(current["disposition"] == "query" and ready[:43] == migrated[:43]
            and ready[51:67] == migrated[51:67]
            and int.from_bytes(ready[43:51], "little") >= int.from_bytes(migrated[43:51], "little"),
            "actual-ready-migrated-query-view")
    refusal = campaign.socket("query", minimum=before["state-view"], subject=cfg.ALICE)
    # The native minimum-view contract rejects incompatible schema/history as
    # Unavailable. Future-generation conflict remains the separate 409 contract.
    require(type(refusal["status"]) is int and refusal["status"] == 503
            and refusal.get("bodyLost") is False and refusal.get("body") == b"Unavailable\n",
            "actual-incompatible-schema-minimum-refusal")
    following, _ = campaign.query(count)
    require(following["disposition"] == "query"
            and http.view_token(following["state-view"]) == ready,
            "schema-minimum-refusal-preserves-ready-view")
    campaign.client.evidence.passed("schema-refuses-stale-query-minimum", {
        "status": refusal["status"], "platformBodyBytes": len(refusal["body"]),
        "originalMinimum": before["state-view"], "originalNativeView": original_view,
        "migratedNativeView": migrated_view, "freshQueryBefore": current, "freshQueryAfter": following,
        "underlyingPlatformError": "unobserved-redacted-http"})
    return current
