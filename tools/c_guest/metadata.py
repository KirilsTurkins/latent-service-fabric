"""Project contracts projected from wasm-tools' resolved WIT, not C/regex types."""
from __future__ import annotations

import json
from pathlib import Path
import re

from tools.c_guest.bindings import digest

PRIMITIVES = {name: name[0].upper() + name[1:] for name in
              ('bool', 'u8', 'u16', 'u32', 'u64', 's8', 's16', 's32', 's64',
               'f32', 'f64', 'char', 'string')}
PLATFORM = frozenset((
    'latent:context/context@0.1.0', 'latent:log/log@0.1.0',
    'latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0',
    'latent:random/random@0.1.0', 'latent:blob/blob@0.2.0',
    'latent:secrets/reader@0.1.0', 'latent:events/publisher@0.2.0',
    'latent:http/client@0.2.0', 'latent:http/streaming@0.3.0',
    'latent:telemetry/custom@0.1.0', 'latent:service/invoke@0.1.0',
))


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def field(name: str, value: object) -> dict:
    return {'name': name, 'value_type': value, 'documentation': None}


class Projection:
    def __init__(self, resolved: dict):
        self.resolved = resolved
        for name in ('types', 'interfaces', 'worlds', 'packages'):
            if not isinstance(resolved.get(name), list) or len(resolved[name]) > 4096:
                raise ValueError('invalid or oversized WIT resolver inventory')
        self.types = resolved['types']

    def value(self, value: object, visiting: tuple[int, ...] = ()) -> object:
        if isinstance(value, str) and value in PRIMITIVES:
            return PRIMITIVES[value]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(self.types):
            raise ValueError('unsupported WIT value type')
        if value in visiting or len(visiting) >= 64:
            raise ValueError('recursive or excessively nested WIT value type')
        node = self.types[value]
        kind = node['kind']
        if not isinstance(kind, dict) or len(kind) != 1:
            raise ValueError('unsupported WIT type representation')
        tag, inner = next(iter(kind.items()))
        convert = lambda child: self.value(child, (*visiting, value))
        if tag == 'type':
            return convert(inner)
        if tag in ('list', 'option'):
            return {tag.title(): convert(inner)}
        if tag == 'tuple':
            types = inner['types'] if isinstance(inner, dict) else inner
            if not isinstance(types, list) or len(types) > 64:
                raise ValueError('unsupported WIT tuple')
            return {'Tuple': [convert(child) for child in types]}
        if tag == 'result':
            return {'Result': {'ok': None if inner['ok'] is None else convert(inner['ok']),
                               'error': None if inner['err'] is None else convert(inner['err'])}}
        if tag in ('record', 'variant') and isinstance(node.get('name'), str):
            # Named record/variant fields remain authoritative in the WIT lock.
            # Walk all fields anyway: a hidden unsupported type cannot be smuggled
            # behind a supported name. Descriptor projection matches the runtime.
            children = inner['fields' if tag == 'record' else 'cases']
            if not isinstance(children, list) or len(children) > 256:
                raise ValueError('oversized WIT aggregate')
            for child in children:
                if child['type'] is not None:
                    convert(child['type'])
            return {tag.title(): node['name']}
        raise ValueError('unsupported exported WIT type: ' + tag)

    def interface_id(self, index: int) -> str:
        interface = self.resolved['interfaces'][index]
        package = self.resolved['packages'][interface['package']]['name']
        name, version = package.rsplit('@', 1)
        return name + '/' + interface['name'] + '@' + version

    def selected_world(self, identity: str) -> dict:
        matches = []
        for world in self.resolved['worlds']:
            package = self.resolved['packages'][world['package']]['name']
            name, version = package.rsplit('@', 1)
            if name + '/' + world['name'] + '@' + version == identity:
                matches.append(world)
        if len(matches) != 1:
            raise ValueError('select exactly one fully versioned application world')
        return matches[0]

    @staticmethod
    def interface_index(item: dict) -> int:
        if set(item) != {'interface'} or not isinstance(item['interface'].get('id'), int):
            raise ValueError('capsules require named interface imports and exports')
        return item['interface']['id']

    def contracts(self, identity: str) -> tuple[bytes, list[str], list[str]]:
        world = self.selected_world(identity)
        imports = sorted(self.interface_id(self.interface_index(item))
                         for item in world['imports'].values())
        if len(imports) != len(set(imports)) or not set(imports) <= PLATFORM:
            raise ValueError('application imports must use exact current platform WIT identities')
        descriptors, exports = [], []
        for item in world['exports'].values():
            index = self.interface_index(item)
            interface = self.resolved['interfaces'][index]
            contract = self.interface_id(index)
            if contract in exports:
                raise ValueError('duplicate exported contract')
            functions = []
            for name, function in interface['functions'].items():
                kind = function['kind']
                if kind not in ('freestanding', 'async-freestanding'):
                    raise ValueError('exported resource methods are outside the capsule value profile')
                if len(function['params']) > 64:
                    raise ValueError('too many WIT parameters')
                result = function.get('result')
                functions.append({'id': name, 'name': name,
                    'asynchronous': kind == 'async-freestanding', 'documentation': None, 'attributes': {},
                    'parameters': [field(param['name'], self.value(param['type'])) for param in function['params']],
                    'results': [] if result is None else [field('result', self.value(result))]})
            if not functions or len(functions) > 128:
                raise ValueError('empty or oversized exported interface')
            projected = {'id': contract, 'documentation': None, 'functions': functions}
            projected['digest'] = digest(canonical(projected))
            package = self.resolved['packages'][interface['package']]['name']
            package_name, version = package.rsplit('@', 1)
            descriptor = {'id': contract, 'package_name': package_name,
                          'semantic_version': version, 'interfaces': [projected], 'dependencies': []}
            descriptor['digest'] = digest(canonical(descriptor))
            descriptors.append(descriptor)
            exports.append(contract)
        if not descriptors or len(descriptors) > 32:
            raise ValueError('empty or oversized world exports')
        return canonical({'format_version': 1, 'contracts': descriptors}), sorted(exports), imports


