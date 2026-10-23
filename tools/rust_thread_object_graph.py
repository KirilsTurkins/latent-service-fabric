"""Bounded original-object and final-core byte/relocation verification.

Library hashes bind bytes to the compiler receipt supplied by the owning build;
they do not independently establish source trust. The caller must authenticate
that receipt, selected source/Cargo tree and compiler distribution first. This
module never grants runtime enablement: source-catalogue, incoming-call and
indirect receiver/Arc provenance are distinct remaining proof obligations.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from bisect import bisect_left
from dataclasses import dataclass
import hashlib
import json

MAX_LIBRARY_BYTES = 64 * 1024 * 1024
MAX_LIBRARIES_BYTES = 128 * 1024 * 1024
MAX_LIBRARIES = 16
MAX_OBJECTS = 4096
MAX_NODES = 65536
MAX_RELOCATIONS = 2_000_000
MAX_CORE_BYTES = 8 * 1024 * 1024


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


@dataclass(frozen=True)
class Library:
    label: str
    content: bytes
    expected_digest: str

    def checked(self) -> None:
        require(isinstance(self.content, bytes) and len(self.content) <= MAX_LIBRARY_BYTES,
                "rust-object-library-byte-bound")
        require(self.label and len(self.label) <= 256 and "/" not in self.label and "\\" not in self.label,
                "rust-object-library-label")
        require(digest(self.content) == self.expected_digest, "rust-object-library-receipt-mismatch")

class Reader:

    def __init__(self, raw):
        self.raw, self.p = (raw, 0)

    def byte(self):
        if not self.p < len(self.raw):
            raise ValueError('rust-object-bounds-or-encoding')
        value = self.raw[self.p]
        self.p += 1
        return value

    def number(self, signed=False, bits=32):
        value = 0
        for shift in range(0, bits, 7):
            byte = self.byte()
            value |= (byte & 127) << shift
            if byte < 128:
                if signed and byte & 64:
                    value -= 1 << shift + 7
                if not -(1 << bits - 1) <= value < 1 << (bits - 1 if signed else bits):
                    raise ValueError('rust-object-bounds-or-encoding')
                return value
        raise ValueError('finite LEB')

    def blob(self, size):
        if not 0 <= size <= len(self.raw) - self.p:
            raise ValueError('rust-object-bounds-or-encoding')
        value = self.raw[self.p:self.p + size]
        self.p += size
        return value

    def name(self):
        size = self.number()
        if not size <= 16384:
            raise ValueError('rust-object-bounds-or-encoding')
        return self.blob(size).decode()

    def done(self):
        if not self.p == len(self.raw):
            raise ValueError('rust-object-bounds-or-encoding')

def archive(raw):
    if not (raw[:8] == b'!<arch>\n' and len(raw) <= 64 * 1024 * 1024):
        raise ValueError('rust-object-bounds-or-encoding')
    p, names, count = (8, b'', 0)
    while p < len(raw):
        header = raw[p:p + 60]
        if not (len(header) == 60 and header[58:] == b'`\n'):
            raise ValueError('rust-object-bounds-or-encoding')
        size = int(header[48:58])
        body = raw[p + 60:p + 60 + size]
        if not len(body) == size:
            raise ValueError('rust-object-bounds-or-encoding')
        label = header[:16].decode().strip()
        p += 60 + size + size % 2
        if label == '//':
            names = body
        elif label.startswith('/') and label[1:].isdigit():
            label = names[int(label[1:]):].split(b'/\n', 1)[0].decode()
        if label not in {'/', '//'} and label.endswith('/'):
            label = label[:-1]
        if label.endswith('.o'):
            count += 1
            if not count <= 4096:
                raise ValueError('rust-object-bounds-or-encoding')
            yield (label, body)
    if not p == len(raw):
        raise ValueError('rust-object-bounds-or-encoding')

def object_nodes(raw, label):
    if not raw[:8] == b'\x00asm\x01\x00\x00\x00':
        raise ValueError('rust-object-bounds-or-encoding')
    reader = Reader(raw[8:])
    sections = []
    symbols = []
    imports = defaultdict(list)
    functions = []
    data = []
    relocations = []
    while reader.p < len(reader.raw):
        tag = reader.byte()
        part = reader.blob(reader.number())
        r = Reader(part)
        ordinal = len(sections)
        sections.append((tag, part))
        if tag == 2:
            count = r.number()
            require(count <= MAX_NODES, 'rust-object-import-count-bound')
            for _ in range(count):
                module, name, kind = (r.name(), r.name(), r.byte())
                imports[kind].append((module, name))
                if kind == 0:
                    r.number()
                elif kind in (1, 2):
                    if kind == 1:
                        r.byte()
                    flags = r.number()
                    r.number()
                    if flags & 1:
                        r.number()
                elif kind == 3:
                    r.byte()
                    r.byte()
                elif kind == 4:
                    r.byte()
                    r.number()
                else:
                    raise ValueError(('import kind', kind))
            r.done()
        elif tag == 10:
            count = r.number()
            require(count <= MAX_NODES, 'rust-object-function-count-bound')
            for _ in range(count):
                size = r.number()
                begin = r.p
                body = r.blob(size)
                functions.append({'section': ordinal, 'start': begin, 'end': r.p, 'raw': body})
            r.done()
        elif tag == 11:
            count = r.number()
            require(count <= MAX_NODES, 'rust-object-data-count-bound')
            for _ in range(count):
                flags = r.number()
                if not flags in (0, 1, 2):
                    raise ValueError('rust-object-bounds-or-encoding')
                if flags == 2:
                    r.number()
                if flags != 1:
                    if not r.byte() == 65:
                        raise ValueError('rust-object-bounds-or-encoding')
                    r.number(signed=True)
                    if not r.byte() == 11:
                        raise ValueError('rust-object-bounds-or-encoding')
                size = r.number()
                begin = r.p
                body = r.blob(size)
                data.append({'section': ordinal, 'start': begin, 'end': r.p, 'raw': body})
            r.done()
        elif tag == 0:
            name = r.name()
            if name == 'linking':
                if not r.number() == 2:
                    raise ValueError('rust-object-bounds-or-encoding')
                while r.p < len(part):
                    kind = r.byte()
                    sub = Reader(r.blob(r.number()))
                    if kind != 8:
                        continue
                    count = sub.number()
                    require(count <= MAX_NODES, 'rust-object-symbol-count-bound')
                    for _ in range(count):
                        kind, flags = (sub.byte(), sub.number())
                        row = {'kind': kind, 'flags': flags, 'defined': not bool(flags & 16)}
                        if kind in (0, 2, 4, 5):
                            row['index'] = sub.number()
                            row['name'] = sub.name() if row['defined'] or flags & 64 else imports[{0: 0, 2: 3, 4: 4, 5: 1}[kind]][row['index']][1]
                            if not row['defined']:
                                row['import'] = imports[{0: 0, 2: 3, 4: 4, 5: 1}[kind]][row['index']]
                        elif kind == 1:
                            row['name'] = sub.name()
                            if row['defined']:
                                row['segment'], row['offset'], row['size'] = (sub.number(), sub.number(), sub.number())
                        elif kind == 3:
                            row['index'] = sub.number()
                        else:
                            raise ValueError(('symbol kind', kind))
                        symbols.append(row)
                    sub.done()
            elif name.startswith('reloc.'):
                target = r.number()
                count = r.number()
                if not count <= 2000000:
                    raise ValueError('rust-object-bounds-or-encoding')
                for _ in range(count):
                    kind, offset, index = (r.byte(), r.number(), r.number())
                    if not 0 <= kind <= 26:
                        raise ValueError('rust-object-bounds-or-encoding')
                    addend = r.number(True, 64 if kind in {14, 15, 16, 17, 22, 25} else 32) if kind in {3, 4, 5, 8, 9, 11, 14, 15, 16, 17, 21, 22, 23, 25} else 0
                    extent = 10 if kind in {14, 15, 17, 18, 24, 25} else 8 if kind in {16, 19, 22} else 4 if kind in {2, 5, 8, 9, 13, 23, 26} else 5
                    relocations.append({'section': target, 'offset': offset, 'index': index, 'kind': kind, 'addend': addend, 'extent': extent})
                r.done()
    nodes = []
    by_section = defaultdict(list)
    for relocation in relocations:
        by_section[relocation['section']].append(relocation)
    indexed = {}
    for section, rows in by_section.items():
        rows.sort(key=lambda row: row['offset'])
        indexed[section] = ([row['offset'] for row in rows], rows)
    attached = 0
    for index, symbol in enumerate(symbols):
        if not symbol['defined'] or symbol['kind'] not in (0, 1):
            continue
        if symbol['kind'] == 0:
            require(len(imports[0]) <= symbol['index'] < len(imports[0]) + len(functions),
                    'rust-object-defined-function-index')
            region = functions[symbol['index'] - len(imports[0])]
        else:
            require(0 <= symbol['segment'] < len(data), 'rust-object-defined-data-segment')
            segment = data[symbol['segment']]
            begin = segment['start'] + symbol['offset']
            end = begin + symbol['size']
            if not end <= segment['end']:
                raise ValueError('rust-object-bounds-or-encoding')
            region = {'section': segment['section'], 'start': begin, 'end': end, 'raw': segment['raw'][symbol['offset']:symbol['offset'] + symbol['size']]}
        relevant = []
        offsets, rows = indexed.get(region['section'], ([], []))
        for relocation in rows[bisect_left(offsets, region['start']):bisect_left(offsets, region['end'])]:
            if relocation['section'] == region['section']:
                if not relocation['offset'] + relocation['extent'] <= region['end']:
                    raise ValueError('rust-object-bounds-or-encoding')
                item = dict(relocation)
                item['offset'] -= region['start']
                if item['kind'] == 6:
                    item['target'] = {'kind': 'type', 'index': item['index']}
                else:
                    if not item['index'] < len(symbols):
                        raise ValueError('rust-object-bounds-or-encoding')
                    item['target'] = symbols[item['index']]
                attached += 1
                require(attached <= MAX_RELOCATIONS, 'rust-object-attached-relocation-bound')
                relevant.append(item)
        nodes.append({'object': label, 'symbolIndex': index, **symbol, 'bodySection': region['section'], 'bodyStart': region['start'], 'bodyEnd': region['end'], 'bodyBytes': len(region['raw']), 'bodyDigest': hashlib.sha256(region['raw']).hexdigest(), 'relocations': relevant})
    return (nodes, len(relocations))

def sections(raw):
    if not raw[:8] == b'\x00asm\x01\x00\x00\x00':
        raise ValueError('rust-object-bounds-or-encoding')
    reader = Reader(raw[8:])
    parts = []
    while reader.p < len(reader.raw):
        tag = reader.byte()
        parts.append((tag, reader.blob(reader.number())))
    if not len(parts) <= 512:
        raise ValueError('rust-object-bounds-or-encoding')
    return parts

def signature(reader):
    if not reader.byte() == 96:
        raise ValueError('rust-object-bounds-or-encoding')

    def values(maximum):
        count = reader.number()
        if not count <= maximum:
            raise ValueError('rust-object-bounds-or-encoding')
        result = tuple((reader.byte() for _ in range(count)))
        if not all((value in {127, 126, 125, 124, 123} for value in result)):
            raise ValueError('rust-object-bounds-or-encoding')
        return result
    return (values(64), values(16))

def code(raw):
    types, function_types, imports, bodies = ([], [], [], [])
    for tag, part in sections(raw):
        reader = Reader(part)
        if tag == 1:
            count = reader.number()
            if not count <= 65536:
                raise ValueError('rust-object-bounds-or-encoding')
            types = [signature(reader) for _ in range(count)]
            reader.done()
        elif tag == 2:
            count = reader.number()
            if not count <= 65536:
                raise ValueError('rust-object-bounds-or-encoding')
            for _ in range(count):
                module, name, kind = (reader.name(), reader.name(), reader.byte())
                if kind == 0:
                    function_types.append(reader.number())
                    imports.append((module, name))
                elif kind in {1, 2}:
                    if kind == 1:
                        reader.byte()
                    flags = reader.number()
                    reader.number()
                    if flags & 1:
                        reader.number()
                elif kind == 3:
                    reader.byte()
                    reader.byte()
                else:
                    raise ValueError('non-numeric original import kind')
            reader.done()
        elif tag == 3:
            count = reader.number()
            if not count <= 65536:
                raise ValueError('rust-object-bounds-or-encoding')
            function_types.extend((reader.number() for _ in range(count)))
            reader.done()
        elif tag == 10:
            count = reader.number()
            if not count <= 65536:
                raise ValueError('rust-object-bounds-or-encoding')
            bodies = [reader.blob(reader.number()) for _ in range(count)]
            reader.done()
    if not len(function_types) == len(imports) + len(bodies):
        raise ValueError('rust-object-bounds-or-encoding')
    require(all(0 <= index < len(types) for index in function_types),
            'rust-object-function-type-index')
    signatures = [types[index] for index in function_types]
    return (signatures, imports, bodies)

def match_body(original, actual, relocations, expected_signature, actual_signature):
    """Require every nonrelocation byte plus the complete signature to match.

    Relocation values are exposed for subsequent referent closure, not ignored
    as arbitrary bytes in an accepted graph. Overlapping/misencoded spans fail.
    """
    if len(original) != len(actual) or expected_signature != actual_signature:
        raise ValueError('object-final-function-body-or-signature')
    values, previous = ([], 0)
    for row in sorted(relocations, key=lambda row: row['offset']):
        begin, end = (row['offset'], row['offset'] + row['extent'])
        if not previous <= begin < end <= len(original) or original[previous:begin] != actual[previous:begin]:
            raise ValueError('object-final-function-nonrelocated-bytes')
        kind = row['kind']
        reader = Reader(actual[begin:end])
        if kind in {0, 3, 6, 7, 10, 20}:
            value = reader.number()
            reader.done()
        elif kind in {1, 4, 11, 12, 21}:
            value = reader.number(signed=True)
            reader.done()
        elif kind in {2, 5, 8, 9, 13, 23, 26}:
            if not row['extent'] == 4:
                raise ValueError('rust-object-bounds-or-encoding')
            value = int.from_bytes(actual[begin:end], 'little')
        else:
            raise ValueError('object-final-unqualified-relocation-kind')
        values.append((row, value))
        previous = end
    if original[previous:] != actual[previous:]:
        raise ValueError('object-final-function-nonrelocated-bytes')
    return values

def types(raw):
    for tag, part in sections(raw):
        if tag == 1:
            reader = Reader(part)
            result = [signature(reader) for _ in range(reader.number())]
            reader.done()
            return result
    return []

def memory_table(raw):
    memory, table, exports = (None, {}, {})
    for tag, part in sections(raw):
        reader = Reader(part)
        if tag == 5:
            if not reader.number() == 1:
                raise ValueError('rust-object-bounds-or-encoding')
            flags, minimum = (reader.number(), reader.number())
            if not (flags in (0, 1) and minimum <= 512):
                raise ValueError('rust-object-bounds-or-encoding')
            if flags:
                reader.number()
            memory = bytearray(minimum * 65536)
            reader.done()
        elif tag == 7:
            for _ in range(reader.number()):
                name, kind, index = (reader.name(), reader.byte(), reader.number())
                exports[name] = (kind, index)
        elif tag == 9:
            for _ in range(reader.number()):
                flags = reader.number()
                if not flags in (0, 2):
                    raise ValueError('rust-object-bounds-or-encoding')
                if flags == 2:
                    if not reader.number() == 0:
                        raise ValueError('rust-object-bounds-or-encoding')
                if not reader.byte() == 65:
                    raise ValueError('rust-object-bounds-or-encoding')
                offset = reader.number(True)
                if not (offset >= 0 and reader.byte() == 11):
                    raise ValueError('rust-object-bounds-or-encoding')
                if flags == 2:
                    if not reader.byte() == 0:
                        raise ValueError('rust-object-bounds-or-encoding')
                for i in range(reader.number()):
                    if not offset + i not in table:
                        raise ValueError('rust-object-bounds-or-encoding')
                    table[offset + i] = reader.number()
            reader.done()
        elif tag == 11:
            for _ in range(reader.number()):
                flags = reader.number()
                if not flags in (0, 1, 2):
                    raise ValueError('rust-object-bounds-or-encoding')
                if flags == 2:
                    if not reader.number() == 0:
                        raise ValueError('rust-object-bounds-or-encoding')
                offset = None
                if flags != 1:
                    if not reader.byte() == 65:
                        raise ValueError('rust-object-bounds-or-encoding')
                    offset = reader.number(True)
                    if not (offset >= 0 and reader.byte() == 11):
                        raise ValueError('rust-object-bounds-or-encoding')
                data = reader.blob(reader.number())
                if offset is not None:
                    if not (memory is not None and offset + len(data) <= len(memory)):
                        raise ValueError('rust-object-bounds-or-encoding')
                    memory[offset:offset + len(data)] = data
            reader.done()
    return (memory, table, exports)

def instructions(body):
    r = Reader(body)
    groups = r.number()
    require(groups <= MAX_NODES, 'rust-object-local-group-bound')
    locals_count = 0
    for _ in range(groups):
        locals_count += r.number()
        require(locals_count <= MAX_NODES and r.byte() in (127, 126, 125, 124, 123),
                'rust-object-local-bound-or-type')
    count = 0
    while r.p < len(body):
        count += 1
        require(count <= MAX_RELOCATIONS, 'rust-object-operator-bound')
        start = r.p
        op = r.byte()
        args = []
        if op in (2, 3, 4):
            args = [r.number(True, 33)]
        elif op in (12, 13, 16, 18, 32, 33, 34, 35, 36, 37, 38, 63, 64, 210):
            args = [r.number()]
        elif op == 14:
            targets = r.number()
            require(targets < MAX_NODES, 'rust-object-branch-table-bound')
            args = [r.number() for _ in range(targets + 1)]
        elif op in (17, 19):
            args = [r.number(), r.number()]
        elif op == 28:
            count_types = r.number()
            require(count_types <= 16, 'rust-object-select-type-bound')
            args = [r.byte() for _ in range(count_types)]
        elif 40 <= op <= 62:
            args = [r.number(), r.number()]
        elif op == 65:
            args = [r.number(True)]
        elif op == 66:
            args = [r.number(True, 64)]
        elif op == 67:
            r.blob(4)
        elif op == 68:
            r.blob(8)
        elif op == 208:
            args = [r.number(True, 33)]
        elif op == 252:
            sub = r.number()
            args = [sub]
            if 0 <= sub <= 7:
                pass
            elif sub in (8, 10, 12, 14):
                args += [r.number(), r.number()]
            elif sub in (9, 11, 13, 15, 16, 17):
                args += [r.number()]
            else:
                raise ValueError(('unsupported-fc', sub, start))
        elif op in (0, 1, 5, 11, 15, 26, 27, 209) or 69 <= op <= 196:
            pass
        else:
            raise ValueError(('unsupported-opcode', op, start))
        yield (start, op, args)
    r.done()


def bounded_instructions(body, remaining=MAX_RELOCATIONS):
    """Bound retained operator rows before allocation, including callers' total."""
    require(0 <= remaining <= MAX_RELOCATIONS, 'rust-object-operator-bound')
    rows = []
    for row in instructions(body):
        require(len(rows) < remaining, 'rust-object-operator-bound')
        rows.append(row)
    return rows




