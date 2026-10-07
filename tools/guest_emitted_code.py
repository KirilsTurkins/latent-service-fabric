"""Bounded compiler-emitted core call graphs; never execute guest initialization.

Encoding references: WebAssembly/core binary modules and instructions, and
WebAssembly/component-model design/mvp/Binary.md. This deliberately decodes a
finite subset. Unknown instructions/features make elimination unknown instead
of treating their bytes as calls. This is diagnostics, not a Wasm validator.
"""
from __future__ import annotations

from collections import deque
import re

from tools import guest_compatibility as compatibility
from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha
from tools.rust_capsule_project import read_file, write_json

SCHEMA = 'lsf.guest.emitted-reachability.v1'
MAX_BYTES = 65536
MAX_FINDINGS = 64
MAX_ANALYSIS_BYTES = 8 * 1024 * 1024
MAX_FUNCTIONS = 65536
MAX_INSTRUCTIONS = 262144
CORE = b'\x00asm\x01\x00\x00\x00'
COMPONENT = b'\x00asm\x0d\x00\x01\x00'
STATES = {'potentially-reachable', 'statically-unreachable', 'dynamic-unknown'}
REASONS = {'analysis-byte-limit', 'analysis-work-limit', 'unsupported-or-malformed-encoding',
           'table-or-indirect-dispatch', 'no-core-module-observed'}


class UnknownEncoding(ValueError):
    pass


class Budget:
    def __init__(self):
        self.instructions = self.functions = self.modules = self.name_bytes = 0

    def add(self, kind, count, maximum):
        setattr(self, kind, getattr(self, kind) + count)
        if getattr(self, kind) > maximum: raise UnknownEncoding('analysis-work-limit')


class Reader:
    def __init__(self, data, budget):
        self.data, self.at, self.budget = memoryview(data), 0, budget

    def take(self, count):
        end = self.at + count
        if count < 0 or end > len(self.data): raise UnknownEncoding('unsupported-or-malformed-encoding')
        value = self.data[self.at:end]; self.at = end
        return value

    def byte(self): return self.take(1)[0]

    def leb(self, bits=32, signed=False):
        value = 0
        for shift in range(0, bits, 7):
            byte = self.byte(); value |= (byte & 127) << shift
            if not byte & 128:
                used = min(7, bits - shift)
                if signed:
                    high = byte & (127 ^ ((1 << used) - 1))
                    sign = byte & (1 << (used - 1))
                    if high != (127 ^ ((1 << used) - 1) if sign else 0):
                        raise UnknownEncoding('unsupported-or-malformed-encoding')
                elif value >= 1 << bits:
                    raise UnknownEncoding('unsupported-or-malformed-encoding')
                return value
        raise UnknownEncoding('unsupported-or-malformed-encoding')

    def count(self, maximum):
        value = self.leb()
        if value > maximum: raise UnknownEncoding('analysis-work-limit')
        return value

    def name(self):
        size = self.count(4096); self.budget.add('name_bytes', size, 1024 * 1024)
        try: return bytes(self.take(size)).decode('utf-8')
        except UnicodeError: raise UnknownEncoding('unsupported-or-malformed-encoding') from None

    def child(self): return Reader(self.take(self.leb()), self.budget)

    def done(self):
        if self.at != len(self.data): raise UnknownEncoding('unsupported-or-malformed-encoding')


def value_type(reader):
    value = reader.byte()
    if value in (0x63, 0x64): reader.leb(33, True)
    elif value not in (0x7f, 0x7e, 0x7d, 0x7c, 0x7b, 0x70, 0x6f):
        raise UnknownEncoding('unsupported-or-malformed-encoding')


def limits(reader):
    flags = reader.leb()
    if flags & ~3: raise UnknownEncoding('unsupported-or-malformed-encoding')
    reader.leb()
    if flags & 1: reader.leb()


