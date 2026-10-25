"""Automatic bounded queries from captured declarations, never app policy.

Source candidates select passive compiler observations. They do not prove that
an expression is a call, that its spelling resolves to an API, or that a method
is reachable. Only the actual complete compiler body can establish a call edge.
"""
from __future__ import annotations

import re
from pathlib import Path

from tools import guest_compiler_edges as edges
from tools.dev_workflow.common import digest, encode, members, require, sha
from tools.rust_capsule_project import inventory, read_file, write_json

OUTPUT = 'compatibility-compiler-edges.json'
MAX_QUERIES = 32
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_BODY_WORK = 32 * 1024 * 1024
KINDS = {'c': 'c-llvm', 'rust': 'rust-mir', 'go': 'go-ssa'}
RECIPE = ('tools/guest_compiler_edges.py', 'tools/guest_compiler_capture.py')
CONTROL = frozenset(('if', 'else', 'while', 'for', 'switch', 'return', 'sizeof', 'alignof',
                     'match', 'loop', 'unsafe', 'select', 'defer', 'go', 'func', 'fn'))


def code(raw, language):
    """Mask comments/literals without changing offsets; unfamiliar syntax omits.

    This finite source reader is query selection only. It never certifies the
    meaning of a source expression or a compiler-eliminated API.
    """
    require(type(raw) is bytes and len(raw) <= edges.MAX_BYTES, 'compiler-query-source-byte-limit')
    text = raw.decode('utf-8')
    require('\0' not in text, 'compiler-query-source-nul')
    if language == 'rust' and re.search(r'\br#*"|\'[A-Za-z_]', text):
        raise ValueError('compiler-query-unmapped-Rust-literal-or-lifetime')
    if language == 'go' and '`' in text:
        # Go raw strings are supported below; C/Rust backticks are not strings.
        pass
    result, at = list(text), 0
    while at < len(text):
        start = at
        if text.startswith('//', at):
            end = text.find('\n', at + 2); at = len(text) if end < 0 else end
        elif text.startswith('/*', at):
            depth, at = 1, at + 2
            while depth and at < len(text):
                if text.startswith('/*', at):
                    require(language == 'rust' and depth < 32, 'compiler-query-comment-nesting')
                    depth += 1; at += 2
                elif text.startswith('*/', at): depth -= 1; at += 2
                else: at += 1
            require(depth == 0, 'compiler-query-truncated-comment')
        elif text[at] in ('"', "'", '`'):
            quote = text[at]
            require(quote != '`' or language == 'go', 'compiler-query-unmapped-literal')
            at += 1
            while at < len(text) and text[at] != quote:
                if text[at] == '\\' and quote != '`': at += 2
                else: at += 1
            require(at < len(text), 'compiler-query-truncated-literal'); at += 1
        else:
            at += 1; continue
        for index in range(start, at):
            if result[index] not in '\r\n': result[index] = ' '
    return ''.join(result)


def go_imports(raw, masked):
    """Finite original import declarations, not a guessed alias registry.

    The masked source locates real import tokens outside comments/literals;
    original bytes supply their literal paths. Dot/blank and exotic imports
    are not resolved, and conflicting aliases refuse this passive source unit.
    """
    original, aliases = raw.decode('utf-8'), {}
    for start in re.finditer(r'(?m)^\s*import\b', masked):
        at = start.end()
        while at < len(original) and original[at] in ' \t': at += 1
        if at < len(original) and original[at] == '(':
            end = original.find(')', at + 1)
            require(end >= 0 and end - at <= 16384, 'compiler-query-Go-import-bound')
            body = original[at + 1:end]
        else:
            end = original.find('\n', at)
            body = original[at:len(original) if end < 0 else end]
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith('//'): continue
            match = re.fullmatch(r'(?:(\w+|\.)\s+)?"([A-Za-z0-9_./-]{1,192})"\s*(?://[^\r\n]*)?', line)
            require(match is not None and '..' not in match[2].split('/'), 'compiler-query-Go-import-shape')
            alias, path = match[1], match[2]
            # An unaliased import uses the imported package's DECLARED name,
            # not necessarily its path basename. No guessed resolution.
            if alias is None or alias in ('_', '.'): continue
            if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', alias): continue
            require(alias not in aliases, 'compiler-query-Go-import-alias')
            aliases[alias] = path
    return aliases


