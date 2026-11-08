"""Closed observations from the signed ordinary-Go TCP harness.

This decoder has no compiler or runtime dependencies. It validates observations,
not kernel retirement, production availability, or the provenance of input logs.
The qualification controller owns actual execution and source binding.
"""
from __future__ import annotations

import json
import re

SCHEMA_VERSION = 'latent.go.network.runtime.v2'
CASE = 'signed_ordinary_go_declared_tcp_preserves_refusals_io_and_cancelled_owner_retirement'
EXPECTED = (
    ('unsupported-network', 0, 'unsupported-network', 0),
    ('standalone-dns', 1, 'unsupported-standalone-dns', 0),
    ('pre-cancelled', 2, 'cancelled-before-connect', 0),
    ('expired', 3, 'expired-before-connect', 0),
    ('resolver-replaced', 5, 'unsupported-custom-default-resolver', 0),
    ('resolver-prefer-go', 6, 'unsupported-custom-default-resolver', 0),
    ('resolver-strict', 7, 'unsupported-custom-default-resolver', 0),
    ('resolver-dial', 8, 'unsupported-custom-default-resolver', 0),
    ('ordinary-tcp', 4, 'ordinary-tcp-exchange', 1),
    ('half-close-eof', 9, 'ordinary-half-close-eof', 1),
    ('fragmented-read', 4, 'ordinary-tcp-exchange', 1),
    ('cancel-pending-read', 4, 'cancelled', 1),
    ('fresh-after-cancel', 4, 'ordinary-tcp-exchange', 1),
)
MAXIMUM_OUTPUT_BYTES = 1024 * 1024
MAXIMUM_RECORD_BYTES = 4096


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Go-network-runtime-duplicate-observation-field')
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise ValueError('Go-network-runtime-nonfinite-observation')


def _same(actual: object, expected: dict) -> bool:
    # The protocol is flat and closed. In particular, True != 1 and 0.0 != 0.
    return (type(actual) is dict and actual.keys() == expected.keys()
            and all(type(actual[key]) is type(value) and actual[key] == value
                    for key, value in expected.items()))


def _edge(label: str) -> dict:
    return {'case': label, 'constructedReads': 2, 'retiredReadDeliveredBytes': 1,
            'deliveredReadBytes': 1, 'pendingReads': 1, 'pendingOperations': 1,
            'ioCalls': 1, 'streamOwners': 1, 'connections': 1, 'retiredGenerations': 0,
            'quarantinedConnections': 0, 'providerStopped': False,
            'currentGenerationRetired': False, 'liveStores': 1, 'activeActivations': 1}


def outcomes(raw: bytes, filtered: int = 0) -> dict:
    """Require every ordered owner, case and read edge from one successful run."""
    if not isinstance(raw, bytes) or len(raw) > MAXIMUM_OUTPUT_BYTES:
        raise ValueError('Go-network-runtime-output-bound')
    if type(filtered) is not int or filtered < 0:
        raise ValueError('Go-network-runtime-invalid-filtered-count')
    # Inspect every test-prefixed line, including malformed names and leading
    # whitespace. A regex matching only valid identifiers would silently drop
    # an unexpected failed or ignored case from an otherwise valid transcript.
    candidates = []
    for line in raw.split(b'\n'):
        stripped = line.lstrip(b' \t')
        if stripped == b'test' or stripped.startswith((b'test ', b'test\t')):
            candidates.append(line)
    summary = re.compile(rb'test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; '
                         + str(filtered).encode() + rb' filtered out; finished in [0-9]+(?:\.[0-9]+)?s')
    if (len(candidates) != 2 or candidates[0] != b'test ' + CASE.encode() + b' ... ok'
            or summary.fullmatch(candidates[1]) is None):
        raise ValueError('Go-network-runtime-exact-native-case-required')

    # Inspect every reserved-prefix line, not just well-formed regex matches.
    # Otherwise an extra empty/tab-separated/unknown record disappears before
    # the ordering check and a corrupt transcript can masquerade as complete.
    events = []
    for line in raw.split(b'\n'):
        if not line.lstrip().startswith(b'GO_NETWORK_'):
            continue
        if len(line) > MAXIMUM_RECORD_BYTES:
            raise ValueError('Go-network-runtime-record-bound')
        name, separator, payload = line.partition(b' ')
        if (separator != b' ' or name not in {
                b'GO_NETWORK_OWNER', b'GO_NETWORK_CASE', b'GO_NETWORK_READ_EDGE',
                b'GO_NETWORK_COMPLETE'} or not payload):
            raise ValueError('Go-network-runtime-malformed-observation')
        try:
            row = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_constant)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise ValueError('Go-network-runtime-malformed-observation') from None
        events.append((name, row))
        # Two records per case, two read edges, one completion. Reject before
        # retaining arbitrary numbers of otherwise syntactically valid records.
        if len(events) > 2 * len(EXPECTED) + 3:
            raise ValueError('Go-network-runtime-exact-event-order-required')

    expected = []
    for label, mode, result, contacts in EXPECTED:
        if label in ('fragmented-read', 'cancel-pending-read'):
            expected.append((b'GO_NETWORK_READ_EDGE', _edge(label)))
        expected.append((b'GO_NETWORK_OWNER', {
            'case': label, 'stores': 0, 'instances': 0, 'streamOwners': 0,
            'ioOwners': 0, 'kernelRetirementQualified': False}))
        expected.append((b'GO_NETWORK_CASE', {
            'case': label, 'mode': mode, 'result': result, 'contacts': contacts}))
    expected.append((b'GO_NETWORK_COMPLETE', {
        'cases': 13, 'contacts': 5, 'cleanLogicalProviderStop': True,
        'kernelRetirementQualified': False, 'normalProviderInstalled': False}))
    if [name for name, _ in events] != [name for name, _ in expected]:
        raise ValueError('Go-network-runtime-exact-event-order-required')
    reasons = {
        b'GO_NETWORK_CASE': 'Go-network-runtime-exact-ordinary-observations-required',
        b'GO_NETWORK_OWNER': 'Go-network-runtime-exact-user-owner-retirement-required',
        b'GO_NETWORK_READ_EDGE': 'Go-network-runtime-constructed-read-owner-required',
        b'GO_NETWORK_COMPLETE': 'Go-network-runtime-completion-or-kernel-claim',
    }
    for (name, row), (_, wanted) in zip(events, expected):
        if not _same(row, wanted):
            raise ValueError(reasons[name])
    return {
        'cases': [row for name, row in events if name == b'GO_NETWORK_CASE'],
        'readEdges': [row for name, row in events if name == b'GO_NETWORK_READ_EDGE'],
        'userSpaceOwners': [row for name, row in events if name == b'GO_NETWORK_OWNER'],
        'completion': events[-1][1],
    }
