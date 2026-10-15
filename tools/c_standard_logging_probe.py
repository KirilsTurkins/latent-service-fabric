"""Captured ordinary C stdio calls and bounded signed-node error probes."""
from pathlib import Path

from tools import application_dependencies as dependencies
from tools.build_snapshot import canonical, digest
from tools.c_guest.standard_facilities import LOGGING_PROFILE
from tools.rust_capsule_project import read_json, write_json

CASES = ('bad-fd', 'invalid-utf8', 'too-many-vectors', 'too-large', 'invalid-memory',
         'zero', 'budget', 'seek', 'descriptor', 'stderr', 'split-utf8')
LIBRARY = r'''#include "log_probe.h"
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <wasi/api.h>
extern int32_t __imported_wasi_snapshot_preview1_fd_write(int32_t, int32_t, int32_t, int32_t);
static int initializer_accepted;
__attribute__((constructor)) static void ordinary_library_initializer(void) {
    initializer_accepted = printf("ordinary library initializer") >= 0;
}
int standard_log_probe(unsigned mode) {
    if (mode == 12) return !initializer_accepted;
    if (!initializer_accepted) return 0;
    unsigned char bytes[4097]; memset(bytes, 'a', sizeof(bytes));
    __wasi_ciovec_t vector = {.buf = bytes, .buf_len = 1};
    __wasi_size_t written = 99;
    if (mode == 0) {
        return printf("ordinary dependency: %d \xc3\xbc\n", 42) >= 0;
    }
    if (mode == 1) return __wasi_fd_write(0, &vector, 1, &written) == __WASI_ERRNO_BADF && written == 99;
    if (mode == 2) {
        static const unsigned char invalid[][4] = {{0xff}, {0xc0, 0x80}, {0xed, 0xa0, 0x80},
            {0xf4, 0x90, 0x80, 0x80}, {0xe2, 0x82}};
        static const unsigned lengths[] = {1, 2, 3, 4, 2};
        for (unsigned i = 0; i < 5; ++i) {
            vector.buf = invalid[i]; vector.buf_len = lengths[i];
            if (__wasi_fd_write(1, &vector, 1, &written) != __WASI_ERRNO_ILSEQ || written != 99) return 0;
        }
        return 1;
    }
    if (mode == 3) return __wasi_fd_write(1, &vector, 17, &written) == __WASI_ERRNO_INVAL && written == 99;
    if (mode == 4) {
        vector.buf_len = sizeof(bytes);
        return __wasi_fd_write(1, &vector, 1, &written) == __WASI_ERRNO_INVAL && written == 99;
    }
    if (mode == 5) return __imported_wasi_snapshot_preview1_fd_write(1, 0, 1, (int32_t)(uintptr_t)&written) == __WASI_ERRNO_FAULT && written == 99;
    if (mode == 6) return __imported_wasi_snapshot_preview1_fd_write(1, 0, 0, (int32_t)(uintptr_t)&written) == 0 && written == 0;
    if (mode == 7) {
        vector.buf_len = 4096;
        for (unsigned i = 0; i < 64; ++i) {
            __wasi_errno_t result = __wasi_fd_write(1, &vector, 1, &written);
            if (result) return result == __WASI_ERRNO_AGAIN;
        }
        return 0;
    }
    if (mode == 8) {
        __wasi_filesize_t offset = 99;
        return __wasi_fd_seek(1, 0, __WASI_WHENCE_SET, &offset) == __WASI_ERRNO_NOTSUP && offset == 99;
    }
    if (mode == 9) {
        __wasi_fdstat_t state;
        return __wasi_fd_fdstat_get(1, &state) == 0 && state.fs_filetype == __WASI_FILETYPE_UNKNOWN
            && state.fs_rights_base == __WASI_RIGHTS_FD_WRITE && state.fs_rights_inheriting == 0;
    }
    if (mode == 10) return fprintf(stderr, "ordinary dependency error\n") >= 0;
    if (mode == 11) {
        static const unsigned char lead[] = {0xc3}, tail[] = {0xbc, 0, '\n'};
        __wasi_ciovec_t parts[] = {{.buf = lead, .buf_len = sizeof(lead)}, {.buf = tail, .buf_len = sizeof(tail)}};
        return __wasi_fd_write(1, parts, 2, &written) == 0 && written == 4;
    }
    return 0;
}
'''


