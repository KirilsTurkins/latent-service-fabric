"""Copy stopped catalog custody for a fresh v2 installation; grant no authority."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import re
import stat
import time

from .inputs import require
from .native_store import identity
from .recovery import require_stopped_owner

MAX_ENTRIES = 4096
MAX_FILE_BYTES = 268435456
MAX_LOGICAL_BYTES = 1073741824
RESTORED_STORE_IDENTITY = 'java-transaction-restored-qualification'


def store_identity(value):
    require(type(value) is str and re.fullmatch(r'[A-Za-z0-9._-]{1,128}', value) is not None,
            'canonical-restore-store-identity')
    return value


def requested_identity(original: dict):
    state = original.get('state')
    require(isinstance(state, dict) and type(state.get('formatVersion')) is int
            and state['formatVersion'] == 2 and 'stateRoot' not in state,
            'explicit-current-v2-restore-configuration')
    if 'storeIdentity' not in state:
        return None
    source = store_identity(state['storeIdentity'])
    require(source != RESTORED_STORE_IDENTITY, 'distinct-restore-store-identity')
    return RESTORED_STORE_IDENTITY


def directory(path: Path):
    require(isinstance(path, Path) and path.is_absolute() and len(str(path)) <= 4096
            and '..' not in path.parts and path.resolve(strict=True) == path
            and not path.is_symlink(), 'canonical-restore-catalog-directory')
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode)
            and (not hasattr(os, 'geteuid') or info.st_uid == os.geteuid()),
            'owned-restore-catalog-directory')
    return info


def selection(original: dict, data_root: Path, checkpoint_root: Path, *, identity=None) -> dict:
    directory(data_root)
    directory(checkpoint_root)
    state = original.get('state')
    require(isinstance(state, dict) and type(state.get('formatVersion')) is int
            and state['formatVersion'] == 2 and 'stateRoot' not in state,
            'explicit-current-v2-restore-configuration')
    business_root = data_root / 'state'
    directory(business_root)
    require(not checkpoint_root.is_relative_to(business_root)
            and not business_root.is_relative_to(checkpoint_root),
            'independently-protected-restore-checkpoint')
    selected = copy.deepcopy(original)
    selected['dataDirectory'] = str(data_root)
    selected['state']['checkpointRoot'] = str(checkpoint_root)
    selected['state']['createIfMissing'] = False
    if identity is not None:
        selected['state']['storeIdentity'] = store_identity(identity)
    return selected


def catalogs(client, node, source: Path, destination: Path, checkpoint_root: Path) -> dict:
    require_stopped_owner(client, node)
    before_root = directory(source)
    parent = directory(destination.parent)
    require(os.name != 'posix' or (before_root.st_mode | parent.st_mode) & 0o077 == 0,
            'private-restore-catalog-roots')
    require(destination.is_absolute() and destination.resolve() == destination
            and len(str(destination)) <= 4096 and '..' not in destination.parts
            and not destination.exists() and not destination.is_symlink()
            and not destination.is_relative_to(source)
            and not source.is_relative_to(destination), 'fresh-restore-catalog-root')
    checkpoint = checkpoint_root.resolve(strict=True)
    directory(checkpoint)
    excluded = [source / 'state']
    if checkpoint.is_relative_to(source):
        excluded.append(checkpoint)
    entries, directories, pending, logical = {}, [], [source], 0
    scanned_directories = {}
    while pending:
        current = pending.pop()
        client.cancellation.check()
        require(time.monotonic() < client.deadline, 'restore-catalog-deadline')
        scanned_directories[current.relative_to(source)] = directory(current)
        for path in sorted(current.iterdir()):
            if any(path == prefix or path.is_relative_to(prefix) for prefix in excluded):
                continue
            relative = path.relative_to(source)
            require(len(relative.as_posix().encode()) <= 512 and len(relative.parts) <= 16
                    and not any(ord(char) < 32 or ord(char) == 127 for char in relative.as_posix()),
                    'restore-catalog-path-bound')
            info = path.lstat()
            require(not path.is_symlink() and not (getattr(info, 'st_file_attributes', 0) & 0x400)
                    and (not hasattr(os, 'geteuid') or
                         (info.st_uid, info.st_gid) == (before_root.st_uid, before_root.st_gid)),
                    'restore-catalog-owned-nonsymlink-entry')
            if stat.S_ISDIR(info.st_mode):
                directories.append(relative)
                pending.append(path)
            else:
                require(stat.S_ISREG(info.st_mode) and 0 < info.st_nlink <= MAX_ENTRIES
                        and info.st_size <= MAX_FILE_BYTES, 'restore-catalog-regular-file-bound')
                logical += info.st_size
                entries[relative] = info
            require(len(entries) + len(directories) <= MAX_ENTRIES
                    and logical <= MAX_LOGICAL_BYTES, 'restore-catalog-observation-bound')
    groups = {}
    for relative, info in entries.items():
        groups.setdefault((info.st_dev, info.st_ino), []).append(relative)
    for group in groups.values():
        require(len(group) == entries[group[0]].st_nlink,
                'restore-catalog-links-must-remain-inside-copied-custody')
    destination.mkdir(mode=0o700)
    for relative in sorted(directories, key=lambda path: (len(path.parts), path.as_posix())):
        (destination / relative).mkdir(mode=0o700)
    copied, distinct_bytes = {}, 0
    for relative, info in entries.items():
        client.cancellation.check()
        require(time.monotonic() < client.deadline, 'restore-catalog-deadline')
        key = (info.st_dev, info.st_ino)
        target = destination / relative
        if key in copied:
            os.link(copied[key], target)
            continue
        descriptor = os.open(source / relative, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb', buffering=0) as original, target.open('xb') as retained:
            opened = os.fstat(original.fileno())
            require(identity(opened) == identity(info), 'restore-catalog-source-replaced')
            total = 0
            while chunk := original.read(65536):
                client.cancellation.check()
                require(time.monotonic() < client.deadline, 'restore-catalog-deadline')
                total += len(chunk)
                require(total <= info.st_size, 'restore-catalog-source-growth')
                retained.write(chunk)
            require(total == info.st_size and identity(os.fstat(original.fileno())) == identity(info),
                    'restore-catalog-source-changed')
            retained.flush()
            os.fsync(retained.fileno())
        target.chmod(stat.S_IMODE(info.st_mode))
        copied[key] = target
        distinct_bytes += info.st_size
    require(identity(source.stat()) == identity(before_root)
            and all(identity((source / relative).lstat()) == identity(info)
                    for relative, info in scanned_directories.items())
            and all(identity((source / relative).lstat()) == identity(info)
                    for relative, info in entries.items()), 'restore-catalog-custody-changed')
    require(not (destination / 'state').exists(), 'restore-state-created-only-by-native-stage')
    return {'schemaVersion': 'latent.java.restore-catalog-custody.v1',
            'files': len(entries), 'directories': len(directories),
            'logicalBytes': logical, 'distinctBytes': distinct_bytes,
            'sourceStateCopied': False, 'sourceCheckpointCopied': False,
            'currentAuthorityInferred': False}
