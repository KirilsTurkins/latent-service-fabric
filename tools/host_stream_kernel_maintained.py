"""Authenticate maintained source data without building or enabling a kernel."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import paths

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'research/standard-outbound/linux-6.12-lineage/maintained-source-6.12.113.json'
MANIFEST_SHA = '551b4157660f6f63adc90bbc39b1d5d8ba71e5444044f598ef9abdfea9fb7960'
COMMIT = '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e'
MAX_ARCHIVE = 256 * 1024**2
MAX_FILE = 4 * 1024**2
MAX_SELECTED = 16 * 1024**2


def require(condition, reason):
    if not condition:
        raise ValueError('maintained-kernel-' + reason)


def manifest():
    raw = paths.read(ROOT, MANIFEST, 65536)
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, 'manifest-byte-identity')
    value = json.loads(raw)
    require(value['version'] == '6.12.113' and value['commit'] == COMMIT
        and len(value['source']) == 71 and value['selectedBytes'] == 5117172,
        'selected-source-envelope')
    require(value['kernelBuilt'] is value['configurationResolved'] is value['productionInstallation'] is False
        and value['completeAllocationClosure'] is False
        and value['imageIdentity'] is value['btfIdentity'] is None, 'unqualified-source-only')
    return value


def authenticate_files(selected, expected):
    require(set(selected) == set(expected), 'selected-source-membership')
    total = 0
    for name, row in expected.items():
        raw = selected[name]
        require(type(raw) is bytes and len(raw) == row['bytes'] and 0 < len(raw) <= MAX_FILE,
            'selected-file-bound')
        total += len(raw)
        require(total <= MAX_SELECTED, 'selected-total-bound')
        require(hashlib.sha256(raw).hexdigest() == row['sha256']
            and hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['gitBlob'],
            'selected-file-byte-identity')
    return total


def extra_selection(names, expected):
    require(type(names) is tuple and len(names) <= 32 and len(set(names)) == len(names), 'extra-source-bound')
    for name in names:
        require(type(name) is str and paths.relative(name) == name and name not in expected,
            'extra-source-path-or-duplicate')
    return frozenset(names)


def selected_members(source, expected, prefix, count, expanded_bytes, check, extra_sources=()):
    """Never extract links or use archive names as output paths."""
    extras = extra_selection(extra_sources, expected)
    selected, seen, expanded, selected_bytes = {}, set(), 0, 0
    for member in source:
        check()
        name = PurePosixPath(member.name)
        require(not name.is_absolute() and '..' not in name.parts and '\\' not in member.name
            and name.parts and name.parts[0] == prefix, 'archive-path')
        require(member.name not in seen and len(seen) < count, 'archive-membership')
        seen.add(member.name)
        expanded += member.size
        require(0 <= member.size and expanded <= expanded_bytes, 'archive-expanded-bound')
        relative = '/'.join(name.parts[1:])
        if relative not in expected and relative not in extras:
            continue
        require(member.isfile() and 0 < member.size <= MAX_FILE
            and relative not in selected, 'selected-member-type-or-bound')
        selected_bytes += member.size
        require(selected_bytes <= MAX_SELECTED, 'selected-total-bound')
        with source.extractfile(member) as stream:
            raw = stream.read(MAX_FILE + 1)
        require(len(raw) == member.size, 'selected-member-length')
        selected[relative] = raw
    require(len(seen) == count and expanded == expanded_bytes, 'archive-complete-membership')
    require(set(selected) == set(expected) | extras, 'selected-source-membership')
    authenticate_files({name: selected[name] for name in expected}, expected)
    return selected


def authenticate_archive(archive, value, extra_sources=()):
    extra_selection(extra_sources, value['source'])
    archive = paths.absolute(archive)
    deadline = time.monotonic() + 180
    def check():
        require(time.monotonic() < deadline, 'source-read-deadline')
    with paths.opened(archive.parent, archive.name) as descriptor:
        before = os.fstat(descriptor)
        require(before.st_size == value['archive']['bytes'] <= MAX_ARCHIVE, 'archive-byte-bound')
        checksum, used = hashlib.sha256(), 0
        while raw := os.read(descriptor, 1024 * 1024):
            check();used += len(raw)
            require(used <= MAX_ARCHIVE, 'archive-byte-bound')
            checksum.update(raw)
        require(used == before.st_size and checksum.hexdigest() == value['archive']['sha256'],
            'archive-byte-identity')
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(os.dup(descriptor), 'rb') as stream, tarfile.open(fileobj=stream, mode='r|xz') as source:
            selected = selected_members(source, value['source'], 'linux-' + value['version'],
                value['archive']['members'], value['archive']['expandedBytes'], check, extra_sources)
        after = os.fstat(descriptor)
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'archive-changed-during-read')
    check()
    return selected


def acquire(archive, output, extra_sources=()):
    value = manifest()
    selected = authenticate_archive(archive, value, extra_sources)
    output = paths.absolute(output)
    require(output != ROOT and ROOT not in output.parents, 'outside-checkout-output-required')
    paths.new_directory(output)
    for name, raw in selected.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        paths.write_new(target, raw)
    identities = {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'gitBlob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
        for name, raw in sorted(selected.items())}
    receipt = {'schemaVersion': 'lsf.maintained-kernel-source.v1', 'version': value['version'],
        'commit': COMMIT, 'manifestSha256': MANIFEST_SHA, 'archive': value['archive'],
        'selectedSource': identities, 'selectedBytes': sum(map(len, selected.values())),
        'originalGitCorroboratedFiles': sorted(value['source']),
        'extraSourceFilesFromExactArchive': list(extra_sources),
        'extraSourceFilesIndependentlyCorroborated': False,
        'kernelBuilt': False, 'configurationResolved': False, 'completeAllocationClosure': False,
        'productionInstallation': False, 'imageIdentity': None, 'btfIdentity': None,
        'historicalPreimagesChanged': False}
    paths.write_new(output / 'SOURCE-COMPLETE.json', (json.dumps(receipt, indent=2) + '\n').encode())
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--extra-source', action='append', default=[], help='Additional regular source from the same byte-authenticated archive (maximum32)')
    args = parser.parse_args()
    result = acquire(args.archive, args.output, tuple(args.extra_source))
    print(json.dumps({'version': result['version'], 'commit': result['commit'],
        'selectedFiles': len(result['selectedSource']), 'kernelBuilt': False}))
