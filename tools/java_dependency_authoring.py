"""Reviewed Java dependency edits and authenticated developer-frontend delegation."""
from __future__ import annotations

from contextlib import contextmanager
import copy
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
from tools.java_capsule_project import validate_sdk_inputs
from tools.rust_capsule_project import decode_json, inventory, snapshot

STATE = 'target/java-dependency-authoring'
DECLARATIONS = 'java-dependencies.json'
RESOLUTION = 'java-resolved.lock.json'


def optional(root: Path, name: str) -> bytes | None:
    return read_bytes(root / name, inputs.MAX_LOCK) if os.path.lexists(root / name) else None


def seal(project: Path):
    owner, app, descriptor = layout(project, 'java')
    if owner != app and any(os.path.lexists(app / name) for name in (inputs.MANIFEST, inputs.LOCK)):
        raise DependencyError('dependency-frontend-ambiguous-application-lock')
    files = snapshot(app)
    _lock, vendor, _pins = validate_sdk_inputs(files)
    return owner, app, (files['sdk-lock.json'], inventory(vendor), descriptor)


def unchanged(owner: Path, original) -> None:
    if seal(owner)[2] != original:
        raise DependencyError('java-authoring-sdk-or-descriptor-drift')


@contextmanager
def transaction(project: Path):
    owner, app, sdk = seal(project)
    private = regular_path(owner / STATE)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    with state.lock(private, 'authoring.lock'):
        unchanged(owner, sdk)
        yield owner, app, private, sdk


def candidate_location(project: Path, candidate: Path) -> Path:
    owner, app, _sdk = seal(project)
    candidate = regular_path(Path(os.path.abspath(candidate)))
    if candidate.is_relative_to(owner) and not any(candidate.is_relative_to(root / 'target') for root in (owner, app)):
        raise DependencyError('java-candidate-cannot-overwrite-reviewed-input')
    return candidate


