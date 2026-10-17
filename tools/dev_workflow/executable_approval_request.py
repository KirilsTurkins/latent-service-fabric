"""Explicit private observation of the last owned, failed Rust approval request.

The caller holds the workspace and build-control locks. This operation never
approves execution, selects an arbitrary attempt, or writes project/state data.
"""
from pathlib import Path

from . import build, build_cache, build_control, paths, project, snapshot, state, tool_inventory
from .common import decode, digest, integer, members, require, sha
from .executable_approval import maintained

MAX_REQUEST = 1024 * 1024
MAX_METADATA = 4 * 1024 * 1024
PROFILE = 'linux-captured-compiler-namespaces-v1'


def _file(value, name=None, maximum=512 * 1024 * 1024):
    members(value, {'digest', 'size'} | ({'name'} if name is not None else set()))
    sha(value['digest'])
    integer(value['size'], 0, maximum)
    if name is not None:
        require(value['name'] == name and value['size'] > 0, 'executable-request-compiler-file')


def _compiler(value):
    members(value, {'formatVersion', 'profile', 'distributions', 'tools', 'sandbox', 'loaderObserver',
                    'hostRuntimeLibraries', 'network', 'ambientHome', 'credentials', 'boundary'},
            {'loaderLibraryDirectories'})
    require(type(value['formatVersion']) is int and value['formatVersion'] == 1
            and value['profile'] == PROFILE and value['network'] == 'denied'
            and value['ambientHome'] == 'absent' and value['credentials'] == 'not-inherited'
            and value['boundary'] == 'trusted-single-user-compiler-host-not-hardened-multitenant-vm',
            'executable-request-compiler-profile')
    members(value['distributions'], {'rust-compiler-and-sysroot', 'zig-host-linker-and-sysroot'})
    for rows in value['distributions'].values():
        require(isinstance(rows, list) and 0 < len(rows) <= 32768, 'executable-request-distribution-limit')
        names, total = set(), 0
        for row in rows:
            members(row, {'path', 'digest', 'size'})
            name = paths.relative(row['path'])
            require(name not in names, 'executable-request-distribution-duplicate')
            names.add(name)
            _file({key: row[key] for key in ('digest', 'size')})
            total += row['size']
        require(total <= 2 * 1024**3, 'executable-request-distribution-byte-limit')
    members(value['tools'], {'cargo', 'rustc', 'wasm-tools', 'wit-bindgen', 'zig', 'shell', 'linker'})
    for name, row in value['tools'].items():
        _file(row, name)
    _file(value['sandbox'], 'build-sandbox')
    _file(value['loaderObserver'], 'loader-dependency-observer')
    libraries = value['hostRuntimeLibraries']
    require(isinstance(libraries, dict) and len(libraries) <= 1024, 'executable-request-library-limit')
    for name, row in libraries.items():
        require(isinstance(name, str) and len(name) <= 1024 and name.startswith(('/lib/', '/lib64/', '/usr/lib/')),
                'executable-request-library-path')
        paths.relative(name.lstrip('/'))
        _file(row, 'compiler-host-library', 64 * 1024 * 1024)
    if 'loaderLibraryDirectories' in value:
        rows = value['loaderLibraryDirectories']
        require(isinstance(rows, list) and 0 < len(rows) <= 8, 'executable-request-loader-limit')
        for row in rows:
            members(row, {'distribution', 'path'})
            require(row['distribution'] in value['distributions'], 'executable-request-loader-owner')
            paths.relative(row['path'])
    return value


