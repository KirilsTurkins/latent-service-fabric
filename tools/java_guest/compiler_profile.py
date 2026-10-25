"""One source-pinned normal compiler cohort; never caller-supplied authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DATA = 'tools/data/java-compiler-profile.json'
SCHEMA = 'latent.java.normal-compiler-profile.v1'
PROFILE = 'lsf-private-scalar-v1'
RECIPE_SHA = 'eebc8920624c8a0b40b89648154bab16eaa5a3a9e54eb38ca4dfd18a3211366d'
CLANG_VERSION = '21.1.4-wasi-sdk-' + PROFILE
OFFICIAL = ('29.0', 'wasi-libc: ac020b86fd44', 'llvm: 222fc11f2b8f',
            'llvm-version: 21.1.4', 'config: f992bcc08219')
NOTICES = {'NOTICE', 'LLVM-LICENSE.txt', 'LLVM-PATCH.json',
           'LLVM-PRIVATE-STORES.json', 'official-origin-VERSION'}
FUTURE = {'producer', 'qualification', 'carrier', 'manifest', 'version',
          'inventories', 'buildInput', 'notices'}
MAXIMUM = 64 * 1024


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError('Java compiler profile ' + reason)


def identity(raw: bytes) -> dict:
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def encoded(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def read() -> bytes:
    from tools.rust_capsule_project import read_file
    return read_file(ROOT / DATA, MAXIMUM)


def digest_row(row, maximum: int) -> None:
    need(type(row) is dict and set(row) == {'bytes', 'sha256'}
         and type(row['bytes']) is int and 0 < row['bytes'] <= maximum
         and type(row['sha256']) is str
         and re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None, 'identity')


def sha(value, size: int) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is not None


def _source_pin(raw: bytes) -> dict | None:
    from tools.rust_capsule_project import decode_json
    value = decode_json(raw)
    need(type(value) is dict and set(value) == FUTURE | {
        'schemaVersion', 'profile', 'cohortRecipeSha256'}
         and value['schemaVersion'] == SCHEMA and value['profile'] == PROFILE
         and value['cohortRecipeSha256'] == RECIPE_SHA, 'schema')
    if all(value[name] is None for name in FUTURE):
        return None
    need(all(value[name] is not None for name in FUTURE), 'partial-promotion')
    producer = value['producer']
    need(type(producer) is dict and set(producer) == {'head', 'tree', 'run', 'job', 'artifact', 'archive'}
         and sha(producer['head'], 40) and sha(producer['tree'], 40)
         and all(type(producer[name]) is int and producer[name] > 0 for name in ('run', 'job', 'artifact')),
         'producer')
    digest_row(producer['archive'], 2 * 1024 ** 3)
    qualification = value['qualification']
    need(type(qualification) is dict and set(qualification) == {
        'producerReceipt', 'publicReceipt', 'publicComponent', 'publicHead', 'publicRun', 'publicJob', 'publicArtifact',
        'normalCommandShape'}
         and sha(qualification['publicHead'], 40)
         and all(type(qualification[name]) is int and qualification[name] > 0
                 for name in ('publicRun', 'publicJob')), 'qualification')
    for name, maximum in [('producerReceipt', 8 * 1024 ** 2), ('publicReceipt', 8 * 1024 ** 2),
                          ('publicComponent', 64 * 1024 ** 2), ('normalCommandShape', 64 * 1024)]:
        digest_row(qualification[name], maximum)
    public_artifact = qualification['publicArtifact']
    need(type(public_artifact) is dict and set(public_artifact) == {'id', 'archive', 'expiresAt'}
         and type(public_artifact['id']) is int and public_artifact['id'] > 0
         and type(public_artifact['expiresAt']) is str
         and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', public_artifact['expiresAt']),
         'public-artifact')
    digest_row(public_artifact['archive'], 64 * 1024 ** 2)
    for name, maximum in [('carrier', 2 * 1024 ** 3 - 64 * 1024 ** 2),
                          ('manifest', 16 * 1024 ** 2), ('version', 1024)]:
        digest_row(value[name], maximum)
    need(type(value['inventories']) is dict and set(value['inventories']) == {'linked', 'managed'}, 'inventories')
    for row in value['inventories'].values():
        digest_row(row, 16 * 1024 ** 2)
    need(type(value['notices']) is dict and set(value['notices']) == NOTICES, 'notices')
    for row in value['notices'].values():
        digest_row(row, 1024 * 1024)
    supplied = value['buildInput']
    need(type(supplied) is dict and set(supplied) == {'kind', 'artifactId', 'archive', 'expiresAt'}
         and supplied['kind'] == 'prepared-compiler-inputs'
         and type(supplied['artifactId']) is int and supplied['artifactId'] == producer['artifact']
         and supplied['archive'] == producer['archive']
         and type(supplied['expiresAt']) is str
         and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', supplied['expiresAt']),
         'prepared-input')
    need(identity(version_bytes(value)) == value['version'], 'version-identity')
    return value


def pin() -> dict | None:
    """Only a complete checked-in promotion changes the ordinary Java default."""
    return _source_pin(read())


def version_bytes(value: dict) -> bytes:
    return ('\n'.join((OFFICIAL[0] + '-' + PROFILE, *OFFICIAL[1:],
                      'lsf-llvm-patch-sha256: ' + value['notices']['LLVM-PRIVATE-STORES.json']['sha256']))
            + '\n').encode()


def admit(root: Path) -> tuple[str, bytes] | None:
    """Unknown or not-yet-promoted SDKs never acquire the new normal identity."""
    source = read()
    value = _source_pin(source)
    if value is None:
        return None
    from tools.rust_capsule_project import read_file
    if read_file(root / 'VERSION', 1024) != version_bytes(value):
        return None
    from tools.java_guest.compiler import tool_inventory
    inventory = identity(tool_inventory({'wasi-sdk': root}))
    matches = [name for name, row in value['inventories'].items() if row == inventory]
    need(len(matches) == 1, 'unreviewed-complete-sdk-inventory')
    need(read() == source, 'source-changed-during-admission')
    record = {'schemaVersion': SCHEMA, 'profile': PROFILE, 'compilerVersion': CLANG_VERSION,
              'representation': matches[0], 'compilerInventory': inventory,
              'sourceProfile': identity(source), 'producer': value['producer'],
              'qualification': value['qualification'], 'carrier': value['carrier'],
              'manifest': value['manifest'], 'version': value['version'], 'notices': value['notices'],
              'buildInput': value['buildInput'], 'runtimeQualification': False}
    return CLANG_VERSION, encoded(record)


def recheck(record: bytes) -> None:
    from tools.rust_capsule_project import decode_json
    value = decode_json(record)
    need(identity(read()) == value['sourceProfile'], 'source-changed-during-build')
