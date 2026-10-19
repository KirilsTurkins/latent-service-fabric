"""Captured ordinary libc composition; four independent explicit provider grants."""
from pathlib import Path

from tools import application_dependencies as dependencies
from tools.build_snapshot import canonical, digest
from tools.c_guest.standard_facilities import COMBINED_PROFILE
from tools.rust_capsule_project import read_json, write_json

CASES = ('initializer', 'sequence', 'wall', 'stderr', 'entropy-error', 'clock-error')
LIBRARY = r'''#include "facilities_probe.h"
#include <errno.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
#include <wasi/api.h>
static unsigned initialized;
static int ready;
__attribute__((constructor)) static void ordinary_library_initializer(void) {
    struct timespec now;
    unsigned char bytes[16];
    ++initialized;
    ready = clock_gettime(CLOCK_MONOTONIC, &now) == 0
        && getentropy(bytes, sizeof(bytes)) == 0
        && printf("ordinary combined initializer\n") >= 0;
}
int combined_probe(unsigned mode) {
    if (initialized != 1 || !ready) return 0;
    struct timespec first = {7, 8}, second = {0, 0};
    unsigned char bytes[257];
    if (clock_gettime(CLOCK_MONOTONIC, &first) || getentropy(bytes, 32)) return 0;
    if (printf("combined library: %u\n", mode) < 0) return 0;
    if (clock_gettime(CLOCK_MONOTONIC, &second)) return 0;
    if (second.tv_sec < first.tv_sec || (second.tv_sec == first.tv_sec && second.tv_nsec < first.tv_nsec)) return 0;
    if (mode == 0 || mode == 1 || mode == 2) return 1;
    if (mode == 3) return clock_gettime(CLOCK_REALTIME, &first) == 0
        && first.tv_sec > 0 && first.tv_nsec % 1000000 == 0;
    if (mode == 4) return fprintf(stderr, "ordinary combined error\n") >= 0;
    if (mode == 5) return getentropy(bytes, sizeof(bytes)) == -1 && errno == EIO;
    if (mode == 6) {
        __wasi_timestamp_t untouched = 7;
        return __wasi_clock_time_get(2, 1, &untouched) == __WASI_ERRNO_NOTSUP && untouched == 7;
    }
    return 0;
}
'''


def prepare(project: Path) -> dict:
    library = project.parent / 'outside-combined-facilities-library'
    library.mkdir()
    (library / 'facilities_probe.h').write_text('int combined_probe(unsigned mode);\n', encoding='utf-8')
    (library / 'facilities_probe.c').write_text(LIBRARY, encoding='utf-8')
    configuration = read_json(project / 'capsule-project.json')
    configuration['runtimeProfile'] = COMBINED_PROFILE
    configuration['limits']['logBytes'] = 16384
    (project / 'capsule-project.json').write_bytes(canonical(configuration))
    write_json(project / dependencies.MANIFEST, {'formatVersion': 1, 'language': 'c',
        'selection': {'target': 'wasm32-wasi', 'runtimeProfile': COMBINED_PROFILE}, 'nativeLocks': [],
        'artifacts': [{'id': 'outside-owner/combined-facilities/2026.10.19', 'role': 'application',
            'format': 'directory', 'mount': 'application-vendor/combined-facilities',
            'source': {'path': '../' + library.name}, 'dependencies': [],
            'metadata': {'cSources': ['facilities_probe.c'], 'includeDirectories': ['.']}}],
        'transformations': []})
    (project / dependencies.LOCK).write_bytes(canonical(dependencies.capture(project)))
    source = project / 'src/main.c'
    original = source.read_text(encoding='utf-8')
    opening = '                                         probe_string_t *error) {'
    if original.count(opening) != 1:
        raise ValueError('c-combined-probe-requires-original-greeting-template')
    branches = ''.join(f'    if (name->len == {len("combined:" + name)} && memcmp(name->ptr, "combined:{name}", name->len) == 0) mode = {i};\n'
                       for i, name in enumerate(CASES, 1))
    body = '\n    static unsigned calls;\n    unsigned mode = 0;\n' + branches + '''
    if (++calls != 1 || !combined_probe(mode)) {
        probe_string_free(name); lsf_text_error(error, "combined-facilities-probe-failed"); return false;
    }
    if (mode) { probe_string_free(name); probe_string_dup(value, "1"); return true; }
'''
    source.write_text('#include "facilities_probe.h"\n' + original.replace(opening, opening + body), encoding='utf-8')
    originals = {path.name: digest(path.read_bytes()) for path in library.iterdir()}
    for name in ('facilities_probe.c', 'facilities_probe.h'):
        (library / name).unlink()
    library.rmdir()
    return {'profile': COMBINED_PROFILE, 'originalLibrary': originals, 'originalLibraryRemoved': not library.exists(),
            'lockDigest': digest((project / dependencies.LOCK).read_bytes()), 'extraCases': list(CASES)}


