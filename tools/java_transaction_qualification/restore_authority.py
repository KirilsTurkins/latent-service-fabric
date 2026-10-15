"""Freeze once-read current policy generations for a stopped restore adoption."""
from __future__ import annotations

from pathlib import Path
import re

from tools.phase2_operator_process import write_json
from tools.rust_capsule_project import read_file

from .inputs import decode, digest, require
from . import configuration as cfg


def generation(value):
    require(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value)
            and int(value) < 2**64, 'actual-current-policy-generation')
    return value


def prepare(client, proposals: dict, directory: Path) -> list[dict]:
    require(directory.is_absolute() and directory.is_dir() and not directory.is_symlink(),
            'owned-restore-authority-directory')
    rows = []
    for family, kind in (('bindings', 'provider-binding'), ('policies', 'policy')):
        for name, document in proposals[family].items():
            require(isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name)
                    and len(rows) < 16, 'bounded-restore-authority-program')
            observed = client.call('policy', '--kind', kind, 'get', '--id', name)
            require(observed['outcomeKnown'] is True and observed['category'] == 'success',
                    'known-current-policy-observation')
            original = observed['data']['policy']
            require(isinstance(original, dict) and original['id'] == name
                    and original['tenant'] == cfg.TENANT
                    and original['revoked'] is False
                    and original['recordKind'] == kind,
                    'exact-current-policy-record')
            expected = generation(original['generation'])
            path = directory / f'{kind}-{name}.json'
            require(not path.exists(), 'fresh-restore-authority-input')
            write_json(path, document)
            path.chmod(0o600)
            raw = read_file(path, 262144)
            rows.append({'kind': kind, 'id': name, 'file': path.name,
                         'operationId': f'java-restore-{kind}-{name}',
                         'expectedGeneration': expected, 'original': original,
                         'digest': digest(raw), 'bytes': len(raw)})
    require(rows, 'nonempty-restore-authority-program')
    return rows


def apply(client, proposals: dict, directory: Path, rows: list[dict]) -> dict:
    expected = [(kind, name, document) for family, kind in (('bindings', 'provider-binding'), ('policies', 'policy'))
                for name, document in proposals[family].items()]
    require(isinstance(rows, list) and len(rows) == len(expected) and 0 < len(rows) <= 16,
            'retained-restore-authority-program-count')
    for row, (kind, name, document) in zip(rows, expected):
        require(isinstance(row, dict)
                and set(row) == {'kind', 'id', 'file', 'operationId', 'expectedGeneration', 'original', 'digest', 'bytes'}
                and row['kind'] == kind and row['id'] == name
                and row['file'] == f'{kind}-{name}.json'
                and row['operationId'] == f'java-restore-{kind}-{name}'
                and isinstance(row['original'], dict) and row['original']['id'] == name
                and row['original']['tenant'] == cfg.TENANT
                and row['original']['recordKind'] == kind and row['original']['revoked'] is False
                and row['expectedGeneration'] == generation(row['original']['generation'])
                and type(row['bytes']) is int and 0 < row['bytes'] <= 262144,
                'closed-retained-restore-authority-input')
        raw = read_file(directory / row['file'], 262144)
        require(len(raw) == row['bytes'] and digest(raw) == row['digest'] and decode(raw) == document,
                'restore-authority-input-byte-drift')
    receipts = {}
    for row in rows:
        result = client.call('policy', '--kind', row['kind'], 'apply', '--id', row['id'],
                             '--file', directory / row['file'], '--operation-id', row['operationId'],
                             '--expected-generation', row['expectedGeneration'])
        require(result['outcomeKnown'] is True and result['category'] == 'success'
                and result['data']['receipt']['operationId'] == row['operationId'],
                'actual-restore-authority-mutation-receipt')
        receipt = result['data']['receipt']
        require(int(generation(receipt['generation'])) > int(row['expectedGeneration'])
                and receipt['id'] == row['id'] and receipt['recordKind'] == row['kind']
                and receipt['tenant'] == cfg.TENANT
                and receipt['revoked'] is False,
                'actual-restore-authority-generation-advance')
        receipts[row['id']] = receipt
    return receipts
