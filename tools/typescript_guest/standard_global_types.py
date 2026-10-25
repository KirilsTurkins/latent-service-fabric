"""Compose finite runtime declarations with a verified standard Node type provider.

This changes compiler declarations only. It installs no runtime globals/APIs,
constructor implementation, authority or package-specific application dispatch.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from tools.rust_capsule_project import digest, read_file
from tools.build_snapshot import canonical

PROFILE = 'lsf-captured-node-global-types-v1'
RECEIPT = 'typescript-standard-global-types.json'
RUNTIME = 'sdk/typescript-guest/activation/runtime-globals.d.ts'
CLOCK = 'sdk/typescript-guest/activation/clock-globals.d.ts'
PROVIDER = '@types/node/'
FILES = ('package.json', 'index.d.ts', 'web-globals/abortcontroller.d.ts',
         'web-globals/performance.d.ts', 'perf_hooks.d.ts')
INLINE_FILES = tuple(name for name in FILES if name != 'web-globals/performance.d.ts')
INLINE_LAYOUT = 'inline-performance-value-v1'
INLINE_PERFORMANCE_IMPORT = '''    import {
        performance as _performance,
        PerformanceEntry as _PerformanceEntry,
        PerformanceMark as _PerformanceMark,
        PerformanceMeasure as _PerformanceMeasure,
        PerformanceObserver as _PerformanceObserver,
        PerformanceObserverEntryList as _PerformanceObserverEntryList,
        PerformanceResourceTiming as _PerformanceResourceTiming,
    } from "perf_hooks";'''
SIGNAL = """declare var AbortSignal: {
    abort(reason?: any): AbortSignal;
    timeout(milliseconds: number): AbortSignal;
    any(signals: Iterable<AbortSignal>): AbortSignal;
};"""
CONTROLLER = """declare class AbortController {
    readonly signal: AbortSignal;
    abort(reason?: any): void;
}"""
PERFORMANCE = """declare var performance: {
    now(): number;
    readonly timeOrigin: number;
};"""


def identity(data):
    return {'digest': digest(data), 'size': len(data)}


def select(closure):
    from tools.application_dependencies import Closure, VerifiedInputs
    if not isinstance(closure, (Closure, VerifiedInputs)):
        raise ValueError('standard-global-types-require-verified-closure')
    roots = [row for row in closure.lock['artifacts'] if row['metadata'].get('assetType') == 'selected-node-modules']
    if len(roots) != 1:
        raise ValueError('standard-global-types-module-root')
    tree = roots[0]
    files = {row['path']: row for row in tree['files']}
    providers = [name for name in files if name == PROVIDER+'package.json'
                 or name.endswith('/node_modules/'+PROVIDER+'package.json')]
    partial = any(name.startswith(PROVIDER) for name in files)
    if not providers and not partial:
        return None
    separate = PROVIDER+'web-globals/performance.d.ts' in files
    required = FILES if separate else INLINE_FILES
    if providers != [PROVIDER+'package.json'] or not all(PROVIDER+name in files for name in required):
        raise ValueError('standard-global-types-ambiguous-or-incomplete-provider')
    selected = [files[PROVIDER+name] for name in required]
    if any(type(row['size']) is not int or not 0 < row['size'] <= 1024**2 for row in selected) or sum(row['size'] for row in selected) > 2*1024**2:
        raise ValueError('standard-global-types-provider-bound')
    content = {}
    for name in required:
        row = files[PROVIDER+name]
        data = (read_file(closure.work/tree['mount']/PROVIDER/name, 1024**2)
                if isinstance(closure, Closure) else closure.store.get(row['digest'], row['size']))
        if identity(data) != {key: files[PROVIDER+name][key] for key in ('digest', 'size')}:
            raise ValueError('standard-global-types-provider-mutated')
        content[name] = data
    package = json.loads(content['package.json'])
    if not all(type(package.get(key)) is str and 0 < len(package[key]) <= 512 for key in ('name','version')):
        raise ValueError('standard-global-types-provider-identity')
    # The maintained compiler is TypeScript 7. A different active entrypoint
    # cannot be silently composed using the unselected index declarations.
    versions = package.get('typesVersions', {})
    if (package.get('types') != 'index.d.ts' or package.get('exports') is not None
            or type(versions) is not dict or any(not re.fullmatch(r'<=([0-9]+)\.[0-9]+', key)
                or int(key[2:].split('.')[0]) >= 7 for key in versions)):
        raise ValueError('standard-global-types-ambiguous-provider-entrypoint')
    index = content['index.d.ts'].decode('utf-8')
    for name in required[2:]:
        if index.count('/// <reference path="'+name+'" />') != 1:
            raise ValueError('standard-global-types-incomplete-provider-reference')
    inline_marker = '_performance' in content['perf_hooks.d.ts'].decode('utf-8')
    if separate:
        if inline_marker:
            raise ValueError('standard-global-types-mixed-performance-layout')
    else:
        if 'web-globals/performance.d.ts' in index:
            raise ValueError('standard-global-types-incomplete-provider-reference')
        inline_performance_value(content['perf_hooks.d.ts'])
    return {'inputIdentity': closure.identity, 'mount': tree['mount'],
        'package': {key:package[key] for key in ('name','version')}, 'content': content,
        'files': [{'path': tree['mount']+'/'+PROVIDER+name, **identity(content[name])} for name in required]}


def inline_performance_value(data):
    """One captured inline declaration grammar, with its real value alias."""
    source = data.decode('utf-8').replace('\r\n','\n')
    anchor = '        var performance: '
    if (source.count(INLINE_PERFORMANCE_IMPORT) != 1 or source.count(anchor) != 1
            or len(re.findall(r'\b_performance\b', source)) != 2):
        raise ValueError('standard-global-types-unreviewed-inline-performance')
    tail = source.split(anchor,1)[1][:8192]
    depth = 0
    for index, character in enumerate(tail):
        if character == '{': depth += 1
        elif character == '}': depth -= 1
        elif character == ';' and depth == 0:
            value = tail[:index]
            if ' '.join(value.split()) != ('typeof globalThis extends { onmessage: any; '
                    'performance: infer T; } ? T : typeof _performance'):
                raise ValueError('standard-global-types-unreviewed-inline-performance')
            return value.replace('typeof _performance', 'typeof import("node:perf_hooks").performance')
        if depth < 0: break
    raise ValueError('standard-global-types-provider-variable-bound')


def node_variable(data, name):
    source = data.decode('utf-8').replace('\r\n','\n')
    anchor = '    var '+name+': '
    if source.count(anchor) != 1:
        raise ValueError('standard-global-types-ambiguous-provider-variable')
    tail = source.split(anchor,1)[1][:8192]
    depth = 0
    for index, character in enumerate(tail):
        if character == '{': depth += 1
        elif character == '}': depth -= 1
        elif character == ';' and depth == 0:
            value = tail[:index]
            expected = 'typeof globalThis extends { onmessage: any; '+name+': infer T } ? T'
            if not value.startswith(expected) or any(token in value for token in ('//','/*',"'",'"')):
                raise ValueError('standard-global-types-unreviewed-provider-variable')
            return value
        if depth < 0: break
    raise ValueError('standard-global-types-provider-variable-bound')


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError('standard-global-types-owned-preimage-drift')
    return source.replace(before, after, 1)


def compose(provider, runtime, clock):
    if provider is None:
        return runtime, clock, None  # Exact old/default bytes, no new provider.
    original_runtime, original_clock = runtime, clock
    runtime = runtime.decode('utf-8').replace('\r\n','\n')
    clock = clock.decode('utf-8').replace('\r\n','\n') if clock is not None else None
    abort = provider['content']['web-globals/abortcontroller.d.ts']
    signal = node_variable(abort, 'AbortSignal')
    controller = node_variable(abort, 'AbortController')
    for name, value in (('AbortSignal', signal), ('AbortController', controller)):
        if value.count('prototype: '+name+';') != 1 or value.count('new(): '+name+';') != 1:
            raise ValueError('standard-global-types-unreviewed-constructor')
    runtime = replace_once(runtime, SIGNAL, 'declare var AbortSignal: '+signal+';')
    finite_controller = CONTROLLER.replace('declare class', 'interface')
    runtime = replace_once(runtime, CONTROLLER, finite_controller+'\ndeclare var AbortController: '+controller+';')
    runtime = '/// <reference types="node" />\n'+runtime
    if clock is not None:
        if 'web-globals/performance.d.ts' in provider['content']:
            perf_source = provider['content']['web-globals/performance.d.ts']
            if perf_source.decode('utf-8').count('import * as perf_hooks from "node:perf_hooks";') != 1:
                raise ValueError('standard-global-types-unreviewed-performance-import')
            performance = node_variable(perf_source, 'performance')
            if performance.count('perf_hooks.Performance') != 1:
                raise ValueError('standard-global-types-unreviewed-performance-type')
            # Same captured module type, with its local namespace alias made explicit.
            performance = performance.replace('perf_hooks.Performance', 'import("node:perf_hooks").Performance')
        else:
            performance = inline_performance_value(provider['content']['perf_hooks.d.ts'])
        finite_performance = PERFORMANCE.replace('declare var performance: {', 'interface Performance {').removesuffix(';')
        clock = replace_once(clock, PERFORMANCE, finite_performance+'\ndeclare var performance: '+performance+';')
    runtime = runtime.encode()
    clock = clock.encode() if clock is not None else None
    receipt = {'schemaVersion':'latent.typescript.standard-global-types.v1','profile':PROFILE,
        'authority':'none','qualification':'unknown','runtimeApiChange':False,
        'scope':'provided-Node-compile-time-types; finite-runtime-profile-unchanged',
        'reason':'Compose finite instance contracts with exact captured standard constructor/value declarations; no runtime API inference',
        'inputIdentity':provider['inputIdentity'],'provider':provider['package'],'providerFiles':provider['files'],
        'originals':{RUNTIME:identity(original_runtime)},
        'derived':{'activation-runtime-globals.d.ts':{**identity(runtime),'text':runtime.decode()}}}
    if clock is not None:
        receipt['originals'][CLOCK] = identity(original_clock)
        receipt['derived']['clock-runtime-globals.d.ts'] = {**identity(clock),'text':clock.decode()}
    if 'web-globals/performance.d.ts' not in provider['content']:
        receipt['providerLayout'] = INLINE_LAYOUT
    if len(canonical(receipt)) > 65536:
        raise ValueError('standard-global-types-receipt-bound')
    return runtime, clock, receipt


def retain(compiled, output, expected):
    path = compiled/RECEIPT
    if expected is None:
        if path.exists(): raise ValueError('standard-global-types-unselected-receipt')
        return (), []
    raw = read_file(path,65536)
    if canonical(json.loads(raw)) != canonical(expected):
        raise ValueError('standard-global-types-retained-selection-drift')
    if (output/RECEIPT).exists():
        if read_file(output/RECEIPT,65536) != raw:
            raise ValueError('standard-global-types-attempted-selection-drift')
    else:
        (output/RECEIPT).write_bytes(raw)
    return ((RECEIPT,'asset','application/vnd.latent.typescript.standard-global-types.v1+json'),), [
        {'name':'typescript-standard-global-types','digest':digest(raw),'size':len(raw)}]
