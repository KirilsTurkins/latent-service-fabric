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
# Reuse disjoint TeaVM exception descriptors before sealing generated input.
# Retain the original 64 KiB stack, below static data so downward overflow
# cannot overwrite activation-owner registries.
ACTIVATION_C_STACK_BYTES = 64 * 1024
ACTIVATION_C_STACK_FLAGS = ('-Wl,--stack-first', f'-Wl,-z,stack-size={ACTIVATION_C_STACK_BYTES}')
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


def seal(data: bytes, generated: Path, compiler_index: bytes, *, source_before: str | None = None,
         date_required: bool = False) -> tuple[bytes, dict]:
    _, enums, source_bytes, parents, types, source_digest = inventory(generated)
    need(source_before is None or source_before == source_digest, 'source-drift')
    need(len(enums) <= MAX_CLASSES and all(len(fields) <= MAX_SLOTS_PER_CLASS for fields in enums.values())
         and sum(map(len, enums.values())) <= MAX_SLOTS, 'cost-bound')
    _index(compiler_index, enums, parents)
    cleaned = _verify_translation_unit(data, enums, parents, types)
    from tools.java_guest.date_guard import seal as seal_date
    cleaned, date_receipt = seal_date(data, cleaned, required=date_required)
    need(cleaned.count(OLD_COUNT) == 1 and cleaned.count(OLD_VALUE) == 1, 'helper-preimage')
    cleaned = cleaned.replace(OLD_COUNT, b'static int32_t teavm_enumConstantCount(TeaVM_Class* cls);')
    cleaned = cleaned.replace(OLD_VALUE, b'static void* teavm_enumConstant(TeaVM_Class* cls, int32_t index);')
    guard = _guard(enums)
    result = cleaned + guard
    need(len(result) <= MAX_INPUT and source_bytes + len(result) <= MAX_SOURCE, 'sealed-bound')
    receipt = {'schemaVersion': 'latent.java.enum-guard.v1',
                    'compilerIndexSha256': hashlib.sha256(compiler_index).hexdigest(),
                    'generatedSourceSha256': source_digest,
                    'preprocessedSha256': hashlib.sha256(data).hexdigest(),
                    'guardSha256': hashlib.sha256(guard).hexdigest(),
                    'sealedSha256': hashlib.sha256(result).hexdigest(),
                    'sealedBytes': len(result), 'classes': len(enums),
                    'slots': sum(map(len, enums.values())),
                    'maximumClassComparisons': len(enums),
                    'maximumSlotComparisons': max(map(len, enums.values()), default=0)}
    if date_receipt is not None:
        receipt['dateGuard'] = date_receipt
    return result, receipt


