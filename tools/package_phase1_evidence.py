#!/usr/bin/env python3
"""Package Phase 1 evidence, including independent revision diagnostics, with mandatory replay."""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

try:
    from . import package_phase0_evidence as paths
    from .validate_phase1_archive import (ARCHIVE, MANIFEST, MAX_COMPRESSED, MAX_EXPANDED,
                                         MAX_FILES, evidence_kind, file_reference, relative_path, require,
                                         verify_package, CHUNK, MAX_SPLIT_COMPRESSED, PARTS_MANIFEST,
                                         split_layout, archive_bounds)
except ImportError:
    import package_phase0_evidence as paths
    from validate_phase1_archive import (ARCHIVE, MANIFEST, MAX_COMPRESSED, MAX_EXPANDED,
                                        MAX_FILES, evidence_kind, file_reference, relative_path, require,
                                        verify_package, CHUNK, MAX_SPLIT_COMPRESSED, PARTS_MANIFEST,
                                        split_layout, archive_bounds)


def checked_compression_level(value):
    require(type(value) is int and 1 <= value <= 9, 'compression level must be an integer from 1 through 9')
    return value


def write_split_archive(stage, archive_reference):
    archive_path = stage / ARCHIVE
    references = []
    with archive_path.open('rb') as source:
        for name, expected_bytes in split_layout(int(archive_reference['bytes'])):
            part = stage / name
            remaining = expected_bytes
            with part.open('xb') as output:
                while remaining:
                    chunk = source.read(min(CHUNK, remaining))
                    require(chunk, 'archive truncated while splitting')
                    output.write(chunk)
                    remaining -= len(chunk)
            references.append(file_reference(part, stage, MAX_COMPRESSED))
        require(source.read(1) == b'', 'archive grew while splitting')
    value = {'schema': 'latent.phase1.archive-parts.v1', 'archive': archive_reference,
             'parts': references}
    (stage / PARTS_MANIFEST).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n',
                                       encoding='utf-8', newline='\n')
    # The oversized logical stream is temporary; only bounded parts are published.
    archive_path.unlink()


def create_archive(source, stage, policy, compression_level=6, *, split_archive=False):
    compression_level = checked_compression_level(compression_level)
    require(type(split_archive) is bool, 'split archive option must be a boolean')
    kind = evidence_kind(source)
    maximum_expanded, maximum_file = archive_bounds(kind)
    files = {relative_path(path.relative_to(source).as_posix()): path
             for path in paths.regular_files(source, 'measurement source')}
    if kind == 'measurement':
        require('measurement-policy.json' not in files, 'source already contains a policy copy')
        files['measurement-policy.json'] = paths.existing_regular_file_path(policy, 'measurement policy')
    require(len(files) <= MAX_FILES, 'too many evidence files')
    require(sum(path.stat().st_size for path in files.values()) <= maximum_expanded, 'evidence exceeds expanded bound')
    references = []
    archive_path = stage / ARCHIVE
    with archive_path.open('xb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, compresslevel=compression_level, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                for name, path in sorted(files.items()):
                    original = file_reference(path, path.parent, maximum_file)
                    references.append({**original, 'path': name})
                    info = tarfile.TarInfo(name)
                    info.size = int(original['bytes'])
                    info.mode = 0o644
                    info.mtime = 0
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
    compressed_bytes = archive_path.stat().st_size
    maximum = MAX_SPLIT_COMPRESSED if split_archive else MAX_COMPRESSED
    require(compressed_bytes <= maximum,
            f'compressed evidence exceeds bound: {archive_path}; actual={compressed_bytes} bytes, maximum={maximum} bytes')
    manifest = {'schema': 'latent.phase1.archive-manifest.v1',
                'archive': file_reference(archive_path, stage, maximum),
                'files': references, 'total_bytes': str(sum(int(row['bytes']) for row in references))}
    (stage / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    (stage / (ARCHIVE + '.sha256')).write_text(manifest['archive']['sha256'][7:] + '  ' + ARCHIVE + '\n', encoding='ascii', newline='\n')
    if split_archive:
        write_split_archive(stage, manifest['archive'])
    outer_files = (('aggregate.json', 'comparison.json', 'measurement-policy.json')
                   if kind == 'measurement' else ('aggregate.json',))
    for name in outer_files:
        require(name in files, 'required outer measurement evidence missing')
        shutil.copyfile(files[name], stage / name)
    return manifest


def package(source, output, policy, compression_level=6, *, split_archive=False):
    compression_level = checked_compression_level(compression_level)
    require(type(split_archive) is bool, 'split archive option must be a boolean')
    source = paths.existing_directory_path(source, 'measurement source')
    output = paths.absent_output_path(output)
    require(not output.is_relative_to(source) and not source.is_relative_to(output),
            'source and output must not overlap')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.latent-phase1-package-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'package'
        stage.mkdir()
        manifest = create_archive(source, stage, policy, compression_level, split_archive=split_archive)
        verify_package(stage)
        stage.rename(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--policy', type=Path, default=Path(__file__).resolve().parents[1] / 'benchmarks/phase1/measurement-policy.json')
    parser.add_argument('--compression-level', type=int, choices=range(1, 10), default=6,
                        help='gzip level 1 through 9; default 6 preserves existing archive output')
    parser.add_argument('--split-archive', action='store_true',
                        help='retain the exact gzip stream in 2–4 parts of at most 50 MB (198 MB total)')
    args = parser.parse_args()
    try:
        manifest = package(args.source, args.output, args.policy, args.compression_level,
                           split_archive=args.split_archive)
    except (ValueError, OSError, tarfile.TarError, EOFError) as error:
        parser.exit(2, f'Phase 1 packaging failed: {error}\n')
    print(f"Packaged and replayed {len(manifest['files'])} unchanged evidence files.")


if __name__ == '__main__':
    main()
