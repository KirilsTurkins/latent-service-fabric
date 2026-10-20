"""Closed host HTTP refusal witnesses; never execution or retirement proof."""
from __future__ import annotations

import io
import re

from tools.phase2_operator_process import write_json

ENVIRONMENT = "LSF_JAVA_HTTP_REFUSAL_DIAGNOSTIC"
PREFIX = b"LSF-JAVA-HTTP-REFUSAL-V1"
STAGES = frozenset({"typed-http-conversion", "pool-active-dial"})
CATEGORIES = frozenset({"resource-exhausted", "admission-rejected"})
REASONS = frozenset({"busy", "capacity", "unclassified"})
MAX_RECORDS = 16
MAX_STDERR = 262144


def observe(stderr):
    """Read only bounded owned-node stderr, without projecting raw messages."""
    if type(stderr) is not bytes or len(stderr) > MAX_STDERR:
        return {"formatVersion": 1, "qualification": False, "status": "invalid-source", "records": []}
    records = []
    invalid = 0
    for line in io.BytesIO(stderr):
        line = line.rstrip(b"\r\n")
        if not line.startswith(PREFIX):
            continue
        match = re.fullmatch(rb"LSF-JAVA-HTTP-REFUSAL-V1 ([a-z-]{1,32}) ([a-z-]{1,32}) ([a-z-]{1,32})", line)
        if match is None:
            invalid += 1
            continue
        stage, category, reason = (atom.decode("ascii") for atom in match.groups())
        if stage not in STAGES or category not in CATEGORIES or reason not in REASONS:
            invalid += 1
            continue
        if len(records) == MAX_RECORDS:
            invalid += 1
            continue
        records.append({"stage": stage, "category": category, "reason": reason})
    return {"formatVersion": 1, "qualification": False, "status": "observed" if records else "not-observed",
            "records": records, "invalidMarkerCount": invalid,
            "atCaptureLimit": len(records) == MAX_RECORDS,
            "scope": "host-http-refusals-only-no-execution-or-retirement-proof"}


def retain(node, evidence):
    """Retain a closed projection after cleanup; never replace its outcome."""
    try:
        result = observe(bytes(node.buffers[1]))
        write_json(evidence / "http-refusals.json", result)
        return result
    except Exception:
        return {"formatVersion": 1, "qualification": False, "status": "retention-unavailable", "records": []}
