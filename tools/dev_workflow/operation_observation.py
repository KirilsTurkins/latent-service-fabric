"""Closed diagnostics for an unresolved original management operation.

This is an observation of the returned CLI response, never evidence that a
mutation was rejected, completed, safe to repeat, or eligible for a retry.
"""
from __future__ import annotations


CURRENTNESS_REASONS = frozenset({
    "admission-authority-busy", "admission-authority-poisoned", "admission-control-busy",
    "admission-clock-lease-uncovered", "admission-clock-regression", "admission-durability-uncertain",
    "admission-owner-retired", "admission-restart-clock-floor", "admission-verification-busy",
    "signature-clock-regression", "signature-trust-conflict", "signature-stale-proof",
})


def currentness(result: dict) -> dict | None:
    """Retain one exact public detail, excluding every free-form field."""
    if result.get("category") != "platform-failure":
        return None
    error = result.get("error")
    if not isinstance(error, dict) or type(error.get("retryable")) is not bool:
        return None
    details = error.get("details")
    if not isinstance(details, list) or len(details) != 1:
        return None
    detail = details[0]
    if not isinstance(detail, dict) or set(detail) != {"kind", "fields"} or detail["kind"] != "admission.currentness":
        return None
    fields = detail["fields"]
    if not isinstance(fields, dict) or set(fields) != {"reason"}:
        return None
    reason = fields["reason"]
    if not isinstance(reason, str) or reason not in CURRENTNESS_REASONS:
        return None
    return {"kind": "admission.currentness", "reason": reason, "retryable": error["retryable"]}
