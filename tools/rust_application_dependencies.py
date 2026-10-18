"""Native Cargo graph/vendor capture and offline selected-manifest staging."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import ssl
import tempfile
import tomllib
from urllib.parse import parse_qs, urlsplit

from tools.application_dependencies import LOCK, MANIFEST, MAX_LOCK, capture, validate_manifest
from tools.application_dependency_store import DependencyError, Store, directory_files, path_name, read_bytes, regular_path, tree_identity
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import ROOT, snapshot

MAX_REGISTRY_CA = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MANIFEST_TOKENS = 131072
MAX_MANIFEST_DEPTH = 32
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_GRAPH_ROWS = 65536
CERTIFICATE = rb'-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----'


def registry_trust(project: Path, value: dict) -> tuple[str, bytes]:
    """Select public CA bytes explicitly, without changing machine trust."""
    if not isinstance(value, dict) or set(value) != {'caFile'} or not isinstance(value['caFile'], str):
        raise DependencyError('cargo-registry-trust-declaration-invalid')
    name = path_name(value['caFile'])
    if name.split('/')[0] in {'vendor', 'target', '.git', 'dependency-inputs', 'dependencies', 'application-vendor'}:
        raise DependencyError('cargo-registry-certificate-path-invalid')
    raw = read_bytes(regular_path(project / name), MAX_REGISTRY_CA)
    if not 1 <= len(re.findall(CERTIFICATE, raw)) <= 256 or re.sub(CERTIFICATE, b'', raw).strip():
        raise DependencyError('cargo-registry-public-certificate-required')
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=raw.decode('ascii'))
    except (UnicodeError, ValueError, ssl.SSLError):
        raise DependencyError('cargo-registry-public-certificate-required') from None
    return name, raw


def package_identity(package: dict) -> str:
    return package['name'] + '/' + package['version'] + '/' + digest(package['id'].encode())[7:23]


def _dependency_path_fields(document: dict) -> dict[tuple[str, ...], str]:
    """Cargo dependency locations only; metadata and source-file paths are data."""
    result = {}

    def dependencies(table, prefix):
        if table is None:
            return
        if not isinstance(table, dict):
            raise DependencyError('cargo-path-relocation-syntax-unsupported')
        for name, specification in table.items():
            if not isinstance(specification, (dict, str)):
                raise DependencyError('cargo-path-relocation-syntax-unsupported')
            if isinstance(specification, dict) and 'path' in specification:
                if not isinstance(specification['path'], str) or '\0' in specification['path']:
                    raise DependencyError('cargo-path-relocation-path-invalid')
                result[(*prefix, name, 'path')] = specification['path']

    target, workspace, patch = (document.get(name, {}) for name in ('target', 'workspace', 'patch'))
    if any(not isinstance(table, dict) for table in (target, workspace, patch)):
        raise DependencyError('cargo-path-relocation-syntax-unsupported')
    for section in ('dependencies', 'dev-dependencies', 'build-dependencies'):
        dependencies(document.get(section), (section,))
        for name, table in target.items():
            if isinstance(table, dict):
                dependencies(table.get(section), ('target', name, section))
            else:
                raise DependencyError('cargo-path-relocation-syntax-unsupported')
    dependencies(workspace.get('dependencies'), ('workspace', 'dependencies'))
    for source, table in patch.items():
        dependencies(table, ('patch', source))
    dependencies(document.get('replace'), ('replace',))
    return result


def _manifest_tokens(text: str) -> list[tuple[str, str, int, int]]:
    """Locate syntax spans after tomllib validation; never interpret user code."""
    tokens, offset = [], 0
    while offset < len(text):
        if len(tokens) >= MAX_MANIFEST_TOKENS:
            raise DependencyError('cargo-path-relocation-limit')
        first, character = offset, text[offset]
        if character in ' \t\r':
            offset += 1
            continue
        if character == '#':
            offset = text.find('\n', offset)
            if offset == -1:
                break
            continue
        if character in {'"', "'"}:
            quote, triple = character, text.startswith(character * 3, offset)
            offset += 3 if triple else 1
            while offset < len(text):
                if quote == '"' and text[offset] == '\\':
                    offset += 2
                    continue
                if triple and text.startswith(quote * 3, offset):
                    while offset < len(text) and text[offset] == quote:
                        offset += 1
                    break
                if not triple and text[offset] == quote:
                    offset += 1
                    break
                offset += 1
            else:
                raise DependencyError('cargo-path-relocation-syntax-unsupported')
            kind = 'string'
        elif character in '\n[]=.,{}':
            kind, offset = character, offset + 1
        else:
            kind = 'atom'
            while offset < len(text) and text[offset] not in ' \t\r\n#"\x27[]=.,{}':
                offset += 1
        tokens.append((kind, text[first:offset], first, offset))
    return tokens


def _dependency_path_spans(text: str, fields: dict) -> list[tuple[int, int, str]]:
    tokens, found, spans = _manifest_tokens(text), set(), []

    def keys(index, stop):
        names = []
        while index < len(tokens):
            kind, raw, _start, _end = tokens[index]
            if kind == 'string':
                names.append(tomllib.loads('value = ' + raw)['value'])
            elif kind == 'atom' and re.fullmatch('[A-Za-z0-9_-]+', raw):
                names.append(raw)
            else:
                break
            index += 1
            if index < len(tokens) and tokens[index][0] == stop:
                return tuple(names), index + 1
            if index >= len(tokens) or tokens[index][0] != '.':
                break
            index += 1
        raise DependencyError('cargo-path-relocation-syntax-unsupported')

    def value(index, prefix, depth=0):
        if depth > MAX_MANIFEST_DEPTH or index >= len(tokens):
            raise DependencyError('cargo-path-relocation-limit')
        kind, raw, start, end = tokens[index]
        if kind == 'string':
            if prefix in fields:
                if prefix in found or tomllib.loads('value = ' + raw)['value'] != fields[prefix]:
                    raise DependencyError('cargo-path-relocation-ambiguous')
                found.add(prefix)
                spans.append((start, end, fields[prefix]))
            return index + 1
        if kind == '{':
            index += 1
            while index < len(tokens) and tokens[index][0] != '}':
                names, index = keys(index, '=')
                index = value(index, None if prefix is None else prefix + names, depth + 1)
                if index < len(tokens) and tokens[index][0] == ',':
                    index += 1
                elif index >= len(tokens) or tokens[index][0] != '}':
                    raise DependencyError('cargo-path-relocation-syntax-unsupported')
            if index >= len(tokens):
                raise DependencyError('cargo-path-relocation-syntax-unsupported')
            return index + 1
        if kind == '[':
            # Dependency specifications are objects, never array entries.
            stack, index = [']'], index + 1
            while stack and index < len(tokens):
                kind = tokens[index][0]
                if kind in {'[', '{'}:
                    stack.append(']' if kind == '[' else '}')
                elif kind in {']', '}'}:
                    if stack.pop() != kind:
                        raise DependencyError('cargo-path-relocation-syntax-unsupported')
                if len(stack) + depth > MAX_MANIFEST_DEPTH:
                    raise DependencyError('cargo-path-relocation-limit')
                index += 1
            if stack:
                raise DependencyError('cargo-path-relocation-syntax-unsupported')
            return index
        while index < len(tokens) and tokens[index][0] not in {'\n', ',', '}', ']'}:
            index += 1
        return index

    table, index = (), 0
    while index < len(tokens):
        if tokens[index][0] == '\n':
            index += 1
            continue
        if tokens[index][0] == '[':
            array = index + 1 < len(tokens) and tokens[index + 1][0] == '['
            table, index = keys(index + (2 if array else 1), ']')
            if array:
                if index >= len(tokens) or tokens[index][0] != ']':
                    raise DependencyError('cargo-path-relocation-syntax-unsupported')
                table, index = None, index + 1
        else:
            names, index = keys(index, '=')
            index = value(index, None if table is None else table + names)
        if index < len(tokens) and tokens[index][0] != '\n':
            raise DependencyError('cargo-path-relocation-syntax-unsupported')
    if found != fields.keys():
        raise DependencyError('cargo-path-relocation-syntax-unsupported')
    return spans


def selected_manifest(data: bytes, original: Path, mapped: Path, mappings: dict[Path, Path]) -> bytes:
    """Relocate selected Cargo dependency values, preserving every other byte."""
    if len(data) > MAX_MANIFEST_BYTES:
        raise DependencyError('cargo-path-relocation-limit')
    try:
        text = data.decode('utf-8')
        document = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise DependencyError('cargo-path-relocation-invalid-toml') from None
    except RecursionError:
        raise DependencyError('cargo-path-relocation-limit') from None
    fields = _dependency_path_fields(document)
    if not fields:
        return data
    for start, end, path in sorted(_dependency_path_spans(text, fields), reverse=True):
        try:
            destination = (original.parent / path).resolve(strict=False)
        except (OSError, ValueError):
            raise DependencyError('cargo-path-relocation-path-invalid') from None
        selected = mappings.get(destination)
        if selected is None and destination.is_relative_to(original.parent):
            continue
        if selected is None:
            raise DependencyError('cargo-path-dependency-not-in-selected-graph')
        try:
            relative = os.path.relpath(selected, mapped.parent).replace('\\', '/')
        except (OSError, ValueError):
            raise DependencyError('cargo-path-relocation-path-invalid') from None
        text = text[:start] + json.dumps(relative, ensure_ascii=False) + text[end:]
    return text.encode('utf-8')


def native_metadata(data: bytes) -> dict:
    """Read bounded native JSON without silently replacing duplicate fields."""
    if len(data) > MAX_METADATA_BYTES:
        raise DependencyError('cargo-native-metadata-limit')

    def fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise DependencyError('cargo-native-metadata-duplicate-field')
            result[name] = value
        return result

    def invalid_constant(_):
        raise ValueError()

    try:
        return json.loads(data, object_pairs_hook=fields, parse_constant=invalid_constant)
    except DependencyError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise DependencyError('cargo-native-metadata-invalid') from None


def native_graph(metadata: dict, *, filtered=False) -> tuple[dict, dict]:
    """Validate observed graph fields; keep opaque IDs and native records intact."""
    def token(value):
        return (isinstance(value, str) and 0 < len(value) <= 32768
                and not any(ord(char) < 32 or ord(char) == 127 for char in value))

    def rows(value):
        if not isinstance(value, list) or len(value) > 1024:
            raise DependencyError('cargo-native-graph-invalid')
        return value

    def strings(value, maximum=1024):
        if (not isinstance(value, list) or len(value) > maximum
                or any(not token(item) for item in value) or len(set(value)) != len(value)):
            raise DependencyError('cargo-native-graph-invalid')
        return value

    if (not isinstance(metadata, dict) or type(metadata.get('version')) is not int
            or metadata['version'] != 1 or not isinstance(metadata.get('resolve'), dict)):
        raise DependencyError('cargo-native-graph-invalid')
    packages, nodes = {}, {}
    for group, selected in ((metadata.get('packages'), packages), (metadata['resolve'].get('nodes'), nodes)):
        for row in rows(group):
            if not isinstance(row, dict) or not token(row.get('id')):
                raise DependencyError('cargo-native-graph-invalid')
            if row['id'] in selected:
                raise DependencyError('cargo-native-graph-duplicate-id')
            selected[row['id']] = row
    closed = set(nodes) <= set(packages) if filtered else set(nodes) == set(packages)
    if not packages or not closed:
        raise DependencyError('cargo-native-graph-not-closed')
    if not token(metadata['resolve'].get('root')) or metadata['resolve']['root'] not in nodes:
        raise DependencyError('cargo-native-graph-root-invalid')
    count = 0
    for node in nodes.values():
        # Native all-features vectors are not package/edge collections. Keep
        # their existing aggregate capacity without expanding structural rows.
        count += len(strings(node.get('features'), maximum=MAX_GRAPH_ROWS))
        identities = set()
        for edge in rows(node.get('deps')):
            if (not isinstance(edge, dict) or not token(edge.get('pkg')) or edge['pkg'] not in nodes
                    or 'name' in edge and not token(edge['name'])):
                raise DependencyError('cargo-native-edge-not-closed')
            identity = (edge.get('name'), edge['pkg'])
            if identity in identities:
                raise DependencyError('cargo-native-edge-duplicate')
            identities.add(identity)
            if 'dep_kinds' in edge:
                kinds = rows(edge['dep_kinds'])
                seen = set()
                for kind in kinds:
                    if (not isinstance(kind, dict) or kind.get('kind') not in (None, 'dev', 'build')
                            or 'kind' not in kind or 'target' not in kind
                            or kind['target'] is not None and not token(kind['target'])):
                        raise DependencyError('cargo-native-edge-kind-invalid')
                    key = (kind['kind'], kind['target'])
                    if key in seen:
                        raise DependencyError('cargo-native-edge-kind-duplicate')
                    seen.add(key)
                count += len(kinds)
            count += 1
        if 'dependencies' in node and set(strings(node['dependencies'])) != {edge['pkg'] for edge in node['deps']}:
            raise DependencyError('cargo-native-edge-not-closed')
        if count > MAX_GRAPH_ROWS:
            raise DependencyError('cargo-native-metadata-limit')
    return packages, nodes


def selected_graph(metadata: dict, selected: dict, root: Path) -> dict:
    packages, nodes = native_graph(metadata)
    selected_packages, selected_nodes = native_graph(selected, filtered=True)
    if (not set(selected_packages) <= set(packages) or not set(selected_nodes) <= set(nodes)
            or any(package != packages[identity] for identity, package in selected_packages.items())):
        raise DependencyError('cargo-selected-graph-package-drift')
    root_id = metadata['resolve']['root']
    try:
        actual = [row['id'] for row in packages.values()
                  if Path(row['manifest_path']).resolve(strict=False) == (root / 'Cargo.toml').resolve(strict=False)]
    except (KeyError, TypeError, ValueError, OSError):
        raise DependencyError('cargo-native-graph-root-invalid') from None
    if actual != [root_id] or selected['resolve']['root'] != root_id:
        raise DependencyError('cargo-native-graph-root-invalid')
    for identity, node in selected_nodes.items():
        full = nodes[identity]
        if not set(node['features']) <= set(full['features']):
            raise DependencyError('cargo-selected-graph-feature-drift')
        edges = {(edge.get('name'), edge['pkg']): edge for edge in full['deps']}
        for edge in node['deps']:
            original = edges.get((edge.get('name'), edge['pkg']))
            if original is None or ('dep_kinds' in edge) != ('dep_kinds' in original):
                raise DependencyError('cargo-selected-graph-edge-drift')
            kinds = {(item['kind'], item['target']) for item in original.get('dep_kinds', [])}
            if any((kind['kind'], kind['target']) not in kinds for kind in edge.get('dep_kinds', [])):
                raise DependencyError('cargo-selected-graph-edge-drift')
    return selected['resolve']


def analyze(metadata: dict, root: Path, vendor: Path, pins: dict) -> tuple[list[dict], dict]:
    if (not isinstance(metadata, dict) or metadata.get('version') != 1 or not isinstance(metadata.get('packages'), list)
            or not isinstance(metadata.get('resolve'), dict) or len(metadata['packages']) > 1024):
        raise DependencyError('cargo-native-graph-invalid')
    packages, nodes = native_graph(metadata)
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
        # An outside path crate can reuse SDK coordinates. A missing checksum
        # establishes no SDK ownership and must not waive executable approval.
        sdk_owned = bool(source and baseline.get(key) and native_checksums.get(key) == baseline[key])
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


def registry_policy(owner: Path, project: Path, registry_config: Path | None):
    """The explicit registry/CA policy shared by native locking and capture."""
    registries = {}
    registry_bytes = None
    trust_name, trust_raw = None, None
    if registry_config is not None:
        registry_config = regular_path(registry_config).resolve(strict=True)
        if registry_config.is_relative_to(owner):
            raise DependencyError('cargo-private-registry-config-must-stay-outside-project')
        registry_bytes = read_bytes(registry_config)
        declaration = json.loads(registry_bytes)
        if (not isinstance(declaration, dict) or not {'registries'} <= set(declaration) <= {'registries', 'tlsTrust'}
                or not isinstance(declaration['registries'], dict)):
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
        aliases = {*registries, 'crates-io'}
        if len({alias.upper().replace('-', '_') for alias in aliases}) != len(aliases):
            raise DependencyError('cargo-registry-credential-slot-ambiguous')
        if 'tlsTrust' in declaration:
            trust_name, trust_raw = registry_trust(project, declaration['tlsTrust'])
    return registries, registry_bytes, trust_name, trust_raw


def fetch_environment(temporary: Path, pins: dict, cargo: Path, registries: dict, trust_raw: bytes | None):
    """Fresh Cargo home and explicit credentials; never discover project config."""
    from tools.dev_workflow import paths
    certificate = None
    environment = build_environment(temporary)
    environment.update(CARGO_HOME=str(temporary / 'cargo-home'), HOME=str(temporary / 'home'),
                       USERPROFILE=str(temporary / 'home'), RUSTUP_TOOLCHAIN=pins['toolchain']['channel'], RUSTUP_AUTO_INSTALL='0',
                       RUSTC=str(cargo.parent / ('rustc.exe' if os.name == 'nt' else 'rustc')),
                       GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(temporary / 'git-empty.config'),
                       GIT_TERMINAL_PROMPT='0')
    paths.write_new(temporary / 'git-empty.config', b'')
    # Private registry credentials are resolver-only opt-in environment.
    configuration_lines = []
    if trust_raw is not None:
        certificate = temporary / 'private-registry-public-ca.pem'
        paths.write_new(certificate, trust_raw)
        configuration_lines += ['[http]', 'ssl-verify = true', 'cainfo = ' + json.dumps(str(certificate))]
    for alias, entry in registries.items():
        configuration_lines += ['[registries.' + json.dumps(alias) + ']',
                                'index = ' + json.dumps(entry['index']), 'credential-provider = "cargo:token"']
    for alias in {*registries, 'crates-io'}:
        key = 'CARGO_REGISTRIES_' + alias.upper().replace('-', '_') + '_TOKEN'
        if key in os.environ:
            token = os.environ[key]
            if not 1 <= len(token) <= 16384 or re.search(r'[\x00-\x1f\x7f]', token):
                raise DependencyError('cargo-registry-token-invalid')
            environment[key] = token
    Path(environment['CARGO_HOME']).mkdir()
    (Path(environment['CARGO_HOME']) / 'config.toml').write_text('\n'.join(configuration_lines) + '\n', encoding='utf-8')
    return environment, certificate


def resolve(project: Path, candidate: Path, *, cargo: Path | None = None, selection: dict | None = None,
            registry_config: Path | None = None) -> dict:
    """Explicit fetch stage. Cargo metadata/vendor do not run application hooks."""
    from tools.rust_dependency_authoring import transaction
    with transaction(project) as (owner, app, private, sdk):
        return _resolve(owner, app, private, sdk, candidate, cargo=cargo,
                        selection=selection, registry_config=registry_config)


def _resolve(owner: Path, project: Path, private: Path, sdk, candidate: Path, *,
             cargo: Path | None, selection: dict | None, registry_config: Path | None) -> dict:
    from tools.rust_dependency_authoring import candidate_location, optional, replace, unchanged
    from tools.dev_workflow import paths
    candidate = candidate_location(owner, candidate)
    recipe_before = file_identity(Path(__file__), 'cargo-capture-recipe')
    if os.path.lexists(candidate):
        raise DependencyError('dependency-candidate-exists')
    previous_manifest, previous_lock = optional(owner, MANIFEST), optional(owner, LOCK)
    previous_graph = optional(project, 'cargo-resolved.lock.json')
    before = snapshot(project)
    original_lock = read_bytes(project / 'Cargo.lock')
    pins = tomllib.loads(read_bytes(project / 'vendor/lsf/rust-toolchain.toml').decode())
    selected = dict(selection or {})
    if set(selected) - {'features', 'allFeatures', 'noDefaultFeatures', 'runtimeProfile', 'target'}:
        raise DependencyError('cargo-selection-fields-invalid')
    if selected.get('target', 'wasm32-unknown-unknown') != 'wasm32-unknown-unknown':
        raise DependencyError('cargo-target-profile-not-maintained')
    if selected.get('runtimeProfile', 'wasm32-unknown-unknown-panic-abort-v1') != 'wasm32-unknown-unknown-panic-abort-v1':
        raise DependencyError('cargo-runtime-profile-not-installed')
    features = selected.get('features', [])
    if (not isinstance(features, list) or len(features) > 256 or any(not isinstance(value, str)
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./+-]{0,127}', value) for value in features)
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
    registries, registry_bytes, trust_name, trust_raw = registry_policy(owner, project, registry_config)
    with tempfile.TemporaryDirectory(prefix='lsf-cargo-resolve-') as temporary:
        temporary = Path(temporary)
        environment, certificate = fetch_environment(temporary, pins, cargo, registries, trust_raw)
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
        metadata = native_metadata(raw)
        selected_raw = run_bounded([str(cargo), 'metadata', '--manifest-path', str(project / 'Cargo.toml'), '--locked', '--format-version', '1',
                                    '--filter-platform', selected['target'], *flags], temporary, environment, 600, 16 * 1024 * 1024).stdout
        selected_resolve = selected_graph(metadata, native_metadata(selected_raw), project)
        vendor = temporary / 'vendor'
        configuration = run_bounded([str(cargo), 'vendor', '--manifest-path', str(project / 'Cargo.toml'), '--locked', '--versioned-dirs', str(vendor)],
                                   temporary, environment, 600, 4 * 1024 * 1024).stdout
        resolver = {'cargo': file_identity(cargo, 'cargo-resolver'), 'version': version,
                    'metadataDigest': digest(raw), 'selectedMetadataDigest': digest(selected_raw), 'nativeLockDigest': digest(original_lock),
                    'registryConfigurationDigest': digest(canonical(registries)), 'recipe': recipe_before}
        if registry_bytes is not None:
            resolver['registryConfigurationInputDigest'] = digest(registry_bytes)
        if trust_raw is not None:
            resolver['tlsTrust'] = {'profile': 'cargo-explicit-registry-ca-v1', 'caFile': trust_name,
                                    'digest': digest(trust_raw), 'size': len(trust_raw), 'verification': 'required'}
        artifacts, graph = analyze(metadata, project, vendor, resolver)
        graph['selectedResolve'] = selected_resolve
        mappings = {Path(package['manifest_path']).parent.resolve(): Path(row['mount'])
                    for package in metadata['packages'] for row in artifacts if row['metadata']['nativeIdDigest'] == digest(package['id'].encode())}
        mappings.update({project: Path('.'), **{Path(package['manifest_path']).parent.resolve():
                         Path(package['manifest_path']).parent.resolve().relative_to(project)
                         for package in metadata['packages'] if Path(package['manifest_path']).resolve().is_relative_to(project)}})
        root_id = 'cargo-project/' + digest(before['Cargo.toml'])[7:31]
        root_package = next(package for package in metadata['packages'] if Path(package['manifest_path']).resolve() == project / 'Cargo.toml')
        build_target = next((target for target in root_package['targets'] if 'custom-build' in target['kind']), None)
        build_script = None
        if build_target is not None:
            path = Path(build_target['src_path']).resolve(strict=True)
            if not path.is_relative_to(project):
                raise DependencyError('cargo-root-build-script-outside-captured-source')
            data = read_bytes(path)
            build_script = {'path': path.relative_to(project).as_posix(), 'digest': digest(data), 'size': len(data)}
        artifacts.append({'id': root_id, 'role': 'build-tool' if build_script else 'generated', 'format': 'file', 'mount': 'application-vendor/cargo-project/Cargo.toml',
                          'source': {'path': str(project / 'Cargo.toml')}, 'dependencies': [row['id'] for row in artifacts],
                          'metadata': {'ecosystem': 'cargo', 'rootManifest': True, 'buildScript': build_script}})
        store = Store(owner / 'dependency-inputs/objects')
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
        # Cargo's vendor source replacements use registry URLs. Application
        # manifests still refer to named aliases; preserve their public mapping
        # so offline compilation never needs an ambient Cargo configuration.
        graph['registries'] = registries
        graph['selection'] = selected
        prefix = project.relative_to(owner).as_posix() + '/' if project != owner else ''
        native_names = ['Cargo.lock', 'cargo-resolved.lock.json'] + ([trust_name] if trust_name else [])
        manifest = {'formatVersion': 1, 'language': 'rust', 'selection': selected,
                    'nativeLocks': [prefix + name for name in native_names],
                    'artifacts': artifacts, 'transformations': transforms}
        manifest_raw, graph_raw = canonical(manifest) + b'\n', canonical(graph) + b'\n'
        # Resolve into an owned review view first. Failed captures preserve all
        # accepted application inputs, and native Cargo never edits SDK bytes.
        staged = temporary / 'capture'
        staged.mkdir(mode=0o700)
        stage_inputs = [(MANIFEST, manifest_raw), (prefix + 'Cargo.lock', original_lock),
                        (prefix + 'cargo-resolved.lock.json', graph_raw)]
        if trust_raw is not None:
            stage_inputs.append((prefix + trust_name, trust_raw))
        for name, raw_input in stage_inputs:
            target = staged / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            paths.write_new(target, raw_input)
        locked = capture(staged, cache=owner / 'dependency-inputs/objects')
        # Captured directory originals survive removal of resolver temp paths.
        # The manifest source is provenance only; verification reconstructs CAS.
        if trust_raw is not None:
            try:
                current_trust = read_bytes(regular_path(project / trust_name), MAX_REGISTRY_CA)
                copied_trust = read_bytes(regular_path(certificate), MAX_REGISTRY_CA)
            except (OSError, DependencyError):
                raise DependencyError('cargo-registry-certificate-mutated') from None
            if current_trust != trust_raw or copied_trust != trust_raw:
                raise DependencyError('cargo-registry-certificate-mutated')
        if snapshot(project) != before:
            raise DependencyError('cargo-resolution-input-mutated')
        if optional(owner, MANIFEST) != previous_manifest or optional(owner, LOCK) != previous_lock:
            raise DependencyError('cargo-authoring-concurrent-input-edit')
        if file_identity(cargo, 'cargo-resolver') != resolver['cargo']:
            raise DependencyError('cargo-resolver-mutated')
        if file_identity(Path(__file__), 'cargo-capture-recipe') != recipe_before:
            raise DependencyError('cargo-capture-recipe-mutated')
        if registry_config is not None:
            try:
                current_registry_bytes = read_bytes(registry_config)
            except OSError:
                raise DependencyError('cargo-registry-configuration-mutated') from None
            if current_registry_bytes != registry_bytes:
                raise DependencyError('cargo-registry-configuration-mutated')
        unchanged(owner, sdk)
        for row in artifacts:
            if row['format'] == 'directory' and candidate.is_relative_to(Path(row['source']['path'])):
                raise DependencyError('cargo-candidate-inside-captured-source')
        # Each edited file is atomic. An interrupted pair remains fail-closed
        # against the unchanged accepted lock and requires another resolution.
        replace(owner, private, prefix + 'cargo-resolved.lock.json', graph_raw, previous_graph, sdk)
        replace(owner, private, MANIFEST, manifest_raw, previous_manifest, sdk)
        if (read_bytes(owner / MANIFEST) != manifest_raw or read_bytes(project / 'cargo-resolved.lock.json') != graph_raw
                or optional(owner, LOCK) != previous_lock):
            raise DependencyError('cargo-authoring-concurrent-input-edit')
        raw_candidate = canonical(locked) + b'\n'
        if len(raw_candidate) > MAX_LOCK:
            raise DependencyError('dependency-lock-limit')
        paths.write_new(candidate, raw_candidate)
        return locked


def configure(closure, work: Path, home: Path) -> tuple[bytes, dict]:
    from tools.guest_dependency_inputs import read_native
    if closure is None:
        raise DependencyError('cargo-closure-required')
    graph = json.loads(read_native(closure, 'cargo-resolved.lock.json'))
    root = next((row for row in closure.lock['artifacts'] if row['metadata'].get('rootManifest')), None)
    if root is None:
        raise DependencyError('cargo-selected-root-manifest-missing')
    if digest(read_bytes(work / 'Cargo.toml')) != root['original']['digest']:
        raise DependencyError('cargo-root-manifest-drift-resolve-and-review')
    declaration = tomllib.loads(read_bytes(work / 'Cargo.toml').decode())
    script = declaration['package'].get('build', 'build.rs' if (work / 'build.rs').exists() else False)
    expected_script = root['metadata'].get('buildScript')
    if script is not False:
        data = read_bytes(work / script)
        if expected_script != {'path': script, 'digest': digest(data), 'size': len(data)} or root['role'] != 'build-tool':
            raise DependencyError('cargo-root-build-script-drift-resolve-and-review')
    elif expected_script is not None:
        raise DependencyError('cargo-root-build-script-drift-resolve-and-review')
    adapted = read_bytes(work / root['mount'])
    (work / 'Cargo.toml').write_bytes(adapted)
    source = graph['sourceReplacement'].get('source', {})
    lines = []
    registries = graph.get('registries', {})
    if not isinstance(registries, dict) or len(registries) > 16:
        raise DependencyError('cargo-captured-registry-configuration-invalid')
    for name, value in registries.items():
        if (not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', name) or not isinstance(value, dict)
                or set(value) != {'index'} or not isinstance(value['index'], str)):
            raise DependencyError('cargo-captured-registry-configuration-invalid')
        parsed = urlsplit(value['index'].removeprefix('sparse+'))
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise DependencyError('cargo-captured-registry-configuration-invalid')
        # Authentication providers and CA selection belong only to resolution.
        lines += ['[registries.' + json.dumps(name) + ']', 'index = ' + json.dumps(value['index'])]
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