def original_linker_layout(core: bytes, exports: dict, memory_bytes: int) -> dict:
    """Use original stack globals, active data and physical initial memory."""
    globals_ = []
    active_high = 0
    for tag, part in sections(core):
        reader = Reader(part)
        if tag == 6:
            for _ in range(reader.number()):
                value_type, mutable = reader.byte(), reader.byte()
                require(value_type == 0x7f and mutable in (0, 1) and reader.byte() == 0x41,
                        'rust-object-layout-i32-constant-global')
                value = reader.number(True)
                require(value >= 0 and reader.byte() == 0x0b,
                        'rust-object-layout-global-initializer')
                globals_.append((value, mutable))
            reader.done()
        elif tag == 11:
            for _ in range(reader.number()):
                flags = reader.number()
                require(flags in (0, 1, 2), 'rust-object-layout-data-mode')
                if flags == 2:
                    require(reader.number() == 0, 'rust-object-layout-data-memory')
                offset = None
                if flags != 1:
                    require(reader.byte() == 0x41, 'rust-object-layout-active-offset')
                    offset = reader.number(True)
                    require(offset >= 0 and reader.byte() == 0x0b,
                            'rust-object-layout-active-offset')
                size = reader.number()
                reader.blob(size)
                if offset is not None:
                    active_high = max(active_high, offset + size)
            reader.done()
    require(exports.get('__stack_pointer', (-1, -1))[0] == 3 and
            exports.get('__stack_low', (-1, -1))[0] == 3,
            'rust-object-layout-original-stack-exports')
    require(all(0 <= exports[name][1] < len(globals_) for name in ('__stack_pointer', '__stack_low')),
            'rust-object-layout-original-global-index')
    high, mutable = globals_[exports['__stack_pointer'][1]]
    low, low_mutable = globals_[exports['__stack_low'][1]]
    require(mutable == 1 and low_mutable == 0 and
            0 < low < high <= memory_bytes <= 32 * 1024 * 1024 and
            low % 16 == high % 16 == 0 and active_high <= low,
            'rust-object-layout-original-stack-data-or-memory')
    return {'stackLow': low, 'stackHigh': high, 'activeDataHigh': active_high,
            'initialMemoryBytes': memory_bytes}


