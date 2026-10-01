"""Reviewed NuGet declarations, native asset selection and original packages."""
from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import re
import struct
import tempfile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from tools.application_dependencies import MANIFEST, capture
from tools.application_dependency_store import DependencyError, Store, archive_files, directory_files, path_name, read_bytes, regular_path
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import snapshot

PROFILE = 'dotnet-native-aot-component-v1'
PROJECT = 'Capsule.csproj'
LOCK = 'packages.lock.json'
ASSETS = 'nuget-resolved.lock.json'
IMPORT_GUARDS = ('ImportDirectoryBuildProps', 'ImportDirectoryBuildTargets',
                 'ImportProjectExtensionProps', 'ImportProjectExtensionTargets',
                 'ImportUserLocationsByWildcardBeforeMicrosoftCommonProps', 'ImportUserLocationsByWildcardAfterMicrosoftCommonProps',
                 'ImportUserLocationsByWildcardBeforeMicrosoftCommonTargets', 'ImportUserLocationsByWildcardAfterMicrosoftCommonTargets')


def selection(value: dict | None = None) -> dict:
    value = dict(value or {})
    expected = {'framework': 'net10.0', 'runtimeIdentifier': 'wasi-wasm', 'runtimeProfile': PROFILE}
    if set(value) - expected.keys() or any(value.get(key, expected[key]) != expected[key] for key in expected):
        raise DependencyError('dotnet-runtime-framework-profile-not-installed')
    return expected


def xml(data: bytes) -> ET.Element:
    if len(data) > 1024 * 1024 or b'<!' in data:
        raise DependencyError('dotnet-project-xml-declaration-denied')
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise DependencyError('dotnet-project-xml-invalid') from None


def _shape(node: ET.Element):
    return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(), tuple(_shape(child) for child in node))


def condition(value: str | None, selected: dict) -> bool:
    if value is None:
        return True
    clauses = re.split(r'\s+[Aa][Nn][Dd]\s+', value.strip())
    if not clauses or len(clauses) > 4:
        raise DependencyError('dotnet-project-condition-not-reviewed')
    matched = []
    for clause in clauses:
        parsed = re.fullmatch(r"'\$\((TargetFramework|RuntimeIdentifier)\)'\s*(==|!=)\s*'([A-Za-z0-9._-]{1,64})'", clause)
        if not parsed:
            raise DependencyError('dotnet-project-condition-not-reviewed')
        key = {'TargetFramework': 'framework', 'RuntimeIdentifier': 'runtimeIdentifier'}[parsed[1]]
        equal = selected[key] == parsed[3]
        matched.append(equal if parsed[2] == '==' else not equal)
    return all(matched)


