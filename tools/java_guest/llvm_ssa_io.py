"""Finite private input/disk handling for the fixed LLVM compiler producer."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import tarfile
import time
import urllib.request

from tools.build_process import BuildProcessError

GIB = 1024 ** 3


def _capacity_read(path: Path, maximum: int) -> bytes:
    with path.open('rb') as source:
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('llvm-capacity-byte-limit')
    return raw


def host_capacity() -> dict:
    """Fixed Linux host facts, not a hard RSS quota or a memory-fit proof.

    Read the current cgroup and its bounded ancestor chain, so a child service
    limit cannot be mistaken for the host's advertised physical resources.
    Paths are kernel-reported, anchored below the one fixed cgroup mount, and
    never emitted. No caller selects a path, runner or resource fallback.
    """
    result = {'status': 'refused', 'reason': 'unreadable-or-unsupported',
              'minimumCpuMilli': 4000, 'minimumTotalBytes': 12 * GIB,
              'minimumAvailableBytes': 10 * GIB,
              'hardRssQuota': False, 'memoryFitQualified': False}
    try:
        affinity, process = len(os.sched_getaffinity(0)), os.process_cpu_count()
        if type(process) is not int or not 1 <= process <= 4096 or not 1 <= affinity <= 4096:
            return result
        result.update(affinityCpuCount=affinity, processCpuCount=process,
                      effectiveCpuMilli=1000 * min(affinity, process))
        mem = _capacity_read(Path('/proc/meminfo'), 65536)
        values = {}
        for label in (b'MemTotal', b'MemAvailable'):
            matches = re.findall(rb'^' + label + rb':[ ]+([0-9]{1,20}) kB$', mem, re.MULTILINE)
            if len(matches) != 1:
                return result
            values[label] = int(matches[0]) * 1024
        result.update(physicalTotalBytes=values[b'MemTotal'], physicalAvailableBytes=values[b'MemAvailable'],
                      effectiveTotalBytes=values[b'MemTotal'], effectiveAvailableBytes=values[b'MemAvailable'])
        group = _capacity_read(Path('/proc/self/cgroup'), 4096)
        match = re.fullmatch(rb'0::(/[^\n]*)\n?', group)
        if match is None:
            return result
        relative = PurePosixPath(match[1].decode('utf8'))
        parts = relative.parts[1:]
        if len(parts) > 32 or any(not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,255}', part)
                                 or part in {'.', '..'} for part in parts):
            return result
        base = Path('/sys/fs/cgroup')
        if base.is_symlink() or not base.is_dir():
            return result
        current = base
        chain = [base]
        for part in parts:
            current /= part
            if current.is_symlink() or not current.is_dir():
                return result
            chain.append(current)
        quota_levels = memory_levels = 0
        for directory in chain:
            for name in ('cpu.max', 'memory.max'):
                path = directory / name
                try:
                    if path.is_symlink():
                        return result
                    raw = _capacity_read(path, 4096).strip()
                except FileNotFoundError:
                    continue  # No limit is exposed by this controller here.
                if name == 'cpu.max':
                    fields = raw.split()
                    if len(fields) != 2 or not re.fullmatch(rb'[1-9][0-9]{0,19}', fields[1]):
                        return result
                    if fields[0] != b'max':
                        if not re.fullmatch(rb'[1-9][0-9]{0,19}', fields[0]):
                            return result
                        quota_levels += 1
                        result['effectiveCpuMilli'] = min(result['effectiveCpuMilli'],
                                                         int(fields[0]) * 1000 // int(fields[1]))
                elif raw != b'max':
                    if not re.fullmatch(rb'[1-9][0-9]{0,19}', raw):
                        return result
                    used_path = directory / 'memory.current'
                    if used_path.is_symlink():
                        return result
                    used = _capacity_read(used_path, 4096).strip()
                    if not re.fullmatch(rb'[0-9]{1,20}', used):
                        return result
                    memory_levels += 1
                    limit = int(raw)
                    result['effectiveTotalBytes'] = min(result['effectiveTotalBytes'], limit)
                    result['effectiveAvailableBytes'] = min(result['effectiveAvailableBytes'],
                                                            max(0, limit - int(used)))
        result.update(cgroupLevels=len(chain), cpuQuotaLevels=quota_levels, memoryLimitLevels=memory_levels)
        if result['effectiveCpuMilli'] < 4000:
            result['reason'] = 'insufficient-cpu'
        elif result['effectiveTotalBytes'] < 12 * GIB:
            result['reason'] = 'insufficient-memory-total'
        elif result['effectiveAvailableBytes'] < 10 * GIB:
            result['reason'] = 'insufficient-memory-available'
        else:
            result.update(status='admitted', reason='operational-preconditions-met')
    except (OSError, ValueError, OverflowError):
        pass
    return result
SDK_SOURCE = {
    'url': 'https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-29/wasi-sdk-29.0-x86_64-linux.tar.gz',
    'bytes': 119441678,
    'sha256': '87d1d1a2879d139cdc624b968efad3d4a97b8078cdff95e63ac88ecafd1a0171',
}
SDK_PREFIX = 'wasi-sdk-29.0-x86_64-linux'
MAX_ENTRIES = 200000
MAX_OWNED_BYTES = 16 * GIB
MAX_SINGLE_FILE = 2 * GIB
SOURCE_BYTES = 3 * GIB
SDK_BYTES = 2 * GIB
PRODUCT_BYTES = 2 * GIB
MINIMUM_FREE = 18 * GIB
FREE_RESERVE = 2 * GIB
SOURCES = {
    'sdk': {**SDK_SOURCE, 'prefix': SDK_PREFIX, 'maximumBytes': SDK_BYTES,
            'maximumEntries': 50000, 'maximumFile': 512 * 1024 ** 2},
    'llvm': {
        'url': 'https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.4/llvm-project-21.1.4.src.tar.xz',
        'bytes': 158939036, 'sha256': 'a01ad7e5167780c945871d75c0413081d12067607a6de5cf71dc3e8d1a82112c',
        'prefix': 'llvm-project-21.1.4.src', 'maximumBytes': SOURCE_BYTES,
        'maximumEntries': MAX_ENTRIES, 'maximumFile': 256 * 1024 ** 2,
        'tagObject': '82b2afbd3178f4517c922ec241ffe44c3323016b',
        'commit': '222fc11f2b8f25f6a0f4976272ef1bb7bf49521d',
    },
}


def fresh(path: Path) -> Path:
    if path.is_symlink() or path.is_junction() or path.exists() or not path.parent.is_dir():
        raise ValueError('llvm-producer-output-not-fresh')
    path.mkdir()
    return path.resolve(strict=True)


def tree_size(root: Path, maximum: int, *, entries: int = MAX_ENTRIES,
              deadline: float, signals=None, operational: bool = False) -> dict:
    """Strict inventory by default; only a live-build sample may lose entries."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError('llvm-producer-tree-root')
    count, total, pending = 0, 0, [root]
    while pending:
        directory = pending.pop()
        try:
            scan = os.scandir(directory)
        except FileNotFoundError:
            if operational and directory != root:
                continue
            raise
        with scan as rows:
            for row in rows:
                if signals is not None:
                    signals.check()
                if time.monotonic() >= deadline:
                    raise BuildProcessError('llvm-producer-deadline')
                try:
                    info = row.stat(follow_symlinks=False)
                except FileNotFoundError:
                    if operational:
                        continue
                    raise
                count += 1
                if count > entries:
                    raise BuildProcessError('llvm-producer-disk-entries')
                if Path(row.path).is_junction():
                    raise ValueError('llvm-producer-output-link')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(row.path))
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if info.st_size > MAX_SINGLE_FILE or total > maximum:
                        raise BuildProcessError('llvm-producer-disk-bytes')
                elif stat.S_ISLNK(info.st_mode):
                    # LLVM's trusted test sources and official SDK have link
                    # fixtures. Count the link itself; never traverse it here.
                    try:
                        link = os.readlink(row.path)
                    except FileNotFoundError:
                        if operational:
                            continue
                        raise
                    total += len(os.fsencode(link))
                    if total > maximum:
                        raise BuildProcessError('llvm-producer-disk-bytes')
                else:
                    raise BuildProcessError('llvm-producer-disk-kind')
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError('llvm-producer-tree-root')
    return {'entries': count, 'logicalBytes': total}


