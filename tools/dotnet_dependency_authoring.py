"""Reviewed NuGet edits, exact candidate review and maintained frontend delegation."""
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
from tools.dotnet_guest.project import validate_sdk_inputs

STATE = 'target/nuget-dependency-authoring'
MAX_RECEIPT = 1024 * 1024


def candidate_location(project: Path, candidate: Path) -> Path:
    owner, app, _descriptor = layout(project, 'dotnet')
    candidate = regular_path(Path(os.path.abspath(candidate)))
    if candidate.is_relative_to(owner) and not any(candidate.is_relative_to(root / 'target') for root in (owner, app)):
        raise DependencyError('nuget-candidate-cannot-overwrite-reviewed-input')
    return candidate


def optional(root: Path, name: str) -> bytes | None:
    return read_bytes(root / name, inputs.MAX_LOCK) if os.path.lexists(root / name) else None


def source_files(app: Path) -> dict[str, bytes]:
    # Ambient MSBuild output and package installations are not source inputs.
    return snapshot(app, exclude=('obj', 'bin', 'dependencies', 'application-vendor'))


def seal(project: Path):
    owner, app, descriptor = layout(project, 'dotnet')
    if owner != app and any(os.path.lexists(app / name) for name in (inputs.MANIFEST, inputs.LOCK)):
        raise DependencyError('dependency-frontend-ambiguous-application-lock')
    files = source_files(app)
    _lock, vendor, _pins = validate_sdk_inputs(files)
    return owner, app, (files['sdk-lock.json'], inventory(vendor), descriptor)


