"""Check the pinned, separately authenticated frontend qualification release."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tarfile


def unpack(root: Path):
    sums = {line.split()[1]: line.split()[0] for line in (root / 'SHA256SUMS').read_text().splitlines()}
    source = '2d6cc2eafc0a17dfe573be4252fa49835bebbbd6'
    archive_digest = 'a823a3c5b06ee81a09e39053451e768ee7b22199e37c3b524f89843db7b045b3'
    manifest = root / 'release.json'
    assert manifest.stat().st_size <= 1024 * 1024
    raw = manifest.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sums['release.json']
    release = json.loads(raw)
    assert release['sourceCommit'] == source and release['version'] == '0.1.0-alpha.4'
    archive = root / 'lsf-0.1.0-alpha.4-x86_64-unknown-linux-gnu.tar.gz'
    assert archive.stat().st_size == release['archive']['size'] == 29453861
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
