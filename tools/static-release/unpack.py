"""Check the pinned, separately authenticated frontend qualification release."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tarfile


def unpack(root: Path):
    sums = {line.split()[1]: line.split()[0] for line in (root / 'SHA256SUMS').read_text().splitlines()}
    source = 'f6d8f32177208b60a68f14070f549f927052dd48'
    archive_digest = '873e597e5b3f4694e2204bf58b05d1be41a624927f02ef25be5ab5899f071725'
    manifest = root / 'release.json'
    assert manifest.stat().st_size <= 1024 * 1024
    raw = manifest.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sums['release.json']
    release = json.loads(raw)
    assert release['sourceCommit'] == source and release['version'] == '0.1.0-alpha.5'
    archive = root / 'lsf-0.1.0-alpha.5-x86_64-unknown-linux-gnu.tar.gz'
    assert archive.stat().st_size == release['archive']['size'] == 30519375
    with archive.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == sums[archive.name] == archive_digest
    destination = root / 'extracted'
    destination.mkdir(mode=0o755)
    with tarfile.open(archive, 'r:gz') as stream:
        entries, total, names = 0, 0, set()
        for member in stream:
            entries += 1
            total += member.size
            assert entries <= 4096 and total <= 1024 ** 3 and member.name not in names
            names.add(member.name)
            assert member.isfile() or member.isdir()
            target = (destination / member.name).resolve()
            assert target.is_relative_to(destination.resolve())
            stream.extract(member, destination, filter='data')
    for entry in release['files']:
        candidate = destination / entry['path']
        assert candidate.is_file() and not candidate.is_symlink()
        assert candidate.stat().st_size == entry['size']
        with candidate.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == entry['sha256']
    return {'sourceCommit': source, 'archiveSha256': archive_digest, 'archiveEntries': entries,
            'publisherAuthentication': 'required-in-preceding-exact-gh-verification'}


if __name__ == '__main__':
    print(json.dumps(unpack(Path(sys.argv[1]).resolve(strict=True))))
