"""Create one empty snapshot leaf; native owners retain file and ancestry checks."""
from pathlib import Path
import os
import re

from .inputs import require
from .recovery import require_stopped_owner
from .restore_destination_roots import boundary, missing, private_directory, stamp


def provision(client, node, scope: Path, operation: str):
    """Provision a fresh operation-scoped root without reusing failed evidence."""
    require_stopped_owner(client, node)
    boundary(client)
    require(type(operation) is str
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', operation) is not None,
            'snapshot-directory-operation-identity')
    original_scope = stamp(private_directory(scope))
    root = scope / ('snapshot-' + operation)
    missing(root, scope)
    boundary(client)
    require(stamp(private_directory(scope)) == original_scope, 'snapshot-directory-scope-changed')
    root.mkdir(mode=0o700)
    created = stamp(private_directory(root))
    require(next(root.iterdir(), None) is None, 'empty-snapshot-directory')
    boundary(client)
    require(stamp(private_directory(scope)) == original_scope
            and stamp(private_directory(root)) == created, 'snapshot-directory-custody-changed')
    require(next(root.iterdir(), None) is None, 'empty-snapshot-directory')
    return root, {'schemaVersion': 'latent.java.snapshot-destination-directory.v1',
                  'operationId': operation, 'directoriesCreated': 1, 'durableFilesCreated': 0,
                  'posixModeObserved': os.name == 'posix', 'currentAuthorityInferred': False}
