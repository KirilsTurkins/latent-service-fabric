"""Native npm capture with ignored hooks and an attributable offline module tree."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import unquote, urlsplit

from tools.application_dependencies import MANIFEST, capture, validate_manifest
from tools.application_dependency_store import (DependencyError, Store, archive_files, directory_files,
                                               path_name, read_bytes, regular_path, tree_identity)
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import decode_json, snapshot

PROFILE = 'spidermonkey-public-sync-v1'
FIELDS = ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies')


def source_snapshot(project: Path) -> dict[str, bytes]:
    return snapshot(project, exclude=('node_modules',) if (project / MANIFEST).is_file() else ())


def selection(value: dict | None = None) -> dict:
    value = dict(value or {})
    if set(value) - {'target', 'runtimeProfile', 'conditions'}:
        raise DependencyError('npm-selection-fields-invalid')
    conditions = value.get('conditions', [])
    if (not isinstance(conditions, list) or len(conditions) > 32
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) for name in conditions)):
        raise DependencyError('npm-module-conditions-invalid')
    if value.get('target', 'wasm32-component') != 'wasm32-component' or value.get('runtimeProfile', PROFILE) != PROFILE:
        raise DependencyError('npm-runtime-profile-not-installed')
    return {'target': 'wasm32-component', 'runtimeProfile': PROFILE, 'conditions': sorted(set(conditions))}


def native_lock(data: bytes) -> dict:
    value = decode_json(data)
    if (not isinstance(value, dict) or value.get('lockfileVersion') not in (2, 3)
            or not isinstance(value.get('packages'), dict) or '' not in value['packages']
            or len(value['packages']) > 1024):
        raise DependencyError('npm-native-lock-version-or-limit')
    for name, row in value['packages'].items():
        if not isinstance(name, str) or not isinstance(row, dict):
            raise DependencyError('npm-native-lock-invalid')
        if name.startswith('node_modules/'):
            path_name(name)
        source = row.get('resolved', '')
        if not isinstance(source, str):
            raise DependencyError('npm-native-source-invalid')
        if '://' in source and not source.startswith('file:'):
            parsed = urlsplit(source.removeprefix('git+'))
            if parsed.username or parsed.password or parsed.query:
                raise DependencyError('npm-native-source-credentials-denied')
            if parsed.scheme != 'https' or parsed.fragment and not re.fullmatch(r'[a-fA-F0-9]{40,64}', parsed.fragment):
                raise DependencyError('npm-native-source-not-locked-https')
        for field in FIELDS:
            if not isinstance(row.get(field, {}), dict) or any(not isinstance(value, str) for value in row.get(field, {}).values()):
                raise DependencyError('npm-native-declarations-invalid')
    return value


def edge_location(location: str, name: str, packages: dict) -> str | None:
    if not re.fullmatch(r'(?:@[a-zA-Z0-9._-]+/)?[a-zA-Z0-9._-]+', name):
        raise DependencyError('npm-native-dependency-name-invalid')
    candidate = location
    while True:
        selected = (candidate + '/' if candidate else '') + 'node_modules/' + name
        if selected in packages:
            return selected
        if not candidate:
            return None
        candidate = candidate.rpartition('/node_modules/')[0] if '/node_modules/' in candidate else ''


def graph(lock: dict, installed: dict[str, dict], platform: dict) -> dict:
    """Use the native lock's physical Node resolution, including peers/options."""
    packages, rows = lock['packages'], []
    for location, declaration in sorted(packages.items()):
        if location and not location.startswith('node_modules/'):
            continue  # Link targets are attributed by their installed Node path.
        row = packages.get(declaration.get('resolved'), {}) if declaration.get('link') else declaration
        present = not location or location in installed
        if not present and not row.get('optional'):
            raise DependencyError('npm-required-selected-package-missing')
        actual = installed.get(location, {})
        if present and location and actual.get('version') != row.get('version'):
            raise DependencyError('npm-installed-version-differs-from-native-lock')
        dependencies = []
        for kind in FIELDS:
            for name, specification in sorted(row.get(kind, {}).items()):
                selected = edge_location(location, name, packages)
                optional = kind == 'optionalDependencies' or (kind == 'peerDependencies' and
                    row.get('peerDependenciesMeta', {}).get(name, {}).get('optional', False))
                if selected is None and not optional and present:
                    raise DependencyError('npm-native-graph-not-closed')
                dependencies.append({'name': name, 'kind': kind, 'specification': specification,
                                     'selected': selected, 'optional': optional})
        rows.append({'location': location, 'version': row.get('version'), 'integrity': row.get('integrity'),
            'sourceDigest': digest(row.get('resolved', 'captured-local').encode()), 'link': bool(declaration.get('link')),
            'selected': present, 'optional': bool(row.get('optional')), 'peer': bool(row.get('peer')),
            'os': row.get('os'), 'cpu': row.get('cpu'), 'libc': row.get('libc'), 'dependencies': dependencies,
            'exports': actual.get('exports'), 'imports': actual.get('imports'), 'type': actual.get('type'),
            'main': actual.get('main'), 'module': actual.get('module'), 'license': actual.get('license'),
            'ignoredLifecycleScripts': sorted(set(actual.get('scripts', {})) & {'preinstall', 'install', 'postinstall', 'prepare'})})
    return {'formatVersion': 1, 'nodes': rows, 'installationPlatform': platform,
            'installScripts': 'never-executed', 'binLinks': False, 'networkResolution': 'explicit-capture-only'}


