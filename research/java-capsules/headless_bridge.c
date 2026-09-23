/* Research reactor bridge. The application and GC remain TeaVM-generated Java. */
#define TEAVM_CUSTOM_LOG 1
#include "all.c"

/* Standard I/O is outside this profile. Never install WASI or fake a write. */
void teavm_printString(char16_t* value) { (void) value; __builtin_trap(); }
void teavm_printWString(wchar_t* value) { (void) value; __builtin_trap(); }
void teavm_printInt(int32_t value) { (void) value; __builtin_trap(); }
void teavm_logCodePoint(int32_t value) { (void) value; __builtin_trap(); }

static int lsf_java_initialized;

__attribute__((export_name("latent:java-probe/probe@1.0.0#run")))
int64_t lsf_probe_run(int64_t seed) {
    if (!lsf_java_initialized) {
        /* A trapping initialization poisons this instance: discard, never retry. */
        lsf_java_initialized = 1;
        lsf_java_initialize();
        lsf_java_initialized = 2;
    }
    if (lsf_java_initialized != 2) __builtin_trap();
    return java_probe(seed);
}