def unchanged(owner: Path, original) -> None:
    _owner, _app, observed = seal(owner)
    if observed != original:
        raise DependencyError('nuget-authoring-sdk-or-descriptor-drift')


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
    prefix = app.relative_to(owner).as_posix() + '/' if app != owner else ''
    if name not in {inputs.MANIFEST, inputs.LOCK, *(prefix + item for item in ('Capsule.csproj', 'packages.lock.json', 'nuget-resolved.lock.json'))}:
        raise DependencyError('nuget-authoring-edit-target')
    if len(raw) > inputs.MAX_LOCK:
        raise DependencyError('dependency-lock-limit')
    temporary = private / ('pending-' + secrets.token_hex(16))
    paths.write_new(temporary, raw)
    try:
        target = owner / name
        with paths.directory(target.parent) as destination, paths.directory(private) as source:
            if optional(owner, name) != previous:
                raise DependencyError('nuget-authoring-concurrent-input-edit')
            unchanged(owner, sdk)
            if os.name == 'nt':
                os.replace(temporary, target)
            else:
                os.replace(temporary.name, target.name, src_dir_fd=source, dst_dir_fd=destination)
                os.fsync(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish(owner: Path, private: Path, sdk, candidate: Path, lock: dict,
            updates: dict[str, tuple[bytes, bytes | None]]) -> None:
    """Publish a successful capture; roll back only our exact bytes on failure."""
    changed = []
    try:
        for name, (raw, previous) in updates.items():
            replace(owner, private, name, raw, previous, sdk)
            changed.append((name, raw, previous))
        candidate.parent.mkdir(parents=True, exist_ok=True)
        paths.write_new(candidate, canonical(lock) + b'\n')
    except BaseException:
        for name, raw, previous in reversed(changed):
            target = owner / name
            temporary = private / ('rollback-' + secrets.token_hex(16))
            if previous is not None:
                paths.write_new(temporary, previous)
            try:
                with paths.directory(target.parent) as destination, paths.directory(private) as source:
                    # Restore only our own exact published bytes, even if SDK
                    # drift caused the failure. Never overwrite a user's edit.
                    if optional(owner, name) != raw:
                        continue
                    if previous is None:
                        if os.name == 'nt':
                            target.unlink()
                        else:
                            os.unlink(target.name, dir_fd=destination)
                    elif os.name == 'nt':
                        os.replace(temporary, target)
                    else:
                        os.replace(temporary.name, target.name, src_dir_fd=source, dst_dir_fd=destination)
                    if os.name != 'nt':
                        os.fsync(destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
        raise


def public(owner: Path, sdk) -> dict:
    declaration, lock = optional(owner, inputs.MANIFEST), optional(owner, inputs.LOCK)
    value = inputs.validate_manifest(decode_json(declaration), 'dotnet') if declaration is not None else None
    selected = value['selection'] if value else {}
    return {'manifestDigest': digest(declaration) if declaration is not None else None,
            'lockDigest': digest(lock) if lock is not None else None, 'sdkLockDigest': digest(sdk[0]),
            'selection': {key: selected[key] for key in ('framework', 'runtimeIdentifier', 'runtimeProfile') if key in selected},
            'artifacts': [row['id'] for row in value['artifacts']] if value else []}


def edit(project: Path, operation: str, *, identity: str, version: str | None = None) -> dict:
    from tools.dotnet_application_dependencies import PROJECT, declarations, package_name, sdk_packages, xml
    import xml.etree.ElementTree as ET
    selected = package_name(identity)
    if operation in {'add', 'update'} and (not isinstance(version, str)
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version)
            or len(version) > 128):
        raise DependencyError('nuget-authoring-exact-version-required')
    with transaction(project) as (owner, app, private, sdk):
        files = source_files(app)
        declarations(files)
        root = xml(files[PROJECT])
        baseline_names = {name.partition('/')[0] for name in sdk_packages(
            decode_json(files['vendor/lsf/sdk/dotnet-guest/probes/smoke/packages.lock.json']))}
        if selected in baseline_names:
            raise DependencyError('nuget-authoring-sdk-package-edit-denied')
        matches = [(group, node) for group in root for node in group if node.tag == 'PackageReference' and 'Include' in node.attrib
                   and package_name(node.attrib['Include']) == selected]
        if operation == 'add':
            if matches:
                raise DependencyError('nuget-dependency-already-declared')
            group = ET.SubElement(root, 'ItemGroup')
            ET.SubElement(group, 'PackageReference', {'Include': identity, 'Version': '[' + version + ']'})
        elif operation in {'update', 'remove'}:
            if len(matches) != 1:
                raise DependencyError('nuget-dependency-not-declared-or-ambiguous')
            group, node = matches[0]
            if 'Condition' in node.attrib or any(child.tag == 'Condition' for child in node):
                raise DependencyError('nuget-authoring-conditional-edit-requires-explicit-source-review')
            if operation == 'remove':
                group.remove(node)
                if not list(group):
                    root.remove(group)
            else:
                node.attrib['Version'] = '[' + version + ']'
                for child in list(node):
                    if child.tag == 'Version':
                        node.remove(child)
        else:
            raise DependencyError('nuget-authoring-edit-operation')
        raw = ET.tostring(root, encoding='utf-8') + b'\n'
        declarations({**files, PROJECT: raw})
        if source_files(app) != files:
            raise DependencyError('nuget-authoring-concurrent-input-edit')
        prefix = app.relative_to(owner).as_posix() + '/' if app != owner else ''
        replace(owner, private, prefix + PROJECT, raw, files[PROJECT], sdk)
        return {'formatVersion': 1, 'stage': 'nuget-' + operation, 'status': 'edited',
                'configurationDigest': digest(raw), 'sdkLockDigest': digest(sdk[0]),
                'reviewRequired': True, 'previousLockPreserved': True, 'compilerExecution': False}


def current_application(app: Path, lock: dict) -> None:
    from tools.dotnet_application_dependencies import validate_selection
    files = source_files(app)
    validate_selection(files, lock['selection'], decode_json(files['packages.lock.json']),
                       decode_json(files['nuget-resolved.lock.json']), lock['artifacts'])


def review(project: Path, candidate: Path, expected: str) -> dict:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise DependencyError('nuget-candidate-review-digest-required')
    raw = read_bytes(regular_path(candidate), inputs.MAX_LOCK)
    if digest(raw) != expected:
        raise DependencyError('nuget-candidate-review-drift')
    with transaction(project) as (owner, app, private, sdk):
        declaration = read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)
        value = inputs.validate_manifest(decode_json(declaration), 'dotnet')
        previous = optional(owner, inputs.LOCK)
        with tempfile.TemporaryDirectory(prefix='nuget-lock-review-', dir=private) as temporary:
            check = Path(temporary)
            (check / inputs.MANIFEST).write_bytes(declaration)
            (check / inputs.LOCK).write_bytes(raw)
            for name in value['nativeLocks']:
                target = check / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_bytes(owner / name))
            verified = inputs.verify_inputs(check, 'dotnet', cache=owner / 'dependency-inputs/objects')
            if verified is None:
                raise DependencyError('nuget-candidate-not-verified')
            current_application(app, verified.lock)
        if (read_bytes(candidate, inputs.MAX_LOCK) != raw
                or read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK) != declaration):
            raise DependencyError('nuget-authoring-concurrent-input-edit')
        for row in verified.lock['nativeLocks']:
            if digest(read_bytes(owner / row['path'])) != row['digest']:
                raise DependencyError('dependency-native-lock-drift')
        current_application(app, verified.lock)
        replace(owner, private, inputs.LOCK, raw, previous, sdk)
        return {'formatVersion': 1, 'stage': 'nuget-reviewed-lock', 'status': 'reviewed',
                'candidateDigest': expected, 'previousLockDigest': digest(previous) if previous is not None else None,
                **public(owner, sdk), 'capturedInputIdentity': verified.identity,
                'executableInputs': verified.lock['executableInputs'], 'compilerExecution': False,
                'frontendTrustRequired': True}


