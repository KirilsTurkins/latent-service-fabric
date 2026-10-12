"""Review captured Cargo inputs without mutating immutable SDK or executing hooks."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import tempfile
import tomllib

from tools import application_dependencies as inputs
from tools.application_dependency_store import DependencyError, SHA, read_bytes, regular_path
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import paths, state
from tools.guest_dependency_inputs import layout
from tools.rust_capsule_project import decode_json, inventory, snapshot

STATE = 'target/rust-dependency-authoring'
MAX_RECEIPT = 1024 * 1024


def candidate_location(project: Path, candidate: Path) -> Path:
    root, app, _descriptor = layout(project, 'rust')
    # Normalize lexical traversal without following any filesystem links.
    candidate = regular_path(Path(os.path.abspath(candidate)))
    if candidate.is_relative_to(root) and not any(candidate.is_relative_to(owner / 'target') for owner in (root, app)):
        raise DependencyError('cargo-candidate-cannot-overwrite-reviewed-input')
    return candidate


def optional(root: Path, name: str) -> bytes | None:
    return read_bytes(root / name, inputs.MAX_LOCK) if os.path.lexists(root / name) else None


def seal(project: Path):
    from tools.rust_capsule_build import validate_sdk_inputs
    root, app, descriptor = layout(project, 'rust')
    if root != app and any(os.path.lexists(app / name) for name in (inputs.MANIFEST, inputs.LOCK)):
        raise DependencyError('dependency-frontend-ambiguous-application-lock')
    files = snapshot(app)
    if not {'sdk-lock.json', 'rust-toolchain.toml'} <= files.keys():
        raise DependencyError('cargo-authoring-incomplete-sdk')
    _pins, vendor = validate_sdk_inputs(files)
    return root, app, (files['sdk-lock.json'], files['rust-toolchain.toml'], inventory(vendor), descriptor)


def unchanged(root: Path, original) -> None:
    _root, _app, observed = seal(root)
    if observed != original:
        raise DependencyError('cargo-authoring-sdk-or-descriptor-drift')


@contextmanager
def transaction(project: Path):
    root, app, sdk = seal(project)
    private = regular_path(root / STATE)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state.lock(private, 'authoring.lock'):
        unchanged(root, sdk)
        yield root, app, private, sdk


def replace(root: Path, private: Path, name: str, raw: bytes, previous: bytes | None, sdk) -> None:
    paths.relative(name)
    _owner, app, _identity = seal(root)
    graph = ((app.relative_to(root).as_posix() + '/') if app != root else '') + 'cargo-resolved.lock.json'
    if name not in {inputs.MANIFEST, inputs.LOCK, graph}:
        raise DependencyError('cargo-authoring-edit-target')
    if len(raw) > inputs.MAX_LOCK:
        raise DependencyError('dependency-lock-limit')
    temporary = private / ('pending-' + secrets.token_hex(16))
    paths.write_new(temporary, raw)
    try:
        target = root / name
        with paths.directory(target.parent) as destination, paths.directory(private) as source:
            if optional(root, name) != previous:
                raise DependencyError('cargo-authoring-concurrent-input-edit')
            unchanged(root, sdk)
            if os.name == 'nt':
                os.replace(temporary, target)
            else:
                os.replace(temporary.name, target.name, src_dir_fd=source, dst_dir_fd=destination)
                os.fsync(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def public(root: Path, sdk) -> dict:
    manifest, lock = optional(root, inputs.MANIFEST), optional(root, inputs.LOCK)
    value = inputs.validate_manifest(decode_json(manifest), 'rust') if manifest is not None else None
    selection = value['selection'] if value is not None else {}
    # The native resolver already closes these fields. Do not reflect arbitrary
    # application metadata or source/credential locations into public outcomes.
    selected = {key: selection[key] for key in ('target', 'runtimeProfile', 'features', 'allFeatures', 'noDefaultFeatures')
                if key in selection}
    return {'manifestDigest': digest(manifest) if manifest is not None else None,
            'lockDigest': digest(lock) if lock is not None else None, 'sdkLockDigest': digest(sdk[0]),
            'selection': selected, 'artifacts': [row['id'] for row in value['artifacts']] if value else []}


def current_application(app: Path, lock: dict) -> None:
    """A review cannot approve a graph resolved for a different Cargo manifest."""
    roots = [row for row in lock['artifacts'] if row['metadata'].get('rootManifest')]
    if len(roots) != 1 or roots[0]['format'] != 'file':
        raise DependencyError('cargo-selected-root-manifest-missing')
    root = roots[0]
    declaration = read_bytes(app / 'Cargo.toml')
    if digest(declaration) != root['original']['digest']:
        raise DependencyError('cargo-root-manifest-drift-resolve-and-review')
    declared = tomllib.loads(declaration.decode('utf-8'))['package'].get('build', 'build.rs' if os.path.lexists(app / 'build.rs') else False)
    expected = root['metadata'].get('buildScript')
    if declared is not False:
        paths.relative(declared)
        raw = read_bytes(app / declared)
        if root['role'] != 'build-tool' or expected != {'path': declared, 'digest': digest(raw), 'size': len(raw)}:
            raise DependencyError('cargo-root-build-script-drift-resolve-and-review')
    elif expected is not None:
        raise DependencyError('cargo-root-build-script-drift-resolve-and-review')


def review(project: Path, candidate: Path, expected: str) -> dict:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise DependencyError('cargo-candidate-review-digest-required')
    candidate = regular_path(candidate)
    raw = read_bytes(candidate, inputs.MAX_LOCK)
    if digest(raw) != expected:
        raise DependencyError('cargo-candidate-review-drift')
    with transaction(project) as (root, app, private, sdk):
        declaration = read_bytes(root / inputs.MANIFEST, inputs.MAX_LOCK)
        value = inputs.validate_manifest(decode_json(declaration), 'rust')
        previous = optional(root, inputs.LOCK)
        with tempfile.TemporaryDirectory(prefix='cargo-lock-review-', dir=private) as temporary:
            check = Path(temporary)
            (check / inputs.MANIFEST).write_bytes(declaration)
            (check / inputs.LOCK).write_bytes(raw)
            for name in value['nativeLocks']:
                target = check / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_bytes(root / name))
            verified = inputs.verify_inputs(check, 'rust', cache=root / 'dependency-inputs/objects')
            if verified is None:
                raise DependencyError('cargo-candidate-not-verified')
            current_application(app, verified.lock)
        if (read_bytes(candidate, inputs.MAX_LOCK) != raw
                or read_bytes(root / inputs.MANIFEST, inputs.MAX_LOCK) != declaration):
            raise DependencyError('cargo-authoring-concurrent-input-edit')
        for row in verified.lock['nativeLocks']:
            if digest(read_bytes(root / row['path'])) != row['digest']:
                raise DependencyError('dependency-native-lock-drift')
        current_application(app, verified.lock)
        replace(root, private, inputs.LOCK, raw, previous, sdk)
        return {'formatVersion': 1, 'stage': 'cargo-reviewed-lock', 'status': 'reviewed',
                'candidateDigest': expected, 'previousLockDigest': digest(previous) if previous is not None else None,
                **public(root, sdk), 'capturedInputIdentity': verified.identity,
                'executableInputs': verified.lock['executableInputs'], 'compilerExecution': False,
                'frontendTrustRequired': True}


def status(project: Path) -> dict:
    root, app, sdk = seal(project)
    verified = inputs.verify_inputs(root, 'rust')
    if verified is not None:
        current_application(app, verified.lock)
    return {'formatVersion': 1, 'stage': 'cargo-dependency-status', 'status': 'verified' if verified else 'undeclared',
            **public(root, sdk), 'capturedInputIdentity': verified.identity if verified else None,
            'executableInputs': verified.lock['executableInputs'] if verified else [], 'compilerExecution': False}


def resolved(project: Path, candidate: Path, lock: dict) -> dict:
    root, app, sdk = seal(project)
    raw = read_bytes(candidate, inputs.MAX_LOCK)
    if decode_json(raw) != lock or digest(read_bytes(root / inputs.MANIFEST, inputs.MAX_LOCK)) != lock['manifestDigest']:
        raise DependencyError('cargo-candidate-resolution-drift')
    for row in lock['nativeLocks']:
        original = read_bytes(root / row['path'])
        if len(original) != row['size'] or digest(original) != row['digest']:
            raise DependencyError('dependency-native-lock-drift')
    current_application(app, lock)
    return {'formatVersion': 1, 'stage': 'cargo-resolution-capture', 'status': 'captured',
            'candidateDigest': digest(raw), **public(root, sdk),
            'executableInputs': lock['executableInputs'], 'reviewRequired': True,
            'compilerExecution': False, 'previousLockPreserved': True}


def record(project: Path, result: dict) -> Path:
    raw = canonical(result) + b'\n'
    if len(raw) > MAX_RECEIPT:
        raise DependencyError('cargo-authoring-receipt-limit')
    with transaction(project) as (_root, _app, private, _sdk):
        target = private / ('receipt-' + secrets.token_hex(16) + '.json')
        paths.write_new(target, raw)
        return target


def failure(operation: str, error: Exception) -> dict:
    from tools.dev_workflow.common import DevError
    code = error.code if isinstance(error, DevError) else str(error) if isinstance(error, DependencyError) else ''
    reason = code if re.fullmatch(r'[a-z][a-z0-9-]{0,127}', code) else 'cargo-authoring-invalid-or-unavailable-input'
    return {'formatVersion': 1, 'stage': 'cargo-' + operation, 'status': 'failed', 'reason': reason,
            'compilerExecution': False, 'automaticReplay': False}


def frontend(project: Path, action: str, *, workspace: str, state_root: Path | None = None,
             tool_root: str | None = None, selections: tuple[str, ...] = (), environment='node') -> list[str]:
    from tools.dev_workflow import common, dependencies, project as dev_project
    root, _app, _sdk = seal(project)
    descriptor, _identity = dev_project.load(root)
    common.require(descriptor['language'] == 'rust', 'cargo-authoring-project-language')
    dependencies.verify(root, descriptor)
    status(root)
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
        raise DependencyError('cargo-authoring-frontend-operation')
    return argv
