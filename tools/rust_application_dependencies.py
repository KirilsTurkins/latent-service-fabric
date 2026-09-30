"""Native Cargo graph/vendor capture and offline selected-manifest staging."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib
from urllib.parse import parse_qs, urlsplit

from tools.application_dependencies import LOCK, MANIFEST, capture, validate_manifest
from tools.application_dependency_store import DependencyError, Store, directory_files, read_bytes, regular_path, tree_identity
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import ROOT, snapshot


def package_identity(package: dict) -> str:
    return package['name'] + '/' + package['version'] + '/' + digest(package['id'].encode())[7:23]


def selected_manifest(data: bytes, original: Path, mapped: Path, mappings: dict[Path, Path]) -> bytes:
    """Preserve Cargo syntax while relocating only observed path dependencies."""
    tomllib.loads(data.decode('utf-8'))
    pattern = re.compile(r'(?<![A-Za-z_])path\s*=\s*("(?:[^"\\]|\\.)*"|\x27[^\x27]*\x27)')
    def replacement(match):
        value = tomllib.loads('value = ' + match[1])['value']
        destination = (original.parent / value).resolve(strict=False)
        selected = mappings.get(destination)
        if selected is None and destination.is_relative_to(original.parent):
            return match[0]
        if selected is None:
            # Paths to an in-tree file remain valid; all external roots must be
            # an actual native-resolver selected package.
            raise DependencyError('cargo-path-dependency-not-in-selected-graph')
        relative = os.path.relpath(selected, mapped.parent).replace('\\', '/')
        return 'path = ' + json.dumps(relative)
    return pattern.sub(replacement, data.decode('utf-8')).encode('utf-8')


def analyze(metadata: dict, root: Path, vendor: Path, pins: dict) -> tuple[list[dict], dict]:
    if (not isinstance(metadata, dict) or metadata.get('version') != 1 or not isinstance(metadata.get('packages'), list)
            or not isinstance(metadata.get('resolve'), dict) or len(metadata['packages']) > 1024):
        raise DependencyError('cargo-native-graph-invalid')
    packages = {row['id']: row for row in metadata['packages']}
    nodes = {row['id']: row for row in metadata['resolve']['nodes']}
    if set(packages) != set(nodes):
        raise DependencyError('cargo-native-graph-not-closed')
    baseline = {(row['name'], row['version'], row.get('source')): row.get('checksum')
                for row in tomllib.loads((ROOT / 'tools/rust_capsule.lock').read_text())['package']}
    native_checksums = {(row['name'], row['version'], row.get('source')): row.get('checksum')
                       for row in tomllib.loads(read_bytes(root / 'Cargo.lock').decode())['package']}
    artifacts, graph = [], []
    for identity, package in sorted(packages.items()):
        node = nodes[identity]
        if any(edge['pkg'] not in packages for edge in node.get('deps', [])):
            raise DependencyError('cargo-native-edge-not-closed')
        source = package.get('source')
        path = regular_path(Path(package['manifest_path'])).resolve(strict=True)
        if path.parent == root or path.is_relative_to(root / 'vendor/lsf'):
            graph.append({'id': identity, 'artifact': None, 'features': node.get('features', []),
                          'dependencies': node.get('deps', []), 'source': 'captured-project-or-sdk'})
            continue
        if source:
            url = source.partition('+')[2].split('#', 1)[0]
            parsed = urlsplit(url)
            if parsed.username or parsed.password or set(parse_qs(parsed.query)) - {'rev', 'tag', 'branch'}:
                raise DependencyError('cargo-source-credentials-denied')
            matches = [candidate for candidate in vendor.iterdir() if candidate.is_dir()
                       and (candidate / 'Cargo.toml').is_file()
                       and (native := tomllib.loads(read_bytes(candidate / 'Cargo.toml').decode())).get('package', {}).get('name') == package['name']
                       and native['package'].get('version') == package['version']]
            if len(matches) != 1:
                raise DependencyError('cargo-vendor-package-ambiguous-or-missing')
            directory = matches[0]
            mount = 'dependencies/cargo-vendor/' + directory.name
        else:
            directory = path.parent
            mount = 'dependencies/cargo-paths/' + digest(identity.encode())[7:31]
        executable = [target['kind'] for target in package.get('targets', [])
                      if any(kind in {'proc-macro', 'custom-build'} for kind in target.get('kind', []))]
        key = (package['name'], package['version'], source)
        sdk_owned = key in baseline and native_checksums.get(key) == baseline[key]
        role = 'compiler' if sdk_owned else 'build-tool' if executable else 'application'
        row = {'id': package_identity(package), 'role': role, 'format': 'directory', 'mount': mount,
               'source': {'path': str(directory)}, 'dependencies': [],
               'metadata': {'ecosystem': 'cargo', 'nativeIdDigest': digest(identity.encode()), 'package': package['name'],
                            'version': package['version'], 'nativeSourceDigest': digest((source or 'captured-path').encode()), 'features': node.get('features', []),
                            'targets': package.get('targets', []), 'license': package.get('license'),
                            'licenseFile': package.get('license_file'), 'executableKinds': executable,
                            'sdkCompilerInput': sdk_owned}}
        artifacts.append(row)
        graph.append({'id': identity, 'artifact': row['id'], 'features': node.get('features', []),
                      'dependencies': node.get('deps', []), 'source': source or 'captured-path'})
    by_native = {entry['id']: entry['artifact'] for entry in graph if entry['artifact']}
    by_digest = {digest(identity.encode()): identity for identity in by_native}
    for row in artifacts:
        row['dependencies'] = sorted({by_native[edge['pkg']] for edge in nodes[by_digest[row['metadata']['nativeIdDigest']]].get('deps', [])
                                      if edge['pkg'] in by_native})
    return artifacts, {'formatVersion': 1, 'target': 'wasm32-unknown-unknown', 'nodes': graph,
                       'root': metadata['resolve'].get('root'), 'resolver': pins}


def resolve(project: Path, candidate: Path, *, cargo: Path | None = None, selection: dict | None = None,
            registry_config: Path | None = None) -> dict:
    """Explicit fetch stage. Cargo metadata/vendor do not run application hooks."""
    project = regular_path(project).resolve(strict=True)
    recipe_before = file_identity(Path(__file__), 'cargo-capture-recipe')
    if candidate.exists():
        raise DependencyError('dependency-candidate-exists')
    before = snapshot(project)
    original_lock = read_bytes(project / 'Cargo.lock')
    pins = tomllib.loads(read_bytes(project / 'vendor/lsf/rust-toolchain.toml').decode())
    selected = dict(selection or {})
    if set(selected) - {'features', 'allFeatures', 'noDefaultFeatures', 'runtimeProfile', 'target'}:
        raise DependencyError('cargo-selection-fields-invalid')
    if selected.get('target', 'wasm32-unknown-unknown') != 'wasm32-unknown-unknown':
        raise DependencyError('cargo-target-profile-not-maintained')
    features = selected.get('features', [])
    if (not isinstance(features, list) or len(features) > 256 or any(not isinstance(value, str)
            or not re.fullmatch(r'[A-Za-z0-9_./+-]{1,128}', value) for value in features)
            or any(type(selected.get(name, False)) is not bool for name in ('allFeatures', 'noDefaultFeatures'))):
        raise DependencyError('cargo-feature-selection-invalid')
    selected.update(target='wasm32-unknown-unknown', features=sorted(set(features)),
                    runtimeProfile=selected.get('runtimeProfile', 'wasm32-unknown-unknown-panic-abort-v1'))
    located = cargo
    if located is None and (rustup := shutil.which('rustup')):
        located = run_bounded([rustup, 'which', '--toolchain', pins['toolchain']['channel'], 'cargo'],
                              project, build_environment(project), 30, 16384).stdout.decode().strip()
    if not located:
        raise DependencyError('cargo-resolver-not-installed')
    cargo = regular_path(Path(located)).resolve(strict=True)
    registries = {}
    if registry_config is not None:
        declaration = json.loads(read_bytes(registry_config))
        if not isinstance(declaration, dict) or set(declaration) != {'registries'} or not isinstance(declaration['registries'], dict):
            raise DependencyError('cargo-registry-configuration-invalid')
        registries = declaration['registries']
        if len(registries) > 16:
            raise DependencyError('cargo-registry-configuration-limit')
        for alias, entry in registries.items():
            if (not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', alias) or not isinstance(entry, dict)
                    or set(entry) != {'index'} or not isinstance(entry['index'], str)):
                raise DependencyError('cargo-registry-configuration-invalid')
            parsed = urlsplit(entry['index'].removeprefix('sparse+'))
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise DependencyError('cargo-registry-credentials-or-endpoint-denied')
    with tempfile.TemporaryDirectory(prefix='lsf-cargo-resolve-') as temporary:
        temporary = Path(temporary)
        environment = build_environment(temporary)
        environment.update(CARGO_HOME=str(temporary / 'cargo-home'), HOME=str(temporary / 'home'),
                           USERPROFILE=str(temporary / 'home'), RUSTUP_TOOLCHAIN=pins['toolchain']['channel'], RUSTUP_AUTO_INSTALL='0',
                           RUSTC=str(cargo.parent / ('rustc.exe' if os.name == 'nt' else 'rustc')))
        # Private registry credentials are resolver-only opt-in environment.
        configuration_lines = []
        for alias, entry in registries.items():
            configuration_lines += ['[registries.' + json.dumps(alias) + ']',
                                    'index = ' + json.dumps(entry['index']), 'credential-provider = "cargo:token"']
        for alias in {*registries, 'crates-io'}:
            key = 'CARGO_REGISTRIES_' + alias.upper().replace('-', '_') + '_TOKEN'
            if key in os.environ:
                environment[key] = os.environ[key]
        Path(environment['CARGO_HOME']).mkdir()
        (Path(environment['CARGO_HOME']) / 'config.toml').write_text('\n'.join(configuration_lines) + '\n', encoding='utf-8')
        version = run_bounded([str(cargo), '--version'], project, environment, 10, 16384).stdout.decode().strip()
        if pins['toolchain']['channel'] not in version.split():
            raise DependencyError('cargo-resolver-version-not-pinned')
        flags = []
        if features:
            flags += ['--features', ','.join(features)]
        if selected.get('allFeatures'):
            flags.append('--all-features')
        if selected.get('noDefaultFeatures'):
            flags.append('--no-default-features')
        raw = run_bounded([str(cargo), 'metadata', '--manifest-path', str(project / 'Cargo.toml'), '--locked', '--format-version', '1',
                           *flags], temporary, environment, 600, 16 * 1024 * 1024).stdout
        metadata = json.loads(raw)
        selected_raw = run_bounded([str(cargo), 'metadata', '--manifest-path', str(project / 'Cargo.toml'), '--locked', '--format-version', '1',
                                    '--filter-platform', selected['target'], *flags], temporary, environment, 600, 16 * 1024 * 1024).stdout
        vendor = temporary / 'vendor'
        configuration = run_bounded([str(cargo), 'vendor', '--manifest-path', str(project / 'Cargo.toml'), '--locked', '--versioned-dirs', str(vendor)],
                                   temporary, environment, 600, 4 * 1024 * 1024).stdout
        resolver = {'cargo': file_identity(cargo, 'cargo-resolver'), 'version': version,
                    'metadataDigest': digest(raw), 'selectedMetadataDigest': digest(selected_raw), 'nativeLockDigest': digest(original_lock),
                    'registryConfigurationDigest': digest(canonical(registries)), 'recipe': recipe_before}
        artifacts, graph = analyze(metadata, project, vendor, resolver)
        graph['selectedResolve'] = json.loads(selected_raw)['resolve']
        mappings = {Path(package['manifest_path']).parent.resolve(): Path(row['mount'])
                    for package in metadata['packages'] for row in artifacts if row['metadata']['nativeIdDigest'] == digest(package['id'].encode())}
        mappings.update({project: Path('.'), **{Path(package['manifest_path']).parent.resolve():
                         Path(package['manifest_path']).parent.resolve().relative_to(project)
                         for package in metadata['packages'] if Path(package['manifest_path']).resolve().is_relative_to(project)}})
        root_id = 'cargo-project/' + digest(before['Cargo.toml'])[7:31]
        artifacts.append({'id': root_id, 'role': 'generated', 'format': 'file', 'mount': 'application-vendor/cargo-project/Cargo.toml',
                          'source': {'path': str(project / 'Cargo.toml')}, 'dependencies': [row['id'] for row in artifacts],
                          'metadata': {'ecosystem': 'cargo', 'rootManifest': True}})
        store = Store(project / 'dependency-inputs/objects')
        transforms = []
        for row in artifacts:
            original_path = Path(row['source']['path']) / 'Cargo.toml' if row['format'] == 'directory' else Path(row['source']['path'])
            raw_manifest = read_bytes(original_path)
            original_root = project / 'Cargo.toml' if row['id'] == root_id else Path(next(package['manifest_path']
                for package in metadata['packages'] if digest(package['id'].encode()) == row['metadata']['nativeIdDigest']))
            target = Path('Cargo.toml') if row['id'] == root_id else Path(row['mount']) / 'Cargo.toml'
            transformed = selected_manifest(raw_manifest, original_root, target, mappings)
            if transformed != raw_manifest:
                files = ({'Cargo.toml': raw_manifest} if row['format'] == 'file' else directory_files(Path(row['source']['path'])))
                original_rows = [{'path': name, 'digest': digest(data), 'size': len(data)} for name, data in sorted(files.items())]
                files['Cargo.toml'] = transformed
                output_rows = [{'path': name, 'digest': digest(data), 'size': len(data)} for name, data in sorted(files.items())]
                transformed_object = store.put(transformed)
                transforms.append({'id': 'cargo-path-relocation/' + digest(row['id'].encode())[7:31], 'artifact': row['id'],
                    'inputDigest': tree_identity(original_rows), 'outputDigest': tree_identity(output_rows),
                    'files': [{'path': 'Cargo.toml', 'inputDigest': digest(raw_manifest),
                               'source': str(store.path(transformed_object['digest'])), 'outputDigest': transformed_object['digest']}],
                    'tool': file_identity(Path(__file__), 'cargo-selected-path-relocator'), 'selection': selected})
        # Native vendor replacement is captured input, not ambient Cargo config.
        config = tomllib.loads(configuration.decode())
        for source in config.get('source', {}).values():
            if 'directory' in source:
                source['directory'] = 'dependencies/cargo-vendor'
        graph['sourceReplacement'] = config
        graph['selection'] = selected
        native_path = project / 'cargo-resolved.lock.json'
        native_path.write_bytes(canonical(graph) + b'\n')
        manifest = {'formatVersion': 1, 'language': 'rust', 'selection': selected,
                    'nativeLocks': ['Cargo.lock', 'cargo-resolved.lock.json'], 'artifacts': artifacts, 'transformations': transforms}
        (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
        locked = capture(project)
        # Captured directory originals survive removal of resolver temp paths.
        # The manifest source is provenance only; verification reconstructs CAS.
        if read_bytes(project / 'Cargo.lock') != original_lock or any(read_bytes(project / name) != data
                for name, data in before.items() if name not in {MANIFEST, LOCK, 'cargo-resolved.lock.json'}):
            raise DependencyError('cargo-resolution-input-mutated')
        if file_identity(cargo, 'cargo-resolver') != resolver['cargo']:
            raise DependencyError('cargo-resolver-mutated')
        if file_identity(Path(__file__), 'cargo-capture-recipe') != recipe_before:
            raise DependencyError('cargo-capture-recipe-mutated')
        with candidate.open('xb') as output:
            output.write(canonical(locked) + b'\n')
        return locked


def configure(closure, work: Path, home: Path) -> tuple[bytes, dict]:
    if closure is None:
        raise DependencyError('cargo-closure-required')
    graph = json.loads(read_bytes(closure.project / 'cargo-resolved.lock.json'))
    root = next((row for row in closure.lock['artifacts'] if row['metadata'].get('rootManifest')), None)
    if root is None:
        raise DependencyError('cargo-selected-root-manifest-missing')
    adapted = read_bytes(work / root['mount'])
    (work / 'Cargo.toml').write_bytes(adapted)
    source = graph['sourceReplacement'].get('source', {})
    lines = []
    for name, value in source.items():
        lines.append('[source.' + json.dumps(name) + ']')
        for key, item in value.items():
            if key not in {'directory', 'replace-with', 'git', 'rev', 'tag', 'branch', 'registry'} or not isinstance(item, str):
                raise DependencyError('cargo-source-replacement-invalid')
            if key == 'directory':
                item = str(work / 'dependencies/cargo-vendor')
            lines.append(key + ' = ' + json.dumps(item))
    home.mkdir(parents=True, exist_ok=True)
    configuration = ('\n'.join(lines) + '\n[net]\noffline = true\n').encode()
    (home / 'config.toml').write_bytes(configuration)
    return adapted, {'formatVersion': 1, 'inputIdentity': closure.identity, 'selection': closure.lock['selection'],
                     'selectedManifestDigest': digest(adapted), 'cargoConfigurationDigest': digest(configuration),
                     'nativeGraphDigest': digest(canonical(graph)), 'networkResolution': False}