def replace(owner: Path, private: Path, name: str, raw: bytes, previous: bytes | None, sdk) -> None:
    paths.relative(name)
    _owner, app, _observed = seal(owner)
    prefix = app.relative_to(owner).as_posix() + '/' if owner != app else ''
    if name not in {inputs.MANIFEST, inputs.LOCK, prefix + DECLARATIONS, prefix + RESOLUTION}:
        raise DependencyError('java-authoring-edit-target')
    if len(raw) > inputs.MAX_LOCK:
        raise DependencyError('dependency-lock-limit')
    temporary = private / ('pending-' + secrets.token_hex(16))
    paths.write_new(temporary, raw)
    try:
        target = owner / name
        with paths.directory(target.parent) as destination, paths.directory(private) as source:
            if optional(owner, name) != previous:
                raise DependencyError('java-authoring-concurrent-input-edit')
            unchanged(owner, sdk)
            if os.name == 'nt':
                os.replace(temporary, target)
            else:
                os.replace(temporary.name, target.name, src_dir_fd=source, dst_dir_fd=destination)
                os.fsync(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def configuration(app: Path) -> dict:
    from tools.java_dependency_resolution import declarations
    raw = optional(app, DECLARATIONS)
    return declarations(decode_json(raw)) if raw is not None else {
        'formatVersion': 1, 'dependencies': [], 'localJars': [],
        'repositories': [{'id': 'central', 'url': 'https://repo.maven.apache.org/maven2'}],
        'selection': {'release': 25, 'runtimeProfile': 'java-teavm-c'}}


def edit(project: Path, operation: str, *, coordinate: str | None = None,
         local_id: str | None = None, jar: Path | None = None, dependencies: tuple[str, ...] = (),
         scope: str = 'runtime', exclusions: tuple[str, ...] = (), repository: tuple[str, str] | None = None,
         repository_ca: str | None = None,
         identity: str | None = None, version: str | None = None) -> dict:
    from tools.java_dependency_resolution import declarations
    with transaction(project) as (owner, app, private, sdk):
        previous = optional(app, DECLARATIONS)
        value = copy.deepcopy(configuration(app))
        if operation == 'add':
            parts = coordinate.split(':') if isinstance(coordinate, str) else []
            if len(parts) != 3:
                raise DependencyError('java-maven-coordinate-or-scope-invalid')
            omitted = []
            for exclusion in exclusions:
                pair = exclusion.split(':')
                if len(pair) != 2:
                    raise DependencyError('java-maven-exclusion-invalid')
                omitted.append(dict(zip(('group', 'name'), pair)))
            row = dict(zip(('group', 'name', 'version'), parts))
            row.update(scope=scope, exclusions=omitted)
            key = ':'.join(parts[:2])
            if any(item['group'] + ':' + item['name'] == key for item in value['dependencies']):
                raise DependencyError('java-dependency-already-declared')
            value['dependencies'].append(row)
        elif operation == 'add-local':
            if jar is None:
                raise DependencyError('java-local-jar-declaration-invalid')
            selected = regular_path(jar)
            payload = read_bytes(selected)
            from tools.java_application_dependencies import selected_entries
            selected_entries(payload, 25)
            if any(item['id'] == local_id for item in value['localJars']):
                raise DependencyError('java-dependency-already-declared')
            relative = os.path.relpath(selected, app).replace('\\', '/')
            value['localJars'].append({'id': local_id, 'path': relative, 'dependencies': list(dependencies)})
        elif operation in {'update', 'remove'}:
            maven = [item for item in value['dependencies'] if item['group'] + ':' + item['name'] == identity]
            local = [item for item in value['localJars'] if item['id'] == identity]
            if len(maven) + len(local) != 1:
                raise DependencyError('java-dependency-not-declared-or-ambiguous')
            row = (maven or local)[0]
            if operation == 'remove':
                value['dependencies' if maven else 'localJars'].remove(row)
            elif maven and version is not None:
                row['version'] = version
            elif local and jar is not None:
                selected = regular_path(jar)
                from tools.java_application_dependencies import selected_entries
                selected_entries(read_bytes(selected), 25)
                row['path'] = os.path.relpath(selected, app).replace('\\', '/')
            else:
                raise DependencyError('java-dependency-update-requires-exact-input')
        else:
            raise DependencyError('java-authoring-edit-operation')
        if repository is not None:
            if any(item['id'] == repository[0] for item in value['repositories']):
                raise DependencyError('java-repository-already-declared')
            declared = {'id': repository[0], 'url': repository[1]}
            if repository_ca is not None:
                declared['tlsTrust'] = {'caFile': repository_ca}
            value['repositories'].append(declared)
        elif repository_ca is not None:
            raise DependencyError('java-registry-certificate-requires-repository')
        declarations(value)
        prefix = app.relative_to(owner).as_posix() + '/' if owner != app else ''
        raw = canonical(value) + b'\n'
        replace(owner, private, prefix + DECLARATIONS, raw, previous, sdk)
        return {'formatVersion': 1, 'stage': 'java-' + operation, 'status': 'edited',
                'configurationDigest': digest(raw), 'sdkLockDigest': digest(sdk[0]),
                'reviewRequired': True, 'previousLockPreserved': True, 'compilerExecution': False}


def current_application(app: Path, lock: dict) -> None:
    from tools.java_dependency_resolution import declarations
    config_raw = read_bytes(app / DECLARATIONS, inputs.MAX_LOCK)
    config = declarations(decode_json(config_raw))
    native = decode_json(read_bytes(app / RESOLUTION, inputs.MAX_LOCK))
    if (native.get('formatVersion') != 1 or native.get('configurationDigest') != digest(config_raw)
            or native.get('selection') != config['selection'] or lock['selection'] != config['selection']
            or native.get('lifecycleScripts') != 'disabled'):
        raise DependencyError('java-native-graph-or-declaration-drift-resolve-and-review')
    graph = native.get('graph')
    identities = native.get('artifacts')
    if (not isinstance(graph, list) or len(graph) > 1024 or not isinstance(identities, dict)
            or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in graph)
            or len({row['id'] for row in graph}) != len(graph)):
        raise DependencyError('java-native-module-selection-ambiguous')
    jars = [row for row in lock['artifacts'] if row['role'] == 'application'
            and row['metadata'].get('assetType') != 'maven-resolution-metadata']
    if (len({row['id'] for row in jars}) != len(jars) or set(identities) != {row['id'] for row in jars}
            or any(row['format'] != 'file' or not row['mount'].endswith('.jar')
                   or identities[row['id']] != row['original'] for row in jars)):
        raise DependencyError('java-native-jar-artifact-identity-mismatch')
    local = {row['id']: row for row in config['localJars']}
    if set(local) - {row['id'] for row in jars}:
        raise DependencyError('java-local-jar-not-captured')
    for row in jars:
        if row['id'] in local:
            declared = local[row['id']]
            if (row['metadata'].get('ecosystem') != 'captured-local-jar'
                    or row['metadata'].get('originalLocalPath') != declared['path']
                    or not set(declared['dependencies']) <= set(row['dependencies'])):
                raise DependencyError('java-local-jar-declaration-drift')
            original = regular_path(app / declared['path'])
            if os.path.lexists(original) and digest(read_bytes(original)) != row['original']['digest']:
                raise DependencyError('java-local-jar-drift-resolve-and-review')
        elif row['id'] not in {item['id'] for item in graph}:
            raise DependencyError('java-native-jar-artifact-identity-mismatch')


def public(owner: Path, sdk) -> dict:
    declaration, lock = optional(owner, inputs.MANIFEST), optional(owner, inputs.LOCK)
    value = inputs.validate_manifest(decode_json(declaration), 'java') if declaration is not None else None
    return {'manifestDigest': digest(declaration) if declaration is not None else None,
            'lockDigest': digest(lock) if lock is not None else None, 'sdkLockDigest': digest(sdk[0]),
            'selection': value['selection'] if value else {}, 'artifacts': [row['id'] for row in value['artifacts']] if value else []}


