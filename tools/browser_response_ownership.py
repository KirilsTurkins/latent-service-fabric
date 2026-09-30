"""Bounded discovery of the shipped response policy, never runtime authority."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'contracts/http/browser-response-ownership-v1.json'
BEGIN = '<!-- response-ownership-v1:begin -->'
END = '<!-- response-ownership-v1:end -->'
FORBIDDEN = {'HostSecurity', 'HostTransport', 'ForbiddenHopByHop', 'ForbiddenIdentity',
             'ForbiddenPlatform', 'ForbiddenBrowserPolicy'}


def table():
    raw = CONTRACT.read_bytes()
    if len(raw) > 32768:
        raise ValueError('response-ownership-contract-bound')
    value = json.loads(raw)
    if value['schemaVersion'] != 'latent.browser.response-ownership.v1' or len(value['rows']) != 10:
        raise ValueError('response-ownership-contract-profile')
    return value


def ownership(name, contract=None):
    if not isinstance(name, str) or not 0 < len(name) <= 64 or not name.isascii():
        raise ValueError('response-header-name-grammar')
    name = name.lower()
    for row in (contract or table())['rows']:
        if name in row['names'] or any(name.startswith(prefix) for prefix in row['prefixes']):
            return row['id']
    return 'GuestAllowed'


def inspect_declared_header_names(names, *, dynamic=False):
    """Catch static conflicts only; values/body/current computed output need validation.

    No header name/value is reflected in the result. A dynamic declaration never
    becomes a claim of a valid response just because its listed fields are safe.
    """
    if not isinstance(names, list) or len(names) > 64 or type(dynamic) is not bool:
        raise ValueError('response-header-inspection-bound')
    contract, conflicts, singletons = table(), [], set()
    for index, name in enumerate(names):
        try:
            category = ownership(name, contract)
        except ValueError:
            conflicts.append({'index': index, 'reason': 'header-grammar'})
            continue
        if category in FORBIDDEN:
            conflicts.append({'index': index, 'reason': 'reserved-header'})
        elif name != name.lower() or any(not (c.isalnum() or c in "!#$%&'*+-.^_`|~") for c in name):
            conflicts.append({'index': index, 'reason': 'header-grammar'})
        elif name in ('location', 'content-encoding'):
            if name in singletons:
                conflicts.append({'index': index, 'reason': 'duplicate-singleton'})
            singletons.add(name)
    return {'schemaVersion': 'latent.browser.response-header-inspection.v1',
            'ownershipProfile': contract['schemaVersion'], 'conflicts': conflicts,
            'dynamicOutputRequiresExecution': dynamic, 'valuesAndBodyRequireValidation': True,
            'responseQualified': False}


def documentation(contract=None):
    contract = contract or table()
    lines = [BEGIN, '| Class | Names and prefixes | Behavior |', '| --- | --- | --- |']
    for row in contract['rows']:
        names = [*row['names'], *(prefix + '*' for prefix in row['prefixes'])]
        fields = ', '.join('`' + name + '`' for name in names) or 'Other valid names'
        lines.append('| ' + row['label'] + ' | ' + fields + ' | ' + row['behavior'] + ' |')
    return '\n'.join([*lines, END])


def java_vectors():
    contract, result = table(), []
    for row in contract['rows']:
        for name in [*row['names'], *(prefix + 'fixture' for prefix in row['prefixes'])]:
            result.extend([name + '\t' + row['id'], name.upper() + '\t' + row['id']])
    result.extend(['x-app-example\tGuestAllowed', 'etag\tGuestAllowed'])
    result.extend('limit:' + name + '\t' + str(value) for name, value in contract['limits'].items())
    return '\n'.join(result) + '\n'
