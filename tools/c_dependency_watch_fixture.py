"""Independent C library revisions for the delivered dependency/watch probe."""
from pathlib import Path

from tools.build_snapshot import canonical, digest

CHILD = 'outside-watch-child/2026.10.16'
PRIMARY = 'outside-watch-primary/2026.10.16'
PRIMARY_FILES = {
    'owned_api.h': b'int outside_add(int value);\nconst char *outside_badge(void);\n',
    'owned.c': b'#include "owned_api.h"\n#include "child.h"\n#include "badge.h"\n'
               b'int outside_add(int value) { return child_add(value); }\n'
               b'const char *outside_badge(void) { return badge; }\n',
    'badge.h': b'static const char badge[] = "captured watch data";\n',
}
SOURCE = r'''/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/text.h"
LIBRARY_INCLUDE
static bool watch_append(char *text, size_t *length, const uint8_t *bytes, size_t count) {
    if (count >= 160 - *length) return false;
    memcpy(text + *length, bytes, count);
    *length += count;
    text[*length] = 0;
    return true;
}
INTEGER_FORMATTER
bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *value, probe_string_t *error) {
    static unsigned calls;
    if (++calls != 1 || name->len > 100) {
        probe_string_free(name); lsf_text_error(error, "invalid-fresh-watch-input"); return false;
    }
    char text[160] = {0};
    size_t length = 0;
    size_t name_length = 0;
    while (name_length < name->len && name->ptr[name_length] != 0) ++name_length;
    bool formatted = FORMAT;
    probe_string_free(name);
    if (!formatted) {
        lsf_text_error(error, "watch-result-too-large"); return false;
    }
    probe_string_dup(value, text);
    return true;
}
'''


def application_source(*, removed=False):
    include = '' if removed else '#include "owned_api.h"'
    integer = '' if removed else r'''static bool watch_integer(char *text, size_t *length, int value) {
    char reverse[sizeof(int) * 3 + 1];
    size_t count = 0;
    unsigned magnitude = value < 0 ? 0u - (unsigned)value : (unsigned)value;
    do { reverse[count++] = (char)('0' + magnitude % 10); magnitude /= 10; } while (magnitude);
    if (value < 0 && !watch_append(text, length, (const uint8_t *)"-", 1)) return false;
    while (count) if (!watch_append(text, length, (const uint8_t *)&reverse[--count], 1)) return false;
    return true;
}'''
    formatting = ('watch_append(text, &length, (const uint8_t *)"removed/", 8) && '
                  'watch_append(text, &length, name->ptr, name_length)' if removed else
                  'watch_integer(text, &length, outside_add(3)) && '
                  'watch_append(text, &length, (const uint8_t *)"/", 1) && '
                  'watch_append(text, &length, name->ptr, name_length) && '
                  'watch_append(text, &length, (const uint8_t *)"/", 1) && '
                  'watch_append(text, &length, (const uint8_t *)outside_badge(), strlen(outside_badge()))')
    return SOURCE.replace('LIBRARY_INCLUDE', include).replace('INTEGER_FORMATTER', integer).replace('FORMAT', formatting)


def create(application: Path) -> dict:
    root = application.parent / 'outside-library'
    root.mkdir(mode=0o700)
    declarations = {}
    for name, increment in (('child-v1', 39), ('child-v2', 40), ('primary', None)):
        directory = root / name
        directory.mkdir(mode=0o700)
        files = PRIMARY_FILES if increment is None else {
            'child.h': ('static inline int child_add(int value) { return value + ' + str(increment) + '; }\n').encode()}
        for path, raw in files.items():
            (directory / path).write_bytes(raw)
        artifact = {'id': PRIMARY if increment is None else CHILD, 'role': 'application', 'format': 'directory',
                    'mount': 'application-vendor/' + ('primary' if increment is None else 'child'),
                    'source': {'path': '../outside-library/' + name},
                    'dependencies': [CHILD] if increment is None else [],
                    'metadata': {'includeDirectories': ['.'], 'cSources': ['owned.c'] if increment is None else []}}
        declaration = root / (name + '.json')
        declaration.write_bytes(canonical(artifact))
        declarations[name] = declaration
    return {'root': root, 'declarations': declarations,
            'inputDigests': {path.relative_to(root).as_posix(): digest(path.read_bytes())
                            for path in sorted(root.rglob('*')) if path.is_file()}}


def remove_original(fixture: dict, name: str) -> None:
    directory = fixture['root'] / name
    names = PRIMARY_FILES if name == 'primary' else {'child.h': b''}
    if {path.name for path in directory.iterdir()} != set(names):
        raise ValueError('c-watch-original-input-inventory-changed')
    for path in names:
        selected = directory / path
        if digest(selected.read_bytes()) != fixture['inputDigests'][name + '/' + path]:
            raise ValueError('c-watch-original-input-bytes-changed')
    for path in names:
        (directory / path).unlink()
    directory.rmdir()


def restore_primary(fixture: dict) -> None:
    directory = fixture['root'] / 'primary'
    directory.mkdir(mode=0o700)
    for name, raw in PRIMARY_FILES.items():
        (directory / name).write_bytes(raw)
        if digest(raw) != fixture['inputDigests']['primary/' + name]:
            raise ValueError('c-watch-restored-primary-drift')