def rust_conditionals(text):
    """Conservative cfg item ranges; an unrelated later item is not this fn.

    Only brace-bodied items are understood. Unknown attribute/item framing
    refuses the unit, rather than treating it as unconditional. No cfg is
    evaluated or inferred true from this source reader.
    """
    result, work = [], 0
    for match in re.finditer(r'#\s*\[\s*cfg(?:_attr)?\s*\(', text):
        require(len(result) < 256, 'compiler-query-Rust-conditional-bound')
        end = text.find(']', match.end())
        require(end >= 0 and end - match.start() <= 4096, 'compiler-query-Rust-attribute-shape')
        opening = text.find('{', end + 1)
        require(opening >= 0 and opening - end <= 4096 and ';' not in text[end + 1:opening],
                'compiler-query-Rust-conditional-item')
        depth, at = 1, opening + 1
        while depth and at < len(text):
            work += 1
            require(work <= MAX_BODY_WORK, 'compiler-query-Rust-conditional-work')
            if text[at] == '{': depth += 1
            elif text[at] == '}': depth -= 1
            require(depth <= 256, 'compiler-query-Rust-conditional-depth')
            at += 1
        require(depth == 0, 'compiler-query-Rust-conditional-tail')
        result.append((match.start(), at))
    return result


def go_emitted_symbol(import_path, function):
    """Pinned Go1.27 linker spelling, followed by its Wasm name sanitizer.

    cmd/compile/internal/types/pkg.go -> objabi.PathToPrefix ->
    cmd/compile/internal/base.PkgLinksym -> cmd/link/internal/wasm nameRegexp.
    This is a candidate only: the final component must contain exactly ONE
    matching actual name. Sanitizer collisions/missing stripped names refuse.
    """
    require(type(import_path) is str and 0 < len(import_path.encode()) <= 384
        and import_path not in {'go', 'type'} and not import_path.endswith('/')
        and all(part not in {'', '.', '..'} for part in import_path.split('/')),
        'compiler-query-Go-package-name')
    edges.identifier(function)
    raw, last_slash = import_path.encode(), import_path.encode().rfind(b'/')
    prefix = ''.join('%' + format(byte, '02x') if byte <= 32 or byte in (37, 34) or byte >= 127
        or byte == 46 and at > last_slash else chr(byte) for at, byte in enumerate(raw))
    name = re.sub(r'[^A-Za-z0-9_.]', '_', prefix + '.' + function)
    edges.identifier(name)
    return name


