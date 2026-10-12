"""Reviewed C declarations and offline lock acceptance, separate from SDK locks."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import tempfile

from tools import application_dependencies as inputs
from tools.application_dependency_store import DependencyError, SHA, read_bytes, regular_path
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import decode_json
from tools.dev_workflow import paths, state

SDK_LOCK = 'sdk-lock.json'
STATE = 'target/c-dependency-authoring'
RECEIPT_LIMIT = 1024 * 1024


def layout(project: Path) -> tuple[Path, Path, bytes | None]:
    """Support both direct capsules and the maintained frontend's app subdirectory."""
    from tools.guest_dependency_inputs import layout as checked_layout
    checked_layout(project, 'c')
    root = regular_path(project)
    descriptor = root / 'latent.project.json'
    raw = read_bytes(descriptor, 256 * 1024) if os.path.lexists(descriptor) else None
    if raw is None:
        return root, root, None
    from tools.dev_workflow import common, project as dev_project
    value = dev_project.validate(common.decode(raw))
    if value['language'] != 'c':
        raise DependencyError('c-dependency-project-language')
    app = regular_path(root / value['build']['workingDirectory'])
    if not app.is_relative_to(root) or app == root:
        raise DependencyError('c-dependency-application-layout')
    return root, app, raw


def application_root(project: Path) -> Path:
    return layout(project)[1]


def sdk_identity(root: Path) -> tuple[Path, bytes, bytes | None]:
    _root, app, descriptor = layout(root)
    sdk = read_bytes(app / SDK_LOCK, inputs.MAX_LOCK)
    lock = decode_json(sdk)
    if not isinstance(lock, dict) or lock.get('language') != 'c':
        raise DependencyError('c-dependency-project-language')
    return app / SDK_LOCK, sdk, descriptor


def check_authority(root: Path, sdk: tuple[Path, bytes, bytes | None]) -> None:
    if (read_bytes(sdk[0], inputs.MAX_LOCK) != sdk[1]
            or read_optional(root, 'latent.project.json') != sdk[2]):
        raise DependencyError('c-dependency-concurrent-edit')


def build_inputs(app: Path) -> tuple[dict[str, bytes], Path]:
    """Bind the outer reviewed closure into the existing observed C source snapshot."""
    from tools.rust_capsule_project import MAX_FILE, MAX_FILES, MAX_SOURCE, snapshot
    from tools.guest_dependency_inputs import layout as checked_layout
    checked_layout(app, 'c')
    app = regular_path(app)
    files = snapshot(app)
    owner = app.parent
    if not os.path.lexists(owner / 'latent.project.json'):
        return files, app
    if not any(os.path.lexists(owner / name) for name in (inputs.MANIFEST, inputs.LOCK)):
        return files, app
    root, selected_app, descriptor = layout(owner)
    if selected_app != app:
        raise DependencyError('c-dependency-application-layout')
    if any(os.path.lexists(app / name) for name in (inputs.MANIFEST, inputs.LOCK)):
        raise DependencyError('c-dependency-ambiguous-application-lock')
    from tools.dev_workflow.dependencies import selected
    _binding, names = selected(root, 'c')
    # The lock and prepare receipt bind verified object bytes. Do not copy the
    # CAS into a compiler namespace or broaden the ordinary source-size bounds.
    captured = {'latent.project.json': descriptor}
    for name in names:
        if name != 'dependency-inputs/objects':
            captured[name] = read_bytes(root / name, MAX_FILE)
    for name, raw in captured.items():
        if name in files and files[name] != raw:
            raise DependencyError('c-dependency-source-input-collision')
        files[name] = raw
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_SOURCE:
        raise DependencyError('c-dependency-source-input-limit')
    return dict(sorted(files.items())), root


def manifest(value: dict) -> dict:
    if not isinstance(value, dict):
        raise DependencyError('dependency-manifest-version-or-language')
    try:
        inputs.validate_manifest(value, 'c')
    except (KeyError, TypeError):
        raise DependencyError('dependency-artifact-declaration') from None
    if (value['selection'].get('target', 'wasm32-wasi') != 'wasm32-wasi'
            or value['selection'].get('runtimeProfile', 'closed-synchronous-v1') != 'closed-synchronous-v1'):
        raise DependencyError('c-dependency-runtime-profile-not-installed')
    for artifact in value['artifacts']:
        if artifact['role'] not in {'application', 'resource', 'build-tool'}:
            raise DependencyError('c-dependency-role-not-application-input')
        if set(artifact['metadata']) & {'buildCommand', 'configure', 'compilerOptions', 'generator', 'plugins'}:
            raise DependencyError('c-executable-or-unobserved-build-options-denied')
    return value


def read_optional(root: Path, name: str) -> bytes | None:
    if not os.path.lexists(root / name):
        return None
    return read_bytes(root / name, inputs.MAX_LOCK)


def identity(raw: bytes | None) -> str | None:
    return None if raw is None else digest(raw)