def prepare(project: Path) -> dict:
    library = project.parent / 'outside-standard-stdio-library'
    library.mkdir()
    (library / 'log_probe.h').write_text('int standard_log_probe(unsigned mode);\n', encoding='utf-8')
    (library / 'log_probe.c').write_text(LIBRARY, encoding='utf-8')
    configuration = read_json(project / 'capsule-project.json')
    configuration['runtimeProfile'] = LOGGING_PROFILE
    configuration['limits']['logBytes'] = 16384
    (project / 'capsule-project.json').write_bytes(canonical(configuration))
    write_json(project / dependencies.MANIFEST, {'formatVersion': 1, 'language': 'c',
        'selection': {'target': 'wasm32-wasi', 'runtimeProfile': LOGGING_PROFILE}, 'nativeLocks': [],
        'artifacts': [{'id': 'outside-owner/stdio-library/2026.10.16', 'role': 'application', 'format': 'directory',
            'mount': 'application-vendor/standard-log', 'source': {'path': '../' + library.name},
            'dependencies': [], 'metadata': {'cSources': ['log_probe.c'], 'includeDirectories': ['.']}}],
        'transformations': []})
    lock = dependencies.capture(project)
    (project / dependencies.LOCK).write_bytes(canonical(lock))
    source = project / 'src/main.c'
    original = source.read_text(encoding='utf-8')
    opening = '                                         probe_string_t *error) {'
    if original.count(opening) != 1:
        raise ValueError('c-standard-logging-requires-original-greeting-template')
    branches = ''.join(f'    if (name->len == {len("log:" + name)} && memcmp(name->ptr, "log:{name}", name->len) == 0) mode = {i};\n'
                       for i, name in enumerate(CASES, 1))
    branches += '    if (name->len == 22 && memcmp(name->ptr, "log:initializer-denied", name->len) == 0) mode = 12;\n'
    body = '\n    static unsigned calls;\n    unsigned mode = 0;\n' + branches + '''
    if (++calls != 1 || !standard_log_probe(mode)) {
        probe_string_free(name); lsf_text_error(error, "standard-logging-probe-failed"); return false;
    }
    if (mode) { probe_string_free(name); probe_string_dup(value, "1"); return true; }
'''
    source.write_text('#include "log_probe.h"\n' + original.replace(opening, opening + body), encoding='utf-8')
    originals = {path.name: digest(path.read_bytes()) for path in library.iterdir()}
    for name in ('log_probe.c', 'log_probe.h'):
        (library / name).unlink()
    library.rmdir()
    return {'profile': LOGGING_PROFILE, 'originalLibrary': originals, 'originalLibraryRemoved': not library.exists(),
            'lockDigest': digest((project / dependencies.LOCK).read_bytes()), 'extraCases': list(CASES)}


def grant_and_probe(client, node, fixture, targets, publications, result):
    from tools.phase2_operator_process import require
    from tools.rust_capsule_node import assert_value, call, deploy, provider_idle
    target = targets['greeting']
    initialization = call(client, target, 'greeting', 'greet', ['log:initializer-denied'], 'c-stdio-initializer-without-grant')
    result['invocations'].append(initialization)
    assert_value(client, initialization, [{'ok': '1'}])
    denied = call(client, target, 'greeting', 'greet', ['Ada'], 'c-stdio-without-log-grant')
    result['invocations'].append(denied)
    assert_value(client, denied, [{'err': 'standard-logging-probe-failed'}], 3)
    policy = client.directory / 'standard-stdio-policy.json'
    capability = 'latent:log/log@0.1.0'
    write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'stdio', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [publications['greeting']], 'capability': capability,
        'operations': ['write'], 'resources': {'kind': 'log', 'levels': ['info', 'error']},
        'ceiling': {'operations': 64, 'inputBytes': 16384, 'outputBytes': 0, 'wallTimeMillis': 5000}}]})
    client.call('policy', 'apply', '--id', 'standard-stdio', '--file', policy,
                '--operation-id', 'grant-standard-stdio', '--expected-generation', '0')
    target = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
        generation=str(target['generation']), grants=[{'capability': capability, 'policy': 'standard-stdio'}])
    targets['greeting'] = target
    result['cStandardLoggingGrant'] = {'capability': capability, 'policy': 'standard-stdio'}
    for ordinal, name in enumerate(CASES):
        row = call(client, target, 'greeting', 'greet', ['log:' + name], 'c-stdio-' + str(ordinal))
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': '1'}])
        result['providerIdle'].append(provider_idle(client))
    require(len(CASES) == 11, 'c-standard-stdio-probe-count')
