"""Bounded owned-node stderr evidence; no execution or retirement qualification."""
from __future__ import annotations

import io
import re

from tools.phase2_operator_process import write_json

PREFIX = b"LSF-RUNTIME-OWNER-REFUSAL-V1"
BUCKETS = ("tasks", "executors", "queued-work", "waits", "timers", "results", "native")
MAX_RECORDS = 4
MAX_STDERR = 262144
MAX_RECORD_BYTES = 160
MAX_OWNERS = 8192
PATTERN = re.compile(PREFIX + b"".join(b" " + label.encode("ascii") + rb"=(0|[1-9][0-9]{0,3})"
                                       for label in BUCKETS))


def observe(stderr):
    if type(stderr) is not bytes or len(stderr) > MAX_STDERR:
        return {"formatVersion": 1, "qualification": False, "status": "invalid-source", "records": []}
    records, invalid = [], 0
    for line in io.BytesIO(stderr):
        line = line.rstrip(b"\r\n")
        if not line.startswith(PREFIX):
            continue
        match = PATTERN.fullmatch(line) if len(line) + 1 <= MAX_RECORD_BYTES else None
        if match is None:
            invalid += 1
            continue
        counts = tuple(int(value) for value in match.groups())
        if not any(counts) or max(counts) > MAX_OWNERS or sum(counts) > MAX_OWNERS or len(records) == MAX_RECORDS:
            invalid += 1
            continue
        records.append(dict(zip(BUCKETS, counts)))
    return {"formatVersion": 1, "qualification": False, "status": "observed" if records else "not-observed",
            "records": records, "invalidMarkerCount": invalid, "atCaptureLimit": len(records) == MAX_RECORDS,
            "tasksIncludesManagedIdleWorkers": True,
            "scope": "host-runtime-finalization-refusals-only-no-retirement-proof"}


def retain(node, evidence):
    """Only the original reaped node's stderr is a diagnostic input."""
    try:
        if node.owner.finished is not True:
            result = {"formatVersion": 1, "qualification": False, "status": "node-not-reaped", "records": []}
        else:
            result = observe(bytes(node.buffers[1]))
        write_json(evidence / "runtime-owner-refusals.json", result)
        return result
    except Exception:
        return {"formatVersion": 1, "qualification": False, "status": "retention-unavailable", "records": []}
