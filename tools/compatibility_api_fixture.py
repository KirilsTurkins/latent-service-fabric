"""Fixed ordinary C/Rust/Go call-edge pairs; no compiler or runtime execution.

Libraries are original local source inputs captured by the normal dependency
owner. The sole counterfactual is the fixed constant edge in application source.
An absent edge is not global API absence or a compatibility certificate.
"""
from __future__ import annotations

from pathlib import Path

from tools.rust_capsule_project import canonical, digest, fresh, inventory, read_file, snapshot

LANGUAGES = ('c', 'rust', 'go')
SOURCES = {'c': 'src/main.c', 'rust': 'src/lib.rs', 'go': 'src/main.go'}
PRIMARY = {'c': 'outside-api-primary/2026.10.25', 'rust': 'outside-api-primary',
           'go': 'outside.example.test/api-primary'}
CHILD = {'c': 'outside-api-child/2026.10.25', 'rust': 'outside-api-child',
         'go': 'outside.example.test/api-child'}
ROOTS = {'c': 'compatibility_root', 'rust': 'compatibility_root', 'go': 'compatibilityRoot'}
CALLEES = {'c': 'outside_api_primary', 'rust': 'outside_api_primary::probe', 'go': 'primary.Probe'}
API_KEYS = {'c': 'c.fopen.valid-mode', 'rust': 'rust.std.fs.File.open', 'go': 'go.os.Open'}
ROOT_EDGES = {
    'c': (b'if (0) { /* lsf-api-root-edge */', b'if (1) { /* lsf-api-root-edge */'),
    'rust': (b'if false { // lsf-api-root-edge', b'if true { // lsf-api-root-edge'),
    'go': (b'if false { // lsf-api-root-edge', b'if true { // lsf-api-root-edge'),
}

C = r'''#include "lsf/text.h"
#include "api_primary.h"
static int compatibility_root(void) __attribute__((noinline));
static int compatibility_root(void) {
    volatile int baseline = 0;
    if (0) { /* lsf-api-root-edge */
        return outside_api_primary();
    }
    return baseline;
}
bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *value,
                                         probe_string_t *error) {
    (void)error;
    int result = compatibility_root();
    probe_string_free(name);
    if (result == 0) probe_string_dup(value, "api|c|edge-not-taken");
    else if (result == 1) probe_string_dup(value, "api|c|unsupported");
    else __builtin_trap();
    return true;
}
'''
RUST = r'''#[inline(never)]
#[no_mangle]
fn compatibility_root() -> i32 {
    if false { // lsf-api-root-edge
        return outside_api_primary::probe();
    }
    0
}
pub fn greet(_name: String) -> Result<String, String> {
    match compatibility_root() {
        0 => Ok("api|rust|edge-not-taken".into()),
        1 => Ok("api|rust|unsupported".into()),
        _ => panic!("api-fixture-unexpected-result"),
    }
}
#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service"});
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        fn greet(name: String) -> Result<String, String> { super::greet(name) }
    }
    export!(Capsule);
}
'''
GO = r'''package export_examples_greeting_api
import (
    primary "outside.example.test/api-primary"
    wit "go.bytecodealliance.org/pkg/wit/types"
)
//go:noinline
func compatibilityRoot() int32 {
    if false { // lsf-api-root-edge
        return primary.Probe()
    }
    return 0
}
func Greet(_ string) wit.Result[string, string] {
    switch compatibilityRoot() {
    case 0: return wit.Ok[string, string]("api|go|edge-not-taken")
    case 1: return wit.Ok[string, string]("api|go|unsupported")
    default: panic("api-fixture-unexpected-result")
    }
}
'''


def require(condition, reason):
    if not condition:
        raise ValueError('compatibility-fixture-' + reason)


def application_source(language: str, *, reached=False) -> bytes:
    require(language in LANGUAGES and type(reached) is bool, 'selection')
    raw = {'c': C, 'rust': RUST, 'go': GO}[language].encode()
    before, after = ROOT_EDGES[language]
    require(raw.count(before) == 1 and after not in raw, 'fixed-root-edge')
    return raw.replace(before, after, 1) if reached else raw


