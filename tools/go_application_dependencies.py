"""Native Go module selection, original h1 inputs and offline compiler staging."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from tools.application_dependencies import MANIFEST, capture, validate_manifest
from tools.application_dependency_store import (DependencyError, Store, archive_files, directory_files,
                                               read_bytes, regular_path, tree_identity)
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import snapshot

PROFILE = 'go-component-async-v1'


def native_assembly(data: bytes) -> bool:
    """Go import-linkage markers containing only comments have no opcodes."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return True
    return re.fullmatch(r'(?:\s|//[^\n]*(?:\n|$)|/\*[\s\S]*?\*/)*', text) is None


def selection(value: dict | None = None) -> dict:
    value = dict(value or {})
    if set(value) - {'target', 'runtimeProfile', 'tags'}:
        raise DependencyError('go-selection-fields-invalid')
    tags = value.get('tags', [])
    if (not isinstance(tags, list) or len(tags) > 32 or any(not isinstance(tag, str)
            or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', tag) for tag in tags)):
        raise DependencyError('go-build-tags-invalid')
    if value.get('target', 'wasip1/wasm') != 'wasip1/wasm' or value.get('runtimeProfile', PROFILE) != PROFILE:
        raise DependencyError('go-runtime-profile-not-installed')
    return {'target': 'wasip1/wasm', 'runtimeProfile': PROFILE, 'tags': sorted(set(tags))}


def json_stream(data: bytes) -> list[dict]:
    if len(data) > 16 * 1024 * 1024:
        raise DependencyError('go-native-metadata-byte-limit')
    text, decoder, rows = data.decode('utf-8'), json.JSONDecoder(), []
    while text.strip():
        value, offset = decoder.raw_decode(text.lstrip())
        if not isinstance(value, dict) or len(rows) >= 1024 or value.get('Error'):
            raise DependencyError('go-native-metadata-invalid-or-unresolved')
        rows.append(value)
        text = text.lstrip()[offset:]
    return rows


def module_path(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 512 or any(char in value for char in '\\:@?#\n\r\t "`')
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise DependencyError('go-native-module-identity-invalid')
    return value


def module_id(row: dict) -> str:
    return 'go-module/' + digest((module_path(row['Path']) + '@' + row.get('Version', '')).encode())[7:31]


def sums(data: bytes) -> dict[tuple[str, str], str]:
    result = {}
    for line in data.decode('utf-8').splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 3 or not fields[2].startswith('h1:'):
            raise DependencyError('go-native-sum-invalid')
        module_path(fields[0])
        try:
            decoded = base64.b64decode(fields[2][3:], validate=True)
            if len(decoded) != 32:
                raise ValueError()
        except ValueError:
            raise DependencyError('go-native-sum-invalid') from None
        key = (fields[0], fields[1])
        if key in result and result[key] != fields[2]:
            raise DependencyError('go-native-sum-conflict')
        result[key] = fields[2]
    return result


def h1(files: dict[str, bytes]) -> str:
    # Go's dirhash.Hash1: SHA-256 per file, then the sorted hex/name lines.
    lines = ''.join(hashlib.sha256(content).hexdigest() + '  ' + name + '\n'
                    for name, content in sorted(files.items())).encode('utf-8')
    return 'h1:' + base64.b64encode(hashlib.sha256(lines).digest()).decode('ascii')


def verify_download(row: dict, expected: dict) -> tuple[dict[str, bytes], dict[str, bytes]]:
    path, version = module_path(row['Path']), row['Version']
    if (expected.get((path, version)) != row.get('Sum')
            or expected.get((path, version + '/go.mod')) != row.get('GoModSum')):
        raise DependencyError('go-downloaded-module-not-in-reviewed-sums')
    original = archive_files(read_bytes(Path(row['Zip'])), 'zip')
    prefix = path + '@' + version + '/'
    if not original or any(not name.startswith(prefix) for name in original) or h1(original) != row['Sum']:
        raise DependencyError('go-original-module-zip-identity')
    go_mod = read_bytes(Path(row['GoMod']))
    if h1({'go.mod': go_mod}) != row['GoModSum']:
        raise DependencyError('go-original-module-manifest-identity')
    selected = directory_files(Path(row['Dir']))
    unpacked = {name.removeprefix(prefix): content for name, content in original.items()}
    if unpacked != selected:
        raise DependencyError('go-expanded-module-differs-from-original-zip')
    return original, selected


def graph(modules: list[dict], edges: str, root: dict) -> dict:
    selected = {module_path(row['Path']): row for row in modules}
    if len(selected) != len(modules) or len(modules) > 1024:
        raise DependencyError('go-native-module-selection-ambiguous')
    main = [row for row in modules if row.get('Main')]
    if len(main) != 1 or main[0]['Path'] != root['Module']['Path']:
        raise DependencyError('go-native-main-module-mismatch')
    result = []
    for line in edges.splitlines():
        values = line.split()
        if len(values) != 2 or len(result) >= 8192:
            raise DependencyError('go-native-module-graph-invalid')
        owner, dependency = values
        dep_path, _, minimum = dependency.partition('@')
        owner_path = owner.partition('@')[0]
        if dep_path in {'go', 'toolchain'}:
            result.append({'owner': owner, 'dependency': dependency, 'selected': None, 'nativeToolchainDirective': True})
            continue
        module_path(owner_path)
        module_path(dep_path)
        if dep_path not in selected:
            raise DependencyError('go-native-selected-graph-not-closed')
        result.append({'owner': owner, 'dependency': dependency, 'minimumVersion': minimum,
                       'selected': module_id(selected[dep_path]), 'nativeToolchainDirective': False})
    nodes = []
    for row in sorted(modules, key=lambda value: value['Path']):
        replacement = row.get('Replace')
        nodes.append({'id': module_id(row), 'path': row['Path'], 'version': row.get('Version'),
            'main': bool(row.get('Main')), 'indirect': bool(row.get('Indirect')), 'goVersion': row.get('GoVersion'),
            'sum': row.get('Sum'), 'goModSum': row.get('GoModSum'),
            'replacement': {'path': replacement['Path'] if replacement.get('Version') else None, 'version': replacement.get('Version'),
                'localSourceIdentityDigest': digest(replacement['Dir'].encode()) if not replacement.get('Version') and replacement.get('Dir') else None}
                if replacement else None})
    return {'formatVersion': 1, 'module': root['Module']['Path'], 'goVersion': root.get('Go'),
            'toolchain': root.get('Toolchain'), 'exclusions': root.get('Exclude', []), 'nodes': nodes, 'edges': result}


def _mirror(source: Path, owned: Path) -> Path:
    source = source.resolve(strict=False)
    return owned / 'mirror' / (source.drive.replace(':', '') or 'posix') / Path(*source.parts[1:])


def resolve(project: Path, candidate: Path, *, go: Path | None = None, selected: dict | None = None,
            proxy_config: Path | None = None) -> dict:
    project = regular_path(project).resolve(strict=True)
    if candidate.exists():
        raise DependencyError('dependency-candidate-exists')
    selected = selection(selected)
    original = {name: read_bytes(project / name) for name in ('go.mod', 'go.sum')}
    expected_sums = sums(original['go.sum'])
    pins = json.loads(read_bytes(project / 'vendor/lsf/sdk/go-guest/toolchain.lock.json'))
    sdk_lock = json.loads(read_bytes(project / 'vendor/lsf/sdk/go-guest/runtime-deps/dependencies.lock.json'))
    recipe_before = file_identity(Path(__file__), 'go-module-capture-recipe')
    go = regular_path(go or Path(shutil.which('go') or 'missing-go')).resolve(strict=True)
    policy = json.loads(read_bytes(proxy_config)) if proxy_config else {'proxy': 'https://proxy.golang.org', 'sumdb': 'sum.golang.org'}
    if (not isinstance(policy, dict) or set(policy) - {'proxy', 'sumdb', 'private', 'authorizationEnv', 'username'}
            or not {'proxy', 'sumdb'} <= set(policy)):
        raise DependencyError('go-proxy-policy-invalid')
    proxy = urlsplit(policy['proxy'])
    if proxy.scheme != 'https' or not proxy.hostname or proxy.username or proxy.password or proxy.query or proxy.fragment:
        raise DependencyError('go-proxy-endpoint-invalid')
    if not isinstance(policy['sumdb'], str) or not re.fullmatch(r'(?:off|[a-zA-Z0-9.+/_=-]{1,512})', policy['sumdb']):
        raise DependencyError('go-checksum-policy-invalid')
    private = policy.get('private', [])
    if not isinstance(private, list) or len(private) > 32 or any(not isinstance(value, str)
            or not re.fullmatch(r'[A-Za-z0-9_./*?\[\]-]{1,512}', value) for value in private):
        raise DependencyError('go-private-module-policy-invalid')
    with tempfile.TemporaryDirectory(prefix='lsf-go-module-resolve-') as temporary:
        owned = Path(temporary)
        environment = build_environment(owned)
        environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', CGO_ENABLED='0', GOFLAGS='-mod=readonly',
            GOCACHE=str(owned / 'cache'), GOMODCACHE=str(owned / 'modules'), HOME=str(owned / 'home'),
            USERPROFILE=str(owned / 'home'), GOPROXY=policy['proxy'], GOSUMDB=policy['sumdb'],
            GOPRIVATE=','.join(private), GONOPROXY='none', GONOSUMDB=','.join(private), GOAUTH='netrc')
        if variable := policy.get('authorizationEnv'):
            username = policy.get('username', 'token')
            if (not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', variable) or not os.environ.get(variable)
                    or not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', username)):
                raise DependencyError('go-proxy-authorization-unavailable')
            secret = os.environ[variable]
            if not re.fullmatch(r'[^\s]{1,8192}', secret):
                raise DependencyError('go-proxy-authorization-format')
            netrc = owned / 'resolver.netrc'
            netrc.write_text('machine ' + proxy.hostname + ' login ' + username + ' password ' + secret + '\n')
            netrc.chmod(0o600)
            environment['NETRC'] = str(netrc)
        version = run_bounded([str(go), 'version'], owned, environment, 10, 16384).stdout.decode().strip()
        if version.split()[2:3] != [pins['go']['version']]:
            raise DependencyError('go-module-resolver-version-not-pinned')
        root = json.loads(run_bounded([str(go), 'mod', 'edit', '-json'], project, environment, 10, 1024 * 1024).stdout)
        module_path(root['Module']['Path'])
        if root.get('Tool'):
            raise DependencyError('go-executable-tool-declarations-require-approved-isolated-stage')
        work = _mirror(project, owned)
        work.mkdir(parents=True)
        for name, data in original.items():
            (work / name).write_bytes(data)
        locals_ = {}
        for replacement in root.get('Replace', []) or []:
            target = replacement['New']
            if target.get('Version'):
                module_path(target['Path'])
                continue
            source = (project / target['Path']).resolve(strict=False)
            destination = _mirror(source, owned)
            if source.exists():
                regular_path(source)
                for name, data in directory_files(source, exclude=('.git',)).items():
                    path = destination / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                locals_[source] = destination
            if Path(target['Path']).is_absolute():
                old = replacement['Old']['Path'] + ('@' + replacement['Old']['Version'] if replacement['Old'].get('Version') else '')
                run_bounded([str(go), 'mod', 'edit', '-replace=' + old + '=' + str(destination)], work, environment, 10, 16384)
        fetch_manifest = read_bytes(work / 'go.mod')
        modules = json_stream(run_bounded([str(go), 'list', '-m', '-json', 'all'], work, environment, 600, 16 * 1024 * 1024).stdout)
        downloads = json_stream(run_bounded([str(go), 'mod', 'download', '-json', 'all'], work, environment, 600, 16 * 1024 * 1024).stdout)
        if read_bytes(work / 'go.sum') != original['go.sum'] or read_bytes(work / 'go.mod') != fetch_manifest:
            raise DependencyError('go-native-declarations-or-sums-not-locked')
        edges = run_bounded([str(go), 'mod', 'graph'], work, environment, 60, 2 * 1024 * 1024).stdout.decode()
        native = graph(modules, edges, root)
        downloads_by_key = {(row['Path'], row['Version']): row for row in downloads}
        store, artifacts = Store(project / 'dependency-inputs/objects'), []
        cache, cache_files = owned / 'captured-downloads', {}
        cache.mkdir()
        selected_local = {}
        for row in sorted(modules, key=lambda item: item['Path']):
            if row.get('Main'):
                continue
            effective = row.get('Replace') or row
            local = bool(row.get('Replace') and not effective.get('Version'))
            identifier = module_id(row)
            if local:
                directory = regular_path(Path(effective['Dir']))
                if not directory.is_relative_to(owned):
                    raise DependencyError('go-local-module-outside-owned-fetch')
                selected_local[row['Path']] = (identifier, row.get('Version'))
                original_path = next((source for source, destination in locals_.items() if destination == directory), None)
                if original_path is None:
                    raise DependencyError('go-local-replacement-not-in-native-declarations')
                native_row = next(value for value in native['nodes'] if value['id'] == identifier)
                native_row['replacement']['localSourceIdentityDigest'] = digest(str(original_path).encode())
                files = directory_files(directory)
                if directory_files(original_path, exclude=('.git',)) != files:
                    raise DependencyError('go-local-module-mutated-during-resolution')
                module_sum, mod_sum = None, None
            else:
                downloaded = downloads_by_key.get((effective['Path'], effective['Version']))
                if downloaded is None:
                    raise DependencyError('go-selected-module-download-missing')
                _, files = verify_download(downloaded, expected_sums)
                directory = Path(downloaded['Dir'])
                module_sum, mod_sum = downloaded['Sum'], downloaded['GoModSum']
                for field in ('Info', 'GoMod', 'Zip'):
                    path = regular_path(Path(downloaded[field]))
                    relative = path.relative_to(owned / 'modules/cache/download').as_posix()
                    cache_files[relative] = read_bytes(path)
                zip_hash = Path(downloaded['Zip']).with_suffix('.ziphash')
                if read_bytes(zip_hash).decode().strip() != module_sum:
                    raise DependencyError('go-native-ziphash-mismatch')
                cache_files[zip_hash.relative_to(owned / 'modules/cache/download').as_posix()] = read_bytes(zip_hash)
            baseline = next((value for value in sdk_lock['modules'] if value['path'] == row['Path']), None)
            if baseline and (row.get('Replace') or row.get('Version') != baseline['version'] or module_sum != baseline['sum']
                    or mod_sum != baseline['goModSum']):
                raise DependencyError('go-application-overrides-immutable-sdk-runtime-module')
            artifacts.append({'id': identifier, 'role': 'runtime' if baseline else 'application', 'format': 'directory',
                'mount': 'dependencies/go-modules/' + identifier.rpartition('/')[2], 'source': {'path': str(directory)},
                'dependencies': [], 'metadata': {'ecosystem': 'go', 'assetType': 'local-module' if local else 'selected-module-source',
                    'module': row['Path'], 'version': row.get('Version'), 'sum': module_sum, 'goModSum': mod_sum,
                    'localSourceIdentityDigest': digest(str(original_path).encode()) if local else None,
                    'effectiveModule': effective['Path'] if not local else None, 'effectiveVersion': effective.get('Version'),
                    'sdkRuntimeInput': bool(baseline), 'sourceFilesDigest': tree_identity([
                        {'path': name, 'digest': digest(data), 'size': len(data)} for name, data in sorted(files.items())])}})
        for row in artifacts:
            owners = [edge for edge in native['edges'] if edge['owner'].partition('@')[0] == row['metadata']['module']]
            row['dependencies'] = sorted({edge['selected'] for edge in owners if edge['selected'] and edge['selected'] != row['id']})
        for name, data in cache_files.items():
            path = cache / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        cache_id = 'go-downloads/' + digest(original['go.sum'])[7:31]
        artifacts.append({'id': cache_id, 'role': 'application', 'format': 'directory', 'mount': 'dependencies/go-downloads',
            'source': {'path': str(cache)}, 'dependencies': [row['id'] for row in artifacts],
            'metadata': {'ecosystem': 'go', 'assetType': 'selected-module-downloads', 'networkResolution': 'explicit-capture-only'}})
        staged = owned / 'selected-root'
        staged.mkdir()
        (staged / 'go.mod').write_bytes(original['go.mod'])
        for replacement in root.get('Replace', []) or []:
            if replacement['New'].get('Version'):
                continue
            old = replacement['Old']
            old_identity = old['Path'] + ('@' + old['Version'] if old.get('Version') else '')
            selected_row = selected_local.get(old['Path'])
            if selected_row and (not old.get('Version') or old['Version'] == selected_row[1]):
                target = './dependencies/go-modules/' + selected_row[0].rpartition('/')[2]
            else:
                target = './dependencies/go-unselected/' + digest(canonical(replacement))[7:31]
            run_bounded([str(go), 'mod', 'edit', '-replace=' + old_identity + '=' + target], staged, environment, 10, 16384)
        transformed = read_bytes(staged / 'go.mod')
        root_id = 'go-project/' + digest(original['go.mod'])[7:31]
        artifacts.append({'id': root_id, 'role': 'generated', 'format': 'file', 'mount': 'application-vendor/go-project/go.mod',
            'source': {'path': str(project / 'go.mod')}, 'dependencies': [row['id'] for row in artifacts],
            'metadata': {'ecosystem': 'go', 'assetType': 'selected-root-module'}})
        transforms = []
        if transformed != original['go.mod']:
            reference = store.put(transformed)
            before = [{'path': 'go.mod', 'digest': digest(original['go.mod']), 'size': len(original['go.mod'])}]
            after = [{'path': 'go.mod', 'digest': digest(transformed), 'size': len(transformed)}]
            transforms.append({'id': 'go-local-replacement-relocation/' + digest(original['go.mod'])[7:31], 'artifact': root_id,
                'inputDigest': tree_identity(before), 'outputDigest': tree_identity(after),
                'files': [{'path': 'go.mod', 'inputDigest': digest(original['go.mod']), 'source': str(store.path(reference['digest'])),
                           'outputDigest': reference['digest']}], 'tool': file_identity(go, 'go-mod-edit'), 'selection': selected})
        native.update(selection=selected, resolverGo=file_identity(go, 'native-module-resolver'), resolverVersion=version,
            recipe=recipe_before, policyDigest=digest(canonical(policy)), originalManifestDigest=digest(original['go.mod']),
            fetchManifestDigest=digest(fetch_manifest), selectedManifestDigest=digest(transformed),
            nativeSumDigest=digest(original['go.sum']), generatedCommands='never-executed',
            downloadSourceIdentityDigest=digest(canonical([{key: row.get(key) for key in ('Path', 'Version', 'Sum', 'GoModSum', 'Origin')}
                for row in downloads])))
        (project / 'go-resolved.lock.json').write_bytes(canonical(native) + b'\n')
        manifest = {'formatVersion': 1, 'language': 'go', 'selection': selected,
            'nativeLocks': ['go.mod', 'go.sum', 'go-resolved.lock.json'], 'artifacts': artifacts, 'transformations': transforms}
        validate_manifest(manifest, 'go')
        (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
        result = capture(project)
        if original != {name: read_bytes(project / name) for name in original} or file_identity(Path(__file__), 'go-module-capture-recipe') != recipe_before:
            raise DependencyError('go-declaration-lock-or-capture-recipe-mutated')
        candidate.parent.mkdir(parents=True, exist_ok=True)
        with candidate.open('xb') as output:
            output.write(canonical(result) + b'\n')
        return result


def configure(closure, generated: Path) -> dict:
    chosen = selection(closure.lock['selection'])
    root = [row for row in closure.lock['artifacts'] if row['metadata'].get('assetType') == 'selected-root-module']
    caches = [row for row in closure.lock['artifacts'] if row['metadata'].get('assetType') == 'selected-module-downloads']
    if len(root) != 1 or len(caches) != 1:
        raise DependencyError('go-selected-root-or-download-closure-missing')
    (generated / 'go.mod').write_bytes(read_bytes(closure.work / root[0]['mount']))
    (generated / 'go.sum').write_bytes(read_bytes(closure.work / 'go.sum'))
    for row in closure.lock['artifacts']:
        if row['metadata'].get('assetType') != 'local-module':
            continue
        for name, data in directory_files(closure.work / row['mount']).items():
            target = generated / row['mount'] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    native = json.loads(read_bytes(closure.work / 'go-resolved.lock.json'))
    if native['selection'] != chosen or native['selectedManifestDigest'] != digest(read_bytes(generated / 'go.mod')):
        raise DependencyError('go-selected-build-module-identity-mismatch')
    return {**chosen, 'module': native['module'], 'downloadCache': str(closure.work / caches[0]['mount']),
            'inputIdentity': closure.identity, 'generators': 'never-executed', 'cgo': False}
