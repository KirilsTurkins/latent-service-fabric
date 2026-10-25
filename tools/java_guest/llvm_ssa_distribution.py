"""Typed, mode-preserving carrier and closed upload admission for one compiler."""
from __future__ import annotations

import gzip
import hashlib
import io as byteio
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import tarfile
import time

from tools.java_guest import llvm_ssa_io as io, llvm_ssa_patch as patch

PROFILE = 'lsf-sjlj-phi-v1'
SCHEMA = 'latent.java.llvm-sjlj-carrier.v1'
ARCHIVE = 'derived-sdk.tar.gz'
MANIFEST = 'derived-sdk-manifest.json'
UPLOAD_BYTES = 2 * io.GIB
METADATA_BYTES = 64 * 1024 ** 2
CARRIER_BYTES = UPLOAD_BYTES - METADATA_BYTES
MANIFEST_BYTES = 16 * 1024 ** 2
TOP = {'toolchain', 'official-origin-VERSION', 'LLVM-LICENSE.txt', 'LLVM-PATCH.json', 'NOTICE'}
FIXED_METADATA = {
    'result.json': 8 * 1024 ** 2, 'source.json': 8 * 1024 ** 2,
    'commands.json': 8 * 1024 ** 2, 'units.xml': 256 * 1024,
    'lit.xml': 256 * 1024, 'sjlj-through-wineh.ll': 256 * 1024,
    'sjlj-through-wineh.o': 1024 ** 2, MANIFEST: MANIFEST_BYTES,
}


