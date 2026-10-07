#!/usr/bin/env python3
"""Capture explicitly selected static build outputs; never run a framework build."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_snapshot import SnapshotError, canonical, digest, is_reparse, owned_child, portable_path

MAX_ASSETS = 252
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_INPUT_BYTES = 256 * 1024
MAX_WEB_MANIFEST_BYTES = 256 * 1024
MAX_OBSERVATIONS = 8
MAX_OBSERVATION_BYTES = 1024 * 1024
MAX_EXCLUDED = 128
MAX_STYLE_HASHES = 64
MAX_PATH_BYTES = 232
MAX_SEGMENT_BYTES = 64
# Coupled to PackageLimits and MAX_WEB_* in latent-artifacts; this capture
# reserves web/capture metadata plus the native SBOM/build-input layers.
MAX_PACKAGE_LAYERS = 256
RESERVED_PACKAGE_LAYERS = 4
LARGEST_ASSETS = 5
MEDIA = {'html': 'text/html', 'js': 'text/javascript', 'mjs': 'text/javascript',
         'css': 'text/css', 'json': 'application/json', 'xml': 'application/xml', 'txt': 'text/plain',
         'svg': 'image/svg+xml', 'png': 'image/png', 'jpg': 'image/jpeg',
         'jpeg': 'image/jpeg', 'webp': 'image/webp', 'ico': 'image/x-icon', 'woff2': 'font/woff2'}


def require(condition, message):
    if not condition:
        raise SnapshotError('static-site-' + message)


def bounded(actual, maximum, name):
    require(actual <= maximum, f'{name}: actual={actual} maximum={maximum}')


def fields(value, required, optional=frozenset()):
    require(isinstance(value, dict) and required <= value.keys()
            and not value.keys() - required - optional, 'input-fields')


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate-json-key')
        result[key] = value
    return result


def decode(raw):
    bounded(len(raw), MAX_INPUT_BYTES, 'input-bytes')
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as error:
        raise SnapshotError('static-site-input-json') from error


def encode_input(config):
    # Programmatic fixture/tool callers receive the CLI's descriptor bound too.
    # Stop encoding at that bound rather than materializing an unlimited list.
    result = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    for piece in encoder.iterencode(config):
        raw = piece.encode()
        bounded(len(result) + len(raw), MAX_INPUT_BYTES, 'input-bytes')
        result.extend(raw)
    return bytes(result)


def path(value):
    require(isinstance(value, str) and len(value) <= MAX_PATH_BYTES, 'path')
    portable_path(value)
    require(all(len(part) <= MAX_SEGMENT_BYTES for part in value.split('/')), 'path-segment-bytes')
    return value


def public_path(value):
    require(isinstance(value, str) and value.startswith('/') and value != '/', 'public-path')
    path(value[1:])
    require(value.split('/')[1].lower() != '_lsf', 'reserved-namespace')
    return value


def public_file(value):
    path(value)
    parts = [piece.lower() for piece in value.split('/')]
    require(all(not part.startswith('.') for part in parts), 'hidden-path')
    require(not any(piece in {'server', 'ssr', 'private', 'secrets', 'credentials', 'node_modules'}
                    or piece.startswith(('server.', 'server-', 'credentials.', 'secret.')) for piece in parts),
            'private-output')
    require('.server.' not in value.lower() and not value.lower().endswith(('.map', '.pem', '.key')), 'private-output')
    extension = value.rsplit('.', 1)[-1]
    require(extension in MEDIA, 'unsupported-media')
    return MEDIA[extension]


def read(root, relative, maximum):
    """Read bounded regular bytes and reject links, replacements and escapes."""
    selected = root / relative
    owned_child(selected, root)
    before = selected.lstat()
    require(stat.S_ISREG(before.st_mode) and not is_reparse(selected), 'source-file')
    bounded(before.st_size, maximum, 'source-bytes')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(selected, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'source-replaced')
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    owned_child(selected, root)
    final = selected.lstat()
    require(not is_reparse(selected) and len(data) == before.st_size <= maximum
            and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            == (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns), 'source-changed')
    return data


def asset_digest(assets):
    value = hashlib.sha256()
    def part(data):
        value.update(len(data).to_bytes(8, 'little'))
        value.update(data)
    part(b'lsf-web-public-assets-v1')
    for asset in assets:
        for name in ('path', 'layer', 'digest', 'mediaType'):
            part(asset[name].encode())
        part(asset['size'].to_bytes(8, 'little'))
    return 'sha256:' + value.hexdigest()


def budget(config, input_raw, table, web_raw, observation, contents):
    """Describe only the bounded immutable capture; never reread source files."""
    paths = [row['path'][1:] for row in table] + [row['source'] for row in config['assets']]
    paths += config['excluded'] + [row['name'] for row in observation['observations']]
    def usage(actual, maximum, unit):
        return {'actual': actual, 'maximum': maximum, 'remaining': maximum - actual, 'unit': unit}
    largest = sorted(table, key=lambda row: (-row['size'], row['path']))[:LARGEST_ASSETS]
    distinct = {row['digest']: row['size'] for row in table}
    source = next(row for row in observation['observations'] if row['kind'] == 'source')
    return {'schemaVersion': 'latent.static-site.budget.v1', 'complete': True,
            'selection': {'captureProfile': config['profile'], 'webProfile': 'lsf.web-release.v1',
                          'routingProfile': 'static-site-v1', 'packageName': config['name'],
                          'packageVersion': config['version'], 'sourceObservationDigest': source['digest'],
                          'inputDescriptorDigest': digest(input_raw), 'assetsDigest': observation['assetsDigest'],
                          'webManifestDigest': observation['webManifestDigest'], 'inputObservationTrust': 'operator-supplied'},
            'captureLimits': {
                'publicAssetCount': usage(len(table), MAX_ASSETS, 'paths'),
                'largestAssetBytes': usage(max(row['size'] for row in table), MAX_ASSET_BYTES, 'bytes'),
                'logicalPublicBytes': usage(sum(row['size'] for row in table), MAX_TREE_BYTES, 'bytes'),
                'webManifestBytes': usage(len(web_raw), MAX_WEB_MANIFEST_BYTES, 'bytes'),
                'inputDescriptorBytes': usage(len(input_raw), MAX_INPUT_BYTES, 'bytes'),
                'longestRelativePathBytes': usage(max(len(value.encode()) for value in paths), MAX_PATH_BYTES, 'bytes'),
                'longestPathSegmentBytes': usage(max(len(part.encode()) for value in paths for part in value.split('/')), MAX_SEGMENT_BYTES, 'bytes'),
                'excludedCount': usage(len(config['excluded']), MAX_EXCLUDED, 'paths'),
                'styleHashCount': usage(len(config.get('styleHashes', [])), MAX_STYLE_HASHES, 'hashes'),
                'observationCount': usage(len(observation['observations']), MAX_OBSERVATIONS, 'files'),
                'largestObservationBytes': usage(max(row['size'] for row in observation['observations']), MAX_OBSERVATION_BYTES, 'bytes'),
                'packageNameBytes': usage(len(config['name'].encode()), 128, 'bytes'),
                'packageVersionBytes': usage(len(config['version'].encode()), 128, 'bytes')},
            'largestAssets': [{'path': row['path'], 'size': row['size'], 'digest': row['digest']} for row in largest],
            'largestAssetsMaximum': LARGEST_ASSETS,
            'storageObservation': {'distinctPublicDigests': len(distinct), 'deduplicatedPublicBytes': sum(distinct.values()),
                                   'accounting': 'logical-paths-charged-independently', 'catalogCapacityObserved': False},
            'generatedInputs': {'scope': 'capture-inputs-before-assembly',
                                'webManifestBytes': len(web_raw), 'captureObservationBytes': len(contents['metadata/static-observation.json']),
                                'packageSourceBytes': len(contents['package-source.json']), 'sbomInputsBytes': len(contents['sbom-inputs.json']),
                                'capturedMetadataLayers': 2, 'capturedLayers': len(table) + 2,
                                'reservedPackageLayers': RESERVED_PACKAGE_LAYERS, 'packageLayerCeiling': MAX_PACKAGE_LAYERS,
                                'standardPackageLayers': usage(len(table) + RESERVED_PACKAGE_LAYERS, MAX_PACKAGE_LAYERS, 'layers'),
                                'finalPackageBytesObserved': False},
            'qualification': {'signingVerified': False, 'admissionVerified': False, 'browserQualified': False, 'servingQualified': False},
            'nodeCapacity': 'not-observed'}


def human_budget(report):
    selection = report['selection']
    lines = [report['schemaVersion'] + ' complete',
             f"{selection['captureProfile']} / {selection['webProfile']} / {selection['routingProfile']}",
             f"Package {selection['packageName']} {selection['packageVersion']}; operator-supplied source {selection['sourceObservationDigest']}"]
    for name, row in report['captureLimits'].items():
        lines.append(f"{name}: {row['actual']}/{row['maximum']} {row['unit']}; remaining {row['remaining']}")
    lines.append(f"Largest assets (maximum {report['largestAssetsMaximum']}; ties by public path):")
    lines.extend(f"  {json.dumps(row['path'])}: {row['size']} bytes" for row in report['largestAssets'])
    storage, generated = report['storageObservation'], report['generatedInputs']
    lines.append(f"Distinct public content: {storage['distinctPublicDigests']} digests, {storage['deduplicatedPublicBytes']} bytes; logical paths remain independently charged")
    lines.append(f"Generated inputs: web {generated['webManifestBytes']}, capture {generated['captureObservationBytes']}, recipe {generated['packageSourceBytes']}, SBOM input {generated['sbomInputsBytes']} bytes")
    layers = generated['standardPackageLayers']
    lines.append(f"Standard package layers: {layers['actual']}/{layers['maximum']}; remaining {layers['remaining']}; {generated['reservedPackageLayers']} reserved metadata/SBOM layers")
    lines.append('Final package and node/catalog capacity not observed; signing, admission, browser and serving qualification remain required.')
    return '\n'.join(lines)


def capture(root: Path, config: dict, destination: Path, *, input_raw: bytes | None = None) -> dict:
    root, destination = root.absolute(), destination.absolute()
    require(root.is_dir() and not any(is_reparse(p) for p in [root, *root.parents]), 'root-link')
    require(not destination.exists() and root != destination and root not in destination.parents, 'output-root')
    require(destination.parent.is_dir() and not any(is_reparse(p) for p in [destination.parent, *destination.parent.parents]), 'output-link')
    # Freeze the explicit descriptor too. CLI reporting uses its exact supplied
    # bytes; programmatic callers use canonical JSON, with the same input bound.
    input_raw = encode_input(config) if input_raw is None else input_raw
    selected = decode(input_raw)
    require(selected == config, 'input-descriptor-changed')
    config = selected
    fields(config, {'formatVersion', 'profile', 'name', 'version', 'assets', 'entryDocument',
                    'directoryIndex', 'fallback', 'excluded', 'observations'}, {'styleHashes', 'errorDocument'})
    styles = config.get('styleHashes', [])
    require(isinstance(styles, list) and len(styles) <= MAX_STYLE_HASHES
            and all(isinstance(value, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value) for value in styles)
            and styles == sorted(set(styles)), 'style-hashes')
    require(type(config['formatVersion']) is int and config['formatVersion'] == 1
            and config['profile'] == 'static-site-input-v1', 'profile')
    require(isinstance(config['name'], str) and re.fullmatch(r'[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?', config['name']), 'package-name')
    require(isinstance(config['version'], str) and len(config['version']) <= 128 and re.fullmatch(
        r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?', config['version']), 'package-version')
    prerelease = config['version'].split('+', 1)[0].partition('-')[2]
    require(not any(piece.isdigit() and len(piece) > 1 and piece.startswith('0')
                    for piece in prerelease.split('.')), 'package-version')
    assets = config['assets']
    require(isinstance(assets, list) and assets, 'asset-count')
    bounded(len(assets), MAX_ASSETS, 'asset-count')
    excluded = config['excluded']
    require(isinstance(excluded, list) and len(excluded) <= MAX_EXCLUDED, 'excluded-count')
    exclusions = {path(item).casefold() for item in excluded}
    require(len(exclusions) == len(excluded), 'excluded-collision')
    names, sources, captured = set(), set(), []
    total = 0
    for asset in assets:
        fields(asset, {'path', 'source'}, {'mediaType'})
        name, source = public_path(asset['path']), path(asset['source'])
        media = public_file(name[1:])
        require(public_file(source) == media and asset.get('mediaType', media) == media, 'media-mismatch')
        require(name.casefold() not in names and source.casefold() not in sources and source.casefold() not in exclusions, 'asset-collision-or-exclusion')
        names.add(name.casefold()); sources.add(source.casefold())
        data = read(root, source, MAX_ASSET_BYTES)
        total += len(data)
        bounded(total, MAX_TREE_BYTES, 'asset-tree-bytes')
        captured.append(({'path': name, 'layer': 'public' + name, 'digest': digest(data),
                          'size': len(data), 'mediaType': media}, data))
    captured.sort(key=lambda row: row[0]['path'])
    table = [row[0] for row in captured]
    by_path = {row['path']: row for row in table}
    def html(name):
        public_path(name)
        require(name in by_path and by_path[name]['mediaType'] == 'text/html', 'missing-html-document')
        return name
    entry = html(config['entryDocument'])
    index, fallback = config['directoryIndex'], config['fallback']
    fields(index, {'mode', 'document'})
    require(index['mode'] in ('disabled', 'redirect'), 'directory-index-mode')
    html(index['document'])
    fields(fallback, {'mode'}, {'document'})
    require(fallback['mode'] in ('none', 'spa'), 'fallback-mode')
    require((fallback['mode'] == 'spa') == ('document' in fallback), 'fallback-document')
    if fallback['mode'] == 'spa':
        html(fallback['document'])
    error_document = config.get('errorDocument')
    if 'errorDocument' in config:
        fields(error_document, {'profile', 'document'})
        require(error_document['profile'] == 'html-not-found-v1', 'error-document-profile')
        html(error_document['document'])
    declared = config['observations']
    require(isinstance(declared, list) and 3 <= len(declared) <= MAX_OBSERVATIONS, 'observation-count')
    observations, seen = [], set()
    for row in declared:
        fields(row, {'kind', 'source', 'digest'})
        require(row['kind'] in {'source', 'toolchain', 'build'}, 'observation-kind')
        source = path(row['source'])
        require(source.casefold() not in seen and source.casefold() not in sources, 'observation-collision')
        seen.add(source.casefold())
        data = read(root, source, MAX_OBSERVATION_BYTES)
        require(data, 'empty-observation')
        require(row['digest'] == digest(data), 'observation-digest')
        observations.append({'kind': row['kind'], 'name': source, 'digest': digest(data), 'size': len(data)})
    require({row['kind'] for row in observations} == {'source', 'toolchain', 'build'}
            and sum(row['kind'] == 'source' for row in observations) == 1, 'observation-kinds')
    routing = {'profile': 'static-site-v1', 'entryDocument': entry,
               'directoryIndex': index['mode'], 'directoryIndexDocument': index['document'], 'fallback': fallback}
    if error_document is not None:
        routing['errorDocument'] = error_document
    routes = [{'path': '/', 'mode': 'client', 'asset': entry}] if index['mode'] == 'disabled' else []
    web = {'formatVersion': 1, 'profile': 'lsf.web-release.v1', 'assetsDigest': asset_digest(table),
           'assets': table, 'routes': routes, 'staticRouting': routing}
    if styles:
        web['styleHashes'] = styles
    web_raw = canonical(web)
    bounded(len(web_raw), MAX_WEB_MANIFEST_BYTES, 'web-manifest-bytes')
    observation = {'schemaVersion': 'latent.static-site.capture.v1', 'inputObservationTrust': 'operator-supplied',
                   'frameworkBuildExecuted': False, 'reproducibility': 'not-checked',
                   'observations': sorted(observations, key=lambda row: (row['kind'], row['name'])),
                   'excluded': sorted(excluded), 'assetsDigest': web['assetsDigest'],
                   'webManifestDigest': digest(web_raw), 'routingDigest': digest(canonical(routing))}
    contents = {row['layer']: data for row, data in captured}
    contents['metadata/web-application.json'] = web_raw
    contents['metadata/static-observation.json'] = canonical(observation)
    layers = [{'path': name, 'source': name, 'role': 'asset',
               'mediaType': by_path[name[6:]]['mediaType'] if name.startswith('public/') else 'application/json'}
              for name in sorted(contents)]
    recipe = {'formatVersion': 1, 'kind': 'browser-assets', 'name': config['name'], 'version': config['version'],
              'entrypoint': 'public' + entry, 'annotations': {}, 'layers': layers}
    inventory = {'formatVersion': 1, 'packageKind': 'browser-assets', 'packageName': config['name'],
                 'packageVersion': config['version'], 'dependencyCompleteness': 'declared-inputs-incomplete',
                 'sourceSnapshotDigest': next(row['digest'] for row in observations if row['kind'] == 'source'),
                 'entries': [{'kind': 'asset', 'name': name, 'path': name, 'digest': digest(data),
                              'size': len(data), 'digestScope': 'output-bytes', 'origin': 'package-input'}
                             for name, data in sorted(contents.items())]}
    contents.update({'package-source.json': canonical(recipe), 'sbom-inputs.json': canonical(inventory)})
    report = budget(config, input_raw, table, web_raw, observation, contents)
    destination.mkdir()
    for name, data in sorted(contents.items()):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
    # Diagnostics never enter web metadata, SBOM inputs or capture provenance.
    return {**observation, 'budget': report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-output', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--format', choices=('json', 'human'), default='json')
    args = parser.parse_args()
    try:
        raw = read(args.input.absolute().parent, args.input.name, MAX_INPUT_BYTES)
        result = capture(args.build_output, decode(raw), args.output, input_raw=raw)
        print(human_budget(result['budget']) if args.format == 'human' else json.dumps(result, sort_keys=True))
        return 0
    except (SnapshotError, OSError, ValueError, TypeError) as error:
        print(str(error) if isinstance(error, SnapshotError) else 'static-site-capture-failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
