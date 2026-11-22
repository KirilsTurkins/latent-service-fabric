"""Reuse disjoint TeaVM C handler buffers, never overlapping handler lifetimes.

A longjmp descriptor is linked only between TEAVM_TRY and its original restore.
Separate automatic objects are retained for every lexical nesting level. Only
sequential regions in the same native invocation reuse an object; no buffer is
moved to the heap, shared across invocations, or retained after native return.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from tools.java_guest.enum_inventory import MAX_ENTRIES, MAX_FILES, MAX_FILE, MAX_SOURCE
from tools.rust_capsule_project import read_file

HEADER_SHA256 = '024e4fafa0a2cd330911b5d84d1b929f928a88d74730cc265d08cbbb940eb368'
PREFIX = 'lsf_teavm_jump_slot_'
MACRO = 'LSF_TEAVM_TRY_SLOT'
MARKER = re.compile(r'\bTEAVM_(?:TRY|CATCH|END_TRY)\b|[{}]')
FUNCTION = re.compile(r'[A-Za-z_][A-Za-z_0-9* \t]*\b[A-Za-z_][A-Za-z_0-9]*'
                      r'\([^;{}\r\n]*\)[ \t]*\{')
PROTECTED = re.compile(r'^[ \t]*#[ \t]*(?:define|undef)[ \t]+'
                       r'(?:TEAVM_(?:TRY|CATCH|END_TRY|RESTORE_JUMP_BUFFER)|'
                       r'LSF_TEAVM_TRY_SLOT|lsf_teavm_jump_slot_[A-Za-z_0-9]*)\b', re.M)


def need(value: bool, reason: str) -> None:
    if not value:
        raise ValueError('java-exception-slots-' + reason)


def mask(source: str) -> str:
    """Keep positions/newlines while hiding C comments and quoted literals."""
    need("\0" not in source, "nul")
    out = list(source)
    index = 0
    while index < len(source):
        start = index
        if source.startswith('//', index):
            end = source.find('\n', index)
            index = len(source) if end < 0 else end
        elif source.startswith('/*', index):
            end = source.find('*/', index + 2)
            need(end >= 0, 'comment')
            index = end + 2
        elif source[index] in ('"', "'"):
            quote = source[index]
            index += 1
            while index < len(source):
                value = source[index]
                need(value not in '\r\n\0', 'literal')
                index += 1
                if value == quote:
                    break
                if value == '\\':
                    need(index < len(source) and source[index] not in '\r\n\0', 'escape')
                    index += 1
            else:
                raise ValueError('java-exception-slots-literal')
        else:
            need(source[index] != '\0', 'nul')
            index += 1
            continue
        for pos in range(start, index):
            if source[pos] not in '\r\n':
                out[pos] = ' '
    return ''.join(out)


def header(original: bytes) -> bytes:
    """Derive a second macro from the exact pinned original, not a new EH path."""
    need(hashlib.sha256(original).hexdigest() == HEADER_SHA256, 'header-preimage')
    text = original.decode('ascii')
    start = text.index('    #define TEAVM_TRY \\\n')
    end = text.index('    #define TEAVM_CATCH ', start)
    selected = text[start:end]
    declaration = '            TeaVM_LongjmpDesc teavm_longJmpdesc; \\\n'
    need(selected.count(declaration) == 1, 'declaration')
    selected = selected.replace('#define TEAVM_TRY ', '#define ' + MACRO + '(slot) ', 1)
    selected = selected.replace(declaration, '').replace('teavm_longJmpdesc', '(slot)')
    return original + ('\n#if TEAVM_USE_SETJMP && defined(LSF_JAVA_ACTIVATION_PROFILE)\n'
                       + selected + '#endif\n').encode('ascii')


def transform(raw: bytes) -> tuple[bytes, dict]:
    """Change only whole-line handler markers inside ordinary generated functions.

    A brace/marker stack checks the emitted structured form before edits. The
    existing catch, restore, rethrow, spill and continuation text is untouched.
    Separate slot variables (not an array) keep a live outer setjmp object's C
    automatic-object lifetime independent of mutations of nested descriptors.
    """
    need(len(raw) <= MAX_FILE, 'file-bound')
    text = raw.decode('utf-8')
    need('\\\n' not in text and '\\\r\n' not in text, 'line-splice')
    code = mask(text)
    need(PREFIX not in code and MACRO not in code and 'teavm_longJmpdesc' not in code,
         'reserved-name')
    need(PROTECTED.search(code) is None, 'macro-override')
    edits = []
    braces = 0
    opening = None
    handlers = []
    regions = []
    depth = 0
    methods = total_regions = total_slots = 0
    for token in MARKER.finditer(code):
        value = token.group()
        if value == '{':
            if braces == 0:
                line = code[code.rfind('\n', 0, token.start()) + 1:token.end()]
                opening = token.end() if FUNCTION.fullmatch(line) else None
                regions, handlers, depth = [], [], 0
            braces += 1
        elif value == '}':
            need(braces > 0, 'braces')
            braces -= 1
            if braces == 0:
                need(not handlers, 'unclosed-handler')
                if opening is not None and len(regions) > depth:
                    declarations = ''.join('\n    TeaVM_LongjmpDesc ' + PREFIX + str(slot) + ';'
                                           for slot in range(depth))
                    edits.append((opening, opening, declarations))
                    edits.extend((start, end, MACRO + '(' + PREFIX + str(slot) + ')')
                                 for start, end, slot in regions)
                    methods += 1
                    total_regions += len(regions)
                    total_slots += depth
                opening = None
        else:
            need(opening is not None, 'handler-outside-function')
            line_start = code.rfind('\n', 0, token.start()) + 1
            line_end = code.find('\n', token.end())
            if line_end < 0:
                line_end = len(code)
            need(code[line_start:line_end].strip() == value, 'marker-shape')
            if value == 'TEAVM_TRY':
                regions.append((token.start(), token.end(), len(handlers)))
                handlers.append((braces, False))
                depth = max(depth, len(handlers))
            elif value == 'TEAVM_CATCH':
                need(bool(handlers) and handlers[-1] == (braces, False), 'catch-order')
                handlers[-1] = (braces, True)
            else:
                need(bool(handlers) and handlers[-1] == (braces, True), 'end-order')
                handlers.pop()
    need(braces == 0 and not handlers, 'unclosed-source')
    # Preprocessor control inside a rewritten function could invalidate the
    # lexical proof. Pinned generated class bodies contain no directives.
    if edits:
        for line in code.splitlines():
            need(not line.lstrip().startswith('#') or line.lstrip().startswith('#include '),
                 'conditional-source')
    pieces, cursor = [], 0
    for start, end, value in sorted(edits):
        need(cursor <= start, 'overlapping-edits')
        pieces.extend((text[cursor:start], value))
        cursor = end
    pieces.append(text[cursor:])
    result = ''.join(pieces).encode('utf-8')
    need(len(result) <= MAX_FILE, 'output-bound')
    return result, {'methods': methods, 'regions': total_regions, 'slots': total_slots}


def stage(generated: Path) -> dict:
    """Validate every input before changing the private generated source tree."""
    need(generated.is_dir() and not generated.is_symlink() and not generated.is_junction(), 'root')
    original_header = read_file(generated / 'exceptions.h', 65536)
    adapted_header = header(original_header)
    originals, outputs, identities = {}, {}, []
    entries = total = methods = regions = slots = 0
    for path in sorted(generated.rglob('*')):
        entries += 1
        need(entries <= MAX_ENTRIES and not path.is_symlink() and not path.is_junction(), 'entry-bound')
        if path.suffix not in ('.c', '.h'):
            continue
        need(len(originals) < MAX_FILES, 'file-count')
        raw = read_file(path, MAX_FILE)
        total += len(raw)
        need(total <= MAX_SOURCE, 'source-bound')
        originals[path] = raw
        if path == generated / 'exceptions.h':
            need(raw == original_header, 'source-drift')
            continue
        # C removes escaped newlines before recognizing comments/directives.
        # Do not let a split protected macro name bypass the ownership check.
        logical = raw.decode('utf-8').replace('\\\r\n', '').replace('\\\n', '')
        code = mask(logical)
        need(PROTECTED.search(code) is None and PREFIX not in code and MACRO not in code,
             'macro-override')
        if path.suffix != '.c' or not re.search(r'\bTEAVM_(?:TRY|CATCH|END_TRY)\b', code):
            continue
        value, observed = transform(raw)
        if value != raw:
            outputs[path] = value
            methods += observed['methods']
            regions += observed['regions']
            slots += observed['slots']
            identities.append({'path': path.relative_to(generated).as_posix(),
                               'inputSha256': hashlib.sha256(raw).hexdigest(),
                               'outputSha256': hashlib.sha256(value).hexdigest(), **observed})
    if outputs:
        outputs[generated / 'exceptions.h'] = adapted_header
    need(total + sum(len(data) - len(originals[path]) for path, data in outputs.items()) <= MAX_SOURCE,
         'output-bound')
    for path, raw in originals.items():
        need(read_file(path, MAX_FILE) == raw, 'source-drift')
    for path, data in outputs.items():
        path.write_bytes(data)
    return {'schemaVersion': 'latent.java.exception-slots.v1',
            'headerInputSha256': HEADER_SHA256,
            'headerOutputSha256': hashlib.sha256(adapted_header if outputs else original_header).hexdigest(),
            'methods': methods, 'regions': regions, 'slots': slots, 'files': identities}
