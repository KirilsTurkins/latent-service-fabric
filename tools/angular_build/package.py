"""Exact public asset mapping, private metadata and package-bound inventory inputs."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from pathlib import Path

from tools.angular_build.inputs import MEDIA, MAX_ASSET_TREE_BYTES, decode, read
from tools.build_observation import file_identity
from tools.build_snapshot import SnapshotError, canonical, digest


class Hydration(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active, self.data, self.total = False, [], 0

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = any(name == 'type' and value and value.lower() == 'application/json' for name, value in attrs)
            self.data = []

    def handle_data(self, data):
        if self.active:
            self.total += len(data.encode('utf-8'))
            if self.total > 32768:
                raise SnapshotError('Angular prerender hydration byte limit exceeded')
            self.data.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            decode(''.join(self.data).encode())
            self.active = False


def check_html(data: bytes) -> None:
    if len(data) > 131072:
        raise SnapshotError('Angular supplied HTML byte limit exceeded')
    parser = Hydration()
    try:
        parser.feed(data.decode('utf-8'))
        parser.close()
    except UnicodeError as error:
        raise SnapshotError('Angular HTML must be UTF-8') from error
    if parser.active:
        raise SnapshotError('Angular supplied hydration script is incomplete')


def asset_digest(assets: list[dict]) -> str:
    hash = hashlib.sha256()
    def part(data):
        hash.update(len(data).to_bytes(8, 'little')); hash.update(data)
    part(b'lsf-web-public-assets-v1')
    for item in assets:
        for field in ('path', 'layer', 'digest', 'mediaType'):
            part(item[field].encode())
        part(item['size'].to_bytes(8, 'little'))
    return 'sha256:' + hash.hexdigest()


def stage(config: dict, captured: Path, bundle: Path, composed: Path, inputs: Path,
          profile: dict, source_inventory: bytes) -> tuple[dict, str]:
    inputs.mkdir()
    layers, assets = [], []
    def layer(name, data, role='asset', media='application/json'):
        target = inputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        layers.append({'path': name, 'source': name, 'role': role, 'mediaType': media})
    client = read(bundle, 'client.js', 8 * 1024 * 1024)
    client_name = '/client/' + digest(client)[7:] + '/main.js'
    for name, data in [(client_name, client), *[(row['path'], read(captured, row['source'], 8 * 1024 * 1024)) for row in config['assets']]]:
        media = MEDIA[name.rsplit('.', 1)[-1]]
        if media == 'text/html':
            check_html(data)
        relative = 'public' + name
        layer(relative, data, media=media)
        assets.append({'path': name, 'layer': relative, 'digest': digest(data), 'size': len(data), 'mediaType': media})
    assets.sort(key=lambda item: item['path'])
    if sum(item['size'] for item in assets) > MAX_ASSET_TREE_BYTES:
        raise SnapshotError('Angular generated asset tree byte limit exceeded')
    tree = asset_digest(assets)
    component = read(composed.parent, composed.name, 32 * 1024 * 1024)
    renderer = {'layer': 'server/renderer.wasm', 'digest': digest(component), 'size': len(component),
                'profile': profile['profile'], 'profileDigest': profile['profileDigest'], 'assetsDigest': tree}
    layer(renderer['layer'], component, role='renderer', media='application/wasm')
    web = {'formatVersion': 1, 'profile': 'lsf.web-release.v1', 'assetsDigest': tree, 'assets': assets,
           'routes': sorted(config['routes'], key=lambda row: row['path']), 'renderer': renderer}
    layer('metadata/web-application.json', canonical(web))
    layer('metadata/source-inputs.json', source_inventory)
    # The compiler graph and source inventory remain private package metadata.
    layer('metadata/bundle-inputs.json', read(bundle, 'bundle-inputs.json', 1024 * 1024))
    recipe = {'formatVersion': 1, 'kind': 'ssr-package', 'name': config['name'], 'version': config['version'],
              'entrypoint': renderer['layer'], 'annotations': {}, 'layers': sorted(layers, key=lambda row: row['path'])}
    (inputs / 'package-source.json').write_bytes(canonical(recipe))
    return recipe, client_name


def inventory(recipe: dict, inputs: Path, toolchain: Path, source_inventory: bytes, tools: list[dict],
              dependencies: list[dict]) -> bytes:
    rows = list(dependencies)
    for layer in recipe['layers']:
        actual = file_identity(inputs / layer['source'], layer['path'], 32 * 1024 * 1024)
        rows.append({'kind': layer['role'], 'name': layer['path'], 'path': layer['path'],
                     'digest': actual['digest'], 'size': actual['size'], 'digestScope': 'output-bytes', 'origin': 'package-input'})
    used = decode(read(inputs, 'metadata/bundle-inputs.json', 1024 * 1024))
    guest = set()
    for name in [*used['server'], *used['client']]:
        pieces = name.split('/')
        guest.add('/'.join(pieces[:2]) if name.startswith('@') else pieces[0])
    # Includes the prebuilt JS engine's package as an embedding dependency.
    guest.add('@bytecodealliance/componentize-js')
    lock = decode(read(toolchain, 'package-lock.json', 4 * 1024 * 1024))
    for location, declared in lock['packages'].items():
        if not location or not (toolchain / location / 'package.json').is_file():
            continue  # a platform-specific optional dependency may be absent
        if not location.startswith('node_modules/'):
            raise SnapshotError('Angular npm source location is unsupported')
        raw = read(toolchain, location + '/package.json', 1024 * 1024)
        manifest = decode(raw)
        name, version = manifest.get('name'), manifest.get('version')
        if not isinstance(name, str) or not isinstance(version, str) or version != declared.get('version'):
            raise SnapshotError('Angular npm installed version differs from the lock')
        row = {'kind': 'guest-dependency' if name in guest else 'build-dependency', 'name': name, 'version': version,
               'source': 'urn:lsf:registry:npm/' + name, 'digest': digest(raw), 'digestScope': 'source-manifest',
               'manifestDigest': digest(raw), 'manifestSize': len(raw), 'origin': 'observed-cache'}
        # Preserve simple observed SPDX declarations; compound/unrecognized
        # declarations remain unattributed rather than guessed or normalized.
        if manifest.get('license') in ('MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC', 'CC0-1.0', '0BSD'):
            row['licenseExpression'] = manifest['license']
        rows.append(row)
    for tool in tools:
        rows.append({'kind': 'build-tool', 'name': tool['name'], 'source': 'urn:lsf:build-tool:' + tool['name'],
                     'digest': tool['digest'], 'size': tool['size'], 'digestScope': 'tool-executable', 'origin': 'toolchain'})
    rows = unique_entries(rows)
    result = {'formatVersion': 1, 'packageKind': 'ssr-package', 'packageName': recipe['name'],
              'packageVersion': recipe['version'], 'dependencyCompleteness': 'declared-inputs-incomplete',
              'sourceSnapshotDigest': digest(source_inventory), 'entries': sorted(rows, key=canonical)}
    encoded = canonical(result)
    if len(rows) > 1024 or len(encoded) > 1024 * 1024:
        raise SnapshotError('Angular SBOM inventory limit exceeded')
    return encoded


def unique_entries(rows: list[dict]) -> list[dict]:
    """Multiple npm installation locations may contain the same immutable unit.

    Keep one exact attribution; conflicting manifests are never silently merged.
    Actual installation locations remain bound by the npm tree and lock inputs.
    """
    identities = {}
    for row in rows:
        key = tuple(row.get(field) for field in ('kind', 'name', 'version', 'source', 'path'))
        previous = identities.setdefault(key, row)
        if previous != row:
            raise SnapshotError('conflicting Angular dependency inventory')
    return list(identities.values())