def declarations(files: dict[str, bytes], selected: dict | None = None) -> dict:
    """Extend only the maintained project; never evaluate application MSBuild."""
    from tools.dotnet_guest.project import project_xml
    selected = selection(selected)
    template = xml(project_xml(files['vendor/lsf/sdk/dotnet-guest/probes/smoke/Smoke.csproj']))
    root = xml(files[PROJECT])
    if root.tag != 'Project' or root.attrib != template.attrib:
        raise DependencyError('dotnet-project-sdk-not-reviewed')
    baseline = [_shape(node) for group in template for node in group]
    remaining = list(baseline)
    packages, resources, descriptors = [], [], []
    for group in root:
        if group.tag not in {'PropertyGroup', 'ItemGroup'} or group.attrib:
            raise DependencyError('dotnet-project-build-target-not-reviewed')
        for node in group:
            shape = _shape(node)
            if shape in remaining:
                remaining.remove(shape)
                continue
            if group.tag != 'ItemGroup' or node.tag not in {'PackageReference', 'EmbeddedResource', 'TrimmerRootDescriptor'}:
                raise DependencyError('dotnet-project-input-outside-reviewed-recipe')
            fields = dict(node.attrib)
            for child in node:
                if child.attrib or list(child) or child.tag in fields:
                    raise DependencyError('dotnet-project-item-metadata-invalid')
                fields[child.tag] = (child.text or '').strip()
            if node.text and node.text.strip():
                raise DependencyError('dotnet-project-item-metadata-invalid')
            active = condition(fields.pop('Condition', None), selected)
            if node.tag == 'PackageReference':
                if set(fields) - {'Include', 'Version', 'IncludeAssets', 'ExcludeAssets', 'PrivateAssets'} or not {'Include', 'Version'} <= fields.keys():
                    raise DependencyError('dotnet-package-reference-not-reviewed')
                package_name(fields['Include'])
                if not re.fullmatch(r'[A-Za-z0-9.\[\](), +_-]{1,256}', fields['Version']) or '$' in fields['Version']:
                    raise DependencyError('dotnet-package-version-not-native-literal')
                for key in ('IncludeAssets', 'ExcludeAssets', 'PrivateAssets'):
                    if key in fields and any(item.lower() not in {'all', 'none', 'compile', 'runtime', 'native', 'contentfiles', 'build', 'buildmultitargeting', 'buildtransitive', 'analyzers'}
                                             for item in fields[key].split(';')):
                        raise DependencyError('dotnet-package-asset-policy-invalid')
                packages.append({'attributes': fields, 'active': active})
            else:
                allowed = {'Include', 'LogicalName'} if node.tag == 'EmbeddedResource' else {'Include'}
                if set(fields) - allowed or 'Include' not in fields:
                    raise DependencyError('dotnet-resource-item-not-reviewed')
                source = path_name(fields['Include'])
                if source not in files or source.startswith(('vendor/', 'dependency-inputs/')):
                    raise DependencyError('dotnet-resource-input-not-captured')
                if 'LogicalName' in fields and (not 0 < len(fields['LogicalName']) <= 512 or any(c in fields['LogicalName'] for c in '\0\r\n$')):
                    raise DependencyError('dotnet-resource-logical-name-invalid')
                (resources if node.tag == 'EmbeddedResource' else descriptors).append({'attributes': fields, 'active': active,
                    'digest': digest(files[source]), 'size': len(files[source])})
    if remaining:
        raise DependencyError('dotnet-project-sdk-compiler-input-mutated')
    if len(packages) > 256 or len(resources) > 256 or len(descriptors) > 64 or sum(row['size'] for row in resources + descriptors) > 32 * 1024 * 1024:
        raise DependencyError('dotnet-project-declaration-limit')
    names = [row['attributes']['Include'].lower() for row in packages if row['active']]
    if len(names) != len(set(names)):
        raise DependencyError('dotnet-package-reference-ambiguous')
    return {'selection': selected, 'packages': packages, 'resources': resources, 'trimmingDescriptors': descriptors}


def package_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', value):
        raise DependencyError('nuget-package-identity-invalid')
    return value.lower()


def executable_resources(declared: dict, files: dict[str, bytes]) -> list[dict]:
    """ResX compilation can instantiate ResourceReader/types during MSBuild."""
    specs = []
    for row in declared['resources']:
        source = row['attributes']['Include']
        if not row['active'] or not source.lower().endswith('.resx'):
            continue
        identity = digest(canonical({'path': source, 'digest': row['digest']}))
        if digest(files[source]) != row['digest']:
            raise DependencyError('dotnet-executable-resource-preimage-mismatch')
        specs.append({'id': 'msbuild-resource/' + identity, 'role': 'build-tool', 'format': 'file',
            'mount': 'dependencies/msbuild-resources/' + identity + '/' + Path(source).name,
            'source': {'path': source}, 'dependencies': [], 'metadata': {'ecosystem': 'msbuild-resource',
                'source': source, 'originalDigest': row['digest'], 'originalSize': row['size'],
                'selection': declared['selection']}})
    return specs


def coordinate(value: str) -> tuple[str, str]:
    name, separator, version = value.partition('/')
    if not separator or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}', version):
        raise DependencyError('nuget-package-coordinate-invalid')
    return package_name(name), version.lower()


