"""Finite captured libc programme and explicit test-only provider policy probes."""
from pathlib import Path

from tools import application_dependencies as dependencies
from tools.build_snapshot import canonical, digest
from tools.c_guest.standard_facilities import PROFILE
from tools.rust_capsule_project import read_json, write_json

CASES = ('clock-cpu', 'monotonic-resolution', 'wall-resolution', 'entropy-length',
         'random-zero', 'random-length', 'random-fault', 'entropy-budget')
LIBRARY = r'''#include "clock_probe.h"
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wasi/api.h>
extern int32_t __imported_wasi_snapshot_preview1_random_get(int32_t, int32_t)
    __attribute__((import_module("wasi_snapshot_preview1"), import_name("random_get")));
int standard_probe(unsigned mode) {
    struct timespec first = {7, 8}, second = {0, 0};
    unsigned char bytes[4097];
    if (mode == 0) {
        if (clock_gettime(CLOCK_MONOTONIC, &first) || clock_gettime(CLOCK_MONOTONIC, &second)) return 0;
        if (second.tv_sec < first.tv_sec || (second.tv_sec == first.tv_sec && second.tv_nsec < first.tv_nsec)) return 0;
        if (first.tv_nsec < 0 || first.tv_nsec >= 1000000000) return 0;
        if (clock_gettime(CLOCK_REALTIME, &first) || first.tv_sec <= 0 || first.tv_nsec % 1000000) return 0;
        if (getentropy(bytes, 256)) return 0;
        unsigned char any = 0; for (unsigned i = 0; i < 256; ++i) any |= bytes[i];
        return any != 0;
    }
    if (mode == 1) {
        __wasi_timestamp_t unsupported = 7;
        return __wasi_clock_time_get(2, 1, &unsupported) == __WASI_ERRNO_NOTSUP && unsupported == 7;
    }
    if (mode == 2) return clock_getres(CLOCK_MONOTONIC, &first) == -1 && errno == ENOTSUP && first.tv_sec == 7 && first.tv_nsec == 8;
    if (mode == 3) return clock_getres(CLOCK_REALTIME, &first) == 0 && first.tv_sec == 0 && first.tv_nsec == 1000000;
    if (mode == 4) {
        memset(bytes, 0x5a, sizeof(bytes));
        if (getentropy(bytes, 257) != -1 || errno != EIO) return 0;
        for (unsigned i = 0; i < sizeof(bytes); ++i) if (bytes[i] != 0x5a) return 0;
        return 1;
    }
    if (mode == 5) return __imported_wasi_snapshot_preview1_random_get(0, 0) == 0;
    if (mode == 6) return __wasi_random_get(bytes, sizeof(bytes)) == __WASI_ERRNO_INVAL;
    if (mode == 7) return __imported_wasi_snapshot_preview1_random_get(0, 8) == __WASI_ERRNO_FAULT;
    if (mode == 8) {
        for (unsigned i = 0; i < 16; ++i) if (__wasi_random_get(bytes, 4096)) return 0;
        return __wasi_random_get(bytes, 4096) == __WASI_ERRNO_AGAIN;
    }
    return 0;
}
'''


