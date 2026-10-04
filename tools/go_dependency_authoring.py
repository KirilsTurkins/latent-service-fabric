"""Exact Go candidate review and maintained frontend delegation; no implicit generators."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import tempfile

from tools import application_dependencies as inputs
from tools.application_dependency_store import DependencyError, SHA, read_bytes, regular_path
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import paths, state
from tools.guest_dependency_inputs import layout
from tools.rust_capsule_project import decode_json, inventory, snapshot
from tools.go_capsule_project import validate_sdk_inputs

STATE = 'target/go-dependency-authoring'
MAX_RECEIPT = 1024 * 1024


def candidate_location(project: Path, candidate: Path) -> Path:
    owner, app, _descriptor = layout(project, 'go')
    candidate = regular_path(Path(os.path.abspath(candidate)))
    if candidate.is_relative_to(owner) and not any(candidate.is_relative_to(root / 'target') for root in (owner, app)):
        raise DependencyError('go-candidate-cannot-overwrite-reviewed-input')
    return candidate


def optional(root: Path, name: str) -> bytes | None:
    return read_bytes(root / name, inputs.MAX_LOCK) if os.path.lexists(root / name) else None


def source_files(app: Path) -> dict[str, bytes]:
    # Application/SDK sources are observed; native resolution uses a fresh owned
    # module cache and never an ambient module installation or go.work.
    return snapshot(app, exclude=())


def seal(project: Path):
    owner, app, descriptor = layout(project, 'go')
    if owner != app and any(os.path.lexists(app / name) for name in (inputs.MANIFEST, inputs.LOCK)):
        raise DependencyError('dependency-frontend-ambiguous-application-lock')
    files = source_files(app)
    _lock, vendor, _pins = validate_sdk_inputs(files)
    return owner, app, (files['sdk-lock.json'], inventory(vendor), descriptor)


def unchanged(owner: Path, original) -> None:
    _owner, _app, observed = seal(owner)
    if observed != original:
        raise DependencyError('go-authoring-sdk-or-descriptor-drift')


@contextmanager
def transaction(project: Path):
    owner, app, sdk = seal(project)
    private = regular_path(owner / STATE)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state.lock(private, 'authoring.lock'):
        unchanged(owner, sdk)
        yield owner, app, private, sdk


def replace(owner: Path, private: Path, name: str, raw: bytes, previous: bytes | None, sdk) -> None:
    paths.relative(name)
    _owner, app, _observed = seal(owner)
    graph = (app.relative_to(owner).as_posix() + '/' if app != owner else '') + 'go-resolved.lock.json'
    if name not in {inputs.MANIFEST, inputs.LOCK, graph}:
        raise DependencyError('go-authoring-edit-target')
    if len(raw) > inputs.MAX_LOCK:
        raise DependencyError('dependency-lock-limit')
    temporary = private / ('pending-' + secrets.token_hex(16))
    paths.write_new(temporary, raw)
    try:
        target = owner / name
        with paths.directory(target.parent) as destination, paths.directory(private) as source:
            if optional(owner, name) != previous:
                raise DependencyError('go-authoring-concurrent-input-edit')
            unchanged(owner, sdk)
            if os.name == 'nt':
                os.replace(temporary, target)
            else:
                os.replace(temporary.name, target.name, src_dir_fd=source, dst_dir_fd=destination)
                os.fsync(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def public(owner: Path, sdk) -> dict:
    declaration, lock = optional(owner, inputs.MANIFEST), optional(owner, inputs.LOCK)
    value = inputs.validate_manifest(decode_json(declaration), 'go') if declaration is not None else None
    selected = value['selection'] if value else {}
    return {'manifestDigest': digest(declaration) if declaration is not None else None,
            'lockDigest': digest(lock) if lock is not None else None, 'sdkLockDigest': digest(sdk[0]),
            'selection': {key: selected[key] for key in ('target', 'runtimeProfile', 'tags') if key in selected},
            'artifacts': [row['id'] for row in value['artifacts']] if value else []}


def current_application(app: Path, lock: dict) -> None:
    from tools.go_application_dependencies import selection, sums
    declaration = read_bytes(app / 'go.mod')
    native_bytes = read_bytes(app / 'go.sum')
    sums(native_bytes)
    graph = decode_json(read_bytes(app / 'go-resolved.lock.json', inputs.MAX_LOCK))
    selected = selection(lock['selection'])
    roots = [row for row in lock['artifacts'] if row['metadata'].get('assetType') == 'selected-root-module']
    caches = [row for row in lock['artifacts'] if row['metadata'].get('assetType') == 'selected-module-downloads']
    if (len(roots) != 1 or roots[0]['format'] != 'file' or len(roots[0]['files']) != 1
            or roots[0]['files'][0]['path'] != 'go.mod' or len(caches) != 1):
        raise DependencyError('go-selected-root-or-download-closure-missing')
    if (not isinstance(graph, dict) or type(graph.get('formatVersion')) is not int or graph['formatVersion'] != 1
            or graph.get('selection') != selected
            or graph.get('originalManifestDigest') != digest(declaration)
            or graph.get('nativeSumDigest') != digest(native_bytes)
            or graph.get('selectedManifestDigest') != roots[0]['files'][0]['digest']
            or roots[0]['original']['digest'] != digest(declaration)):
        raise DependencyError('go-native-graph-or-declaration-drift-resolve-and-review')
    nodes = graph.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 1024 or any(not isinstance(row, dict) for row in nodes):
        raise DependencyError('go-native-module-selection-ambiguous')
    main = [row for row in nodes if row.get('main') is True]
    modules = [row for row in lock['artifacts'] if row['metadata'].get('assetType') in {'local-module', 'selected-module-source'}]
    selected_nodes = [row for row in nodes if row.get('main') is False]
    if (len(main) != 1 or main[0].get('path') != graph.get('module')
            or len(selected_nodes) + 1 != len(nodes)
            or {row.get('id') for row in selected_nodes} != {row['id'] for row in modules}
            or len({row.get('id') for row in selected_nodes}) != len(selected_nodes)):
        raise DependencyError('go-native-module-selection-ambiguous')
    by_id = {row['id']: row for row in modules}
    for row in selected_nodes:
        artifact = by_id[row['id']]
        if (artifact['format'] != 'directory' or artifact['metadata'].get('module') != row.get('path')
                or artifact['metadata'].get('version') != row.get('version')):
            raise DependencyError('go-native-module-artifact-identity-mismatch')


def review(project: Path, candidate: Path, expected: str) -> dict:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise DependencyError('go-candidate-review-digest-required')
    raw = read_bytes(regular_path(candidate), inputs.MAX_LOCK)
    if digest(raw) != expected:
        raise DependencyError('go-candidate-review-drift')
    with transaction(project) as (owner, app, private, sdk):
        declaration = read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)
        value = inputs.validate_manifest(decode_json(declaration), 'go')
        previous = optional(owner, inputs.LOCK)
        with tempfile.TemporaryDirectory(prefix='go-lock-review-', dir=private) as temporary:
            check = Path(temporary)
            (check / inputs.MANIFEST).write_bytes(declaration)
            (check / inputs.LOCK).write_bytes(raw)
            for name in value['nativeLocks']:
                target = check / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_bytes(owner / name))
            verified = inputs.verify_inputs(check, 'go', cache=owner / 'dependency-inputs/objects')
            if verified is None:
                raise DependencyError('go-candidate-not-verified')
            current_application(app, verified.lock)
        if (read_bytes(candidate, inputs.MAX_LOCK) != raw
                or read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK) != declaration):
            raise DependencyError('go-authoring-concurrent-input-edit')
        for row in verified.lock['nativeLocks']:
            if digest(read_bytes(owner / row['path'])) != row['digest']:
                raise DependencyError('dependency-native-lock-drift')
        current_application(app, verified.lock)
        replace(owner, private, inputs.LOCK, raw, previous, sdk)
        return {'formatVersion': 1, 'stage': 'go-reviewed-lock', 'status': 'reviewed',
                'candidateDigest': expected, 'previousLockDigest': digest(previous) if previous is not None else None,
                **public(owner, sdk), 'capturedInputIdentity': verified.identity,
                'executableInputs': verified.lock['executableInputs'], 'compilerExecution': False,
                'frontendTrustRequired': True}


def status(project: Path) -> dict:
    owner, app, sdk = seal(project)
    verified = inputs.verify_inputs(owner, 'go')
    if verified is not None:
        current_application(app, verified.lock)
    return {'formatVersion': 1, 'stage': 'go-dependency-status', 'status': 'verified' if verified else 'undeclared',
            **public(owner, sdk), 'capturedInputIdentity': verified.identity if verified else None,
            'executableInputs': verified.lock['executableInputs'] if verified else [], 'compilerExecution': False}


def resolved(project: Path, candidate: Path, lock: dict) -> dict:
    owner, app, sdk = seal(project)
    raw = read_bytes(candidate, inputs.MAX_LOCK)
    if decode_json(raw) != lock or digest(read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)) != lock['manifestDigest']:
        raise DependencyError('go-candidate-resolution-drift')
    for row in lock['nativeLocks']:
        original = read_bytes(owner / row['path'])
        if len(original) != row['size'] or digest(original) != row['digest']:
            raise DependencyError('dependency-native-lock-drift')
    current_application(app, lock)
    return {'formatVersion': 1, 'stage': 'go-resolution-capture', 'status': 'captured',
            'candidateDigest': digest(raw), **public(owner, sdk), 'executableInputs': lock['executableInputs'],
            'reviewRequired': True, 'compilerExecution': False, 'previousLockPreserved': True}


def record(project: Path, result: dict) -> Path:
    raw = canonical(result) + b'\n'
    if len(raw) > MAX_RECEIPT:
        raise DependencyError('go-authoring-receipt-limit')
    with transaction(project) as (_owner, _app, private, _sdk):
        target = private / ('receipt-' + secrets.token_hex(16) + '.json')
        paths.write_new(target, raw)
        return target


def failure(operation: str, error: Exception) -> dict:
    from tools.dev_workflow.common import DevError
    code = error.code if isinstance(error, DevError) else str(error) if isinstance(error, DependencyError) else ''
    reason = code if re.fullmatch(r'[a-z][a-z0-9-]{0,127}', code) else 'go-authoring-invalid-or-unavailable-input'
    return {'formatVersion': 1, 'stage': 'go-' + operation, 'status': 'failed', 'reason': reason,
            'compilerExecution': False, 'automaticReplay': False}


def frontend(project: Path, action: str, *, workspace: str, state_root: Path | None = None,
             tool_root: str | None = None, selections: tuple[str, ...] = (), environment='node') -> list[str]:
    from tools.dev_workflow import common, dependencies, project as dev_project
    owner, _app, _sdk = seal(project)
    descriptor, _identity = dev_project.load(owner)
    common.require(descriptor['language'] == 'go', 'go-authoring-project-language')
    dependencies.verify(owner, descriptor)
    status(owner)
    argv = ['--state-root', str(state_root)] if state_root is not None else []
    if action == 'test':
        argv += ['dev', 'test', '--workspace', workspace, '--project', str(owner), '--environment', environment]
        for selected in selections:
            argv += ['--select', selected]
    elif action == 'watch':
        argv += ['dev', 'up', '--workspace', workspace, '--project', str(owner), '--watch']
        if tool_root is not None:
            argv += ['--tool-root', tool_root]
        for selected in selections:
            argv += ['--test-select', selected]
    else:
        raise DependencyError('go-authoring-frontend-operation')
    return argv
