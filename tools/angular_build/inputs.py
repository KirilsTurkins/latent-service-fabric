"""Closed application inputs, captured without links, discovery or executable hooks."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools.build_observation import file_identity
from tools.build_snapshot import SnapshotError, canonical, digest, owned_child, portable_path

PROFILE = "angular-ssr-component-v1"
MAX_SOURCE_FILES = 256
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ASSETS = 126  # leave room for the generated immutable client and entry document
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_ASSET_TREE_BYTES = 16 * 1024 * 1024
MEDIA = {"html": "text/html", "js": "text/javascript", "mjs": "text/javascript",
         "css": "text/css", "json": "application/json", "txt": "text/plain",
         "svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg",
         "jpeg": "image/jpeg", "webp": "image/webp", "ico": "image/x-icon", "woff2": "font/woff2"}


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise SnapshotError("duplicate Angular input field")
        result[key] = value
    return result


def decode(data: bytes):
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as error:
        raise SnapshotError("invalid Angular input JSON") from error


def fields(value, required: set[str], optional=frozenset()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise SnapshotError("unsupported Angular input fields")


def path(value, prefix: str | None = None) -> str:
    if not isinstance(value, str) or len(value) > 220:
        raise SnapshotError("invalid Angular input path")
    portable_path(value)
    if any(piece.startswith('.') or len(piece) > 64 for piece in value.split('/')) or (prefix and not value.startswith(prefix)):
        raise SnapshotError("Angular input path is outside its declared area")
    return value


def url_path(value) -> str:
    if value == '/':
        return value
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('/_lsf/assets/'):
        raise SnapshotError("invalid Angular route or asset path")
    path(value[1:])
    return value


def read(root: Path, relative: str, maximum: int) -> bytes:
    selected = root / relative
    owned_child(selected, root)
    identity = file_identity(selected, relative, maximum)
    with selected.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) != identity['size'] or digest(data) != identity['digest']:
        raise SnapshotError("Angular input changed during capture")
    return data


def validate(value: dict) -> None:
    fields(value, {'formatVersion', 'profile', 'name', 'version', 'serverEntry', 'clientEntry', 'sources', 'assets', 'routes'}, {'backendProfile'})
    if value.get('backendProfile', 'none') not in ('none', 'scoped-http-get-v1'):
        raise SnapshotError('unsupported Angular backend profile')
    if type(value['formatVersion']) is not int or value['formatVersion'] != 1 or value['profile'] != PROFILE:
        raise SnapshotError("unsupported Angular build profile")
    if not isinstance(value['name'], str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?', value['name']):
        raise SnapshotError("invalid Angular package name")
    version = value['version']
    if not isinstance(version, str) or len(version) > 128 or not re.fullmatch(
            r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?', version):
        raise SnapshotError("invalid Angular package version")
    prerelease = version.split('+', 1)[0].partition('-')[2]
    if any(item.isdigit() and len(item) > 1 and item.startswith('0') for item in prerelease.split('.')):
        raise SnapshotError("invalid Angular prerelease version")
    for key, prefix in (('serverEntry', 'server/'), ('clientEntry', 'client/')):
        if not path(value[key], prefix).endswith('.ts'):
            raise SnapshotError("Angular entry must be TypeScript")
    sources = value['sources']
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCE_FILES:
        raise SnapshotError("Angular source count exceeded")
    for name in sources:
        path(name)
        if name.split('/')[0] not in ('server', 'client', 'shared') or Path(name).suffix not in ('.ts', '.html', '.css'):
            raise SnapshotError("unsupported Angular source kind")
    if len({name.lower() for name in sources}) != len(sources) or any(value[key] not in sources for key in ('serverEntry', 'clientEntry')):
        raise SnapshotError("duplicate or missing Angular source")
    assets = value['assets']
    if not isinstance(assets, list) or len(assets) > MAX_ASSETS:
        raise SnapshotError("Angular asset count exceeded")
    names, layers = set(), set()
    for asset in assets:
        fields(asset, {'path', 'source'})
        name, source = url_path(asset['path']), path(asset['source'], 'public/')
        if Path(name).suffix != Path(source).suffix or name.rsplit('.', 1)[-1] not in MEDIA:
            raise SnapshotError("unsupported Angular public asset type")
        if name.lower() in names or source.lower() in layers or name.startswith('/client/'):
            raise SnapshotError("duplicate or reserved Angular public asset")
        names.add(name.lower()); layers.add(source.lower())
    routes = value['routes']
    if not isinstance(routes, list) or not 1 <= len(routes) <= 128:
        raise SnapshotError("Angular route count exceeded")
    paths = set()
    for route in routes:
        fields(route, {'path', 'mode'}, {'asset'})
        name = url_path(route['path'])
        if name.lower() in paths:
            raise SnapshotError("duplicate Angular route")
        paths.add(name.lower())
        if route['mode'] == 'server':
            if 'asset' in route:
                raise SnapshotError("server route cannot name a supplied prerender")
        elif route['mode'] in ('client', 'prerender'):
            if not isinstance(route.get('asset'), str) or not any(a['path'] == route['asset'] and a['path'].endswith('.html') for a in assets):
                raise SnapshotError("Angular static route requires an explicit HTML asset")
        else:
            raise SnapshotError("unsupported Angular route mode")


def capture(source: Path, config_path: str, destination: Path) -> tuple[dict, bytes]:
    raw = read(source, path(config_path), 64 * 1024)
    config = decode(raw)
    validate(config)
    destination.mkdir()
    records = [{'path': config_path, 'digest': digest(raw), 'size': len(raw)}]
    names = [*config['sources'], *(asset['source'] for asset in config['assets'])]
    total = assets_total = 0
    for name in sorted(names):
        is_asset = name.startswith('public/')
        data = read(source, name, MAX_ASSET_BYTES if is_asset else 1024 * 1024)
        if is_asset:
            assets_total += len(data)
        else:
            total += len(data)
        if total > MAX_SOURCE_BYTES or assets_total > MAX_ASSET_TREE_BYTES:
            raise SnapshotError("Angular input aggregate bytes exceeded")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append({'path': name, 'digest': digest(data), 'size': len(data)})
    inventory = canonical(sorted(records, key=lambda row: row['path']))
    (destination / 'angular-build.json').write_bytes(canonical(config))
    return config, inventory