def instructions(reader, *, body=False):
    calls, addresses, dynamic, depth = set(), set(), False, 1
    if body:
        for _ in range(reader.count(4096)):
            reader.count(MAX_FUNCTIONS); value_type(reader)
    while depth:
        reader.budget.add('instructions', 1, MAX_INSTRUCTIONS)
        op = reader.byte()
        if op in (0x02, 0x03, 0x04): reader.leb(33, True); depth += 1
        elif op == 0x0b: depth -= 1
        elif op in (0x0c, 0x0d, 0x20, 0x21, 0x22, 0x23, 0x24): reader.leb()
        elif op == 0x0e:
            for _ in range(reader.count(4096) + 1): reader.leb()
        elif op in (0x10, 0x12): calls.add(reader.leb())
        elif op in (0x11, 0x13): reader.leb(); reader.leb(); dynamic = True
        elif op in (0x14, 0x15): reader.leb(); dynamic = True
        elif op in (0x25, 0x26): reader.leb(); dynamic = True
        elif 0x28 <= op <= 0x3e:
            alignment = reader.leb()
            if alignment >= 64: raise UnknownEncoding('unsupported-or-malformed-encoding')
            reader.leb()
        elif op in (0x3f, 0x40): reader.leb()
        elif op in (0x41, 0x42): reader.leb(32 if op == 0x41 else 64, True)
        elif op in (0x43, 0x44): reader.take(4 if op == 0x43 else 8)
        elif op == 0x1c:
            for _ in range(reader.count(16)): value_type(reader)
        elif op == 0xd0: reader.leb(33, True); dynamic = True
        elif op == 0xd2: addresses.add(reader.leb()); dynamic = True
        elif op in (0xd1, 0xd3): dynamic = True
        elif op == 0xfc:
            sub = reader.leb()
            if 0 <= sub <= 7: pass
            elif sub in (8, 10): reader.leb(); reader.leb()
            elif sub in (9, 11): reader.leb()
            elif 12 <= sub <= 17:
                reader.leb()
                if sub in (12, 14): reader.leb()
                dynamic = True
            else: raise UnknownEncoding('unsupported-or-malformed-encoding')
        elif op in (0x00, 0x01, 0x05, 0x0f, 0x1a, 0x1b) or 0x45 <= op <= 0xc4: pass
        else: raise UnknownEncoding('unsupported-or-malformed-encoding')
        if depth > 256: raise UnknownEncoding('analysis-work-limit')
    return calls, addresses, dynamic