def locked_sources(staged: Path, destination: Path, resolved: dict) -> list[dict]:
    """One bounded WIT source per package in the initial C project layout.

    Only package identities and dependency edges are read from text here; the
    authoritative parser has already validated every type and reference.
    """
    files = sorted(staged.rglob('*.wit'))
    known = {package['name'] for package in resolved['packages']}
    records, contents = {}, {}
    for source in files:
        data = source.read_bytes()
        if len(data) > 262144:
            raise ValueError('oversized WIT package')
        text = data.decode('utf-8')
        declarations = re.findall(r'\bpackage\s+([a-z0-9:-]+@[0-9][a-zA-Z0-9.+-]*)\s*;', text)
        if len(declarations) != 1 or declarations[0] not in known:
            raise ValueError('one versioned declaration per WIT source is required')
        name = declarations[0]
        if name in contents:
            raise ValueError('C authoring currently requires one source file per WIT package')
        dependencies = sorted({a + '@' + b for a, b in re.findall(
            r'([a-z0-9-]+:[a-z0-9-]+)/[a-z0-9-]+@([0-9][a-zA-Z0-9.+-]*)', text)} - {name})
        if not set(dependencies) <= known:
            raise ValueError('WIT dependency is absent from the authoritative resolver')
        contents[name] = data
        records[name] = dependencies
    if set(contents) != known:
        raise ValueError('WIT resolver and source inventories differ')
    directory = destination / 'wit'
    directory.mkdir()
    result = []
    for index, name in enumerate(sorted(contents)):
        path = f'wit/package-{index}.wit'
        (destination / path).write_bytes(contents[name])
        result.append({'id': name, 'sourcePath': path, 'digest': digest(contents[name]),
                       'dependencies': records[name]})
    return result
