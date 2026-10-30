"""Exact LLVM 21 source backport; this module never acquires or builds tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'tools/data/java-llvm-ssa'
LLVM = '222fc11f2b8f25f6a0f4976272ef1bb7bf49521d'
SDK = '338aec5def0debda9de7e47838c9883e4e0d923f'
SCHEMA = 'latent.java.llvm-sjlj-phi-backport.v1'
PATCH_SHA256 = 'dd04c818debbb0491866ce119465526fb70a3112e85452b857d2528629b557ea'
PATHS = (
    'llvm/include/llvm/Transforms/Utils/SSAUpdaterBulk.h',
    'llvm/lib/Transforms/Utils/SSAUpdaterBulk.cpp',
    'llvm/unittests/Transforms/Utils/SSAUpdaterBulkTest.cpp',
    'llvm/lib/Target/WebAssembly/WebAssemblyLowerEmscriptenEHSjLj.cpp',
)
UPSTREAM = (
    '0e025418abda731629160639e2994f02f5fac1ab',
    'f140491dcc906e18aa67a6c204774245c69fc606',
    '23f6a8aeaf9feb781025c54cf3f12db69f633cb5',
    'ca9f43fe158d929e78d0443d075f07947eb86fcd',
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def regular(root: Path, name: str, maximum: int = 1024 * 1024) -> bytes:
    """Read only anchored, regular source members; never follow a component link."""
    parts = PurePosixPath(name)
    if parts.is_absolute() or '..' in parts.parts or '\\' in name:
        raise ValueError('llvm-patch-path')
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError('llvm-patch-root')
    cursor = root
    for part in parts.parts:
        cursor /= part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode) or cursor.is_junction():
            raise ValueError('llvm-patch-link')
    before = cursor.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise ValueError('llvm-patch-file')
    with cursor.open('rb') as stream:
        data = stream.read(maximum + 1)
    after = cursor.stat()
    if (len(data) != before.st_size or len(data) > maximum
            or (before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError('llvm-patch-mutated')
    return data


def manifest() -> dict:
    raw = regular(DATA, 'patch.json')
    if sha(raw) != PATCH_SHA256:
        raise ValueError('llvm-patch-manifest-identity')
    value = json.loads(raw)
    if (set(value) != {'schemaVersion', 'llvmCommit', 'wasiSdkCommit', 'upstreamCommits', 'scope', 'files'}
            or value['schemaVersion'] != SCHEMA or value['llvmCommit'] != LLVM
            or value['wasiSdkCommit'] != SDK or value['upstreamCommits'] != list(UPSTREAM)
            or tuple(value['files']) != PATHS):
        raise ValueError('llvm-patch-manifest-shape')
    fields = {'original', 'originalBytes', 'originalSha256',
              'modified', 'modifiedBytes', 'modifiedSha256'}
    for row in value['files'].values():
        if set(row) != fields:
            raise ValueError('llvm-patch-member-shape')
        for stage in ('original', 'modified'):
            data = row[stage].encode('utf-8')
            if not 0 < len(data) <= 1024 * 1024 or len(data) != row[stage + 'Bytes'] or sha(data) != row[stage + 'Sha256']:
                raise ValueError('llvm-patch-member-identity')
    return value


def identities(stage: str) -> dict:
    if stage not in ('original', 'modified'):
        raise ValueError('llvm-patch-stage')
    return {name: {'bytes': row[stage + 'Bytes'], 'sha256': row[stage + 'Sha256']}
            for name, row in manifest()['files'].items()}


def check(source: Path, stage: str) -> dict:
    expected = identities(stage)
    actual = {name: {'bytes': len(data), 'sha256': sha(data)}
              for name in PATHS for data in [regular(source, name)]}
    if actual != expected:
        raise ValueError('llvm-patch-source-identity')
    return actual


def apply(source: Path) -> dict:
    """All four preimages must match before the first write; no replay/fallback."""
    value = manifest()
    before = check(source, 'original')
    for name, row in value['files'].items():
        # Recheck each original at the write boundary; the complete tree belongs
        # exclusively to this producer and no build child is running yet.
        if regular(source, name) != row['original'].encode('utf-8'):
            raise ValueError('llvm-patch-source-mutated')
        (source / name).write_bytes(row['modified'].encode('utf-8'))
    after = check(source, 'modified')
    return {'schemaVersion': SCHEMA, 'llvmCommit': LLVM, 'wasiSdkCommit': SDK,
            'patchSha256': PATCH_SHA256, 'upstreamCommits': list(UPSTREAM),
            'before': before, 'after': after}


def unit_cases() -> tuple[str, ...]:
    source = manifest()['files'][PATHS[2]]['modified']
    cases = re.findall(r'^TEST\(SSAUpdaterBulk, (\w+)\)', source, re.M)
    if len(cases) != 9 or len(set(cases)) != 9:
        raise ValueError('llvm-patch-unit-cases')
    return tuple('SSAUpdaterBulk.' + name for name in cases)
