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
                                         verify_package)
except ImportError:
    import package_phase0_evidence as paths
    from validate_phase1_archive import (ARCHIVE, MANIFEST, MAX_COMPRESSED, MAX_EXPANDED,
                                        MAX_FILES, evidence_kind, file_reference, relative_path, require,
                                        verify_package)


def create_archive(source, stage, policy):
    kind = evidence_kind(source)
    files = {relative_path(path.relative_to(source).as_posix()): path
             for path in paths.regular_files(source, 'measurement source')}
    if kind == 'measurement':
        require('measurement-policy.json' not in files, 'source already contains a policy copy')
        files['measurement-policy.json'] = paths.existing_regular_file_path(policy, 'measurement policy')
    require(len(files) <= MAX_FILES, 'too many evidence files')
    require(sum(path.stat().st_size for path in files.values()) <= MAX_EXPANDED, 'evidence exceeds expanded bound')
    references = []
    archive_path = stage / ARCHIVE
    with archive_path.open('xb') as output:
        with gzip.GzipFile(filename='', mode='wb', fileobj=output, compresslevel=6, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                for name, path in sorted(files.items()):
                    original = file_reference(path, path.parent)
                    references.append({**original, 'path': name})
                    info = tarfile.TarInfo(name)
                    info.size = int(original['bytes'])
                    info.mode = 0o644
                    info.mtime = 0
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
    manifest = {'schema': 'latent.phase1.archive-manifest.v1',
                'archive': file_reference(archive_path, stage, MAX_COMPRESSED),
                'files': references, 'total_bytes': str(sum(int(row['bytes']) for row in references))}
    (stage / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    (stage / (ARCHIVE + '.sha256')).write_text(manifest['archive']['sha256'][7:] + '  ' + ARCHIVE + '\n', encoding='ascii', newline='\n')
    outer_files = (('aggregate.json', 'comparison.json', 'measurement-policy.json')
                   if kind == 'measurement' else ('aggregate.json',))
    for name in outer_files:
        require(name in files, 'required outer measurement evidence missing')
        shutil.copyfile(files[name], stage / name)
    return manifest


def package(source, output, policy):
    source = paths.existing_directory_path(source, 'measurement source')
    output = paths.absent_output_path(output)
    require(not output.is_relative_to(source) and not source.is_relative_to(output),
            'source and output must not overlap')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.latent-phase1-package-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'package'
        stage.mkdir()
        manifest = create_archive(source, stage, policy)
        verify_package(stage)
        stage.rename(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--policy', type=Path, default=Path(__file__).resolve().parents[1] / 'benchmarks/phase1/measurement-policy.json')
    args = parser.parse_args()
    try:
        manifest = package(args.source, args.output, args.policy)
    except (ValueError, OSError, tarfile.TarError, EOFError) as error:
        parser.exit(2, f'Phase 1 packaging failed: {error}\n')
    print(f"Packaged and replayed {len(manifest['files'])} unchanged evidence files.")


if __name__ == '__main__':
    main()
