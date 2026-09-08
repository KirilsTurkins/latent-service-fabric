#!/usr/bin/env python3
"""Verify a bounded Phase 1 archive, safely extract it temporarily, and replay its evidence."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import tempfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from . import package_phase0_evidence as paths
    from . import phase0_evidence
    from .phase1_evidence.replay import validate_aggregate, validate_comparison
    from .phase1_evidence.common import canonical, read_json
    from .validate_phase1_paired import replay as validate_paired
    from .optimization_evidence.common import read_json as read_optimization_json
    from .optimization_evidence.suite import validate_suite as validate_optimization_suite
    from .artifact_identity_evidence import validate_suite as validate_artifact_identity_suite
    from .optimization_revision_evidence.suite import validate_suite as validate_revision_suite
    from .optimization_backend_revision.evidence import validate_suite as validate_backend_revision_suite
except ImportError:
    import package_phase0_evidence as paths
    import phase0_evidence
    from phase1_evidence.replay import validate_aggregate, validate_comparison
    from phase1_evidence.common import canonical, read_json
    from validate_phase1_paired import replay as validate_paired
    from tools.optimization_evidence.common import read_json as read_optimization_json
    from tools.optimization_evidence.suite import validate_suite as validate_optimization_suite
    from tools.artifact_identity_evidence import validate_suite as validate_artifact_identity_suite
    from tools.optimization_revision_evidence.suite import validate_suite as validate_revision_suite
    from tools.optimization_backend_revision.evidence import validate_suite as validate_backend_revision_suite

ARCHIVE = 'raw-evidence.tar.gz'
MANIFEST = 'raw-evidence.manifest.json'
MAX_COMPRESSED = 99_000_000
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_FILES = 5000
MAX_AGGREGATE_BYTES = 8 * 1024 * 1024
CHUNK = 64 * 1024


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def relative_path(value):
    require(isinstance(value, str) and len(value) <= 1024
            and re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', value)
            and all(part not in ('.', '..') for part in value.split('/')), 'invalid archive path')
    return value


def pairs(rows):
    value = {}
    for key, item in rows:
        require(key not in value, 'duplicate manifest field')
        value[key] = item
    return value


def size(value):
    require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,10}', value), 'invalid size')
    return int(value)


def file_reference(path, root, maximum=MAX_EXPANDED):
    paths.require_regular_file(path, 'evidence file')
    total = 0
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            total += len(chunk)
            require(total <= maximum, 'evidence file exceeds bound')
            digest.update(chunk)
    return {'path': relative_path(path.relative_to(root).as_posix()),
            'bytes': str(total), 'sha256': 'sha256:' + digest.hexdigest()}


def load_manifest(root):
    path = paths.existing_regular_file_path(root / MANIFEST, 'archive manifest')
    with path.open('rb') as stream:
        encoded = stream.read(4 * 1024 * 1024 + 1)
    require(len(encoded) <= 4 * 1024 * 1024, 'manifest exceeds bound')
    value = json.loads(encoded, object_pairs_hook=pairs)
    require(set(value) == {'schema', 'archive', 'files', 'total_bytes'}
            and value['schema'] == 'latent.phase1.archive-manifest.v1', 'invalid manifest schema')
    require(isinstance(value['files'], list) and 0 < len(value['files']) <= MAX_FILES,
            'invalid archive file count')
    observed = set()
    total = 0
    for row in [value['archive'], *value['files']]:
        require(isinstance(row, dict) and set(row) == {'path', 'bytes', 'sha256'}, 'invalid file reference')
        relative_path(row['path'])
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', row['sha256']), 'invalid file digest')
        require(size(row['bytes']) <= MAX_EXPANDED, 'file exceeds expanded bound')
    require(value['archive']['path'] == ARCHIVE, 'unexpected archive name')
    for row in value['files']:
        folded = row['path'].casefold()
        require(folded not in observed, 'duplicate archive path')
        observed.add(folded)
        total += size(row['bytes'])
    require(total == size(value['total_bytes']) and total <= MAX_EXPANDED, 'expanded byte bound')
    return value


def verify_policy(policy, aggregate):
    recorded = aggregate['policy']
    encoded = json.dumps(policy, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    require(policy == recorded['document'], 'archived policy differs from aggregate policy')
    require('sha256:' + hashlib.sha256(encoded).hexdigest() == recorded['sha256'],
            'archived policy digest differs from aggregate policy')


def evidence_kind(directory):
    path = paths.existing_regular_file_path(directory / 'aggregate.json', 'aggregate')
    # Full optimization aggregates exceed the legacy 200,000-node ceiling.
    # Inspect with that format's bounded parser, retaining the archive byte cap.
    aggregate = read_optimization_json(path, MAX_AGGREGATE_BYTES)
    require(isinstance(aggregate, dict), 'invalid aggregate object')
    if aggregate.get('schema') == 'latent.optimization.aggregate.v1':
        return 'optimization'
    if aggregate.get('schema') == 'latent.artifact-identity.aggregate.v1':
        return 'artifact-identity'
    if aggregate.get('schema') == 'latent.optimization.revision-aggregate.v1':
        return 'revision'
    if aggregate.get('schema') == 'latent.optimization.backend-revision-aggregate.v1':
        return 'backend-revision'
    del aggregate
    # Other formats still satisfy every original structural/string limit.
    aggregate = read_json(path, MAX_AGGREGATE_BYTES)
    require(isinstance(aggregate, dict), 'invalid aggregate object')
    schema = aggregate.get('schema')
    if schema == 'latent.phase1.paired-aggregate.v1':
        return 'paired'
    # Shape-only archive verification remains available for legacy callers.
    # A missing schema never passes the mandatory semantic publication replay.
    require(schema in (None, 'latent.phase1.measurement-aggregate.v1'), 'unsupported evidence schema')
    return 'measurement'


def verify_optimization(directory):
    retained = read_optimization_json(
        paths.existing_regular_file_path(directory / 'aggregate.json', 'aggregate'),
        MAX_AGGREGATE_BYTES)
    suite = paths.existing_regular_file_path(directory / 'suite.json', 'optimization suite')
    regenerated = validate_optimization_suite(suite)
    require(canonical(retained) == canonical(regenerated),
            'optimization aggregate differs from replayed evidence')
    require(regenerated.get('schema') == 'latent.optimization.aggregate.v1'
            and regenerated.get('profile') == 'full'
            and regenerated.get('status') == 'complete'
            and regenerated.get('population_complete') is True
            and regenerated.get('attempt_count_complete') is True,
            'optimization archive requires complete full-population evidence')


def verify_artifact_identity(directory):
    retained = read_optimization_json(
        paths.existing_regular_file_path(directory / 'aggregate.json', 'aggregate'),
        MAX_AGGREGATE_BYTES)
    suite = paths.existing_regular_file_path(directory / 'suite.json', 'artifact identity suite')
    regenerated = validate_artifact_identity_suite(suite)
    require(canonical(retained) == canonical(regenerated),
            'artifact identity aggregate differs from replayed evidence')
    require(regenerated.get('schema') == 'latent.artifact-identity.aggregate.v1'
            and regenerated.get('profile') == 'full'
            and regenerated.get('status') == 'passed'
            and regenerated.get('population_complete') is True
            and regenerated.get('full_comparison_qualified') is True,
            'artifact identity archive requires a qualified full comparison')


def verify_revision(directory, *, backend=False):
    kind = 'backend-revision' if backend else 'revision'
    retained = read_optimization_json(
        paths.existing_regular_file_path(directory / 'aggregate.json', 'aggregate'),
        MAX_AGGREGATE_BYTES)
    suite = paths.existing_regular_file_path(directory / 'suite.json', f'{kind} suite')
    validator = validate_backend_revision_suite if backend else validate_revision_suite
    regenerated = validator(suite)
    require(canonical(retained) == canonical(regenerated),
            f'{kind} aggregate differs from replayed evidence')
    require(regenerated.get('schema') == f'latent.optimization.{kind}-aggregate.v1'
            and regenerated.get('profile') == 'full'
            and regenerated.get('status') == 'complete'
            and regenerated.get('population_complete') is True
            and regenerated.get('attempt_count_complete') is True,
            f'{kind} archive requires complete full-population evidence')


def verify_package(directory, *, replay=True):
    root = paths.existing_directory_path(directory, 'evidence package')
    manifest = load_manifest(root)
    archive_path = paths.existing_regular_file_path(root / ARCHIVE, 'evidence archive')
    require(file_reference(archive_path, root, MAX_COMPRESSED) == manifest['archive'], 'archive checksum mismatch')
    checksum = paths.existing_regular_file_path(root / (ARCHIVE + '.sha256'), 'archive checksum')
    require(checksum.stat().st_size <= 256, 'oversized archive checksum')
    require(checksum.read_text() == manifest['archive']['sha256'][7:] + '  ' + ARCHIVE + '\n',
            'archive checksum sidecar mismatch')
    expected = {row['path']: row for row in manifest['files']}
    # Inspect fixed-size headers before a general tar parser can allocate a PAX
    # body. Packages use plain USTAR only. All expansion, padding and trailing
    # data are bounded and checked before the shared extractor is called.
    seen = set()
    zero_blocks = 0
    expanded = 0
    expansion_bound = size(manifest['total_bytes']) + len(expected) * 1024 + 10240
    with gzip.open(archive_path, 'rb') as archive:
        while header := archive.read(512):
            expanded += len(header)
            require(expanded <= expansion_bound and len(header) == 512, 'invalid tar expansion')
            if not any(header):
                zero_blocks += 1
                continue
            require(zero_blocks == 0, 'data follows tar end marker')
            member = tarfile.TarInfo.frombuf(header, encoding='utf-8', errors='strict')
            name = relative_path(member.name)
            require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE),
                    'archive member must be a plain regular file')
            require(name not in seen and name in expected, 'unexpected or duplicate archive member')
            require(member.size == size(expected[name]['bytes']), 'archive member size mismatch')
            seen.add(name)
            digest = hashlib.sha256()
            total = 0
            while total < member.size:
                chunk = archive.read(min(CHUNK, member.size - total))
                require(chunk, 'truncated tar member')
                digest.update(chunk)
                total += len(chunk)
            padding = (-member.size) % 512
            padding_bytes = archive.read(padding)
            require(len(padding_bytes) == padding and not any(padding_bytes), 'invalid tar padding')
            expanded += total + padding
            require(expanded <= expansion_bound, 'tar expansion exceeds bound')
            require(total == member.size and 'sha256:' + digest.hexdigest() == expected[name]['sha256'],
                    'archive member checksum mismatch')
    require(zero_blocks >= 2 and seen == set(expected), 'archive omits files or end markers')
    with tempfile.TemporaryDirectory(prefix='latent-phase1-archive-') as temporary:
        extracted = Path(temporary) / 'raw'
        with gzip.open(archive_path, 'rb') as stream:
            files = phase0_evidence.extract_tar_stream(stream, extracted, 'Phase 1 evidence')
        require(files == seen, 'extraction differs from verified archive')
        for name, row in expected.items():
            require(file_reference(extracted / name, extracted) == row, 'round-trip checksum mismatch')
        kind = evidence_kind(extracted)
        outer_files = (('aggregate.json', 'comparison.json', 'measurement-policy.json')
                       if kind == 'measurement' else ('aggregate.json',))
        if kind in ('optimization', 'artifact-identity', 'revision', 'backend-revision'):
            require('suite.json' in expected, f'{kind} archive omits suite')
        for name in outer_files:
            require(name in expected and file_reference(root / name, root) == expected[name],
                    'outer evidence differs from archived evidence')
        if replay:
            if kind == 'paired':
                validate_paired(extracted / 'aggregate.json')
            elif kind == 'optimization':
                verify_optimization(extracted)
            elif kind == 'artifact-identity':
                verify_artifact_identity(extracted)
            elif kind in ('revision', 'backend-revision'):
                verify_revision(extracted, backend=kind == 'backend-revision')
            else:
                validate_aggregate(extracted / 'aggregate.json')
                validate_comparison(extracted / 'comparison.json')
                policy = json.loads((extracted / 'measurement-policy.json').read_text())
                aggregate = json.loads((extracted / 'aggregate.json').read_text())
                verify_policy(policy, aggregate)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    try:
        manifest = verify_package(args.package)
    except (ValueError, OSError, tarfile.TarError, EOFError) as error:
        parser.exit(2, f'Phase 1 archive rejected: {error}\n')
    print(f"Phase 1 archive and evidence replay validated ({len(manifest['files'])} files).")


if __name__ == '__main__':
    main()
