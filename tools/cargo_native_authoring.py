"""Native Cargo declaration/lock authoring in an observed fetch-only mirror."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib
from urllib.parse import parse_qs, urlsplit

from tools import rust_application_dependencies as native, rust_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, directory_files, read_bytes, regular_path
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import digest
from tools.rust_capsule_project import snapshot

SECTIONS = ('dependencies', 'dev-dependencies', 'build-dependencies')


def git_url(value: str):
    if (not isinstance(value, str) or not 0 < len(value) <= 4096
            or any(ord(char) < 33 or ord(char) == 127 for char in value)):
        raise DependencyError('cargo-native-authoring-git-selection-invalid')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError()
        return parsed.hostname, 443 if parsed.port is None else parsed.port, parsed.path or '/'
    except ValueError:
        raise DependencyError('cargo-native-authoring-git-selection-invalid') from None


def selected_git(metadata: bytes, work: Path, identity: str, version: str, git: str, revision: str) -> str:
    observed = native.native_metadata(metadata)
    graph = native.selected_graph(observed, observed, work)
    root = next(node for node in graph['nodes'] if node['id'] == graph['root'])
    direct = {edge['pkg'] for edge in root['deps']}
    matches = [row for row in observed['packages'] if row['id'] in direct
               and row.get('name') == identity and row.get('version') == version]
    if len(matches) != 1:
        raise DependencyError('cargo-native-authoring-native-selection-mismatch')
    source = matches[0].get('source')
    try:
        if not isinstance(source, str) or not source.startswith('git+'):
            raise ValueError()
        parsed = urlsplit(source[4:])
        if (parsed.fragment != revision or parse_qs(parsed.query, strict_parsing=True) != {'rev': [revision]}
                or git_url(parsed._replace(query='', fragment='').geturl()) != git_url(git)):
            raise ValueError()
    except (ValueError, TypeError):
        raise DependencyError('cargo-native-authoring-native-selection-mismatch') from None
    return source


def mirror(source: Path, owned: Path) -> Path:
    return owned / 'mirror' / (source.drive.replace(':', '') or 'posix') / Path(*source.parts[1:])


def dependency_tables(value: dict):
    for section in SECTIONS:
        if isinstance(value.get(section), dict):
            yield value[section]
    if isinstance(value.get('workspace', {}).get('dependencies'), dict):
        yield value['workspace']['dependencies']
    for target in value.get('target', {}).values():
        if isinstance(target, dict):
            yield from dependency_tables(target)
    for table in value.get('patch', {}).values():
        if isinstance(table, dict):
            yield table
    if isinstance(value.get('replace'), dict):
        yield value['replace']


def observe(app: Path, additional: Path | None = None):
    roots, missing, pending, manifests, locations = {}, set(), [app], set(), {app}
    if additional is not None:
        pending.append(additional)
    while pending:
        source = regular_path(pending.pop()).resolve(strict=False)
        locations.add(source)
        if source in roots or source in missing:
            continue
        if source != app and source in app.parents:
            raise DependencyError('cargo-native-authoring-local-source-overlaps-project')
        if not source.exists():
            missing.add(source)
            continue
        files = snapshot(app) if source == app else directory_files(source, exclude=('.git', 'target'))
        roots[source] = files
        if (len(roots) + len(missing) > 1024 or sum(map(len, roots.values())) > 32768
                or sum(len(raw) for rows in roots.values() for raw in rows.values()) > 256 * 1024 * 1024):
            raise DependencyError('cargo-native-authoring-local-byte-or-count-limit')
        for name, raw in files.items():
            if Path(name).name != 'Cargo.toml' or source / name in manifests:
                continue
            manifest = source / name; manifests.add(manifest)
            value = tomllib.loads(raw.decode('utf-8'))
            if value.get('package', {}).get('workspace'):
                raise DependencyError('cargo-native-authoring-external-workspace-pointer-not-captured')
            for table in dependency_tables(value):
                for row in table.values():
                    if isinstance(row, dict) and 'path' in row:
                        if not isinstance(row['path'], str):
                            raise DependencyError('cargo-native-authoring-local-path-invalid')
                        target = regular_path(manifest.parent / row['path']).resolve(strict=False)
                        locations.add(target)
                        if len(locations) > 32768:
                            raise DependencyError('cargo-native-authoring-local-byte-or-count-limit')
                        # Already observed application/SDK files need no second
                        # root; absent in-tree paths still map into the mirror.
                        if not target.is_relative_to(app):
                            pending.append(target)
    return roots, missing, locations


def recipe_identity():
    return {name: file_identity(path, name) for name, path in {
        'native-authoring': Path(__file__), 'capture-owner': Path(native.__file__),
        'review-owner': Path(authoring.__file__)}.items()}


def sdk_configuration(value):
    maintained = value.get('target', {}).get('cfg(target_arch = "wasm32")', {}).get('dependencies', {})
    return {'workspace': value.get('workspace'), 'package': value.get('package'), 'lib': value.get('lib'),
            'profile': value.get('profile'), 'maintained': {name: maintained.get(name) for name in ('wit-bindgen', 'latent-guest')}}


def workspace_sections(raw: bytes) -> tuple[str, str]:
    """Separate explicit immutable recipe tables; final equality is mandatory."""
    workspace, remainder, selected = [], [], False
    for line in raw.decode('utf-8').splitlines(keepends=True):
        if re.match(r'^\s*\[', line):
            try:
                header = tomllib.loads(line)
            except tomllib.TOMLDecodeError:
                pass
            else:
                selected = set(header) in ({'workspace'}, {'profile'})
        (workspace if selected else remainder).append(line)
    return ''.join(workspace), ''.join(remainder)


def preserve_workspace_recipe(original: bytes, selected: bytes) -> bytes:
    """Undo only Cargo remove's unused dependencies/package-profile pruning."""
    before, after = tomllib.loads(original.decode()), tomllib.loads(selected.decode())
    prior, current = before.get('workspace', {}), after.get('workspace', {})
    prior_profiles, current_profiles = before.get('profile', {}), after.get('profile', {})
    if prior == current and prior_profiles == current_profiles:
        return selected
    if not isinstance(prior, dict) or not isinstance(current, dict):
        raise DependencyError('cargo-native-authoring-mutated-sdk-recipe')
    prior_dependencies, current_dependencies = prior.get('dependencies', {}), current.get('dependencies', {})
    if prior != current and (not isinstance(prior_dependencies, dict) or not isinstance(current_dependencies, dict)
            or not prior_dependencies or len(current_dependencies) >= len(prior_dependencies)
            or any(name not in prior_dependencies or prior_dependencies[name] != value
                   for name, value in current_dependencies.items())
            or {name: value for name, value in prior.items() if name != 'dependencies'}
               != {name: value for name, value in current.items() if name != 'dependencies'}):
        raise DependencyError('cargo-native-authoring-mutated-sdk-recipe')
    if not isinstance(prior_profiles, dict) or not isinstance(current_profiles, dict):
        raise DependencyError('cargo-native-authoring-mutated-sdk-recipe')
    for name in set(prior_profiles) | set(current_profiles):
        original_profile, selected_profile = prior_profiles.get(name), current_profiles.get(name, {})
        if original_profile == selected_profile:
            continue
        if not isinstance(original_profile, dict) or not isinstance(selected_profile, dict):
            raise DependencyError('cargo-native-authoring-mutated-sdk-recipe')
        original_packages, selected_packages = original_profile.get('package', {}), selected_profile.get('package', {})
        if (not isinstance(original_packages, dict) or not isinstance(selected_packages, dict)
                or not original_packages or len(selected_packages) >= len(original_packages)
                or any(package not in original_packages or original_packages[package] != value
                       for package, value in selected_packages.items())
                or {key: value for key, value in original_profile.items() if key != 'package'}
                   != {key: value for key, value in selected_profile.items() if key != 'package'}):
            raise DependencyError('cargo-native-authoring-mutated-sdk-recipe')
    expected = dict(after, workspace=prior)
    if 'profile' in before:
        expected['profile'] = prior_profiles
    if sdk_configuration(expected) != sdk_configuration(before):
        raise DependencyError('cargo-native-authoring-mutated-sdk-recipe')
    original_workspace, _ = workspace_sections(original)
    _, selected_remainder = workspace_sections(selected)
    restored = (selected_remainder.rstrip() + '\n\n' + original_workspace.rstrip() + '\n').encode()
    try:
        value = tomllib.loads(restored.decode())
    except tomllib.TOMLDecodeError:
        raise DependencyError('cargo-native-authoring-workspace-preservation-unsupported-layout') from None
    if value != expected:
        raise DependencyError('cargo-native-authoring-workspace-preservation-semantic-mismatch')
    return restored


