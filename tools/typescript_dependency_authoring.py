"""Exact npm candidate review and maintained frontend delegation; no implicit hooks."""
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
from tools.typescript_guest.project import validate_sdk_inputs

STATE = 'target/npm-dependency-authoring'
MAX_RECEIPT = 1024 * 1024


def candidate_location(project: Path, candidate: Path) -> Path:
    owner, app, _descriptor = layout(project, 'typescript')
    candidate = regular_path(Path(os.path.abspath(candidate)))
    if candidate.is_relative_to(owner) and not any(candidate.is_relative_to(root / 'target') for root in (owner, app)):
        raise DependencyError('npm-candidate-cannot-overwrite-reviewed-input')
    return candidate


def optional(root: Path, name: str) -> bytes | None:
    return read_bytes(root / name, inputs.MAX_LOCK) if os.path.lexists(root / name) else None


def source_files(app: Path) -> dict[str, bytes]:
    # Resolution always copies application sources into its own npm installation.
    # An ambient node_modules tree is never a source or SDK input.
    return snapshot(app, exclude=('node_modules',))


def seal(project: Path):
    owner, app, descriptor = layout(project, 'typescript')
    if owner != app and any(os.path.lexists(app / name) for name in (inputs.MANIFEST, inputs.LOCK)):
        raise DependencyError('dependency-frontend-ambiguous-application-lock')
    files = source_files(app)
    _lock, vendor, _pins = validate_sdk_inputs(files)
    return owner, app, (files['sdk-lock.json'], inventory(vendor), descriptor)


def unchanged(owner: Path, original) -> None:
    _owner, _app, observed = seal(owner)
    if observed != original:
        raise DependencyError('npm-authoring-sdk-or-descriptor-drift')


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
    graph = (app.relative_to(owner).as_posix() + '/' if app != owner else '') + 'npm-resolved.lock.json'
    if name not in {inputs.MANIFEST, inputs.LOCK, graph}:
        raise DependencyError('npm-authoring-edit-target')
    if len(raw) > inputs.MAX_LOCK:
        raise DependencyError('dependency-lock-limit')
    temporary = private / ('pending-' + secrets.token_hex(16))
    paths.write_new(temporary, raw)
    try:
        target = owner / name
        with paths.directory(target.parent) as destination, paths.directory(private) as source:
            if optional(owner, name) != previous:
                raise DependencyError('npm-authoring-concurrent-input-edit')
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
    value = inputs.validate_manifest(decode_json(declaration), 'typescript') if declaration is not None else None
    selected = value['selection'] if value else {}
    return {'manifestDigest': digest(declaration) if declaration is not None else None,
            'lockDigest': digest(lock) if lock is not None else None, 'sdkLockDigest': digest(sdk[0]),
            'selection': {key: selected[key] for key in ('target', 'runtimeProfile', 'conditions') if key in selected},
            'artifacts': [row['id'] for row in value['artifacts']] if value else []}


def current_application(app: Path, lock: dict) -> None:
    from tools.typescript_application_dependencies import native_lock, selection
    declaration = read_bytes(app / 'package.json')
    native_bytes = read_bytes(app / 'package-lock.json')
    native_lock(native_bytes)
    graph = decode_json(read_bytes(app / 'npm-resolved.lock.json', inputs.MAX_LOCK))
    selected = selection(lock['selection'])
    modules = [row for row in lock['artifacts'] if row['metadata'].get('assetType') == 'selected-node-modules']
    if len(modules) != 1 or modules[0]['format'] != 'directory' or modules[0]['role'] != 'application':
        raise DependencyError('npm-selected-module-tree-missing-or-ambiguous')
    if (not isinstance(graph, dict) or type(graph.get('formatVersion')) is not int or graph['formatVersion'] != 1
            or graph.get('selection') != selected
            or graph.get('originalManifestDigest') != digest(declaration)
            or graph.get('nativeLockDigest') != digest(native_bytes)
            or graph.get('filesDigest') != digest(canonical(modules[0]['files']))):
        raise DependencyError('npm-native-graph-or-declaration-drift-resolve-and-review')