def status(project: Path) -> dict:
    owner, app, sdk = seal(project)
    verified = inputs.verify_inputs(owner, 'dotnet')
    if verified is not None:
        current_application(app, verified.lock)
    return {'formatVersion': 1, 'stage': 'nuget-dependency-status', 'status': 'verified' if verified else 'undeclared',
            **public(owner, sdk), 'capturedInputIdentity': verified.identity if verified else None,
            'executableInputs': verified.lock['executableInputs'] if verified else [], 'compilerExecution': False}


def resolved(project: Path, candidate: Path, lock: dict) -> dict:
    owner, app, sdk = seal(project)
    raw = read_bytes(candidate, inputs.MAX_LOCK)
    if decode_json(raw) != lock or digest(read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)) != lock['manifestDigest']:
        raise DependencyError('nuget-candidate-resolution-drift')
    for row in lock['nativeLocks']:
        original = read_bytes(owner / row['path'])
        if len(original) != row['size'] or digest(original) != row['digest']:
            raise DependencyError('dependency-native-lock-drift')
    current_application(app, lock)
    return {'formatVersion': 1, 'stage': 'nuget-resolution-capture', 'status': 'captured',
            'candidateDigest': digest(raw), **public(owner, sdk), 'executableInputs': lock['executableInputs'],
            'reviewRequired': True, 'compilerExecution': False, 'previousLockPreserved': True}


def record(project: Path, result: dict) -> Path:
    raw = canonical(result) + b'\n'
    if len(raw) > MAX_RECEIPT:
        raise DependencyError('nuget-authoring-receipt-limit')
    with transaction(project) as (_owner, _app, private, _sdk):
        target = private / ('receipt-' + secrets.token_hex(16) + '.json')
        paths.write_new(target, raw)
        return target


def failure(operation: str, error: Exception) -> dict:
    from tools.dev_workflow.common import DevError
    code = error.code if isinstance(error, DevError) else str(error) if isinstance(error, DependencyError) else ''
    reason = code if re.fullmatch(r'[a-z][a-z0-9-]{0,127}', code) else 'nuget-authoring-invalid-or-unavailable-input'
    return {'formatVersion': 1, 'stage': 'nuget-' + operation, 'status': 'failed', 'reason': reason,
            'compilerExecution': False, 'automaticReplay': False}


def frontend(project: Path, action: str, *, workspace: str, state_root: Path | None = None,
             tool_root: str | None = None, selections: tuple[str, ...] = (), environment='node') -> list[str]:
    from tools.dev_workflow import common, dependencies, project as dev_project
    owner, _app, _sdk = seal(project)
    descriptor, _identity = dev_project.load(owner)
    common.require(descriptor['language'] == 'dotnet', 'nuget-authoring-project-language')
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
        raise DependencyError('nuget-authoring-frontend-operation')
    return argv
