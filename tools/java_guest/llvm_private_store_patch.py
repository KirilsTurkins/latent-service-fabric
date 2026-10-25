"""Fixed R8 supplement; no acquisition, build, runtime loader or fuzzy patch."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import stat

from tools.java_guest import llvm_ssa_patch as base

ROOT, LLVM, SDK, UPSTREAM = base.ROOT, base.LLVM, base.SDK, base.UPSTREAM
regular, sha, unit_cases = base.regular, base.sha, base.unit_cases
DATA = ROOT / 'tools/data/java-llvm-private-stores'
SCHEMA = 'latent.java.llvm-private-scalar-supplement.v1'
PATCH_SHA256 = '4fe9958f20d2e5b5d04d13717ae74b16d1bda1d8a720652d3caa36f10e5e899d'
PROFILE = 'lsf-private-scalar-v1'
TARGET = 'llvm/lib/Target/WebAssembly/WebAssemblyTargetMachine.cpp'
TESTS = ('llvm/test/CodeGen/WebAssembly/private-scalar-store-traces.ll',
         'llvm/test/CodeGen/WebAssembly/private-scalar-store-barriers.ll')
PATHS = (*base.PATHS, TARGET, *TESTS)


def identity(raw: bytes) -> dict:
    return {'bytes': len(raw), 'sha256': sha(raw)}


def manifest() -> dict:
    raw = regular(DATA, 'supplement.json')
    if sha(raw) != PATCH_SHA256:
        raise ValueError('llvm-private-supplement-identity')
    value = json.loads(raw)
    if (set(value) != {'schemaVersion', 'llvmCommit', 'wasiSdkCommit', 'basePatchSha256',
                       'profile', 'scope', 'target', 'tests'}
            or value['schemaVersion'] != SCHEMA or value['llvmCommit'] != LLVM
            or value['wasiSdkCommit'] != SDK or value['basePatchSha256'] != base.PATCH_SHA256
            or value['profile'] != PROFILE or tuple(value['tests']) != TESTS):
        raise ValueError('llvm-private-supplement-shape')
    base.manifest()  # The four original fixes remain a separately sealed input.
    target = value['target']
    if set(target) != {'path', 'original', 'originalIdentity', 'modified', 'modifiedIdentity'} or target['path'] != TARGET:
        raise ValueError('llvm-private-target-shape')
    for stage in ('original', 'modified'):
        data = target[stage].encode('utf-8')
        if not 0 < len(data) <= 1024 * 1024 or identity(data) != target[stage + 'Identity']:
            raise ValueError('llvm-private-target-identity')
    for row in value['tests'].values():
        if (set(row) != {'original', 'modified', 'bytes', 'sha256'} or row['original'] != 'absent'
                or not 0 < row['bytes'] <= 65536
                or identity(row['modified'].encode('utf-8')) != {k: row[k] for k in ('bytes', 'sha256')}):
            raise ValueError('llvm-private-test-identity')
    return value


def identities(stage: str) -> dict:
    if stage not in ('original', 'modified'):
        raise ValueError('llvm-private-stage')
    value = manifest()
    return {**base.identities(stage), TARGET: value['target'][stage + 'Identity'],
            **{name: ({'absent': True} if stage == 'original' else
                       {k: row[k] for k in ('bytes', 'sha256')})
               for name, row in value['tests'].items()}}


def _absent(source: Path, name: str) -> None:
    current = source
    for part in PurePosixPath(name).parts[:-1]:
        current /= part
        if (not stat.S_ISDIR(current.lstat().st_mode) or current.is_symlink()
                or current.is_junction()):
            raise ValueError('llvm-private-test-parent')
    try:
        (source / name).lstat()
    except FileNotFoundError:
        return
    raise ValueError('llvm-private-test-not-absent')


def check(source: Path, stage: str) -> dict:
    expected = identities(stage)
    actual = base.check(source, stage)
    actual[TARGET] = identity(regular(source, TARGET))
    for name in TESTS:
        if stage == 'original':
            _absent(source, name)
            actual[name] = {'absent': True}
        else:
            actual[name] = identity(regular(source, name, 65536))
    if actual != expected:
        raise ValueError('llvm-private-source-identity')
    return actual


def apply(source: Path) -> dict:
    value = manifest()
    before = check(source, 'original')  # ALL originals/absences before any write.
    base.apply(source)
    if regular(source, TARGET) != value['target']['original'].encode('utf-8'):
        raise ValueError('llvm-private-target-mutated')
    (source / TARGET).write_bytes(value['target']['modified'].encode('utf-8'))
    for name, row in value['tests'].items():
        _absent(source, name)
        with (source / name).open('xb') as destination:
            destination.write(row['modified'].encode('utf-8'))
    after = check(source, 'modified')
    return {'schemaVersion': SCHEMA, 'llvmCommit': LLVM, 'wasiSdkCommit': SDK,
            'patchSha256': PATCH_SHA256, 'basePatchSha256': base.PATCH_SHA256,
            'upstreamCommits': list(UPSTREAM), 'before': before, 'after': after}