def prepare(project: Path) -> dict:
    """Capture an unregistered external library; compile only verified CAS bytes."""
    library = project.parent / 'outside-standard-clock-library'
    library.mkdir()
    (library / 'clock_probe.h').write_text('int standard_probe(unsigned mode);\n', encoding='utf-8')
    (library / 'clock_probe.c').write_text(LIBRARY, encoding='utf-8')
    configuration = read_json(project / 'capsule-project.json')
    configuration['runtimeProfile'] = PROFILE
    (project / 'capsule-project.json').write_bytes(canonical(configuration))
    artifact = {'id': 'independent/clock-entropy-library/1', 'role': 'application', 'format': 'directory',
                'mount': 'application-vendor/standard-probe', 'source': {'path': '../' + library.name},
                'dependencies': [], 'metadata': {'cSources': ['clock_probe.c'], 'includeDirectories': ['.']}}
    write_json(project / dependencies.MANIFEST, {'formatVersion': 1, 'language': 'c',
        'selection': {'target': 'wasm32-wasi', 'runtimeProfile': PROFILE}, 'nativeLocks': [],
        'artifacts': [artifact], 'transformations': []})
    lock = dependencies.capture(project)
    (project / dependencies.LOCK).write_bytes(canonical(lock))
    source = project / 'src/main.c'
    original = source.read_text(encoding='utf-8')
    opening = '                                         probe_string_t *error) {'
    if original.count(opening) != 1:
        raise ValueError('c-standard-probe-requires-original-greeting-template')
    branches = ''.join(f'    if (name->len == {len("probe:" + name)} && memcmp(name->ptr, "probe:{name}", name->len) == 0) mode = {i};\n'
                       for i, name in enumerate(CASES, 1))
    body = '''
    static unsigned calls;
    unsigned mode = 0;
''' + branches + '''    int passed = ++calls == 1 && standard_probe(mode);
    if (!passed) {
        probe_string_free(name); lsf_text_error(error, "standard-facilities-probe-failed"); return false;
    }
    if (mode) {
        probe_string_free(name); probe_string_dup(value, "1"); return true;
    }
'''
    source.write_text('#include "clock_probe.h"\n' + original.replace(opening, opening + body), encoding='utf-8')
    originals = {path.name: digest(path.read_bytes()) for path in library.iterdir()}
    for name in ('clock_probe.c', 'clock_probe.h'):
        (library / name).unlink()
    library.rmdir()
    return {'profile': PROFILE, 'originalLibrary': originals, 'originalLibraryRemoved': not library.exists(),
            'lockDigest': digest((project / dependencies.LOCK).read_bytes()), 'extraCases': list(CASES)}


def require_denied_before_guest(denied):
    from tools.phase2_operator_process import require
    response = denied.get('response', {})
    data = response.get('data', {})
    consumption = data.get('consumption', {})
    require(denied.get('exitCode') == 4 and response.get('error', {}).get('code') == 'permission-denied'
            and response.get('outcomeKnown') is True and data.get('terminalState') == 'rejected'
            and consumption.get('cpuFuel') == '0' and consumption.get('peakMemoryBytes') == '0',
            'c-standard-missing-grant-must-reject-before-guest')


def grant_and_probe(client, node, fixture, targets, publications, result):
    """Each grant is an explicit ordinary operator mutation on an isolated node."""
    from tools.guest_runtime_profiles import profiles
    from tools.phase2_operator_process import require
    from tools.rust_capsule_node import assert_value, call, deploy, provider_idle
    steps, target = [], targets['greeting']
    selected = profiles('c')
    for ordinal, (name, (capability, profile, operation, kind)) in enumerate(selected.items()):
        denied = call(client, target, 'greeting', 'greet', ['Ada'], 'c-standard-denied-' + str(ordinal))
        result['invocations'].append(denied)
        require_denied_before_guest(denied)
        installed = [row for row in node.startup_record['providers'] if row['id'] == name]
        require(len(installed) == 1 and installed[0]['capability'] == capability and installed[0]['profile'] == profile,
                'c-standard-provider-identity')
        descriptor = installed[0]
        binding = client.directory / (name + '-binding.json')
        write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': capability,
            'providerProfile': profile, 'configurationDigest': descriptor['configurationDigest'],
            'configurationEpoch': 1, 'restriction': {'operations': [operation]}})
        client.call('policy', '--kind', 'provider-binding', 'apply', '--id', name + '-installed', '--file', binding,
                    '--operation-id', 'install-' + name, '--expected-generation', '0')
        policy = client.directory / (name + '-policy.json')
        write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [publications['greeting']],
            'capability': capability, 'operations': [operation], 'resources': {'kind': kind},
            'ceiling': {'operations': 4096, 'inputBytes': 128 if kind == 'random' else 0,
                        'outputBytes': 65536, 'wallTimeMillis': 5000}}]})
        client.call('policy', 'apply', '--id', name + '-allow', '--file', policy,
                    '--operation-id', 'grant-' + name, '--expected-generation', '0')
        steps.append({'capability': capability, 'policy': name + '-allow'})
        target = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
                        generation=str(target['generation']), grants=list(steps))
    targets['greeting'] = target
    result['cStandardGrantSteps'] = steps
    for ordinal, name in enumerate(CASES):
        row = call(client, target, 'greeting', 'greet', ['probe:' + name], 'c-standard-' + str(ordinal))
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': '1'}])
        result['providerIdle'].append(provider_idle(client))
