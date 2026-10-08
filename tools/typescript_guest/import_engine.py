"""Explicit source-owned asynchronous import candidate; no API qualification."""
from __future__ import annotations
import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once

IMPORT_PROFILE = 'spidermonkey-activation-promises-clocks-imports-v1'
NATIVE_IMPORT_SOURCES = ('native_import_lifecycle.h', 'native_imports.h',
                         'broker_import_accounting.h', 'native_import_bridge.cpp',
                         'native_import_values.h','native_import_globals.cpp',
                         'async_import_descriptor.rs','async_import_splice.rs')
SOURCE_PREIMAGES = {
    'crates/spidermonkey-embedding-splicer/src/bindgen.rs':
        'd0704346724cfc41cbd35f958361736bc1c1aff801424c94d69565b8aa7d7ed3',
    'crates/spidermonkey-embedding-splicer/src/splice.rs':
        'abb62bc9580a9f8b8e8026950f6bb285f64373a905ae770718612508dafa301a',
}


def extend_native_import_source(base_source: dict[str,bytes], native: dict[str,bytes]) -> tuple[dict[str,bytes],dict]:
    """Derived private compiler source; original carriers remain immutable."""
    if set(native)!=set(NATIVE_IMPORT_SOURCES):
        raise ValueError('exact-private-async-import-source-required')
    install='StarlingMonkey/builtins/install_builtins.cpp'
    if install not in base_source:
        raise ValueError('unreviewed-or-already-extended-import-source')
    for name,raw in native.items():
        if 'lsf/'+name in base_source and base_source['lsf/'+name]!=raw:
            raise ValueError('native-import-header-source-mismatch:'+name)
    original=base_source[install]
    source=replace_once(original,b'#include "extension-api.h"\n',
        b'#include "extension-api.h"\n#include "native_engine.h"\n','private-import-builtin-header')
    source=replace_once(source,
        b'  return lsf::typescript::activation::install_clock_globals(engine->cx(), engine->global());\n',
        b'  return lsf::typescript::activation::install_clock_globals(engine->cx(), engine->global()) &&\n'
        b'         lsf::typescript::activation::install_import_bridge(engine->cx(), engine->global());\n',
        'private-import-bridge-before-application')
    result=dict(base_source)
    result[install]=source
    result.update({'lsf/'+name:raw for name,raw in native.items()})
    return result, {'profile':IMPORT_PROFILE,'originalSource':identity(base_source),'derivedSource':identity(result),
        'nativeSource':identity(native),'compilerSourceFilesToAdd':['lsf/native_import_bridge.cpp','lsf/native_import_globals.cpp'],
        'activationInterfaceChanged':False,'clockAuthorityGranted':False,'qualification':'unknown',
        'apiSupport':'not-evaluated','signedLSFComponentQualified':False}


def source_selection(original: dict[str, bytes], native: dict[str, bytes]) -> dict:
    """Authenticate source preparation without inferring implementation/build."""
    if set(original) != set(SOURCE_PREIMAGES) or set(native) != set(NATIVE_IMPORT_SOURCES):
        raise ValueError('exact-async-import-source-selection-required')
    for name, raw in original.items():
        if hashlib.sha256(raw).hexdigest() != SOURCE_PREIMAGES[name]:
            raise ValueError('unreviewed-original-async-import-source:'+name)
    return {'profile': IMPORT_PROFILE, 'originalSource': identity(original),
            'nativeSource': identity(native), 'activationInterfaceChanged': False,
            'clockAuthorityGranted': False, 'qualification': 'unknown',
            'apiSupport': 'not-evaluated', 'signedLSFComponentQualified': False}


def async_imports(graph: dict, world: str) -> list[dict]:
    """Select only actual parser async function kinds, including resources.

    Numeric graph identities are retained for the native ABI generator; no
    name suffix, package classification or HostABI recognition selects async.
    """
    from tools.typescript_guest.runtime_profile import find_world, interface_id
    selected = find_world(graph, world)
    result = []
    def add(interface, function):
        kind = function['kind']
        if isinstance(kind, str):
            if kind not in ('freestanding','async-freestanding'):
                raise ValueError('unknown-async-import-function-kind')
            enabled = kind == 'async-freestanding'
        elif isinstance(kind, dict) and len(kind) == 1:
            if next(iter(kind)) not in ('method','static','constructor','async-method','async-static'):
                raise ValueError('unknown-async-import-function-kind')
            enabled = next(iter(kind)) in ('async-method', 'async-static')
        else:
            raise ValueError('unknown-async-import-function-kind')
        if enabled:
            result.append({'interface': interface, 'function': function['name'],
                           'kind': kind, 'params': function['params'], 'result': function['result']})
    for name, item in selected['imports'].items():
        if set(item) == {'function'}:
            add('$root', item['function'])
        elif set(item) == {'interface'}:
            index = item['interface']['id']
            for function in graph['interfaces'][index]['functions'].values():
                add(interface_id(graph, index), function)
        elif set(item) != {'type'}:
            raise ValueError('unknown-async-import-world-item')
    return result
