"""Bounded stopped snapshot/restore for the node-owned local container layout."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

# The maintained helper is run from a reviewed checkout, not from the image.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_runtime import files
from native_runtime.common import InstallError, document, encode, require
from ownership import acquire

ROOTS = ('config', 'data', 'cache')
MAX_ENTRIES = 16384
MAX_BYTES = 1024 * 1024 * 1024


def scan(root: Path, deadline: float) -> dict:
    rows, hardlinks = {}, {}
    total = 0
    pending = [Path(name) for name in ROOTS]
    while pending:
        relative = pending.pop()
        require(time.monotonic() < deadline and len(rows) < MAX_ENTRIES, 'snapshot-entry-or-time-bound')
        source = root / relative
        with files.directory(source.parent, {0, 10001}) as parent:
            fd = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        try:
            info = os.fstat(fd)
            require(info.st_uid == 10001 and info.st_gid == 10001 and not info.st_mode & 0o022,
                    'snapshot-requires-node-owned-protected-layout')
            files.no_acl(fd)
            record = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
            if stat.S_ISDIR(info.st_mode):
                record['kind'] = 'directory'
                names = os.listdir(fd)
                require(len(names) + len(rows) + len(pending) <= MAX_ENTRIES, 'snapshot-entry-bound')
                for name in sorted(names, reverse=True):
                    require(len(name.encode()) <= 240 and name not in {'.', '..'}, 'snapshot-path-bound')
                    pending.append(relative / name)
            else:
                require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_BYTES, 'snapshot-regular-file-required')
                total += info.st_size
                require(total <= MAX_BYTES, 'snapshot-byte-bound')
                digest, size = files.digest_fd(fd, MAX_BYTES)
                inode = (info.st_dev, info.st_ino)
                record.update(kind='file', size=size, sha256=digest,
                              linkGroup=hardlinks.setdefault(inode, relative.as_posix()), links=info.st_nlink)
            after = os.fstat(fd)
            require(all(getattr(after, field) == getattr(info, field)
                        for field in ('st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_nlink')),
                    'snapshot-source-changed')
            rows[relative.as_posix()] = record
        finally:
            os.close(fd)
    counts = Counter(row['linkGroup'] for row in rows.values() if row['kind'] == 'file')
    require(all(row['links'] == counts[row['linkGroup']] for row in rows.values() if row['kind'] == 'file'),
            'snapshot-hardlink-outside-coupled-roots')
    return dict(sorted(rows.items()))


def copy(source: Path, target: Path, rows: dict, deadline: float):
    copied = {}
    for relative, row in sorted(rows.items(), key=lambda pair: (len(Path(pair[0]).parts), pair[0])):
        require(time.monotonic() < deadline, 'snapshot-copy-time-bound')
        destination = target / relative
        if row['kind'] == 'directory':
            files.mkdir(destination, 0o700, (10001, 10001), owners={0, 10001})
            continue
        identity = row['linkGroup']
        if identity in copied:
            os.link(copied[identity], destination, follow_symlinks=False)
            continue
        with files.directory((source / relative).parent, {0, 10001}) as parent:
            src = os.open(Path(relative).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        with files.directory(destination.parent, {0, 10001}) as parent:
            dst = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                          0o600, dir_fd=parent)
        try:
            info = os.fstat(src)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 10001 and info.st_size == row['size'],
                    'snapshot-source-file-changed')
            digest, size = hashlib.sha256(), 0
            while block := os.read(src, 65536):
                require(time.monotonic() < deadline, 'snapshot-copy-time-bound')
                size += len(block)
                require(size <= row['size'], 'snapshot-source-size-changed')
                digest.update(block)
                remaining = memoryview(block)
                while remaining:
                    written = os.write(dst, remaining)
                    require(written > 0, 'snapshot-write-incomplete')
                    remaining = remaining[written:]
            require(size == row['size'] and digest.hexdigest() == row['sha256'], 'snapshot-source-bytes-changed')
            os.fchmod(dst, row['mode'])
            os.fsync(dst)
            copied[identity] = destination
        finally:
            os.close(src)
            os.close(dst)
    for relative, row in sorted(rows.items(), key=lambda pair: len(Path(pair[0]).parts), reverse=True):
        if row['kind'] == 'directory':
            with files.directory(target / relative, {0, 10001}) as descriptor:
                os.fchmod(descriptor, row['mode'])
                os.fsync(descriptor)


def transfer(source: Path, output: Path, mode: str) -> dict:
    source, output = source.absolute(), output.absolute()
    files.absolute(source)
    files.absolute(output)
    require(not output.is_relative_to(source) and not source.is_relative_to(output), 'snapshot-roots-must-be-disjoint')
    require(not output.exists(), 'fresh-snapshot-destination-required')
    os.umask(0o077)
    owner = acquire(source / 'data')
    try:
        deadline = time.monotonic() + 120
        before = scan(source, deadline)
        if mode == 'restore':
            receipt = document(files.read(source / 'SNAPSHOT-COMPLETE.json', 8 * 1024 * 1024,
                                          owners={0, 10001}, private=True), 8 * 1024 * 1024)
            require(receipt.get('schemaVersion') == 'latent.container-snapshot.v1'
                    and receipt.get('entries') == before, 'complete-exact-snapshot-required')
        files.mkdir(output, 0o700, (10001, 10001), owners={0, 10001})
        copy(source, output, before, deadline)
        require(scan(source, deadline) == before and scan(output, deadline) == before, 'snapshot-source-or-copy-changed')
        receipt = {'schemaVersion': 'latent.container-snapshot.v1', 'entries': before,
                   'consistency': 'stopped-coupled-private-roots', 'mode': mode}
        files.create(output / 'SNAPSHOT-COMPLETE.json', encode(receipt))
        return {'schemaVersion': 'latent.container-snapshot-result.v1', 'passed': True, 'mode': mode,
                'entries': len(before), 'contentAndModesVerified': True, 'hardlinksPreserved': True,
                'powerLossQualified': False, 'remoteFilesystemQualified': False}
    finally:
        os.close(owner)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('snapshot', 'restore'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(transfer(args.source, args.output, args.mode)))
        return 0
    except InstallError as error:
        print(str(error), file=sys.stderr)
    except OSError:
        print('inspect-protected-node-owned-snapshot-paths', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