def encode(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def check_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ValueError('llvm-carrier-deadline')


def name_check(name: str) -> None:
    if (not isinstance(name, str) or not 0 < len(name.encode()) <= 4096
            or any(ord(c) < 32 for c in name) or '\\' in name
            or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
            or PurePosixPath(name).as_posix() != name):
        raise ValueError('llvm-carrier-member-name')


def payload_rows(root: Path, deadline: float) -> dict:
    rows = io.inventory(root, io.PRODUCT_BYTES, deadline, include_directories=True)
    if {PurePosixPath(n).parts[0] for n in rows} != TOP:
        raise ValueError('llvm-carrier-product-set')
    result = {}
    for name, identity in rows.items():
        name_check(name)
        mode = stat.S_IMODE((root / name).lstat().st_mode)
        if mode & ~0o777:
            raise ValueError('llvm-carrier-member-mode')
        if 'directory' in identity:
            result[name] = {'kind': 'directory', 'mode': mode}
        elif 'link' in identity:
            result[name] = {'kind': 'symlink', 'mode': mode, 'link': identity['link']}
        else:
            result[name] = {'kind': 'file', 'mode': mode,
                            'bytes': identity['bytes'], 'sha256': identity['sha256']}
    return result


def validate_manifest(value, deadline: float) -> bytes:
    if (not isinstance(value, dict) or set(value) != {
            'schemaVersion', 'profile', 'sourceCommit', 'llvmCommit', 'patchSha256',
            'decodedByteLimit', 'members'} or value['schemaVersion'] != SCHEMA
            or value['profile'] != PROFILE or value['llvmCommit'] != patch.LLVM
            or value['patchSha256'] != patch.PATCH_SHA256
            or value['decodedByteLimit'] != io.PRODUCT_BYTES
            or not re.fullmatch(r'[0-9a-f]{40}', value['sourceCommit'])
            or not isinstance(value['members'], dict) or not 0 < len(value['members']) <= io.MAX_ENTRIES):
        raise ValueError('llvm-carrier-manifest')
    rows, total = value['members'], 0
    if {PurePosixPath(n).parts[0] for n in rows} != TOP:
        raise ValueError('llvm-carrier-product-set')
    if (rows.get('toolchain', {}).get('kind') != 'directory'
            or any(rows.get(n, {}).get('kind') != 'file' for n in TOP - {'toolchain'})):
        raise ValueError('llvm-carrier-product-set')
    for name, row in rows.items():
        check_time(deadline)
        name_check(name)
        if (not isinstance(row, dict) or type(row.get('mode')) is not int
                or not 0 <= row['mode'] <= 0o777):
            raise ValueError('llvm-carrier-member-mode')
        kind, keys = row.get('kind'), {'kind', 'mode'}
        if kind == 'file':
            keys |= {'bytes', 'sha256'}
            if (type(row.get('bytes')) is not int or not 0 <= row['bytes'] <= io.MAX_SINGLE_FILE
                    or not re.fullmatch(r'[0-9a-f]{64}', row.get('sha256', ''))):
                raise ValueError('llvm-carrier-file')
            total += row['bytes']
        elif kind == 'symlink':
            keys.add('link')
            link = row.get('link')
            if (not isinstance(link, str) or not 0 < len(link.encode()) <= 4096
                    or '\\' in link or any(ord(c) < 32 for c in link) or posixpath.isabs(link)):
                raise ValueError('llvm-carrier-link')
            total += len(link.encode())
        elif kind != 'directory':
            raise ValueError('llvm-carrier-member-kind')
        if set(row) != keys:
            raise ValueError('llvm-carrier-member-fields')
        parent = PurePosixPath(name).parent.as_posix()
        if parent != '.' and rows.get(parent, {}).get('kind') != 'directory':
            raise ValueError('llvm-carrier-parent')
    # Resolve link chains, including directory aliases, against this complete
    # manifest. Neither archive validation nor upload follows host symlinks.
    for name, row in rows.items():
        if row['kind'] != 'symlink':
            continue
        parts = list(PurePosixPath(name).parent.parts) + list(PurePosixPath(row['link']).parts)
        resolved, steps = [], 0
        while parts:
            check_time(deadline)
            part = parts.pop(0)
            if part == '..':
                if not resolved:
                    raise ValueError('llvm-carrier-link')
                resolved.pop()
            elif part != '.':
                resolved.append(part)
                target = '/'.join(resolved)
                if rows.get(target, {}).get('kind') == 'symlink':
                    steps += 1
                    if steps > len(rows):
                        raise ValueError('llvm-carrier-link')
                    resolved.pop()
                    parts = list(PurePosixPath(rows[target]['link']).parts) + parts
        if '/'.join(resolved) not in rows:
            raise ValueError('llvm-carrier-link')
    raw = encode(value)
    if len(raw) > MANIFEST_BYTES or total + len(raw) > io.PRODUCT_BYTES:
        raise ValueError('llvm-carrier-decoded-bound')
    return raw


class BoundedWriter:
    def __init__(self, output, deadline):
        self.output, self.deadline, self.count = output, deadline, 0

    def write(self, data):
        check_time(self.deadline)
        if self.count + len(data) > CARRIER_BYTES:
            raise ValueError('llvm-carrier-encoded-bound')
        count = self.output.write(data)
        self.count += count
        return count

    def flush(self):
        self.output.flush()


def write_carrier(root: Path, target: Path, value: dict, deadline: float) -> None:
    """Write actual tar headers; upload-artifact never rewrites SDK modes/links."""
    raw = validate_manifest(value, deadline)
    with target.open('xb') as output, gzip.GzipFile(
            filename='', mode='wb', fileobj=BoundedWriter(output, deadline), mtime=0) as compressed, \
            tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as carrier:
        member = tarfile.TarInfo('MANIFEST.json')
        member.mode, member.size = 0o644, len(raw)
        carrier.addfile(member, byteio.BytesIO(raw))
        for name, row in sorted(value['members'].items()):
            check_time(deadline)
            member = tarfile.TarInfo(name)
            member.mode = row['mode']
            if row['kind'] == 'file':
                member.size = row['bytes']
                with (root / name).open('rb') as stream:
                    carrier.addfile(member, stream)
            elif row['kind'] == 'directory':
                member.type = tarfile.DIRTYPE
                carrier.addfile(member)
            else:
                member.type, member.linkname = tarfile.SYMTYPE, row['link']
                carrier.addfile(member)


def file_identity(root: Path, name: str, maximum: int, deadline: float) -> dict:
    name_check(name)
    path = root / name
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError('llvm-carrier-file-root')
    for part in PurePosixPath(name).parts:
        root = root / part
        if root.is_symlink() or root.is_junction():
            raise ValueError('llvm-carrier-file-link')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise ValueError('llvm-carrier-file-bound')
    hasher, count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while data := stream.read(65536):
            check_time(deadline)
            count += len(data)
            if count > maximum:
                raise ValueError('llvm-carrier-file-bound')
            hasher.update(data)
    after = path.stat()
    if (count != before.st_size or (before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError('llvm-carrier-file-mutated')
    return {'bytes': count, 'sha256': hasher.hexdigest()}


def verify_carrier(root: Path, name: str, value: dict, deadline: float) -> dict:
    expected = validate_manifest(value, deadline)
    identity = file_identity(root, name, CARRIER_BYTES, deadline)
    seen = set()
    with tarfile.open(root / name, mode='r|gz') as carrier:
        for member in carrier:
            check_time(deadline)
            if member.name in seen or len(seen) > io.MAX_ENTRIES:
                raise ValueError('llvm-carrier-member-set')
            seen.add(member.name)
            if (member.uid != 0 or member.gid != 0 or member.mtime != 0
                    or member.uname or member.gname or member.issparse()
                    or set(member.pax_headers) - {'path', 'linkpath'}):
                raise ValueError('llvm-carrier-header')
            if member.name == 'MANIFEST.json':
                if (len(seen) != 1 or not member.isfile() or member.mode != 0o644
                        or member.size != len(expected)
                        or carrier.extractfile(member).read(MANIFEST_BYTES + 1) != expected):
                    raise ValueError('llvm-carrier-manifest')
                continue
            row = value['members'].get(member.name)
            if row is None or member.mode != row['mode']:
                raise ValueError('llvm-carrier-member-set')
            if row['kind'] == 'file':
                if not member.isfile() or member.size != row['bytes']:
                    raise ValueError('llvm-carrier-file')
                hasher, count = hashlib.sha256(), 0
                stream = carrier.extractfile(member)
                while data := stream.read(65536):
                    check_time(deadline)
                    count += len(data)
                    hasher.update(data)
                if count != row['bytes'] or hasher.hexdigest() != row['sha256']:
                    raise ValueError('llvm-carrier-file')
            elif row['kind'] == 'directory':
                if not member.isdir() or member.size:
                    raise ValueError('llvm-carrier-directory')
            elif not member.issym() or member.linkname != row['link'] or member.size:
                raise ValueError('llvm-carrier-link')
        trailing = 0
        while data := carrier.fileobj.read(65536):
            check_time(deadline)
            trailing += len(data)
            if trailing > tarfile.RECORDSIZE or any(data):
                raise ValueError('llvm-carrier-trailing-data')
    if seen != {'MANIFEST.json', *value['members']}:
        raise ValueError('llvm-carrier-member-set')
    if file_identity(root, name, CARRIER_BYTES, deadline) != identity:
        raise ValueError('llvm-carrier-file-mutated')
    return identity


def create(root: Path, source_commit: str, deadline: float) -> dict:
    products = root / 'products'
    members = payload_rows(products, deadline)
    value = {'schemaVersion': SCHEMA, 'profile': PROFILE, 'sourceCommit': source_commit,
             'llvmCommit': patch.LLVM, 'patchSha256': patch.PATCH_SHA256,
             'decodedByteLimit': io.PRODUCT_BYTES, 'members': members}
    raw = validate_manifest(value, deadline)
    partial = root / (ARCHIVE + '.part')
    write_carrier(products, partial, value, deadline)
    identity = verify_carrier(root, partial.name, value, deadline)
    if payload_rows(products, deadline) != members:
        raise ValueError('llvm-carrier-product-mutated')
    if (root / ARCHIVE).exists() or (root / MANIFEST).exists():
        raise ValueError('llvm-carrier-output-exists')
    (root / MANIFEST).write_bytes(raw)
    partial.rename(root / ARCHIVE)
    return {'archive': {'path': ARCHIVE, **identity},
            'manifest': {'path': MANIFEST, 'bytes': len(raw), 'sha256': patch.sha(raw)},
            'decodedLogicalBytes': len(raw) + sum(row.get('bytes', len(row.get('link', '').encode()))
                                                 for row in members.values()),
            'decodedByteLimit': io.PRODUCT_BYTES, 'carrierByteLimit': CARRIER_BYTES,
            'members': len(members)}


def admit_upload(root: Path, source_commit: str, deadline: float) -> dict:
    """Always run before upload, including failed compiler/partial-package cases."""
    rows = {}
    for name, maximum in FIXED_METADATA.items():
        if (root / name).exists() or (root / name).is_symlink():
            rows[name] = file_identity(root, name, maximum, deadline)
    commands = root / 'commands'
    if commands.exists() or commands.is_symlink():
        if commands.is_symlink() or commands.is_junction() or not commands.is_dir():
            raise ValueError('llvm-upload-command-directory')
        for path in commands.iterdir():
            if (len(rows) >= 256 or not re.fullmatch(
                    r'[0-9]{2}-[a-z0-9-]{1,80}\.(stdout|stderr)\.log', path.name)):
                raise ValueError('llvm-upload-command-member')
            if path.is_file() and not path.is_symlink() and path.stat().st_size == 0:
                rows['commands/' + path.name] = {'bytes': 0, 'sha256': patch.sha(b'')}
            else:
                rows['commands/' + path.name] = file_identity(root, 'commands/' + path.name,
                                                            4 * 1024 ** 2, deadline)
    result = json.loads(patch.regular(root, 'result.json', 8 * 1024 ** 2)) if 'result.json' in rows else None
    carrier = None
    if result is not None and result.get('status') == 'passed':
        if (result.get('schemaVersion') != 'latent.java.llvm-sjlj-producer.v1'
                or result.get('source', {}).get('sourceCommit') != source_commit
                or result.get('profile') != PROFILE):
            raise ValueError('llvm-upload-qualification')
        value = json.loads(patch.regular(root, MANIFEST, MANIFEST_BYTES))
        if value.get('sourceCommit') != source_commit:
            raise ValueError('llvm-upload-qualification')
        carrier = verify_carrier(root, ARCHIVE, value, deadline)
        distribution = result.get('distribution', {})
        if (distribution.get('archive') != {'path': ARCHIVE, **carrier}
                or distribution.get('manifest') != {'path': MANIFEST, **rows[MANIFEST]}):
            raise ValueError('llvm-upload-qualification')
    elif (root / ARCHIVE).exists() or (root / ARCHIVE).is_symlink():
        # A late source/deadline failure can leave a completely built carrier.
        # Preserve it under a fixed unqualified name; the upload never selects it.
        file_identity(root, ARCHIVE, CARRIER_BYTES, deadline)
        destination = root / 'unqualified-derived-sdk.tar.gz'
        if destination.exists() or destination.is_symlink():
            raise ValueError('llvm-upload-unqualified-collision')
        (root / ARCHIVE).rename(destination)
    summary = {'schemaVersion': 'latent.java.llvm-sjlj-upload.v1', 'sourceCommit': source_commit,
               'qualifiedCompiler': carrier is not None, 'metadata': rows, 'carrier': carrier,
               'metadataByteLimit': METADATA_BYTES, 'carrierByteLimit': CARRIER_BYTES,
               'uploadedByteLimit': UPLOAD_BYTES}
    raw = encode(summary)
    metadata_bytes = sum(row['bytes'] for row in rows.values()) + len(raw)
    if len(raw) > 65536 or metadata_bytes > METADATA_BYTES:
        raise ValueError('llvm-upload-metadata-bound')
    if metadata_bytes + (carrier or {}).get('bytes', 0) > UPLOAD_BYTES:
        raise ValueError('llvm-upload-total-bound')
    check_time(deadline)
    with (root / 'upload-admission.json').open('xb') as stream:
        stream.write(raw)
    return {'qualifiedCompiler': carrier is not None, 'metadataBytes': metadata_bytes,
            'carrierBytes': (carrier or {}).get('bytes', 0)}
