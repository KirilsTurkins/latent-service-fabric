"""One ordinary captured C project; no private threading intrinsics or grants."""
from __future__ import annotations

import json
from pathlib import Path

from tools import c_capsule_project
from tools.c_guest.threading import PROFILE
from tools.rust_capsule_project import read_file, snapshot

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = 'tools/fixtures/c-thread-runtime/'
WORLD = 'examples:c-thread-runtime/service@1.0.0'
API = 'examples:c-thread-runtime/api@1.0.0'
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
          'timers': 8, 'results': 8, 'nativeOwners': 8}
MODES = ('pthread', 'c11', 'mixed', 'invalid', 'pressure', 'root-return',
         'application-error', 'root-trap', 'callback-trap', 'cancel', 'deadline',
         'sync-pthread', 'sync-mixed')


def prepare(directory: Path) -> Path:
    project = c_capsule_project.create(directory, 'greeting', name='c-thread-runtime',
                                       threading_profile=PROFILE)
    (project / 'src/main.c').write_bytes(read_file(ROOT / (FIXTURE + 'main.c')))
    (project / 'src/synchronization.h').write_bytes(read_file(ROOT / (FIXTURE + 'synchronization.h')))
    (project / 'wit/world.wit').write_bytes(read_file(ROOT / (FIXTURE + 'world.wit')))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config['world'] = WORLD
    # One declared envelope for every mode, including cancellation and pressure.
    # It must pay original linear memory AND all actual native stack mappings.
    config['limits'].update(cpuFuel=1_000_000_000, memoryBytes=32 * 1024 * 1024,
                             wallTimeLimitMillis=5000, logBytes=0)
    (project / 'capsule-project.json').write_bytes(
        (json.dumps(config, sort_keys=True, indent=2) + '\n').encode())
    c_capsule_project.validate(snapshot(project))
    return project


def observation(value: str, children: int, *, synchronized: bool = False) -> dict:
    """Consume real child-side observe output, never turn a model into proof."""
    if type(value) is not str or not value.startswith('joined:') or len(value) > 160:
        raise ValueError('c-thread-observed-result')
    parts = value.split(':')[1:]
    if len(parts) != 9 or any(not part.isascii() or not part.isdigit()
                              or len(part) > 20 or str(int(part)) != part for part in parts):
        raise ValueError('c-thread-observed-numeric-shape')
    count, entered, destructed, waits, parked, tasks, results, native, memory = map(int, parts)
    expected_waits = 2 if synchronized is True else 1
    if (type(synchronized) is not bool or synchronized and children != 2
            or type(children) is not int or not 1 <= children <= 3
            or (count, entered, destructed, waits, parked) != (children, children, children, expected_waits, expected_waits)
            or tasks != children + 1 or results != children or native != 2 + 2 * children
            or not 0 < memory <= 32 * 1024 * 1024):
        raise ValueError('c-thread-real-join-owner-witness')
    return {'children': count, 'entered': entered, 'destructed': destructed,
            'waits': waits, 'parkedTasks': parked, 'tasks': tasks, 'results': results,
            'nativeOwners': native, 'nativeMemoryBytes': memory,
            'positivePoint': 'generated activation.observe in child while original parent join is parked',
            'waitForPollPendingClaimed': False}


HTTP_FIXTURE = 'sdk/c-guest/runtime-fixtures/libfetch/'
HTTP_WORLD = 'examples:libfetch/probe@0.1.0'
HTTP_API = 'examples:libfetch/api@0.1.0'
HTTP_CASES = ('normal', 'not-found', 'denied', 'early-close', 'sibling')


def prepare_http(directory: Path) -> Path:
    from tools.c_guest.standard_facilities import FETCH_PROFILE
    project = c_capsule_project.create(directory, 'greeting', name='c-thread-runtime',
                                       threading_profile=PROFILE)
    for target, original in (('src/main.c', 'probe.c'), ('wit/world.wit', 'world.wit')):
        (project / target).write_bytes(read_file(ROOT / (HTTP_FIXTURE + original)))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config.update(world=HTTP_WORLD, runtimeProfile=FETCH_PROFILE)
    # Three ordinary GETs in the sibling cell; node/provider ceilings are unchanged.
    config['limits'].update(cpuFuel=1_000_000_000, memoryBytes=32 * 1024 * 1024,
                            wallTimeLimitMillis=5000, logBytes=0, outboundRequests=3)
    (project / 'capsule-project.json').write_bytes(
        (json.dumps(config, sort_keys=True, indent=2) + '\n').encode())
    c_capsule_project.validate(snapshot(project))
    return project


