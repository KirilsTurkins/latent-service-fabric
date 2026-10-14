"""Provision empty restore directories; native owners alone create durable files.

Directory observations are descriptive custody, never restore approval, a
storage identity or a replacement for the native ProtectedRoot checks.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import time

from .inputs import require
from .recovery import require_stopped_owner
from .restore_installation import directory


def boundary(client):
    client.cancellation.check()
    require(time.monotonic() < client.deadline, 'restore-destination-root-deadline')


def stamp(info):
    return info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode


def private_directory(path):
    info = directory(path)
    require(not (getattr(info, 'st_file_attributes', 0) & 0x400)
            and (os.name != 'posix' or stat.S_IMODE(info.st_mode) == 0o700),
            'private-restore-destination-directory')
    return info


def missing(path, scope):
    require(isinstance(path, Path) and path.is_absolute() and len(str(path)) <= 4096
            and '..' not in path.parts and path.resolve() == path
            and path != scope and path.is_relative_to(scope)
            and not path.exists() and not path.is_symlink(),
            'fresh-scoped-restore-destination-root')
    try:
        path.lstat()
    except FileNotFoundError:
        return
    require(False, 'fresh-scoped-restore-destination-root')


def provision(client, node, scope: Path, business_root: Path, checkpoint_root: Path):
    """Create exactly two fresh empty 0700 leaves under the existing owner.

    No existing target is reused or removed. Failure retains any partially
    created directory as failed evidence and must stop the dependent action.
    Windows observations do not establish native POSIX mode qualification.
    """
    require_stopped_owner(client, node)
    boundary(client)
    owned_scope = stamp(private_directory(scope))
    roots = (business_root, checkpoint_root)
    require(all(isinstance(path, Path) for path in roots)
            and not business_root.is_relative_to(checkpoint_root)
            and not checkpoint_root.is_relative_to(business_root),
            'independent-restore-destination-roots')
    parents = {}
    for path in roots:
        missing(path, scope)
        parents[path.parent] = stamp(private_directory(path.parent))
    created = {}
    for path in roots:
        boundary(client)
        require(stamp(private_directory(scope)) == owned_scope,
                'restore-destination-scope-changed')
        require(stamp(private_directory(path.parent)) == parents[path.parent],
                'restore-destination-parent-changed')
        missing(path, scope)
        path.mkdir(mode=0o700)
        created[path] = stamp(private_directory(path))
        require(next(path.iterdir(), None) is None, 'empty-restore-destination-root')
    boundary(client)
    require(stamp(private_directory(scope)) == owned_scope,
            'restore-destination-scope-changed')
    for path in roots:
        require(stamp(private_directory(path)) == created[path]
                and stamp(private_directory(path.parent)) == parents[path.parent],
                'restore-destination-custody-changed')
        require(next(path.iterdir(), None) is None, 'empty-restore-destination-root')
    return {'schemaVersion': 'latent.java.restore-destination-directories.v1',
            'directoriesCreated': 2, 'durableFilesCreated': 0,
            'posixModeObserved': os.name == 'posix', 'currentAuthorityInferred': False}