def cached_archive(cache: Path, integrity: str) -> bytes:
    try:
        algorithm, encoded = integrity.split()[0].split('-', 1)
        expected = base64.b64decode(encoded, validate=True)
        if algorithm not in {'sha512', 'sha256', 'sha1'} or len(expected) != hashlib.new(algorithm).digest_size:
            raise ValueError()
    except (ValueError, TypeError):
        raise DependencyError('npm-native-integrity-invalid') from None
    hexed = expected.hex()
    try:
        data = read_bytes(cache / '_cacache/content-v2' / algorithm / hexed[:2] / hexed[2:4] / hexed[4:])
    except FileNotFoundError:
        raise DependencyError('npm-original-package-archive-unavailable') from None
    if hashlib.new(algorithm, data).digest() != expected:
        raise DependencyError('npm-native-archive-integrity')
    files = archive_files(data, 'tar')  # Reject every unsafe original archive entry.
    if any(not name.startswith('package/') for name in files):
        raise DependencyError('npm-native-archive-package-prefix')
    return data


def _mirror(path: Path, owned: Path) -> Path:
    path = path.resolve(strict=False)
    parts = path.parts[1:] if path.anchor else path.parts
    drive = path.drive.replace(':', '') or 'posix'
    return owned / 'mirror' / drive / Path(*parts)


def local_path(source: str, project: Path) -> Path:
    if source.startswith('file://'):
        parsed = urlsplit(source)
        if parsed.netloc not in ('', 'localhost') or parsed.query or parsed.fragment:
            raise DependencyError('npm-local-file-endpoint-invalid')
        value = unquote(parsed.path)
        if os.name == 'nt' and re.match(r'^/[A-Za-z]:/', value):
            value = value[1:]
    else:
        value = source.removeprefix('file:')
    return (project / value).resolve(strict=True)