def http_result(row: dict, case: str) -> None:
    from tools.standard_http.vectors import DOMAIN, PARTIAL, json_bytes
    def checksum(data):
        value = 0
        for byte in data:
            value = (value * 33 + byte) & 0xffffffff
        return str(len(data)) + ':' + str(value)
    expected = {
        'normal': (0, [{'ok': checksum(json_bytes(DOMAIN))}]),
        'not-found': (3, [{'err': 'unavailable'}]),
        'denied': (3, [{'err': 'permission-denied'}]),
        'early-close': (0, [{'ok': 'closed'}]),
        'sibling': (0, [{'ok': checksum(PARTIAL) + ':' + checksum(json_bytes(DOMAIN)) + ':1:1:1'}]),
    }
    if type(row.get('exitCode')) is not int or case not in expected or (row['exitCode'], row['decoded']) != expected[case]:
        raise ValueError('c-libfetch-exact-ordinary-result')


LIBUCL_FIXTURE = 'sdk/c-guest/runtime-fixtures/libucl/'
LIBUCL_CASES = ('normal', 'not-found', 'denied', 'file', 'glob')


def prepare_libucl(directory: Path, outside: Path) -> Path:
    """Normal captured dependency recipe; no configure subprocess or backend glue."""
    from tools.application_dependencies import MANIFEST, LOCK, capture
    from tools.build_snapshot import canonical, digest
    from tools.c_guest.standard_facilities import FETCH_STANDARD_PROFILE
    declaration = json.loads(read_file(ROOT / (LIBUCL_FIXTURE + 'UPSTREAM.json'), 65536))
    originals = snapshot(ROOT / (LIBUCL_FIXTURE + 'upstream'))
    expected = {row['path']: row for row in declaration['files']}
    if (len(originals) != 25 or set(originals) != set(expected)
            or sum(map(len, originals.values())) > 2 * 1024 * 1024
            or any(len(data) != expected[name]['bytes'] or digest(data) != expected[name]['sha256']
                   for name, data in originals.items())):
        raise ValueError('c-libucl-original-source-closure')
    outside.mkdir(mode=0o700)
    for name, data in originals.items():
        target = outside / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    project = c_capsule_project.create(directory, 'greeting', name='c-thread-runtime',
                                       threading_profile=PROFILE)
    for target, original in (('src/main.c', 'probe.c'), ('wit/world.wit', 'world.wit')):
        (project / target).write_bytes(read_file(ROOT / (LIBUCL_FIXTURE + original)))
    config = json.loads(read_file(project / 'capsule-project.json'))
    config.update(world=HTTP_WORLD, runtimeProfile=FETCH_STANDARD_PROFILE)
    config['limits'].update(cpuFuel=1_000_000_000, memoryBytes=32 * 1024 * 1024,
                            wallTimeLimitMillis=5000, logBytes=0, outboundRequests=3)
    (project / 'capsule-project.json').write_bytes(canonical(config) + b'\n')
    dependency = {'formatVersion': 1, 'language': 'c',
        'selection': {'target': 'wasm32-wasi', 'runtimeProfile': FETCH_STANDARD_PROFILE},
        'nativeLocks': [], 'artifacts': [{
            'id': 'vstakhov/libucl/' + declaration['commit'], 'role': 'application',
            'format': 'directory', 'mount': 'dependencies/libucl', 'source': {'path': str(outside)},
            'dependencies': [], 'metadata': {
                'cSources': declaration['cSources'],
                'includeDirectories': declaration['includeDirectories'],
                'defines': declaration['defines'],
                'license': 'BSD-2-Clause AND MIT AND BSD-1-Clause'}}], 'transformations': []}
    (project / MANIFEST).write_bytes(canonical(dependency) + b'\n')
    (project / LOCK).write_bytes(canonical(capture(project)) + b'\n')
    c_capsule_project.validate(snapshot(project))
    return project