def library_sources(language: str) -> dict[str, bytes]:
    require(language in LANGUAGES, 'language')
    if language == 'c':
        return {
            'primary/api_primary.h': b'__attribute__((noinline)) int outside_api_primary(void);\n',
            'primary/primary.c': b'#include "api_primary.h"\n#include "api_child.h"\n'
                b'int outside_api_primary(void) { return outside_api_child(); }\n',
            'child/api_child.h': b'__attribute__((noinline)) int outside_api_child(void);\n',
            'child/child.c': b'#include "api_child.h"\n#include <errno.h>\n#include <stdio.h>\n'
                b'static int original_api_callback(void) {\n'
                b'    errno = 0; FILE *file = fopen("lsf-api-fixture", "rb"); int cause = errno;\n'
                b'    if (file != NULL) { fclose(file); return -1; }\n'
                b'    return cause == ENOTSUP ? 1 : -1;\n}\n'
                b'int outside_api_child(void) {\n'
                b'    int (*callback)(void) = original_api_callback; return callback();\n}\n',
        }
    if language == 'rust':
        return {
            'primary/Cargo.toml': b'[package]\nname="outside-api-primary"\nversion="1.0.0"\nedition="2021"\n'
                b'[dependencies]\noutside-api-child={path="../child",version="=1.0.0"}\n',
            'primary/src/lib.rs': b'#[inline(never)]\npub fn probe() -> i32 { outside_api_child::probe() }\n',
            'child/Cargo.toml': b'[package]\nname="outside-api-child"\nversion="1.0.0"\nedition="2021"\n',
            'child/src/lib.rs': b'fn original_api_callback() -> i32 {\n'
                b'    match std::fs::File::open("lsf-api-fixture") {\n'
                b'        Err(error) if error.kind() == std::io::ErrorKind::Unsupported => 1,\n'
                b'        Err(_) => panic!("api-fixture-wrong-native-refusal"),\n'
                b'        Ok(file) => { drop(file); panic!("api-fixture-unexpected-success"); }\n'
                b'    }\n}\n#[inline(never)]\npub fn probe() -> i32 {\n'
                b'    let callback: fn() -> i32 = original_api_callback; callback()\n}\n',
        }
    return {
        'primary/go.mod': b'module outside.example.test/api-primary\n\ngo 1.27.3\n\n'
            b'require outside.example.test/api-child v1.0.0\n'
            b'replace outside.example.test/api-child => ../child\n',
        'primary/primary.go': b'package primary\nimport child "outside.example.test/api-child"\n'
            b'//go:noinline\nfunc Probe() int32 { return child.Probe() }\n',
        'child/go.mod': b'module outside.example.test/api-child\n\ngo 1.27.3\n',
        'child/child.go': b'package child\nimport ("errors"; "os"; "syscall")\n'
            b'func originalAPICallback() int32 {\n'
            b'    file, err := os.Open("lsf-api-fixture")\n'
            b'    if err == nil { file.Close(); panic("api-fixture-unexpected-success") }\n'
            b'    var pathError *os.PathError; var number syscall.Errno\n'
            b'    if !errors.As(err, &pathError) || !errors.As(err, &number) || number != syscall.ENOSYS ||\n'
            b'        !errors.Is(err, errors.ErrUnsupported) { panic("api-fixture-wrong-native-refusal") }\n'
            b'    return 1\n}\n//go:noinline\nfunc Probe() int32 {\n'
            b'    callback := originalAPICallback; return callback()\n}\n',
    }


def _creator(language):
    if language == 'c':
        from tools.c_capsule_project import create
    elif language == 'rust':
        from tools.rust_capsule_project import create
    else:
        from tools.go_capsule_project import create
    return create


def _c_declarations():
    return {part + '.json': canonical({'id': identifier, 'role': 'application', 'format': 'directory',
        'mount': 'application-vendor/' + part, 'source': {'path': '../libraries/' + part},
        'dependencies': [CHILD['c']] if part == 'primary' else [],
        'metadata': {'includeDirectories': ['.'], 'cSources': [part + '.c']}})
        for part, identifier in (('child', CHILD['c']), ('primary', PRIMARY['c']))}