def preflight(parent: Path) -> None:
    if parent.is_symlink() or not parent.is_dir() or shutil.disk_usage(parent).free < MINIMUM_FREE:
        raise ValueError('llvm-producer-disk-preflight')


def case_sensitive(root: Path) -> None:
    """The Linux source carrier has legitimate case-distinct test members."""
    probe = fresh(root / 'case-probe')
    upper, lower = probe / 'Header', probe / 'header'
    try:
        with upper.open('xb') as stream:
            stream.write(b'A')
        try:
            with lower.open('xb') as stream:
                stream.write(b'B')
        except FileExistsError:
            raise ValueError('llvm-producer-case-sensitive-filesystem-required') from None
        if upper.read_bytes() != b'A' or lower.read_bytes() != b'B':
            raise ValueError('llvm-producer-case-sensitive-filesystem-required')
    finally:
        # Only these two fresh producer-owned probe files, never host cleanup.
        for path in (upper, lower):
            if path.exists():
                path.unlink()
        probe.rmdir()


class DiskCancellation:
    """Sample a trusted build's owned disk while the ORIGINAL process owner runs.

    This is an operational build budget, not an OS disk quota. A child can
    transiently cross it between scans. No service resource-accounting claim is
    made. The ten-second sampled check, reserve and strict post-cleanup check fail the
    producer; no host/system/cache deletion or competing reaper is installed.
    """
    def __init__(self, signals, root: Path, deadline: float):
        self.signals, self.root, self.deadline = signals, root, deadline
        self.next_scan = 0.0
        self.maximum_observed = 0

    def defer(self):
        return self.signals.defer()

    def check_after_exit(self):
        self.signals.check()

    def check(self):
        self.signals.check()
        now = time.monotonic()
        if now >= self.deadline:
            raise BuildProcessError('llvm-producer-deadline')
        if now < self.next_scan:
            return
        self.inspect(operational=True)
        self.next_scan = time.monotonic() + 10.0

    def inspect(self, *, operational: bool = False) -> dict:
        self.signals.check()
        if shutil.disk_usage(self.root).free < FREE_RESERVE:
            raise BuildProcessError('llvm-producer-disk-reserve')
        value = tree_size(self.root, MAX_OWNED_BYTES, deadline=self.deadline,
                          signals=self.signals, operational=operational)
        self.maximum_observed = max(self.maximum_observed, value['logicalBytes'])
        return value