def automatic(files, language):
    """LSF-generated selection; no query file, command flag or application gate.

    Prioritize initializer declarations and ordinary export declarations, then
    the remaining captured functions. Ambiguous syntax is counted as unknown.
    Source-only labels never become a final-component reachability assertion.
    """
    require(language in KINDS, 'compiler-query-language')
    require(type(files) is dict and len(files) <= 32768, 'compiler-query-input-count')
    suffix = {'c': '.c', 'rust': '.rs', 'go': '.go'}[language]
    selected, total, functions, unavailable, candidates = [], 0, 0, 0, 0
    work, exhausted, declarations, conditional = 0, False, {}, set()
    for path, raw in sorted(files.items()):
        if not path.startswith('src/') or not path.endswith(suffix): continue
        if re.fullmatch(r'src/[A-Za-z0-9_./-]{1,192}', path) is None or '..' in path.split('/'):
            unavailable += 1; continue
        total += len(raw)
        if total > MAX_SOURCE_BYTES or exhausted:
            unavailable += 1; continue
        try:
            text = code(raw, language)
            aliases = go_imports(raw, text) if language == 'go' else {}
            conditional_items = rust_conditionals(text) if language == 'rust' else []
        except (ValueError, UnicodeError):
            unavailable += 1; continue
        if (language == 'c' and re.search(r'(?m)^\s*#\s*(?:if|ifdef|ifndef|elif)\b', text)
                or language == 'go' and re.search(rb'(?m)^//(?:go:build|go:linkname|\s*\+build)\b', raw)):
            conditional.add(path)
        if language == 'c':
            pattern = r'(?m)^[ \t]*(?:(?:[A-Za-z_][A-Za-z0-9_]*|\*)[ \t]+)+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*\{'
        elif language == 'rust':
            pattern = r'\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)(?:\s*->[^;{}]*)?\s*\{'
        else:
            pattern = r'(?m)^func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)[^{;\n]*\{'
        for declaration in re.finditer(pattern, text):
            if functions >= 65536 or exhausted:
                unavailable += 1; exhausted = True; break
            functions += 1
            root = declaration[1]
            if not edges.IDENTIFIER.fullmatch(root):
                unavailable += 1; continue
            declarations[root] = declarations.get(root, 0) + 1
            # Balanced actual source body; source braces inside strings/comments
            # have already been masked. No unbounded recursive parser.
            depth, at = 1, declaration.end()
            while depth and at < len(text):
                work += 1
                if work > MAX_BODY_WORK:
                    exhausted = True; break
                if text[at] == '{': depth += 1
                elif text[at] == '}': depth -= 1
                if depth > 256: break
                at += 1
            if depth:
                unavailable += 1; continue
            body = text[declaration.end():at - 1]
            callees = sorted(set(match[1] for match in re.finditer(
                r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*(?:(?:::|\.)[A-Za-z_][A-Za-z0-9_]*)*)\s*\(', body)
                if match[1] not in CONTROL and match[1] != root))
            initializer = root == 'init' or root.startswith(('initialize_', '__init', '_GLOBAL__sub_I_'))
            exported = (root.startswith('exports_') if language == 'c' else
                        root[:1].isupper() if language == 'go' else
                        bool(re.search(r'\bpub\b', text[max(0, declaration.start() - 64):declaration.start()])))
            role = 'initializer-declaration' if initializer else 'export-declaration' if exported else 'captured-declaration'
            for callee in callees:
                if not edges.IDENTIFIER.fullmatch(callee):
                    unavailable += 1; continue
                candidates += 1
                if candidates > 65536:
                    exhausted = True; unavailable += 1; break
                query = {'source': path, 'root': root, 'callee': callee, 'declarationRole': role,
                         'sourceIdentity': digest(raw)}
                target, resolution = callee, 'unresolved-source-spelling'
                ambiguous_selector = False
                if language == 'go' and '.' in callee:
                    alias, member = callee.split('.', 1)
                    if alias in aliases and re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', member):
                        # A valid Go parameter/local may shadow its file's
                        # import. Bare occurrences in the signature/body make
                        # this finite source attribution unavailable. Never
                        # turn a receiver call into an imported API query.
                        header = text[declaration.start():declaration.end()]
                        ambiguous_selector = bool(re.search(r'\b' + re.escape(alias) + r'\b', header)
                            or re.search(r'\b' + re.escape(alias) + r'\b(?!\s*\.)', body))
                        if not ambiguous_selector:
                            resolved = aliases[alias] + '.' + member
                            if edges.IDENTIFIER.fullmatch(resolved):
                                target, resolution = resolved, 'captured-import-identity'
                            else:
                                ambiguous_selector = True
                query.update(compilerTarget=target, calleeResolution=resolution)
                query['_conditional'] = any(start <= declaration.start() < end for start, end in conditional_items)
                query['_ambiguousSelector'] = ambiguous_selector
                selected.append(query)
                selected.sort(key=lambda row: ({'initializer-declaration': 0, 'export-declaration': 1,
                    'captured-declaration': 2}[row['declarationRole']], row['source'], row['root'], row['callee']))
                selected = selected[:MAX_QUERIES]
    for query in selected:
        local_conditional = query.pop('_conditional')
        ambiguous_selector = query.pop('_ambiguousSelector')
        query['declarationState'] = ('ambiguous-captured-declaration' if declarations[query['root']] != 1 else
            'conditionally-compiled-declaration' if query['source'] in conditional or local_conditional else
            'unresolved-receiver-binding' if ambiguous_selector else
            'incomplete-captured-declarations' if unavailable else 'unique-captured-candidate')
        query['id'] = digest(encode(query))[7:]
    return {'schemaVersion': 'lsf.guest.automatic-compiler-queries.v1', 'language': language,
        'sourceDigest': digest(inventory(files)), 'queries': selected, 'functionsInspected': functions,
        'omittedQueries': candidates - len(selected), 'unmappedSourceUnits': unavailable,
        'selection': 'lsf-captured-declarations', 'rootReachability': 'unknown', 'apiResolution': 'unknown'}


class Capture:
    """Small private raw set; public output contains hashes/counts only."""
    def __init__(self, files, language):
        self.language = language
        self.selection = automatic(files, language)
        self.raw, self.failures, self.total, self.units = {}, {
            row['id'] for row in self.queries if row['declarationState'] != 'unique-captured-candidate'}, 0, set()
        self.source_files = files
        self.emitted_roots = {}

    @property
    def queries(self): return self.selection['queries']

    def failed(self, identity):
        require(identity in {row['id'] for row in self.queries}, 'compiler-query-unselected')
        self.failures.add(identity)

    def bind_go_root(self, identity, import_path):
        require(self.language == 'go' and identity in {row['id'] for row in self.queries}
            and identity not in self.emitted_roots, 'compiler-query-Go-root-binding')
        query = next(row for row in self.queries if row['id'] == identity)
        self.emitted_roots[identity] = {'format': 'go-1.27-wasm-name-v1',
            'importPathDigest': digest(import_path.encode()), 'symbol': go_emitted_symbol(import_path, query['root'])}

    def retain(self, identity, raw):
        require(identity in {row['id'] for row in self.queries} and identity not in self.raw,
                'compiler-query-unselected-or-duplicate')
        require(type(raw) is bytes and 0 < len(raw) <= edges.MAX_BYTES, 'compiler-query-raw-byte-limit')
        unit = digest(raw)
        extra = 0 if unit in self.units else len(raw)
        require(self.total + extra <= MAX_RAW_BYTES, 'compiler-query-raw-byte-limit')
        self.raw[identity] = raw; self.total += extra; self.units.add(unit)

    def retain_unit(self, path, raw):
        """One original compiler output may answer several selected queries."""
        for query in self.queries:
            if query['source'] == path:
                self.retain(query['id'], raw)

    def fail_unit(self, path):
        for query in self.queries:
            if query['source'] == path: self.failed(query['id'])

    def finish(self, output: Path, files, component, recipe, compiler, graph):
        require(automatic(files, self.language) == self.selection, 'compiler-query-selection-changed')
        for item in (recipe, compiler, graph): sha(item)
        bindings = {'sourceDigest': self.selection['sourceDigest'], 'componentDigest': digest(component),
                    'recipeDigest': recipe, 'compilerDigest': compiler, 'graphDigest': graph}
        rows = []
        for query in self.queries:
            observed = None
            if query['id'] in self.raw and query['id'] not in self.failures:
                try: observed = edges.observe(KINDS[self.language], self.raw[query['id']], query['root'], query['compilerTarget'], bindings)
                except (ValueError, UnicodeError): pass
            rows.append({**query, 'emittedRoot': self.emitted_roots.get(query['id']),
                'state': 'observed' if observed is not None else 'unavailable',
                **({'observation': observed} if observed is not None else {'reason': 'witness-unavailable-or-unknown'})})
        value = {'schemaVersion': 'lsf.guest.automatic-compiler-results.v1', **bindings,
            'language': self.language, 'selectionDigest': digest(encode(self.selection)), 'queries': rows,
            **{key: self.selection[key] for key in ('functionsInspected', 'omittedQueries', 'unmappedSourceUnits')},
            'apiSupport': 'unknown', 'wholeProgramElimination': 'unknown', 'rootReachability': 'unknown', 'authority': 'none'}
        value['identity'] = digest(encode(value))
        validate(value, files=files, bindings=bindings)
        write_json(output / OUTPUT, value)
        return value


def validate(value, *, files=None, bindings=None):
    keys = ('sourceDigest', 'componentDigest', 'recipeDigest', 'compilerDigest', 'graphDigest')
    members(value, {'schemaVersion', 'language', *keys, 'selectionDigest', 'queries', 'functionsInspected',
        'omittedQueries', 'unmappedSourceUnits', 'apiSupport', 'wholeProgramElimination', 'rootReachability',
        'authority', 'identity'})
    require(value['schemaVersion'] == 'lsf.guest.automatic-compiler-results.v1' and value['language'] in KINDS
            and (value['apiSupport'], value['wholeProgramElimination'], value['rootReachability'], value['authority']) ==
                ('unknown', 'unknown', 'unknown', 'none'), 'compiler-query-result-scope')
    for key in (*keys, 'selectionDigest', 'identity'): sha(value[key])
    for key in ('functionsInspected', 'omittedQueries', 'unmappedSourceUnits'):
        require(type(value[key]) is int and 0 <= value[key] <= 2**64 - 1, 'compiler-query-result-count')
    rows = value['queries']
    require(type(rows) is list and len(rows) <= MAX_QUERIES, 'compiler-query-result-selection')
    seen = set()
    for row in rows:
        members(row, {'id', 'source', 'root', 'callee', 'compilerTarget', 'calleeResolution',
            'declarationRole', 'declarationState', 'sourceIdentity', 'state', 'emittedRoot'}, {'reason', 'observation'})
        require(type(row['id']) is str and re.fullmatch('[0-9a-f]{64}', row['id']) and row['id'] not in seen,
                'compiler-query-result-id')
        seen.add(row['id']); sha(row['sourceIdentity'])
        query = {key: row[key] for key in ('source', 'root', 'callee', 'compilerTarget', 'calleeResolution',
            'declarationRole', 'declarationState', 'sourceIdentity')}
        require(row['id'] == digest(encode(query))[7:] and type(row['source']) is str
                and re.fullmatch(r'src/[A-Za-z0-9_./-]{1,192}', row['source']) and '..' not in row['source'].split('/')
                and row['declarationRole'] in {'initializer-declaration', 'export-declaration', 'captured-declaration'}
                and row['declarationState'] in {'unique-captured-candidate', 'ambiguous-captured-declaration',
                    'conditionally-compiled-declaration', 'incomplete-captured-declarations', 'unresolved-receiver-binding'},
                'compiler-query-result-query')
        edges.identifier(row['root']); edges.identifier(row['callee']); edges.identifier(row['compilerTarget'])
        require(type(row['calleeResolution']) is str and row['calleeResolution'] in
            {'unresolved-source-spelling', 'captured-import-identity'}
            and (row['calleeResolution'] != 'captured-import-identity' or value['language'] == 'go'),
            'compiler-query-result-callee-resolution')
        fields = {'id', 'source', 'root', 'callee', 'compilerTarget', 'calleeResolution',
                  'declarationRole', 'declarationState', 'sourceIdentity', 'state', 'emittedRoot'}
        if row['emittedRoot'] is not None:
            bound_root = members(row['emittedRoot'], {'format', 'importPathDigest', 'symbol'})
            require(value['language'] == 'go' and bound_root['format'] == 'go-1.27-wasm-name-v1',
                    'compiler-query-emitted-root-language')
            sha(bound_root['importPathDigest']); edges.identifier(bound_root['symbol'])
        if row['state'] == 'observed':
            require(set(row) == fields | {'observation'}
                    and row['declarationState'] == 'unique-captured-candidate',
                    'compiler-query-result-fields')
            observed = edges.validate(row['observation'], bindings={key: value[key] for key in keys})
            require(observed['compilerFormat'] == KINDS[value['language']]
                    and observed['rootIdentity'] == digest(row['root'].encode())
                    and observed['targetIdentity'] == digest(row['compilerTarget'].encode()), 'compiler-query-result-format-or-symbol')
        else:
            require(row['state'] == 'unavailable' and set(row) == fields | {'reason'}
                and row['reason'] == 'witness-unavailable-or-unknown',
                'compiler-query-result-fields')
    if files is not None:
        selected = automatic(files, value['language'])
        require(value['sourceDigest'] == selected['sourceDigest'] and value['selectionDigest'] == digest(encode(selected))
                and ([{key: row[key] for key in selected['queries'][0]} for row in rows] == selected['queries']
                    if selected['queries'] else not rows), 'compiler-query-result-detached-source')
        require(all(value[key] == selected[key] for key in ('functionsInspected', 'omittedQueries', 'unmappedSourceUnits')),
                'compiler-query-result-detached-count')
    if bindings is not None:
        require(set(bindings) == set(keys) and all(value[key] == item for key, item in bindings.items()),
                'compiler-query-result-stale-binding')
    require(len(encode(value)) <= 65536
            and value['identity'] == digest(encode({key: item for key, item in value.items() if key != 'identity'})),
            'compiler-query-result-identity')
    return value


def finish(captured, output, files, component, recipe, compiler):
    """Bind the reduced observation as a normal existing build material."""
    from tools import guest_runtime_receipts
    graph = guest_runtime_receipts.captured_graph(files)
    value = captured.finish(output, files, component, digest(recipe), compiler, digest(encode(graph)))
    raw = read_file(output / OUTPUT, 65536)
    return {'name': 'compiler-call-edges', 'digest': digest(raw), 'size': len(raw)}
