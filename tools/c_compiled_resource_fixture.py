"""Ordinary C23 #embed from an outside transitive captured resource artifact."""
from pathlib import Path

from tools import application_dependencies as dependencies
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import read_json, write_json

PAYLOADS = {'message.txt': 'Gr\u00fc\u00dfe'.encode(), 'data.bin': bytes((0, 255, 65, 128)), 'empty.bin': b''}
DECLARATIONS = (
    {'path': 'data/utf8.txt', 'source': 'message.txt', 'mediaType': 'text/plain'},
    {'path': 'data/binary.bin', 'source': 'data.bin', 'mediaType': 'application/octet-stream'},
    {'path': 'data/alias.bin', 'source': 'data.bin', 'mediaType': 'application/octet-stream'},
    {'path': 'data/empty.bin', 'source': 'empty.bin', 'mediaType': 'application/octet-stream'})
CASES = (('utf8', 'compiled UTF8|Gr\u00fc\u00dfe'), ('binary', 'binary:00ff4180'),
         ('empty', 'empty:0'), ('shared', 'shared:00ff4180'), ('missing', 'missing:absent'), ('fresh', 'fresh:1'))
LIBRARY = r'''#include "compiled_resource.h"
#include <string.h>
static const unsigned char text[] = {
#embed "message.txt" suffix(,0)
};
static const unsigned char binary[] = {
#embed "data.bin"
};
static const unsigned char alias[] = {
#embed "data.bin"
};
static const unsigned char empty[] = {
#embed "empty.bin" if_empty(0)
};
#if __has_embed("empty.bin") != __STDC_EMBED_EMPTY__
#error "captured empty resource changed"
#endif
#if __has_embed("missing.bin") != __STDC_EMBED_NOT_FOUND__
#error "uncaptured missing resource unexpectedly present"
#endif
static unsigned initialized, calls;
__attribute__((constructor)) static void initialize_library(void) { ++initialized; }
int compiled_resource(unsigned mode, char output[128]) {
    if (initialized != 1 || ++calls != 1 || sizeof(text) != 8 || sizeof(binary) != 4
        || memcmp(binary, alias, sizeof(binary)) || binary[0] != 0 || binary[1] != 255
        || binary[2] != 65 || binary[3] != 128 || sizeof(empty) != 1 || empty[0] != 0) return 0;
    if (mode == 0) return 1;
    if (mode == 1) { memcpy(output, "compiled UTF8|", 14); memcpy(output + 14, text, sizeof(text)); return 1; }
    if (mode == 2 || mode == 4) {
        static const char digits[] = "0123456789abcdef";
        memcpy(output, mode == 2 ? "binary:" : "shared:", 7);
        for (unsigned i = 0; i < sizeof(binary); ++i) {
            output[7 + 2*i] = digits[binary[i] >> 4]; output[8 + 2*i] = digits[binary[i] & 15];
        }
        output[15] = 0; return 1;
    }
    if (mode == 3) { memcpy(output, "empty:0", sizeof("empty:0")); return 1; }
    if (mode == 5) { memcpy(output, "missing:absent", sizeof("missing:absent")); return 1; }
    if (mode == 6) { memcpy(output, "fresh:0", sizeof("fresh:0")); output[6] += calls; return 1; }
    if (mode == 7) __builtin_trap();
    if (mode == 8) { volatile unsigned consumed = 0; for (;;) consumed += binary[consumed % sizeof(binary)]; }
    return 0;
}
'''


