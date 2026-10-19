"""Project declared immutable C dependency data from the verified capture only."""
from dataclasses import dataclass
from pathlib import Path

from tools import guest_resources
from tools.application_dependencies import Closure, LOCK, MANIFEST
from tools.application_dependency_store import read_bytes
from tools.build_snapshot import digest
from tools.rust_capsule_project import decode_json

RECIPE = ('tools/c_resource_inputs.py',)


@dataclass(frozen=True)
class Resources:
    rows: tuple[dict, ...]
    sources: dict[str, bytes]
    directories: tuple[Path, ...]
    observation: dict


def selected(closure: Closure | None, files: dict[str, bytes]) -> Resources:
    require = guest_resources.require
    if closure is None:
        return Resources((), {}, (), {'formatVersion': 1, 'resources': []})
    require(files.get(LOCK) == closure.lock_bytes and files.get(MANIFEST) == closure.manifest,
            'c-resource-source-lock-binding', 'denied')
    require(decode_json(closure.lock_bytes) == closure.lock, 'c-resource-lock-mutated', 'denied')
    rows, sources, directories, observed, total = [], {}, [], [], 0
    for artifact in closure.lock['artifacts']:
        if artifact['role'] != 'resource':
            continue
        metadata = artifact['metadata']
        declarations = metadata.get('resources', [])
        # Existing single-fragment declarations keep their exact captured text.
        if 'logicalPath' in metadata or 'mediaType' in metadata:
            require('resources' not in metadata and 'logicalPath' in metadata and 'mediaType' in metadata
                    and len(artifact['files']) == 1, 'c-resource-single-file-declaration')
            declarations = [{'path': metadata['logicalPath'], 'source': artifact['files'][0]['path'],
                             'mediaType': metadata['mediaType']}]
        require(isinstance(declarations, list) and len(declarations) <= guest_resources.MAX_COUNT,
                'resource-count-limit', 'exhausted')
        by_name = {item['path']: item for item in artifact['files']}
        root = closure.work / artifact['mount']
        for declaration in declarations:
            require(len(rows) < guest_resources.MAX_COUNT, 'resource-count-limit', 'exhausted')
            require(isinstance(declaration, dict) and set(declaration) == {'path', 'source', 'mediaType'},
                    'c-resource-declaration-schema')
            logical = guest_resources.name(declaration['path'])
            source = guest_resources.name(declaration['source'], 1024)
            media = guest_resources.media(declaration['mediaType'])
            require(source in by_name, 'c-resource-source-not-captured', 'denied')
            item = by_name[source]
            require(type(item['size']) is int and 0 <= item['size'] <= guest_resources.MAX_FILE,
                    'resource-byte-limit', 'exhausted')
            total += item['size']
            require(total <= guest_resources.MAX_TOTAL, 'resource-byte-limit', 'exhausted')
            path = root if artifact['format'] == 'file' else root / source
            data = read_bytes(path, guest_resources.MAX_FILE)
            require(len(data) == item['size'] and digest(data) == item['digest']
                    and data == closure.store.get(item['digest'], item['size']),
                    'c-resource-captured-bytes-changed', 'denied')
            staged = path.relative_to(closure.work).as_posix()
            require(staged not in files or files[staged] == data, 'c-resource-source-shadowed', 'denied')
            sources[staged] = data
            rows.append({'path': logical, 'source': staged, 'mediaType': media,
                         'digest': item['digest'], 'owner': artifact['id']})
            observed.append({'path': logical, 'source': staged, 'mediaType': media, 'owner': artifact['id'],
                             'digest': item['digest'], 'size': item['size']})
        if declarations:
            directory = root.parent if artifact['format'] == 'file' else root
            if directory not in directories:
                directories.append(directory)
    # Shared validation covers combined application/dependency aliases and bounds.
    guest_resources.select({**files, **sources}, additional_resources=rows)
    return Resources(tuple(rows), sources, tuple(directories), {
        'formatVersion': 1, 'profile': 'c-captured-compiled-resources-v1',
        'dependencyLockDigest': digest(closure.lock_bytes), 'resources': observed,
        'networkResolution': False, 'runtimeFilesystem': 'not-installed'})