def prepare(directory: Path, language: str, *, reached=False) -> dict:
    """Only normal project creation and fixed source writes; never resolve/build."""
    require(language in LANGUAGES and type(reached) is bool, 'selection')
    directory = fresh(directory)
    app = _creator(language)(directory / 'project', 'greeting', 'my-greeting')
    before = snapshot(app)
    (app / SOURCES[language]).write_bytes(application_source(language, reached=reached))
    libraries = fresh(directory / 'libraries')
    fixed = library_sources(language)
    for name, raw in fixed.items():
        target = libraries / name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(raw)
    declarations = []
    if language == 'c':
        declaration_root = fresh(directory / 'declarations')
        for name, raw in _c_declarations().items():
            target = declaration_root / name; target.write_bytes(raw)
            declarations.append(str(target))
    after = snapshot(app)
    require(set(after) == set(before) and all(after[name] == raw for name, raw in before.items()
            if name != SOURCES[language]), 'normal-sdk-profile-wit-limits-unchanged')
    canonical_target = PRIMARY['go'] + '.Probe' if language == 'go' else CALLEES[language]
    return {'schemaVersion': 'latent.compatibility.api-fixture.v1', 'language': language,
        'projectPath': str(app), 'ownedRoot': str(directory), 'rootSource': SOURCES[language],
        'rootFunction': ROOTS[language], 'targetFunction': canonical_target,
        'sourceTargetSpelling': CALLEES[language], 'apiKey': API_KEYS[language],
        'expectedScope': 'exact-selected-compiler-call-edge', 'reached': reached,
        'libraries': str(libraries), 'libraryIdentity': digest(inventory(fixed)),
        'libraryFiles': {name: digest(raw) for name, raw in sorted(fixed.items())},
        'declarations': declarations, 'expectedResult': [{'ok': 'api|' + language +
            ('|unsupported' if reached else '|edge-not-taken')}],
        'dependencyCapture': 'required-normal-owner-not-executed',
        'compilerExecuted': False, 'runtimeQualified': False, 'globalApiElimination': 'unknown'}


def capture(value: dict, author) -> dict:
    """Future bounded owner supplies its EXISTING normal CLI runner.

    author(label, operation, project, *args) must raise on failure. This function
    installs no process owner, selects no tool/cache/flag and never runs in prepare.
    Rust/Go normal add/resolve may invoke their pinned resolver; no compiler is
    acquired here. The original dependency review remains an exact digest step.
    """
    language = value['language']
    require(language in LANGUAGES and type(value['reached']) is bool, 'selection')
    app, root = Path(value['projectPath']), Path(value['ownedRoot'])
    require(app == root / 'project' and Path(value['libraries']) == root / 'libraries', 'owned-paths')
    def check():
        require(read_file(app / SOURCES[language]) == application_source(language, reached=value['reached']), 'root-source-drift')
        require(snapshot(root / 'libraries') == library_sources(language), 'library-source-drift')
        require(value['libraryIdentity'] == digest(inventory(library_sources(language))), 'library-identity-drift')
        if language == 'c':
            require(snapshot(root / 'declarations') == _c_declarations(), 'declaration-source-drift')
    def step(label, operation, *args):
        check(); result = author(label, operation, app, *args); check(); return result
    if language == 'c':
        expected = [str(root / 'declarations' / (part + '.json')) for part in ('child', 'primary')]
        require(value['declarations'] == expected, 'declaration-paths')
        step('api-add', 'add', '--artifact', expected[0], '--artifact', expected[1])
    else:
        version = 'v1.0.0' if language == 'go' else '1.0.0'
        step('api-add-primary', 'add', PRIMARY[language], '--version', version, '--path', root / 'libraries/primary')
        if language == 'go':
            step('api-add-child', 'add', CHILD[language], '--version', version, '--path', root / 'libraries/child')
            step('api-lock', 'lock')
    candidate = root / 'captured-candidate.json'
    require(not candidate.exists() and not candidate.is_symlink(), 'fresh-candidate')
    step('api-resolve', 'resolve', '--candidate', candidate)
    candidate_digest = digest(read_file(candidate, 8 * 1024 * 1024))
    step('api-review', 'review-lock', '--candidate', candidate, '--expect', candidate_digest)
    step('api-offline-status', 'dependencies')
    return {'candidateDigest': candidate_digest, 'normalDependencyOwnerUsed': True,
            'libraryIdentity': value['libraryIdentity'], 'componentCompiled': False,
            'runtimeQualified': False}


