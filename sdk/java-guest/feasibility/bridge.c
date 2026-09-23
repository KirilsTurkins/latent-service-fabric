/* Only the smoke bridge is handwritten. Canonical ABI comes from current
 * wit-bindgen C, never the removed TeaVM-WASI generator. This is not the typed
 * Java binding generator required by #548. */
#include "probe.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

extern int main(int argc, char **argv);
extern int64_t lsf_java_identity(int64_t value);
extern int32_t lsf_java_smoke(void);
static bool initialized;

static void initialize(void) {
    if (!initialized) {
        initialized = true;
        if (main(0, NULL) != 0) __builtin_trap();
    }
}

int64_t exports_tests_java_feasibility_probe_identity(int64_t value) {
    initialize();
    return lsf_java_identity(value);
}

uint32_t exports_tests_java_feasibility_probe_smoke(void) {
    initialize();
    return (uint32_t) lsf_java_smoke();
}
