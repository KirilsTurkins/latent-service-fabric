"""Authenticated captured objects use their own finite, non-executable domain."""
from __future__ import annotations

import io
import os
from pathlib import Path
import tarfile

from tools import application_dependencies as capture
from tools.application_dependency_store import MAX_OBJECT, SHA, Store

from . import dependencies, paths
from .common import digest, encode, members, require, sha

PROFILE = 'latent.dev.captured-inputs.v1'
DOMAIN = 'dependency-capture-v1'
MAX_REFERENCES = capture.MAX_LOCK // 71  # Every reference contains a SHA256 identity.
METADATA = 'release/capture.json'
ARCHIVE = 'release/objects.tar'


def references(lock: dict) -> list[dict]:
    found = {}
    def add(row):
        require(isinstance(row, dict) and isinstance(row.get('digest'), str)
                and SHA.fullmatch(row['digest']) and type(row.get('size')) is int
                and 0 <= row['size'] <= MAX_OBJECT, 'captured-input-object-reference')
        require(row['digest'] not in found or found[row['digest']] == row['size'], 'captured-input-object-size-drift')
        found[row['digest']] = row['size']
        require(len(found) <= MAX_REFERENCES, 'captured-input-reference-limit')
    for row in lock['nativeLocks']:
        add(row)
    for item in lock['artifacts']:
        add(item['original'])
        for row in item['files']:
            add(row)
    for transformation in lock['transformations']:
        for row in transformation['changes']:
            add(row['original'])
            add(row['transformed'])
    return [{'digest': identity, 'size': size} for identity, size in sorted(found.items())]


def validate(value: dict) -> dict:
    members(value, {'schemaVersion', 'manifestDigest', 'lockDigest', 'objectsIdentity',
                    'objectCount', 'objectBytes', 'closureFiles', 'closureBytes', 'identity'})
    require(value['schemaVersion'] == PROFILE, 'captured-input-profile')
    for field in ('manifestDigest', 'lockDigest', 'objectsIdentity', 'identity'):
        sha(value[field])
    for field, maximum in (('objectCount', MAX_REFERENCES), ('objectBytes', capture.MAX_CLOSURE_BYTES),
                           ('closureFiles', capture.MAX_CLOSURE_FILES), ('closureBytes', capture.MAX_CLOSURE_BYTES)):
        require(type(value[field]) is int and 0 <= value[field] <= maximum, 'captured-input-domain-limit')
    require(value['objectCount'] > 0 and digest(encode({key: item for key, item in value.items() if key != 'identity'}))
            == value['identity'], 'captured-input-identity')
    return value


def observe(root: Path) -> tuple[dict, list[dict]]:
    manifest = dependencies.capture_document(paths.read(root, capture.MANIFEST, capture.MAX_LOCK))
    verified = capture.verify_inputs(root, manifest['language'])
    require(verified is not None, 'captured-inputs-required')
    rows = references(verified.lock)
    value = {'schemaVersion': PROFILE, 'manifestDigest': digest(verified.manifest_bytes),
             'lockDigest': digest(verified.lock_bytes), 'objectsIdentity': digest(encode(rows)),
             'objectCount': len(rows), 'objectBytes': sum(row['size'] for row in rows),
             'closureFiles': sum(len(item['files']) for item in verified.lock['artifacts']),
             'closureBytes': sum(row['size'] for item in verified.lock['artifacts'] for row in item['files'])}
    value['identity'] = digest(encode(value))
    return validate(value), rows


def object_path(identity: str) -> str:
    value = sha(identity)[7:]
    return dependencies.OBJECTS + '/' + value[:2] + '/' + value[2:]


def pack(root: Path, expected: dict, destination: Path) -> dict[str, Path]:
    observed, rows = observe(root)
    require(observed == expected, 'captured-inputs-changed-before-transfer')
    paths.new_directory(destination)
    paths.new_directory(destination / 'release')
    metadata = encode({'schemaVersion': PROFILE, 'capture': expected, 'objects': rows})
    require(len(metadata) <= capture.MAX_LOCK, 'captured-input-metadata-limit')
    paths.write_new(destination / METADATA, metadata)
    store = Store(root / dependencies.OBJECTS, create=False)
    with (destination / ARCHIVE).open('xb') as output, tarfile.open(fileobj=output, mode='w') as archive:
        for row in rows:
            raw = store.get(row['digest'], row['size'])
            entry = tarfile.TarInfo('objects/' + row['digest'][7:])
            entry.mode, entry.size = 0o600, len(raw)
            archive.addfile(entry, io.BytesIO(raw))
    require(observe(root)[0] == expected, 'captured-inputs-changed-during-transfer')
    return {METADATA: destination / METADATA, ARCHIVE: destination / ARCHIVE}


def restore(root: Path, expected: dict, directory: Path) -> None:
    validate(expected)
    require(digest(paths.read(root, capture.MANIFEST, capture.MAX_LOCK)) == expected['manifestDigest']
            and digest(paths.read(root, capture.LOCK, capture.MAX_LOCK)) == expected['lockDigest'],
            'captured-input-document-drift')
    value = dependencies.capture_document(paths.read(directory, METADATA, capture.MAX_LOCK))
    members(value, {'schemaVersion', 'capture', 'objects'})
    require(value['schemaVersion'] == PROFILE and value['capture'] == expected and isinstance(value['objects'], list)
            and len(value['objects']) == expected['objectCount'], 'captured-input-metadata-drift')
    lock = dependencies.capture_document(paths.read(root, capture.LOCK, capture.MAX_LOCK))
    rows = references(lock)
    require(value['objects'] == rows and digest(encode(rows)) == expected['objectsIdentity'],
            'captured-input-object-inventory')
    require(len(rows) == expected['objectCount'] and sum(row['size'] for row in rows) == expected['objectBytes'],
            'captured-input-object-accounting')
    remaining = {row['digest'][7:]: row for row in rows}
    store = Store(root / dependencies.OBJECTS)
    maximum_archive = capture.MAX_CLOSURE_BYTES + len(rows) * 1024 + 10240
    with paths.opened(directory, ARCHIVE) as descriptor:
        require(os.fstat(descriptor).st_size <= maximum_archive, 'captured-input-archive-byte-limit')
        with io.FileIO(descriptor, 'rb', closefd=False) as stream, tarfile.open(fileobj=stream, mode='r:') as archive:
            for item in archive:
                require(item.isfile() and not item.pax_headers and item.name.startswith('objects/'),
                        'captured-input-unsafe-archive')
                key = item.name[len('objects/'):]
                require(key in remaining and item.size == remaining[key]['size'], 'captured-input-object-inventory')
                row = remaining.pop(key)
                raw = archive.extractfile(item).read(row['size'] + 1)
                require(len(raw) == row['size'] and digest(raw) == row['digest'], 'captured-input-object-content')
                require(store.put(raw) == {'digest': row['digest'], 'size': row['size']}, 'captured-input-object-content')
    require(not remaining and observe(root)[0] == expected, 'captured-input-restore-incomplete')


def copy(source: Path, destination: Path, expected: dict) -> None:
    observed, rows = observe(source)
    require(observed == expected, 'captured-inputs-changed-before-copy')
    original, target = Store(source / dependencies.OBJECTS, create=False), Store(destination / dependencies.OBJECTS)
    for row in rows:
        require(target.put(original.get(row['digest'], row['size'])) == row, 'captured-input-copy-mismatch')
    require(observe(source)[0] == expected and observe(destination)[0] == expected, 'captured-inputs-changed-during-copy')
