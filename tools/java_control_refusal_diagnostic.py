"""Private host stderr projection for the existing Java qualification owners."""
from __future__ import annotations

import io
import re

from tools.phase2_operator_process import write_json

ENVIRONMENT = "LSF_JAVA_CONTROL_REFUSAL_DIAGNOSTIC"
PREFIX = b"LSF-JAVA-CONTROL-REFUSAL-V1"
STAGES = frozenset({"trigger-request", "trigger-preparation", "trigger-audit-begin", "trigger-commit",
                    "audit-query-reservation", "audit-query-completion"})
REASONS = frozenset({"exclusive-rollout-work", "http-budget", "http-table", "audit-critical-pending",
                     "audit-capacity", "audit-busy", "unclassified"})
MAX_RECORDS = 16
MAX_STDERR = 262144


def observe(stderr):
    """No guest output, CLI response, message, argument or path is a source."""
    if type(stderr) is not bytes or len(stderr) > MAX_STDERR:
        return {"formatVersion": 1, "qualification": False, "status": "invalid-source", "records": []}
    records = []
    invalid = 0
    for line in io.BytesIO(stderr):
        line = line.rstrip(b"\r\n")
        if not line.startswith(PREFIX):
            continue
        match = re.fullmatch(rb"LSF-JAVA-CONTROL-REFUSAL-V1 ([a-z-]{1,32}) ([a-z-]{1,32})", line)
        if match is None:
            invalid += 1
            continue
        stage, reason = (atom.decode("ascii") for atom in match.groups())
        if stage not in STAGES or reason not in REASONS:
            invalid += 1
            continue
        if len(records) == MAX_RECORDS:
            invalid += 1
            continue
        records.append({"stage": stage, "reason": reason})
    return {"formatVersion": 1, "qualification": False, "status": "observed" if records else "not-observed",
            "records": records, "invalidMarkerCount": invalid,
            "atCaptureLimit": len(records) == MAX_RECORDS,
            "scope": "host-management-refusals-only-no-execution-or-retirement-proof"}


def retain(node, evidence):
    """The existing owned node's stderr is the sole source, after its cleanup."""
    try:
        result = observe(bytes(node.buffers[1]))
        write_json(evidence / "management-refusals.json", result)
        return result
    except Exception:
        # Diagnostic retention cannot replace an original refusal or cleanup.
        return {"formatVersion": 1, "qualification": False, "status": "retention-unavailable", "records": []}