def compiler_delegator(body: bytes, expected_signature, actual_signature, arity: int):
    """Exact compiler-generated forwarding body, never an arbitrary call mask."""
    require(expected_signature == actual_signature and body[:1] == b'\0',
            'rust-object-compiler-delegator-signature-or-locals')
    ops = [(op, args) for _, op, args in instructions(body)]
    if arity == -1:
        require(expected_signature == ((), ()) and ops == [(15, []), (11, [])],
                'rust-object-compiler-no-alloc-shim-body')
        return None
    require(len(ops) == arity + 3 and ops[:arity] == [(32, [i]) for i in range(arity)]
            and ops[arity][0] == 16 and ops[-2:] == [(15, []), (11, [])],
            'rust-object-compiler-delegator-body')
    return ops[arity][1][0]


COMPILER_SHIMS = {
    '12___rust_alloc': ('11___rdl_alloc', 2),
    '14___rust_dealloc': ('13___rdl_dealloc', 3),
    '14___rust_realloc': ('13___rdl_realloc', 4),
    '19___rust_alloc_zeroed': ('18___rdl_alloc_zeroed', 2),
    '35___rust_no_alloc_shim_is_unstable_v2': (None, -1),
}


def observe_objects(core: bytes, libraries: tuple[Library, ...],
                    root_exports: tuple[str, ...],
                    additional_roots: tuple[tuple[str, str], ...] = ()) -> dict:
    """Verify original byte/reference closure, retaining every unresolved edge.

    Root names only locate already source-authenticated object definitions.
    Exports/candidate names never establish body authority. Additional roots
    require a unique complete-body/signature candidate; every relocated value
    then has to identify the corresponding original definition/import/boundary.
    A returned observation is deliberately insufficient to enable execution.
    """
    require(isinstance(core, bytes) and len(core) <= MAX_CORE_BYTES,
            'rust-object-core-byte-bound')
    require(0 < len(libraries) <= MAX_LIBRARIES and
            sum(len(item.content) for item in libraries) <= MAX_LIBRARIES_BYTES,
            'rust-object-libraries-byte-bound')
    require(0 < len(root_exports) <= 32 and len(set(root_exports)) == len(root_exports),
            'rust-object-root-bound')
    require(len(additional_roots) <= 32 and len(set(additional_roots)) == len(additional_roots),
            'rust-object-additional-root-bound')
    require(len({item.label for item in libraries}) == len(libraries),
            'rust-object-duplicate-library')
    for item in libraries:
        item.checked()
    try:
        return _observe(core, libraries, root_exports, additional_roots)
    except (IndexError, KeyError, UnicodeError, OverflowError) as error:
        raise ValueError('rust-object-malformed-reference') from error


