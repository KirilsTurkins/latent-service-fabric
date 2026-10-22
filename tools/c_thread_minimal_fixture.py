"""Minimal ordinary children alongside unchanged original C workers; diagnostic only."""
from pathlib import Path
import hashlib
from tools import c_thread_runtime_fixture as original
from tools.rust_capsule_project import ROOT, read_file

BASE_SHA256='952ea08c07bee537511a0746c572367879029e2c2576a65b43af00b764453edc'
MODES=('application-error','minimal-c11','minimal-pthread','c11','pthread')
FUNCTIONS=b"""
/* Diagnostic-only child bodies: no TLS/key/errno/self-join/observe assertions.
 * The original maintained thread trampoline, TLS finish and frame retirement
 * still run, and the caller still performs ordinary join before returning. */
static volatile unsigned minimal_entered;
static void *minimal_pthread(void *argument) {
    ++minimal_entered;
    return argument;
}
static int minimal_c11(void *argument) {
    ++minimal_entered;
    return *(const int *)argument;
}
"""
CASES=b"""
    if (mode(input, "minimal-pthread") || mode(input, "minimal-c11")) {
        int argument = 42;
        unsigned entered_after_create;
        require(minimal_entered == 0);
        if (mode(input, "minimal-pthread")) {
            pthread_t child;
            void *actual = NULL;
            require(pthread_create(&child, NULL, minimal_pthread, &argument) == 0);
            entered_after_create = minimal_entered;
            require(entered_after_create <= 1 && errno == 23);
            require(!pthread_equal(child, root_id));
            require(pthread_join(child, &actual) == 0 && actual == &argument);
        } else {
            thrd_t child;
            int actual = 0;
            require(thrd_create(&child, minimal_c11, &argument) == thrd_success);
            entered_after_create = minimal_entered;
            require(entered_after_create <= 1 && errno == 23);
            require(!thrd_equal(child, thrd_current()));
            require(thrd_join(child, &actual) == thrd_success && actual == 42);
        }
        require(minimal_entered == 1 && entered == 0 && destructed == 0);
        require(root_frame == 0x744 && local == 70 && errno == 23);
        require(pthread_getspecific(key) == (void *)(uintptr_t)77);
        require(pthread_setspecific(key, NULL) == 0 && pthread_key_delete(key) == 0);
        probe_string_dup(result, mode(input, "minimal-pthread")
            ? (entered_after_create == 0 ? "minimal-pthread:42:1:create=0" : "minimal-pthread:42:1:create=1")
            : (entered_after_create == 0 ? "minimal-c11:42:1:create=0" : "minimal-c11:42:1:create=1"));
        probe_string_free(input);
        return true;
    }
"""

def selected_source(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest()!=BASE_SHA256:
        raise ValueError('c-minimal-original-main-preimage')
    first=b'static int c11_worker(void *argument) { return (int)(uintptr_t)worker(argument); }\n'
    second=b'    unsigned children = 1;\n'
    if raw.count(first)!=1 or raw.count(second)!=1:
        raise ValueError('c-minimal-exact-two-insertion-sites')
    return raw.replace(first,first+FUNCTIONS,1).replace(second,CASES+second,1)

def prepare(directory:Path)->Path:
    app=original.prepare(directory)
    main=read_file(ROOT/(original.FIXTURE+'main.c'))
    (app/'src/main.c').write_bytes(selected_source(main))
    return app
