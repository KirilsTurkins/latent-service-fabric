"""Reuse exact-symbol, allocation-origin and simultaneous-live replay."""
from tools.optimization_backend_revision.ownership import allocations as origin
from .model import MAX_PROFILE_RECORDS, SYMBOLS


def proofs(value, binary, tool, artifacts):
    return origin.proofs(value, binary, tool, artifacts, symbols=SYMBOLS)


def attribute(record, binary, proof, tool, artifacts, whole):
    return origin.attribute(record, binary, proof, tool, artifacts, whole, symbols=SYMBOLS,
                            maximum_records=MAX_PROFILE_RECORDS,
                            scope="allocations-with-verified-measured-decode-or-encode-batch-frame-union")
