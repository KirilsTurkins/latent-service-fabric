"""Shared public HTTP value vectors; only real guest/provider observations qualify."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re

from .protocol import METHODS, require
from .vectors import json_bytes

SOURCE = Path(__file__).with_name('values.json')
PROFILE = 'latent.standard-http.values.v1'
GO_MODE_BASE = 25


def load() -> list[dict]:
    raw = SOURCE.read_bytes()
    require(len(raw) <= 8192, 'http-value-source-limit')
    value = json.loads(raw)
    require(isinstance(value, dict) and set(value) == {'schemaVersion', 'cases'}
            and value['schemaVersion'] == PROFILE, 'http-value-source-profile')
    cases = value['cases']
    require(isinstance(cases, list) and 1 <= len(cases) <= 9, 'http-value-case-limit')
    identities = set()
    for case in cases:
        require(isinstance(case, dict) and set(case) == {
            'id', 'method', 'bodyBase64', 'length', 'mediaType', 'header'}, 'http-value-case-shape')
        identity = case['id']
        require(isinstance(identity, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,31}', identity)
                and identity not in identities, 'http-value-case-identity')
        identities.add(identity)
        require(isinstance(case['method'], str) and case['method'].encode('utf-8') in METHODS,
                'http-value-method')
        require(case['length'] in {'known', 'unknown'}, 'http-value-length')
        require(isinstance(case['bodyBase64'], str) and len(case['bodyBase64']) <= 128,
                'http-value-body-limit')
        body = base64.b64decode(case['bodyBase64'], validate=True)
        require(len(body) <= 64 and base64.b64encode(body).decode('ascii') == case['bodyBase64'],
                'http-value-body-encoding')
        for key in ('mediaType', 'header'):
            require(case[key] is None or (isinstance(case[key], str)
                    and len(case[key].encode('utf-8')) <= 64), 'http-value-metadata-limit')
    return cases


def echo(case: dict) -> dict:
    header = case['header']
    return {'method': case['method'], 'bodyBase64': case['bodyBase64'],
        'contentLengthPresent': case['length'] == 'known',
        'contentTypePresent': case['mediaType'] is not None,
        'customHeaderBase64': base64.b64encode(header.encode('utf-8')).decode('ascii')
            if header is not None else None}


def unique_fields(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, 'http-value-result-duplicate-field')
        result[key] = value
    return result


def require_result(case: dict, returned: str) -> None:
    require(isinstance(returned, str) and len(returned.encode('utf-8')) <= 4096, 'http-value-result-limit')
    expected = echo(case)
    if case['method'] == 'HEAD':
        require(returned == 'values-head:200:' + str(len(json_bytes(expected))) + ':0', 'http-value-head')
        return
    require(returned.startswith('values:'), 'http-value-result-prefix')
    result = json.loads(returned.removeprefix('values:'), object_pairs_hook=unique_fields)
    require(isinstance(result, dict) and set(result) == set(expected)
            and all(type(result[key]) is type(value) and result[key] == value
                    for key, value in expected.items()), 'http-value-result')


def require_peer(cases: list[dict], rows: list[dict]) -> None:
    """Pair the guest result with actual ordered requests, not its own success marker."""
    require(len(rows) == len(cases), 'http-value-peer-count')
    for case, row in zip(cases, rows, strict=True):
        body = base64.b64decode(case['bodyBase64'], validate=True)
        require(row.get('role') == 'primary' and row.get('vector') == 'method-bytes'
                and row.get('method') == case['method'] and row.get('state') == 'closed'
                and row.get('bodyBytes') == len(body)
                and row.get('bodySha256') == 'sha256:' + hashlib.sha256(body).hexdigest()
                and row.get('requestFraming') == ('length' if case['length'] == 'known' else 'chunked'),
                'http-value-peer-request')