def core_graph(raw, budget):
    reader = Reader(raw, budget)
    if bytes(reader.take(8)) != CORE: raise UnknownEncoding('unsupported-or-malformed-encoding')
    imported, declared, bodies, labels = [], 0, [], {}
    roots = {'invocation': set(), 'initialization': set(), 'callbacks': set()}
    dynamic, seen, reasons = False, set(), set()
    while reader.at < len(reader.data):
        kind, section = reader.byte(), reader.child()
        if kind and kind in seen: raise UnknownEncoding('unsupported-or-malformed-encoding')
        seen.add(kind)
        if kind == 0:
            name = section.name()
            if name == 'name':
                while section.at < len(section.data):
                    sub, names = section.byte(), section.child()
                    if sub == 1:
                        for _ in range(names.count(MAX_FUNCTIONS)):
                            index, label = names.leb(), names.name()
                            if index in labels: raise UnknownEncoding('unsupported-or-malformed-encoding')
                            labels[index] = label
                        names.done()
            section.at = len(section.data)
        elif kind == 2:
            for _ in range(section.count(MAX_FUNCTIONS)):
                module, name, sort = section.name(), section.name(), section.byte()
                if sort == 0: section.leb(); imported.append(module + '/' + name)
                elif sort == 1: value_type(section); limits(section); dynamic = True
                elif sort == 2: limits(section)
                elif sort == 3: value_type(section); section.byte()
                elif sort == 4: section.byte(); section.leb()
                else: raise UnknownEncoding('unsupported-or-malformed-encoding')
        elif kind == 3:
            declared = section.count(MAX_FUNCTIONS)
            for _ in range(declared): section.leb()
        elif kind == 5:
            for _ in range(section.count(128)): limits(section)
        elif kind == 6:
            for _ in range(section.count(MAX_FUNCTIONS)):
                value_type(section); section.byte()
                _, addresses, indirect = instructions(section)
                roots['callbacks'].update(addresses); dynamic |= indirect
        elif kind == 7:
            for _ in range(section.count(MAX_FUNCTIONS)):
                name, sort, index = section.name(), section.byte(), section.leb()
                if sort == 0: roots['invocation'].add(index)
        elif kind == 8: roots['initialization'].add(section.leb())
        elif kind == 10:
            for _ in range(section.count(MAX_FUNCTIONS)):
                function = section.child()
                try:
                    calls, addresses, indirect = instructions(function, body=True); function.done()
                except UnknownEncoding as error:
                    calls, addresses, indirect = set(), set(), True; reasons.add(str(error))
                bodies.append(calls); roots['callbacks'].update(addresses); dynamic |= indirect
        elif kind in (4, 9):
            # Tables/element segments can introduce host-visible callback
            # references. Do not certify a closed graph from their mere presence.
            dynamic = True; section.at = len(section.data)
        elif kind in (1, 11, 12, 13): section.at = len(section.data)
        else: raise UnknownEncoding('unsupported-or-malformed-encoding')
        section.done()
    if len(bodies) != declared: raise UnknownEncoding('unsupported-or-malformed-encoding')
    total = len(imported) + declared; budget.add('functions', total, MAX_FUNCTIONS)
    all_indices = set(range(total)); edges = {index + len(imported): row for index, row in enumerate(bodies)}
    if any(not row <= all_indices for row in [*roots.values(), *edges.values()]):
        raise UnknownEncoding('unsupported-or-malformed-encoding')
    if dynamic: reasons.add('table-or-indirect-dispatch')
    reachable = {}
    for phase, initial in roots.items():
        pending, selected = deque(initial), set(initial)
        while pending:
            for target in edges.get(pending.popleft(), ()):
                if target not in selected: selected.add(target); pending.append(target)
        for index in selected: reachable.setdefault(index, set()).add(phase)
    return {'functions': total, 'imports': imported, 'labels': labels, 'reachable': reachable,
            'closed': not dynamic and not reasons, 'reasons': reasons}


def graphs(raw, budget, depth=0):
    if depth > 8: raise UnknownEncoding('analysis-work-limit')
    if bytes(raw[:8]) == CORE:
        budget.add('modules', 1, 64)
        return [core_graph(raw, budget)]
    reader = Reader(raw, budget)
    if bytes(reader.take(8)) != COMPONENT: raise UnknownEncoding('unsupported-or-malformed-encoding')
    result = []
    while reader.at < len(reader.data):
        kind, section = reader.byte(), reader.child()
        if kind in (1, 4): result.extend(graphs(section.data, budget, depth + 1))
        elif kind > 12: raise UnknownEncoding('unsupported-or-malformed-encoding')
    return result


def safe_symbol(name, fallback):
    try:
        compatibility.token(name)
        require(re.fullmatch(r'[A-Za-z0-9_.+\[\]-]+(?:::[A-Za-z0-9_.+\[\]-]+)*', name),
                'emitted-symbol-private-path')
        return name, False
    except ValueError: return fallback, True


