"""Explicit Go declarations and native locking, separate from capture/review."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from tools import go_application_dependencies as native, go_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, directory_files, read_bytes, regular_path
from tools.build_observation import file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest


def command(go: Path, arguments: list[str], work: Path, environment: dict, *, fetch=False):
    return run_bounded([str(go), *arguments], work, environment, 600 if fetch else 10,
                       4 * 1024 * 1024 if fetch else 1024 * 1024)


def declaration(go: Path, work: Path, environment: dict) -> dict:
    value = json.loads(command(go, ['mod', 'edit', '-json'], work, environment).stdout)
    native.module_path(value['Module']['Path'])
    if value.get('Tool'):
        raise DependencyError('go-executable-tool-declarations-require-approved-isolated-stage')
    for field in ('Require', 'Replace', 'Exclude'):
        if not isinstance(value.get(field) or [], list) or len(value.get(field) or []) > 1024:
            raise DependencyError('go-native-declaration-count-limit')
    return value


def initialize(app: Path, owned: Path, go: Path | None, proxy_config: Path | None, owner: Path):
    go = regular_path(go or Path(shutil.which('go') or 'missing-go')).resolve(strict=True)
    identity = file_identity(go, 'go-native-authoring')
    environment, policy, policy_bytes = native.fetch_environment(owner, owned, proxy_config)
    # A declaration edit never resolves or fetches anything, even with a
    # developer-supplied go.mod toolchain directive or an ambient module cache.
    environment.update(GOPROXY='off', GOSUMDB='off')
    version = command(go, ['version'], owned, environment).stdout.decode().strip()
    pins = json.loads(read_bytes(app / 'vendor/lsf/sdk/go-guest/toolchain.lock.json'))
    if version.split()[2:3] != [pins['go']['version']]:
        raise DependencyError('go-module-resolver-version-not-pinned')
    return go, identity, environment, policy, policy_bytes, version


def recipe_identity() -> dict:
    return {name: file_identity(path, name) for name, path in {
        'native-authoring': Path(__file__), 'capture-owner': Path(native.__file__),
        'review-owner': Path(authoring.__file__)}.items()}


def still_current(owner, app, sdk, before, go, go_before, recipes, proxy_config, policy_bytes, accepted):
    if (authoring.source_files(app) != before or file_identity(go, 'go-native-authoring') != go_before
            or recipe_identity() != recipes
            or proxy_config is not None and read_bytes(proxy_config) != policy_bytes
            or {name: authoring.optional(owner, name) for name in accepted} != accepted):
        raise DependencyError('go-native-authoring-source-tool-or-policy-mutated')
    authoring.unchanged(owner, sdk)


def module_key(row: dict) -> str:
    return row['Path'] + ('@' + row['Version'] if row.get('Version') else '')


def edit(project: Path, operation: str, *, identity: str, version: str | None = None,
         local: Path | None = None, go: Path | None = None) -> dict:
    native.module_path(identity)
    if operation not in {'add', 'update', 'remove'}:
        raise DependencyError('go-authoring-edit-operation')
    if operation != 'remove' and (not isinstance(version, str) or len(version) > 128
            or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version)):
        raise DependencyError('go-authoring-exact-version-required')
    with authoring.transaction(project) as (owner, app, private, sdk):
        before = authoring.source_files(app)
        baseline = json.loads(before['vendor/lsf/sdk/go-guest/runtime-deps/dependencies.lock.json'])
        if identity in {row['path'] for row in baseline['modules']}:
            raise DependencyError('go-authoring-immutable-sdk-module-edit-denied')
        accepted = {name: authoring.optional(owner, name) for name in ('latent.dependencies.json', 'latent.dependencies.lock.json')}
        recipes = recipe_identity()
        with tempfile.TemporaryDirectory(prefix='lsf-go-declaration-') as temporary:
            owned = Path(temporary)
            go, go_before, environment, _policy, _raw, version_text = initialize(app, owned, go, None, owner)
            work = owned / 'project'; work.mkdir()
            (work / 'go.mod').write_bytes(before['go.mod'])
            value = declaration(go, work, environment)
            matches = [row for row in value.get('Require') or [] if row['Path'] == identity]
            if operation == 'add' and matches:
                raise DependencyError('go-dependency-already-declared')
            if operation != 'add' and len(matches) != 1:
                raise DependencyError('go-dependency-not-declared-or-ambiguous')
            arguments = ['mod', 'edit', ('-droprequire=' + identity) if operation == 'remove'
                         else '-require=' + identity + '@' + version]
            # Remove all replacements for this identity when changing its
            # source; unrelated replacements/exclusions stay native Go inputs.
            replacements = [row for row in value.get('Replace') or [] if row['Old']['Path'] == identity]
            arguments += ['-dropreplace=' + module_key(row['Old']) for row in replacements]
            if operation != 'remove' and local is not None:
                source = regular_path(local).resolve(strict=True)
                if (not source.is_dir() or source in {owner, app} or source in owner.parents
                        or source.is_relative_to(app / 'vendor')):
                    raise DependencyError('go-authoring-local-source-overlaps-sdk-or-project')
                arguments.append('-replace=' + identity + '=' + os.path.relpath(source, app).replace('\\', '/'))
            command(go, arguments, work, environment)
            declaration(go, work, environment)
            raw = read_bytes(work / 'go.mod')
            still_current(owner, app, sdk, before, go, go_before, recipes, None, None, accepted)
            prefix = app.relative_to(owner).as_posix() + '/' if app != owner else ''
            authoring.replace(owner, private, prefix + 'go.mod', raw, before['go.mod'], sdk)
            return {'formatVersion': 1, 'stage': 'go-' + operation, 'status': 'edited',
                    'configurationDigest': digest(raw), 'sdkLockDigest': digest(sdk[0]),
                    'nativeLockRequired': True, 'reviewRequired': True, 'previousLockPreserved': True,
                    'compilerExecution': False, 'generators': 'never-executed',
                    'nativeGo': go_before, 'resolverVersion': version_text, 'recipe': recipes}


def create_lock(project: Path, *, go: Path | None = None, proxy_config: Path | None = None,
                tags: list[str] | None = None) -> dict:
    selected = native.selection({'tags': tags or []})
    with authoring.transaction(project) as (owner, app, private, sdk):
        before = authoring.source_files(app)
        accepted = {name: authoring.optional(owner, name) for name in ('latent.dependencies.json', 'latent.dependencies.lock.json')}
        recipes = recipe_identity()
        if proxy_config is not None:
            proxy_config = regular_path(proxy_config).resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix='lsf-go-native-lock-') as temporary:
            owned = Path(temporary)
            go, go_before, environment, policy, policy_bytes, version = initialize(app, owned, go, proxy_config, owner)
            environment.update(GOPROXY=policy['proxy'], GOSUMDB=policy['sumdb'], GOOS='wasip1', GOARCH='wasm',
                GOFLAGS='-mod=mod' + (' -tags=' + ','.join(selected['tags']) if selected['tags'] else ''))
            work = native._mirror(app, owned)
            for name, raw in before.items():
                destination = work / name; destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            root = declaration(go, work, environment)
            local_inputs, replacements = {}, []
            for row in root.get('Replace') or []:
                target = row['New']
                if target.get('Version'):
                    native.module_path(target['Path'])
                    continue
                source = regular_path(app / target['Path']).resolve(strict=True)
                if (not source.is_dir() or source in {owner, app} or source in owner.parents
                        or source.is_relative_to(app / 'vendor')):
                    raise DependencyError('go-authoring-local-source-overlaps-sdk-or-project')
                files = directory_files(source, exclude=('.git',))
                local_inputs[source] = files
                if (len(local_inputs) > 1024 or sum(map(len, local_inputs.values())) > 32768
                        or sum(len(data) for item in local_inputs.values() for data in item.values()) > 256 * 1024 * 1024):
                    raise DependencyError('go-native-lock-local-byte-or-count-limit')
                destination = native._mirror(source, owned)
                for name, raw in files.items():
                    target_path = destination / name; target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_bytes(raw)
                key = module_key(row['Old'])
                command(go, ['mod', 'edit', '-replace=' + key + '=' + str(destination)], work, environment)
                replacements.append((key, row['New']['Path']))
            # Both commands select metadata/download bytes only. Neither invokes
            # go generate, application code, a toolchain installer or a compiler.
            command(go, ['mod', 'tidy'], work, environment, fetch=True)
            command(go, ['mod', 'download', 'all'], work, environment, fetch=True)
            declaration(go, work, environment)
            for key, original in replacements:
                command(go, ['mod', 'edit', '-replace=' + key + '=' + original], work, environment)
            outputs = {'go.mod': read_bytes(work / 'go.mod'),
                       'go.sum': read_bytes(work / 'go.sum') if (work / 'go.sum').exists() else b''}
            native.sums(outputs['go.sum'])
            if any(directory_files(source, exclude=('.git',)) != files for source, files in local_inputs.items()):
                raise DependencyError('go-native-lock-local-input-mutated')
            still_current(owner, app, sdk, before, go, go_before, recipes, proxy_config, policy_bytes, accepted)
            prefix = app.relative_to(owner).as_posix() + '/' if app != owner else ''
            authoring.publish_native(owner, private, sdk,
                {prefix + name: (raw, before.get(name)) for name, raw in outputs.items()})
            return {'formatVersion': 1, 'stage': 'go-native-lock', 'status': 'locked',
                    'configurationDigest': digest(outputs['go.mod']), 'nativeSumDigest': digest(outputs['go.sum']),
                    'fetchPolicyDigest': digest(canonical(policy)), 'sdkLockDigest': digest(sdk[0]),
                    'captureRequired': True, 'reviewRequired': True, 'previousLockPreserved': True,
                    'compilerExecution': False, 'generators': 'never-executed', 'tags': selected['tags'],
                    'nativeGo': go_before, 'resolverVersion': version, 'recipe': recipes}