def _bindings_identity(directory: Path) -> dict:
    names = ('bridge.c', 'probe.c', 'probe.h', 'probe_component_type.o')
    result = {}
    for name in names:
        data = read_file(directory / name, MAX_INPUT)
        result[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return result


def _date_graph(data: bytes) -> dict:
    need(data in (b'required\n', b'unused\n'), 'date-index')
    return {'selection': data.decode('ascii').strip(), 'sha256': hashlib.sha256(data).hexdigest()}


# Exact resource from the authenticated TeaVM 0.15 compiler JAR. This adaptation
# changes storage, not setjmp sites, handler dispatch, or restoration edges.
# Independent earlier lowering retained for its native reference controls.
# Production run() uses exception_slots.stage exactly once; never chain them.
EXCEPTION_HEADER_SHA256 = '024e4fafa0a2cd330911b5d84d1b929f928a88d74730cc265d08cbbb940eb368'
EXCEPTION_TRY = '''    #define TEAVM_TRY \\
        do { \\
            TeaVM_LongjmpDesc teavm_longJmpdesc; \\
            teavm_longJmpdesc.previous = teavm_shadowStack.header.jmpTarget; \\
            teavm_shadowStack.header.jmpTarget = &teavm_longJmpdesc; \\
            int teavm_exceptionHandler = setjmp(teavm_longJmpdesc.buffer); \\
            if (teavm_exceptionHandler == 0) {'''
EXCEPTION_TRY_SLOT = '''    #define LSF_TEAVM_TRY_SLOT(slot) \\
        do { \\
            (slot).previous = teavm_shadowStack.header.jmpTarget; \\
            teavm_shadowStack.header.jmpTarget = &(slot); \\
            int teavm_exceptionHandler = setjmp((slot).buffer); \\
            if (teavm_exceptionHandler == 0) {'''
_FRAME_TOKEN = re.compile(r'\b(?:TEAVM_TRY|TEAVM_CATCH|TEAVM_END_TRY)\b')
_FRAME_FUNCTION = re.compile(r'^[A-Za-z_][^\n;={}]*\([^\n;{}]*\) \{\n', re.M)


def _frame_code_view(source: str) -> str:
    """Mask comments and literals without changing offsets or line structure."""
    view = list(source)
    pos = 0
    while pos < len(source):
        start = pos
        if source.startswith('//', pos):
            end = source.find('\n', pos)
            pos = len(source) if end < 0 else end
        elif source.startswith('/*', pos):
            end = source.find('*/', pos + 2)
            need(end >= 0, 'exception-frame-comment')
            pos = end + 2
        elif source[pos] in ('"', "'"):
            quote = source[pos]
            pos += 1
            while pos < len(source) and source[pos] != quote:
                need(source[pos] not in '\r\n', 'exception-frame-literal')
                if source[pos] == '\\':
                    pos += 1
                    need(pos < len(source) and source[pos] not in '\r\n', 'exception-frame-escape')
                pos += 1
            need(pos < len(source), 'exception-frame-literal')
            pos += 1
        else:
            pos += 1
            continue
        for index in range(start, pos):
            if source[index] not in '\r\n':
                view[index] = ' '
    return ''.join(view)


def exception_frame_source(raw: bytes) -> tuple[bytes, list[dict]]:
    """Reuse only disjoint lexical handler lifetimes within one generated frame.

    Each active nesting level keeps a distinct descriptor. Catch routing and
    every generated explicit restore before return/break/continue are untouched.
    A recursive call owns new automatic descriptors; no buffer survives suspension
    or return, and no global/heap owner or resource allowance is introduced.
    This accepts the pinned emitter grammar, not arbitrary hand-written C.
    """
    need(len(raw) <= MAX_INPUT, 'exception-frame-source-bound')
    source = raw.decode('utf-8')
    if not _FRAME_TOKEN.search(source) and 'LSF_TEAVM_TRY_SLOT' not in source and 'lsf_teavm_jump_frame_' not in source:
        return raw, []
    need('\r' not in source and '\\\n' not in source, 'exception-frame-lines')
    code = _frame_code_view(source)
    need(not re.search(r'\b(?:LSF_TEAVM_TRY_SLOT|lsf_teavm_jump_frame_[A-Za-z0-9_]*)\b', code),
         'exception-frame-already-adapted')
    edits, records, consumed = [], [], set()
    previous_end = 0
    for match in _FRAME_FUNCTION.finditer(code):
        need(match.start() >= previous_end, 'exception-frame-function-overlap')
        opening = match.end() - 2
        depth, end = 1, opening + 1
        while depth and end < len(code):
            depth += (code[end] == '{') - (code[end] == '}')
            end += 1
        need(depth == 0, 'exception-frame-function-braces')
        previous_end = end
        body = code[match.end():end - 1]
        tokens = list(_FRAME_TOKEN.finditer(body))
        if not tokens:
            continue
        roots = list(re.finditer(r'^    TEAVM_ALLOC_STACK\(INT32_C\([0-9]+\)\);$', body, re.M))
        need(len(roots) == 1 and roots[0].end() < tokens[0].start(), 'exception-frame-root')
        stack, maximum, sites = [], 0, 0
        for token in tokens:
            offset = match.end() + token.start()
            start = code.rfind('\n', match.end(), offset) + 1
            stop = code.find('\n', offset)
            need(stop >= 0 and code[start:stop].strip() == token.group(), 'exception-frame-token-shape')
            consumed.add(offset)
            if token.group() == 'TEAVM_TRY':
                edits.append((offset, offset + len(token.group()), f'LSF_TEAVM_TRY_SLOT(lsf_teavm_jump_frame_{len(stack)})'))
                stack.append('try')
                maximum = max(maximum, len(stack))
                sites += 1
                need(maximum <= 256 and sites <= 65536, 'exception-frame-cost-bound')
            elif token.group() == 'TEAVM_CATCH':
                need(bool(stack) and stack[-1] == 'try', 'exception-frame-catch')
                stack[-1] = 'catch'
            else:
                need(bool(stack) and stack[-1] == 'catch', 'exception-frame-end')
                stack.pop()
        need(not stack, 'exception-frame-unclosed')
        # Separate automatic objects, not a shared aggregate: changing an inner
        # descriptor must not change the outer descriptor across its setjmp.
        declarations = ''.join(f'    TeaVM_LongjmpDesc lsf_teavm_jump_frame_{slot};\n'
                               for slot in range(maximum))
        edits.append((match.end(), match.end(), declarations))
        records.append({'function': source[match.start():opening].strip(),
                        'sites': sites, 'slots': maximum})
        need(len(records) <= 65536, 'exception-frame-function-bound')
    need(consumed == {token.start() for token in _FRAME_TOKEN.finditer(code)},
         'exception-frame-unscoped-token')
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    result = source.encode('utf-8')
    need(len(result) <= MAX_INPUT, 'exception-frame-output-bound')
    return result, records


def compact_exception_frames(generated: Path) -> dict:
    """Validate the complete input before modifying any generated compiler bytes."""
    initial = inventory(generated)
    source_before = initial[-1]
    header = generated / 'exceptions.h'
    original = read_file(header, 65536)
    need(hashlib.sha256(original).hexdigest() == EXCEPTION_HEADER_SHA256,
         'exception-frame-header-preimage')
    text = original.decode('utf-8')
    need(text.count(EXCEPTION_TRY) == 1, 'exception-frame-header-shape')
    outputs, identities, total_sites, total_slots = [], [], 0, 0
    for path in sorted(generated.rglob('*.c')):
        raw = read_file(path, MAX_INPUT)
        adapted, records = exception_frame_source(raw)
        if not records:
            continue
        outputs.append((path, raw, adapted))
        total_sites += sum(row['sites'] for row in records)
        total_slots += sum(row['slots'] for row in records)
        identities.append({'path': path.relative_to(generated).as_posix(),
                           'originalSha256': hashlib.sha256(raw).hexdigest(),
                           'adaptedSha256': hashlib.sha256(adapted).hexdigest(),
                           'functions': records})
    adapted_header = text.replace(EXCEPTION_TRY, EXCEPTION_TRY + '\n' + EXCEPTION_TRY_SLOT).encode('utf-8')
    need(initial[2] + len(adapted_header) - len(original)
         + sum(len(adapted) - len(raw) for _path, raw, adapted in outputs) <= MAX_SOURCE,
         'exception-frame-total-bound')
    need(inventory(generated)[-1] == source_before, 'exception-frame-source-drift')
    for path, raw, _adapted in outputs:
        need(read_file(path, MAX_INPUT) == raw, 'exception-frame-source-drift')
    need(read_file(header, 65536) == original, 'exception-frame-header-drift')
    for path, _raw, adapted in outputs:
        path.write_bytes(adapted)
    header.write_bytes(adapted_header)
    return {'profile': 'teavm-0.15-lexical-exception-frames-v1',
            'sourceBeforeSha256': source_before,
            'sourceAfterSha256': inventory(generated)[-1],
            'headerOriginalSha256': EXCEPTION_HEADER_SHA256,
            'headerAdaptedSha256': hashlib.sha256(adapted_header).hexdigest(),
            'handlerSites': total_sites, 'functionLocalSlots': total_slots, 'files': identities}


def run(compiler, generated: Path, selected: tuple[str, ...], destination: Path, core: Path) -> dict:
    """Preprocess once, validate, then link the exact sealed bytes on stdin."""
    bindings = destination / 'bindings'
    sdk = compiler.sdk
    original = _bindings_identity(bindings)
    index_path = generated.parents[2] / 'compiler-patch/enum-index-v1.tsv'
    index = read_file(index_path, MAX_INDEX)
    date_index_path = index_path.with_name('date-init-required-v1.txt')
    date_index = read_file(date_index_path, 32)
    graph_receipt = _date_graph(date_index)
    from tools.java_guest.exception_slots import stage as stage_exception_slots
    exception_slots = stage_exception_slots(generated)
    source_before = inventory(generated)[-1]
    preprocessed = compiler.capture_preprocessed('-target', 'wasm32-wasip1', '-std=c11', '-O2',
        '-DLSF_JAVA_ACTIVATION_PROFILE=1', '-DLSF_TEAVM_WASM=1', '-DTEAVM_CUSTOM_LOG=1',
        '-mllvm', '-wasm-enable-sjlj', '-mllvm', '-wasm-use-legacy-eh=false',
        '-include', sdk / 'runtime/native.h', '-I', bindings, '-I', sdk / 'runtime', '-iquote', generated,
        '-E', '-dD', generated / 'all.c')
    need(time.monotonic() < compiler.deadline, 'deadline')
    sealed, receipt = seal(preprocessed, generated, index, source_before=source_before,
                           date_required=date_index == b'required\n')
    need(time.monotonic() < compiler.deadline, 'deadline')
    if 'dateGuard' in receipt:
        from tools.java_guest.date_link_guard import run as run_date_link
        receipt['dateGuard']['link'] = run_date_link(compiler, generated, selected, destination, core, sealed)
    else:
        # Keep the fixed downward-growing C stack below static data. An overflow
        # must trap at the memory boundary, not overwrite allocator/bridge state.
        c_failure_context.run(compiler, generated, selected, '-target', 'wasm32-wasip1', '-std=c11', '-O2',
            '-DLSF_JAVA_ACTIVATION_PROFILE=1', '-DLSF_TEAVM_WASM=1', '-DTEAVM_CUSTOM_LOG=1',
            '-mllvm', '-wasm-enable-sjlj', '-lsetjmp', '-mllvm', '-wasm-use-legacy-eh=false',
            '-mexec-model=reactor', '-Wl,--no-entry', '-Wl,--export-memory', *ACTIVATION_C_STACK_FLAGS,
            '-Wl,--max-memory=67108864', '-include', sdk / 'runtime/native.h',
            '-I', bindings, '-I', sdk / 'runtime', '-iquote', generated,
            '-x', 'cpp-output', '-', '-x', 'none', bindings / 'bridge.c', sdk / 'feasibility/platform.c',
            bindings / 'probe.c', bindings / 'probe_component_type.o', '-o', core, input_bytes=sealed)
    need(original == _bindings_identity(bindings), 'bindings-drift')
    need(index == read_file(index_path, MAX_INDEX), 'index-drift')
    need(date_index == read_file(date_index_path, 32), 'date-index-drift')
    receipt['cStack'] = {'bytes': ACTIVATION_C_STACK_BYTES, 'layout': 'stack-first'}
    receipt['exceptionSlots'] = exception_slots
    receipt['dateGraph'] = graph_receipt
    receipt['bindings'] = original
    return receipt