def grant_and_probe(client, node, fixture, targets, publications, result):
    from tools.c_standard_facilities_probe import require_denied_before_guest
    from tools.guest_runtime_profiles import profiles
    from tools.phase2_operator_process import require
    from tools.rust_capsule_node import assert_value, call, deploy, provider_idle
    target, steps = targets['greeting'], []
    selected = {**profiles('c'), 'log': ('latent:log/log@0.1.0', 'activation-log-v1', 'write', 'log')}
    for name, (capability, profile, operation, kind) in selected.items():
        installed = [row for row in node.startup_record['providers'] if row['id'] == name]
        require(len(installed) == 1 and installed[0]['capability'] == capability
                and installed[0]['profile'] == profile and installed[0]['tenant'] == 'examples'
                and installed[0]['service'] == 'runtime-host', 'c-combined-provider-identity')
        descriptor = installed[0]
        binding = client.directory / (name + '-combined-binding.json')
        write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': capability,
            'providerProfile': profile, 'configurationDigest': descriptor['configurationDigest'],
            'configurationEpoch': 1, 'restriction': {'operations': [operation]}})
        client.call('policy', '--kind', 'provider-binding', 'apply', '--id', name + '-installed', '--file', binding,
                    '--operation-id', 'install-combined-' + name, '--expected-generation', '0')
        policy = client.directory / (name + '-combined-policy.json')
        resources = {'kind': kind, **({'levels': ['info', 'error']} if kind == 'log' else {})}
        ceiling = ({'operations': 64, 'inputBytes': 16384, 'outputBytes': 0, 'wallTimeMillis': 5000}
                   if kind == 'log' else {'operations': 4096, 'inputBytes': 128 if kind == 'random' else 0,
                                         'outputBytes': 65536, 'wallTimeMillis': 5000})
        write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'combined', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [publications['greeting']],
            'capability': capability, 'operations': [operation], 'resources': resources, 'ceiling': ceiling}]})
        policy_id = name + '-combined-allow'
        client.call('policy', 'apply', '--id', policy_id, '--file', policy,
                    '--operation-id', 'grant-combined-' + name, '--expected-generation', '0')
        steps.append({'capability': capability, 'policy': policy_id})
    # Omit exactly one grant at a time so another absent capability cannot mask it.
    for ordinal, omitted in enumerate(steps):
        target = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
                        generation=str(target['generation']), grants=[step for step in steps if step != omitted])
        denied = call(client, target, 'greeting', 'greet', ['combined:initializer'], 'c-combined-denied-' + str(ordinal))
        result['invocations'].append(denied)
        require_denied_before_guest(denied)
        result['providerIdle'].append(provider_idle(client))
    target = deploy(client, fixture / 'my-greeting/deployment.json', publications['greeting'],
                    generation=str(target['generation']), grants=list(steps))
    targets['greeting'] = target
    result['cStandardCombinedGrantSteps'] = steps
    require(len(steps) == 4 and len(CASES) == 6, 'c-combined-finite-probe-count')
    for ordinal, name in enumerate(CASES):
        row = call(client, target, 'greeting', 'greet', ['combined:' + name], 'c-combined-' + str(ordinal))
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': '1'}])
        result['providerIdle'].append(provider_idle(client))
