"""Closed host-derived read-guard witness for the ordinary Go cancellation case.

This validates an execution observation, not a provider/kernel retirement proof.
The source-bound native harness must isolate the original connection itself.
"""
from __future__ import annotations

import json
import re

MAXIMUM_OUTPUT_BYTES = 1024 * 1024
MAXIMUM_BARRIER_BYTES = 1024
EXPECTED = {
    'case': 'cancel-pending-read',
    'owners': 1,
    'connections': 1,
    'readAdmissions': 2,
    'readReleases': 1,
    'pendingReads': 1,
    'releasedReadBytes': 1,
    'deliveredReadBytes': 1,
    'pendingOperations': 1,
    'ioCalls': 1,
}


def read_barrier(raw: bytes) -> dict:
    """Require one exact typed witness; old bytes/pending tuples are insufficient."""
    if not isinstance(raw, bytes) or len(raw) > MAXIMUM_OUTPUT_BYTES:
        raise ValueError('Go-network-read-barrier-output-bound')
    rows = re.findall(rb'^GO_NETWORK_READ_BARRIER(?: (.*))?$', raw, re.M)
    if len(rows) != 1:
        raise ValueError('Go-network-read-barrier-single-observation-required')

    if len(rows[0]) > MAXIMUM_BARRIER_BYTES:
        raise ValueError('Go-network-read-barrier-record-bound')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Go-network-read-barrier-duplicate-field')
            result[key] = value
        return result

    try:
        row = json.loads(rows[0], object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise ValueError('Go-network-read-barrier-invalid-json') from None
    if not isinstance(row, dict) or row.keys() != EXPECTED.keys():
        raise ValueError('Go-network-read-barrier-closed-fields-required')
    if any(type(row[key]) is not type(value) or row[key] != value
           for key, value in EXPECTED.items()):
        raise ValueError('Go-network-read-barrier-original-second-read-required')
    return row
