"""Explicit controlled npm native-lock authoring; never install application hooks."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import tempfile

from tools import typescript_dependency_authoring as authoring
from tools import typescript_application_dependencies as native
from tools.application_dependency_store import DependencyError, directory_files, read_bytes, regular_path
from tools.build_observation import file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import decode_json


def local_source(value: str, project: Path) -> Path | None:
    if value.startswith('file:'):
        return native.local_path(value, project)
    if value.startswith(('./', '../', '/', '\\')) or len(value) > 2 and value[1:3] in {':/', ':\\'}:
        return regular_path(project / value).resolve(strict=True)
    return None


def sources(app: Path, owner: Path, declaration: dict) -> dict[Path, dict[str, bytes] | bytes]:
    """Observe direct and transitive local inputs before native npm can read them."""
    result, pending = {}, [(app, declaration)]
    total = count = 0
    while pending:
        source, manifest = pending.pop()
        if source in result:
            continue
        if len(result) >= 1024:
            raise DependencyError('npm-native-lock-local-source-limit')
        if source != app and (source == owner or source in owner.parents or source.is_relative_to(app / 'vendor')):
            raise DependencyError('npm-native-lock-local-source-overlaps-sdk-or-project')
        if source.is_dir():
            files = (authoring.source_files(app) if source == app else
                     directory_files(source, exclude=('.git', 'target', 'node_modules')))
            if '.npmrc' in files:
                raise DependencyError('npm-project-configuration-requires-explicit-registry-policy')
            if manifest is None:
                if 'package.json' not in files:
                    raise DependencyError('npm-local-package-manifest-missing')
                manifest = decode_json(files['package.json'])
            if not isinstance(manifest, dict):
                raise DependencyError('npm-local-package-manifest-invalid')
            if manifest.get('bundleDependencies') or manifest.get('bundledDependencies'):
                raise DependencyError('npm-local-bundled-inputs-require-explicit-native-archive')
            result[source] = files
            for field in native.FIELDS:
                selected = manifest.get(field, {})
                if not isinstance(selected, dict) or len(selected) > 256:
                    raise DependencyError('npm-native-lock-local-declaration-limit')
                for value in selected.values():
                    if not isinstance(value, str) or not 0 < len(value) <= 4096:
                        raise DependencyError('npm-native-lock-local-declaration-invalid')
                    if child := local_source(value, source):
                        pending.append((child, None))
        else:
            result[source] = read_bytes(source)
            native.archive_files(result[source], 'tar')
        total += sum(map(len, result[source].values())) if isinstance(result[source], dict) else len(result[source])
        count += len(result[source]) if isinstance(result[source], dict) else 1
        if total > 256 * 1024 * 1024 or count > 32768:
            raise DependencyError('npm-native-lock-local-byte-or-count-limit')
    return result


def mirrored_manifest(raw: bytes, source: Path, owned: Path) -> dict:
    value = decode_json(raw)
    for field in native.FIELDS:
        for name, spec in value.get(field, {}).items():
            if path := local_source(spec, source):
                value[field][name] = 'file:' + str(native._mirror(path, owned))
    return value


def normalized_lock(raw: bytes, app: Path, owned: Path, selected: dict) -> bytes:
    value = copy.deepcopy(native.native_lock(raw))
    reverse = {native._mirror(source, owned): source for source in selected}
    for location, row in value['packages'].items():
        if row.get('link'):
            raise DependencyError('npm-native-lock-workspace-link-not-supported')
        original = app if not location else None
        spec = row.get('resolved', '')
        if fetched := local_source(spec, native._mirror(app, owned)):
            if fetched not in reverse:
                raise DependencyError('npm-native-lock-unobserved-local-source')
            original = reverse[fetched]
            row['resolved'] = 'file:' + os.path.relpath(original, app).replace('\\', '/')
        if original is not None and isinstance(selected[original], dict):
            # Preserve each local package's own original relative declarations,
            # rather than leaking the temporary mirror or changing npm semantics.
            manifest = decode_json(selected[original]['package.json'])
            for field in native.FIELDS:
                if field in manifest:
                    row[field] = manifest[field]
                else:
                    row.pop(field, None)
    return canonical(value) + b'\n'


def create_lock(project: Path, *, node: Path | None = None, npm: Path | None = None,
                registry_config: Path | None = None) -> dict:
    with authoring.transaction(project) as (owner, app, private, sdk):
        declaration = authoring.configuration(app)
        before = authoring.source_files(app)
        if 'package.json' not in before:
            raise DependencyError('npm-native-lock-requires-package-declaration')
        observed = sources(app, owner, declaration)
        previous = authoring.optional(app, 'package-lock.json')
        accepted = authoring.optional(owner, 'latent.dependencies.lock.json')
        previous_manifest = authoring.optional(owner, 'latent.dependencies.json')
        node = regular_path(node or Path(shutil.which('node') or 'missing-node')).resolve(strict=True)
        if npm is None:
            located = Path(shutil.which('npm') or 'missing-npm')
            npm = located.parent / 'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else located.resolve(strict=True)
        npm = regular_path(npm).resolve(strict=True)
        node_before, npm_before = file_identity(node, 'npm-node'), file_identity(npm, 'npm-cli')
        recipes = {'npm-native-lock-authoring': Path(__file__), 'npm-capture-owner': Path(native.__file__),
                   'npm-review-owner': Path(authoring.__file__)}
        recipe_before = {name: file_identity(path, name) for name, path in recipes.items()}
        policy_bytes = None
        if registry_config is not None:
            registry_config = regular_path(registry_config).resolve(strict=True)
            if registry_config.is_relative_to(owner):
                raise DependencyError('npm-registry-configuration-must-stay-outside-project')
            policy_bytes = read_bytes(registry_config)
        policy = decode_json(policy_bytes) if policy_bytes is not None else {'registries': []}
        if (not isinstance(policy, dict) or set(policy) != {'registries'} or not isinstance(policy['registries'], list)
                or len(policy['registries']) > 16):
            raise DependencyError('npm-registry-configuration-invalid')
        with tempfile.TemporaryDirectory(prefix='lsf-npm-native-lock-') as temporary:
            owned = Path(temporary)
            environment = native.fetch_environment(owned, policy)
            environment['NPM_CONFIG_IGNORE_SCRIPTS'] = 'true'
            for source, original in observed.items():
                target = native._mirror(source, owned)
                files = original if isinstance(original, dict) else {target.name: original}
                for name, raw in files.items():
                    destination = target / name if isinstance(original, dict) else target
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(original, dict) and name == 'package.json':
                        raw = canonical(mirrored_manifest(raw, source, owned)) + b'\n'
                    destination.write_bytes(raw)
            fetched_declaration = mirrored_manifest(before['package.json'], app, owned)
            # An existing lock may retain obsolete local paths. Native selection
            # regenerates it from the explicit application declarations privately.
            work = native._mirror(app, owned)
            (work / 'package-lock.json').unlink(missing_ok=True)
            if run_bounded([str(node), '--version'], owned, environment, 10, 16384).stdout.strip() != b'v24.19.0':
                raise DependencyError('npm-node-host-not-pinned')
            npm_version = run_bounded([str(node), str(npm), '--version'], owned, environment, 10, 16384).stdout.decode().strip()
            run_bounded([str(node), str(npm), 'install', '--package-lock-only', '--ignore-scripts', '--install-links=true',
                         '--bin-links=false', '--strict-peer-deps', '--no-audit', '--no-fund'],
                        work, environment, 600, 4 * 1024 * 1024)
            if decode_json(read_bytes(work / 'package.json')) != fetched_declaration:
                raise DependencyError('npm-native-lock-mutated-application-declarations')
            raw = normalized_lock(read_bytes(work / 'package-lock.json', 8 * 1024 * 1024), app, owned, observed)
            if (authoring.source_files(app) != before or sources(app, owner, declaration) != observed
                    or authoring.optional(owner, 'latent.dependencies.lock.json') != accepted
                    or authoring.optional(owner, 'latent.dependencies.json') != previous_manifest
                    or file_identity(node, 'npm-node') != node_before or file_identity(npm, 'npm-cli') != npm_before
                    or {name: file_identity(path, name) for name, path in recipes.items()} != recipe_before
                    or registry_config is not None and read_bytes(registry_config) != policy_bytes):
                raise DependencyError('npm-native-lock-source-tool-or-policy-mutated')
            authoring.unchanged(owner, sdk)
            prefix = app.relative_to(owner).as_posix() + '/' if app != owner else ''
            authoring.replace(owner, private, prefix + 'package-lock.json', raw, previous, sdk)
            return {'formatVersion': 1, 'stage': 'npm-native-lock', 'status': 'locked',
                    'nativeLockDigest': digest(raw), 'configurationDigest': digest(before['package.json']), 'fetchPolicyDigest': digest(canonical(policy)),
                    'sdkLockDigest': digest(sdk[0]), 'captureRequired': True, 'reviewRequired': True,
                    'previousLockPreserved': True, 'compilerExecution': False, 'installScripts': 'never-executed',
                    'node': node_before, 'npm': npm_before, 'npmVersion': npm_version, 'recipe': recipe_before}
