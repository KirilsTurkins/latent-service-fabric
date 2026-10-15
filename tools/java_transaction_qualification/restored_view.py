"""Observe the named current restore's incompatible minimum; no cause inference."""
from __future__ import annotations

from . import configuration as cfg, http, lifecycle, recovery, schema_view
from .inputs import require


def minimum_refused(campaign, count, before, inspected_view, resumed_view, recovered, writer_item):
    """Bracket one original minimum refusal with healthy restored-history queries."""
    require(campaign.service == cfg.SERVICE, "current-terminal-restore-minimum-observation")
    minimum = http.view_token(before["state-view"])
    inspected = bytes(recovery.original_view(inspected_view))
    resumed = bytes(recovery.original_view(resumed_view))
    ready = http.view_token(recovered["state-view"])
    # This named case restores the writer schema. Native readable-schema review
    # is broader; it does not replace this exact retained companion association.
    binding = schema_view._binding(lifecycle.schema(writer_item))
    require(before["disposition"] == recovered["disposition"] == "query"
            and all(view[3:35] == binding and view[35:43] == (1).to_bytes(8, "little")
                    for view in (minimum, inspected, resumed, ready)),
            "actual-restored-query-scope-binding")
    require(minimum[51:59] == inspected[51:59]
            and inspected[51:67] == resumed[51:67] == ready[51:67]
            and int.from_bytes(inspected[59:67], "little") > int.from_bytes(minimum[59:67], "little"),
            "actual-restored-query-recovery-history")
    generation = int.from_bytes(inspected[43:51], "little")
    # Restore imports the snapshot generation; never order it against the lost
    # newer history. First native activation advances only that generation.
    require(generation < 2**64 - 1
            and int.from_bytes(resumed[43:51], "little") == generation + 1
            and int.from_bytes(ready[43:51], "little") >= int.from_bytes(resumed[43:51], "little"),
            "actual-ready-restored-query-view")
    refusal = campaign.socket("query", minimum=before["state-view"], subject=cfg.ALICE)
    # Epoch incompatibility maps to Unavailable, separately from a future
    # generation's Conflict. Redacted HTTP does not reveal its private producer.
    require(type(refusal["status"]) is int and refusal["status"] == 503
            and refusal.get("bodyLost", False) is False and refusal.get("body") == b"Unavailable\n",
            "actual-incompatible-restore-minimum-refusal")
    following, _ = campaign.query(count)
    require(following["disposition"] == "query"
            and http.view_token(following["state-view"]) == ready,
            "restore-minimum-refusal-preserves-ready-view")
    campaign.client.evidence.passed("restore-refuses-stale-query-minimum", {
        "status": refusal["status"], "platformBodyBytes": len(refusal["body"]),
        "originalMinimum": before["state-view"], "inspectedNativeView": inspected_view,
        "resumedNativeView": resumed_view, "freshQueryBefore": recovered, "freshQueryAfter": following,
        "underlyingPlatformError": "unobserved-redacted-http"})
    return recovered