def acquire(kind: str, target: Path, deadline: float) -> dict:
    """Only the two declared archives; authenticate them before any tar access."""
    if kind not in SOURCES:
        raise ValueError('llvm-producer-source-kind')
    source = SOURCES[kind]
    expires = min(deadline, time.monotonic() + 600)
    if time.monotonic() >= expires:
        raise ValueError('llvm-producer-acquisition-deadline')
    digest, count = hashlib.sha256(), 0
    with urllib.request.urlopen(source['url'], timeout=30) as response, target.open('xb') as output:
        if not response.geturl().startswith('https://'):
            raise ValueError('llvm-producer-acquisition-https')
        while True:
            if time.monotonic() >= expires:
                raise ValueError('llvm-producer-acquisition-deadline')
            chunk = response.read(min(65536, source['bytes'] - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > source['bytes']:
                raise ValueError('llvm-producer-acquisition-bytes')
            digest.update(chunk)
            output.write(chunk)
    value = {'bytes': count, 'sha256': digest.hexdigest()}
    if value != {key: source[key] for key in value}:
        raise ValueError('llvm-producer-acquisition-identity')
    return value


def validate_members(carrier, source: dict, target: Path, deadline: float) -> None:
    names, total = set(), 0
    for member in carrier:
        path = PurePosixPath(member.name)
        normalized = member.name.rstrip('/')
        if (time.monotonic() >= deadline or path.is_absolute() or '..' in path.parts
                or not path.parts or path.parts[0] != source['prefix'] or '\\' in member.name
                or path.as_posix() != normalized or normalized in names
                or not (member.isdir() or member.isfile() or member.issym() or member.islnk())):
            raise ValueError('llvm-producer-archive-member')
        names.add(normalized)
        total += member.size
        if (len(names) > source['maximumEntries'] or total > source['maximumBytes']
                or not 0 <= member.size <= source['maximumFile']):
            raise ValueError('llvm-producer-archive-bound')
        tarfile.data_filter(member, str(target))


def authenticate_archive(kind: str, archive: Path, deadline: float) -> dict:
    if kind not in SOURCES:
        raise ValueError('llvm-producer-source-kind')
    source = SOURCES[kind]
    if archive.is_symlink() or archive.stat().st_size != source['bytes']:
        raise ValueError('llvm-producer-archive-input')
    hasher = hashlib.sha256()
    with archive.open('rb') as stream:
        while chunk := stream.read(65536):
            if time.monotonic() >= deadline:
                raise ValueError('llvm-producer-extraction-deadline')
            hasher.update(chunk)
    if hasher.hexdigest() != source['sha256']:
        raise ValueError('llvm-producer-archive-identity')
    return {'bytes': archive.stat().st_size, 'sha256': hasher.hexdigest()}


def extract(kind: str, archive: Path, target: Path, deadline: float) -> Path:
    """Validate ALL bounded members before the first source extraction write."""
    authenticate_archive(kind, archive, deadline)
    source = SOURCES[kind]
    fresh(target)
    def filtered(member, destination):
        if time.monotonic() >= deadline:
            raise ValueError('llvm-producer-extraction-deadline')
        return tarfile.data_filter(member, destination)
    with tarfile.open(archive) as carrier:
        validate_members(carrier, source, target, deadline)
        carrier.extractall(target, filter=filtered)
    result = target / source['prefix']
    tree_size(result, source['maximumBytes'], entries=source['maximumEntries'], deadline=deadline)
    return result


def inventory(root: Path, maximum: int, deadline: float, *, source_links: bool = False,
              include_directories: bool = False) -> dict:
    """Hash the entire output closure, including anchored relative links."""
    tree_size(root, maximum, deadline=deadline)
    result = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            if time.monotonic() >= deadline:
                raise ValueError('llvm-producer-inventory-deadline')
            name = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                link = os.readlink(path)
                if source_links:
                    # Trusted source test fixtures may be dangling links. Bind
                    # their literal bytes without following them. All archive
                    # links were independently filtered before extraction.
                    resolved = posixpath.normpath(posixpath.join(PurePosixPath(name).parent.as_posix(), link))
                    outside = resolved == '..' or resolved.startswith('../')
                else:
                    outside = not path.resolve(strict=True).is_relative_to(root.resolve(strict=True))
                if os.path.isabs(link) or outside:
                    raise ValueError('llvm-producer-output-link')
                result[name] = {'link': link}
            elif stat.S_ISDIR(info.st_mode):
                if include_directories:
                    result[name] = {'directory': True}
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                digest, count = hashlib.sha256(), 0
                with path.open('rb') as stream:
                    while chunk := stream.read(65536):
                        if time.monotonic() >= deadline:
                            raise ValueError('llvm-producer-inventory-deadline')
                        count += len(chunk)
                        if count > MAX_SINGLE_FILE:
                            raise ValueError('llvm-producer-output-file')
                        digest.update(chunk)
                after = path.stat()
                if (count != info.st_size or (info.st_ino, info.st_size, info.st_mtime_ns)
                        != (after.st_ino, after.st_size, after.st_mtime_ns)):
                    raise ValueError('llvm-producer-output-mutated')
                result[name] = {'bytes': count, 'sha256': digest.hexdigest(),
                                'executable': bool(info.st_mode & 0o111)}
            else:
                raise ValueError('llvm-producer-output-kind')
    return dict(sorted(result.items()))


def source_identity(root: Path, deadline: float) -> dict:
    """Hash every source member, with no ignored/cache/path exclusions."""
    rows = inventory(root, SOURCE_BYTES, deadline, source_links=True, include_directories=True)
    hasher, total = hashlib.sha256(), 0
    for name, identity in rows.items():
        total += identity.get('bytes', len(os.fsencode(identity.get('link', ''))))
        # One canonical row at a time, avoiding a second full serialized tree.
        hasher.update((json.dumps([name, identity], sort_keys=True, separators=(',', ':')) + '\n').encode())
    return {'entries': len(rows), 'logicalBytes': total, 'sha256': hasher.hexdigest()}