def analyze(component, source_digest, runtime_profile, host_profile, *, graph_digest=None, recipe_digest=None):
    sha(source_digest); compatibility.token(runtime_profile); compatibility.token(host_profile)
    for item in (graph_digest, recipe_digest):
        if item is not None: sha(item)
    reasons, findings, omitted, redacted = set(), [], 0, 0
    budget = Budget(); modules = []
    if len(component) > MAX_ANALYSIS_BYTES: reasons.add('analysis-byte-limit')
    else:
        try: modules = graphs(component, budget)
        except UnknownEncoding as error: reasons.add(str(error))
    if not modules and not reasons: reasons.add('no-core-module-observed')
    for ordinal, module in enumerate(modules):
        reasons.update(module['reasons'])
        for index in range(module['functions']):
            if len(findings) == MAX_FINDINGS: omitted += 1; continue
            fallback = f'core-{ordinal}.function-{index}'
            name = module['labels'].get(index, module['imports'][index] if index < len(module['imports']) else fallback)
            symbol, was_redacted = safe_symbol(name, fallback); redacted += int(was_redacted)
            phases = sorted(module['reachable'].get(index, ()))
            state = 'potentially-reachable' if phases else 'statically-unreachable' if module['closed'] else 'dynamic-unknown'
            findings.append({'module': ordinal, 'function': index, 'symbol': symbol, 'state': state,
                             'phases': phases, 'moduleGraph': 'closed' if module['closed'] else 'incomplete',
                             'sourceLocation': 'not-observed', 'apiElimination': 'not-established'})
    value = {'schemaVersion': SCHEMA, 'sourceDigest': source_digest, 'componentDigest': digest(component),
        'runtimeProfile': runtime_profile, 'hostAbiProfile': host_profile, 'graphDigest': graph_digest,
        'recipeDigest': recipe_digest, 'rootScope': 'all-core-exports-starts-addressable-callbacks',
        'selectedExportMapping': 'conservative-superset', 'libraryReachability': 'unknown',
        'initializationExecution': 'not-executed', 'dynamicDispatch': 'unknown' if reasons else 'closed-core-subset',
        'analysisReasons': sorted(reasons), 'findings': findings, 'omittedFindings': omitted,
        'redactedSymbols': redacted, 'modulesObserved': len(modules), 'workerDrain': 'unproven',
        'qualification': 'unknown', 'authority': 'none'}
    value['identity'] = digest(encode(value))
    return validate(value, source=source_digest, component=digest(component), runtime=runtime_profile, host=host_profile)


def validate(value, *, source=None, component=None, runtime=None, host=None, graph=..., recipe=None):
    members(value, {'schemaVersion', 'sourceDigest', 'componentDigest', 'runtimeProfile', 'hostAbiProfile',
        'graphDigest', 'recipeDigest', 'rootScope', 'selectedExportMapping', 'libraryReachability',
        'initializationExecution', 'dynamicDispatch', 'analysisReasons', 'findings', 'omittedFindings',
        'redactedSymbols', 'modulesObserved', 'workerDrain', 'qualification', 'authority', 'identity'})
    require(value['schemaVersion'] == SCHEMA, 'emitted-reachability-version')
    for name in ('sourceDigest', 'componentDigest', 'identity'): sha(value[name])
    for name in ('graphDigest', 'recipeDigest'):
        if value[name] is not None: sha(value[name])
    compatibility.token(value['runtimeProfile']); compatibility.token(value['hostAbiProfile'])
    require((value['rootScope'], value['selectedExportMapping'], value['libraryReachability'], value['initializationExecution'],
             value['workerDrain'], value['qualification'], value['authority']) ==
            ('all-core-exports-starts-addressable-callbacks', 'conservative-superset', 'unknown', 'not-executed', 'unproven', 'unknown', 'none'),
            'emitted-reachability-cannot-certify-api-or-execution')
    require(isinstance(value['analysisReasons'], list) and set(value['analysisReasons']) <= REASONS
            and len(set(value['analysisReasons'])) == len(value['analysisReasons']), 'emitted-reachability-reasons')
    require(value['dynamicDispatch'] == ('unknown' if value['analysisReasons'] else 'closed-core-subset'), 'emitted-reachability-dynamic-state')
    integer(value['modulesObserved'], 0, 64); integer(value['omittedFindings'], 0, MAX_FUNCTIONS)
    integer(value['redactedSymbols'], 0, MAX_FINDINGS)
    require(isinstance(value['findings'], list) and len(value['findings']) <= MAX_FINDINGS, 'emitted-reachability-finding-limit')
    seen = set()
    for row in value['findings']:
        members(row, {'module', 'function', 'symbol', 'state', 'phases', 'moduleGraph', 'sourceLocation', 'apiElimination'})
        integer(row['module'], 0, value['modulesObserved'] - 1); integer(row['function'], 0, MAX_FUNCTIONS - 1)
        require((row['module'], row['function']) not in seen, 'emitted-reachability-duplicate-function')
        seen.add((row['module'], row['function']))
        require(safe_symbol(row['symbol'], 'redacted')[0] == row['symbol'] and row['state'] in STATES,
                'emitted-reachability-symbol-or-state')
        require(isinstance(row['phases'], list) and set(row['phases']) <= {'invocation', 'initialization', 'callbacks'}
                and len(row['phases']) == len(set(row['phases'])), 'emitted-reachability-phase')
        require(row['moduleGraph'] in {'closed', 'incomplete'}
                and bool(row['phases']) == (row['state'] == 'potentially-reachable')
                and (row['state'] != 'statically-unreachable' or row['moduleGraph'] == 'closed'),
                'emitted-reachability-state-evidence')
        require((row['sourceLocation'], row['apiElimination']) == ('not-observed', 'not-established'), 'emitted-reachability-attribution')
    require(len(encode(value)) <= MAX_BYTES and digest(encode({k: v for k, v in value.items() if k != 'identity'})) == value['identity'],
            'emitted-reachability-identity-or-size')
    for expected, actual, label in ((source, value['sourceDigest'], 'source'), (component, value['componentDigest'], 'component'),
                                  (runtime, value['runtimeProfile'], 'runtime'), (host, value['hostAbiProfile'], 'host'),
                                  (recipe, value['recipeDigest'], 'recipe')):
        if expected is not None: require(expected == actual, 'emitted-reachability-stale-' + label)
    if graph is not ...: require(graph == value['graphDigest'], 'emitted-reachability-stale-graph')
    return value