def review(project: Path, candidate: Path, expected: str) -> dict:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise DependencyError('npm-candidate-review-digest-required')
    raw = read_bytes(regular_path(candidate), inputs.MAX_LOCK)
    if digest(raw) != expected:
        raise DependencyError('npm-candidate-review-drift')
    with transaction(project) as (owner, app, private, sdk):
        declaration = read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)
        value = inputs.validate_manifest(decode_json(declaration), 'typescript')
        previous = optional(owner, inputs.LOCK)
        with tempfile.TemporaryDirectory(prefix='npm-lock-review-', dir=private) as temporary:
            check = Path(temporary)
            (check / inputs.MANIFEST).write_bytes(declaration)
            (check / inputs.LOCK).write_bytes(raw)
            for name in value['nativeLocks']:
                target = check / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_bytes(owner / name))
            verified = inputs.verify_inputs(check, 'typescript', cache=owner / 'dependency-inputs/objects')
            if verified is None:
                raise DependencyError('npm-candidate-not-verified')
            current_application(app, verified.lock)
        if (read_bytes(candidate, inputs.MAX_LOCK) != raw
                or read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK) != declaration):
            raise DependencyError('npm-authoring-concurrent-input-edit')
        for row in verified.lock['nativeLocks']:
            if digest(read_bytes(owner / row['path'])) != row['digest']:
                raise DependencyError('dependency-native-lock-drift')
        current_application(app, verified.lock)
        replace(owner, private, inputs.LOCK, raw, previous, sdk)
        return {'formatVersion': 1, 'stage': 'npm-reviewed-lock', 'status': 'reviewed',
                'candidateDigest': expected, 'previousLockDigest': digest(previous) if previous is not None else None,
                **public(owner, sdk), 'capturedInputIdentity': verified.identity,
                'executableInputs': verified.lock['executableInputs'], 'compilerExecution': False,
                'frontendTrustRequired': True}


def status(project: Path) -> dict:
    owner, app, sdk = seal(project)
    from tools.typescript_generator_authoring import validate_generated_inputs
    validate_generated_inputs(source_files(app))
    verified = inputs.verify_inputs(owner, 'typescript')
    if verified is not None:
        current_application(app, verified.lock)
    return {'formatVersion': 1, 'stage': 'npm-dependency-status', 'status': 'verified' if verified else 'undeclared',
            **public(owner, sdk), 'capturedInputIdentity': verified.identity if verified else None,
            'executableInputs': verified.lock['executableInputs'] if verified else [], 'compilerExecution': False}


def resolved(project: Path, candidate: Path, lock: dict) -> dict:
    owner, app, sdk = seal(project)
    raw = read_bytes(candidate, inputs.MAX_LOCK)
    if decode_json(raw) != lock or digest(read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)) != lock['manifestDigest']:
        raise DependencyError('npm-candidate-resolution-drift')
    for row in lock['nativeLocks']:
        original = read_bytes(owner / row['path'])
        if len(original) != row['size'] or digest(original) != row['digest']:
            raise DependencyError('dependency-native-lock-drift')
    current_application(app, lock)
    return {'formatVersion': 1, 'stage': 'npm-resolution-capture', 'status': 'captured',
            'candidateDigest': digest(raw), **public(owner, sdk), 'executableInputs': lock['executableInputs'],
            'reviewRequired': True, 'compilerExecution': False, 'previousLockPreserved': True}


def record(project: Path, result: dict) -> Path:
    raw = canonical(result) + b'\n'
    if len(raw) > MAX_RECEIPT:
        raise DependencyError('npm-authoring-receipt-limit')
    with transaction(project) as (_owner, _app, private, _sdk):
        target = private / ('receipt-' + secrets.token_hex(16) + '.json')
        paths.write_new(target, raw)
        return target


def failure(operation: str, error: Exception) -> dict:
    from tools.dev_workflow.common import DevError
    code = error.code if isinstance(error, DevError) else str(error) if isinstance(error, DependencyError) else ''
    reason = code if re.fullmatch(r'[a-z][a-z0-9-]{0,127}', code) else 'npm-authoring-invalid-or-unavailable-input'
    return {'formatVersion': 1, 'stage': 'npm-' + operation, 'status': 'failed', 'reason': reason,
            'compilerExecution': False, 'automaticReplay': False}


def frontend(project: Path, action: str, *, workspace: str, state_root: Path | None = None,
             tool_root: str | None = None, selections: tuple[str, ...] = (), environment='node') -> list[str]:
    from tools.dev_workflow import common, dependencies, project as dev_project
    owner, _app, _sdk = seal(project)
    descriptor, _identity = dev_project.load(owner)
    common.require(descriptor['language'] == 'typescript', 'npm-authoring-project-language')
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
        raise DependencyError('npm-authoring-frontend-operation')
    return argv