def counterfactual(value: dict) -> dict:
    """Flip only the fixed root edge in the SAME already captured application.

    The normal verified dependency closure is checked on both sides. No add,
    resolve, lock review, tool execution or separate native declaration paths.
    Existing snapshot exclusions omit dependency objects/target; verify_inputs
    independently checks the complete accepted object closure on both sides.
    """
    from tools.application_dependencies import verify_inputs
    language = value['language']
    require(language in LANGUAGES and value['reached'] is False, 'baseline-selection')
    app, root = Path(value['projectPath']), Path(value['ownedRoot'])
    require(app == root / 'project' and value['rootSource'] == SOURCES[language]
        and Path(value['libraries']) == root / 'libraries', 'owned-paths')
    require(value['libraryIdentity'] == digest(inventory(library_sources(language))), 'library-identity-drift')
    before = snapshot(app)
    require(before.get(SOURCES[language]) == application_source(language), 'root-source-drift')
    accepted = verify_inputs(app, language)
    require(accepted is not None, 'accepted-dependency-inputs-required')
    identity = accepted.identity
    selected = app / SOURCES[language]
    selected.write_bytes(application_source(language, reached=True))
    after = snapshot(app)
    require(set(after) == set(before) and after[SOURCES[language]] == application_source(language, reached=True)
        and all(after[name] == raw for name, raw in before.items() if name != SOURCES[language]),
        'counterfactual-root-only-change')
    current = verify_inputs(app, language)
    require(current is not None and current.identity == identity, 'counterfactual-accepted-inputs-drift')
    return {**value, 'reached': True, 'expectedResult': [{'ok': 'api|' + language + '|unsupported'}],
        'acceptedInputIdentity': identity}


INITIALIZATION_KINDS = {'c': 'eager-c-constructor', 'go': 'eager-package-variable',
                        'rust': 'lazy-static-during-invocation'}
C_INITIALIZER = r'''#include "lsf/text.h"
#include "api_primary.h"
static unsigned initializer_calls, greeting_calls;
static int initializer_result;
static int compatibility_root(void) __attribute__((noinline));
static int compatibility_root(void) { return outside_api_primary(); }
static void compatibility_initialize(void) __attribute__((constructor, noinline));
static void compatibility_initialize(void) {
    if (++initializer_calls != 1) __builtin_trap();
    initializer_result = compatibility_root() == 1 ? 42 : -1;
}
bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *value,
                                         probe_string_t *error) {
    (void)error;
    if (++greeting_calls != 1 || initializer_calls != 1 || initializer_result != 42)
        __builtin_trap();
    probe_string_free(name);
    probe_string_dup(value, "api|c|initialization|unsupported|result=42|count=1");
    return true;
}
'''
GO_INITIALIZER = r'''package export_examples_greeting_api
import (
    primary "outside.example.test/api-primary"
    wit "go.bytecodealliance.org/pkg/wit/types"
)
var initializerCalls, greetingCalls int
var initializerResult = compatibilityInitialize()
//go:noinline
func compatibilityRoot() int32 { return primary.Probe() }
//go:noinline
func compatibilityInitialize() int32 {
    initializerCalls++
    if initializerCalls != 1 || compatibilityRoot() != 1 { panic("api-fixture-initialization") }
    return 42
}
func Greet(_ string) wit.Result[string, string] {
    greetingCalls++
    if greetingCalls != 1 || initializerCalls != 1 || initializerResult != 42 {
        panic("api-fixture-initialization-state")
    }
    return wit.Ok[string, string]("api|go|initialization|unsupported|result=42|count=1")
}
'''
RUST_INITIALIZER = r'''use std::sync::{LazyLock, atomic::{AtomicU32, Ordering}};
static INITIALIZER_CALLS: AtomicU32 = AtomicU32::new(0);
static GREETING_CALLS: AtomicU32 = AtomicU32::new(0);
static INITIALIZER_RESULT: LazyLock<i32> = LazyLock::new(|| {
    assert_eq!(INITIALIZER_CALLS.fetch_add(1, Ordering::SeqCst), 0, "api-fixture-initialization-count");
    assert_eq!(compatibility_root(), 1, "api-fixture-initialization-result");
    42
});
#[inline(never)]
#[no_mangle]
fn compatibility_root() -> i32 { outside_api_primary::probe() }
pub fn greet(_name: String) -> Result<String, String> {
    assert_eq!(GREETING_CALLS.fetch_add(1, Ordering::SeqCst), 0, "api-fixture-initialization-state");
    let first = *LazyLock::force(&INITIALIZER_RESULT);
    let second = *LazyLock::force(&INITIALIZER_RESULT);
    assert_eq!(first, 42);
    assert_eq!(second, 42);
    assert_eq!(INITIALIZER_CALLS.load(Ordering::SeqCst), 1);
    Ok("api|rust|initialization|unsupported|result=42|count=1".into())
}
'''