def emit(output, component, source, runtime, host, *, graph=None, recipe=None):
    value = analyze(component, source, runtime, host, graph_digest=graph, recipe_digest=recipe)
    path = output / 'compatibility-reachability.json'
    if path.exists() or path.is_symlink():
        existing = read(read_file(path, MAX_BYTES), source=source, component=digest(component), runtime=runtime,
                        host=host, graph=graph, recipe=recipe)
        require(existing == value, 'emitted-reachability-stale-analysis')
    else:
        write_json(path, value)
    return value


def read(raw, **bindings): return validate(decode(raw, MAX_BYTES), **bindings)


def present(value):
    validate(value)
    lines = [f"Emitted core analysis: {value['modulesObserved']} module(s); dynamic dispatch {value['dynamicDispatch']}.",
             'Core export roots are a conservative superset; library/API reachability remains unknown.',
             'Initialization was not executed; worker drain remains unproven.']
    lines.extend(f"{row['symbol']}: {row['state']} ({','.join(row['phases']) or 'no observed root path'})."
                 for row in value['findings'])
    if value['omittedFindings']: lines.append(f"Additional core functions omitted: {value['omittedFindings']}.")
    if value['analysisReasons']: lines.append('Analysis limits: ' + ', '.join(value['analysisReasons']) + '.')
    return '\n'.join(lines) + '\n'


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--context', type=Path, help='Bind presentation to the current compatibility context')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    value = read(read_file(args.report, MAX_BYTES))
    if args.context is not None:
        from tools import guest_compatibility_context
        selected = guest_compatibility_context.read(read_file(args.context, 65536))
        validate(value, source=selected['sourceDigest'], component=selected['componentDigest'],
                 runtime=selected['standardRuntime'].get('profile', 'not-observed'), host=selected['hostAbiProfile'])
    print(encode(value).decode().rstrip() if args.json else present(value), end='\n' if args.json else '')
    return 0


if __name__ == '__main__': raise SystemExit(main())