def _observe(core, libraries, root_exports, additional_roots):
    actual_sigs, actual_imports, actual_bodies = code(core)
    actual_types = types(core)
    memory, table, exports = memory_table(core)
    objects, nodes = {}, []
    local, global_nodes = defaultdict(list), defaultdict(list)
    relocations = 0
    attached_relocations = 0
    defined_bytes = 0

    def locator(row):
        if row['kind'] == 0:
            return (0, row['index'])
        return (1, row['segment'], row['offset'], row['size'])

    for library in libraries:
        for label, original in archive(library.content):
            require(len(label) <= 1024, 'rust-object-member-label-bound')
            obj = library.label + '/' + label
            require(obj not in objects and len(objects) < MAX_OBJECTS,
                    'rust-object-duplicate-or-count-bound')
            parsed, count = object_nodes(original, obj)
            relocations += count
            attached_relocations += sum(len(row['relocations']) for row in parsed)
            defined_bytes += sum(row['bodyBytes'] for row in parsed)
            require(attached_relocations <= MAX_RELOCATIONS and defined_bytes <= MAX_LIBRARIES_BYTES,
                    'rust-object-definition-or-attached-reference-bound')
            require(relocations <= MAX_RELOCATIONS and len(nodes) + len(parsed) <= MAX_NODES,
                    'rust-object-node-or-relocation-bound')
            objects[obj] = {'raw': original, 'sections': sections(original),
                            'code': code(original), 'types': types(original)}
            for node in parsed:
                nodes.append(node)
                local[(obj, locator(node))].append(node)
                if not node['flags'] & 2:
                    global_nodes[(node['kind'], node.get('name'))].append(node)

    def resolve(node, target):
        if target['defined']:
            aliases = local[(node['object'], locator(target))]
            # Multiple linking symbols may designate one exact definition.
            identities = {(r['bodySection'], r['bodyStart'], r['bodyEnd'],
                           r['bodyDigest'], json.dumps(r['relocations'], sort_keys=True))
                          for r in aliases}
            require(len(identities) <= 1, 'rust-object-inconsistent-local-alias')
            return aliases[:1]
        return global_nodes[(target['kind'], target.get('name'))]

    queue = deque()
    for name in root_exports:
        candidates = global_nodes[(0, name)]
        require(len(candidates) == 1 and exports.get(name, (-1, -1))[0] == 0,
                'rust-object-root-definition-or-export')
        queue.append((candidates[0], exports[name][1]))
    for library, name in additional_roots:
        candidates = [node for node in nodes if node['kind'] == 0 and
                      node['object'].startswith(library + '/') and node['name'] == name]
        require(len(candidates) == 1, 'rust-object-additional-root-definition')
        node = candidates[0]
        obj = objects[node['object']]
        original = obj['sections'][node['bodySection']][1][node['bodyStart']:node['bodyEnd']]
        signature = obj['code'][0][node['index']]
        matching = []
        for index, body in enumerate(actual_bodies, len(actual_imports)):
            if len(body) != len(original) or actual_sigs[index] != signature:
                continue
            try:
                match_body(original, body, node['relocations'], signature, actual_sigs[index])
            except ValueError:
                continue
            matching.append(index)
        require(len(matching) == 1, 'rust-object-additional-root-ambiguous')
        queue.append((node, matching[0]))

    seen, bindings, verified = set(), {}, set()
    failures, unresolved, imports = [], [], set()
    edges, matched = Counter(), Counter()
    delegators = {}
    linker_layout = None
    heap_bindings = {}
    while queue:
        require(len(queue) <= MAX_RELOCATIONS, 'rust-object-worklist-bound')
        node, actual = queue.popleft()
        key = (node['object'], node['symbolIndex'])
        if key in bindings and bindings[key] != actual:
            failures.append({'kind': 'inconsistent-original-object-binding',
                             'object': node['object'], 'symbol': node['symbolIndex'],
                             'actual': actual, 'prior': bindings[key]})
            continue
        bindings[key] = actual
        if key in seen:
            continue
        seen.add(key)
        obj = objects[node['object']]
        original = obj['sections'][node['bodySection']][1][node['bodyStart']:node['bodyEnd']]
        require(hashlib.sha256(original).hexdigest() == node['bodyDigest'],
                'rust-object-original-span-digest')
        try:
            if node['kind'] == 0:
                require(len(actual_imports) <= actual < len(actual_sigs),
                        'rust-object-final-function-index')
                refs = match_body(original, actual_bodies[actual - len(actual_imports)],
                                  node['relocations'], obj['code'][0][node['index']],
                                  actual_sigs[actual])
            else:
                require(memory is not None and 0 <= actual <= len(memory) - len(original),
                        'rust-object-final-data-span')
                refs = match_body(original, bytes(memory[actual:actual + len(original)]),
                                  node['relocations'], (), ())
        except ValueError as error:
            failures.append({'kind': 'full-body-or-signature', 'object': node['object'],
                             'symbol': node['symbolIndex'], 'actual': actual,
                             'reason': str(error)})
            continue
        verified.add(key)
        matched[node['kind']] += 1
        for row, value in refs:
            kind, target = row['kind'], row['target']
            edges[kind] += 1
            if kind == 6:
                if obj['types'][row['index']] != actual_types[value]:
                    failures.append({'kind': 'type-relocation', 'object': node['object'],
                                     'symbol': node['symbolIndex'], 'actual': value})
                continue
            if kind in (7, 20):
                expected = (3, value) if kind == 7 else (1, value)
                if exports.get(target.get('name')) != expected:
                    unresolved.append({'kind': 'global-or-table-binding', 'object': node['object'],
                                       'symbol': node['symbolIndex'], 'target': target, 'actual': value})
                continue
            if kind not in (0, 1, 2, 3, 4, 5):
                unresolved.append({'kind': 'relocation-kind', 'object': node['object'],
                                   'symbol': node['symbolIndex'], 'relocation': row, 'actual': value})
                continue
            if kind in (1, 2):
                if value not in table:
                    failures.append({'kind': 'table-referent-not-initialized',
                                     'object': node['object'], 'symbol': node['symbolIndex'],
                                     'actual': value})
                    continue
                destination = table[value]
            elif kind in (3, 4, 5):
                destination = (value - row['addend']) & 0xffffffff
            else:
                destination = value
            candidates = resolve(node, target)
            if not candidates and target['kind'] == 0 and destination < len(actual_imports):
                if (tuple(target.get('import', ())) != actual_imports[destination] or
                        obj['code'][0][target['index']] != actual_sigs[destination]):
                    failures.append({'kind': 'import-attribution', 'object': node['object'],
                                     'symbol': node['symbolIndex'], 'actual': destination})
                else:
                    imports.add(actual_imports[destination])
                continue
            if not candidates and target['kind'] == 1 and target.get('name') in {'__heap_base', '__heap_end'}:
                try:
                    require(kind in (3, 4, 5) and memory is not None,
                            'rust-object-linker-heap-relocation-kind')
                    if linker_layout is None:
                        linker_layout = original_linker_layout(core, exports, len(memory))
                    name = target['name']
                    expected = linker_layout['stackHigh' if name == '__heap_base' else 'initialMemoryBytes']
                    require(destination == expected, 'rust-object-linker-heap-layout-binding')
                    heap_bindings[name] = destination
                except ValueError as error:
                    failures.append({'kind': 'linker-heap-layout', 'object': node['object'],
                                     'symbol': node['symbolIndex'], 'actual': destination,
                                     'reason': str(error)})
                continue
            if not candidates and target['kind'] == 0:
                shim = next(((suffix, spec) for suffix, spec in COMPILER_SHIMS.items()
                             if target.get('name', '').endswith('___rustc' + suffix)), None)
                if shim is not None:
                    suffix, (delegate, arity) = shim
                    expected = obj['code'][0][target['index']]
                    try:
                        require(len(actual_imports) <= destination < len(actual_sigs),
                                'rust-object-compiler-delegator-index')
                        callee = compiler_delegator(actual_bodies[destination - len(actual_imports)],
                                                   expected, actual_sigs[destination], arity)
                        if delegate is None:
                            require(callee is None, 'rust-object-compiler-no-alloc-shim-callee')
                        else:
                            name = target['name'][:-len(suffix)] + delegate
                            original_callee = global_nodes[(0, name)]
                            require(len(original_callee) == 1,
                                    'rust-object-compiler-delegator-original-definition')
                            queue.append((original_callee[0], callee))
                        binding = (callee, target['name'])
                        require(destination not in delegators or delegators[destination] == binding,
                                'rust-object-compiler-delegator-binding')
                        delegators[destination] = binding
                    except ValueError as error:
                        failures.append({'kind': 'compiler-delegator', 'object': node['object'],
                                         'symbol': node['symbolIndex'], 'actual': destination,
                                         'reason': str(error)})
                    continue
            if len(candidates) != 1:
                unresolved.append({'kind': 'original-referent-count', 'object': node['object'],
                                   'symbol': node['symbolIndex'], 'target': target,
                                   'actual': destination, 'candidates': len(candidates),
                                   'relocationKind': kind})
            else:
                queue.append((candidates[0], destination))
        require(len(failures) + len(unresolved) <= MAX_NODES, 'rust-object-diagnostic-bound')

    node_map = {(node['object'], node['symbolIndex']): node for node in nodes}
    matched_functions = {actual for key, actual in bindings.items() if key in verified and node_map[key]['kind'] == 0}
    incoming, indirect, table_mutations, decode_errors = [], [], [], []
    private = {exports[name][1] for name in root_exports}
    operator_count = 0
    for index, body in enumerate(actual_bodies, len(actual_imports)):
        try:
            for offset, op, arguments in instructions(body):
                operator_count += 1
                require(operator_count <= MAX_RELOCATIONS, 'rust-object-operator-bound')
                record = {'caller': index, 'offset': offset, 'operation': op,
                          'arguments': arguments, 'callerBodyMatched': index in matched_functions}
                if op in (16, 18, 210) and arguments[0] in private:
                    incoming.append(record)
                if op in (17, 19):
                    indirect.append(record)
                if op == 38 or op == 252 and arguments[0] in (12, 14, 15, 17):
                    table_mutations.append(record)
        except ValueError as error:
            decode_errors.append({'function': index, 'reason': str(error)})
    return {
        'schemaVersion': 'latent.rust.original-object-observation.v1',
        'coreDigest': digest(core),
        'libraries': [{'label': item.label, 'digest': item.expected_digest,
                       'bytes': len(item.content)} for item in libraries],
        'originalObjects': len(objects), 'originalNodes': len(nodes),
        'matchedFunctionDefinitions': matched[0], 'matchedDataDefinitions': matched[1],
        'relocationEdges': dict(edges), 'matchedDeclaredImports': sorted(imports),
        'failures': failures, 'unresolvedReferents': unresolved,
        'matchedBindings': [{'object': obj, 'symbolIndex': symbol, 'actual': actual,
                             'originalSymbol': node_map[(obj, symbol)]['name'],
                             'kind': node_map[(obj, symbol)]['kind'],
                             'sourceBodyDigest': node_map[(obj, symbol)]['bodyDigest'],
                             'sourceBytes': node_map[(obj, symbol)]['bodyBytes'],
                             'bodyMatched': (obj, symbol) in verified}
                            for (obj, symbol), actual in bindings.items()],
        'originalLinkerLayout': linker_layout, 'linkerHeapBindings': heap_bindings,
        'compilerDelegators': [{'function': index, 'delegate': row[0], 'originalSymbol': row[1]}
                               for index, row in sorted(delegators.items())],
        'incomingPrivateReferences': incoming, 'indirectCalls': indirect,
        'tableMutations': table_mutations, 'instructionDecodeFailures': decode_errors,
        'trustedSourceCatalogueAuthenticated': False,
        'allIncomingUsesChecked': False, 'indirectReceiverProvenanceChecked': False,
        'privateExecutorGraphAuthenticated': False, 'actualGuestExecuted': False,
    }