def _producer(working, attempt, descriptor):
    from tools.build_snapshot import canonical
    from tools.guest_dependency_inputs import capture_source
    from tools.rust_capsule_build import RECIPE
    from tools.rust_capsule_project import inventory

    raw = paths.read(attempt, 'tool-inventory.json', tool_inventory.MAX_DOCUMENT)
    require(digest(raw) == descriptor['build']['inventory']['sha256'], 'guest-tool-inventory-digest')
    selected = tool_inventory.validate(decode(raw, tool_inventory.MAX_DOCUMENT), 'rust', 544, 'linux-x86_64',
                                       host_abi=descriptor['hostAbi'])
    require(selected['sourceCommit'] == descriptor['template']['revision'], 'guest-tool-template-revision-mismatch')
    files = {row['path']: row for row in selected['files']}
    for tool in descriptor['build']['tools']:
        require(tool['path'] in files and tool['sha256'] == files[tool['path']]['sha256'],
                'recipe-tool-outside-inventory')
    output = descriptor['build']['outputRoot'] + '/'
    recipe_raw = paths.read(working, output + 'recipe-inputs.json', MAX_METADATA)
    recipe = decode(recipe_raw, MAX_METADATA)
    names = set(RECIPE) | {'examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json'}
    members(recipe, names)
    for name, row in recipe.items():
        paths.relative(name)
        _file(row)
        pinned = files.get('recipe/' + name)
        require(pinned is not None and row == {'digest': pinned['sha256'], 'size': pinned['size']},
                'executable-request-recipe-input-mismatch')
    require(recipe_raw == canonical(recipe), 'executable-request-recipe-input-format')
    source_raw = paths.read(working, output + 'source-inputs.json', MAX_METADATA)
    # Recompute the actual Rust producer projection, including the unchanged
    # outer descriptor and SDK lock. Detached selection never enters it.
    observed = capture_source(working / descriptor['build']['workingDirectory'], 'rust')
    require(source_raw == inventory(observed.files), 'executable-request-source-input-mismatch')
    compiler_raw = paths.read(working, output + 'rust-compiler-inputs.json', MAX_METADATA)
    compiler = _compiler(decode(compiler_raw, MAX_METADATA, maximum_items=300000))
    for tool in descriptor['build']['tools']:
        if tool['name'] in compiler['tools']:
            require(compiler['tools'][tool['name']]['digest'] == tool['sha256'],
                    'executable-request-compiler-tool-mismatch')
    return digest(canonical({'recipe': digest(recipe_raw), 'sourceSnapshot': digest(source_raw)})), compiler


def read(root: Path) -> dict:
    from tools import application_dependencies
    from tools.application_dependency_approval import request
    from tools.build_snapshot import canonical
    from types import SimpleNamespace

    active = build_control.status(root)
    require(active['state'] == 'reaped' and active.get('attempt') is not None,
            'executable-request-requires-failed-reaped-build')
    attempt = root / 'builds' / active['attempt']
    owner = build_cache.owner(attempt)
    require(owner['state'] == 'failed', 'executable-request-requires-failed-reaped-build')
    saved = members(state.load(root, 'project.json'), {'descriptor', 'trust', 'source', 'snapshot'})
    descriptor = project.validate(saved['descriptor'])
    require(maintained(descriptor) and owner['recipe'] == saved['trust'] == project.trust_identity(descriptor)
            and owner['source'] == saved['snapshot'], 'executable-request-source-or-trust-mismatch')
    sha(saved['snapshot'])
    source = root / 'snapshots' / saved['snapshot'][7:]
    require(saved['source'] == str(source), 'executable-request-snapshot-owner')
    record = decode(paths.read(source, 'snapshot.json'))
    snapshot.validate(record)
    require(record['identity'] == saved['snapshot'], 'executable-request-source-or-trust-mismatch')
    working = attempt / 'source'
    require(decode(paths.read(working, 'snapshot.json')) == record, 'executable-request-source-or-trust-mismatch')
    with paths.directory(attempt), paths.directory(source), paths.directory(working):
        build.unchanged(source, descriptor, record)
        build.unchanged(working, descriptor, record)
        recipe, compiler = _producer(working, attempt, descriptor)
        verified = application_dependencies.verify_inputs(working, 'rust')
        require(verified is not None and verified.lock['executableInputs'], 'executable-request-no-executable-inputs')
        raw = paths.read(working, descriptor['build']['outputRoot'] + '/executable-input-approval-request.json', MAX_REQUEST)
        value = members(decode(raw, MAX_REQUEST), {'formatVersion', 'identity', 'specification'})
        require(type(value['formatVersion']) is int and value['formatVersion'] == 1,
                'executable-request-version')
        sha(value['identity'])
        # Reuse the actual producer's complete schema and input selection. A
        # canonical hash by itself is never proof of an executable closure.
        expected = request(verified, SimpleNamespace(receipt=compiler), recipe)
        require(canonical(value['specification']) == canonical(expected) and value['identity'] == digest(canonical(expected)),
                'executable-request-producer-mismatch')
        build.unchanged(source, descriptor, record)
        build.unchanged(working, descriptor, record)
        require(build_control.status(root) == active and state.load(root, 'project.json') == saved
                and build_cache.owner(attempt) == owner, 'executable-request-owner-changed')
        return {'attempt': attempt.name, 'source': saved['snapshot'], 'trustedRecipe': saved['trust'],
                'request': value, 'executionApproved': False}