def libucl_result(row: dict, case: str) -> None:
    expected = {'normal': (0, [{'ok': 'ucl:7:caf\u00e9:first:\u03bb:0'}]),
                **{name: (3, [{'err': 'include-rejected'}])
                   for name in ('not-found', 'denied', 'file', 'glob')}}
    if type(row.get('exitCode')) is not int or case not in expected or (
            row['exitCode'], row['decoded']) != expected[case]:
        raise ValueError('c-libucl-exact-ordinary-result')


def prepare_http_standard(directory: Path) -> Path:
    """The unchanged current libfetch probe under the expanded normal profile."""
    from tools.c_guest.standard_facilities import FETCH_STANDARD_PROFILE
    project = prepare_http(directory)
    config = json.loads(read_file(project / 'capsule-project.json'))
    config['runtimeProfile'] = FETCH_STANDARD_PROFILE
    (project / 'capsule-project.json').write_bytes(
        (json.dumps(config, sort_keys=True, indent=2) + '\n').encode())
    c_capsule_project.validate(snapshot(project))
    return project


CARD_LIBRARY = b'#include "card_client.h"\n#include <errno.h>\n#include <fetch.h>\n#include <limits.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n\n/* A declared, captured build resource. No runtime filesystem is requested. */\nstatic const unsigned char policy[] = {\n#embed "expected-card.txt" suffix(,0)\n};\n\nstruct card_client {\n    struct url *url;\n    unsigned identifier;\n    unsigned char name[32];\n    size_t name_bytes;\n};\n\nstatic int decimal(const unsigned char **cursor, unsigned *value) {\n    const unsigned char *p = *cursor;\n    unsigned n = 0;\n    if (*p < \'0\' || *p > \'9\') return 0;\n    do {\n        unsigned digit = (unsigned)(*p++ - \'0\');\n        if (n > (UINT_MAX - digit) / 10u) return 0;\n        n = n * 10u + digit;\n    } while (*p >= \'0\' && *p <= \'9\');\n    *cursor = p;\n    *value = n;\n    return 1;\n}\n\nstatic int configure(struct card_client *client) {\n    if (sizeof(policy) < 13 || sizeof(policy) > 128 || memcmp(policy, "id=", 3)) return 0;\n    const unsigned char *p = policy + 3;\n    if (!decimal(&p, &client->identifier) || *p++ != \'\\n\') return 0;\n    if ((size_t)(p - policy) + 5 > sizeof(policy) || memcmp(p, "name=", 5)) return 0;\n    p += 5;\n    const unsigned char *begin = p;\n    while (*p && *p != \'\\n\') {\n        if (*p < 32 || *p == \'"\' || *p == \'\\\\\' || (size_t)(p - begin) >= sizeof(client->name)) return 0;\n        ++p;\n    }\n    if (p == begin || *p++ != \'\\n\' || *p != 0 || (size_t)(p - policy) != sizeof(policy) - 1) return 0;\n    client->name_bytes = (size_t)(p - begin) - 1;\n    memcpy(client->name, begin, client->name_bytes);\n    return 1;\n}\n\nstruct card_client *card_client_new(const char *url, enum card_status *status) {\n    if (!status) return NULL;\n    *status = CARD_ARGUMENT;\n    if (!url || !*url) return NULL;\n    struct card_client *client = calloc(1, sizeof(*client));\n    if (!client) { *status = CARD_MEMORY; return NULL; }\n    if (!configure(client)) { free(client); *status = CARD_RESOURCE; return NULL; }\n    client->url = fetchParseURL(url);\n    if (!client->url) {\n        int first_errno = errno;\n        free(client);\n        errno = first_errno;\n        *status = CARD_URL;\n        return NULL;\n    }\n    *status = CARD_OK;\n    return client;\n}\n\nstatic int domain(const unsigned char *body, size_t size, struct card_client *client,\n                  struct card_result *result) {\n    if (memchr(body, 0, size)) return 0;\n    const unsigned char *id = (const unsigned char *)strstr((const char *)body, "\\"id\\":");\n    const unsigned char *name = (const unsigned char *)strstr((const char *)body, "\\"name\\":\\"");\n    unsigned identifier;\n    if (!id || !name) return 0;\n    id += 5;\n    if (!decimal(&id, &identifier) || identifier != client->identifier || (*id != \',\' && *id != \'}\')) return 0;\n    name += 8;\n    if ((size_t)(name - body) + client->name_bytes + 1 > size\n            || memcmp(name, client->name, client->name_bytes) || name[client->name_bytes] != \'"\') return 0;\n    uint32_t checksum = UINT32_C(2166136261);\n    for (size_t i = 0; i < size; ++i) checksum = (checksum ^ body[i]) * UINT32_C(16777619);\n    *result = (struct card_result){identifier, client->name_bytes, size, checksum};\n    return 1;\n}\n\nenum card_status card_client_request(struct card_client *client, struct card_result *result) {\n    if (!client || !result) return CARD_ARGUMENT;\n    memset(result, 0, sizeof(*result));\n    FILE *stream = fetchGet(client->url, "A");\n    if (!stream) return CARD_HTTP;\n    unsigned char body[4097];\n    size_t used = 0;\n    enum card_status status = CARD_OK;\n    int first_errno = errno;\n    while (used < sizeof(body) - 1) {\n        size_t n = fread(body + used, 1, sizeof(body) - 1 - used, stream);\n        used += n;\n        if (n == 0) {\n            if (ferror(stream) || !feof(stream)) { status = CARD_READ; first_errno = errno; }\n            break;\n        }\n    }\n    if (status == CARD_OK && used == sizeof(body) - 1) {\n        unsigned char excess;\n        if (fread(&excess, 1, 1, stream) != 0) { status = CARD_TOO_LARGE; first_errno = errno; }\n        else if (ferror(stream) || !feof(stream)) { status = CARD_READ; first_errno = errno; }\n    }\n    if (fclose(stream) != 0 && status == CARD_OK) { status = CARD_CLOSE; first_errno = errno; }\n    if (status != CARD_OK) { errno = first_errno; return status; }\n    body[used] = 0;\n    return domain(body, used, client, result) ? CARD_OK : CARD_DOMAIN;\n}\n\nvoid card_client_free(struct card_client *client) {\n    if (client) { fetchFreeURL(client->url); free(client); }\n}\n'
CARD_HEADER = b'#ifndef CARD_CLIENT_H\n#define CARD_CLIENT_H\n#include <stddef.h>\n#include <stdint.h>\n\nstruct card_client;\nstruct card_result {\n    unsigned identifier;\n    size_t name_bytes;\n    size_t body_bytes;\n    uint32_t body_checksum;\n};\nenum card_status {\n    CARD_OK = 0, CARD_ARGUMENT, CARD_RESOURCE, CARD_MEMORY,\n    CARD_URL, CARD_HTTP, CARD_READ, CARD_TOO_LARGE, CARD_CLOSE, CARD_DOMAIN\n};\n\n/* Constructor/destructor are ordinary calls inside the exported application root. */\nstruct card_client *card_client_new(const char *url, enum card_status *status);\nenum card_status card_client_request(struct card_client *client, struct card_result *result);\nvoid card_client_free(struct card_client *client);\n#endif\n'
CARD_RESOURCE = b'id=7\nname=caf\xc3\xa9\n'
CARD_APPLICATION = b'#include "probe.h"\n#include "card_client.h"\n#include <stdbool.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n\nbool exports_examples_libfetch_api_run(probe_string_t *input, probe_string_t *result,\n                                       probe_string_t *error) {\n    if (!input->len || input->len > 8192 || memchr(input->ptr, 0, input->len)) {\n        probe_string_free(input); probe_string_dup(error, "invalid-url"); return false;\n    }\n    char *url = malloc(input->len + 1);\n    if (!url) { probe_string_free(input); probe_string_dup(error, "url-memory"); return false; }\n    memcpy(url, input->ptr, input->len); url[input->len] = 0;\n    probe_string_free(input);\n    enum card_status status;\n    struct card_client *client = card_client_new(url, &status);\n    free(url);\n    struct card_result card;\n    if (client) status = card_client_request(client, &card);\n    card_client_free(client);\n    char output[128];\n    if (status != CARD_OK) {\n        snprintf(output, sizeof(output), "card-status:%u", (unsigned)status);\n        probe_string_dup(error, output); return false;\n    }\n    int length = snprintf(output, sizeof(output), "card:%u:%zu:%zu:%u",\n        card.identifier, card.name_bytes, card.body_bytes, card.body_checksum);\n    if (length < 0 || (size_t)length >= sizeof(output)) { probe_string_dup(error, "card-output"); return false; }\n    probe_string_dup(result, output);\n    return true;\n}\n'

