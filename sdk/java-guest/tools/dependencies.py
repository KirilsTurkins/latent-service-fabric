"""Inventory the actual compiler cache; never silently accept new dependencies.

Gradle performs strict SHA-256 verification of plugins, metadata and jars before
using them. This additional receipt maps downloaded jars onto the repository's
existing Maven/OSV inventory format. Bootstrap candidates are never installed in
the source tree or treated as a qualification result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NS = '{https://schema.gradle.org/dependency-verification}'
TOKEN = re.compile(r'[A-Za-z0-9_.-]+')
SHA256 = re.compile(r'[a-f0-9]{64}')


def file_identity(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError('dependency-symlink')
    size = path.stat().st_size
    if not 0 < size <= 64 * 1024 * 1024:
        raise ValueError('dependency-size-limit')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {'sha256': digest.hexdigest(), 'size': size}


def cache_inventory(cache: Path) -> dict:
    artifacts = {}
    for path in cache.glob('*/*/*/*/*.jar'):
        if len(artifacts) >= 512:
            raise ValueError('dependency-count-limit')
        group, name, version, cache_key, filename = path.relative_to(cache).parts
        if (not all(TOKEN.fullmatch(p) for p in (group, name, version, cache_key))
                or filename != f'{name}-{version}.jar'
                or not re.fullmatch(r'[0-9]+[A-Za-z0-9_.-]*', version)
                or 'SNAPSHOT' in version):
            raise ValueError('dependency-coordinate-invalid')
        coordinate = f'{group.replace(".", "/")}/{name}/{version}/{filename}'
        item = {'path': coordinate, **file_identity(path), 'platform': 'any'}
        if coordinate in artifacts and artifacts[coordinate] != item:
            raise ValueError('dependency-coordinate-conflict')
        artifacts[coordinate] = item
    if not artifacts:
        raise ValueError('dependency-cache-empty')
    return {'schemaVersion': 1, 'maven': 'https://repo.maven.apache.org/maven2/',
            'artifacts': [artifacts[key] for key in sorted(artifacts)]}


def verified_jars(metadata: Path) -> dict:
    payload = metadata.read_bytes()
    if not payload or len(payload) > 1024 * 1024 or b'<!DOCTYPE' in payload.upper():
        raise ValueError('verification-metadata-invalid')
    root = ET.fromstring(payload)
    if root.tag != NS + 'verification-metadata':
        raise ValueError('verification-metadata-schema')
    config = root.find(NS + 'configuration')
    if (config is None or config.findtext(NS + 'verify-metadata') != 'true'
            or config.findtext(NS + 'verify-signatures') != 'false'
            or any(e.tag not in {NS + 'verify-metadata', NS + 'verify-signatures'} for e in config)):
        raise ValueError('verification-metadata-not-strict')
    jars = {}
    for component in root.findall(f'{NS}components/{NS}component'):
        group, name, version = (component.get(key, '') for key in ('group', 'name', 'version'))
        if not all(TOKEN.fullmatch(value) for value in (group, name, version)):
            raise ValueError('verification-coordinate-invalid')
        for artifact in component.findall(NS + 'artifact'):
            filename = artifact.get('name', '')
            checksums = list(artifact)
            if (len(checksums) != 1 or checksums[0].tag != NS + 'sha256'
                    or list(checksums[0]) or not SHA256.fullmatch(checksums[0].get('value', ''))):
                raise ValueError('verification-artifact-not-exact')
            if not filename.endswith('.jar'):
                continue
            if filename != f'{name}-{version}.jar':
                raise ValueError('verification-jar-coordinate-invalid')
            coordinate = f'{group.replace(".", "/")}/{name}/{version}/{filename}'
            if coordinate in jars:
                raise ValueError('verification-jar-duplicate')
            jars[coordinate] = checksums[0].get('value')
    if not jars:
        raise ValueError('verification-jar-empty')
    return jars


def verify_inventory(observed: dict, lock: dict, metadata: Path) -> None:
    if set(lock) != {'schemaVersion', 'maven', 'artifacts'} or lock['schemaVersion'] != 1:
        raise ValueError('dependency-lock-schema')
    if lock['maven'] != 'https://repo.maven.apache.org/maven2/':
        raise ValueError('dependency-lock-registry')
    entries = lock['artifacts']
    if not isinstance(entries, list) or not 0 < len(entries) <= 512:
        raise ValueError('dependency-lock-count')
    expected = {}
    for entry in entries:
        if (set(entry) != {'path', 'sha256', 'size', 'platform'}
                or entry['platform'] != 'any' or type(entry['size']) is not int
                or not 0 < entry['size'] <= 64 * 1024 * 1024
                or not SHA256.fullmatch(entry['sha256']) or entry['path'] in expected):
            raise ValueError('dependency-lock-entry')
        expected[entry['path']] = entry
    # The advisory inventory must cover every executable jar Gradle trusts,
    # including configurations not needed by a particular compiler invocation.
    if {key: value['sha256'] for key, value in expected.items()} != verified_jars(metadata):
        raise ValueError('dependency-lock-metadata-drift')
    for entry in observed['artifacts']:
        if expected.get(entry['path']) != entry:
            raise ValueError('dependency-cache-lock-drift')


def retain(cache: Path, project: Path, output: Path, bootstrap: bool) -> dict:
    observed = cache_inventory(cache)
    metadata = project / 'gradle/verification-metadata.xml'
    if bootstrap:
        verify_inventory(observed, observed, metadata)
        (output / 'dependencies.candidate.json').write_text(json.dumps(observed, indent=2) + '\n')
        (output / 'verification-metadata.candidate.xml').write_bytes(metadata.read_bytes())
        return {'status': 'unreviewed-bootstrap-candidate', 'jars': len(observed['artifacts'])}
    lock = json.loads((project / 'dependencies.lock.json').read_text())
    verify_inventory(observed, lock, metadata)
    (output / 'dependencies.observed.json').write_text(json.dumps(observed, indent=2) + '\n')
    return {'status': 'checksummed-gradle-metadata', 'downloadedJars': len(observed['artifacts']),
            'reviewedJars': len(lock['artifacts']), 'lock': file_identity(project / 'dependencies.lock.json'),
            'metadata': file_identity(metadata)}
