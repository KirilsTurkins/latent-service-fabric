"""Explicit application fallback; the old scratch-refusal fixtures stay unchanged."""
from pathlib import Path

from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest, inventory, read_file, snapshot

LANGUAGES = ('c', 'go')
CASES = (('open', 7, 42), ('open', 11, 62), ('trap', 13, None), ('open', 19, 102))
C = r'''
#include <errno.h>
#include <stdio.h>
static unsigned fallback_calls;
static const char *fallback_case(probe_string_t *name) {
    lsf_require(++fallback_calls == 1);
    lsf_require(name->len >= 15 && name->len <= 18);
    bool trapped = memcmp(name->ptr + 9, "trap:", 5) == 0;
    lsf_require(trapped || memcmp(name->ptr + 9, "open:", 5) == 0);
    unsigned seed = 0;
    for (size_t i = 14; i < name->len; ++i) {
        lsf_require(name->ptr[i] >= '0' && name->ptr[i] <= '9');
        seed = seed * 10 + (unsigned)(name->ptr[i] - '0');
        lsf_require(seed <= 1000);
    }
    errno = 0;
    FILE *file = fopen("lsf-explicit-fallback", "rb");
    int cause = errno;
    if (file != NULL) { fclose(file); return "fallback|c|unexpected-success"; }
    if (cause != ENOTSUP) return "fallback|c|wrong-native-refusal";
    if (trapped) __builtin_trap();
    unsigned alternate = seed * 5 + 7;
    static char result[128];
    int written = snprintf(result, sizeof(result),
        "fallback|c|unsupported|seed=%u|alternate=%u|fresh=1", seed, alternate);
    lsf_require(written > 0 && (size_t)written < sizeof(result));
    return result;
}
'''
GO = r'''
var fallbackCalls int
func fallbackCase(value string) string {
    fallbackCalls++
    if fallbackCalls != 1 { panic("fallback-state-reused") }
    mode, raw, found := strings.Cut(value, ":")
    if !found || (mode != "open" && mode != "trap") || len(raw) < 1 || len(raw) > 4 {
        panic("fallback-input")
    }
    for _, digit := range raw {
        if digit < '0' || digit > '9' { panic("fallback-seed") }
    }
    seed, parseError := strconv.Atoi(raw)
    if parseError != nil || seed < 0 || seed > 1000 { panic("fallback-seed") }
    file, err := os.Open("lsf-explicit-fallback")
    if err == nil { file.Close(); return "fallback|go|unexpected-success" }
    var pathError *os.PathError
    var errno syscall.Errno
    if !errors.As(err, &pathError) || !errors.As(err, &errno) || errno != syscall.ENOSYS ||
        !errors.Is(err, errors.ErrUnsupported) { return "fallback|go|wrong-native-refusal" }
    if mode == "trap" { panic("explicit-fallback-fixture-trap") }
    alternate := seed * 5 + 7
    return "fallback|go|unsupported|seed=" + strconv.Itoa(seed) +
        "|alternate=" + strconv.Itoa(alternate) + "|fresh=1"
}
'''


def expected(language, seed, alternate):
    require(language in LANGUAGES and type(seed) is type(alternate) is int
        and 0 <= seed <= 1000 and alternate == seed * 5 + 7, 'fallback-finite-expectation')
    return [{'ok': f'fallback|{language}|unsupported|seed={seed}|alternate={alternate}|fresh=1'}]


def project(language: str, directory: Path):
    require(language in LANGUAGES, 'fallback-language')
    if language == 'c':
        from tools.c_capsule_project import create
        source_path = 'src/main.c'
    else:
        from tools.go_capsule_project import create
        source_path = 'src/main.go'
    app = create(directory, 'greeting')
    before = snapshot(app)
    source = before[source_path].decode()
    if language == 'c':
        anchor = '    size_t first = name->len, end = 0, offset = 0;'
        hook = '''    if (name->len >= 9 && memcmp(name->ptr, "fallback:", 9) == 0) {
        const char *outcome = fallback_case(name); probe_string_free(name);
        lsf_text_error(value, outcome); return true;
    }
'''
        declaration = '#include "lsf/text.h"'
        require(source.count(declaration) == 1, 'fallback-c-template-include')
        source = source.replace(declaration, declaration + '\n' + C, 1)
    else:
        anchor = '\tname = strings.TrimSpace(name)'
        hook = '\tif strings.HasPrefix(name,"fallback:") { return wit.Ok[string,string](fallbackCase(strings.TrimPrefix(name,"fallback:"))) }\n'
        require(source.count('import (') == 1, 'fallback-go-template-imports')
        source = source.replace('import (', 'import (\n"os"\n"errors"\n"syscall"\n"strconv"', 1) + GO
    require(source.count(anchor) == 1, 'fallback-original-template-anchor')
    source = source.replace(anchor, hook + anchor, 1)
    (app / source_path).write_bytes(source.encode())
    after = snapshot(app)
    require(set(before) == set(after) and all(before[p] == after[p] for p in before if p != source_path),
        'fallback-no-sdk-profile-wit-or-grant-change')
    return app, {'language': language, 'sourcePath': source_path, 'sourceDigest': digest(inventory(after)),
        'fixtureDigest': digest(read_file(app / source_path)), 'explicitApplicationFallback': True,
        'sdkProfileAndLimitsChanged': False, 'filesystemGrantAdded': False,
        'compilerExecuted': False, 'signedQualification': 'pending'}
