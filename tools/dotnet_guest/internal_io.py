"""Paired, private WASI I/O function-type projection for the closed CLR port.

Core modules are unbundled and reinserted byte-for-byte. Only the four matched
internal I/O function types may change; the complete resulting WIT graph must
equal that explicit projection. Public application types are never projected.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time

from tools.rust_capsule_project import digest, read_file, write_json

PROFILE = 'dotnet-private-async-io-v1'
TARGETS = {'wasi:io/poll@0.2.6': {'poll', '[method]pollable.block'},
           'wasi:io/streams@0.2.6': {'[method]input-stream.blocking-read', '[method]output-stream.blocking-flush'}}
MAX_BINARY, MAX_TEXT = 64*1024*1024, 16*1024*1024


@dataclass
class Node:
    start: int
    end: int
    items: list

    def head(self, name):
        return bool(self.items) and self.items[0] == name


def tree(text):
    if len(text.encode()) > MAX_TEXT:
        raise ValueError('dotnet-internal-io-metadata-text-limit')
    offset, count = 0, 0

    def whitespace():
        nonlocal offset
        while offset < len(text):
            if text[offset].isspace(): offset += 1
            elif text.startswith('(;', offset):
                depth = 1
                offset += 2
                while depth and offset < len(text):
                    if text.startswith('(;', offset): depth += 1; offset += 2
                    elif text.startswith(';)', offset): depth -= 1; offset += 2
                    else: offset += 1
                if depth: raise ValueError('dotnet-internal-io-unbalanced-comment')
            elif text.startswith(';;', offset):
                newline = text.find('\n', offset)
                offset = len(text) if newline == -1 else newline + 1
            else: break

    def value(depth):
        nonlocal offset, count
        whitespace()
        count += 1
        if depth > 128 or count > 250000 or offset >= len(text):
            raise ValueError('dotnet-internal-io-metadata-structure-limit')
        start = offset
        if text[offset] == '(':
            offset += 1
            items = []
            while True:
                whitespace()
                if offset >= len(text): raise ValueError('dotnet-internal-io-unbalanced-text')
                if text[offset] == ')':
                    offset += 1
                    return Node(start, offset, items)
                items.append(value(depth + 1))
        if text[offset] == '"' or text.startswith('$"', offset):
            if text[offset] == '$': offset += 1
            offset += 1
            while offset < len(text):
                if text[offset] == '\\': offset += 2
                elif text[offset] == '"':
                    offset += 1
                    return text[start:offset]
                else: offset += 1
            raise ValueError('dotnet-internal-io-unbalanced-string')
        while offset < len(text) and not text[offset].isspace() and text[offset] not in '()': offset += 1
        if offset == start: raise ValueError('dotnet-internal-io-invalid-token')
        return text[start:offset]

    result = value(0)
    whitespace()
    if offset != len(text) or not isinstance(result, Node) or not result.head('component'):
        raise ValueError('dotnet-internal-io-component-shape')
    return result


def interface_name(graph, index):
    interface = graph['interfaces'][index]
    package = graph['packages'][interface['package']]['name']
    base, sep, version = package.partition('@')
    return base + '/' + interface['name'] + (sep + version if sep else '')


def named_export_syntax(text):
    """Repair the pinned printer's identifier placement in type exports.

    --name-unnamed places an optional identifier before the export string,
    whereas the pinned text parser requires it inside the item signature.
    Identifiers have no type or runtime meaning; final complete graphs and all
    original core bytes are independently compared after actual encoding.
    """
    edits = []
    def walk(node, *, type_body=False):
        if (type_body and node.head('export') and len(node.items) == 4
                and isinstance(node.items[1], str) and node.items[1].startswith('$')
                and isinstance(node.items[2], str) and node.items[2].startswith('"')
                and isinstance(node.items[3], Node)):
            inner = node.items[3]
            if inner.items[0] not in {'type', 'func', 'instance', 'component'}:
                raise ValueError('dotnet-internal-io-named-export-kind')
            body = text[inner.start:inner.end]
            prefix = '(' + inner.items[0]
            body = prefix + ' ' + node.items[1] + body[len(prefix):]
            edits.append((node.start, node.end, '(export ' + node.items[2] + ' ' + body + ')'))
            return
        for item in node.items:
            if isinstance(item, Node):
                nested_type = type_body or node.head('type') and (item.head('instance') or item.head('component'))
                walk(item, type_body=nested_type)
    walk(tree(text))
    for start, end, value in sorted(edits, reverse=True): text = text[:start]+value+text[end:]
    return text


def functions(graph, direction):
    if len(graph['worlds']) != 1:
        raise ValueError('dotnet-internal-io-world-count')
    result = {}
    for item in graph['worlds'][0][direction].values():
        if 'interface' in item:
            index = item['interface']['id']
            result[interface_name(graph, index)] = graph['interfaces'][index]['functions']
    return result


def shape(graph, value, *, type_index=False, depth=0):
    if depth > 64: raise ValueError('dotnet-internal-io-type-depth')
    if type_index and type(value) is int:
        row = graph['types'][value]
        owner = row.get('owner')
        nominal = interface_name(graph, owner['interface']) if owner and 'interface' in owner else None
        return {'name': row['name'], 'owner': nominal,
                'kind': shape(graph, row['kind'], depth=depth+1)}
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == 'docs': continue
            if key == 'kind' and isinstance(child, dict) and set(child) <= {'method', 'async-method'}:
                result[key] = {'method': shape(graph, next(iter(child.values())), type_index=True, depth=depth+1)}
            elif key == 'kind' and child in ('freestanding', 'async-freestanding'):
                result[key] = 'freestanding'
            else:
                result[key] = shape(graph, child, type_index=key in {'type', 'result', 'borrow', 'own', 'list', 'ok', 'err'}, depth=depth+1)
        return result
    if isinstance(value, list):
        return [shape(graph, child, depth=depth+1) for child in value]
    return value


def projection(original, adapter):
    expected = copy.deepcopy(original)
    imported, supplied = functions(expected, 'imports'), functions(adapter, 'exports')
    selected = {}
    for interface, names in TARGETS.items():
        for name in sorted(names & imported.get(interface, {}).keys()):
            function = imported[interface][name]
            candidate = supplied.get(interface, {}).get(name)
            if candidate is None or shape(expected, function) != shape(adapter, candidate):
                raise ValueError('dotnet-internal-io-function-shape:' + interface + '#' + name)
            kind = function['kind']
            if kind == 'freestanding': function['kind'] = 'async-freestanding'
            elif isinstance(kind, dict) and set(kind) == {'method'}: function['kind'] = {'async-method': kind['method']}
            else: raise ValueError('dotnet-internal-io-preimage-kind')
            if not (candidate['kind'] == 'async-freestanding' or
                    isinstance(candidate['kind'], dict) and set(candidate['kind']) == {'async-method'}):
                raise ValueError('dotnet-internal-io-adapter-type-must-match')
            selected.setdefault(interface, []).append(name)
    return expected, selected


def adapted_text(text, selected):
    root = tree(text)
    rows = [node for node in root.items if isinstance(node, Node)]
    types = {node.items[1]: node for node in rows if node.head('type') and isinstance(node.items[1], str)}
    edits, ordinal = [], 0
    for node in rows:
        if not node.head('import'): continue
        name = node.items[1]
        if name.strip('"') in selected:
            names = set(selected[name.strip('"')])
            use = node.items[2]
            refs = [item for item in use.items if isinstance(item, Node) and item.head('type')]
            if len(refs) != 1 or refs[0].items[1] not in types: raise ValueError('dotnet-internal-io-instance-type-use')
            instance = types[refs[0].items[1]].items[-1]
            local = {item.items[1]: item for item in instance.items if isinstance(item, Node) and item.head('type')}
            found = set()
            for export in instance.items:
                if not isinstance(export, Node) or not export.head('export'): continue
                symbols = [item.strip('"') for item in export.items if isinstance(item, str) and item.startswith('"')]
                if len(symbols) != 1 or symbols[0] not in names: continue
                name = symbols[0]
                if name in found: raise ValueError('dotnet-internal-io-duplicate-function')
                function = export.items[-1]
                reference = function.items[-1]
                if not function.head('func') or not isinstance(reference, Node) or not reference.head('type'):
                    raise ValueError('dotnet-internal-io-function-type-use')
                original_type = local[reference.items[1]].items[-1]
                if not original_type.head('func') or original_type.items[1:2] == ['async']:
                    raise ValueError('dotnet-internal-io-function-type-preimage')
                identifier = '$lsf-private-async-io-' + str(ordinal)
                ordinal += 1
                if identifier in local: raise ValueError('dotnet-internal-io-type-name-collision')
                body = text[original_type.start:original_type.end].replace('(func', '(func async', 1)
                # Clone the type: read and blocking-read often share a type.
                # Every original reference is named by the pinned printer.
                copied_export = text[export.start:export.end]
                relative_start, relative_end = reference.start-export.start, reference.end-export.start
                copied_export = copied_export[:relative_start] + '(type ' + identifier + ')' + copied_export[relative_end:]
                edits.append((export.start, export.end, '(type ' + identifier + ' ' + body + ')\n      ' + copied_export))
                found.add(name)
            if found != names: raise ValueError('dotnet-internal-io-missing-function')
    for start, end, value in sorted(edits, reverse=True): text = text[:start] + value + text[end:]
    if len(text.encode()) > MAX_TEXT: raise ValueError('dotnet-internal-io-reconstructed-text-limit')
    return text


def integer(data, position):
    value, shift = 0, 0
    while True:
        if position >= len(data) or shift >= 35: raise ValueError('dotnet-internal-io-section-length')
        byte, position = data[position], position+1
        value |= (byte & 127) << shift
        if byte < 128:
            if value > 0xffffffff: raise ValueError('dotnet-internal-io-section-length')
            return value, position
        shift += 7


def encoded_integer(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def sections(data):
    if len(data) > MAX_BINARY or data[:8] != b'\0asm\x0d\0\x01\0':
        raise ValueError('dotnet-internal-io-component-binary')
    position = 8
    while position < len(data):
        start = position
        kind, position = data[position], position+1
        length, position = integer(data, position)
        end = position + length
        if end > len(data): raise ValueError('dotnet-internal-io-section-bounds')
        yield kind, data[position:end], data[start:end]
        position = end


def core_modules(data):
    result = []
    for kind, payload, _raw in sections(data):
        if kind == 1:
            if payload[:8] != b'\0asm\x01\0\0\0': raise ValueError('dotnet-internal-io-core-header')
            result.append(payload)
        elif kind == 4: result.extend(core_modules(payload))
    return result


def rebundle(data, modules):
    """Replace only the pinned unbundler's standalone core-module imports.

    All other sections remain exact encoder output. Module payloads are never
    parsed, disassembled or rewritten. Unsupported import grouping fails closed.
    """
    result, consumed = bytearray(data[:8]), set()
    for kind, payload, raw in sections(data):
        if kind != 10:
            result.extend(raw)
            continue
        count, position = integer(payload, 0)
        if not count or position >= len(payload) or payload[position] != 0:
            result.extend(raw)
            continue
        length, first = integer(payload, position+1)
        if not payload[first:first+length].startswith(b'unbundled-module'):
            result.extend(raw)
            continue
        if count > 64: raise ValueError('dotnet-internal-io-unbundle-import-count')
        for _ in range(count):
            if position >= len(payload) or payload[position] != 0:
                raise ValueError('dotnet-internal-io-unbundle-import-name')
            length, position = integer(payload, position+1)
            end = position+length
            if end > len(payload): raise ValueError('dotnet-internal-io-unbundle-import-name')
            name = payload[position:end].decode('utf-8')
            position = end
            if name not in modules or name in consumed or payload[position:position+2] != b'\0\x11':
                raise ValueError('dotnet-internal-io-unbundle-import-type')
            _index, position = integer(payload, position+2)
            body = modules[name]
            result.extend(b'\x01' + encoded_integer(len(body)) + body)
            consumed.add(name)
        if position != len(payload): raise ValueError('dotnet-internal-io-unbundle-import-trailing-bytes')
    if consumed != set(modules): raise ValueError('dotnet-internal-io-unconsumed-core-module')
    if len(result) > MAX_BINARY: raise ValueError('dotnet-internal-io-selected-binary-limit')
    return bytes(result)


def prepare(compiler, raw: Path, adapter: Path, output: Path, original: dict):
    adapter_graph = json.loads(compiler.run('internal-io-adapter-wit', compiler.wasm, 'component', 'wit', adapter, '--json'))
    expected, selected = projection(original, adapter_graph)
    if not selected: return raw, None
    original_bytes = read_file(raw, MAX_BINARY)
    output.mkdir()
    before = core_modules(original_bytes)
    if not before or len(before) > 64: raise ValueError('dotnet-internal-io-core-module-count')
    compiler.run('internal-io-unbundle', compiler.wasm, 'component', 'unbundle', raw,
        '--module-dir', output/'modules', '--threshold', '0', '-o', output/'unbundled.wasm')
    modules = {}
    for path in sorted((output/'modules').iterdir()):
        if not re.fullmatch(r'unbundled-module[0-9]+\.wasm', path.name): raise ValueError('dotnet-internal-io-module-filename')
        modules[path.stem] = read_file(path, MAX_BINARY)
    if sorted(before) != sorted(modules.values()): raise ValueError('dotnet-internal-io-unbundle-changed-core')
    compiler.run('internal-io-print', compiler.wasm, 'print', '--name-unnamed', output/'unbundled.wasm', '-o', output/'unbundled.wat')
    if time.monotonic() >= compiler.commands.deadline: raise ValueError('dotnet-internal-io-original-deadline')
    text = adapted_text(named_export_syntax(read_file(output/'unbundled.wat', MAX_TEXT).decode()), selected)
    (output/'selected.wat').write_text(text, encoding='utf-8')
    (compiler.commands.output/'internal-io-selected.wat').write_text(text, encoding='utf-8', newline='\n')
    component = output/'selected.wasm'
    compiler.run('internal-io-encode', compiler.wasm, 'parse', output/'selected.wat', '-o', output/'unbundled-selected.wasm')
    component.write_bytes(rebundle(read_file(output/'unbundled-selected.wasm', MAX_BINARY), modules))
    compiler.run('internal-io-validate', compiler.wasm, 'validate', '--features', 'all', component)
    after = json.loads(compiler.run('internal-io-selected-wit', compiler.wasm, 'component', 'wit', component, '--json'))
    if expected != after or sorted(before) != sorted(core_modules(read_file(component, MAX_BINARY))):
        raise ValueError('dotnet-internal-io-projection-changed-other-types-or-core')
    if read_file(raw, MAX_BINARY) != original_bytes: raise ValueError('dotnet-internal-io-original-component-changed')
    record = {'profile': PROFILE, 'originalDigest': digest(original_bytes), 'selectedDigest': digest(read_file(component, MAX_BINARY)),
        'functions': selected, 'coreModules': [{'digest': digest(body), 'size': len(body)} for body in before],
        'coreBytesUnchanged': True, 'publicApplicationGraphUnchanged': True, 'signedExecution': 'not-run'}
    write_json(compiler.commands.output/'internal-io-port.json', record)
    return component, record
