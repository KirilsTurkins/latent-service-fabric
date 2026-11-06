"""Bounded inventory of the exact generated TeaVM C translation unit."""
import hashlib
from pathlib import Path
import re
from tools.rust_capsule_project import read_file

MAX_ENTRIES = 65536
MAX_FILES = 16384
MAX_SOURCE = 256 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
TABLE = re.compile(r"^static void\* (" + IDENT + r")_enumConstants\[([0-9]{1,10})\] = \{ \(void\*\) \(intptr_t\) ([0-9]{1,10})((?:, &" + IDENT + r")*) \};$", re.M)
INCLUDE = re.compile(r'^#include "([A-Za-z0-9_./@-]+\.c)"$')
DEFINES = ('#define _XOPEN_SOURCE', '#define __USE_XOPEN', '#define _GNU_SOURCE')


def require(value, why):
    if not value:
        raise ValueError('enum-guard-' + why)


def validate_enum_parent_chains(enum_parents):
    for cls in enum_parents:
        visited = set()
        cursor = cls
        while cursor != 'jl_Enum_Cls':
            require(cursor in enum_parents and cursor not in visited, 'enum-parent-chain')
            visited.add(cursor)
            require(len(visited) <= len(enum_parents), 'enum-parent-chain-bound')
            cursor = enum_parents[cursor]


def inventory(generated):
    root = Path(generated)
    require(root.is_dir() and not root.is_symlink() and not root.is_junction(), 'root')
    files, headers, used, entries = {}, {}, 0, 0
    manifest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        entries += 1
        require(entries <= MAX_ENTRIES and not path.is_symlink() and not path.is_junction(), 'entry-bound')
        if path.suffix not in ('.c', '.h'):
            continue
        require(path.is_file() and path.stat().st_size <= MAX_FILE, 'file-bound')
        raw = read_file(path, MAX_FILE)
        relative = path.relative_to(root).as_posix()
        encoded_name = relative.encode('utf8')
        manifest.update(len(encoded_name).to_bytes(4, 'big'))
        manifest.update(encoded_name)
        manifest.update(len(raw).to_bytes(8, 'big'))
        manifest.update(hashlib.sha256(raw).digest())
        used += len(raw)
        require(len(files) + len(headers) < MAX_FILES and used <= MAX_SOURCE, 'total-bound')
        target = files if path.suffix == '.c' else headers
        target[relative] = raw
    require('all.c' in files, 'all-missing')
    all_raw = files.pop('all.c')
    lines = all_raw.decode('utf8').splitlines()
    require(lines[:3] == list(DEFINES), 'all-prefix')
    includes = []
    for line in lines[3:]:
        if not line:
            continue
        match = INCLUDE.fullmatch(line)
        require(match is not None, 'all-directive')
        name = match[1]
        require(all(part not in ('', '.', '..') for part in name.split('/')), 'include-path')
        includes.append(name)
    require(len(includes) == len(set(includes)) and set(includes) == set(files), 'include-inventory')
    enums, enum_parents, enum_types, slots = {}, {}, {}, set()
    for name in includes:
        text = files[name].decode('utf8').replace('\r\n', '\n')
        require('\r' not in text, 'enum-line-endings')
        if '_enumConstants' not in text:
            continue
        require('/*' not in text and '//' not in text and (chr(92) + chr(10)) not in text, 'enum-lexical-form')
        require(all(not line.startswith('#') or line.startswith('#include "')
                    for line in text.splitlines()), 'enum-directive')
        found = list(TABLE.finditer(text))
        require(len(found) == 1 and text.count('_enumConstants') == 2, 'table-shape')
        match = found[0]
        cls, size, count = match[1], int(match[2]), int(match[3])
        fields = re.findall(r'&(' + IDENT + ')', match[4])
        require(size == count + 1 and len(fields) == count and
                len(set(fields)) == count and cls not in enums and
                not slots.intersection(fields), 'table-count-or-identity')
        opening = re.search(r'^alignas\(8\) (' + IDENT + ') ' + re.escape(cls) + r' = \{\n', text, re.M)
        require(opening is not None, 'class-declaration')
        end = text.find('\n};', opening.end())
        require(end >= 0, 'class-initializer')
        body = text[opening.end():end]
        parents = re.findall(r'\.superclass = \(TeaVM_Class\*\) &(' + IDENT + r')', body)
        modifiers = re.findall(r'\.modifiers = ([0-9]{1,10})', body)
        require(len(parents) == 1 and len(modifiers) == 1 and
                int(modifiers[0]) & 65536 and
                body.count('.enumValues = ' + cls + '_enumConstants') == 1,
                'enum-class-association')
        for field in fields:
            require(len(re.findall(r'^void\* ' + re.escape(field) + r';$', text, re.M)) == 1,
                    'enum-slot-declaration')
        enums[cls] = fields
        enum_parents[cls] = parents[0]
        enum_types[cls] = opening.group(1)
        slots.update(fields)
    # Constant-specific subclasses are also emitted as enum classes but have
    # their enclosing enum as their superclass. Require every chain to finish
    # at the pinned Enum object, without cycles or a missing intermediate.
    validate_enum_parent_chains(enum_parents)
    return all_raw, enums, used, enum_parents, enum_types, manifest.hexdigest()