def prepare(project: Path) -> dict:
    outside = project.parent / 'outside-compiled-resource-library'
    library, resource = outside / 'library', outside / 'data'
    library.mkdir(parents=True); resource.mkdir()
    (library / 'compiled_resource.h').write_text('int compiled_resource(unsigned mode, char output[128]);\n', encoding='ascii')
    (library / 'compiled_resource.c').write_text(LIBRARY, encoding='ascii')
    for name, payload in PAYLOADS.items():
        (resource / name).write_bytes(payload)
    configuration = read_json(project / 'capsule-project.json')
    configuration['languageStandard'] = 'c23'
    (project / 'capsule-project.json').write_bytes(canonical(configuration))
    declaration = {'formatVersion': 1, 'language': 'c',
        'selection': {'target': 'wasm32-wasi', 'languageStandard': 'c23'}, 'nativeLocks': [],
        'artifacts': [
            {'id': 'outside-owner/compiled-library/1', 'role': 'application', 'format': 'directory',
             'mount': 'dependencies/compiled-library', 'source': {'path': '../' + outside.name + '/library'},
             'dependencies': ['outside-owner/raw-resource/1'],
             'metadata': {'cSources': ['compiled_resource.c'], 'includeDirectories': ['.']}},
            {'id': 'outside-owner/raw-resource/1', 'role': 'resource', 'format': 'directory',
             'mount': 'dependencies/resource-data', 'source': {'path': '../' + outside.name + '/data'},
             'dependencies': [], 'metadata': {'resources': list(DECLARATIONS)}}], 'transformations': []}
    write_json(project / dependencies.MANIFEST, declaration)
    (project / dependencies.LOCK).write_bytes(canonical(dependencies.capture(project)))
    source = project / 'src/main.c'
    original = source.read_text(encoding='utf-8')
    opening = '                                         probe_string_t *error) {'
    if original.count(opening) != 1:
        raise ValueError('c-compiled-resource-requires-original-greeting-template')
    selectors = (*[name for name, _ in CASES], 'trap', 'fuel')
    branches = ''.join(f'    if (name->len == {len("resource:" + name)} && memcmp(name->ptr, "resource:{name}", name->len) == 0) mode = {i};\n'
                       for i, name in enumerate(selectors, 1))
    body = '\n    unsigned mode = 0;\n    char resource_output[128] = {0};\n' + branches + '''
    if (!compiled_resource(mode, resource_output)) {
        probe_string_free(name); lsf_text_error(error, "compiled-resource-probe-failed"); return false;
    }
    if (mode) { probe_string_free(name); probe_string_dup(value, resource_output); return true; }
'''
    source.write_text('#include "compiled_resource.h"\n' + original.replace(opening, opening + body), encoding='utf-8')
    originals = {str(path.relative_to(outside)).replace('\\', '/'): digest(path.read_bytes())
                 for directory in (library, resource) for path in directory.iterdir()}
    for directory in (library, resource):
        for path in directory.iterdir(): path.unlink()
        directory.rmdir()
    outside.rmdir()
    return {'languageStandard': 'c23', 'originalsRemoved': not outside.exists(), 'originalFiles': originals,
            'lockDigest': digest((project / dependencies.LOCK).read_bytes()),
            'resources': [{**row, 'digest': digest(PAYLOADS[row['source']]), 'size': len(PAYLOADS[row['source']])}
                          for row in DECLARATIONS], 'cases': list(CASES)}


def probe(client, target, accounting, result, population):
    from tools.phase2_operator_process import require
    from tools.rust_capsule_node import assert_value, call, provider_idle, sample
    rows, recovery = [], []
    for ordinal, (name, expected) in enumerate(CASES):
        observed = call(client, target, 'greeting', 'greet', ['resource:' + name], 'c-resource-' + str(ordinal))
        result['invocations'].append(observed)
        assert_value(client, observed, [{'ok': expected}])
        rows.append({'case': name, 'activation': observed['activation'], 'decoded': observed['decoded']})
        result['providerIdle'].append(provider_idle(client))
        result['samples'].append(sample(client, accounting, 'c-resource-' + name + '-retired', population))
    for mode, code in (('trap', 'guest-trap'), ('fuel', 'resource-exhausted')):
        bounded = {**target, 'budget': {**target['budget'], 'cpuFuel': min(10_000_000, target['budget']['cpuFuel'])}}
        failed = call(client, bounded, 'greeting', 'greet', ['resource:' + mode], 'c-resource-' + mode)
        result['invocations'].append(failed)
        require(failed['exitCode'] == 4 and failed['processReaped'] and failed['response']['outcomeKnown']
                and failed['response']['error']['code'] == code
                and failed['response']['data']['terminalState'] == code.replace('-', '_'), 'c-resource-failure-shape')
        require(int(failed['response']['data']['consumption']['peakMemoryBytes']) <= target['budget']['memoryBytes'],
                'c-resource-failure-memory-bound')
        if mode == 'fuel':
            require(int(failed['response']['data']['consumption']['cpuFuel']) == bounded['budget']['cpuFuel'],
                    'c-resource-original-fuel-bound')
        result['samples'].append(sample(client, accounting, 'c-resource-' + mode + '-retired', population))
        fresh = call(client, target, 'greeting', 'greet', ['resource:utf8'], 'c-resource-' + mode + '-fresh')
        result['invocations'].append(fresh)
        assert_value(client, fresh, [{'ok': CASES[0][1]}])
        result['samples'].append(sample(client, accounting, 'c-resource-' + mode + '-fresh-retired', population))
        recovery.append({'case': mode, 'failure': failed, 'freshInvocation': fresh})
    result['cCompiledResourceCases'] = rows
    result['cCompiledResourceRecovery'] = recovery