def resolve(project: Path, candidate: Path, *, node: Path | None = None, npm: Path | None = None,
            selected: dict | None = None, registry_config: Path | None = None) -> dict:
    project = regular_path(project).resolve(strict=True)
    if candidate.exists():
        raise DependencyError('dependency-candidate-exists')
    selected = selection(selected)
    original = {name: read_bytes(project / name) for name in ('package.json', 'package-lock.json')}
    declaration = decode_json(original['package.json'])
    locked = native_lock(original['package-lock.json'])
    recipe_before = file_identity(Path(__file__), 'npm-capture-recipe')
    node = regular_path(node or Path(shutil.which('node') or 'missing-node')).resolve(strict=True)
    if npm is None:
        located = Path(shutil.which('npm') or 'missing-npm')
        npm = (located.parent / 'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else located.resolve(strict=True))
    npm = regular_path(npm).resolve(strict=True)
    registries = decode_json(read_bytes(registry_config)) if registry_config else {'registries': []}
    if set(registries) != {'registries'} or not isinstance(registries['registries'], list) or len(registries['registries']) > 16:
        raise DependencyError('npm-registry-configuration-invalid')
    with tempfile.TemporaryDirectory(prefix='lsf-npm-resolve-') as temporary:
        owned = Path(temporary)
        work, cache = _mirror(project, owned), owned / 'npm-cache'
        work.mkdir(parents=True)
        environment = build_environment(owned)
        environment.update(HOME=str(owned / 'home'), USERPROFILE=str(owned / 'home'),
            NPM_CONFIG_CACHE=str(cache), NPM_CONFIG_USERCONFIG=str(owned / 'registry.npmrc'),
            NPM_CONFIG_GLOBALCONFIG=str(owned / 'empty.npmrc'), NPM_CONFIG_UPDATE_NOTIFIER='false',
            GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
        (owned / 'empty.npmrc').write_bytes(b'')
        configuration = []
        for row in registries['registries']:
            if not isinstance(row, dict) or set(row) - {'scope', 'url', 'authorizationEnv'} or 'url' not in row:
                raise DependencyError('npm-registry-configuration-invalid')
            parsed = urlsplit(row['url'])
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise DependencyError('npm-registry-endpoint-invalid')
            scope = row.get('scope', '')
            if scope and not re.fullmatch(r'@[A-Za-z0-9._-]+', scope):
                raise DependencyError('npm-registry-scope-invalid')
            configuration.append((scope + ':' if scope else '') + 'registry=' + row['url'])
            if variable := row.get('authorizationEnv'):
                if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', variable) or not os.environ.get(variable):
                    raise DependencyError('npm-registry-authorization-unavailable')
                environment[variable] = os.environ[variable]
                configuration.append('//' + parsed.netloc + parsed.path.rstrip('/') + '/:_authToken=${' + variable + '}')
        (owned / 'registry.npmrc').write_text('\n'.join(configuration) + '\n', encoding='utf-8')
        # Preserve native relative path semantics in an owned mirror. No project
        # npmrc, global cache, or package lifecycle hook reaches this stage.
        local_paths = {project}
        for location, row in locked['packages'].items():
            source = row.get('resolved', '')
            if row.get('link'):
                local_paths.add((project / source).resolve(strict=True))
            elif source.startswith('file:'):
                local_paths.add(local_path(source, project))
        staged_declaration = json.loads(original['package.json'])
        staged_lock = json.loads(original['package-lock.json'])
        local_originals = []
        for source in sorted(local_paths):
            regular_path(source)
            if source.is_dir():
                if source == project:
                    files = snapshot(source, exclude=('.git', 'target', 'node_modules'))
                else:
                    manifest = decode_json(read_bytes(source / 'package.json'))
                    if manifest.get('bundleDependencies') or manifest.get('bundledDependencies'):
                        raise DependencyError('npm-local-bundled-inputs-require-explicit-native-archive')
                    files = directory_files(source, exclude=('.git', 'node_modules'))
                if '.npmrc' in files:
                    raise DependencyError('npm-project-configuration-requires-explicit-registry-policy')
                for name, data in files.items():
                    destination = _mirror(source, owned) / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                if source != project:
                    local_originals.append((source, _mirror(source, owned), 'directory'))
            else:
                destination = _mirror(source, owned)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(read_bytes(source))
                local_originals.append((source, destination, 'file'))
        for value in [staged_declaration, *staged_lock['packages'].values()]:
            for field in FIELDS:
                for name, source in value.get(field, {}).items():
                    if source.startswith('file:') and (source.startswith('file://') or Path(source[5:]).is_absolute()):
                        value[field][name] = 'file:' + str(_mirror(local_path(source, project), owned))
            source = value.get('resolved', '')
            if source.startswith('file:') and (source.startswith('file://') or Path(source[5:]).is_absolute()):
                value['resolved'] = 'file:' + str(_mirror(local_path(source, project), owned))
        (work / 'package.json').write_bytes(canonical(staged_declaration))
        (work / 'package-lock.json').write_bytes(canonical(staged_lock))
        version = run_bounded([str(node), '--version'], owned, environment, 10, 16384).stdout.decode().strip()
        if version != 'v24.19.0':
            raise DependencyError('npm-node-host-not-pinned')
        npm_version = run_bounded([str(node), str(npm), '--version'], owned, environment, 10, 16384).stdout.decode().strip()
        run_bounded([str(node), str(npm), 'ci', '--ignore-scripts', '--bin-links=false', '--install-links=true',
                     '--no-audit', '--no-fund', '--strict-peer-deps'], work, environment, 600, 4 * 1024 * 1024)
        modules = work / 'node_modules'
        installed = {}
        for location, row in locked['packages'].items():
            if not location.startswith('node_modules/') or not (path := work / location).exists():
                continue
            if path.is_symlink():
                expected = (work / row.get('resolved', '')).resolve(strict=True)
                if not row.get('link') or path.resolve(strict=True) != expected or not expected.is_relative_to(owned):
                    raise DependencyError('npm-unobserved-installation-link')
                data = snapshot(expected, exclude=('node_modules', 'target', '.git'))
                path.unlink()
                path.mkdir()
                for name, content in data.items():
                    target = path / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            installed[location] = decode_json(read_bytes(path / 'package.json'))
        native = graph(locked, installed, {'os': sys.platform, 'cpu': run_bounded(
            [str(node), '-p', 'process.arch'], owned, environment, 10, 16384).stdout.decode().strip()})
        files = directory_files(modules) if modules.is_dir() else {}
        store = Store(project / 'dependency-inputs/objects')
        artifacts, archive_ids = [], []
        for source, captured_source, kind in local_originals:
            identity = 'npm-local-original/' + digest(str(source).encode())[7:31]
            archive_ids.append(identity)
            artifacts.append({'id': identity, 'role': 'application', 'format': kind,
                'mount': 'dependencies/npm-local-originals/' + identity.rpartition('/')[2],
                'source': {'path': str(captured_source)}, 'dependencies': [],
                'metadata': {'ecosystem': 'npm', 'assetType': 'original-local-fetch-input',
                             'sourceIdentityDigest': digest(str(source).encode()), 'ignoredRepositoryMetadata': True}})
        for location, row in sorted(locked['packages'].items()):
            if location not in installed or not row.get('integrity'):
                continue
            payload = cached_archive(cache, row['integrity'])
            for name, content in archive_files(payload, 'tar').items():
                if files.get(location.removeprefix('node_modules/') + '/' + name.removeprefix('package/')) != content:
                    raise DependencyError('npm-unpacked-source-differs-from-original-archive')
            reference = store.put(payload)
            identity = 'npm-archive/' + reference['digest'][7:]
            if identity in archive_ids:
                continue
            archive_ids.append(identity)
            artifacts.append({'id': identity, 'role': 'application', 'format': 'file',
                'mount': 'dependencies/npm-archives/' + reference['digest'][7:] + '.tgz',
                'source': {'path': str(store.path(reference['digest']))}, 'dependencies': [],
                'metadata': {'ecosystem': 'npm', 'integrity': row['integrity'], 'nativeLocation': location,
                             'assetType': 'original-package-archive'}})
        if not modules.is_dir():
            modules.mkdir()
        files = directory_files(modules)
        native.update(selection=selected, node=file_identity(node, 'npm-node'), npm=file_identity(npm, 'npm-cli'),
            npmVersion=npm_version, recipe=recipe_before,
            nativeLockDigest=digest(original['package-lock.json']), originalManifestDigest=digest(original['package.json']),
            fetchManifestDigest=digest(read_bytes(work / 'package.json')),
            fetchLockDigest=digest(read_bytes(work / 'package-lock.json')),
            configurationDigest=digest(canonical(registries)), filesDigest=digest(canonical([
                {'path': name, 'digest': digest(data), 'size': len(data)} for name, data in sorted(files.items())])))
        (project / 'npm-resolved.lock.json').write_bytes(canonical(native) + b'\n')
        artifacts.append({'id': 'npm-selected/' + digest(original['package-lock.json'])[7:31], 'role': 'application',
            'format': 'directory', 'mount': 'dependencies/npm/node_modules', 'source': {'path': str(modules)},
            'dependencies': archive_ids, 'metadata': {'ecosystem': 'npm', 'assetType': 'selected-node-modules',
                'nodeResolution': 'native-lock-physical-tree', 'installScripts': 'never-executed'}})
        manifest = {'formatVersion': 1, 'language': 'typescript', 'selection': selected,
                    'nativeLocks': ['package.json', 'package-lock.json', 'npm-resolved.lock.json'],
                    'artifacts': artifacts, 'transformations': []}
        validate_manifest(manifest, 'typescript')
        (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
        result = capture(project)
        if original != {name: read_bytes(project / name) for name in original} or file_identity(Path(__file__), 'npm-capture-recipe') != recipe_before:
            raise DependencyError('npm-declaration-lock-or-capture-recipe-mutated')
        candidate.parent.mkdir(parents=True, exist_ok=True)
        with candidate.open('xb') as output:
            output.write(canonical(result) + b'\n')
        return result


def bundle_configuration(closure) -> dict:
    selected = selection(closure.lock['selection'])
    roots = [row for row in closure.lock['artifacts'] if row['metadata'].get('assetType') == 'selected-node-modules']
    if len(roots) != 1:
        raise DependencyError('npm-selected-module-tree-missing-or-ambiguous')
    return {**selected, 'nodePaths': [str(closure.work / roots[0]['mount'])],
            'moduleRoot': roots[0]['mount'], 'inputIdentity': closure.identity,
            'platform': 'neutral', 'mainFields': ['module', 'main'], 'commonJs': 'static-require-only',
            'dynamicLoading': 'unsupported', 'installScripts': 'never-executed'}