def sdk_packages(lock: dict) -> dict[str, dict]:
    result = {}
    for target in lock['dependencies'].values():
        for name, row in target.items():
            identity = package_name(name) + '/' + row['resolved'].lower()
            if identity in result and result[identity]['contentHash'] != row['contentHash']:
                raise DependencyError('nuget-sdk-baseline-ambiguous')
            result[identity] = row
    return result


def managed_image(data: bytes) -> None:
    """Selected assembly must have a real bounded PE/CLI header."""
    try:
        if data[:2] != b'MZ' or len(data) < 64:
            raise ValueError()
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        if data[pe:pe + 4] != b'PE\0\0':
            raise ValueError()
        optional_size = struct.unpack_from('<H', data, pe + 20)[0]
        optional = pe + 24
        magic = struct.unpack_from('<H', data, optional)[0]
        start, count = {0x10b: (96, 92), 0x20b: (112, 108)}[magic]
        if optional + optional_size > len(data) or optional_size < start + 15 * 8 or struct.unpack_from('<I', data, optional + count)[0] <= 14:
            raise ValueError()
        rva, size = struct.unpack_from('<II', data, optional + start + 14 * 8)
        if not rva or size < 72:
            raise ValueError()
    except (ValueError, KeyError, struct.error):
        raise DependencyError('nuget-selected-assembly-missing-managed-cli-header') from None


def analyze(lock: dict, assets: dict, baseline: dict, declared: dict) -> dict:
    if lock.get('version') != 1 or assets.get('version') != 3:
        raise DependencyError('nuget-native-lock-assets-version-invalid')
    selected_targets = {'net10.0', 'net10.0/wasi-wasm'}
    if set(lock.get('dependencies', {})) - selected_targets or set(assets.get('targets', {})) != selected_targets:
        raise DependencyError('nuget-native-framework-runtime-selection-invalid')
    sdk = sdk_packages(baseline)
    native = {}
    for target, packages in lock['dependencies'].items():
        for name, row in packages.items():
            identity = package_name(name) + '/' + row['resolved'].lower()
            if row.get('type') not in {'Direct', 'Transitive'} or not isinstance(row.get('contentHash'), str):
                raise DependencyError('nuget-native-dependency-unresolved')
            try:
                if len(base64.b64decode(row['contentHash'], validate=True)) != 64:
                    raise ValueError()
            except ValueError:
                raise DependencyError('nuget-native-content-hash-invalid') from None
            if identity in native and native[identity]['contentHash'] != row['contentHash']:
                raise DependencyError('nuget-native-content-hash-conflict')
            native[identity] = row
            if package_name(name) in {coordinate(value)[0] for value in sdk} and (identity not in sdk or sdk[identity]['contentHash'] != row['contentHash']):
                raise DependencyError('nuget-sdk-compiler-runtime-lock-mutated')
    if set(sdk) - native.keys():
        raise DependencyError('nuget-sdk-compiler-runtime-closure-missing')
    libraries = assets.get('libraries', {})
    if {key.lower() for key in libraries} != native.keys() or any(row.get('type') != 'package' for row in libraries.values()):
        raise DependencyError('nuget-native-selected-graph-not-closed')
    rows = {}
    for original, library in sorted(libraries.items()):
        identity = original.lower()
        name, version = coordinate(identity)
        if library.get('sha512') != native[identity]['contentHash'] or library.get('path') != identity:
            raise DependencyError('nuget-native-asset-package-identity-mismatch')
        files = library.get('files', [])
        if not isinstance(files, list) or len(files) > 8192 or len(files) != len(set(files)):
            raise DependencyError('nuget-native-asset-file-limit')
        for item in files:
            path_name(item)
        rows[identity] = {'package': name, 'version': version, 'contentHash': library['sha512'],
                          'sdk': identity in sdk, 'files': files, 'targets': {}, 'dependencies': [], 'executableAssets': []}
    for target, packages in sorted(assets['targets'].items()):
        target_by_name = {coordinate(key)[0]: key.lower() for key in packages}
        for original, value in sorted(packages.items()):
            identity = original.lower()
            if identity not in rows:
                raise DependencyError('nuget-native-selected-graph-not-closed')
            selected_assets = {key: value[key] for key in ('compile', 'runtime', 'native', 'runtimeTargets', 'build', 'buildMultiTargeting', 'contentFiles', 'frameworkAssemblies') if key in value}
            for kind, selected in selected_assets.items():
                if kind == 'frameworkAssemblies':
                    continue
                if not isinstance(selected, dict):
                    raise DependencyError('nuget-native-assets-invalid')
                for asset in selected:
                    path_name(asset)
                    if asset not in rows[identity]['files']:
                        raise DependencyError('nuget-selected-asset-missing-from-original-package')
                    if kind in {'build', 'buildMultiTargeting'} or (kind == 'contentFiles'
                            and selected[asset].get('buildAction') == 'EmbeddedResource' and asset.lower().endswith('.resx')):
                        rows[identity]['executableAssets'].append(asset)
            rows[identity]['targets'][target] = selected_assets
            for dependency, requested in sorted(value.get('dependencies', {}).items()):
                child = target_by_name.get(package_name(dependency))
                if child is None:
                    raise DependencyError('nuget-native-selected-graph-not-closed')
                rows[identity]['dependencies'].append({'target': target, 'id': child, 'requested': requested})
    for identity, row in rows.items():
        direct = next((item['attributes'] for item in declared['packages'] if item['active'] and package_name(item['attributes']['Include']) == row['package']), {})
        include = set(direct.get('IncludeAssets', 'all').lower().split(';'))
        exclude = set(direct.get('ExcludeAssets', 'none').lower().split(';'))
        if ('all' in include or 'analyzers' in include) and not {'all', 'analyzers'} & exclude:
            row['executableAssets'] += [name for name in row['files'] if name.startswith('analyzers/') and name.endswith('.dll')]
        row['executableAssets'] = sorted(set(row['executableAssets']))
    return {'formatVersion': 1, **declared, 'packages': list(rows.values()), 'sdkBaselineDigest': digest(canonical(baseline))}