def public_state(root: Path) -> dict:
    raw, lock = read_optional(root, inputs.MANIFEST), read_optional(root, inputs.LOCK)
    value = manifest(decode_json(raw)) if raw is not None else None
    return {'manifestDigest': identity(raw), 'lockDigest': identity(lock),
            'selection': copy.deepcopy(value['selection']) if value else {},
            'artifacts': [row['id'] for row in value['artifacts']] if value else [],
            'sdkLockDigest': digest(sdk_identity(root)[1])}


@contextmanager
def transaction(root: Path):
    root = regular_path(root)
    if not root.is_dir():
        raise DependencyError('c-dependency-project-unavailable')
    sdk = sdk_identity(root)
    private = regular_path(root / STATE)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state.lock(private, 'authoring.lock'):
        yield root, private, sdk


def replace(root: Path, private: Path, name: str, raw: bytes, before: bytes | None, sdk):
    if name not in {inputs.MANIFEST, inputs.LOCK} or len(raw) > inputs.MAX_LOCK:
        raise DependencyError('c-dependency-edit-target-or-limit')
    temporary = private / ('pending-' + secrets.token_hex(16))
    paths.write_new(temporary, raw)
    try:
        with paths.directory(root) as destination, paths.directory(private) as source:
            if read_optional(root, name) != before:
                raise DependencyError('c-dependency-concurrent-edit')
            check_authority(root, sdk)
            if os.name == 'nt':
                os.replace(temporary, root / name)
            else:
                os.replace(temporary.name, name, src_dir_fd=source, dst_dir_fd=destination)
                os.fsync(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def edit(project: Path, operation: str, artifacts: list[dict], identifiers: list[str], *, expected: str | None = None) -> dict:
    if operation not in {'add', 'update', 'remove'}:
        raise DependencyError('c-dependency-edit-operation')
    if not artifacts and operation != 'remove' or not identifiers and operation == 'remove':
        raise DependencyError('c-dependency-edit-input-required')
    if operation == 'update' and (len(artifacts) != 1 or len(identifiers) != 1):
        raise DependencyError('c-dependency-update-one-artifact-required')
    if operation == 'add' and identifiers or operation == 'remove' and artifacts:
        raise DependencyError('c-dependency-edit-input-invalid')
    with transaction(project) as (root, private, sdk):
        before = read_optional(root, inputs.MANIFEST)
        if expected is not None and (not SHA.fullmatch(expected) or identity(before) != expected):
            raise DependencyError('c-dependency-manifest-review-drift')
        value = manifest(decode_json(before)) if before is not None else {
            'formatVersion': 1, 'language': 'c', 'selection': {'target': 'wasm32-wasi'},
            'nativeLocks': [], 'artifacts': [], 'transformations': []}
        value = copy.deepcopy(value)
        declared = {row['id'] for row in value['artifacts']}
        if len(set(identifiers)) != len(identifiers) or not set(identifiers) <= declared:
            raise DependencyError('c-dependency-edit-artifact-missing-or-duplicate')
        if operation == 'add':
            value['artifacts'].extend(copy.deepcopy(artifacts))
        elif operation == 'update':
            if artifacts[0].get('id') != identifiers[0]:
                raise DependencyError('c-dependency-update-identity-use-explicit-add-remove')
            value['artifacts'] = [copy.deepcopy(artifacts[0]) if row['id'] == identifiers[0] else row
                                  for row in value['artifacts']]
        else:
            value['artifacts'] = [row for row in value['artifacts'] if row['id'] not in identifiers]
        manifest(value)
        encoded = canonical(value) + b'\n'
        old_lock = read_optional(root, inputs.LOCK)
        replace(root, private, inputs.MANIFEST, encoded, before, sdk)
        return {'formatVersion': 1, 'stage': 'c-dependency-' + operation, 'status': 'declarations-changed',
                'beforeManifestDigest': identity(before), **public_state(root),
                'reviewRequired': True, 'previousLockPreserved': read_optional(root, inputs.LOCK) == old_lock,
                'compilerExecution': False}


def resolve(project: Path, candidate: Path, *, repositories: dict | None = None) -> dict:
    candidate = regular_path(candidate)
    root = regular_path(project)
    if os.path.lexists(candidate):
        raise DependencyError('dependency-candidate-exists')
    if root in candidate.parents and not candidate.is_relative_to(root / 'target'):
        raise DependencyError('c-dependency-candidate-cannot-overwrite-reviewed-input')
    with transaction(project) as (root, _private, sdk):
        before = read_bytes(root / inputs.MANIFEST, inputs.MAX_LOCK)
        manifest(decode_json(before))
        lock_before = read_optional(root, inputs.LOCK)
        selected = inputs.capture(root, repositories=repositories)
        if read_bytes(root / inputs.MANIFEST, inputs.MAX_LOCK) != before:
            raise DependencyError('c-dependency-concurrent-edit')
        check_authority(root, sdk)
        raw = canonical(selected) + b'\n'
        if len(raw) > inputs.MAX_LOCK:
            raise DependencyError('dependency-lock-limit')
        paths.write_new(candidate, raw)
        return {'formatVersion': 1, 'stage': 'c-resolution-capture', 'status': 'candidate',
                'candidateDigest': digest(raw), **public_state(root), 'reviewRequired': True,
                'previousLockPreserved': read_optional(root, inputs.LOCK) == lock_before,
                'compilerExecution': False}


def review(project: Path, candidate: Path, expected: str) -> dict:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise DependencyError('c-dependency-candidate-review-digest-required')
    raw = read_bytes(candidate, inputs.MAX_LOCK)
    if digest(raw) != expected:
        raise DependencyError('c-dependency-candidate-review-drift')
    with transaction(project) as (root, private, sdk):
        declaration = read_bytes(root / inputs.MANIFEST, inputs.MAX_LOCK)
        value = manifest(decode_json(declaration))
        previous = read_optional(root, inputs.LOCK)
        # Verify against the real read-only store without changing the current
        # lock or copying the closure. Original feeds/source paths are unused.
        with tempfile.TemporaryDirectory(prefix='lsf-c-lock-review-', dir=private) as temporary:
            check = Path(temporary)
            (check / inputs.MANIFEST).write_bytes(declaration)
            (check / inputs.LOCK).write_bytes(raw)
            for name in value['nativeLocks']:
                path = check / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(read_bytes(root / name))
            verified = inputs.verify_inputs(check, 'c', cache=root / 'dependency-inputs/objects')
            if verified is None:
                raise DependencyError('c-dependency-candidate-not-verified')
        if (read_bytes(candidate, inputs.MAX_LOCK) != raw
                or read_bytes(root / inputs.MANIFEST, inputs.MAX_LOCK) != declaration):
            raise DependencyError('c-dependency-concurrent-edit')
        for row in verified.lock['nativeLocks']:
            if digest(read_bytes(root / row['path'])) != row['digest']:
                raise DependencyError('dependency-native-lock-drift')
        replace(root, private, inputs.LOCK, raw, previous, sdk)
        return {'formatVersion': 1, 'stage': 'c-dependency-reviewed-lock', 'status': 'reviewed',
                'previousLockDigest': identity(previous), 'candidateDigest': expected, **public_state(root),
                'capturedInputIdentity': verified.identity, 'compilerExecution': False,
                'executableInputs': verified.lock['executableInputs'], 'frontendTrustRequired': True}


def status(project: Path) -> dict:
    root = regular_path(project)
    sdk_identity(root)
    from tools.c_generator_authoring import validate_generated_inputs
    from tools.rust_capsule_project import snapshot
    validate_generated_inputs(snapshot(application_root(root)))
    public = public_state(root)
    verified = inputs.verify_inputs(root, 'c')
    return {'formatVersion': 1, 'stage': 'c-dependency-status', 'status': 'verified' if verified else 'undeclared',
            **public, 'capturedInputIdentity': verified.identity if verified else None,
            'executableInputs': verified.lock['executableInputs'] if verified else [], 'compilerExecution': False}


def failure(operation: str, error: Exception) -> dict:
    # No exception repr, source locations, URLs, command line or environment.
    from tools.dev_workflow.common import DevError
    code = error.code if isinstance(error, DevError) else str(error) if isinstance(error, DependencyError) else ''
    reason = code if re.fullmatch(r'[a-z][a-z0-9-]{0,127}', code) else 'c-dependency-invalid-or-unavailable-input'
    return {'formatVersion': 1, 'stage': 'c-dependency-' + operation, 'status': 'failed',
            'reason': reason, 'compilerExecution': False}


def record(project: Path, result: dict) -> Path:
    """Retain immutable, bounded public outcomes without recording feed secrets."""
    raw = canonical(result) + b'\n'
    if len(raw) > RECEIPT_LIMIT:
        raise DependencyError('c-dependency-receipt-limit')
    with transaction(project) as (_root, private, _sdk):
        receipt = private / ('receipt-' + secrets.token_hex(16) + '.json')
        paths.write_new(receipt, raw)
        return receipt


def frontend(project: Path, action: str, *, workspace: str, state_root: Path | None = None,
             tool_root: str | None = None, selections: tuple[str, ...] = (), environment='node') -> list[str]:
    from tools.dev_workflow import common, dependencies, project as dev_project
    root = regular_path(project)
    layout(root)
    descriptor, _ = dev_project.load(root)
    common.require(descriptor['language'] == 'c', 'c-dependency-project-language')
    dependencies.verify(root, descriptor)
    argv = ['--state-root', str(state_root)] if state_root is not None else []
    if action == 'test':
        argv += ['dev', 'test', '--workspace', workspace, '--project', str(root), '--environment', environment]
        for selected in selections:
            argv += ['--select', selected]
    elif action == 'watch':
        argv += ['dev', 'up', '--workspace', workspace, '--project', str(root), '--watch']
        if tool_root is not None:
            argv += ['--tool-root', tool_root]
        for selected in selections:
            argv += ['--test-select', selected]
    else:
        raise DependencyError('c-dependency-frontend-operation')
    return argv