def author(project: Path, operation: str, *, identity: str | None = None, version: str | None = None,
           local: Path | None = None, section='dependencies', target: str | None = None,
           features: list[str] | None = None, no_default_features=False, optional=False,
           registry: str | None = None, cargo: Path | None = None, registry_config: Path | None = None,
           git: str | None = None, revision: str | None = None) -> dict:
    if operation not in {'add', 'update', 'remove', 'lock'} or section not in SECTIONS:
        raise DependencyError('cargo-native-authoring-operation-or-section-invalid')
    if operation != 'lock' and (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,127}', identity)):
        raise DependencyError('cargo-native-authoring-package-invalid')
    if operation in {'add', 'update'} and (not isinstance(version, str) or len(version) > 128
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version)):
        raise DependencyError('cargo-native-authoring-exact-version-required')
    features = features or []
    if (not isinstance(features, list) or len(features) > 256 or any(not isinstance(item, str)
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./+-]{0,127}', item) for item in features)
            or type(optional) is not bool or type(no_default_features) is not bool
            or target is not None and (not isinstance(target, str) or not 0 < len(target) <= 512
                                      or any(ord(char) < 32 or ord(char) == 127 for char in target))):
        raise DependencyError('cargo-native-authoring-selection-invalid')
    if registry is not None and (not isinstance(registry, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', registry)):
        raise DependencyError('cargo-native-authoring-registry-invalid')
    if git is not None or revision is not None:
        if (operation not in {'add', 'update'} or git is None or local is not None or registry is not None
                or not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision)):
            raise DependencyError('cargo-native-authoring-git-selection-invalid')
        git_url(git)
    with authoring.transaction(project) as (owner, app, private, sdk):
        before = snapshot(app)
        if any(Path(name).name in {'config', 'config.toml'} and '.cargo' in Path(name).parts for name in before):
            raise DependencyError('cargo-native-authoring-project-config-not-supported')
        configuration = tomllib.loads(before['Cargo.toml'].decode('utf-8'))
        table = configuration.get('target', {}).get(target, {}) if target is not None else configuration
        current = table.get(section, {})
        if not isinstance(current, dict):
            raise DependencyError('cargo-native-authoring-declaration-invalid')
        if operation == 'add' and identity in current:
            raise DependencyError('cargo-dependency-already-declared')
        if operation in {'update', 'remove'} and identity not in current:
            raise DependencyError('cargo-dependency-not-declared')
        if target == 'cfg(target_arch = "wasm32")' and section == 'dependencies' and identity in {'wit-bindgen', 'latent-guest'}:
            raise DependencyError('cargo-native-authoring-immutable-sdk-dependency')
        if local is not None:
            local = regular_path(local).resolve(strict=True)
            if (not local.is_dir() or local in {owner, app} or local in owner.parents or local.is_relative_to(app / 'vendor')):
                raise DependencyError('cargo-native-authoring-local-source-overlaps-project')
            package = tomllib.loads(read_bytes(local / 'Cargo.toml').decode('utf-8')).get('package', {})
            if package.get('name') != identity or package.get('version') != version:
                raise DependencyError('cargo-native-authoring-local-package-identity-mismatch')
        observed, missing, locations = observe(app, local)
        accepted = {name: authoring.optional(owner, name) for name in ('latent.dependencies.json', 'latent.dependencies.lock.json')}
        pins = tomllib.loads(before['vendor/lsf/rust-toolchain.toml'].decode())
        if registry_config is not None:
            registry_config = regular_path(registry_config).resolve(strict=True)
        registries, registry_bytes, trust_name, trust_raw = native.registry_policy(owner, app, registry_config)
        if registry is not None and registry not in {*registries, 'crates-io'}:
            raise DependencyError('cargo-native-authoring-registry-not-explicit')
        recipes = recipe_identity()
        with tempfile.TemporaryDirectory(prefix='lsf-cargo-native-authoring-') as temporary:
            owned = Path(temporary)
            located = cargo
            if located is None and (rustup := shutil.which('rustup')):
                located = run_bounded([rustup, 'which', '--toolchain', pins['toolchain']['channel'], 'cargo'],
                                      owned, build_environment(owned), 30, 16384).stdout.decode().strip()
            if not located:
                raise DependencyError('cargo-resolver-not-installed')
            cargo = regular_path(Path(located)).resolve(strict=True)
            tools = {'cargo': cargo, 'rustc': regular_path(cargo.parent / ('rustc.exe' if os.name == 'nt' else 'rustc'))}
            tool_before = {name: file_identity(path, name) for name, path in tools.items()}
            environment, certificate = native.fetch_environment(owned, pins, cargo, registries, trust_raw)
            version_text = run_bounded([str(cargo), '--version'], owned, environment, 10, 16384).stdout.decode().strip()
            if pins['toolchain']['channel'] not in version_text.split():
                raise DependencyError('cargo-resolver-version-not-pinned')
            mappings = {source: mirror(source, owned) for source in locations}
            for source, files in observed.items():
                for name, raw in files.items():
                    original = source / name; destination = mirror(original, owned)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if original.name == 'Cargo.toml':
                        raw = native.selected_manifest(raw, original, destination, mappings)
                        for table in dependency_tables(tomllib.loads(raw.decode('utf-8'))):
                            for row in table.values():
                                if isinstance(row, dict) and 'path' in row:
                                    selected_path = regular_path(destination.parent / row['path']).resolve(strict=False)
                                    if not selected_path.is_relative_to(owned):
                                        raise DependencyError('cargo-native-authoring-unobserved-local-path')
                    destination.write_bytes(raw)
            work = mirror(app, owned)
            staged = {source: snapshot(mirror(source, owned)) for source in observed}
            manifest = ['--manifest-path', str(work / 'Cargo.toml')]
            if operation != 'lock':
                arguments = ['remove', identity] if operation == 'remove' else ['add', identity if local is not None or git is not None else identity + '@=' + version]
                if local is not None:
                    arguments += ['--path', str(mirror(local, owned))]
                if git is not None:
                    arguments += ['--git', git, '--rev', revision]
                if section != 'dependencies':
                    arguments.append('--dev' if section == 'dev-dependencies' else '--build')
                if target is not None:
                    arguments += ['--target', target]
                if operation != 'remove':
                    if registry is not None:
                        arguments += ['--registry', registry]
                    if features:
                        arguments += ['--features', ','.join(sorted(set(features)))]
                    if no_default_features:
                        arguments.append('--no-default-features')
                    if optional:
                        arguments.append('--optional')
                run_bounded([str(cargo), *arguments, *manifest], owned, environment, 600, 4 * 1024 * 1024)
            # Resolve changed declarations against the copied lock. Regenerating
            # it would also refresh every unrelated SDK/compiler dependency.
            metadata = run_bounded([str(cargo), 'metadata', '--format-version', '1', *manifest],
                                   owned, environment, 600, 4 * 1024 * 1024).stdout
            git_source = selected_git(metadata, work, identity, version, git, revision) if git is not None else None
            reverse = {mapped: source for source, mapped in mappings.items()}
            raw_manifest = native.selected_manifest(read_bytes(work / 'Cargo.toml'), work / 'Cargo.toml', app / 'Cargo.toml', reverse)
            if operation == 'remove':
                raw_manifest = preserve_workspace_recipe(before['Cargo.toml'], raw_manifest)
            selected_configuration = tomllib.loads(raw_manifest.decode())
            if sdk_configuration(selected_configuration) != sdk_configuration(configuration):
                raise DependencyError('cargo-native-authoring-mutated-sdk-recipe')
            selected_table = selected_configuration.get('target', {}).get(target, {}) if target is not None else selected_configuration
            selected_row = selected_table.get(section, {}).get(identity)
            if operation == 'remove' and selected_row is not None:
                raise DependencyError('cargo-native-authoring-native-selection-mismatch')
            if operation in {'add', 'update'}:
                selected_row = {'version': selected_row} if isinstance(selected_row, str) else selected_row
                if not isinstance(selected_row, dict):
                    raise DependencyError('cargo-native-authoring-native-selection-mismatch')
                if git is not None:
                    if (selected_row.get('git') != git or selected_row.get('rev') != revision
                            or selected_row.get('version', version) not in (version, '=' + version)
                            or any(key in selected_row for key in ('path', 'registry', 'branch', 'tag'))):
                        raise DependencyError('cargo-native-authoring-native-selection-mismatch')
                elif local is not None:
                    if (not isinstance(selected_row.get('path'), str)
                            or (app / selected_row['path']).resolve(strict=False) != local
                            or selected_row.get('version', version).removeprefix('=') != version):
                        raise DependencyError('cargo-native-authoring-native-selection-mismatch')
                elif (selected_row.get('version') != '=' + version or selected_row.get('path') or selected_row.get('git')
                        or registry is not None and selected_row.get('registry', 'crates-io') != registry):
                    raise DependencyError('cargo-native-authoring-native-selection-mismatch')
            outputs = {'Cargo.toml': raw_manifest, 'Cargo.lock': read_bytes(work / 'Cargo.lock')}
            locked = tomllib.loads(outputs['Cargo.lock'].decode())
            if type(locked.get('version')) is not int or not isinstance(locked.get('package'), list) or len(locked['package']) > 1024:
                raise DependencyError('cargo-native-authoring-native-lock-invalid')
            if git_source is not None and len([row for row in locked['package'] if isinstance(row, dict)
                    and row.get('name') == identity and row.get('version') == version and row.get('source') == git_source]) != 1:
                raise DependencyError('cargo-native-authoring-native-selection-mismatch')
            for source, files in staged.items():
                after = snapshot(mirror(source, owned))
                for name in ('Cargo.toml', 'Cargo.lock') if source == app else ():
                    after.pop(name, None); files.pop(name, None)
                if after != files:
                    raise DependencyError('cargo-native-authoring-mutated-nondeclaration-input')
            if (observe(app, local) != (observed, missing, locations) or snapshot(app) != before
                    or recipe_identity() != recipes or {name: file_identity(path, name) for name, path in tools.items()} != tool_before
                    or {name: authoring.optional(owner, name) for name in accepted} != accepted
                    or registry_config is not None and read_bytes(registry_config) != registry_bytes
                    or trust_raw is not None and (read_bytes(app / trust_name) != trust_raw or read_bytes(certificate) != trust_raw)):
                raise DependencyError('cargo-native-authoring-source-tool-or-policy-mutated')
            authoring.unchanged(owner, sdk)
            prefix = app.relative_to(owner).as_posix() + '/' if app != owner else ''
            authoring.publish_native(owner, private, sdk,
                {prefix + name: (raw, before.get(name)) for name, raw in outputs.items()})
            return {'formatVersion': 1, 'stage': 'cargo-' + operation, 'status': 'locked',
                    'configurationDigest': digest(raw_manifest), 'nativeLockDigest': digest(outputs['Cargo.lock']),
                    'sdkLockDigest': digest(sdk[0]), 'registryPolicyDigest': digest(registry_bytes) if registry_bytes is not None else None,
                    'tlsTrustDigest': digest(trust_raw) if trust_raw is not None else None,
                    'captureRequired': True, 'reviewRequired': True, 'previousLockPreserved': True,
                    'compilerExecution': False, 'applicationHooks': 'never-executed',
                    'tools': tool_before, 'resolverVersion': version_text, 'recipe': recipes}