def prepare_unseen_library(directory: Path, identity_variant: int = 0) -> Path:
    """Ordinary outside source/resource capture; no catalogue lookup or compiler."""
    from tools import application_dependencies as dependencies
    from tools.build_snapshot import canonical
    from tools.c_guest.standard_facilities import FETCH_STANDARD_PROFILE
    if type(identity_variant) is not int or identity_variant not in (0, 1):
        raise ValueError('c-card-identity-variant')
    project = prepare_http(directory)
    configuration = json.loads(read_file(project / 'capsule-project.json'))
    configuration.update(languageStandard='c23', runtimeProfile=FETCH_STANDARD_PROFILE)
    (project / 'capsule-project.json').write_bytes(canonical(configuration))
    (project / 'src/main.c').write_bytes(CARD_APPLICATION)
    outside = project.parent / ('outside-card-' + str(identity_variant))
    outside.mkdir()
    library, resource = outside / 'library', outside / 'data'
    library.mkdir(); resource.mkdir()
    (library / 'card_client.c').write_bytes(CARD_LIBRARY)
    (library / 'card_client.h').write_bytes(CARD_HEADER)
    (resource / 'expected-card.txt').write_bytes(CARD_RESOURCE)
    ids = (('shop-floor/price-card', 'shop-floor/card-policy'),
           ('warehouse/bin-label-reader', 'warehouse/label-policy'))[identity_variant]
    declaration = {'formatVersion': 1, 'language': 'c',
        'selection': {'target': 'wasm32-wasi', 'runtimeProfile': FETCH_STANDARD_PROFILE, 'languageStandard': 'c23'},
        'nativeLocks': [], 'artifacts': [
            {'id': ids[0], 'role': 'application', 'format': 'directory', 'mount': 'dependencies/card-client',
             'source': {'path': '../' + outside.name + '/library'}, 'dependencies': [ids[1]],
             'metadata': {'cSources': ['card_client.c'], 'includeDirectories': ['.'], 'version': '0.1.0-owner-source'}},
            {'id': ids[1], 'role': 'resource', 'format': 'directory', 'mount': 'dependencies/card-policy',
             'source': {'path': '../' + outside.name + '/data'}, 'dependencies': [],
             'metadata': {'resources': [{'path': 'configuration/card-policy.txt', 'source': 'expected-card.txt', 'mediaType': 'text/plain'}]}}],
        'transformations': []}
    (project / dependencies.MANIFEST).write_bytes(canonical(declaration))
    (project / dependencies.LOCK).write_bytes(canonical(dependencies.capture(project)))
    # Only these freshly created originals are removed; normal builds use captured CAS bytes.
    for path in (library / 'card_client.c', library / 'card_client.h', resource / 'expected-card.txt'):
        path.unlink()
    library.rmdir(); resource.rmdir(); outside.rmdir()
    return project


CARD_CASES = ('normal',)


def unseen_result(row: dict, case: str) -> None:
    if (type(row.get('exitCode')) is not int or case != 'normal'
            or (row['exitCode'], row.get('decoded')) != (0, [{'ok': 'card:7:5:57:2650795109'}])):
        raise ValueError('c-card-exact-ordinary-result')
