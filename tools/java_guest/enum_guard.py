"""Bind checked enum metadata to the actual preprocessed TeaVM C input."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import time

from tools.java_guest import c_failure_context
from tools.java_guest.enum_inventory import IDENT, MAX_SOURCE, TABLE, inventory
from tools.rust_capsule_project import read_file

MAX_INPUT = 16 * 1024 * 1024
MAX_INDEX = 1024 * 1024
MAX_CLASSES = 256
MAX_SLOTS_PER_CLASS = 256
MAX_SLOTS = 4096
MAX_GUARD = 1024 * 1024
_SPACE = frozenset(b'\t\n\r\f ')
_FIRST = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz')
_IDENT = _FIRST | frozenset(b'0123456789')
_DIGITS = frozenset(b'0123456789')
_PUNCT = frozenset(b'!%&()*+,-./:;<=>?[]^{}|~')

OLD_COUNT = b'''inline static int32_t teavm_enumConstantCount(TeaVM_Class* cls) {
    void* values = cls->enumValues;
    if (values == ((void*)0)) {
        return 0;
    }
    return *(intptr_t*) values;
}'''
OLD_VALUE = b'''inline static void* teavm_enumConstant(TeaVM_Class* cls, int32_t index) {
    void* values = cls->enumValues;
    return **((void***) values + (index + 1));
}'''


def need(condition, reason):
    if not condition:
        raise ValueError('java-enum-guard-' + reason)


def _token_view(data: bytes) -> str:
    """Validate the preprocessed byte stream and mask all C string/char tokens.

    Preprocessing must have removed comments and directives; any unsupported
    byte, unclosed literal, escaped physical newline or comment fails closed.
    """
    result = bytearray(data)
    i, size = 0, len(data)
    while i < size:
        value = data[i]
        if value in (34, 39):
            quote = value
            result[i] = 32
            i += 1
            closed = False
            while i < size:
                value = data[i]
                need(value not in (0, 10, 13), 'literal')
                result[i] = 32
                i += 1
                if value == quote:
                    closed = True
                    break
                if value == 92:
                    need(i < size and data[i] not in (0, 10, 13), 'literal-escape')
                    result[i] = 32
                    i += 1
            need(closed, 'literal')
            continue
        if value in _SPACE:
            need(value != 13 or i + 1 < size and data[i + 1] == 10, 'line-ending')
            i += 1
            continue
        if value in _FIRST:
            i += 1
            while i < size and data[i] in _IDENT:
                i += 1
            continue
        if value in _DIGITS or value == 46 and i + 1 < size and data[i + 1] in _DIGITS:
            # C preprocessing-number tokens may contain exponent signs. The
            # final compiler still validates the complete numeric grammar.
            previous = value
            i += 1
            while i < size:
                current = data[i]
                if current in _IDENT or current == 46 or current in (43, 45) and previous in b'eEpP':
                    previous = current
                    i += 1
                else:
                    break
            continue
        need(value in _PUNCT, 'token-byte')
        if value == 47 and i + 1 < size:
            need(data[i + 1] not in (42, 47), 'unprocessed-comment')
        i += 1
    return result.decode('ascii')


def _index(data: bytes, enums: dict, parents: dict) -> None:
    need(len(data) <= MAX_INDEX, 'index-bound')
    lines = data.decode('ascii').splitlines()
    need(bool(lines) and lines[0] == 'lsf-teavm-enum-index-v1', 'index-header')
    fields, model_parents = {}, {}
    for line in lines[1:]:
        row = line.split('\t')
        need(len(row) >= 2 and row[0] not in fields
             and all(len(value) <= 1024 and re.fullmatch(IDENT, value) for value in row), 'index-row')
        fields[row[0]], model_parents[row[0]] = row[2:], row[1]
    need(fields == enums and model_parents == parents, 'index-mismatch')


def _directives(data: bytes, protected: set[str]) -> bytes:
    need(len(data) <= MAX_INPUT, 'source-bound')
    output = bytearray()
    for line in data.splitlines(keepends=True):
        if not line.lstrip().startswith(b'#'):
            output.extend(line)
            continue
        macro = re.fullmatch(rb'[ \t]*#[ \t]*(define|undef)[ \t]+(' + IDENT.encode()
                             + rb')(?=[ \t\r\n(]|$)[^\r\n]*\r?\n?', line)
        marker = re.fullmatch(rb'[ \t]*#[ \t]*[0-9]+[ \t]+"(?:[^"\\\r\n]|\\.)*"'
                              rb'(?:[ \t]+[0-9]+)*[ \t]*\r?\n?', line)
        if macro:
            need(macro.group(2).decode('ascii') not in protected and not line.rstrip().endswith(b'\\'),
                 'protected-macro')
            output.extend(b'\n')
        elif marker:
            # Remove line markers too: the bytes subsequently compiled are
            # precisely this already-preprocessed stream, with no directives.
            output.extend(b'\n')
        else:
            raise ValueError('java-enum-guard-directive')
    return bytes(output)


def _verify_translation_unit(data: bytes, enums: dict, parents: dict, types: dict) -> bytes:
    names = set(enums)
    slots = {field for fields in enums.values() for field in fields}
    protected = names | slots | set(parents.values()) | set(types.values())
    protected.update(name + '_enumConstants' for name in names)
    protected.update(('teavm_enumConstant', 'teavm_enumConstantCount', 'enumValues', 'modifiers',
                      'superclass', 'jl_Enum_Cls', 'TeaVM_Class', 'intptr_t', 'int32_t', 'static', 'void'))
    cleaned = _directives(data, protected)
    body = _token_view(cleaned).replace('\r\n', '\n')
    need(not re.search(r'\b(?:asm|__asm|__asm__|__alias__|alias|weak|__weak__)\b', body), 'linkage-token')

    tables = {}
    for match in TABLE.finditer(body):
        name = match.group(1)
        if name in names:
            need(name not in tables, 'duplicate-table')
            fields = re.findall(r'&(' + IDENT + ')', match.group(4))
            need(int(match.group(2)) == len(fields) + 1 and int(match.group(3)) == len(fields), 'table-size')
            tables[name] = fields
    need(tables == enums, 'preprocessed-tables')

    seen_slots = set()
    for match in re.finditer(r'^[ \t]*void[ \t]*\*[ \t]*(' + IDENT + r')[ \t]*;[ \t]*$', body, re.M):
        name = match.group(1)
        if name in slots:
            need(name not in seen_slots, 'duplicate-slot')
            seen_slots.add(name)
    need(seen_slots == slots, 'preprocessed-slots')

    seen = set()
    for match in re.finditer(r'\b(' + IDENT + r')\s+(' + IDENT + r')\s*=\s*\{', body):
        typename, name = match.group(1), match.group(2)
        if name not in names:
            continue
        need(name not in seen and typename == types[name], 'preprocessed-class')
        seen.add(name)
        begin = match.end() - 1
        depth = 0
        for pos in range(begin, len(body)):
            depth += (body[pos] == '{') - (body[pos] == '}')
            if depth == 0:
                break
        else:
            raise ValueError('java-enum-guard-class-braces')
        value = body[begin:pos + 1]
        parent = re.findall(r'\.superclass\s*=\s*\(\s*TeaVM_Class\s*\*\s*\)\s*&\s*(' + IDENT + r')', value)
        association = re.findall(r'\.enumValues\s*=\s*(' + IDENT + r')', value)
        modifiers = re.findall(r'\.modifiers\s*=\s*(\d+)', value)
        need(parent == [parents[name]] and association == [name + '_enumConstants']
             and len(modifiers) == 1 and int(modifiers[0]) & 65536, 'preprocessed-association')
    need(seen == names, 'missing-class')
    return cleaned


def _guard(enums: dict) -> bytes:
    rows = ['\nstatic __attribute__((noinline,optnone)) int32_t teavm_enumConstantCount(TeaVM_Class* cls) {\n']
    for cls, fields in sorted(enums.items()):
        rows.append(f'  if (cls == (TeaVM_Class*) &{cls}) return {len(fields)};\n')
    rows.append('  __builtin_trap();\n}\n')
    rows.append('static __attribute__((noinline,optnone)) void* teavm_enumConstant(TeaVM_Class* cls, int32_t index) {\n')
    for cls, fields in sorted(enums.items()):
        rows.append(f'  if (cls == (TeaVM_Class*) &{cls}) {{\n')
        for index, field in enumerate(fields):
            rows.append(f'    if (index == {index}) return {field};\n')
        rows.append('    __builtin_trap();\n  }\n')
    rows.append('  __builtin_trap();\n}\n')
    raw = ''.join(rows).encode('ascii')
    need(len(raw) <= MAX_GUARD, 'guard-bound')
    return raw


def seal(data: bytes, generated: Path, compiler_index: bytes, *, source_before: str | None = None) -> tuple[bytes, dict]:
    _, enums, source_bytes, parents, types, source_digest = inventory(generated)
    need(source_before is None or source_before == source_digest, 'source-drift')
    need(len(enums) <= MAX_CLASSES and all(len(fields) <= MAX_SLOTS_PER_CLASS for fields in enums.values())
         and sum(map(len, enums.values())) <= MAX_SLOTS, 'cost-bound')
    _index(compiler_index, enums, parents)
    cleaned = _verify_translation_unit(data, enums, parents, types)
    need(cleaned.count(OLD_COUNT) == 1 and cleaned.count(OLD_VALUE) == 1, 'helper-preimage')
    cleaned = cleaned.replace(OLD_COUNT, b'static int32_t teavm_enumConstantCount(TeaVM_Class* cls);')
    cleaned = cleaned.replace(OLD_VALUE, b'static void* teavm_enumConstant(TeaVM_Class* cls, int32_t index);')
    guard = _guard(enums)
    result = cleaned + guard
    need(len(result) <= MAX_INPUT and source_bytes + len(result) <= MAX_SOURCE, 'sealed-bound')
    return result, {'schemaVersion': 'latent.java.enum-guard.v1',
                    'compilerIndexSha256': hashlib.sha256(compiler_index).hexdigest(),
                    'generatedSourceSha256': source_digest,
                    'preprocessedSha256': hashlib.sha256(data).hexdigest(),
                    'guardSha256': hashlib.sha256(guard).hexdigest(),
                    'sealedSha256': hashlib.sha256(result).hexdigest(),
                    'sealedBytes': len(result), 'classes': len(enums),
                    'slots': sum(map(len, enums.values())),
                    'maximumClassComparisons': len(enums),
                    'maximumSlotComparisons': max(map(len, enums.values()), default=0)}


def _bindings_identity(directory: Path) -> dict:
    names = ('bridge.c', 'probe.c', 'probe.h', 'probe_component_type.o')
    result = {}
    for name in names:
        data = read_file(directory / name, MAX_INPUT)
        result[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return result


def run(compiler, generated: Path, selected: tuple[str, ...], destination: Path, core: Path) -> dict:
    """Preprocess once, validate, then link the exact sealed bytes on stdin."""
    bindings = destination / 'bindings'
    sdk = compiler.sdk
    original = _bindings_identity(bindings)
    index_path = generated.parents[2] / 'compiler-patch/enum-index-v1.tsv'
    index = read_file(index_path, MAX_INDEX)
    source_before = inventory(generated)[-1]
    preprocessed = compiler.capture_preprocessed('-target', 'wasm32-wasip1', '-std=c11', '-O2',
        '-DLSF_JAVA_ACTIVATION_PROFILE=1', '-DLSF_TEAVM_WASM=1', '-DTEAVM_CUSTOM_LOG=1',
        '-mllvm', '-wasm-enable-sjlj', '-mllvm', '-wasm-use-legacy-eh=false',
        '-include', sdk / 'runtime/native.h', '-I', bindings, '-I', sdk / 'runtime', '-iquote', generated,
        '-E', '-dD', generated / 'all.c')
    need(time.monotonic() < compiler.deadline, 'deadline')
    sealed, receipt = seal(preprocessed, generated, index, source_before=source_before)
    need(time.monotonic() < compiler.deadline, 'deadline')
    c_failure_context.run(compiler, generated, selected, '-target', 'wasm32-wasip1', '-std=c11', '-O2',
        '-DLSF_JAVA_ACTIVATION_PROFILE=1', '-DLSF_TEAVM_WASM=1', '-DTEAVM_CUSTOM_LOG=1',
        '-mllvm', '-wasm-enable-sjlj', '-lsetjmp', '-mllvm', '-wasm-use-legacy-eh=false',
        '-mexec-model=reactor', '-Wl,--no-entry', '-Wl,--export-memory', '-Wl,-z,stack-size=65536',
        '-Wl,--max-memory=67108864', '-include', sdk / 'runtime/native.h',
        '-I', bindings, '-I', sdk / 'runtime', '-iquote', generated,
        '-x', 'cpp-output', '-', '-x', 'none', bindings / 'bridge.c', sdk / 'feasibility/platform.c',
        bindings / 'probe.c', bindings / 'probe_component_type.o', '-o', core, input_bytes=sealed)
    need(original == _bindings_identity(bindings), 'bindings-drift')
    need(index == read_file(index_path, MAX_INDEX), 'index-drift')
    receipt['bindings'] = original
    return receipt
