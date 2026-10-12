"""Closed Angular failure evidence; never error strings or a new authority."""
from __future__ import annotations

import re

from tools.phase2_operator_process import failed_call_record, stopped_record

# Existing producer-owned latent_core::error::ADMISSION_CURRENTNESS_REASONS.
CURRENTNESS_REASONS = (
    "admission-authority-busy", "admission-authority-poisoned", "admission-control-busy",
    "admission-clock-lease-uncovered", "admission-clock-regression", "admission-durability-uncertain",
    "admission-owner-retired", "admission-restart-clock-floor", "admission-verification-busy",
    "signature-clock-regression", "signature-trust-conflict", "signature-stale-proof",
)
WEB_COMMANDS = frozenset({
    "web publish", "web get", "web prepare", "web operation", "web renew-evidence", "web revoke",
})
STAGES = frozenset({
    "acquire", "protected-configuration-checked", "signed-admission-and-tenant-checks-complete",
    "immutable-assets-before-renderer-preparation-checked", "isolated-cold-preparation-complete",
    "selected-deployment-applied", "render-failure-and-cancellation-recovery-complete",
    "evidence-renewal-and-stale-grant-checks-complete",
    "independent-publication-revocation-and-cas-rollback-checked",
    "selected-lifecycle-and-http-checks-complete", "authenticated-cache-and-restart-checks-complete",
})


def failed_web_call(value, call, status):
    record = failed_call_record(value, call, status)
    record["currentnessReason"] = "unclassified"
    if not isinstance(value, dict) or value.get("schemaVersion") != "latent.cli.result.v1":
        return record
    command = value.get("command")
    if isinstance(command, str) and command in WEB_COMMANDS:
        record["command"] = command
    error = value.get("error")
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, list) or len(details) > 16:
        return record
    observed = []
    for detail in details:
        if not isinstance(detail, dict) or set(detail) != {"kind", "fields"}:
            continue
        fields = detail.get("fields")
        if detail.get("kind") != "admission.currentness" or not isinstance(fields, dict) or set(fields) != {"reason"}:
            continue
        reason = fields["reason"]
        if isinstance(reason, str) and reason in CURRENTNESS_REASONS:
            observed.append(reason)
    if len(observed) == 1:
        record["currentnessReason"] = observed[0]
    return record


def failure_observation(client, identity, completed_shutdown, node):
    """Inspect only original owners AFTER cleanup; missing proof stays absent.

    Group retirement is distinct from an actual clean node stopped record.
    Neither implies any durable mutation disposition, replay or qualification.
    No process buffers, argv, environment, endpoint or opaque IDs are copied.
    """
    clean = None
    retired = None
    if node is not None:
        retired = node.closed is True and node.owner.finished is True
        try:
            clean = stopped_record(node)
        except Exception:
            pass
    digests = {key: value for key, value in identity.items()
               if key in {"cliDigest", "nodeDigest", "compilerDigest"}
               and isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)}
    stage = getattr(client, "workflow_stage", "acquire")
    phase = getattr(client, "preparation_phase", None)
    return {
        "schemaVersion": "latent.angular.t1.workflow.v1", "passed": False,
        "lastCompletedStage": stage if stage in STAGES else "unclassified",
        "preparationPhase": phase if phase in {"cold", "restart"} else None,
        "failedCall": client.failed_call,
        "identity": digests, "identityRechecked": False,
        "cliProcesses": client.calls if type(client.calls) is int and 0 <= client.calls <= 256 else None,
        "originalCompletedShutdowns": completed_shutdown,
        "failedNodeGroupRetired": retired, "failedNodeCleanShutdown": clean,
        "temporaryOutputsRemoved": "unverified",
    }