def initialization_source(language: str) -> bytes:
    """Caught Unsupported initializer completion, not initializer failure.

    C and Go are eager language initializers. Rust is explicitly lazy static
    initialization during invocation; forcing twice must execute only once.
    No API call is added to the ordinary greeting body itself.
    """
    require(language in LANGUAGES, 'initialization-language')
    source = {'c': C_INITIALIZER, 'go': GO_INITIALIZER, 'rust': RUST_INITIALIZER}[language]
    if language == 'rust':
        # Retain the exact canonical component wrapper, including its cfg.
        anchor = '#[cfg(target_arch = "wasm32")]\n'
        require(RUST.count(anchor) == 1, 'original-component-wrapper')
        source += RUST[RUST.index(anchor):]
    return source.encode()


def initializer(value: dict) -> dict:
    """Third variant in the same positively reached, reviewed application.

    Accepted dependency objects are rechecked but never re-resolved. Only the
    original rootSource changes; the two actual captured libraries and all
    SDK/WIT/grants/limits/manifest identities remain the original selection.
    """
    from tools.application_dependencies import verify_inputs
    language = value['language']
    require(language in LANGUAGES and value['reached'] is True, 'reached-selection')
    app, root = Path(value['projectPath']), Path(value['ownedRoot'])
    require(app == root / 'project' and value['rootSource'] == SOURCES[language]
        and Path(value['libraries']) == root / 'libraries', 'owned-paths')
    require(value['libraryIdentity'] == digest(inventory(library_sources(language))), 'library-identity-drift')
    before = snapshot(app)
    require(before.get(SOURCES[language]) == application_source(language, reached=True), 'reached-source-drift')
    accepted = verify_inputs(app, language)
    require(accepted is not None, 'accepted-dependency-inputs-required')
    identity = accepted.identity
    require(value.get('acceptedInputIdentity', identity) == identity, 'accepted-dependency-identity-drift')
    selected = app / SOURCES[language]
    source = initialization_source(language)
    selected.write_bytes(source)
    after = snapshot(app)
    require(set(after) == set(before) and after[SOURCES[language]] == source
        and all(after[name] == raw for name, raw in before.items() if name != SOURCES[language]),
        'initializer-root-only-change')
    current = verify_inputs(app, language)
    require(current is not None and current.identity == identity, 'initializer-accepted-inputs-drift')
    return {**value, 'expectedResult': [{'ok': 'api|' + language +
        '|initialization|unsupported|result=42|count=1'}],
        'expectedScope': 'reached-unsupported-during-initialization/fallback',
        'initializationKind': INITIALIZATION_KINDS[language], 'initializerExpectedCount': 1,
        'acceptedInputIdentity': identity}