def resolver_project(files: dict[str, bytes]) -> bytes:
    declared = declarations(files)
    root = xml(files[PROJECT])
    # Only immutable SDK/compiler properties and reviewed item declarations
    # reached this point. Never import the application's obj/props/targets.
    group = ET.SubElement(root, 'PropertyGroup')
    for key in IMPORT_GUARDS:
        ET.SubElement(group, key).text = 'false'
    ET.SubElement(group, 'NuGetAudit').text = 'false'
    ET.SubElement(group, 'EnableDefaultItems').text = 'false'
    return ET.tostring(root, encoding='utf-8')


def feed_config(policy: dict | None, owned: Path, sdk_configuration: bytes) -> tuple[bytes, dict]:
    baseline = xml(sdk_configuration)
    baseline_sources = [{'name': row.attrib['key'], 'url': row.attrib['value']} for row in baseline.find('packageSources') if row.tag == 'add']
    policy = policy or {'sources': []}
    if set(policy) != {'sources'} or not isinstance(policy['sources'], list) or not 1 <= len(policy['sources']) <= 8:
        if policy != {'sources': []}:
            raise DependencyError('nuget-explicit-feed-policy-invalid')
    root = ET.Element('configuration')
    sources = ET.SubElement(root, 'packageSources')
    ET.SubElement(sources, 'clear')
    credentials = ET.SubElement(root, 'packageSourceCredentials')
    identities, seen = [], set()
    mappings = copy.deepcopy(baseline.find('packageSourceMapping'))
    for row in baseline_sources + policy['sources']:
        if set(row) - {'name', 'url', 'path', 'authorizationEnv', 'username', 'patterns'} or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', row.get('name', '')) or row['name'] in seen:
            raise DependencyError('nuget-explicit-feed-policy-invalid')
        seen.add(row['name'])
        if ('url' in row) == ('path' in row):
            raise DependencyError('nuget-explicit-feed-policy-invalid')
        if 'path' in row:
            source = regular_path(Path(row['path'])).resolve(strict=True)
            target = owned / 'local-feeds' / row['name']
            for name, content in directory_files(source).items():
                if not name.lower().endswith('.nupkg'):
                    raise DependencyError('nuget-local-feed-must-contain-only-package-archives')
                archive_files(content, 'zip')
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            value = str(target)
            identity = digest(canonical({name: digest(content) for name, content in directory_files(target).items()}))
        else:
            parsed = urlsplit(row['url'])
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
                raise DependencyError('nuget-explicit-feed-endpoint-invalid')
            value, identity = row['url'], digest(row['url'].encode())
        ET.SubElement(sources, 'add', {'key': row['name'], 'value': value})
        if row in policy['sources']:
            patterns = row.get('patterns', ['*'])
            if not isinstance(patterns, list) or not 1 <= len(patterns) <= 64 or any(not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_.*-]{1,100}', item) for item in patterns):
                raise DependencyError('nuget-explicit-feed-mapping-invalid')
            mapping = ET.SubElement(mappings, 'packageSource', {'key': row['name']})
            for pattern in patterns:
                ET.SubElement(mapping, 'package', {'pattern': pattern})
        if 'authorizationEnv' in row:
            key = row['authorizationEnv']
            secret = os.environ.get(key) if isinstance(key, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', key) else None
            if not secret or any(char in secret for char in '\0\r\n'):
                raise DependencyError('nuget-explicit-feed-credential-missing')
            credential = ET.SubElement(credentials, row['name'])
            ET.SubElement(credential, 'add', {'key': 'Username', 'value': row.get('username', 'token')})
            ET.SubElement(credential, 'add', {'key': 'ClearTextPassword', 'value': secret})
        identities.append({'name': row['name'], 'kind': 'local' if 'path' in row else 'https', 'sourceIdentityDigest': identity})
    root.append(mappings)
    return ET.tostring(root, encoding='utf-8'), {'sources': identities}


def resolve(project: Path, candidate: Path, *, dotnet: Path, tools: Path, policy: dict | None = None, update_lock: bool = False) -> dict:
    project, dotnet, tools = regular_path(project).resolve(strict=True), regular_path(dotnet).resolve(strict=True), regular_path(tools).resolve(strict=True)
    candidate = regular_path(candidate)
    if candidate.exists() or candidate == project / 'latent.dependencies.lock.json':
        raise DependencyError('nuget-resolve-requires-new-review-candidate')
    files = snapshot(project)
    declared = declarations(files)
    baseline = json.loads(files['vendor/lsf/sdk/dotnet-guest/probes/smoke/packages.lock.json'])
    if snapshot(tools / 'package-hash-source') != snapshot(project / 'vendor/lsf/sdk/dotnet-guest/tools/package-hash'):
        raise DependencyError('nuget-content-hash-helper-source-not-sdk-owned')
    with tempfile.TemporaryDirectory(prefix='lsf-nuget-resolve-') as temporary:
        owned = Path(temporary)
        environment = build_environment(owned)
        environment.update(HOME=str(owned / 'home'), USERPROFILE=str(owned / 'home'), DOTNET_CLI_HOME=str(owned / 'home'),
            DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1', DOTNET_ROLL_FORWARD='Disable',
            DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE='true',
            DOTNET_CLI_USE_MSBUILD_SERVER='0', MSBUILDDISABLENODEREUSE='1', NUGET_PACKAGES=str(owned / 'packages'),
            NUGET_HTTP_CACHE_PATH=str(owned / 'http-cache'), NUGET_PLUGINS_CACHE_PATH=str(owned / 'plugin-cache'))
        if run_bounded([str(dotnet), '--version'], owned, environment, 10, 16384).stdout.strip() != b'10.0.100':
            raise DependencyError('nuget-resolver-sdk-version-not-pinned')
        (owned / 'global.json').write_bytes(files['global.json'])
        config, source_policy = feed_config(policy, owned, files['vendor/lsf/sdk/dotnet-guest/nuget.config'])
        (owned / 'nuget.config').write_bytes(config)
        (owned / PROJECT).write_bytes(resolver_project(files))
        existing = files.get(LOCK)
        if existing and not update_lock:
            (owned / LOCK).write_bytes(existing)
        run_bounded([str(dotnet), 'restore', str(owned / PROJECT), '--configfile', str(owned / 'nuget.config'),
            '--packages', str(owned / 'packages'), '--disable-parallel', '--locked-mode' if existing and not update_lock else '--force-evaluate',
            '-p:NuGetAudit=false', *['-p:' + key + '=false' for key in IMPORT_GUARDS]], owned, environment, 600, 4 * 1024 * 1024)
        lock_bytes, assets_bytes = read_bytes(owned / LOCK), read_bytes(owned / 'obj/project.assets.json', 16 * 1024 * 1024)
        native = analyze(json.loads(lock_bytes), json.loads(assets_bytes), baseline, declared)
        native['assets'] = {key: json.loads(assets_bytes)[key] for key in ('version', 'targets', 'libraries')}
        native['fetchPolicy'] = source_policy
        helper = tools / 'package-hash/PackageHash.dll'
        native['resolver'] = {'dotnet': file_identity(dotnet, 'dotnet'), 'contentHashHelper': file_identity(helper, 'nuget-content-hash-helper')}
        specs = executable_resources(declared, files)
        for row in native['packages']:
            if row['sdk']:
                continue  # Exact immutable SDK package closure is compiler-owned.
            identity = row['package'] + '/' + row['version']
            archive = owned / 'packages' / identity / (row['package'] + '.' + row['version'] + '.nupkg')
            original = read_bytes(archive)
            entries = archive_files(original, 'zip')
            actual = run_bounded([str(dotnet), str(helper), str(archive)], owned, environment, 30, 16384).stdout.decode().strip()
            if actual != row['contentHash']:
                raise DependencyError('nuget-original-content-hash-not-native-lock')
            for target in row['targets'].values():
                for kind in ('compile', 'runtime'):
                    for name in target.get(kind, {}):
                        if name.endswith('.dll'):
                            if name not in entries:
                                raise DependencyError('nuget-selected-asset-missing-from-original-package')
                            managed_image(entries[name])
                if target.get('native') or any(value.get('assetType') == 'native' for value in target.get('runtimeTargets', {}).values()):
                    raise DependencyError('nuget-selected-native-asset-runtime-abi-unavailable')
            row['originalDigest'] = digest(original)
            row['originalSize'] = len(original)
            dependencies = sorted({edge['id'] for edge in row['dependencies'] if not next(item for item in native['packages'] if item['package'] + '/' + item['version'] == edge['id'])['sdk']})
            specs.append({'id': identity, 'role': 'build-tool' if row['executableAssets'] else 'application',
                'format': 'zip', 'mount': 'dependencies/nuget/' + identity, 'source': {'path': str(archive)},
                'dependencies': dependencies, 'metadata': {'ecosystem': 'nuget', **row}})
        # Native assets retain no machine-specific restore/project/cache paths.
        (project / LOCK).write_bytes(lock_bytes)
        (project / ASSETS).write_bytes(canonical(native) + b'\n')
        manifest = {'formatVersion': 1, 'language': 'dotnet', 'selection': declared['selection'],
            'nativeLocks': [PROJECT, 'global.json', LOCK, ASSETS], 'artifacts': specs, 'transformations': []}
        (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
        captured = capture(project)
        # Only resolver locations existed temporarily; every original is now CAS-bound.
        store = Store(project / 'dependency-inputs/objects')
        for row in manifest['artifacts']:
            row['source'] = {'path': store.path(row['metadata']['originalDigest']).relative_to(project).as_posix()}
        (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
        captured = capture(project)
        if any(snapshot(project).get(name) != value for name, value in files.items() if name not in {LOCK, ASSETS, MANIFEST}):
            raise DependencyError('nuget-application-input-mutated-during-resolution')
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(canonical(captured) + b'\n')
        return captured


def configure(closure, project: Path, packages: Path) -> dict:
    files = snapshot(project, exclude=('dependencies', 'application-vendor'))
    declared = declarations(files, closure.lock['selection'])
    native = json.loads(read_bytes(closure.project / ASSETS, 16 * 1024 * 1024))
    baseline = json.loads(read_bytes(project / 'vendor/lsf/sdk/dotnet-guest/probes/smoke/packages.lock.json'))
    if native['selection'] != declared['selection'] or native['sdkBaselineDigest'] != digest(canonical(baseline)):
        raise DependencyError('nuget-native-selection-or-sdk-baseline-drift')
    expected = analyze(json.loads(read_bytes(closure.project / LOCK)), native['assets'], baseline, declared)
    normalized = [{key: value for key, value in row.items() if key not in {'originalDigest', 'originalSize'}} for row in native['packages']]
    if normalized != expected['packages'] or any(native[key] != expected[key] for key in ('resources', 'trimmingDescriptors')):
        raise DependencyError('nuget-native-assets-or-resource-selection-drift')
    active = [row for row in native['packages'] if not row['sdk']]
    rows = {row['id']: row for row in closure.lock['artifacts']}
    resource_specs = executable_resources(declared, files)
    if set(rows) != {row['package'] + '/' + row['version'] for row in active} | {row['id'] for row in resource_specs}:
        raise DependencyError('nuget-captured-package-closure-not-native-selection')
    for spec in resource_specs:
        artifact = rows[spec['id']]
        if (artifact['role'] != 'build-tool' or artifact['mount'] != spec['mount'] or artifact['metadata'] != spec['metadata']
                or artifact['original'] != {'digest': spec['metadata']['originalDigest'], 'size': spec['metadata']['originalSize']}):
            raise DependencyError('dotnet-executable-resource-not-selected-original')
    layouts = []
    for row in active:
        identity = row['package'] + '/' + row['version']
        artifact = rows[identity]
        if (artifact['role'] != ('build-tool' if row['executableAssets'] else 'application')
                or artifact['metadata'] != {'ecosystem': 'nuget', **row} or artifact['original']['digest'] != row['originalDigest']):
            raise DependencyError('nuget-captured-package-not-native-original')
        source = closure.work / artifact['mount']
        destination = packages / identity
        if destination.exists():
            raise DependencyError('nuget-offline-cache-package-collision')
        destination.mkdir(parents=True)
        contents = directory_files(source)
        nuspec = [name for name in contents if '/' not in name and name.lower().endswith('.nuspec')]
        if len(nuspec) != 1 or nuspec[0].lower() != row['package'] + '.nuspec':
            raise DependencyError('nuget-original-manifest-name-not-native-package')
        for name, data in contents.items():
            selected_name = row['package'] + '.nuspec' if name == nuspec[0] else name
            target = destination / selected_name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise DependencyError('nuget-offline-native-layout-collision')
            target.write_bytes(data)
            if name != selected_name:
                layouts.append({'owner': identity, 'operation': 'nuget-native-lowercase-manifest-path-v1',
                    'originalPath': name, 'selectedPath': selected_name, 'originalDigest': digest(data),
                    'selectedDigest': digest(data), 'size': len(data)})
        archive = row['package'] + '.' + row['version'] + '.nupkg'
        (destination / archive).write_bytes(closure.store.get(**artifact['original']))
        (destination / (archive + '.sha512')).write_text(row['contentHash'], encoding='ascii')
        (destination / '.nupkg.metadata').write_bytes(canonical({'version': 2, 'contentHash': row['contentHash'], 'source': 'captured-offline-closure'}))
    return {'formatVersion': 1, 'inputIdentity': closure.identity, **declared,
            'nativeSelectionDigest': digest(read_bytes(closure.project / ASSETS)),
            'automaticLayoutTransformations': layouts,
            'originalPackages': [{'id': row['package'] + '/' + row['version'], 'digest': row['originalDigest'],
                                  'contentHash': row['contentHash'], 'targets': row['targets']} for row in active]}