def review(project: Path, candidate: Path, expected: str) -> dict:
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise DependencyError('java-candidate-review-digest-required')
    raw = read_bytes(regular_path(candidate), inputs.MAX_LOCK)
    if digest(raw) != expected:
        raise DependencyError('java-candidate-review-drift')
    with transaction(project) as (owner, app, private, sdk):
        declaration = read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)
        value = inputs.validate_manifest(decode_json(declaration), 'java')
        previous = optional(owner, inputs.LOCK)
        with tempfile.TemporaryDirectory(prefix='java-lock-review-', dir=private) as temporary:
            check = Path(temporary)
            (check / inputs.MANIFEST).write_bytes(declaration)
            (check / inputs.LOCK).write_bytes(raw)
            for name in value['nativeLocks']:
                target = check / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_bytes(owner / name))
            verified = inputs.verify_inputs(check, 'java', cache=owner / 'dependency-inputs/objects')
            if verified is None:
                raise DependencyError('java-candidate-not-verified')
            current_application(app, verified.lock)
        if read_bytes(candidate, inputs.MAX_LOCK) != raw or read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK) != declaration:
            raise DependencyError('java-authoring-concurrent-input-edit')
        for row in verified.lock['nativeLocks']:
            if digest(read_bytes(owner / row['path'])) != row['digest']:
                raise DependencyError('dependency-native-lock-drift')
        current_application(app, verified.lock)
        replace(owner, private, inputs.LOCK, raw, previous, sdk)
        return {'formatVersion': 1, 'stage': 'java-reviewed-lock', 'status': 'reviewed',
                'candidateDigest': expected, 'previousLockDigest': digest(previous) if previous is not None else None,
                **public(owner, sdk), 'capturedInputIdentity': verified.identity,
                'executableInputs': verified.lock['executableInputs'], 'compilerExecution': False, 'frontendTrustRequired': True}


def status(project: Path) -> dict:
    owner, app, sdk = seal(project)
    from tools.java_generator_authoring import validate_generated_inputs
    validate_generated_inputs(snapshot(app))
    verified = inputs.verify_inputs(owner, 'java')
    if verified is not None:
        current_application(app, verified.lock)
    return {'formatVersion': 1, 'stage': 'java-dependency-status', 'status': 'verified' if verified else 'undeclared',
            **public(owner, sdk), 'capturedInputIdentity': verified.identity if verified else None,
            'executableInputs': verified.lock['executableInputs'] if verified else [], 'compilerExecution': False}


def resolved(project: Path, candidate: Path, lock: dict) -> dict:
    owner, app, sdk = seal(project)
    raw = read_bytes(candidate, inputs.MAX_LOCK)
    if decode_json(raw) != lock or digest(read_bytes(owner / inputs.MANIFEST, inputs.MAX_LOCK)) != lock['manifestDigest']:
        raise DependencyError('java-candidate-resolution-drift')
    for row in lock['nativeLocks']:
        original = read_bytes(owner / row['path'])
        if len(original) != row['size'] or digest(original) != row['digest']:
            raise DependencyError('dependency-native-lock-drift')
    current_application(app, lock)
    return {'formatVersion': 1, 'stage': 'java-resolution-capture', 'status': 'captured',
            'candidateDigest': digest(raw), **public(owner, sdk), 'executableInputs': lock['executableInputs'],
            'reviewRequired': True, 'compilerExecution': False, 'previousLockPreserved': True}


def record(project: Path, result: dict) -> Path:
    raw = canonical(result) + b'\n'
    if len(raw) > 1024 * 1024:
        raise DependencyError('java-authoring-receipt-limit')
    with transaction(project) as (_owner, _app, private, _sdk):
        target = private / ('receipt-' + secrets.token_hex(16) + '.json')
        paths.write_new(target, raw)
        return target


def failure(operation: str, error: Exception) -> dict:
    from tools.dev_workflow.common import DevError
    code = error.code if isinstance(error, DevError) else str(error) if isinstance(error, DependencyError) else ''
    reason = code if re.fullmatch(r'[a-z][a-z0-9-]{0,127}', code) else 'java-authoring-invalid-or-unavailable-input'
    return {'formatVersion': 1, 'stage': 'java-' + operation, 'status': 'failed', 'reason': reason,
            'compilerExecution': False, 'automaticReplay': False}


def frontend(project: Path, action: str, *, workspace: str, state_root: Path | None = None,
             tool_root: str | None = None, selections: tuple[str, ...] = (), environment='node') -> list[str]:
    from tools.dev_workflow import common, dependencies, project as dev_project
    owner, _app, _sdk = seal(project)
    descriptor, _identity = dev_project.load(owner)
    common.require(descriptor['language'] == 'java', 'java-authoring-project-language')
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
        raise DependencyError('java-authoring-frontend-operation')
    return argv
